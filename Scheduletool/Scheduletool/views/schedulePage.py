import json
import threading

from flask import Blueprint, session, redirect,render_template,request,jsonify
from utils import db
import numpy as np
try:
    from ..result import readEP
    _READEP_IMPORT_ERROR = None
except Exception as _e:
    readEP = None
    _READEP_IMPORT_ERROR = str(_e)
import pandas as pd
import os
import random
import datetime
from bson import ObjectId

from ..result.paintGantt import paintGantt

schePage=Blueprint('schedulePage',__name__)

# KDCEA 运行状态跟踪
_kdcea_state = {
    'status': 'idle',   # idle | running | completed | failed | cancelled
    'message': '',
    'thread': None,
}
_kdcea_lock = threading.Lock()


def _ensure_demo_data():
    try:
        from utils.demo_seed import ensure_demo_data

        ensure_demo_data()
    except Exception:
        pass


def _ensure_read_ep_loaded():
    """Delay heavy readEP initialization until route call time."""
    global readEP, _READEP_IMPORT_ERROR
    if readEP is not None:
        return True, None
    try:
        from ..result import readEP as _readEP_module
        readEP = _readEP_module
        _READEP_IMPORT_ERROR = None
        return True, None
    except Exception as e:
        _READEP_IMPORT_ERROR = str(e)
        return False, _READEP_IMPORT_ERROR


# --- Travel time matrix (fuzzy) helpers ---
def _sort_customer_key(c):
    """
    尽量按 customer_id 的数字尾部排序，避免 CUST-10 < CUST-2 这种字符串顺序问题。
    退化为按 customer_id 字符串排序。
    """
    raw = c.get('customer_id')
    cid = '' if raw is None else str(raw)
    # 抽取末尾数字
    num = None
    i = len(cid) - 1
    while i >= 0 and cid[i].isdigit():
        i -= 1
    if i < len(cid) - 1:
        try:
            num = int(cid[i + 1:])
        except Exception:
            num = None
    if num is not None:
        return (0, num, cid)
    return (1, cid)


def _default_triple(value=None):
    # value=None 表示未填写；0 表示明确为 0
    if value is None:
        return [None, None, None]
    return [value, value, value]


def _normalize_triple(triple):
    # triple -> [min, avg, max] 允许 None
    if triple is None:
        return [None, None, None]
    if not isinstance(triple, (list, tuple)) or len(triple) != 3:
        return [None, None, None]
    out = []
    for v in triple:
        if v is None or v == '':
            out.append(None)
        else:
            try:
                out.append(float(v))
            except Exception:
                out.append(None)
    return out


def _is_factory_id(customer_id):
    """工厂的 customer_id 为 0，兼容 0、'0'、0.0 等存储方式。"""
    if customer_id is None:
        return False
    s = str(customer_id).strip()
    if s == '0':
        return True
    try:
        return float(customer_id) == 0
    except (TypeError, ValueError):
        return False


def _customer_id_match_query(customer_id):
    """兼容 customer_id 在库中可能是 int 或 str 的情况。"""
    candidates = [customer_id]
    try:
        candidates.append(int(customer_id))
    except (TypeError, ValueError):
        pass
    # 去重并保持顺序
    uniq = []
    for x in candidates:
        if x not in uniq:
            uniq.append(x)
    if len(uniq) == 1:
        return {'customer_id': uniq[0]}
    return {'customer_id': {'$in': uniq}}


def _ensure_default_factory():
    """
    确保 customerinfo 中至少存在一个工厂（customer_id=0）。
    若缺失则自动创建一个默认工厂记录。
    """
    customers = db.fetch_all('customerinfo', {}) or []
    if any(_is_factory_id(c.get('customer_id')) for c in customers):
        return
    default_factory = {
        'customer_id': 0,
        'customer_name': '海尔胶州智慧物流园',
        'address_X': 0.0,
        'address_Y': 0.0
    }
    db.create('customerinfo', default_factory)


def _load_customers_sorted():
    _ensure_default_factory()
    customers = db.fetch_all('customerinfo', {}) or []
    customers = [c for c in customers if c.get('customer_id') is not None]
    customers.sort(key=_sort_customer_key)
    return customers


def _get_or_migrate_travel_matrix():
    """
    返回与当前 customer 列表一致的矩阵结构；如数据库中已有旧矩阵，则做增删迁移并回写。
    结构：
    {
      matrix_id: "default",
      customer_ids: [...],
      factory_to: [ [min,avg,max], ... ] length n
      retail_to:  [ [ [min,avg,max], ... ] * n ] * n
    }
    """
    customers = _load_customers_sorted()
    customer_ids = [str(c['customer_id']) for c in customers]

    coll = 'travel_time_matrix'
    matrix_id = 'default'
    docs = db.fetch_all(coll, {'matrix_id': matrix_id}) or []
    doc = docs[0] if docs else None

    n = len(customer_ids)

    # 构建一个新的默认矩阵
    new_doc = {
        'matrix_id': matrix_id,
        'customer_ids': list(customer_ids),
        'factory_to': [_default_triple(None) for _ in range(n)],
        'retail_to': [[_default_triple(0 if i == j else None) for j in range(n)] for i in range(n)]
    }

    if not doc:
        # 首次创建（upsert）
        db.update(coll, {'matrix_id': matrix_id}, new_doc, upsert=True)
        return customers, new_doc

    old_ids = [str(x) for x in (doc.get('customer_ids') or [])]
    old_factory = doc.get('factory_to') or []
    old_retail = doc.get('retail_to') or []

    old_index = {cid: idx for idx, cid in enumerate(old_ids)}

    # 迁移：复制仍存在的客户对应的数据
    for new_j, cid_to in enumerate(customer_ids):
        old_j = old_index.get(cid_to)
        if old_j is not None and old_j < len(old_factory):
            new_doc['factory_to'][new_j] = _normalize_triple(old_factory[old_j])

    for new_i, cid_from in enumerate(customer_ids):
        old_i = old_index.get(cid_from)
        for new_j, cid_to in enumerate(customer_ids):
            old_j = old_index.get(cid_to)
            if old_i is not None and old_j is not None:
                try:
                    new_doc['retail_to'][new_i][new_j] = _normalize_triple(old_retail[old_i][old_j])
                except Exception:
                    pass

    # 强制对角线为 0
    for i in range(n):
        new_doc['retail_to'][i][i] = _default_triple(0)

    # 强制对称（零售商-零售商）
    for i in range(n):
        for j in range(i + 1, n):
            a = _normalize_triple(new_doc['retail_to'][i][j])
            b = _normalize_triple(new_doc['retail_to'][j][i])
            # 优先用 a；若 a 全空则用 b
            if all(v is None for v in a) and not all(v is None for v in b):
                a = b
            new_doc['retail_to'][i][j] = a
            new_doc['retail_to'][j][i] = a

    # 若 customer_ids 有变化或内容被规范化，回写
    should_write = (old_ids != customer_ids)
    if not should_write:
        # 简单比较一下长度，避免遗漏变化
        try:
            should_write = (len(old_factory) != n) or (len(old_retail) != n)
        except Exception:
            should_write = True

    if should_write:
        db.update(coll, {'matrix_id': matrix_id}, new_doc, upsert=True)

    return customers, new_doc


def _next_order_id():
    today = datetime.datetime.now()
    prefix = today.strftime('%y%m%d')
    try:
        existing = db.fetch_all('orderinfo', {'order_id': {'$regex': f'^{prefix}'}})
        max_seq = 0
        for r in existing:
            oid = r.get('order_id', '')
            if isinstance(oid, str) and oid.startswith(prefix):
                suf = oid[len(prefix):]
                if suf.isdigit():
                    num = int(suf)
                    if num > max_seq:
                        max_seq = num
        seq = max_seq + 1
    except Exception:
        seq = 1
    return f"{prefix}{seq:04d}"


