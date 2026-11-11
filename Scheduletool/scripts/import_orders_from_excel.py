"""
从 Excel 导入订单到 MongoDB orderinfo / order_items。

- orderinfo.xlsx 的 G~J 列：order_item_id, order_id, product_id, quantity
- retails.xlsx：order_id, customer_id, order_time_start, order_time_end

交付时间以 2025-01-01 00:00 为起点，按小时偏移转为时间戳（delivery_time_type=datetime）。
Excel 中 product_id 1~5 按 productinf 中产品排序后的第 1~5 条记录映射。
"""
import datetime
import os
import re
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils import db  # noqa: E402

DEFAULT_ORDER_ITEMS = os.path.join(ROOT, 'data', 'orderinfo.xlsx')
DEFAULT_ORDER_META = os.path.join(ROOT, 'data', 'retails.xlsx')
BASE_TIME = datetime.datetime(2025, 1, 1, 0, 0, 0)


def _hours_to_timestamp(hours):
    dt = BASE_TIME + datetime.timedelta(hours=float(hours))
    return dt.strftime('%Y-%m-%dT%H:%M')


def _build_product_map():
    products = db.fetch_all('productinf', {}) or []
    if not products:
        raise RuntimeError('productinf 为空，请先创建产品数据')

    mapping = {}
    # 兼容旧数据：产品名以数字结尾时按末尾数字映射
    for p in products:
        name = str(p.get('product_name') or '')
        m = re.search(r'(\d+)\s*$', name)
        if m:
            mapping[int(m.group(1))] = p['product_id']

    if len(mapping) >= 5 and all(i in mapping for i in range(1, 6)):
        return mapping

    # 家电型号等新命名：按 product_id 排序后取前 5 条
    sorted_products = sorted(products, key=lambda x: str(x.get('product_id') or ''))
    if len(sorted_products) < 5:
        raise RuntimeError('productinf 至少需要 5 条产品记录')
    mapping = {
        i + 1: sorted_products[i]['product_id']
        for i in range(5)
    }
    return mapping


def _load_order_meta(path):
    df = pd.read_excel(path, header=0)
    meta = {}
    for _, row in df.iterrows():
        oid = int(row['order_id'])
        meta[oid] = {
            'customer_id': int(row['customer_id']),
            'order_time_start': _hours_to_timestamp(row['order_time_start']),
            'order_time_end': _hours_to_timestamp(row['order_time_end']),
        }
    return meta


def _load_order_items(path):
    df = pd.read_excel(path, header=None)
    header = df.iloc[0].tolist()
    col_idx = {str(v).strip(): i for i, v in enumerate(header) if pd.notna(v)}

    for key in ('order_id', 'product_id', 'quantity'):
        if key not in col_idx:
            raise RuntimeError(f'orderinfo.xlsx 缺少列: {key}')

    item_id_col = col_idx.get('order_item_id')
    items_by_order = {}
    for _, row in df.iloc[1:].iterrows():
        oid = int(row[col_idx['order_id']])
        pid = int(row[col_idx['product_id']])
        qty = int(row[col_idx['quantity']])
        item_id = int(row[item_id_col]) if item_id_col is not None else None
        items_by_order.setdefault(oid, []).append({
            'order_item_id': item_id,
            'product_id': pid,
            'quantity': qty,
        })
    return items_by_order


def import_orders(items_path=DEFAULT_ORDER_ITEMS, meta_path=DEFAULT_ORDER_META, replace=True):
    product_map = _build_product_map()
    order_meta = _load_order_meta(meta_path)
    items_by_order = _load_order_items(items_path)

    missing_meta = sorted(set(items_by_order) - set(order_meta))
    if missing_meta:
        raise RuntimeError(f'retails.xlsx 缺少订单元数据: {missing_meta}')

    if replace:
        db.delete_many('order_items', {})
        db.delete_many('orderinfo', {})

    created_orders = 0
    created_items = 0

    for oid in sorted(order_meta.keys()):
        meta = order_meta[oid]
        items = items_by_order.get(oid, [])
        if not items:
            raise RuntimeError(f'orderinfo.xlsx 缺少订单 {oid} 的商品明细')

        order_doc = {
            'order_id': oid,
            'customer_id': meta['customer_id'],
            'order_time_start': meta['order_time_start'],
            'order_time_end': meta['order_time_end'],
            'delivery_time_type': 'datetime',
        }
        db.create('orderinfo', order_doc)
        created_orders += 1

        item_docs = []
        for it in sorted(items, key=lambda x: x['product_id']):
            db_pid = product_map[it['product_id']]
            item_docs.append({
                'order_items_id': f"OI-{oid}-{db_pid}",
                'order_id': oid,
                'product_id': db_pid,
                'quantity': int(it['quantity']),
            })
        db.create('order_items', item_docs)
        created_items += len(item_docs)

    return created_orders, created_items, product_map


if __name__ == '__main__':
    items_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ORDER_ITEMS
    meta_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ORDER_META
    orders, items, product_map = import_orders(items_path, meta_path)
    print(f'导入完成: {orders} 个订单, {items} 条 order_items')
    print('产品映射:')
    for i in sorted(product_map):
        print(f'  Excel product_id {i} -> {product_map[i]}')
