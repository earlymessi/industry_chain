"""
从 Excel 按顺序导入工厂与零售商名称、经纬度到 MongoDB customerinfo。
默认读取 data/(original) Factory and retailers  locations.xlsx
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils import db  # noqa: E402

DEFAULT_EXCEL = os.path.join(
    ROOT,
    'data',
    '(original) Factory and retailers  locations.xlsx',
)


def _default_triple(value=None):
    if value is None:
        return [None, None, None]
    return [value, value, value]


def _normalize_triple(triple):
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


def _sort_customer_key(c):
    raw = c.get('customer_id')
    cid = '' if raw is None else str(raw)
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


def _sync_travel_matrix():
    customers = db.fetch_all('customerinfo', {}) or []
    customers = [c for c in customers if c.get('customer_id') is not None]
    customers.sort(key=_sort_customer_key)
    customer_ids = [str(c['customer_id']) for c in customers]
    n = len(customer_ids)

    coll = 'travel_time_matrix'
    matrix_id = 'default'
    docs = db.fetch_all(coll, {'matrix_id': matrix_id}) or []
    doc = docs[0] if docs else None

    new_doc = {
        'matrix_id': matrix_id,
        'customer_ids': list(customer_ids),
        'factory_to': [_default_triple(None) for _ in range(n)],
        'retail_to': [[_default_triple(0 if i == j else None) for j in range(n)] for i in range(n)],
    }

    if not doc:
        db.update(coll, {'matrix_id': matrix_id}, new_doc, upsert=True)
        return

    old_ids = [str(x) for x in (doc.get('customer_ids') or [])]
    old_factory = doc.get('factory_to') or []
    old_retail = doc.get('retail_to') or []
    old_index = {cid: idx for idx, cid in enumerate(old_ids)}

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

    for i in range(n):
        new_doc['retail_to'][i][i] = _default_triple(0)

    for i in range(n):
        for j in range(i + 1, n):
            a = _normalize_triple(new_doc['retail_to'][i][j])
            b = _normalize_triple(new_doc['retail_to'][j][i])
            if all(v is None for v in a) and not all(v is None for v in b):
                a = b
            new_doc['retail_to'][i][j] = a
            new_doc['retail_to'][j][i] = a

    db.update(coll, {'matrix_id': matrix_id}, new_doc, upsert=True)


def import_from_excel(excel_path=DEFAULT_EXCEL):
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f'Excel 文件不存在: {excel_path}')

    df = pd.read_excel(excel_path)
    lon_col = 'Longitude ' if 'Longitude ' in df.columns else 'Longitude'
    lat_col = 'Latitude'

    created = 0
    updated = 0
    rows = []

    for _, row in df.iterrows():
        cust_id = int(row['Number'])
        name = str(row['Factory/Retailers']).strip()
        lon = float(row[lon_col])
        lat = float(row[lat_col])

        doc = {
            'customer_id': cust_id,
            'customer_name': name,
            'address_X': lon,
            'address_Y': lat,
        }
        rows.append(doc)

        existing = db.fetch_all('customerinfo', {'customer_id': cust_id}) or []
        if not existing:
            existing = db.fetch_all('customerinfo', {'customer_id': str(cust_id)}) or []

        if existing:
            db.update(
                'customerinfo',
                {'customer_id': existing[0]['customer_id']},
                {
                    'customer_name': name,
                    'address_X': lon,
                    'address_Y': lat,
                },
            )
            updated += 1
        else:
            db.create('customerinfo', doc)
            created += 1

    _sync_travel_matrix()
    return rows, created, updated


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXCEL
    records, created, updated = import_from_excel(path)
    print(f'导入完成: 共 {len(records)} 条（新建 {created}，更新 {updated}）')
    for r in records:
        print(
            f"  [{r['customer_id']}] {r['customer_name']} "
            f"经度={r['address_X']}, 纬度={r['address_Y']}"
        )