def _to_float_or_none(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_datetime_or_none(v):
    """解析 datetime-local/ISO 字符串，失败返回 None。"""
    if v is None or v == '':
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace('Z', '')
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _infer_delivery_time_type(start, end, explicit_mode=None):
    """
    返回 numeric | datetime | None。
    explicit_mode 仅允许 numeric/datetime，非法值会被忽略并走自动识别。
    """
    mode = str(explicit_mode).strip().lower() if explicit_mode is not None else ''
    if mode in ('numeric', 'datetime'):
        return mode
    is_numeric = (_to_float_or_none(start) is not None) and (_to_float_or_none(end) is not None)
    if is_numeric:
        return 'numeric'
    is_datetime = (_parse_datetime_or_none(start) is not None) and (_parse_datetime_or_none(end) is not None)
    if is_datetime:
        return 'datetime'
    return None


def _resolve_order_delivery_type(order_doc):
    """读取订单交付期限类型；旧数据无类型字段时自动推断。"""
    explicit_mode = order_doc.get('delivery_time_type')
    start = order_doc.get('order_time_start')
    end = order_doc.get('order_time_end')
    return _infer_delivery_time_type(start, end, explicit_mode=explicit_mode)



@schePage.route('/schedulePage/dataShow',methods=['GET','POST'])
def dataShow():
    # data_list=db.fetch_all("select * from orderinfo",[])

    return render_template("schedulePage.html")
    #读取数据

#展示pareto前沿
@schePage.route('/schedulePage/paretoShow',methods=['GET','POST'])
def paretoShow():
    ok, err = _ensure_read_ep_loaded()
    if not ok:
        return jsonify({"success": False, "message": f"读取排程结果失败: {err}"}), 500

    solutions = []
    ep = readEP.getEp()
    epsize = ep.shape[0]
    for i in range(epsize):
        infos,infos_2=readEP.readinf(i)
        solutions.append({
            "cost": ep[i, 0],
            "time": ep[i, 1],
            "id": i + 1,
            "time_rank": ep[i, 3],
            "cost_rank": ep[i, 2],
            "info":infos_2
        })
    # print(111111111111111111111111111222)
    result=jsonify(solutions)
    return jsonify(solutions)


@schePage.route('/schedulePage/optimization_summary', methods=['GET'])
def optimization_summary():
    """大屏状态：说明当前 Pareto 解来源及 KDCEA 运行状态。"""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    result_dir = os.path.join(base_dir, 'result')
    metrics_path = os.path.join(result_dir, 'metrics.json')
    batch_ids_path = os.path.join(result_dir, 'excel', 'last_batch_order_ids.json')

    last_run_at = None
    if os.path.isfile(metrics_path):
        try:
            last_run_at = datetime.datetime.fromtimestamp(
                os.path.getmtime(metrics_path)
            ).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            last_run_at = None

    batch_order_count = 0
    if os.path.isfile(batch_ids_path):
        try:
            with open(batch_ids_path, 'r', encoding='utf-8') as f:
                ids = json.load(f)
            batch_order_count = len(ids) if isinstance(ids, list) else 0
        except Exception:
            batch_order_count = 0

    pareto_count = 0
    ep_ok, ep_err = _ensure_read_ep_loaded()
    if ep_ok:
        try:
            pareto_count = int(readEP.getEp().shape[0])
        except Exception:
            pareto_count = 0

    with _kdcea_lock:
        kdcea_status = _kdcea_state.get('status') or 'idle'
        kdcea_message = _kdcea_state.get('message') or ''

    return jsonify({
        'kdcea_status': kdcea_status,
        'kdcea_message': kdcea_message,
        'pareto_count': pareto_count,
        'last_run_at': last_run_at,
        'batch_order_count': batch_order_count,
        'has_results': pareto_count > 0,
        'trigger_hint': '订单管理 → 勾选订单 → 批量处理（启动 KDCEA 求解）',
    })

# 展示甘特图
@schePage.route('/schedulePage/gantt_png/<int:solution_id>')
def get_gantt_png(solution_id):
    """直接返回 PNG，供 <img src> 加载（避免大 JSON + data URL）。"""
    import base64
    import traceback
    from flask import Response

    try:
        ok, err = _ensure_read_ep_loaded()
        if not ok:
            return Response(f'读取排程结果失败: {err}', status=500, mimetype='text/plain; charset=utf-8')

        index = solution_id - 1
        ep = readEP.getEp()
        epsize = ep.shape[0]
        if index < 0 or index >= epsize:
            return Response(f'无效的解ID: {solution_id}', status=404, mimetype='text/plain; charset=utf-8')

        image_base64 = paintGantt(index)
        if not image_base64:
            return Response('图片生成失败', status=500, mimetype='text/plain; charset=utf-8')

        return Response(base64.b64decode(image_base64), mimetype='image/png')
    except Exception as e:
        print(f"[gantt_png] solution_id={solution_id}: {e}")
        print(traceback.format_exc())
        return Response('图片生成失败: ' + str(e), status=500, mimetype='text/plain; charset=utf-8')


@schePage.route('/schedulePage/get_gantt_image/<int:solution_id>')
def get_gantt_image_via_schedule_page(solution_id):
    return get_gantt_image(solution_id)


@schePage.route('/get_gantt_image/<int:solution_id>')
def get_gantt_image(solution_id):
    try:
        ok, err = _ensure_read_ep_loaded()
        if not ok:
            raise RuntimeError(f"读取排程结果失败: {err}")

        # solution_id 为 1,2,3,...，需要转成 0,1,2,...
        index = solution_id - 1

        # 防止越界：根据 EP 的大小检查
        ep = readEP.getEp()
        epsize = ep.shape[0]
        if index < 0 or index >= epsize:
            raise ValueError(f"无效的解ID: {solution_id}，有效范围为 1~{epsize}")

# 打印：前端看到的解ID + 排序后目标值
        print(f"[get_gantt_image] solution_id={solution_id}, sorted_index={index}, "
              f"cost={ep[index,0]}, time={ep[index,1]}")


        image_base64 = paintGantt(index)
        if not image_base64:  # 若生成失败，image_base64可能为空
            raise ValueError("图片生成失败")

        return jsonify({'image': image_base64})

    except Exception as e:
        # 打印详细错误信息到后端日志，便于调试
        import traceback
        print(f"生成甘特图失败 (solution_id={solution_id}): {str(e)}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': '图片生成失败：' + str(e)}), 500

# API: 获取订单列表
# @schePage.route('/schedulePage/get_orders', methods=['GET'])
# def get_orders():
#     # 支持按零售商过滤（通过 query param customer_id）
#     customer_id = request.args.get('customer_id')

#     # 使用 MongoDB 的聚合查询将 orderinfo、order_items、productinf、customerinfo 关联起来
#     pipeline = [
#         # 可选的 match 阶段，先按客户过滤可以减少后续关联数据量
#         *( [{"$match": {"customer_id": customer_id}}] if customer_id else [] ),
#         {"$lookup": {
#             "from": "order_items",
#             "localField": "order_id",
#             "foreignField": "order_id",
#             "as": "items"
#         }},
#         {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": True}},
#         {"$lookup": {
#             "from": "productinf",
#             "localField": "items.product_id",
#             "foreignField": "product_id",
#             "as": "product_info"
#         }},
#         {"$unwind": {"path": "$product_info", "preserveNullAndEmptyArrays": True}},
#         {"$lookup": {
#             "from": "customerinfo",
#             "localField": "customer_id",
#             "foreignField": "customer_id",
#             "as": "customer_info"
#         }},
#         {"$unwind": {"path": "$customer_info", "preserveNullAndEmptyArrays": True}},
#         {"$project": {
#             "order_id": 1,
#             "order_time_start": 1,
#             "order_time_end": 1,
#             "customer_name": "$customer_info.customer_name",
#             "product_id": "$items.product_id",
#             "product_name": "$product_info.product_name",
#             "quantity": "$items.quantity"
#         }}
#     ]

#     results = db.aggregate('orderinfo', pipeline)

#     # 将聚合结果按 order_id 组织成一个含 products 列表的结构
#     order_dict = {}
#     for row in results:
#         order_number = row.get('order_id')
#         if order_number not in order_dict:
#             order_dict[order_number] = {
#                 'order_info': {
#                     'order_id': order_number,
#                     'order_startdate': row.get('order_time_start'),
#                     'order_enddate': row.get('order_time_end'),
#                     'customer_name': row.get('customer_name')
#                 },
#                 'products': []
#             }

#         if row.get('product_id') is not None:
#             order_dict[order_number]['products'].append({
#                 'product_name': row.get('product_name'),
#                 'quantity': row.get('quantity')
#             })

#     orders = list(order_dict.values())
#     return json.dumps(orders, ensure_ascii=False, indent=2)
# API: 获取订单列表
@schePage.route('/schedulePage/get_orders', methods=['GET'])
def get_orders():
    _ensure_demo_data()
    # 支持按零售商过滤（通过 query param customer_id）；分页：page（从1开始）、per_page（默认10）
    customer_id = request.args.get('customer_id')
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(100, int(request.args.get('per_page', 10))))
    except (TypeError, ValueError):
        per_page = 10

    # 调试打印：记录接收到的参数
    try:
        print(f"[get_orders] received customer_id={customer_id}, page={page}, per_page={per_page}")
    except Exception:
        pass

    # 兼容 customer_id 在库中可能是 int 或 str：前端 query string 统一按兼容查询匹配
    customer_match = _customer_id_match_query(customer_id) if customer_id else None

    # 使用 MongoDB 的聚合查询将 orderinfo、order_items、productinf、customerinfo 关联起来
    pipeline = [
        # 可选的 match 阶段，先按客户过滤可以减少后续关联数据量
        *( [{"$match": customer_match}] if customer_match else [] ),
        {"$lookup": {
            "from": "order_items",
            "localField": "order_id",
            "foreignField": "order_id",
            "as": "items"
        }},
        {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "productinf",
            "let": {"pid": "$items.product_id"},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$eq": [
                            {"$toString": {"$ifNull": ["$product_id", ""]}},
                            {"$toString": {"$ifNull": ["$$pid", ""]}}
                        ]
                    }
                }}
            ],
            "as": "product_info"
        }},
        {"$unwind": {"path": "$product_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "customerinfo",
            "let": {"cid": "$customer_id"},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$eq": [
                            {"$toString": {"$ifNull": ["$customer_id", ""]}},
                            {"$toString": {"$ifNull": ["$$cid", ""]}}
                        ]
                    }
                }}
            ],
            "as": "customer_info"
        }},
        {"$unwind": {"path": "$customer_info", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "order_id": 1,
            "customer_id": 1,
            "order_time_start": 1,
            "order_time_end": 1,
            "delivery_time_type": 1,
            "customer_name": "$customer_info.customer_name",
            "product_id": "$items.product_id",
            "product_name": "$product_info.product_name",
            "quantity": "$items.quantity"
        }}
    ]

    # 打印聚合管道供调试
    try:
        print(f"[get_orders] pipeline={json.dumps(pipeline, ensure_ascii=False)}")
    except Exception:
        print("[get_orders] pipeline (非可序列化对象), skipping dump")

    results = db.aggregate('orderinfo', pipeline)

    # 调试打印：聚合返回数量与前几个样例（避免打印全部数据）
    try:
        print(f"[get_orders] aggregate returned {len(results)} rows")
        sample = results[:3]
        print("[get_orders] sample:\n" + json.dumps(sample, ensure_ascii=False, default=str, indent=2))
    except Exception:
        pass

    # 将聚合结果按 order_id 组织成一个含 products 列表的结构
    order_dict = {}
    for row in results:
        order_number = row.get('order_id')
        if order_number not in order_dict:
            order_dict[order_number] = {
                'order_info': {
                    'order_id': order_number,
                    'order_number': order_number,
                    'customer_id': row.get('customer_id'),
                    'order_startdate': row.get('order_time_start'),
                    'order_enddate': row.get('order_time_end'),
                    'delivery_time_type': _infer_delivery_time_type(
                        row.get('order_time_start'),
                        row.get('order_time_end'),
                        explicit_mode=row.get('delivery_time_type')
                    ),
                    'customer_name': row.get('customer_name') or str(row.get('customer_id') or '')
                },
                'products': []
            }

        if row.get('product_id') is not None:
            order_dict[order_number]['products'].append({
                'product_id': row.get('product_id'),
                'product_name': row.get('product_name') or str(row.get('product_id') or ''),
                'quantity': row.get('quantity')
            })

    orders_all = list(order_dict.values())
    total = len(orders_all)
    start = (page - 1) * per_page
    end = start + per_page
    orders = orders_all[start:end]
    return jsonify({'orders': orders, 'total': total})

