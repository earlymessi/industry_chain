"""
从「物流调度数据1」目录导入 Scheduletool MongoDB 集合。

目录内应为 mongoexport 风格的 JSON 数组文件，例如：
  schedule_flask.customerinfo.json
  schedule_flask.productinf.json
  schedule_flask.vehicleinf.json
  schedule_flask.travel_time_matrix.json
  schedule_flask.orderinfo.json
  schedule_flask.order_items.json

用法（在 Scheduletool 目录或项目根目录）:
  python scripts/import_logistics_bundle.py
  python scripts/import_logistics_bundle.py --dir "D:/path/物流调度数据1"
  python scripts/import_logistics_bundle.py --merge   # 不清空，仅 upsert（按业务主键）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(ROOT)
DEFAULT_BUNDLE_DIR = os.path.join(REPO_ROOT, "物流调度数据1")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils import db  # noqa: E402

# 导入顺序：先主数据，后订单
COLLECTIONS: List[Tuple[str, str, Optional[str]]] = [
    ("schedule_flask.customerinfo.json", "customerinfo", "customer_id"),
    ("schedule_flask.productinf.json", "productinf", "product_id"),
    ("schedule_flask.vehicleinf.json", "vehicleinf", "vehicle_id"),
    ("schedule_flask.travel_time_matrix.json", "travel_time_matrix", "matrix_id"),
    ("schedule_flask.orderinfo.json", "orderinfo", "order_id"),
    ("schedule_flask.order_items.json", "order_items", "order_items_id"),
]


def _load_json_array(path: str) -> List[Dict[str, Any]]:
    from bson import json_util

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []
    data = json_util.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"无法解析 JSON 数组: {path}")


def _strip_object_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out.pop("_id", None)
    return out


def _import_collection(
    coll_name: str,
    docs: List[Dict[str, Any]],
    *,
    replace: bool,
    key_field: Optional[str],
) -> int:
    coll = db.get_collection(coll_name)
    cleaned = [_strip_object_id(d) for d in docs]

    if replace:
        coll.delete_many({})
        if not cleaned:
            return 0
        coll.insert_many(cleaned)
        return len(cleaned)

    count = 0
    for doc in cleaned:
        if key_field and doc.get(key_field) is not None:
            coll.replace_one({key_field: doc[key_field]}, doc, upsert=True)
            count += 1
        else:
            coll.insert_one(doc)
            count += 1
    return count


def import_bundle(bundle_dir: str, *, replace: bool = True) -> Dict[str, int]:
    if not os.path.isdir(bundle_dir):
        raise FileNotFoundError(f"数据目录不存在: {bundle_dir}")

    stats: Dict[str, int] = {}
    for filename, coll_name, key_field in COLLECTIONS:
        path = os.path.join(bundle_dir, filename)
        if not os.path.isfile(path):
            print(f"[skip] 未找到 {filename}")
            stats[coll_name] = 0
            continue
        docs = _load_json_array(path)
        n = _import_collection(coll_name, docs, replace=replace, key_field=key_field)
        stats[coll_name] = n
        print(f"[ok] {coll_name}: {n} 条 <- {filename}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="导入物流调度数据1到 schedule_flask")
    parser.add_argument(
        "--dir",
        default=os.getenv("SCHEDULETOOL_BUNDLE_DIR", DEFAULT_BUNDLE_DIR),
        help="JSON 数据目录（默认: 项目根/物流调度数据1）",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="合并模式（不清空集合，按主键 upsert）",
    )
    args = parser.parse_args()

    stats = import_bundle(args.dir, replace=not args.merge)
    total = sum(stats.values())
    print(f"导入完成，共写入 {total} 条记录。")
    for k, v in stats.items():
        if v:
            print(f"  - {k}: {v}")


if __name__ == "__main__":
    main()
