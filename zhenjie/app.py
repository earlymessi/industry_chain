# -*- coding: utf-8 -*-
"""
多周期车辆路径实验 Web 服务
- 实验启停 / 进度 / 结果
- 订单管理（本机 MongoDB: zhenjie_vrp）
"""
from __future__ import annotations

import copy
import os
import subprocess
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from bson import ObjectId
from flask import Flask, jsonify, request, send_from_directory
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

if __package__:
    from . import shili_run2 as engine
else:
    import shili_run2 as engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 挂载时复用主系统 MongoDB；仅独立运行时默认尝试启动本机服务。
AUTO_MONGOD = os.environ.get("ZHENJIE_AUTO_MONGOD", "0" if __package__ else "1").strip().lower() not in ("0", "false", "no")

# ---- MongoDB（本机，非 Docker）----
MONGO_URI = (os.environ.get("ZHENJIE_MONGO_URI") or os.environ.get("MONGO_URL")
             or os.environ.get("MONGO_URI") or "mongodb://127.0.0.1:27017")
MONGO_DB_NAME = "zhenjie_vrp"
MONGO_ORDERS = "orders"
ORDER_FIELDS = ["cust_id", "lon", "lat", "demand", "service", "tw_start", "tw_end", "cust_name"]

app = Flask(__name__, static_folder=None)

OUTPUT_PATH_KEYS = (
    "RUN_RESULTS_CSV", "RUN_SUMMARY_CSV", "BEST_RUN_SUMMARY_CSV",
    "ALNS_IMPROV_PER_RUN_CSV", "ALNS_IMPROV_SUMMARY_CSV",
    "REP_PARETO_PNG", "REP_WORKTIME_PNG", "MAP_OUT_HTML",
    "BEST_STAGE2_TIMELINE_CSV", "BEST_STAGE2_ROUTE_SEQ_CSV",
)

_mongo_client: Optional[MongoClient] = None
_mongo_lock = threading.Lock()

_job_lock = threading.Lock()
_stop_event = threading.Event()
_job: Dict[str, Any] = {
    "status": "idle",  # idle | running | done | error | stopped
    "progress": 0.0,
    "n_runs": 0,
    "current_run": 0,
    "message": "待命",
    "logs": [],
    "started_at": None,
    "finished_at": None,
    "error": None,
    "result": None,
    "stop_requested": False,
}


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _push_log(msg: str, level: str = "info"):
    _job["logs"].append({"time": _now(), "msg": msg, "level": level})
    if len(_job["logs"]) > 400:
        _job["logs"] = _job["logs"][-400:]


def _wait_mongo_ready(timeout_sec: float = 8.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=800)
            c.admin.command("ping")
            c.close()
            return True
        except Exception:
            time.sleep(0.4)
    return False