# API: 删除单个订单（并删除关联的 order_items）
@schePage.route('/schedulePage/delete_order/<order_id>', methods=['DELETE'])
def delete_order(order_id):
    try:
        deleted = db.delete('orderinfo', {'order_id': order_id})
        # 删除关联的 order_items
        db.delete_many('order_items', {'order_id': order_id})
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# API: 获取客户列表（供下拉）
@schePage.route('/schedulePage/get_customers', methods=['GET'])
def get_customers():
    customers = db.fetch_all('customerinfo', {})
    # 返回 customer_id/customer_name，并带上是否工厂标记（customer_id 为 0）
    simplified = []
    for c in customers:
        cid = c.get('customer_id')
        simplified.append({
            'customer_id': cid,
            'customer_name': c.get('customer_name'),
            'is_factory': _is_factory_id(cid)
        })
    return jsonify(simplified)


# API: 获取产品列表（供下拉）
@schePage.route('/schedulePage/get_products', methods=['GET'])
def get_products():
    try:
        products = db.fetch_all('productinf', {})
        try:
            print(f"[list_products] 返回 {len(products)} 条产品数据")
            if len(products) > 0:
                sample_keys = set().union(*(p.keys() for p in products))
                print(f"[list_products] 示例字段: {list(sample_keys)[:10]}")
        except Exception:
            pass
        # 返回完整文档，便于前端显示所有字段
        return jsonify(products)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# API: 创建订单（接收 JSON）
@schePage.route('/schedulePage/create_order', methods=['POST'])
def create_order():
    data = request.get_json() or {}

    # 支持两种前端字段格式：
    # 1) customer_id, order_time_start, order_time_end, items([{product_id, quantity}])
    # 2) retailer, deliveryStart, deliveryEnd, delivery_time_type, products([{product_name, quantity}])
    cust_id = data.get('customer_id') or data.get('retailer')
    start = data.get('order_time_start') or data.get('deliveryStart') or data.get('orderDate')
    end = data.get('order_time_end') or data.get('deliveryEnd')
    items = data.get('items') or data.get('products') or []
    explicit_mode = data.get('delivery_time_type') or data.get('deliveryInputMode')

    # 调试日志：打印接收到的 items，便于排查前端传参格式
    try:
        print(f"[create_order] received items: {items}")
    except Exception:
        pass

    if not cust_id or start in (None, '') or end in (None, ''):
        return jsonify({'success': False, 'message': '缺少订单必要字段'}), 400

    delivery_mode = _infer_delivery_time_type(start, end, explicit_mode=explicit_mode)
    if delivery_mode is None:
        return jsonify({
            'success': False,
            'message': '交付期限格式不正确：请同时输入纯数字（小时）或同时输入具体时间'
        }), 400

    if delivery_mode == 'numeric':
        start_num = _to_float_or_none(start)
        end_num = _to_float_or_none(end)
        if start_num is None or end_num is None:
            return jsonify({'success': False, 'message': '纯数字交付期限必须是有效数字'}), 400
        if start_num > end_num:
            return jsonify({'success': False, 'message': '交付期限开始值不能大于结束值'}), 400
        normalized_start = start_num
        normalized_end = end_num
    else:
        start_dt = _parse_datetime_or_none(start)
        end_dt = _parse_datetime_or_none(end)
        if start_dt is None or end_dt is None:
            return jsonify({'success': False, 'message': '具体时间交付期限格式不正确'}), 400
        if start_dt > end_dt:
            return jsonify({'success': False, 'message': '交付期限开始时间不能晚于结束时间'}), 400
        normalized_start = start_dt.strftime('%Y-%m-%dT%H:%M')
        normalized_end = end_dt.strftime('%Y-%m-%dT%H:%M')

    # 生成规则：YYMMDD + 4位序号（当天从0001开始）
    order_id = _next_order_id()

    order_doc = {
        'order_id': order_id,
        'customer_id': cust_id,
        'order_time_start': normalized_start,
        'order_time_end': normalized_end,
        'delivery_time_type': delivery_mode
    }

    db.create('orderinfo', order_doc)
    # 插入 order_items，兼容 product_id 或 product_name 字段
    items_docs = []
    for it in items:
        product_id = it.get('product_id') or None
        quantity = it.get('quantity') or it.get('qty') or it.get('number') or 0
        pname = it.get('product_name') or None

        # 如果前端只传了 product_name，尝试在 productinf 中查找对应的 product_id
        if not product_id and pname:
            matches = db.fetch_all('productinf', {'product_name': pname})
            if matches and len(matches) > 0:
                product_id = matches[0].get('product_id')

        # 如果传了 product_id 但在 productinf 中找不到，可能前端把 product_name 误放在 value 中，尝试按 product_name 匹配
        if product_id:
            try:
                exists = db.fetch_all('productinf', {'product_id': product_id})
                if not exists and not pname:
                    # 尝试按 product_name 查找
                    alt = db.fetch_all('productinf', {'product_name': product_id})
                    if alt and len(alt) > 0:
                        product_id = alt[0].get('product_id')
                        pname = alt[0].get('product_name')
            except Exception:
                pass

        if not product_id:
            # 找不到 product_id：回滚并报错（不保存 product_name）
            try:
                db.delete('orderinfo', {'order_id': order_id})
            except Exception:
                pass
            try:
                print(f"[create_order] error: product_id not found for item={it}")
            except Exception:
                pass
            return jsonify({'success': False, 'message': f'商品无法识别: {pname or product_id}'}), 400

        items_docs.append({
            'order_items_id': f"OI-{order_id}-{product_id}",
            'order_id': order_id,
            'product_id': product_id,
            'quantity': int(quantity)
        })

    if not items_docs:
        # 没有有效的商品项，回滚已创建的 orderinfo 并返回错误
        try:
            db.delete('orderinfo', {'order_id': order_id})
        except Exception:
            pass
        return jsonify({'success': False, 'message': '没有有效的商品项，订单未保存'}), 400

    try:
        db.create('order_items', items_docs)
    except Exception as e:
        # 插入 order_items 失败，回滚 orderinfo
        try:
            db.delete('orderinfo', {'order_id': order_id})
        except Exception:
            pass
        print(f"[create_order] failed to insert order_items for {order_id}: {e}")
        return jsonify({'success': False, 'message': '保存订单项失败，已回滚订单'}), 500

    return jsonify({'success': True, 'order_id': order_id}), 201


