"""Scheduletool 演示/初始化数据：优先物流调度数据1，其次 Excel 种子。"""

from __future__ import annotations

import os
import sys
from typing import Tuple

_SEEDED = False


def _scheduletool_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bundle_dir() -> str:
    return os.path.join(os.path.dirname(_scheduletool_root()), "物流调度数据1")


def ensure_demo_data() -> Tuple[bool, str]:
    """返回 (是否执行了初始化, 说明)。"""
    global _SEEDED
    if _SEEDED:
        return False, "already_checked"

    from utils import db

    bundle = _bundle_dir()
    bundle_marker = os.path.join(bundle, "schedule_flask.customerinfo.json")
    has_customers = bool(db.fetch_all("customerinfo", {}, projection={"_id": 1}))

    # 存在「物流调度数据1」且库中尚无客户数据时，自动导入整套参数
    if os.path.isfile(bundle_marker) and not has_customers:
        try:
            scripts = os.path.join(_scheduletool_root(), "scripts")
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            from import_logistics_bundle import import_bundle

            stats = import_bundle(bundle, replace=True)
            _SEEDED = True
            return True, f"logistics_bundle:{sum(stats.values())}"
        except Exception as exc:
            return False, f"bundle_failed:{exc}"

    if db.fetch_all("orderinfo", {}, projection={"_id": 1}):
        _SEEDED = True
        return False, "orders_exist"

    root = _scheduletool_root()
    scripts = os.path.join(root, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)

    try:
        if not db.fetch_all("customerinfo", {}, projection={"_id": 1}):
            from import_retailers_from_excel import import_from_excel

            import_from_excel()

        if not db.fetch_all("productinf", {}, projection={"_id": 1}):
            demo_products = [
                ("1", "海尔 BCD-470WDPG 十字四门冰箱"),
                ("2", "海尔 KFR-35GW/01KBB81U1 1.5匹变频空调"),
                ("3", "海尔 EG10014HB939G 10kg滚筒洗衣机"),
                ("4", "海尔 ES60H-HC3 60L储水式电热水器"),
                ("5", "海尔 65U1 65英寸4K智能电视"),
            ]
            for pid, pname in demo_products:
                db.create(
                    "productinf",
                    {
                        "product_id": pid,
                        "product_name": pname,
                        "takt": 1.0,
                        "pc": 1.0,
                        "pallet": 1.0,
                    },
                )

        if not db.fetch_all("vehicleinf", {}, projection={"_id": 1}):
            db.create(
                "vehicleinf",
                {
                    "vehicle_id": "V1",
                    "capacity": 10000,
                    "constcost": 100,
                    "varcost": 10,
                },
            )

        if not db.fetch_all("orderinfo", {}, projection={"_id": 1}):
            from import_orders_from_excel import import_orders

            import_orders(replace=True)

        _SEEDED = True
        return True, "seeded"
    except Exception as exc:
        return False, str(exc)