def _try_start_local_mongod() -> bool:
    """启动本机 MongoDB：优先项目内便携版，其次 Windows 服务，最后官方安装目录。"""
    if not AUTO_MONGOD:
        return False
    if _wait_mongo_ready(1.5):
        return True

    # 1) 项目内便携版（绕过损坏的 Windows 服务）
    portable_root = os.path.join(BASE_DIR, "mongodb-portable")
    portable = None
    if os.path.isdir(portable_root):
        for root, _dirs, files in os.walk(portable_root):
            if "mongod.exe" in files:
                portable = os.path.join(root, "mongod.exe")
                break
    if portable:
        data_dir = os.path.join(BASE_DIR, "mongo_data")
        log_dir = os.path.join(BASE_DIR, "mongo_logs")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "mongod.log")
        try:
            subprocess.Popen(
                [portable, "--dbpath", data_dir, "--bind_ip", "127.0.0.1",
                 "--port", "27017", "--logpath", log_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if _wait_mongo_ready(12):
                return True
        except Exception:
            pass

    # 2) Windows 服务
    try:
        subprocess.run(
            ["sc", "start", "MongoDB"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if _wait_mongo_ready(6):
            return True
    except Exception:
        pass

    # 3) 官方安装目录 mongod.exe
    root = r"C:\Program Files\MongoDB\Server"
    mongod = None
    if os.path.isdir(root):
        for name in sorted(os.listdir(root), reverse=True):
            exe = os.path.join(root, name, "bin", "mongod.exe")
            if os.path.exists(exe):
                mongod = exe
                break
    if not mongod:
        return False

    data_dir = os.path.join(BASE_DIR, "mongo_data")
    log_dir = os.path.join(BASE_DIR, "mongo_logs")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "mongod.log")
    try:
        subprocess.Popen(
            [mongod, "--dbpath", data_dir, "--bind_ip", "127.0.0.1",
             "--port", "27017", "--logpath", log_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return _wait_mongo_ready(10)
    except Exception:
        return False


def get_db():
    global _mongo_client
    with _mongo_lock:
        if _mongo_client is None:
            _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500)
        try:
            _mongo_client.admin.command("ping")
        except ServerSelectionTimeoutError:
            if _try_start_local_mongod():
                _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
                _mongo_client.admin.command("ping")
            else:
                raise
        db = _mongo_client[MONGO_DB_NAME]
        db[MONGO_ORDERS].create_index([("day", ASCENDING), ("cust_id", ASCENDING)], unique=True)
        return db


def _serialize_order(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: doc.get(k) for k in ORDER_FIELDS}
    out["day"] = int(doc.get("day", 1))
    out["id"] = str(doc["_id"])
    if doc.get("updated_at"):
        out["updated_at"] = doc["updated_at"].isoformat(timespec="seconds")
    return out


def _normalize_order_payload(data: Dict[str, Any], day: Optional[int] = None) -> Dict[str, Any]:
    d = int(day if day is not None else data.get("day", 1))
    if d < 1 or d > int(engine.CFG["T"]):
        raise ValueError(f"day 需在 1~{engine.CFG['T']} 之间")

    def _num(key, cast=float, default=None):
        if key not in data or data[key] is None or data[key] == "":
            if default is not None:
                return default
            raise ValueError(f"缺少字段: {key}")
        return cast(data[key])

    cust_id = data.get("cust_id")
    if cust_id is None or cust_id == "":
        raise ValueError("缺少字段: cust_id")

    work_max = float(engine.CFG["WORK_MINUTES"])
    tw_start = _num("tw_start")
    tw_end = _num("tw_end")
    if not (0 <= tw_start < tw_end <= work_max):
        raise ValueError(f"时间窗需满足 0 <= tw_start < tw_end <= {work_max}")

    return {
        "day": d,
        "cust_id": int(cust_id) if str(cust_id).lstrip("-").isdigit() else cust_id,
        "lon": _num("lon"),
        "lat": _num("lat"),
        "demand": _num("demand"),
        "service": _num("service"),
        "tw_start": tw_start,
        "tw_end": tw_end,
        "cust_name": str(data.get("cust_name") or ""),
        "updated_at": datetime.now(),
    }


def _import_csv_to_mongo(force: bool = False) -> Dict[str, Any]:
    db = get_db()
    col = db[MONGO_ORDERS]
    existing = col.count_documents({})
    if existing > 0 and not force:
        return {"imported": 0, "skipped": True, "total": existing}

    if force:
        col.delete_many({})

    inserted = 0
    T = int(engine.CFG["T"])
    for t in range(1, T + 1):
        path = engine.CFG["CSV_PATTERN"].format(t)
        full = os.path.join(BASE_DIR, path)
        if not os.path.exists(full):
            continue
        df = engine.read_csv_smart(full)
        if "cust_name" not in df.columns:
            df["cust_name"] = ""
        docs = []
        for _, row in df.iterrows():
            docs.append({
                "day": t,
                "cust_id": int(row["cust_id"]) if pd.notna(row["cust_id"]) else row["cust_id"],
                "lon": float(row["lon"]),
                "lat": float(row["lat"]),
                "demand": float(row["demand"]),
                "service": float(row["service"]),
                "tw_start": float(row["tw_start"]),
                "tw_end": float(row["tw_end"]),
                "cust_name": str(row.get("cust_name") or ""),
                "updated_at": datetime.now(),
            })
        if docs:
            col.insert_many(docs)
            inserted += len(docs)

    # 同步写回 CSV，保证命令行脚本也能用最新数据
    _export_mongo_to_csv()
    return {"imported": inserted, "skipped": False, "total": col.count_documents({})}


def _export_mongo_to_csv():
    db = get_db()
    T = int(engine.CFG["T"])
    for t in range(1, T + 1):
        rows = list(db[MONGO_ORDERS].find({"day": t}).sort("cust_id", ASCENDING))
        records = []
        for r in rows:
            records.append({k: r.get(k, "" if k == "cust_name" else None) for k in ORDER_FIELDS})
        df = pd.DataFrame(records, columns=ORDER_FIELDS)
        path = os.path.join(BASE_DIR, engine.CFG["CSV_PATTERN"].format(t))
        df.to_csv(path, index=False, encoding="utf-8-sig")


def _load_day_frames_from_mongo() -> List[pd.DataFrame]:
    db = get_db()
    T = int(engine.CFG["T"])
    frames = []
    for t in range(1, T + 1):
        rows = list(db[MONGO_ORDERS].find({"day": t}).sort("cust_id", ASCENDING))
        if not rows:
            raise ValueError(f"第 {t} 天没有订单数据，请先在订单管理中导入或新增")
        records = [{k: r.get(k, "" if k == "cust_name" else None) for k in ORDER_FIELDS} for r in rows]
        frames.append(pd.DataFrame(records))
    return frames


def _ensure_orders_seeded():
    try:
        db = get_db()
        if db[MONGO_ORDERS].count_documents({}) == 0:
            _import_csv_to_mongo(force=False)
    except Exception:
        pass


def _read_csv_safe(path: str) -> List[Dict[str, Any]]:
    full = os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        return []
    try:
        df = pd.read_csv(full)
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception:
        return []


def _load_existing_results() -> Optional[Dict[str, Any]]:
    summary = _read_csv_safe(engine.CFG["RUN_SUMMARY_CSV"])
    if not summary:
        return None
    runs = _read_csv_safe(engine.CFG["RUN_RESULTS_CSV"])
    best_runs = _read_csv_safe(engine.CFG["BEST_RUN_SUMMARY_CSV"])
    alns = _read_csv_safe(engine.CFG["ALNS_IMPROV_PER_RUN_CSV"])
    alns_summary = _read_csv_safe(engine.CFG["ALNS_IMPROV_SUMMARY_CSV"])
    n_runs = 0
    if runs:
        n_runs = int(max(int(r.get("run_id", 0)) for r in runs) + 1)
    return {
        "n_runs": n_runs,
        "summary": summary,
        "best_runs": best_runs,
        "runs": runs,
        "alns_improvement": alns,
        "alns_improvement_summary": alns_summary,
        "outputs": {
            "run_results": engine.CFG["RUN_RESULTS_CSV"],
            "run_summary": engine.CFG["RUN_SUMMARY_CSV"],
            "best_run_summary": engine.CFG["BEST_RUN_SUMMARY_CSV"],
            "alns_improv_per_run": engine.CFG["ALNS_IMPROV_PER_RUN_CSV"],
            "alns_improv_summary": engine.CFG["ALNS_IMPROV_SUMMARY_CSV"],
            "pareto_png": engine.CFG["REP_PARETO_PNG"],
            "worktime_png": engine.CFG["REP_WORKTIME_PNG"],
            "map_html": engine.CFG["MAP_OUT_HTML"],
            "timeline_csv": engine.CFG["BEST_STAGE2_TIMELINE_CSV"],
            "route_seq_csv": engine.CFG["BEST_STAGE2_ROUTE_SEQ_CSV"],
        },
        "from_cache": True,
    }


def _run_worker(n_runs: int, overrides: Dict[str, Any], use_mongo: bool):
    def on_progress(payload: Dict[str, Any]):
        phase = payload.get("phase", "")
        msg = payload.get("message", "")
        n = int(payload.get("n_runs", n_runs) or n_runs)
        run_id = payload.get("run_id")

        with _job_lock:
            if phase == "init":
                _job["progress"] = 2.0
            elif phase == "instance_ready":
                _job["progress"] = 8.0
            elif phase == "run_start" and run_id is not None:
                _job["current_run"] = int(run_id) + 1
                _job["progress"] = 8.0 + (int(run_id) / max(n, 1)) * 82.0
            elif phase == "run_done" and run_id is not None:
                _job["current_run"] = int(run_id) + 1
                _job["progress"] = 8.0 + ((int(run_id) + 1) / max(n, 1)) * 82.0
            elif phase == "summarize":
                _job["progress"] = 92.0
            elif phase == "done":
                _job["progress"] = 100.0

            if msg:
                _job["message"] = msg
                _push_log(msg)

    try:
        with _job_lock:
            _job["status"] = "running"
            _job["progress"] = 1.0
            _job["n_runs"] = n_runs
            _job["current_run"] = 0
            _job["message"] = f"准备启动 {n_runs} 次实验..."
            _job["started_at"] = datetime.now().isoformat(timespec="seconds")
            _job["finished_at"] = None
            _job["error"] = None
            _job["result"] = None
            _job["stop_requested"] = False
            _job["logs"] = []
            _push_log(f"实验任务已启动 | N_RUNS={n_runs}")

        _stop_event.clear()

        day_frames = None
        if use_mongo:
            _push_log("从 MongoDB 加载订单数据...")
            day_frames = _load_day_frames_from_mongo()
            _export_mongo_to_csv()
            _push_log("订单已同步到 CSV，开始构建路网矩阵...")

        cfg_overrides = {"N_RUNS": n_runs}
        cfg_overrides.update(overrides)
        # 不改变进程工作目录，读写均限定在本模块目录。
        for key in ("CSV_PATTERN", *OUTPUT_PATH_KEYS):
            cfg_overrides[key] = os.path.join(BASE_DIR, engine.CFG[key])
        result = engine.run_pipeline(
            cfg_overrides=cfg_overrides,
            on_progress=on_progress,
            should_stop=_stop_event.is_set,
            day_frames=day_frames,
        )
        result["outputs"] = {
            key: os.path.basename(path) for key, path in result.get("outputs", {}).items()
        }

        with _job_lock:
            if _stop_event.is_set():
                _job["status"] = "stopped"
                _job["message"] = "实验已停止"
                _push_log("<span style='color:#e6a23c'>实验已由用户停止</span>", "warn")
            else:
                _job["status"] = "done"
                _job["progress"] = 100.0
                _job["message"] = "实验完成"
                _job["result"] = result
                _push_log(
                    f"<span style='color:#67c23a'>全部完成</span> | "
                    f"代表性运行=#{result['rep_run_id']} | "
                    f"最优Stage2运行=#{result['best_stage2_run_id']}",
                    "success",
                )
            _job["finished_at"] = datetime.now().isoformat(timespec="seconds")
    except engine.ExperimentCancelled as e:
        with _job_lock:
            _job["status"] = "stopped"
            _job["message"] = str(e)
            _job["finished_at"] = datetime.now().isoformat(timespec="seconds")
            _push_log(f"<span style='color:#e6a23c'>已停止: {e}</span>", "warn")
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()}"
        with _job_lock:
            _job["status"] = "error"
            _job["message"] = f"实验失败: {e}"
            _job["error"] = err
            _job["finished_at"] = datetime.now().isoformat(timespec="seconds")
            _push_log(f"<span style='color:#f56c6c'>ERROR: {e}</span>", "error")


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "vrp_lab.html")


@app.route("/api/config", methods=["GET"])
def api_config():
    cfg = engine.CFG
    mongo_ok = False
    mongo_msg = ""
    order_count = 0
    try:
        db = get_db()
        mongo_ok = True
        order_count = db[MONGO_ORDERS].count_documents({})
        if order_count == 0:
            info = _import_csv_to_mongo(force=False)
            order_count = info["total"]
            mongo_msg = f"已从 CSV 初始化 {info['imported']} 条订单"
        else:
            mongo_msg = f"已连接，订单 {order_count} 条"
    except Exception as e:
        mongo_msg = str(e)

    return jsonify({
        "defaults": {
            "N_RUNS": cfg["N_RUNS"],
            "T": cfg["T"],
            "N_DEPOTS": cfg["N_DEPOTS"],
            "K_VEHICLES": cfg["K_VEHICLES"],
            "VEHICLE_CAP": cfg["VEHICLE_CAP"],
            "SEED": cfg["SEED"],
            "N_PARTICLES": cfg["N_PARTICLES"],
            "N_ITERS": cfg["N_ITERS"],
            "ALNS_ITERS": cfg["ALNS_ITERS"],
            "WORK_MINUTES": cfg["WORK_MINUTES"],
            "OSRM_BASE": cfg["OSRM_BASE"],
        },
        "csv_files": [cfg["CSV_PATTERN"].format(t + 1) for t in range(int(cfg["T"]))],
        "has_cached_results": os.path.exists(os.path.join(BASE_DIR, cfg["RUN_SUMMARY_CSV"])),
        "mongo": {
            "connected": mongo_ok,
            "uri": MONGO_URI,
            "db": MONGO_DB_NAME,
            "collection": MONGO_ORDERS,
            "order_count": order_count,
            "message": mongo_msg,
        },
        "order_fields": ORDER_FIELDS,
    })


@app.route("/api/system/health", methods=["GET"])
def api_health():
    mongo = {"connected": False, "uri": MONGO_URI, "db": MONGO_DB_NAME}
    try:
        db = get_db()
        mongo["connected"] = True
        mongo["order_count"] = db[MONGO_ORDERS].count_documents({})
    except Exception as e:
        mongo["error"] = str(e)
    return jsonify({"mongo": mongo})


# ===================== 订单管理 =====================
@app.route("/api/orders", methods=["GET"])
def api_orders_list():
    try:
        _ensure_orders_seeded()
        db = get_db()
        day = request.args.get("day")
        q: Dict[str, Any] = {}
        if day not in (None, "", "all"):
            q["day"] = int(day)
        keyword = (request.args.get("q") or "").strip()
        if keyword:
            q["$or"] = [
                {"cust_name": {"$regex": keyword, "$options": "i"}},
                {"cust_id": keyword if not keyword.isdigit() else int(keyword)},
            ]
        rows = list(db[MONGO_ORDERS].find(q).sort([("day", ASCENDING), ("cust_id", ASCENDING)]))
        return jsonify({"items": [_serialize_order(r) for r in rows], "total": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders/stats", methods=["GET"])
def api_orders_stats():
    try:
        _ensure_orders_seeded()
        db = get_db()
        T = int(engine.CFG["T"])
        by_day = []
        for t in range(1, T + 1):
            cnt = db[MONGO_ORDERS].count_documents({"day": t})
            active = db[MONGO_ORDERS].count_documents({"day": t, "demand": {"$gt": 0}})
            by_day.append({"day": t, "total": cnt, "active": active})
        return jsonify({
            "total": db[MONGO_ORDERS].count_documents({}),
            "by_day": by_day,
            "work_minutes": engine.CFG["WORK_MINUTES"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders", methods=["POST"])
def api_orders_create():
    try:
        data = request.get_json(silent=True) or {}
        doc = _normalize_order_payload(data)
        db = get_db()
        exists = db[MONGO_ORDERS].find_one({"day": doc["day"], "cust_id": doc["cust_id"]})
        if exists:
            return jsonify({"error": f"第{doc['day']}天已存在客户 {doc['cust_id']}"}), 409
        res = db[MONGO_ORDERS].insert_one(doc)
        _export_mongo_to_csv()
        saved = db[MONGO_ORDERS].find_one({"_id": res.inserted_id})
        return jsonify({"status": "ok", "item": _serialize_order(saved)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders/<oid>", methods=["PUT"])
def api_orders_update(oid: str):
    try:
        data = request.get_json(silent=True) or {}
        db = get_db()
        old = db[MONGO_ORDERS].find_one({"_id": ObjectId(oid)})
        if not old:
            return jsonify({"error": "订单不存在"}), 404
        merged = {**old, **data, "day": data.get("day", old["day"])}
        doc = _normalize_order_payload(merged, day=int(merged["day"]))
        clash = db[MONGO_ORDERS].find_one({
            "day": doc["day"],
            "cust_id": doc["cust_id"],
            "_id": {"$ne": ObjectId(oid)},
        })
        if clash:
            return jsonify({"error": f"第{doc['day']}天已存在客户 {doc['cust_id']}"}), 409
        db[MONGO_ORDERS].update_one({"_id": ObjectId(oid)}, {"$set": doc})
        _export_mongo_to_csv()
        saved = db[MONGO_ORDERS].find_one({"_id": ObjectId(oid)})
        return jsonify({"status": "ok", "item": _serialize_order(saved)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders/<oid>", methods=["DELETE"])
def api_orders_delete(oid: str):
    try:
        db = get_db()
        res = db[MONGO_ORDERS].delete_one({"_id": ObjectId(oid)})
        if res.deleted_count == 0:
            return jsonify({"error": "订单不存在"}), 404
        _export_mongo_to_csv()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders/import-csv", methods=["POST"])
def api_orders_import_csv():
    try:
        data = request.get_json(silent=True) or {}
        force = bool(data.get("force", True))
        info = _import_csv_to_mongo(force=force)
        return jsonify({"status": "ok", **info})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders/export-csv", methods=["POST"])
def api_orders_export_csv():
    try:
        _export_mongo_to_csv()
        return jsonify({"status": "ok", "message": "已同步到 customers_day*.csv"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== 实验控制 =====================
@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    try:
        n_runs = int(data.get("n_runs", engine.CFG["N_RUNS"]))
    except (TypeError, ValueError):
        return jsonify({"error": "实验次数必须是整数"}), 400

    if n_runs < 1 or n_runs > 50:
        return jsonify({"error": "实验次数需在 1~50 之间"}), 400

    overrides: Dict[str, Any] = {}
    for key in ("SEED", "N_PARTICLES", "N_ITERS", "ALNS_ITERS", "K_VEHICLES", "VEHICLE_CAP"):
        if key.lower() in data or key in data:
            raw = data.get(key.lower(), data.get(key))
            if raw is not None and raw != "":
                try:
                    overrides[key] = int(raw) if key != "VEHICLE_CAP" else float(raw)
                except (TypeError, ValueError):
                    return jsonify({"error": f"参数 {key} 格式错误"}), 400

    use_mongo = bool(data.get("use_mongo", True))

    with _job_lock:
        if _job["status"] == "running":
            return jsonify({"error": "已有实验正在运行，请先停止或等待完成"}), 409

    t = threading.Thread(target=_run_worker, args=(n_runs, overrides, use_mongo), daemon=True)
    t.start()
    return jsonify({"status": "started", "n_runs": n_runs, "use_mongo": use_mongo})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with _job_lock:
        if _job["status"] != "running":
            return jsonify({"status": _job["status"], "message": "当前没有运行中的实验"})
        _job["stop_requested"] = True
        _job["message"] = "正在停止实验（将在当前轮次结束后中断）..."
        _push_log("<span style='color:#e6a23c'>收到停止请求，等待当前轮次结束...</span>", "warn")
    _stop_event.set()
    return jsonify({"status": "stopping", "message": "停止信号已发送"})


@app.route("/api/status", methods=["GET"])
def api_status():
    with _job_lock:
        payload = {
            "status": _job["status"],
            "progress": _job["progress"],
            "n_runs": _job["n_runs"],
            "current_run": _job["current_run"],
            "message": _job["message"],
            "logs": list(_job["logs"][-80:]),
            "started_at": _job["started_at"],
            "finished_at": _job["finished_at"],
            "error": _job["error"],
            "has_result": _job["result"] is not None,
            "stop_requested": _job["stop_requested"],
        }
    return jsonify(payload)


@app.route("/api/results", methods=["GET"])
def api_results():
    with _job_lock:
        if _job["result"] is not None:
            return jsonify({"status": _job["status"], "data": copy.deepcopy(_job["result"])})

    cached = _load_existing_results()
    if cached:
        return jsonify({"status": "cached", "data": cached})
    return jsonify({"status": "empty", "data": None})


@app.route("/api/artifact/<path:filename>", methods=["GET"])
def api_artifact(filename: str):
    safe = os.path.basename(filename)
    allowed = {engine.CFG[key] for key in OUTPUT_PATH_KEYS}
    if filename != safe or safe not in allowed:
        return jsonify({"error": "文件不存在"}), 404
    path = os.path.join(BASE_DIR, safe)
    if not os.path.exists(path):
        return jsonify({"error": "文件不存在"}), 404
    return send_from_directory(BASE_DIR, safe)


if __name__ == "__main__":
    print("=" * 50)
    print("  多周期车辆路径实验平台")
    print("  http://127.0.0.1:5000")
    print(f"  MongoDB: {MONGO_URI} / {MONGO_DB_NAME}")
    print("=" * 50)
    try:
        _ensure_orders_seeded()
        print("[MongoDB] 就绪")
    except Exception as e:
        print(f"[MongoDB] 暂未连接: {e}")
        print("  请先启动本机 MongoDB 服务后再刷新页面：")
        print("  Start-Service MongoDB")
        print(f"  将使用数据库: {MONGO_DB_NAME}")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