@schePage.route('/schedulePage/next_order_id', methods=['GET'])
def next_order_id_api():
    try:
        nid = _next_order_id()
        return jsonify({'success': True, 'order_id': nid})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# API: 批量删除订单（并删除关联的 order_items）
@schePage.route('/schedulePage/orders/batch_delete', methods=['POST'])
def batch_delete_orders():
    data = request.get_json() or {}
    order_ids = data.get('order_ids', [])
    if not order_ids:
        return jsonify({'success': False, 'message': '没有提供要删除的订单'}), 400

    deleted_count = 0
    for oid in order_ids:
        deleted_count += db.delete('orderinfo', {'order_id': oid})
        db.delete_many('order_items', {'order_id': oid})

    return jsonify({'success': True, 'deleted_orders': deleted_count})


# API: 批量处理选中订单并导出到 Excel（retailsneed.xlsx）
@schePage.route('/schedulePage/orders/batch_process', methods=['POST'])
def batch_process_orders():
    data = request.get_json() or {}
    order_ids = data.get('order_ids', [])
    schedule_start_raw = data.get('schedule_start')
    if not order_ids:
        return jsonify({'success': False, 'message': '没有提供要处理的订单'}), 400

    try:
        # 调试：打印收到的订单ID
        try:
            print(f"[batch_process] received order_ids={order_ids}")
        except Exception:
            pass

        # 获取产品列表，确定列顺序：严格按照 product_id 升序
        products = db.fetch_all('productinf', {}) or []

        # 将 productinf 映射为 {product_id: name}
        product_meta = {}
        for p in products:
            pid = p.get('product_id')
            if pid is None:
                continue
            pid_str = str(pid)
            product_meta[pid_str] = {
                'name': p.get('product_name') or pid_str,
            }

        # 一次性读取所有选中订单信息，避免逐个精确匹配导致类型问题（如字符串/数字）
        # 为兼容数据库中 order_id 可能是数字类型的情况，构造同时包含字符串和数字的 ID 列表
        mixed_ids = list(order_ids)
        for oid in order_ids:
            try:
                num_id = int(oid)
                mixed_ids.append(num_id)
            except Exception:
                # 非纯数字 ID，忽略数值形式
                pass

        orders_docs = db.fetch_all('orderinfo', {'order_id': {'$in': mixed_ids}}) or []
        # 以字符串化的 order_id 作为 key，兼容数据库中可能的类型差异
        orders_by_id = {str(o.get('order_id')): o for o in orders_docs if o.get('order_id') is not None}
        try:
            print(f"[batch_process] loaded {len(orders_by_id)} orders from DB")
            print(f"[batch_process] selected_ids={order_ids}")
            print(f"[batch_process] db_order_ids={list(orders_by_id.keys())[:10]}")
        except Exception:
            pass

        # 一次性读取所有相关的 order_items，并按订单分组（同样使用混合类型 ID）
        items_docs = db.fetch_all('order_items', {'order_id': {'$in': mixed_ids}}) or []
        order_items_map = {}
        for it in items_docs:
            oid = str(it.get('order_id'))
            if oid not in order_items_map:
                order_items_map[oid] = []
            order_items_map[oid].append(it)

        valid_orders = []
        for oid in order_ids:
            oid_str = str(oid)
            order_doc = orders_by_id.get(oid_str)
            if not order_doc:
                try:
                    print(f"[batch_process] order_id={oid_str} not found in orders_by_id")
                except Exception:
                    pass
                continue
            valid_orders.append((oid_str, order_doc))
            items = order_items_map.get(oid_str, [])
            try:
                print(f"[batch_process] order_id={oid_str} items_count={len(items)}")
            except Exception:
                pass
            for it in items:
                pid = it.get('product_id')
                if pid is None:
                    continue
                pid_str = str(pid)
                # 若该 product_id 在 productinf 中不存在，则动态补充到 meta 中
                if pid_str not in product_meta:
                    product_meta[pid_str] = {
                        'name': pid_str,
                    }

        # 若一个有效订单都没有找到，直接返回错误，避免生成空Excel
        if not valid_orders:
            return jsonify({'success': False, 'message': '选中的订单在数据库中不存在，未生成文件'}), 400

        # 校验选中订单交付期限类型必须一致
        delivery_modes = []
        for _, order in valid_orders:
            mode = _resolve_order_delivery_type(order)
            if mode is None:
                return jsonify({
                    'success': False,
                    'error_code': 'invalid_delivery_time',
                    'message': '选中的订单存在无法识别的交付期限格式，请修正后重试'
                }), 400
            delivery_modes.append(mode)
        uniq_modes = set(delivery_modes)
        if len(uniq_modes) != 1:
            return jsonify({
                'success': False,
                'error_code': 'mixed_delivery_time_type',
                'message': '批量处理只允许选择同一种交付期限形式的订单（纯数字或具体时间）'
            }), 400
        batch_delivery_mode = delivery_modes[0]

        # 按订单顺序提取零售商（customer_id），并检查是否重复
        retailer_order = [str((o.get('customer_id') or '')) for _, o in valid_orders]
        if len(retailer_order) != len(set(retailer_order)):
            return jsonify({
                'success': False,
                'message': '选中的订单中存在重复的零售商，请勿重复选择同一零售商的订单，已取消处理。'
            }), 400

        # 提前加载旅行时间矩阵并校验：所有订单对应零售商均需在矩阵中（再写 retailsneed / traveltime）
        try:
            customers, doc = _get_or_migrate_travel_matrix()
            full_ids = [str(x) for x in (doc.get('customer_ids') or [])]
            if not full_ids:
                full_ids = [str(c.get('customer_id')) for c in customers if c.get('customer_id') is not None]
            factory_to = doc.get('factory_to') or []
            retail_to = doc.get('retail_to') or []
            customer_name_map = {
                str(c.get('customer_id')): str(c.get('customer_name') or c.get('customer_id') or '')
                for c in customers
            }

            def _is_filled_triple(triple):
                vals = _normalize_triple(triple)
                return all(v is not None for v in vals)

            batch_indices = []
            for rid in retailer_order:
                if rid not in full_ids:
                    return jsonify({
                        'success': False,
                        'message': '部分订单的零售商不在旅行时间矩阵中，请先在参数设置中维护模糊旅行时间后重试。'
                    }), 400
                batch_indices.append(full_ids.index(rid))

            # 校验是否已填写与本批次零售商相关的模糊旅行时间
            missing_factory = []
            for rid, idx in zip(retailer_order, batch_indices):
                triple = factory_to[idx] if idx < len(factory_to) else None
                if not _is_filled_triple(triple):
                    missing_factory.append(rid)

            missing_pairs = []
            for i in range(len(retailer_order)):
                ri = batch_indices[i]
                rid_i = retailer_order[i]
                for j in range(i + 1, len(retailer_order)):
                    rj = batch_indices[j]
                    rid_j = retailer_order[j]
                    cell = None
                    if ri < len(retail_to) and rj < len(retail_to[ri]):
                        cell = retail_to[ri][rj]
                    if not _is_filled_triple(cell):
                        missing_pairs.append((rid_i, rid_j))

            if missing_factory or missing_pairs:
                detail_parts = []
                if missing_factory:
                    show_factory = []
                    for rid in missing_factory[:5]:
                        cname = customer_name_map.get(rid) or rid
                        show_factory.append(f"{cname}({rid})")
                    suffix = ' 等' if len(missing_factory) > 5 else ''
                    detail_parts.append('工厂->零售商未填写: ' + '、'.join(show_factory) + suffix)
                if missing_pairs:
                    show_pairs = []
                    for rid_i, rid_j in missing_pairs[:5]:
                        ci = customer_name_map.get(rid_i) or rid_i
                        cj = customer_name_map.get(rid_j) or rid_j
                        show_pairs.append(f"{ci}({rid_i})<->{cj}({rid_j})")
                    suffix = ' 等' if len(missing_pairs) > 5 else ''
                    detail_parts.append('零售商间未填写: ' + '、'.join(show_pairs) + suffix)
                return jsonify({
                    'success': False,
                    'error_code': 'travel_time_incomplete',
                    'message': '批量处理前请先补全模糊旅行时间矩阵。' + '；'.join(detail_parts)
                }), 400
        except Exception as e_mat:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'message': '读取旅行时间矩阵失败：' + str(e_mat)}), 500

        # 根据 product_id 生成最终的列顺序（升序）
        def _pid_sort_key(pid: str):
            # 优先按能否转成数字排序，避免 '10' < '2' 这种字符串顺序问题
            try:
                return (0, int(pid))
            except Exception:
                return (1, pid)

        product_ids = sorted(product_meta.keys(), key=_pid_sort_key)
        product_names = [product_meta[pid]['name'] for pid in product_ids]

        # 构建行数据
        rows = []
        schedule_start_dt = None
        if batch_delivery_mode == 'datetime':
            if schedule_start_raw in (None, ''):
                return jsonify({
                    'success': False,
                    'error_code': 'schedule_start_required',
                    'message': '当前订单为“具体时间”交付期限，请先输入排程开始时间。请确保排程开始时间早于所有订单交付期限，并留足生产时间。'
                }), 400
            schedule_start_dt = _parse_datetime_or_none(schedule_start_raw)
            if schedule_start_dt is None:
                return jsonify({
                    'success': False,
                    'error_code': 'schedule_start_invalid',
                    'message': '排程开始时间格式错误，请使用 YYYY-MM-DDTHH:MM'
                }), 400

        for oid, order in valid_orders:
            start = order.get('order_time_start', '')
            end = order.get('order_time_end', '')
            items = order_items_map.get(oid, [])
            qty_map = {str(it.get('product_id')): int(it.get('quantity') or 0) for it in items if it.get('product_id') is not None}

            if batch_delivery_mode == 'numeric':
                start_num = _to_float_or_none(start)
                end_num = _to_float_or_none(end)
                if start_num is None or end_num is None:
                    return jsonify({
                        'success': False,
                        'error_code': 'invalid_delivery_time',
                        'message': f'订单 {oid} 的纯数字交付期限无效'
                    }), 400
                t_start, t_end = start_num, end_num
            else:
                start_dt = _parse_datetime_or_none(start)
                end_dt = _parse_datetime_or_none(end)
                if start_dt is None or end_dt is None:
                    return jsonify({
                        'success': False,
                        'error_code': 'invalid_delivery_time',
                        'message': f'订单 {oid} 的具体时间交付期限无效'
                    }), 400
                if schedule_start_dt >= start_dt or schedule_start_dt >= end_dt:
                    return jsonify({
                        'success': False,
                        'error_code': 'schedule_start_too_late',
                        'message': '排程开始时间必须早于所有订单交付期限，并留足生产时间。'
                    }), 400
                t_start = round((start_dt - schedule_start_dt).total_seconds() / 3600.0, 6)
                t_end = round((end_dt - schedule_start_dt).total_seconds() / 3600.0, 6)

            row = [qty_map.get(pid, 0) for pid in product_ids] + [t_start, t_end]
            rows.append(row)

        # 如果没有任何行（例如所有订单都没有明细），直接报错提示
        if not rows:
            return jsonify({'success': False, 'message': '选中的订单没有任何商品明细，未生成文件'}), 400

        # 调试日志：打印导出行数与列数
        try:
            print(f"[batch_process] product_count={len(product_ids)}, orders_exported={len(rows)}")
        except Exception:
            pass

        # 输出目录：Scheduletool/result/excel
        base_dir = os.path.dirname(os.path.dirname(__file__))  # package root (Scheduletool)
        out_dir = os.path.join(base_dir, 'result', 'excel')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, 'retailsneed.xlsx')
        errors = []  # 记录任一等 xlsx 生成失败时的错误信息

        # 1. 生成 retailsneed.xlsx
        try:
            columns = product_names + ['time_start', 'time_end']
            df = pd.DataFrame(rows, columns=columns)
            df.to_excel(out_path, index=False, header=False)
        except Exception as e_retail:
            import traceback
            traceback.print_exc()
            errors.append('retailsneed.xlsx: ' + str(e_retail))

        # 2. 生成 traveltime.xlsx（工厂到各零售商 + 零售商间模糊旅行时间）
        def _triple_to_row(t):
            raw = (t if isinstance(t, (list, tuple)) and len(t) >= 3 else [None, None, None])[:3]
            return [float(x) if x is not None else 0.0 for x in raw]

        travel_path = os.path.join(out_dir, 'traveltime.xlsx')
        try:
            n_retail = len(retailer_order)
            row0 = []
            for j in range(n_retail):
                idx = batch_indices[j]
                row0.extend(_triple_to_row(factory_to[idx] if idx < len(factory_to) else None))
            matrix_rows = [row0]
            for i in range(n_retail):
                ri = batch_indices[i]
                row = []
                for j in range(n_retail):
                    rj = batch_indices[j]
                    cell = None
                    if ri < len(retail_to) and rj < len(retail_to[ri]):
                        cell = retail_to[ri][rj]
                    row.extend(_triple_to_row(cell))
                matrix_rows.append(row)
            df_travel = pd.DataFrame(matrix_rows)
            df_travel.to_excel(travel_path, index=False, header=False)
        except Exception as e_travel:
            import traceback
            traceback.print_exc()
            errors.append('traveltime.xlsx: ' + str(e_travel))

        # 3. 生成 other.xlsx（产品参数 + 车辆参数）
        other_path = os.path.join(out_dir, 'other.xlsx')
        try:
            def _num(v, dtype=float):
                if v is None or v == '':
                    return np.nan
                try:
                    return dtype(v)
                except (TypeError, ValueError):
                    return np.nan

            all_products = db.fetch_all('productinf', {}) or []
            all_vehicles = db.fetch_all('vehicleinf', {}) or []
            all_products.sort(key=lambda p: str(p.get('product_id') or ''))
            all_vehicles.sort(key=lambda v: str(v.get('vehicle_id') or ''))
            n_p, n_v = len(all_products), len(all_vehicles)
            n_rows = max(n_p, n_v, 1)
            other_rows = []
            for i in range(n_rows):
                p = all_products[i] if i < n_p else {}
                v = all_vehicles[i] if i < n_v else {}
                takt = _num(p.get('takt'), float)
                pc = _num(p.get('pc'), float)
                pallet = _num(p.get('pallet'), float)
                capacity = _num(v.get('capacity'), int)
                constcost = _num(v.get('constcost'), int)
                varcost = _num(v.get('varcost'), int)
                other_rows.append([takt, pc, pallet, capacity, constcost, varcost])
            df_other = pd.DataFrame(other_rows)
            df_other.to_excel(other_path, index=False, header=False)
        except Exception as e_other:
            import traceback
            traceback.print_exc()
            errors.append('other.xlsx: ' + str(e_other))

        if errors:
            msg = '部分或全部 Excel 文件生成失败：\n' + '\n'.join(errors)
            return jsonify({
                'success': False,
                'message': msg,
                'details': errors
            }), 500

        # 全部 xlsx 正常生成后，再保存本次批量处理的订单 ID
        batch_ids = [oid for oid, _ in valid_orders]
        batch_ids_path = os.path.join(out_dir, 'last_batch_order_ids.json')
        try:
            with open(batch_ids_path, 'w', encoding='utf-8') as f:
                json.dump(batch_ids, f, ensure_ascii=False)
        except Exception:
            pass

        # 三个 Excel 均生成成功后，在后台线程中调用 KDCEA（避免阻塞响应）
        def _run_kdcea():
            with _kdcea_lock:
                _kdcea_state['status'] = 'running'
                _kdcea_state['message'] = '正在求解生产调度优化...'
            try:
                from ..fuxian import KDCEA
                class _KDCEAArgs:
                    pass

                args = _KDCEAArgs()
                # KDCEA 读取 instance 下的三个 Excel，结果输出到 result 目录
                args.instance = out_dir
                args.outdir = os.path.join(base_dir, 'result')
                # 设置随机种子
                args.seed = 42
                args.run_id = int(datetime.datetime.now().timestamp())

                KDCEA(args)
                # 求解完成，强制重新加载 EP 数据供 Pareto 展示使用
                try:
                    from ..result import readEP as _readEP
                    _readEP.reload_data()
                except Exception:
                    pass
                try:
                    from ..result.paintGantt import reload_data as _pg_reload
                    _pg_reload()
                except Exception:
                    pass
                with _kdcea_lock:
                    if _kdcea_state['status'] == 'cancelled':
                        return
                    _kdcea_state['status'] = 'completed'
                    _kdcea_state['message'] = '求解完成'
            except Exception as e:
                import traceback
                traceback.print_exc()
                err_text = str(e)
                if ('n_samples' in err_text) and ('n_clusters' in err_text):
                    err_text = '当前用于聚类的样本数（订单+工厂）需 >= 车辆数，请减少车辆数或增加订单后重试。'
                with _kdcea_lock:
                    if _kdcea_state['status'] != 'cancelled':
                        _kdcea_state['status'] = 'failed'
                        _kdcea_state['message'] = err_text
                try:
                    print(f"[batch_process] KDCEA 运行异常: {err_text}")
                except Exception:
                    pass

        with _kdcea_lock:
            _kdcea_state['status'] = 'idle'
            _kdcea_state['message'] = ''
        t = threading.Thread(target=_run_kdcea, daemon=True)
        _kdcea_state['thread'] = t
        t.start()

        return jsonify({
            'success': True,
            'path': out_path,
            'product_count': len(product_ids),
            'orders_exported': len(rows),
            'delivery_time_type': batch_delivery_mode
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# API: 查询 KDCEA 运行状态
@schePage.route('/schedulePage/kdcea_status', methods=['GET'])
def kdcea_status():
    with _kdcea_lock:
        return jsonify({
            'status': _kdcea_state['status'],
            'message': _kdcea_state['message'],
        })


# API: 取消 KDCEA 运行
@schePage.route('/schedulePage/kdcea_cancel', methods=['POST'])
def kdcea_cancel():
    with _kdcea_lock:
        if _kdcea_state['status'] != 'running':
            return jsonify({'success': False, 'message': '当前没有正在运行的求解任务'})
        _kdcea_state['status'] = 'cancelled'
        _kdcea_state['message'] = '已取消'
    return jsonify({'success': True})


# API: 获取当前被批量处理的订单列表（与订单管理页展示结构一致，供大屏展示用）
def _scheduletool_data_dir():
    # views/schedulePage.py -> Scheduletool/ (repo subfolder)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')


def _load_batch_orders_from_seed_excel(order_ids):
    """MongoDB 无订单时，从 data/*.xlsx 还原批量处理订单（只读展示）。"""
    data_dir = _scheduletool_data_dir()
    retails_path = os.path.join(data_dir, 'retails.xlsx')
    orderinfo_path = os.path.join(data_dir, 'orderinfo.xlsx')
    if not os.path.isfile(retails_path) or not os.path.isfile(orderinfo_path):
        return []

    try:
        meta_df = pd.read_excel(retails_path)
        meta_by_id = {
            int(row['order_id']): row.to_dict()
            for _, row in meta_df.iterrows()
            if pd.notna(row.get('order_id'))
        }
    except Exception:
        return []

    items_by_order = {}
    try:
        odf = pd.read_excel(orderinfo_path, header=0)
        for _, row in odf.iterrows():
            if pd.isna(row.get('order_id')):
                continue
            oid = int(row['order_id'])
            pid = int(row['product_id'])
            items_by_order.setdefault(oid, []).append({
                'product_id': pid,
                'product_name': f'产品{pid}',
                'quantity': int(row['quantity']),
            })
    except Exception:
        items_by_order = {}

    orders = []
    for oid in order_ids:
        try:
            oid_int = int(oid)
        except (TypeError, ValueError):
            continue
        meta = meta_by_id.get(oid_int)
        if meta is None:
            continue
        cid = int(meta.get('customer_id') or 0)
        orders.append({
            'order_info': {
                'order_id': oid_int,
                'order_number': oid_int,
                'customer_id': cid,
                'order_startdate': meta.get('order_time_start'),
                'order_enddate': meta.get('order_time_end'),
                'delivery_time_type': 'numeric',
                'customer_name': f'零售商{cid}' if cid else '—',
            },
            'products': items_by_order.get(oid_int, []),
        })
    return orders


@schePage.route('/schedulePage/batch_processed_orders', methods=['GET'])
def get_batch_processed_orders():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    out_dir = os.path.join(base_dir, 'result', 'excel')
    path = os.path.join(out_dir, 'last_batch_order_ids.json')
    if not os.path.isfile(path):
        return jsonify([])
    try:
        with open(path, 'r', encoding='utf-8') as f:
            order_ids = json.load(f)
    except Exception:
        return jsonify([])
    if not order_ids:
        return jsonify([])

    mixed_ids = list(order_ids)
    for oid in order_ids:
        try:
            mixed_ids.append(int(oid))
        except Exception:
            pass

    pipeline = [
        {"$match": {"order_id": {"$in": mixed_ids}}},
        {"$lookup": {
            "from": "order_items",
            "localField": "order_id",
            "foreignField": "order_id",
            "as": "items"
        }},
        {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "productinf",
            "let": {"pid": "$items.product_id"},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$eq": [
                            {"$toString": {"$ifNull": ["$product_id", ""]}},
                            {"$toString": {"$ifNull": ["$$pid", ""]}}
                        ]
                    }
                }}
            ],
            "as": "product_info"
        }},
        {"$unwind": {"path": "$product_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "customerinfo",
            "let": {"cid": "$customer_id"},
            "pipeline": [
                {"$match": {
                    "$expr": {
                        "$eq": [
                            {"$toString": {"$ifNull": ["$customer_id", ""]}},
                            {"$toString": {"$ifNull": ["$$cid", ""]}}
                        ]
                    }
                }}
            ],
            "as": "customer_info"
        }},
        {"$unwind": {"path": "$customer_info", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "order_id": 1,
            "customer_id": 1,
            "order_time_start": 1,
            "order_time_end": 1,
            "delivery_time_type": 1,
            "customer_name": "$customer_info.customer_name",
            "product_id": "$items.product_id",
            "product_name": "$product_info.product_name",
            "quantity": "$items.quantity"
        }}
    ]
    results = db.aggregate('orderinfo', pipeline)

    order_dict = {}
    for row in results:
        order_number = row.get('order_id')
        key = str(order_number)
        if key not in order_dict:
            order_dict[key] = {
                'order_info': {
                    'order_id': order_number,
                    'order_number': order_number,
                    'customer_id': row.get('customer_id'),
                    'order_startdate': row.get('order_time_start'),
                    'order_enddate': row.get('order_time_end'),
                    'delivery_time_type': _infer_delivery_time_type(
                        row.get('order_time_start'),
                        row.get('order_time_end'),
                        explicit_mode=row.get('delivery_time_type')
                    ),
                    'customer_name': row.get('customer_name') or str(row.get('customer_id') or '')
                },
                'products': []
            }
        if row.get('product_id') is not None:
            order_dict[key]['products'].append({
                'product_id': row.get('product_id'),
                'product_name': row.get('product_name') or str(row.get('product_id') or ''),
                'quantity': row.get('quantity')
            })

    # 按文件中的顺序返回
    orders = [order_dict[oid] for oid in order_ids if str(oid) in order_dict]
    if not orders:
        orders = _load_batch_orders_from_seed_excel(order_ids)
    return jsonify(orders)


# 参数设置页面（客户与产品管理）
@schePage.route('/schedulePage/params', methods=['GET'])
def params_page():
    # 本路由已改为重定向到主页面并让前端以内联方式加载 params 片段
    return redirect('/schedulePage?open=params')

# 参数页面片段（供 SPA 内联 AJAX 加载）
@schePage.route('/schedulePage/params_fragment', methods=['GET'])
def params_fragment():
    return render_template('params_fragment.html')


# --- Customer APIs ---
@schePage.route('/schedulePage/customers', methods=['GET'])
def list_customers():
    _ensure_demo_data()
    try:
        customers = _load_customers_sorted()
        try:
            print(f"[list_customers] 返回 {len(customers)} 条客户数据")
        except Exception:
            pass
        # customer_id 为 0 的为工厂，不可删除；工厂排第一位
        out = []
        for c in customers:
            row = dict(c)
            row['is_factory'] = _is_factory_id(c.get('customer_id'))
            out.append(row)
        # 强制工厂排第一（不依赖 _load_customers_sorted 的排序）
        out.sort(key=lambda r: (0 if r.get('is_factory') else 1))
        return jsonify(out)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@schePage.route('/schedulePage/customers', methods=['POST'])
def create_customer():
    data = request.get_json() or {}
    name = data.get('customer_name')
    addr_x = data.get('address_X')
    addr_y = data.get('address_Y')
    cust_id = data.get('customer_id')

    if not name:
        return jsonify({'success': False, 'message': 'customer_name required'}), 400

    if not cust_id:
        cust_id = f"CUST-{int(datetime.datetime.utcnow().timestamp())}"

    # 防止重复
    exists = db.fetch_all('customerinfo', {'customer_id': cust_id})
    if exists:
        return jsonify({'success': False, 'message': 'customer_id already exists'}), 400

    doc = {
        'customer_id': cust_id,
        'customer_name': name,
        'address_X': float(addr_x) if addr_x is not None and addr_x != '' else None,
        'address_Y': float(addr_y) if addr_y is not None and addr_y != '' else None
    }
    db.create('customerinfo', doc)
    return jsonify({'success': True, 'customer_id': cust_id}), 201


@schePage.route('/schedulePage/customers/<customer_id>', methods=['PUT'])
def update_customer(customer_id):
    data = request.get_json() or {}
    update_data = {}
    if 'customer_name' in data:
        update_data['customer_name'] = data.get('customer_name')
    if 'address_X' in data:
        try:
            update_data['address_X'] = float(data.get('address_X')) if data.get('address_X') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'address_X must be numeric'}), 400
    if 'address_Y' in data:
        try:
            update_data['address_Y'] = float(data.get('address_Y')) if data.get('address_Y') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'address_Y must be numeric'}), 400

    if not update_data:
        return jsonify({'success': False, 'message': 'no updatable fields provided'}), 400

    modified = db.update('customerinfo', _customer_id_match_query(customer_id), update_data)
    return jsonify({'success': True, 'modified': modified})


@schePage.route('/schedulePage/customers/<customer_id>', methods=['DELETE'])
def delete_customer(customer_id):
    """
    删除零售商（customerinfo）、该零售商下所有订单及 order_items，并同步删除旅行时间矩阵中对应行/列。
    工厂（customer_id 为 0）不可删除。
    """
    try:
        if _is_factory_id(customer_id):
            return jsonify({'success': False, 'message': '工厂不可删除'}), 403

        # 删除该零售商下的所有订单及其 order_items
        orders = db.fetch_all('orderinfo', _customer_id_match_query(customer_id)) or []
        for o in orders:
            oid = o.get('order_id')
            if oid:
                db.delete_many('order_items', {'order_id': oid})
                db.delete('orderinfo', {'order_id': oid})

        # delete_one 只删一条，这里按兼容查询删第一条匹配记录
        deleted = db.delete('customerinfo', _customer_id_match_query(customer_id))

        # 同步更新旅行时间矩阵（若存在）
        coll = 'travel_time_matrix'
        matrix_id = 'default'
        docs = db.fetch_all(coll, {'matrix_id': matrix_id}) or []
        doc = docs[0] if docs else None
        if doc:
            ids = [str(x) for x in (doc.get('customer_ids') or [])]
            if str(customer_id) in ids:
                idx = ids.index(str(customer_id))
                ids.pop(idx)
                factory_to = doc.get('factory_to') or []
                retail_to = doc.get('retail_to') or []
                # 删除 factory_to 的对应列
                if idx < len(factory_to):
                    factory_to.pop(idx)
                # 删除 retail_to 的对应行/列
                new_retail = []
                for r_i, row in enumerate(retail_to):
                    if r_i == idx:
                        continue
                    try:
                        new_row = list(row)
                        if idx < len(new_row):
                            new_row.pop(idx)
                        new_retail.append(new_row)
                    except Exception:
                        # 结构异常则重建
                        new_retail = []
                        break

                # 重新规范化对角线与对称（防止删减后异常）
                n = len(ids)
                if len(factory_to) != n or len(new_retail) != n:
                    # 让迁移逻辑兜底重建
                    _get_or_migrate_travel_matrix()
                else:
                    for i in range(n):
                        if i < len(new_retail) and i < len(new_retail[i]):
                            new_retail[i][i] = _default_triple(0)
                    for i in range(n):
                        for j in range(i + 1, n):
                            a = _normalize_triple(new_retail[i][j])
                            b = _normalize_triple(new_retail[j][i])
                            if all(v is None for v in a) and not all(v is None for v in b):
                                a = b
                            new_retail[i][j] = a
                            new_retail[j][i] = a
                    db.update(coll, {'matrix_id': matrix_id}, {
                        'customer_ids': ids,
                        'factory_to': factory_to,
                        'retail_to': new_retail
                    }, upsert=True)

        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# --- Travel times APIs ---
@schePage.route('/schedulePage/travel_times', methods=['GET'])
def get_travel_times():
    try:
        customers, doc = _get_or_migrate_travel_matrix()
        # 与矩阵顺序一致，并为前端标记工厂（用于矩阵只显示第一行为工厂、列与其余行为零售商）
        customers_with_flag = [
            {'customer_id': str(c['customer_id']), 'customer_name': c.get('customer_name') or str(c['customer_id']), 'is_factory': _is_factory_id(c.get('customer_id'))}
            for c in customers
        ]
        return jsonify({
            'success': True,
            'customer_ids': [str(c['customer_id']) for c in customers],
            'customers': customers_with_flag,
            'matrix': {
                'factory_to': doc.get('factory_to') or [],
                'retail_to': doc.get('retail_to') or [],
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@schePage.route('/schedulePage/travel_times', methods=['PUT', 'POST'])
def save_travel_times():
    try:
        payload = request.get_json() or {}
        customer_ids = [str(x) for x in (payload.get('customer_ids') or [])]
        matrix = payload.get('matrix') or {}
        factory_to = matrix.get('factory_to') or []
        retail_to = matrix.get('retail_to') or []

        # 以当前 customer 列表为准（避免前端/数据库不同步）
        customers = _load_customers_sorted()
        current_ids = [str(c['customer_id']) for c in customers]
        if customer_ids != current_ids:
            # 前端可能未刷新；直接以当前为准做一次迁移，然后再对齐保存
            customers, base_doc = _get_or_migrate_travel_matrix()
            current_ids = [str(c['customer_id']) for c in customers]

        n = len(current_ids)

        if len(factory_to) != n:
            return jsonify({'success': False, 'message': f'factory_to 长度应为 {n}'}), 400
        if len(retail_to) != n or any((not isinstance(row, list) or len(row) != n) for row in retail_to):
            return jsonify({'success': False, 'message': f'retail_to 形状应为 {n}x{n}'}), 400

        # 规范化
        norm_factory = [_normalize_triple(factory_to[j]) for j in range(n)]
        norm_retail = [[_normalize_triple(retail_to[i][j]) for j in range(n)] for i in range(n)]

        # 对角线固定 0
        for i in range(n):
            norm_retail[i][i] = _default_triple(0)

        # 对称（零售商-零售商）
        for i in range(n):
            for j in range(i + 1, n):
                a = _normalize_triple(norm_retail[i][j])
                b = _normalize_triple(norm_retail[j][i])
                # 优先用 a；若 a 全空则用 b
                if all(v is None for v in a) and not all(v is None for v in b):
                    a = b
                norm_retail[i][j] = a
                norm_retail[j][i] = a

        doc = {
            'matrix_id': 'default',
            'customer_ids': current_ids,
            'factory_to': norm_factory,
            'retail_to': norm_retail
        }
        db.update('travel_time_matrix', {'matrix_id': 'default'}, doc, upsert=True)
        return jsonify({'success': True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# --- Product APIs ---
@schePage.route('/schedulePage/products', methods=['GET'])
def list_products():
    raw = db.fetch_all('productinf', {})
    # 保证每条都有 takt、pc、pallet，便于前端显示（含历史无这些字段的数据）
    products = []
    for p in raw or []:
        row = dict(p)
        if 'takt' not in row:
            row['takt'] = None
        if 'pc' not in row:
            row['pc'] = None
        if 'pallet' not in row:
            row['pallet'] = None
        products.append(row)
    return jsonify(products)


@schePage.route('/schedulePage/products', methods=['POST'])
def create_product():
    data = request.get_json() or {}
    name = str(data.get('product_name') or '').strip()
    takt = data.get('takt')
    pc = data.get('pc')
    pallet = data.get('pallet')
    product_id = str(data.get('product_id') or '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'product_name required'}), 400

    if not product_id:
        product_id = f"PROD-{int(datetime.datetime.utcnow().timestamp())}"

    exists = db.fetch_all('productinf', {'product_id': product_id})
    if exists:
        return jsonify({'success': False, 'message': 'product_id already exists'}), 400

    try:
        doc = {
            'product_id': product_id,
            'product_name': name,
            'takt': float(takt) if takt is not None and takt != '' else None,
            'pc': float(pc) if pc is not None and pc != '' else None,
            'pallet': float(pallet) if pallet is not None and pallet != '' else None
        }
    except Exception:
        return jsonify({'success': False, 'message': 'takt/pc/pallet must be numeric'}), 400

    db.create('productinf', doc)
    return jsonify({'success': True, 'product_id': product_id}), 201


@schePage.route('/schedulePage/products/<product_id>', methods=['PUT'])
def update_product(product_id):
    data = request.get_json() or {}
    update_data = {}
    if 'product_name' in data:
        update_data['product_name'] = data.get('product_name')
    if 'takt' in data:
        try:
            update_data['takt'] = float(data.get('takt')) if data.get('takt') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'takt must be numeric'}), 400
    if 'pc' in data:
        try:
            update_data['pc'] = float(data.get('pc')) if data.get('pc') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'pc must be numeric'}), 400
    if 'pallet' in data:
        try:
            update_data['pallet'] = float(data.get('pallet')) if data.get('pallet') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'pallet must be numeric'}), 400

    if not update_data:
        return jsonify({'success': False, 'message': 'no updatable fields provided'}), 400

    modified = db.update('productinf', {'product_id': product_id}, update_data)
    return jsonify({'success': True, 'modified': modified})


@schePage.route('/schedulePage/products/<product_id>', methods=['DELETE'])
def delete_product(product_id):
    """删除产品：删除 productinf 中记录、所有关联 order_items；若某订单仅含该产品则一并删除订单。"""
    # 1. 找出所有包含该产品的 order_items 及其订单 id
    items = db.fetch_all('order_items', {'product_id': product_id}) or []
    order_ids_affected = set(it.get('order_id') for it in items if it.get('order_id') is not None)
    # 2. 删除所有该产品的 order_items
    db.delete_many('order_items', {'product_id': product_id})
    # 3. 对每个涉及订单检查是否还有其它 items；若无则删除该订单
    for oid in order_ids_affected:
        remaining = db.fetch_all('order_items', {'order_id': oid}) or []
        if not remaining:
            db.delete('orderinfo', {'order_id': oid})
    # 4. 删除产品
    deleted = db.delete('productinf', {'product_id': product_id})
    if not deleted:
        return jsonify({'success': False, 'message': 'product not found'}), 404
    return jsonify({'success': True, 'message': 'deleted'})


# 车辆管理 API：列表 / 创建 / 更新
@schePage.route('/schedulePage/vehicles', methods=['GET'])
def list_vehicles():
    try:
        vehicles = db.fetch_all('vehicleinf', {})
        try:
            print(f"[list_vehicles] 返回 {len(vehicles)} 条车辆数据")
            if len(vehicles) > 0:
                sample_keys = set().union(*(v.keys() for v in vehicles))
                print(f"[list_vehicles] 示例字段: {list(sample_keys)[:10]}")
        except Exception:
            pass
        return jsonify(vehicles)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@schePage.route('/schedulePage/vehicles', methods=['POST'])
def create_vehicle():
    data = request.get_json() or {}
    name = str(data.get('vehicle_name') or '').strip()
    capacity = data.get('capacity')
    constcost = data.get('constcost')
    varcost = data.get('varcost')
    vid = str(data.get('vehicle_id') or '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'vehicle_name required'}), 400

    if not vid:
        vid = f"VEH-{int(datetime.datetime.utcnow().timestamp())}"

    # 防止重复
    exists = db.fetch_all('vehicleinf', {'vehicle_id': vid})
    if exists:
        return jsonify({'success': False, 'message': 'vehicle_id already exists'}), 400

    try:
        doc = {
            'vehicle_id': vid,
            'vehicle_name': name,
            'capacity': int(capacity) if capacity not in (None, '') else None,
            'constcost': int(constcost) if constcost not in (None, '') else None,
            'varcost': int(varcost) if varcost not in (None, '') else None
        }
        db.create('vehicleinf', doc)
        return jsonify({'success': True, 'vehicle_id': vid}), 201
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@schePage.route('/schedulePage/vehicles/<vehicle_id>', methods=['PUT'])
def update_vehicle(vehicle_id):
    vehicle_key = str(vehicle_id or '').strip()
    query_candidates = [{'vehicle_id': vehicle_key}]
    if vehicle_key.isdigit():
        query_candidates.append({'vehicle_id': int(vehicle_key)})
    if ObjectId.is_valid(vehicle_key):
        query_candidates.append({'_id': ObjectId(vehicle_key)})
    query = {'$or': query_candidates} if len(query_candidates) > 1 else query_candidates[0]

    data = request.get_json() or {}
    update_data = {}
    if 'vehicle_name' in data:
        update_data['vehicle_name'] = data.get('vehicle_name')
    if 'capacity' in data:
        try:
            update_data['capacity'] = int(data.get('capacity')) if data.get('capacity') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'capacity must be integer'}), 400
    if 'constcost' in data:
        try:
            update_data['constcost'] = int(data.get('constcost')) if data.get('constcost') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'constcost must be integer'}), 400
    if 'varcost' in data:
        try:
            update_data['varcost'] = int(data.get('varcost')) if data.get('varcost') != '' else None
        except Exception:
            return jsonify({'success': False, 'message': 'varcost must be integer'}), 400

    if not update_data:
        return jsonify({'success': False, 'message': 'no updatable fields provided'}), 400

    exists = db.fetch_all('vehicleinf', query)
    if not exists:
        return jsonify({'success': False, 'message': 'vehicle not found'}), 404
    modified = db.update('vehicleinf', query, update_data)
    return jsonify({'success': True, 'modified': modified})


@schePage.route('/schedulePage/vehicles/<vehicle_id>', methods=['DELETE'])
def delete_vehicle(vehicle_id):
    """删除车辆。"""
    vehicle_key = str(vehicle_id or '').strip()
    query_candidates = [{'vehicle_id': vehicle_key}]
    if vehicle_key.isdigit():
        query_candidates.append({'vehicle_id': int(vehicle_key)})
    if ObjectId.is_valid(vehicle_key):
        query_candidates.append({'_id': ObjectId(vehicle_key)})
    query = {'$or': query_candidates} if len(query_candidates) > 1 else query_candidates[0]
    deleted = db.delete('vehicleinf', query)
    if not deleted:
        return jsonify({'success': False, 'message': 'vehicle not found'}), 404
    return jsonify({'success': True, 'message': 'deleted'})


# @schePage.route('/schedulePage/delete_order/<order_id>', methods=['DELETE'])
# def delete_order(order_id):
#     # 已在上方定义带异常处理的同名视图，保留上面的实现以避免重复路由注册
#     # 这个占位函数不会被注册（已删除），保留此处仅作说明
#     return jsonify({'success': True, 'message': 'duplicate handler removed'})


