"""
日期：2026年03月31日
"""
# -*- coding: utf-8 -*-
"""
多周期(T=5) Stage-1（CCDR-PSO）+ Stage-2（MO-ALNS）+ 两个 Baseline 对比
使用 OSRM 路网距离/时间，并用 Folium 输出地图。

1) 运行 10 次实验（可配置）
2) 三种策略在同一次运行中共享同一份 Stage-1 结果
3) 输出 10 次运行明细、均值/标准差汇总、各策略最优一次
4) 帕累托前沿图与车辆工时直方图采用“代表性运行”
5) 地图采用“主算法 Balanced 解成本最小”的那次运行
6) 地图支持多底图，客户标签在缩小时自动隐藏
7) 保存最优主算法 Balanced 的车辆路径位置变化顺序和到达时间顺序

输入：
- customers_day1.csv ... customers_day5.csv（同目录）
字段必须包含：
  cust_id, lon, lat, demand, service, tw_start, tw_end

时间窗单位 = 分钟
0 = 08:00
WORK_MINUTES = 600 表示 18:00
"""

import math
import random
import time
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import colorsys

import numpy as np
import pandas as pd
import requests
import folium
from folium.features import DivIcon
import matplotlib.pyplot as plt


# =========================================================
# CONFIG
# =========================================================
CFG: Dict[str, Any] = {
    # ---- multi-period ----
    "T": 5,
    "CSV_PATTERN": "customers_day{}.csv",
    "SEED": 2026,
    "N_RUNS": 10,

    # workday minutes: 0 = 08:00, 600 = 18:00
    "WORK_MINUTES": 600,
    "DEPOT_TW": (0.0, 600.0),

    # depots / vehicles ----
    "N_DEPOTS": 4,
    "K_VEHICLES": 18,

    # vehicle capability ----
    "VEHICLE_CAP": 12.0,

    # cost weights ----
    "W_DIST": 10.0,
    "W_ROUTE_FIXED": 200.0,
    "W_TW_LATE": 50.0,
    "W_DEPOT_LATE": 30.0,
    "W_CAPACITY": 5000.0,

    # Stage-1 PSO ----
    "N_PARTICLES": 60,
    "N_ITERS": 800,
    "W": 0.72,
    "C1": 1.49,
    "C2": 1.49,
    "SWITCH_RATIO": 0.00,

    # split / repair ----
    "CUT_BIAS_SCALE": 120.0,
    "FORCE_CUT_IF_CAPACITY": True,
    "DO_MERGE_REPAIR": True,
    "MERGE_MAX_ROUNDS": 25,
    "MERGE_REQUIRE_IMPROVE": True,

    # Baseline1 overnight dispatch ----
    "DISPATCH_COST_PER_DIST": 20.0,

    # Stage-2 main algorithm: MO-ALNS ----
    "ALNS_ITERS": 25000,
    "REMOVE_FRAC_RANGE": (0.18, 0.45),
    "DESTROY_DAY_FOCUS_PROB": 0.60,
    "HEAVY_VEH_TOPK": 5,
    "REPAIR_ALPHA_AK": 0.020,
    "REPAIR_BETA_WT": 0.000,
    "END_GAMMA_WT": 0.0015,
    "ETA_LOOKAHEAD": 0.10,

    # ALNS acceptance ----
    "TEMP0": 0.40,
    "TEMP_DECAY": 0.99965,
    "REHEAT_EVERY": 5000,
    "REHEAT_FACTOR": 1.35,

    # Adaptive weights update ----
    "WEIGHT_UPDATE_EVERY": 250,
    "WEIGHT_R": 0.20,
    "REWARD_BEST": 8.0,
    "REWARD_ARCHIVE": 5.0,
    "REWARD_ACCEPT": 1.0,

    # Multiobjective scalarization ----
    "LAMBDA_LIST": [0.0, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0],

    # Pareto archive ----
    "PARETO_MAX_KEEP": 700,
    "PARETO_ROUND_COST": 2,
    "PARETO_ROUND_VAR": 2,

    # ---- OSRM ----
    "OSRM_BASE": "https://router.project-osrm.org",
    "OSRM_TIMEOUT": 60,
    "OSRM_TABLE_MAX_COORDS": 80,
    "OSRM_RETRIES": 3,
    "OSRM_RETRY_SLEEP_SEC": 1.2,

    # ---- map ----
    "MAP_ZOOM": 11,
    "MAP_LABEL_MIN_ZOOM": 13,
    "MAP_OUT_HTML": "best_stage2_routes_map.html",
    "CUSTOMER_LABEL_EVERY": 1,
    "INACTIVE_COLOR": "#9e9e9e",
    "ACTIVE_COLOR": "#1f77b4",

    # ---- outputs ----
    "RUN_RESULTS_CSV": "multi_run_results.csv",
    "RUN_SUMMARY_CSV": "multi_run_summary.csv",
    "BEST_RUN_SUMMARY_CSV": "best_run_summary.csv",
    "ALNS_IMPROV_PER_RUN_CSV": "alns_improvement_per_run.csv",
    "ALNS_IMPROV_SUMMARY_CSV": "alns_improvement_summary.csv",
    "REP_PARETO_PNG": "representative_pareto_front.png",
    "REP_WORKTIME_PNG": "representative_vehicle_worktime_hist.png",
    "BEST_STAGE2_TIMELINE_CSV": "best_stage2_balanced_vehicle_timeline.csv",
    "BEST_STAGE2_ROUTE_SEQ_CSV": "best_stage2_balanced_vehicle_route_sequence.csv",
}


OSRM_SESSION = requests.Session()
OSRM_SESSION.headers.update({"User-Agent": "ccdr-pso-moalns-vrp/1.0"})


# =========================================================
# DATA STRUCTURES
# =========================================================
@dataclass
class Depot:
    idx: int
    lon: float
    lat: float
    tw: Tuple[float, float]


@dataclass
class Customer:
    idx: int
    cust_id: Any
    lon: float
    lat: float
    demand: float
    service: float
    tw: Tuple[float, float]


# =========================================================
# CSV READER
# =========================================================
def read_csv_smart(path: str) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk", "cp936", "latin1"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as e:
            last_err = e
    raise last_err


# =========================================================
# OSRM HELPERS
# =========================================================
def _requests_get_with_retries(url: str, params: Dict[str, Any], timeout: int, cfg: Dict[str, Any]) -> requests.Response:
    retries = int(cfg.get("OSRM_RETRIES", 3))
    sleep_s = float(cfg.get("OSRM_RETRY_SLEEP_SEC", 1.0))
    last_err = None
    for k in range(retries):
        try:
            r = OSRM_SESSION.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            if k < retries - 1:
                time.sleep(sleep_s * (1.0 + 0.5 * k))
    raise last_err


def osrm_table_blockwise(base: str, coords: List[Tuple[float, float]], max_coords: int, timeout: int, cfg: Dict[str, Any]):
    """
    Build full N x N distance/time matrices using OSRM table calls.
    优先：若 N <= max_coords，则一次性请求全部到全部。
    否则：分块。
    Returns:
      dist_km: (N,N)
      dur_min: (N,N)
    """
    N = len(coords)
    if N == 0:
        return np.zeros((0, 0), dtype=float), np.zeros((0, 0), dtype=float)

    if N <= max_coords:
        coord_str = ";".join([f"{lon},{lat}" for lon, lat in coords])
        url = f"{base}/table/v1/driving/{coord_str}"
        params = {"annotations": "distance,duration"}
        r = _requests_get_with_retries(url, params=params, timeout=timeout, cfg=cfg)
        js = r.json()
        d = js.get("distances")
        t = js.get("durations")
        if d is None or t is None:
            raise RuntimeError(f"OSRM table missing distances/durations: keys={list(js.keys())}")
        dist_km = np.array(d, dtype=float) / 1000.0
        dur_min = np.array(t, dtype=float) / 60.0
        dist_km[~np.isfinite(dist_km)] = 1e6
        dur_min[~np.isfinite(dur_min)] = 1e6
        return dist_km, dur_min

    dist_km = np.zeros((N, N), dtype=float)
    dur_min = np.zeros((N, N), dtype=float)

    blocks = []
    i = 0
    while i < N:
        j = min(N, i + max_coords)
        blocks.append((i, j))
        i = j

    for (a0, a1) in blocks:
        for (b0, b1) in blocks:
            na = a1 - a0
            nb = b1 - b0

            if a0 == b0 and a1 == b1:
                coords_req = coords[a0:a1]
                coord_str = ";".join([f"{lon},{lat}" for lon, lat in coords_req])
                url = f"{base}/table/v1/driving/{coord_str}"
                params = {"annotations": "distance,duration"}
                r = _requests_get_with_retries(url, params=params, timeout=timeout, cfg=cfg)
                js = r.json()
                dblock = js.get("distances")
                tblock = js.get("durations")
                if dblock is None or tblock is None:
                    raise RuntimeError(f"OSRM table missing distances/durations: keys={list(js.keys())}")

                for ii in range(na):
                    for jj in range(na):
                        dm = dblock[ii][jj]
                        ts = tblock[ii][jj]
                        if dm is None or ts is None:
                            dist_km[a0 + ii, a0 + jj] = 1e6
                            dur_min[a0 + ii, a0 + jj] = 1e6
                        else:
                            dist_km[a0 + ii, a0 + jj] = float(dm) / 1000.0
                            dur_min[a0 + ii, a0 + jj] = float(ts) / 60.0
            else:
                coords_req = coords[a0:a1] + coords[b0:b1]
                coord_str = ";".join([f"{lon},{lat}" for lon, lat in coords_req])
                url = f"{base}/table/v1/driving/{coord_str}"
                params = {
                    "annotations": "distance,duration",
                    "sources": ";".join(map(str, range(0, na))),
                    "destinations": ";".join(map(str, range(na, na + nb))),
                }
                r = _requests_get_with_retries(url, params=params, timeout=timeout, cfg=cfg)
                js = r.json()
                dblock = js.get("distances")
                tblock = js.get("durations")
                if dblock is None or tblock is None:
                    raise RuntimeError(f"OSRM table missing distances/durations: keys={list(js.keys())}")

                for ii in range(na):
                    for jj in range(nb):
                        dm = dblock[ii][jj]
                        ts = tblock[ii][jj]
                        if dm is None or ts is None:
                            dist_km[a0 + ii, b0 + jj] = 1e6
                            dur_min[a0 + ii, b0 + jj] = 1e6
                        else:
                            dist_km[a0 + ii, b0 + jj] = float(dm) / 1000.0
                            dur_min[a0 + ii, b0 + jj] = float(ts) / 60.0

    return dist_km, dur_min


_ROUTE_CACHE = {}


def osrm_route_geometry(base: str, coords: List[Tuple[float, float]], timeout: int, cfg: Dict[str, Any]):
    """
    Get route geometry from OSRM route API as GeoJSON LineString.
    coords: ordered list of (lon, lat), len>=2
    """
    if len(coords) < 2:
        return None
    key = tuple((round(lon, 6), round(lat, 6)) for lon, lat in coords)
    if key in _ROUTE_CACHE:
        return _ROUTE_CACHE[key]

    coord_str = ";".join([f"{lon},{lat}" for lon, lat in coords])
    url = f"{base}/route/v1/driving/{coord_str}"
    params = {"overview": "full", "geometries": "geojson"}
    r = _requests_get_with_retries(url, params=params, timeout=timeout, cfg=cfg)
    js = r.json()
    if not js.get("routes"):
        _ROUTE_CACHE[key] = None
        return None
    geom = js["routes"][0]["geometry"]
    _ROUTE_CACHE[key] = geom
    return geom


# =========================================================
# ROUTE SIMULATION
# =========================================================
def minute_to_clock_str(x: float) -> str:
    total = int(round(float(x)))
    hh = 8 + total // 60
    mm = total % 60
    return f"{hh:02d}:{mm:02d}"


def simulate_route(dep_start, dep_end, route, depots, customers,
                   dist_dc_km, dist_cc_km, dist_cd_km,
                   time_dc_min, time_cc_min, time_cd_min,
                   return_timeline: bool = False):
    if not route:
        empty_timeline = []
        return 0.0, depots[dep_start].tw[0], 0.0, 0.0, 0.0, empty_timeline

    t = depots[dep_start].tw[0]
    dist_total = 0.0
    tw_late_sum = 0.0
    load = 0.0
    prev = None
    timeline = []

    if return_timeline:
        timeline.append({
            "node_type": "depot_start",
            "node_id": dep_start,
            "cust_id": None,
            "arrive_min": t,
            "start_service_min": t,
            "finish_min": t,
            "late_min": 0.0,
            "cum_dist_km": 0.0,
            "cum_load": 0.0,
        })

    for cid in route:
        c = customers[cid]
        load += c.demand

        if prev is None:
            d_km = dist_dc_km[dep_start, cid]
            dt_min = time_dc_min[dep_start, cid]
        else:
            d_km = dist_cc_km[prev, cid]
            dt_min = time_cc_min[prev, cid]

        dist_total += d_km
        arrive = t + dt_min
        start = max(arrive, c.tw[0])
        late = max(0.0, start - c.tw[1])
        finish = start + c.service

        tw_late_sum += late
        t = finish
        prev = cid

        if return_timeline:
            timeline.append({
                "node_type": "customer",
                "node_id": cid,
                "cust_id": c.cust_id,
                "arrive_min": arrive,
                "start_service_min": start,
                "finish_min": finish,
                "late_min": late,
                "cum_dist_km": dist_total,
                "cum_load": load,
            })

    last = route[-1]
    d_back = dist_cd_km[last, dep_end]
    dt_back = time_cd_min[last, dep_end]
    dist_total += d_back
    back_time = t + dt_back

    depot_close = depots[dep_end].tw[1]
    depot_late = max(0.0, back_time - depot_close)

    if return_timeline:
        timeline.append({
            "node_type": "depot_end",
            "node_id": dep_end,
            "cust_id": None,
            "arrive_min": back_time,
            "start_service_min": back_time,
            "finish_min": back_time,
            "late_min": depot_late,
            "cum_dist_km": dist_total,
            "cum_load": load,
        })

    return dist_total, back_time, tw_late_sum, depot_late, load, timeline


def route_cost_and_stats(dep_start, dep_end, route, depots, customers,
                         dist_dc_km, dist_cc_km, dist_cd_km,
                         time_dc_min, time_cc_min, time_cd_min, cfg,
                         return_timeline: bool = False):
    if not route:
        stats = {
            "dist_km": 0.0,
            "back_time": depots[dep_start].tw[0],
            "tw_late_min": 0.0,
            "depot_late_min": 0.0,
            "load": 0.0,
            "cap_excess": 0.0,
            "worktime_min": 0.0,
            "fixed_cost": 0.0,
            "dist_cost": 0.0,
            "tw_late_cost": 0.0,
            "depot_late_cost": 0.0,
            "capacity_cost": 0.0,
            "penalty_cost": 0.0,
        }
        if return_timeline:
            stats["timeline"] = []
        return 0.0, stats

    dist_r, back_t, tw_late, depot_late, load, timeline = simulate_route(
        dep_start, dep_end, route, depots, customers,
        dist_dc_km, dist_cc_km, dist_cd_km,
        time_dc_min, time_cc_min, time_cd_min,
        return_timeline=return_timeline
    )
    cap_excess = max(0.0, load - float(cfg["VEHICLE_CAP"]))

    fixed_cost = float(cfg["W_ROUTE_FIXED"])
    dist_cost = float(cfg["W_DIST"]) * dist_r
    tw_late_cost = float(cfg["W_TW_LATE"]) * tw_late
    depot_late_cost = float(cfg["W_DEPOT_LATE"]) * depot_late
    capacity_cost = float(cfg["W_CAPACITY"]) * cap_excess
    penalty_cost = tw_late_cost + depot_late_cost + capacity_cost

    cost = fixed_cost + dist_cost + penalty_cost
    worktime = back_t - depots[dep_start].tw[0]
    stats = {
        "dist_km": dist_r,
        "back_time": back_t,
        "tw_late_min": tw_late,
        "depot_late_min": depot_late,
        "load": load,
        "cap_excess": cap_excess,
        "worktime_min": worktime,
        "fixed_cost": fixed_cost,
        "dist_cost": dist_cost,
        "tw_late_cost": tw_late_cost,
        "depot_late_cost": depot_late_cost,
        "capacity_cost": capacity_cost,
        "penalty_cost": penalty_cost
    }
    if return_timeline:
        stats["timeline"] = timeline
    return cost, stats


# =========================================================
# STAGE-1 HELPERS
# =========================================================
def assign_depots_balanced(pref_vals: np.ndarray, n_depots: int) -> np.ndarray:
    ranks = np.argsort(np.argsort(pref_vals))
    dep = (ranks * n_depots) // len(pref_vals)
    return np.clip(dep, 0, n_depots - 1)


def assign_depots_free(pref_vals: np.ndarray, n_depots: int) -> np.ndarray:
    z = (pref_vals + 4.0) / 8.0
    dep = np.floor(z * n_depots).astype(int)
    return np.clip(dep, 0, n_depots - 1)


def decode_cost_driven_split(order, dep_assign, cut, end_pref,
                            depots, customers,
                            dist_dc_km, dist_cc_km, dist_cd_km,
                            time_dc_min, time_cc_min, time_cd_min,
                            cfg, K):
    M = len(depots)
    routes_all = []
    route_idx_global = 0

    depot_to_seq = [[] for _ in range(M)]
    for cid in order:
        depot_to_seq[int(dep_assign[cid])].append(cid)

    def choose_end_from_pref(v: float):
        z = (v + 4.0) / 8.0
        d = int(np.floor(z * M))
        return int(np.clip(d, 0, M - 1))

    def choose_end(route_idx: int):
        idx = route_idx % len(end_pref)
        return choose_end_from_pref(float(end_pref[idx]))

    for d in range(M):
        seq = depot_to_seq[d]
        if not seq:
            continue

        cur = []
        cur_load = 0.0

        for cid in seq:
            dem = customers[cid].demand
            must_cut = (cur_load + dem > float(cfg["VEHICLE_CAP"])) if cfg["FORCE_CUT_IF_CAPACITY"] else False

            if len(cur) == 0:
                cur = [cid]
                cur_load = dem
                continue

            end_cur = choose_end(route_idx_global)
            cost_cur, _ = route_cost_and_stats(d, end_cur, cur, depots, customers,
                                               dist_dc_km, dist_cc_km, dist_cd_km,
                                               time_dc_min, time_cc_min, time_cd_min, cfg)

            cur_app = cur + [cid]
            end_app = choose_end(route_idx_global)
            cost_app, _ = route_cost_and_stats(d, end_app, cur_app, depots, customers,
                                               dist_dc_km, dist_cc_km, dist_cd_km,
                                               time_dc_min, time_cc_min, time_cd_min, cfg)
            delta_append = cost_app - cost_cur

            end_new = choose_end(route_idx_global + 1)
            cost_new, _ = route_cost_and_stats(d, end_new, [cid], depots, customers,
                                               dist_dc_km, dist_cc_km, dist_cd_km,
                                               time_dc_min, time_cc_min, time_cd_min, cfg)
            delta_cut = cost_new

            bias = - float(cfg["CUT_BIAS_SCALE"]) * float(cut[cid])
            if must_cut or (delta_cut + bias < delta_append):
                _, stats = route_cost_and_stats(d, end_cur, cur, depots, customers,
                                                dist_dc_km, dist_cc_km, dist_cd_km,
                                                time_dc_min, time_cc_min, time_cd_min, cfg)
                routes_all.append({"start": d, "end": end_cur, "route": cur, **stats})
                route_idx_global += 1
                cur = [cid]
                cur_load = dem
            else:
                cur = cur_app
                cur_load += dem

        if len(cur) > 0:
            end_final = choose_end(route_idx_global)
            _, stats = route_cost_and_stats(d, end_final, cur, depots, customers,
                                            dist_dc_km, dist_cc_km, dist_cd_km,
                                            time_dc_min, time_cc_min, time_cd_min, cfg)
            routes_all.append({"start": d, "end": end_final, "route": cur, **stats})
            route_idx_global += 1

    return routes_all


def merge_repair_same_depot(routes_all, depots, customers,
                           dist_dc_km, dist_cc_km, dist_cd_km,
                           time_dc_min, time_cc_min, time_cd_min,
                           cfg):
    if not cfg["DO_MERGE_REPAIR"]:
        return routes_all
    if len(routes_all) <= 1:
        return routes_all

    def full_cost(r):
        c, _ = route_cost_and_stats(r["start"], r["end"], r["route"], depots, customers,
                                    dist_dc_km, dist_cc_km, dist_cd_km,
                                    time_dc_min, time_cc_min, time_cd_min, cfg)
        return c

    for _ in range(int(cfg["MERGE_MAX_ROUNDS"])):
        n = len(routes_all)
        if n <= 1:
            break

        costs = [full_cost(routes_all[i]) for i in range(n)]
        best_delta = 0.0
        best_pair = None
        best_merged = None

        for i in range(n):
            for j in range(i + 1, n):
                A = routes_all[i]
                B = routes_all[j]
                if A["start"] != B["start"]:
                    continue
                dep_start = A["start"]
                merged_seq = A["route"] + B["route"]
                end_d = A["end"]

                c_m, st = route_cost_and_stats(dep_start, end_d, merged_seq, depots, customers,
                                               dist_dc_km, dist_cc_km, dist_cd_km,
                                               time_dc_min, time_cc_min, time_cd_min, cfg)
                delta = c_m - (costs[i] + costs[j])

                if delta < best_delta:
                    best_delta = delta
                    best_pair = (i, j)
                    best_merged = {"start": dep_start, "end": end_d, "route": merged_seq, **st}

        if best_pair is None:
            break

        i, j = best_pair
        for idx in sorted([i, j], reverse=True):
            routes_all.pop(idx)
        routes_all.append(best_merged)

    repaired = []
    for r in routes_all:
        _, st = route_cost_and_stats(r["start"], r["end"], r["route"], depots, customers,
                                     dist_dc_km, dist_cc_km, dist_cd_km,
                                     time_dc_min, time_cc_min, time_cd_min, cfg)
        repaired.append({"start": r["start"], "end": r["end"], "route": r["route"], **st})
    return repaired


def evaluate_particle_day(x, depots, customers,
                          dist_dc_km, dist_cc_km, dist_cd_km,
                          time_dc_min, time_cc_min, time_cd_min,
                          cfg, use_free_assignment, K):
    M = len(depots)
    N = len(customers)

    keys = x[0:N]
    pref = x[N:2*N]
    cut = x[2*N:3*N]
    end_pref = x[3*N:3*N+K]

    order = list(np.argsort(keys))
    dep_assign = assign_depots_free(pref, M) if use_free_assignment else assign_depots_balanced(pref, M)

    routes = decode_cost_driven_split(order, dep_assign, cut, end_pref,
                                      depots, customers,
                                      dist_dc_km, dist_cc_km, dist_cd_km,
                                      time_dc_min, time_cc_min, time_cd_min,
                                      cfg, K)
    routes = merge_repair_same_depot(routes, depots, customers,
                                     dist_dc_km, dist_cc_km, dist_cd_km,
                                     time_dc_min, time_cc_min, time_cd_min,
                                     cfg)

    refined = []
    total_cost = 0.0
    for r in routes:
        seq = r["route"]
        best_cost = None
        best_ds, best_de, best_st = None, None, None
        for ds in range(M):
            for de in range(M):
                c, st = route_cost_and_stats(ds, de, seq, depots, customers,
                                             dist_dc_km, dist_cc_km, dist_cd_km,
                                             time_dc_min, time_cc_min, time_cd_min, cfg)
                if best_cost is None or c < best_cost:
                    best_cost = c
                    best_ds, best_de, best_st = ds, de, st
        refined.append({"start": best_ds, "end": best_de, "route": seq, **best_st})
        total_cost += float(best_cost)

    return total_cost, {"cost": total_cost, "routes": refined}


class PSO_DaySolver:
    def __init__(self, depots, customers,
                 dist_dc_km, dist_cc_km, dist_cd_km,
                 time_dc_min, time_cc_min, time_cd_min,
                 cfg, seed, K):
        self.depots = depots
        self.customers = customers
        self.dist_dc_km = dist_dc_km
        self.dist_cc_km = dist_cc_km
        self.dist_cd_km = dist_cd_km
        self.time_dc_min = time_dc_min
        self.time_cc_min = time_cc_min
        self.time_cd_min = time_cd_min
        self.cfg = cfg

        self.N = len(customers)
        self.K = K
        self.dim = 3 * self.N + self.K

        self.n_particles = int(cfg["N_PARTICLES"])
        self.iters = int(cfg["N_ITERS"])
        self.w = float(cfg["W"])
        self.c1 = float(cfg["C1"])
        self.c2 = float(cfg["C2"])
        self.switch_iter = int(np.floor(float(cfg["SWITCH_RATIO"]) * self.iters))

        self.rng = np.random.default_rng(seed)
        self.X = self.rng.uniform(-1, 1, size=(self.n_particles, self.dim))
        self.V = self.rng.uniform(-0.3, 0.3, size=(self.n_particles, self.dim))

        self.pbest_X = self.X.copy()
        self.pbest_cost = np.full(self.n_particles, np.inf)
        self.gbest_X = None
        self.gbest_cost = np.inf
        self.gbest_summary = None

    def optimize(self):
        for it in range(self.iters):
            use_free = (it >= self.switch_iter)

            for p in range(self.n_particles):
                cost, summary = evaluate_particle_day(
                    self.X[p], self.depots, self.customers,
                    self.dist_dc_km, self.dist_cc_km, self.dist_cd_km,
                    self.time_dc_min, self.time_cc_min, self.time_cd_min,
                    self.cfg, use_free, self.K
                )
                if cost < self.pbest_cost[p]:
                    self.pbest_cost[p] = cost
                    self.pbest_X[p] = self.X[p].copy()
                if cost < self.gbest_cost:
                    self.gbest_cost = cost
                    self.gbest_X = self.X[p].copy()
                    self.gbest_summary = summary

            r1 = self.rng.random((self.n_particles, self.dim))
            r2 = self.rng.random((self.n_particles, self.dim))
            self.V = (
                self.w * self.V
                + self.c1 * r1 * (self.pbest_X - self.X)
                + self.c2 * r2 * (self.gbest_X - self.X)
            )
            self.X = np.clip(self.X + self.V, -4, 4)
            self.V = np.clip(self.V, -1.5, 1.5)

        return self.gbest_cost, self.gbest_summary


# =========================================================
# INIT VEHICLE LOCS
# =========================================================
def build_init_locs_match_need(K: int, need_day0: np.ndarray):
    """
    初始化车辆分布至少满足 Day1 的 fixed-start 需求；
    剩余车辆均匀补齐。
    """
    M = len(need_day0)
    locs = []
    for d in range(M):
        locs += [d] * int(need_day0[d])
    remain = K - len(locs)
    for i in range(remain):
        locs.append(i % M)
    return locs


# =========================================================
# MIN-COST FLOW
# =========================================================
class Edge:
    __slots__ = ("to", "rev", "cap", "cost", "orig_cap")
    def __init__(self, to, rev, cap, cost):
        self.to = to
        self.rev = rev
        self.cap = cap
        self.cost = cost
        self.orig_cap = cap


class MinCostFlow:
    def __init__(self, n):
        self.n = n
        self.g = [[] for _ in range(n)]

    def add_edge(self, fr, to, cap, cost):
        fwd = Edge(to, len(self.g[to]), cap, cost)
        rev = Edge(fr, len(self.g[fr]), 0, -cost)
        self.g[fr].append(fwd)
        self.g[to].append(rev)

    def min_cost_flow(self, s, t, maxf):
        n = self.n
        INF = 10**18
        res = 0
        h = [0] * n
        prevv = [0] * n
        preve = [0] * n
        flow = 0

        import heapq
        while flow < maxf:
            dist = [INF] * n
            dist[s] = 0
            pq = [(0, s)]
            while pq:
                d, v = heapq.heappop(pq)
                if dist[v] < d:
                    continue
                for i, e in enumerate(self.g[v]):
                    if e.cap > 0:
                        nd = d + e.cost + h[v] - h[e.to]
                        if dist[e.to] > nd:
                            dist[e.to] = nd
                            prevv[e.to] = v
                            preve[e.to] = i
                            heapq.heappush(pq, (nd, e.to))

            if dist[t] == INF:
                break

            for v in range(n):
                if dist[v] < INF:
                    h[v] += dist[v]

            d = maxf - flow
            v = t
            while v != s:
                e = self.g[prevv[v]][preve[v]]
                d = min(d, e.cap)
                v = prevv[v]

            v = t
            while v != s:
                e = self.g[prevv[v]][preve[v]]
                e.cap -= d
                self.g[v][e.rev].cap += d
                v = prevv[v]

            flow += d
            res += d * h[t]

        return flow, res


def min_cost_dispatch_flow(current_counts: np.ndarray, required_counts: np.ndarray,
                           dd_km: np.ndarray, unit_cost_per_dist: float):
    """
    Baseline1 night dispatch: depot->depot, only distance-cost on road-network.
    """
    M = dd_km.shape[0]
    deficits = np.maximum(0, required_counts - current_counts).astype(int)
    excess = np.maximum(0, current_counts - required_counts).astype(int)
    need = int(deficits.sum())
    if need == 0:
        return np.zeros((M, M), dtype=int), 0.0

    if int(excess.sum()) < need:
        return None, None

    n = 2 * M + 2
    s = 0
    t = 2 * M + 1
    mcf = MinCostFlow(n)

    for i in range(M):
        if excess[i] > 0:
            mcf.add_edge(s, 1 + i, int(excess[i]), 0)
    for j in range(M):
        if deficits[j] > 0:
            mcf.add_edge(1 + M + j, t, int(deficits[j]), 0)

    scale = 1000
    edge_map = {}
    for i in range(M):
        u = 1 + i
        for j in range(M):
            v = 1 + M + j
            c = int(round(unit_cost_per_dist * dd_km[i, j] * scale))
            idx = len(mcf.g[u])
            mcf.add_edge(u, v, 10**9, c)
            edge_map[(i, j)] = (u, idx)

    f, cost_int = mcf.min_cost_flow(s, t, need)
    if f < need:
        return None, None

    flow = np.zeros((M, M), dtype=int)
    for (i, j), (u, idx) in edge_map.items():
        e = mcf.g[u][idx]
        used = e.orig_cap - e.cap
        if used > 0:
            flow[i, j] = int(used)

    return flow, cost_int / scale


def min_cost_end_matching(cost_matrix: np.ndarray, demand: np.ndarray):
    """
    Assign each used route to an end depot to satisfy EXACT per-depot demand (sum(demand) <= R).
    cost_matrix: shape (R, M) cost of route i ending at depot j
    """
    R, M = cost_matrix.shape
    total_demand = int(np.sum(demand))
    if total_demand == 0:
        return list(np.argmin(cost_matrix, axis=1))
    if total_demand > R:
        return None

    n = 1 + R + M + 1
    s = 0
    t = n - 1
    mcf = MinCostFlow(n)

    for i in range(R):
        mcf.add_edge(s, 1 + i, 1, 0)

    scale = 1000
    for i in range(R):
        u = 1 + i
        for j in range(M):
            v = 1 + R + j
            c = int(round(cost_matrix[i, j] * scale))
            mcf.add_edge(u, v, 1, c)

    for j in range(M):
        cap = int(demand[j])
        if cap > 0:
            mcf.add_edge(1 + R + j, t, cap, 0)

    f, _ = mcf.min_cost_flow(s, t, total_demand)
    if f < total_demand:
        return None

    ends = [-1] * R
    for i in range(R):
        u = 1 + i
        for e in mcf.g[u]:
            if 1 + R <= e.to < 1 + R + M:
                used = e.orig_cap - e.cap
                if used > 0:
                    ends[i] = e.to - (1 + R)
                    break

    for i in range(R):
        if ends[i] == -1:
            ends[i] = int(np.argmin(cost_matrix[i, :]))

    return ends


# =========================================================
# PRECOMPUTE
# =========================================================
def precompute_tables_allstart(days_routes, depots, customers_days_active, mats_days, cfg):
    """
    tables[t][r][s][e] = (cost, worktime)
    """
    T = len(days_routes)
    M = len(depots)
    tables = []
    for t in range(T):
        customers = customers_days_active[t]
        mats = mats_days[t]
        day_tab = []
        for r in days_routes[t]:
            seq = r["route"]
            tab_se = []
            for s in range(M):
                per_end = []
                for e in range(M):
                    c, st = route_cost_and_stats(
                        s, e, seq, depots, customers,
                        mats["dist_dc_km"], mats["dist_cc_km"], mats["dist_cd_km"],
                        mats["time_dc_min"], mats["time_cc_min"], mats["time_cd_min"],
                        cfg
                    )
                    per_end.append((c, st["worktime_min"]))
                tab_se.append(per_end)
            day_tab.append(tab_se)
        tables.append(day_tab)
    return tables


def compute_next_start_scores(table_allstart: List, cfg: Dict[str, Any]):
    """
    next_start_score[t][s] = average over routes r of min_e cost(t,r,s,e)
    """
    T = len(table_allstart)
    M = int(cfg["N_DEPOTS"])
    scores = []
    for t in range(T):
        R = len(table_allstart[t])
        if R == 0:
            scores.append([0.0] * M)
            continue
        arr = []
        for s in range(M):
            mins = []
            for r in range(R):
                mins.append(min(table_allstart[t][r][s][e][0] for e in range(M)))
            arr.append(float(np.mean(mins)))
        scores.append(arr)
    return scores


def start_need_from_stage1(days_routes, M):
    T = len(days_routes)
    need = np.zeros((T, M), dtype=int)
    for t in range(T):
        for r in days_routes[t]:
            need[t, int(r["start"])] += 1
    return need


# =========================================================
# BASELINE1
# =========================================================
def baseline1_with_plan(days_routes, depots, customers_days_active, mats_days, cfg, init_locs, dd_km, seed=0):
    T = len(days_routes)
    M = len(depots)
    K = int(cfg["K_VEHICLES"])
    unit = float(cfg["DISPATCH_COST_PER_DIST"])

    day_costs = []
    day_wts = []
    day_starts = []
    day_ends = []
    for t in range(T):
        customers = customers_days_active[t]
        mats = mats_days[t]
        rc, rw, rs, re = [], [], [], []
        for r in days_routes[t]:
            s = int(r["start"])
            e = int(r["end"])
            seq = r["route"]
            c, st = route_cost_and_stats(
                s, e, seq, depots, customers,
                mats["dist_dc_km"], mats["dist_cc_km"], mats["dist_cd_km"],
                mats["time_dc_min"], mats["time_cc_min"], mats["time_cd_min"],
                cfg
            )
            rc.append(c)
            rw.append(st["worktime_min"])
            rs.append(s)
            re.append(e)
        day_costs.append(rc)
        day_wts.append(rw)
        day_starts.append(rs)
        day_ends.append(re)

    loc = init_locs[:]
    Ak = [0.0] * K
    depot_vehicles = [[] for _ in range(M)]
    for vid, d in enumerate(loc):
        depot_vehicles[d].append(vid)

    per_day_cost = [0.0] * T
    dispatch_costs = [0.0] * max(0, T - 1)
    pre_dispatch_cost = 0.0

    rtov_all = []
    ends_all = []

    for t in range(T):
        need = np.zeros(M, dtype=int)
        for s in day_starts[t]:
            need[s] += 1

        cur_counts = np.array([len(depot_vehicles[d]) for d in range(M)], dtype=int)
        flow, dc = min_cost_dispatch_flow(cur_counts, need, dd_km, unit)
        if flow is None:
            return None

        if dc > 0:
            for i in range(M):
                for j in range(M):
                    cnt = int(flow[i, j])
                    if cnt <= 0:
                        continue
                    depot_vehicles[i].sort(key=lambda vid: Ak[vid])
                    moving = depot_vehicles[i][:cnt]
                    depot_vehicles[i] = depot_vehicles[i][cnt:]
                    depot_vehicles[j].extend(moving)
                    for vid in moving:
                        loc[vid] = j
            if t == 0:
                pre_dispatch_cost += dc
            else:
                dispatch_costs[t - 1] += dc

        routes_by_depot = [[] for _ in range(M)]
        for ridx, s in enumerate(day_starts[t]):
            routes_by_depot[s].append(ridx)

        rtov = [-1] * len(days_routes[t])
        ends = [None] * len(days_routes[t])

        day_cost = 0.0
        for d in range(M):
            rlist = routes_by_depot[d]
            if not rlist:
                continue
            if len(depot_vehicles[d]) < len(rlist):
                return None

            # fairness: long worktime first, least loaded vehicle first
            rlist.sort(key=lambda ridx: day_wts[t][ridx], reverse=True)
            depot_vehicles[d].sort(key=lambda vid: Ak[vid])

            chosen = depot_vehicles[d][:len(rlist)]
            depot_vehicles[d] = depot_vehicles[d][len(rlist):]

            for ridx, vid in zip(rlist, chosen):
                rtov[ridx] = vid
                ends[ridx] = int(day_ends[t][ridx])
                day_cost += day_costs[t][ridx]
                Ak[vid] += day_wts[t][ridx]
                e = day_ends[t][ridx]
                loc[vid] = e
                depot_vehicles[e].append(vid)

        rtov_all.append(rtov)
        ends_all.append(ends)
        per_day_cost[t] = day_cost

    total_cost = sum(per_day_cost) + sum(dispatch_costs) + pre_dispatch_cost
    meanA = sum(Ak) / K
    varA = sum((a - meanA) ** 2 for a in Ak) / K

    return {
        "total_cost": total_cost,
        "var_worktime": varA,
        "per_day_cost": per_day_cost,
        "dispatch_costs": dispatch_costs,
        "pre_dispatch_cost": pre_dispatch_cost,
        "Ak": Ak,
        "route_to_vehicle": rtov_all,
        "end_choice": ends_all,
    }


# =========================================================
# BASELINE2
# =========================================================
def baseline2_route_to_next_need(days_routes, table_allstart, need, init_locs, cfg, seed=0):
    rng = random.Random(seed)
    T = len(days_routes)
    M = int(cfg["N_DEPOTS"])
    K = int(cfg["K_VEHICLES"])

    loc = init_locs[:]
    Ak = [0.0] * K
    per_day_cost = [0.0] * T
    chosen_end = []
    route_to_vehicle_all = []

    for t in range(T):
        depot_vehicles = [[] for _ in range(M)]
        for vid in range(K):
            depot_vehicles[loc[vid]].append(vid)

        depot_routes = [[] for _ in range(M)]
        for ridx, r in enumerate(days_routes[t]):
            depot_routes[int(r["start"])].append(ridx)

        for d in range(M):
            if len(depot_vehicles[d]) < len(depot_routes[d]):
                return None

        assigned = []
        used_vid = set()
        for d in range(M):
            rlist = depot_routes[d]
            if not rlist:
                continue

            vlist = depot_vehicles[d]

            def min_wt(ridx):
                return min(table_allstart[t][ridx][d][e][1] for e in range(M))

            rlist_sorted = sorted(rlist, key=min_wt, reverse=True)
            vlist_sorted = sorted(vlist, key=lambda vid: Ak[vid])

            chosen = vlist_sorted[:len(rlist_sorted)]
            for ridx, vid in zip(rlist_sorted, chosen):
                assigned.append((ridx, vid, d))
                used_vid.add(vid)

        rtov_day = [-1] * len(days_routes[t])
        for ridx, vid, sfix in assigned:
            rtov_day[ridx] = vid
        route_to_vehicle_all.append(rtov_day)

        ends_for_day = [None] * len(days_routes[t])

        if t < T - 1:
            idle_counts = np.zeros(M, dtype=int)
            for vid in range(K):
                if vid not in used_vid:
                    idle_counts[loc[vid]] += 1

            demand_next = need[t + 1].copy()
            remaining_need = np.maximum(0, demand_next - idle_counts)

            R = len(assigned)
            cost_matrix = np.zeros((R, M), dtype=float)
            for i, (ridx, vid, sfix) in enumerate(assigned):
                for e in range(M):
                    cost_matrix[i, e] = table_allstart[t][ridx][sfix][e][0]

            ends_used = min_cost_end_matching(cost_matrix, remaining_need)
            if ends_used is None:
                return None

            for i, (ridx, vid, sfix) in enumerate(assigned):
                ends_for_day[ridx] = int(ends_used[i])

            for ridx, vid, sfix in assigned:
                if ends_for_day[ridx] is None:
                    ends_for_day[ridx] = int(np.argmin([table_allstart[t][ridx][sfix][e][0] for e in range(M)]))
        else:
            for ridx, vid, sfix in assigned:
                ends_for_day[ridx] = int(np.argmin([table_allstart[t][ridx][sfix][e][0] for e in range(M)]))

        for ridx, vid, sfix in assigned:
            e = int(ends_for_day[ridx])
            c, wt = table_allstart[t][ridx][sfix][e]
            per_day_cost[t] += c
            Ak[vid] += wt
            loc[vid] = e

        chosen_end.append(ends_for_day)

    total_cost = float(sum(per_day_cost))
    meanA = sum(Ak) / K
    varA = sum((a - meanA) ** 2 for a in Ak) / K
    return total_cost, varA, per_day_cost, Ak, chosen_end, route_to_vehicle_all


# =========================================================
# MAIN EVALUATION
# =========================================================
def eval_plan_main(route_to_vehicle, end_choice, table_allstart, init_locs, cfg):
    T = len(route_to_vehicle)
    K = int(cfg["K_VEHICLES"])

    loc = init_locs[:]
    Ak = [0.0] * K
    per_day_cost = [0.0] * T

    for t in range(T):
        used = set()
        R = len(route_to_vehicle[t])
        if len(end_choice[t]) != R:
            return False, None, None, None, None
        for r, vid in enumerate(route_to_vehicle[t]):
            if vid == -1:
                return False, None, None, None, None
            if vid in used:
                return False, None, None, None, None
            used.add(vid)

        for r, vid in enumerate(route_to_vehicle[t]):
            s = loc[vid]
            e = int(end_choice[t][r])
            c, wt = table_allstart[t][r][s][e]
            per_day_cost[t] += c
            Ak[vid] += wt
            loc[vid] = e

    total_cost = float(sum(per_day_cost))
    meanA = sum(Ak) / K
    varA = sum((a - meanA) ** 2 for a in Ak) / K
    return True, total_cost, varA, per_day_cost, Ak


def greedy_init_main(days_routes, table_allstart, init_locs, cfg, seed=0):
    rng = random.Random(seed)
    T = len(days_routes)
    M = int(cfg["N_DEPOTS"])
    K = int(cfg["K_VEHICLES"])

    loc = init_locs[:]
    Ak = [0.0] * K

    route_to_vehicle = []
    end_choice = []

    for t in range(T):
        R = len(days_routes[t])
        rtov = [-1] * R
        ends = [0] * R

        used = set()
        route_order = list(range(R))
        rng.shuffle(route_order)

        for r in route_order:
            best = None
            cand_vids = [vid for vid in range(K) if vid not in used]

            for vid in cand_vids:
                s = loc[vid]
                best_end = None
                best_val = None
                for e in range(M):
                    c, wt = table_allstart[t][r][s][e]
                    val = c + float(cfg["END_GAMMA_WT"]) * wt
                    if best_val is None or val < best_val:
                        best_val = val
                        best_end = e
                score = best_val + float(cfg["REPAIR_ALPHA_AK"]) * Ak[vid]
                if best is None or score < best[0]:
                    best = (score, vid, best_end)

            if best is None:
                return None

            _, vid, be = best
            rtov[r] = vid
            ends[r] = int(be)
            used.add(vid)

        for r in range(R):
            vid = rtov[r]
            s = loc[vid]
            e = int(ends[r])
            c, wt = table_allstart[t][r][s][e]
            Ak[vid] += wt
            loc[vid] = e

        route_to_vehicle.append(rtov)
        end_choice.append(ends)

    return route_to_vehicle, end_choice


# =========================================================
# PARETO
# =========================================================
def pareto_update(archive, sol, cfg):
    c, v = sol[0], sol[1]
    rc = round(c, int(cfg["PARETO_ROUND_COST"]))
    rv = round(v, int(cfg["PARETO_ROUND_VAR"]))

    for s in archive:
        if round(s[0], int(cfg["PARETO_ROUND_COST"])) == rc and round(s[1], int(cfg["PARETO_ROUND_VAR"])) == rv:
            return archive

    for s in archive:
        c2, v2 = s[0], s[1]
        if (c2 <= c and v2 <= v) and (c2 < c or v2 < v):
            return archive

    new_archive = []
    for s in archive:
        c2, v2 = s[0], s[1]
        if (c <= c2 and v <= v2) and (c < c2 or v < v2):
            continue
        new_archive.append(s)
    new_archive.append(sol)

    new_archive.sort(key=lambda x: (x[0], x[1]))
    if len(new_archive) > int(cfg["PARETO_MAX_KEEP"]):
        new_archive = new_archive[:int(cfg["PARETO_MAX_KEEP"])]
    return new_archive


def pick_balanced_pareto(pareto):
    """
    选“成本/方差都表现较好”的点：归一化后距离理想点(0,0)最近。
    """
    costs = [s[0] for s in pareto]
    vars_ = [s[1] for s in pareto]
    cmin, cmax = min(costs), max(costs)
    vmin, vmax = min(vars_), max(vars_)
    dc = max(1e-9, cmax - cmin)
    dv = max(1e-9, vmax - vmin)

    best = None
    best_score = None
    for s in pareto:
        cn = (s[0] - cmin) / dc
        vn = (s[1] - vmin) / dv
        score = math.hypot(cn, vn)
        if best is None or score < best_score:
            best = s
            best_score = score
    return best


# =========================================================
# MO-ALNS
# =========================================================
def deep_copy_plan(rtov, ends):
    return [row[:] for row in rtov], [row[:] for row in ends]


def destroy_random(rtov, rng: random.Random, cfg: Dict[str, Any]):
    T = len(rtov)
    frac_lo, frac_hi = cfg["REMOVE_FRAC_RANGE"]
    focus_one_day = (rng.random() < float(cfg["DESTROY_DAY_FOCUS_PROB"]))

    if focus_one_day:
        t = rng.randrange(T)
        R = len(rtov[t])
        if R == 0:
            return
        q = rng.uniform(frac_lo, frac_hi)
        k = max(1, int(round(q * R)))
        idx = list(range(R))
        rng.shuffle(idx)
        for r in idx[:k]:
            rtov[t][r] = -1
    else:
        for t in range(T):
            R = len(rtov[t])
            if R == 0:
                continue
            q = rng.uniform(frac_lo, frac_hi)
            k = max(1, int(round(q * R)))
            idx = list(range(R))
            rng.shuffle(idx)
            for r in idx[:k]:
                rtov[t][r] = -1


def destroy_heavy_vehicles(rtov, ends, table_allstart, init_locs, rng: random.Random, cfg: Dict[str, Any]):
    ok, c, v, per, Ak = eval_plan_main(rtov, ends, table_allstart, init_locs, cfg)
    if not ok:
        return
    K = int(cfg["K_VEHICLES"])
    topk = int(cfg["HEAVY_VEH_TOPK"])
    topk = max(1, min(topk, K))
    order = np.argsort(np.array(Ak))[::-1][:topk]
    heavy = set(int(x) for x in order)

    T = len(rtov)
    for t in range(T):
        R = len(rtov[t])
        for r in range(R):
            if rtov[t][r] in heavy:
                rtov[t][r] = -1


def destroy_high_cost_routes(rtov, ends, table_allstart, init_locs, rng: random.Random, cfg: Dict[str, Any]):
    T = len(rtov)
    frac_lo, frac_hi = cfg["REMOVE_FRAC_RANGE"]

    loc = init_locs[:]
    for t in range(T):
        R = len(rtov[t])
        if R == 0:
            continue

        route_costs = []
        used = set()
        for r in range(R):
            vid = rtov[t][r]
            if vid == -1 or vid in used:
                route_costs.append((1e18, r))
                continue
            used.add(vid)
            s = loc[vid]
            e = int(ends[t][r]) if ends[t][r] is not None else 0
            c0, _ = table_allstart[t][r][s][e]
            route_costs.append((c0, r))

        q = rng.uniform(frac_lo, frac_hi)
        k = max(1, int(round(q * R)))
        route_costs.sort(reverse=True, key=lambda x: x[0])
        for _, r in route_costs[:k]:
            rtov[t][r] = -1

        for r in range(R):
            vid = rtov[t][r]
            if vid == -1:
                continue
            e = int(ends[t][r])
            loc[vid] = e


def repair_greedy(rtov, ends, table_allstart, init_locs, next_scores, rng: random.Random, cfg: Dict[str, Any]):
    T = len(rtov)
    M = int(cfg["N_DEPOTS"])
    K = int(cfg["K_VEHICLES"])
    alpha = float(cfg["REPAIR_ALPHA_AK"])
    beta = float(cfg["REPAIR_BETA_WT"])
    gamma = float(cfg["END_GAMMA_WT"])
    eta = float(cfg["ETA_LOOKAHEAD"])

    loc = init_locs[:]
    Ak = [0.0] * K

    for t in range(T):
        R = len(rtov[t])
        used = set(v for v in rtov[t] if v != -1)
        available = [vid for vid in range(K) if vid not in used]

        unassigned = [r for r in range(R) if rtov[t][r] == -1]
        rng.shuffle(unassigned)

        for r in unassigned:
            best = None
            for vid in available:
                s = loc[vid]
                best_end = None
                best_val = None
                best_c, best_wt = None, None
                for e in range(M):
                    c, wt = table_allstart[t][r][s][e]
                    look = 0.0
                    if t < T - 1:
                        look = next_scores[t + 1][e]
                    val = c + gamma * wt + eta * look
                    if best_val is None or val < best_val:
                        best_val = val
                        best_end = e
                        best_c, best_wt = c, wt
                score = best_val + alpha * Ak[vid] + beta * best_wt
                if best is None or score < best[0]:
                    best = (score, vid, best_end, best_c, best_wt)
            if best is None:
                return False
            _, vid, be, _, _ = best
            rtov[t][r] = int(vid)
            ends[t][r] = int(be)
            available.remove(vid)

        for r in range(R):
            vid = rtov[t][r]
            s = loc[vid]
            if ends[t][r] is None:
                ends[t][r] = 0
            best_end = int(ends[t][r])
            best_val = None
            for e in range(M):
                c, wt = table_allstart[t][r][s][e]
                look = 0.0
                if t < T - 1:
                    look = next_scores[t + 1][e]
                val = c + gamma * wt + eta * look
                if best_val is None or val < best_val:
                    best_val = val
                    best_end = e
            ends[t][r] = int(best_end)

        used2 = set()
        for r in range(R):
            vid = rtov[t][r]
            if vid == -1 or vid in used2:
                return False
            used2.add(vid)
            s = loc[vid]
            e = int(ends[t][r])
            c, wt = table_allstart[t][r][s][e]
            Ak[vid] += wt
            loc[vid] = e

    return True


def repair_mcf_daywise(rtov, ends, table_allstart, init_locs, next_scores, rng: random.Random, cfg: Dict[str, Any]):
    T = len(rtov)
    M = int(cfg["N_DEPOTS"])
    K = int(cfg["K_VEHICLES"])
    alpha = float(cfg["REPAIR_ALPHA_AK"])
    gamma = float(cfg["END_GAMMA_WT"])
    eta = float(cfg["ETA_LOOKAHEAD"])

    loc = init_locs[:]
    Ak = [0.0] * K

    for t in range(T):
        R = len(rtov[t])
        used = set(v for v in rtov[t] if v != -1)
        avail = [vid for vid in range(K) if vid not in used]
        unassigned = [r for r in range(R) if rtov[t][r] == -1]

        if unassigned:
            U = len(unassigned)
            V = len(avail)
            if V < U:
                return False

            cost_mat = np.zeros((U, V), dtype=float)
            best_end_for_pair = [[0] * V for _ in range(U)]

            for i, r in enumerate(unassigned):
                for j, vid in enumerate(avail):
                    s = loc[vid]
                    best_val = None
                    best_e = 0
                    for e in range(M):
                        c, wt = table_allstart[t][r][s][e]
                        look = 0.0
                        if t < T - 1:
                            look = next_scores[t + 1][e]
                        val = c + gamma * wt + eta * look
                        if best_val is None or val < best_val:
                            best_val = val
                            best_e = e
                    cost_mat[i, j] = float(best_val + alpha * Ak[vid])
                    best_end_for_pair[i][j] = int(best_e)

            n = 1 + U + V + 1
            S = 0
            TT = n - 1
            mcf = MinCostFlow(n)

            for i in range(U):
                mcf.add_edge(S, 1 + i, 1, 0)
            scale = 1000
            for i in range(U):
                u = 1 + i
                for j in range(V):
                    v = 1 + U + j
                    c = int(round(cost_mat[i, j] * scale))
                    mcf.add_edge(u, v, 1, c)
            for j in range(V):
                mcf.add_edge(1 + U + j, TT, 1, 0)

            f, _ = mcf.min_cost_flow(S, TT, U)
            if f < U:
                return False

            chosen_vid_for_route = [-1] * U
            for i in range(U):
                u = 1 + i
                for e in mcf.g[u]:
                    if 1 + U <= e.to < 1 + U + V:
                        used_edge = e.orig_cap - e.cap
                        if used_edge > 0:
                            j = e.to - (1 + U)
                            chosen_vid_for_route[i] = j
                            break
                if chosen_vid_for_route[i] == -1:
                    return False

            taken = set()
            for i, r in enumerate(unassigned):
                j = chosen_vid_for_route[i]
                if j in taken:
                    return False
                taken.add(j)
                vid = avail[j]
                rtov[t][r] = int(vid)
                ends[t][r] = int(best_end_for_pair[i][j])

        for r in range(R):
            vid = rtov[t][r]
            s = loc[vid]
            best_e = int(ends[t][r]) if ends[t][r] is not None else 0
            best_val = None
            for e in range(M):
                c, wt = table_allstart[t][r][s][e]
                look = 0.0
                if t < T - 1:
                    look = next_scores[t + 1][e]
                val = c + gamma * wt + eta * look
                if best_val is None or val < best_val:
                    best_val = val
                    best_e = e
            ends[t][r] = int(best_e)

        used2 = set()
        for r in range(R):
            vid = rtov[t][r]
            if vid == -1 or vid in used2:
                return False
            used2.add(vid)
            s = loc[vid]
            e = int(ends[t][r])
            c, wt = table_allstart[t][r][s][e]
            Ak[vid] += wt
            loc[vid] = e

    return True


def mo_alns_main(days_routes, table_allstart, init_locs, next_scores, cfg, seed: int, lam: float, Cref: float, Vref: float):
    rng = random.Random(seed)

    init = greedy_init_main(days_routes, table_allstart, init_locs, cfg, seed=seed + 11)
    if init is None:
        return []
    cur_rtov, cur_end = init

    ok, c0, v0, per0, Ak0 = eval_plan_main(cur_rtov, cur_end, table_allstart, init_locs, cfg)
    if not ok:
        return []

    def F(cost, var):
        return (cost / max(1e-9, Cref)) + float(lam) * (var / max(1e-9, Vref))

    best_rtov, best_end = deep_copy_plan(cur_rtov, cur_end)
    bestF = F(c0, v0)

    archive = []
    archive = pareto_update(archive, (c0, v0, best_rtov, best_end, per0, Ak0), cfg)

    destroy_ops = [
        ("rand", lambda rt, en: destroy_random(rt, rng, cfg)),
        ("heavy", lambda rt, en: destroy_heavy_vehicles(rt, en, table_allstart, init_locs, rng, cfg)),
        ("highcost", lambda rt, en: destroy_high_cost_routes(rt, en, table_allstart, init_locs, rng, cfg)),
    ]
    repair_ops = [
        ("greedy", lambda rt, en: repair_greedy(rt, en, table_allstart, init_locs, next_scores, rng, cfg)),
        ("mcf", lambda rt, en: repair_mcf_daywise(rt, en, table_allstart, init_locs, next_scores, rng, cfg)),
    ]

    d_w = [1.0] * len(destroy_ops)
    r_w = [1.0] * len(repair_ops)
    d_score = [0.0] * len(destroy_ops)
    r_score = [0.0] * len(repair_ops)
    d_cnt = [0] * len(destroy_ops)
    r_cnt = [0] * len(repair_ops)

    def roulette(weights):
        s = sum(weights)
        x = rng.random() * s
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if x <= acc:
                return i
        return len(weights) - 1

    iters = int(cfg["ALNS_ITERS"])
    temp = float(cfg["TEMP0"])
    decay = float(cfg["TEMP_DECAY"])
    upd_every = int(cfg["WEIGHT_UPDATE_EVERY"])
    rr = float(cfg["WEIGHT_R"])

    cur_ok, cur_c, cur_v, cur_per, cur_Ak = eval_plan_main(cur_rtov, cur_end, table_allstart, init_locs, cfg)
    if not cur_ok:
        return []
    curF = F(cur_c, cur_v)

    for it in range(1, iters + 1):
        if int(cfg["REHEAT_EVERY"]) > 0 and (it % int(cfg["REHEAT_EVERY"]) == 0):
            temp *= float(cfg["REHEAT_FACTOR"])

        di = roulette(d_w)
        ri = roulette(r_w)
        d_fn = destroy_ops[di][1]
        r_fn = repair_ops[ri][1]

        cand_rtov, cand_end = deep_copy_plan(cur_rtov, cur_end)

        d_fn(cand_rtov, cand_end)
        d_cnt[di] += 1

        feas = r_fn(cand_rtov, cand_end)
        r_cnt[ri] += 1
        if not feas:
            temp *= decay
            continue

        ok2, c2, v2, per2, Ak2 = eval_plan_main(cand_rtov, cand_end, table_allstart, init_locs, cfg)
        if not ok2:
            temp *= decay
            continue

        f2 = F(c2, v2)

        before_len = len(archive)
        archive = pareto_update(archive, (c2, v2, cand_rtov, cand_end, per2, Ak2), cfg)
        entered_archive = (len(archive) > before_len)

        accept = False
        if f2 <= curF:
            accept = True
        else:
            df = f2 - curF
            if temp > 1e-12 and rng.random() < math.exp(-df / temp):
                accept = True

        reward = 0.0
        if f2 < bestF:
            bestF = f2
            best_rtov, best_end = deep_copy_plan(cand_rtov, cand_end)
            reward = float(cfg["REWARD_BEST"])
        elif entered_archive:
            reward = float(cfg["REWARD_ARCHIVE"])
        elif accept:
            reward = float(cfg["REWARD_ACCEPT"])

        if accept:
            cur_rtov, cur_end = cand_rtov, cand_end
            curF = f2

        d_score[di] += reward
        r_score[ri] += reward

        if it % upd_every == 0:
            for i in range(len(d_w)):
                if d_cnt[i] > 0:
                    avg = d_score[i] / d_cnt[i]
                    d_w[i] = (1 - rr) * d_w[i] + rr * max(0.05, avg)
                d_score[i] = 0.0
                d_cnt[i] = 0
            for i in range(len(r_w)):
                if r_cnt[i] > 0:
                    avg = r_score[i] / r_cnt[i]
                    r_w[i] = (1 - rr) * r_w[i] + rr * max(0.05, avg)
                r_score[i] = 0.0
                r_cnt[i] = 0

        temp *= decay

        if rng.random() < 0.005:
            cur_rtov, cur_end = deep_copy_plan(best_rtov, best_end)
            cur_ok, cur_c, cur_v, cur_per, cur_Ak = eval_plan_main(cur_rtov, cur_end, table_allstart, init_locs, cfg)
            if cur_ok:
                curF = F(cur_c, cur_v)

    return archive


# =========================================================
# MAP HELPERS
# =========================================================
def hsv_to_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def make_route_colors(n: int) -> List[str]:
    s = 0.75
    v = 0.85
    return [hsv_to_hex((k / max(1, n)) % 1.0, s, v) for k in range(n)]


def add_label(parent, lat: float, lon: float, text: str, color: str = "#111", size_px: int = 12, y_offset_px: int = -12):
    folium.Marker(
        location=(lat, lon),
        icon=DivIcon(
            icon_size=(150, 20),
            icon_anchor=(0, 0),
            html=f"""
            <div style="
                font-size:{size_px}px;
                color:{color};
                font-weight:700;
                text-shadow: 1px 1px 2px rgba(255,255,255,0.9);
                transform: translate(0px, {y_offset_px}px);
            ">{text}</div>
            """
        )
    ).add_to(parent)


def make_map_multi_day(depots: List[Depot],
                       customers_days_all: List[pd.DataFrame],
                       customers_days_active: List[List[Customer]],
                       days_routes: List[List[Dict[str, Any]]],
                       chosen_rtov: List[List[int]],
                       chosen_end: List[List[int]],
                       init_locs: List[int],
                       cfg: Dict[str, Any],
                       out_html: Optional[str] = None):
    """
    一个总地图，按 Day 分 FeatureGroup。
    - 多底图可切换
    - 每天：客户点 + 客户标签层 + 路线层
    - 客户标签在缩小时自动隐藏
    """
    T = int(cfg["T"])
    base = cfg["OSRM_BASE"]
    timeout = int(cfg["OSRM_TIMEOUT"])
    min_zoom_show_labels = int(cfg.get("MAP_LABEL_MIN_ZOOM", 13))

    all_lat = [d.lat for d in depots]
    all_lon = [d.lon for d in depots]
    for df in customers_days_all:
        all_lat += df["lat"].astype(float).tolist()
        all_lon += df["lon"].astype(float).tolist()
    center = (sum(all_lat) / len(all_lat), sum(all_lon) / len(all_lon))

    m = folium.Map(location=center, zoom_start=int(cfg["MAP_ZOOM"]), tiles=None, control_scale=True)

    # ---- base layers ----
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True).add_to(m)
    folium.TileLayer("CartoDB Positron", name="CartoDB Positron", control=True).add_to(m)
    folium.TileLayer("CartoDB Voyager", name="CartoDB Voyager", control=True).add_to(m)
    folium.TileLayer(
        tiles='http://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}',
        attr='高德地图',
        name='Gaode Map',
        control=True
    ).add_to(m)
    # depots markers + labels
    depot_layer = folium.FeatureGroup(name="Depots", show=True)
    depot_layer.add_to(m)
    for d in depots:
        folium.Marker(
            location=(d.lat, d.lon),
            popup=f"Depot D{d.idx}",
            icon=folium.Icon(color="red", icon="home")
        ).add_to(depot_layer)
        add_label(depot_layer, d.lat, d.lon, f"D{d.idx}", color="#b30000", size_px=14, y_offset_px=-18)

    K = int(cfg["K_VEHICLES"])
    loc = init_locs[:]
    label_layer_names = []

    for t in range(T):
        day_group = folium.FeatureGroup(name=f"Day {t+1}", show=(t == 0))
        day_group.add_to(m)

        point_layer = folium.FeatureGroup(name=f"Day {t+1} Points", control=False, show=True)
        point_layer.add_to(day_group)

        label_layer = folium.FeatureGroup(name=f"Day {t+1} Labels", control=False, show=True)
        label_layer.add_to(day_group)
        label_layer_names.append(label_layer.get_name())

        route_layer = folium.FeatureGroup(name=f"Day {t+1} Routes", control=False, show=True)
        route_layer.add_to(day_group)

        df = customers_days_all[t].copy()
        df["lon"] = df["lon"].astype(float)
        df["lat"] = df["lat"].astype(float)
        df["demand"] = df["demand"].astype(float)
        df["service"] = df["service"].astype(float)
        df["tw_start"] = df["tw_start"].astype(float)
        df["tw_end"] = df["tw_end"].astype(float)

        every = int(cfg.get("CUSTOMER_LABEL_EVERY", 1))
        for i, row in df.reset_index(drop=True).iterrows():
            is_active = float(row["demand"]) > 0.0
            col = cfg["ACTIVE_COLOR"] if is_active else cfg["INACTIVE_COLOR"]
            op = 0.7 if is_active else 0.45
            folium.CircleMarker(
                location=(float(row["lat"]), float(row["lon"])),
                radius=3,
                color=col,
                fill=True,
                fill_opacity=op,
                popup=(
                    f"day={t+1}<br>"
                    f"cust_id={row['cust_id']}<br>"
                    f"demand={row['demand']}<br>"
                    f"service={row['service']} min<br>"
                    f"tw=[{row['tw_start']},{row['tw_end']}]"
                )
            ).add_to(point_layer)
            if every > 0 and (i % every == 0):
                add_label(label_layer, float(row["lat"]), float(row["lon"]), str(row["cust_id"]),
                          color=col, size_px=11, y_offset_px=-10)

        routes_t = days_routes[t]
        act_customers = customers_days_active[t]
        colors = make_route_colors(len(routes_t))

        used = set()
        for r_idx, r in enumerate(routes_t):
            vid = chosen_rtov[t][r_idx]
            e = int(chosen_end[t][r_idx])
            if vid in used:
                continue
            used.add(vid)
            s = loc[vid]
            seq = r["route"]

            coords = (
                [(depots[s].lon, depots[s].lat)]
                + [(act_customers[cid].lon, act_customers[cid].lat) for cid in seq]
                + [(depots[e].lon, depots[e].lat)]
            )
            geom = None
            try:
                geom = osrm_route_geometry(base, coords, timeout=timeout, cfg=cfg)
            except Exception:
                geom = None

            if geom and geom.get("type") == "LineString":
                latlngs = [(lat, lon) for lon, lat in geom["coordinates"]]
            else:
                latlngs = [(lat, lon) for lon, lat in coords]

            folium.PolyLine(
                latlngs,
                color=colors[r_idx],
                weight=5,
                opacity=0.85,
                tooltip=(f"Day{t+1} R{r_idx} veh={vid + 1}  D{s}->{e}  n={len(seq)}")
            ).add_to(route_layer)

            mid_idx = len(latlngs) // 2
            add_label(route_layer, latlngs[mid_idx][0], latlngs[mid_idx][1], f"D{t+1}-R{r_idx}",
                      color=colors[r_idx], size_px=13, y_offset_px=-14)

            loc[vid] = e

    folium.LayerControl(collapsed=False).add_to(m)

    # ---- JS: hide/show customer labels by zoom ----
    map_name = m.get_name()
    label_layers_js = ", ".join(label_layer_names)
    js = f"""
    <script>
    function toggleCustomerLabels_{map_name}() {{
        var map = {map_name};
        var z = map.getZoom();
        var minZoom = {min_zoom_show_labels};
        var layers = [{label_layers_js}];
        for (var i = 0; i < layers.length; i++) {{
            var lyr = layers[i];
            if (z >= minZoom) {{
                if (!map.hasLayer(lyr)) {{
                    map.addLayer(lyr);
                }}
            }} else {{
                if (map.hasLayer(lyr)) {{
                    map.removeLayer(lyr);
                }}
            }}
        }}
    }}
    // customer-labels-ready
    document.addEventListener('DOMContentLoaded', function() {{
        {map_name}.on('zoomend', toggleCustomerLabels_{map_name});
        toggleCustomerLabels_{map_name}();
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(js))

    if out_html is None:
        out_html = str(cfg["MAP_OUT_HTML"])
    m.save(out_html)
    print(f"[MAP] saved: {out_html}")


# =========================================================
# PLOTS
# =========================================================
def plot_pareto_with_baselines(pareto_points, base1, base2, chosen=None, out_png="representative_pareto_front.png"):
    pts = sorted(pareto_points, key=lambda x: x[0])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    plt.figure(figsize=(8.0, 6.0))
    plt.scatter(xs, ys, alpha=0.75, label="Pareto solutions")
    plt.scatter([base1[0]], [base1[1]], marker="X", s=160, label="Baseline1")
    plt.scatter([base2[0]], [base2[1]], marker="X", s=160, label="Baseline2")

    if chosen is not None:
        plt.scatter([chosen[0]], [chosen[1]], marker="D", s=130, label="Balanced")
        plt.annotate(
            f"Balanced\ncost={chosen[0]:.2f}\nvar={chosen[1]:.2f}",
            (chosen[0], chosen[1]),
            xytext=(8, 8),
            textcoords="offset points"
        )

    plt.xlabel("Total Cost")
    plt.ylabel("Var(Total Worktime per Vehicle)")
    plt.title("Representative Run: Pareto Front with Baselines")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close()
    print(f"[PLOT] saved: {out_png}")


def plot_vehicle_worktime_histograms(b1_Ak, b2_Ak, alns_Ak, out_png="representative_vehicle_worktime_hist.png"):
    veh_ids = np.arange(1, len(b1_Ak) + 1)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

    schemes = [
        ("Baseline1", b1_Ak),
        ("Baseline2", b2_Ak),
        ("Stage-2 Balanced(ALNS)", alns_Ak),
    ]

    for ax, (title, vals) in zip(axes, schemes):
        ax.bar(veh_ids, vals)
        ax.set_title(title)
        ax.set_ylabel("Worktime (min)")
        ax.set_xticks(veh_ids)
        ax.set_xticklabels([str(i) for i in veh_ids])
        ax.grid(axis="y", alpha=0.3)

    axes[-1].set_xlabel("Vehicle ID")
    plt.tight_layout()
    plt.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close()
    print(f"[PLOT] saved: {out_png}")


# =========================================================
# EXPORT / EVALUATION
# =========================================================
def evaluate_scheme_summary(
    scheme_name: str,
    days_routes,
    depots,
    customers_days_active,
    mats_days,
    cfg,
    init_locs,
    route_to_vehicle,
    end_choice,
    extra_cost: float = 0.0,
    dispatch_cost: float = 0.0,
):
    T = len(days_routes)
    K = int(cfg["K_VEHICLES"])

    loc = init_locs[:]
    Ak = [0.0] * K

    total_cost_day_routes = 0.0
    total_dist = 0.0
    total_fixed_cost = 0.0
    total_dist_cost = 0.0
    total_penalty_cost = 0.0
    total_tw_late_min = 0.0
    total_depot_late_min = 0.0
    total_cap_excess = 0.0
    total_tw_late_cost = 0.0
    total_depot_late_cost = 0.0
    total_capacity_cost = 0.0
    total_routes = 0

    for t in range(T):
        customers = customers_days_active[t]
        mats = mats_days[t]

        for r_idx, r in enumerate(days_routes[t]):
            vid = int(route_to_vehicle[t][r_idx])
            dep_start = int(loc[vid])
            dep_end = int(end_choice[t][r_idx])
            seq = r["route"]

            cost, st = route_cost_and_stats(
                dep_start, dep_end, seq, depots, customers,
                mats["dist_dc_km"], mats["dist_cc_km"], mats["dist_cd_km"],
                mats["time_dc_min"], mats["time_cc_min"], mats["time_cd_min"],
                cfg, return_timeline=False
            )

            total_cost_day_routes += cost
            total_dist += st["dist_km"]
            total_fixed_cost += st["fixed_cost"]
            total_dist_cost += st["dist_cost"]
            total_penalty_cost += st["penalty_cost"]
            total_tw_late_min += st["tw_late_min"]
            total_depot_late_min += st["depot_late_min"]
            total_cap_excess += st["cap_excess"]
            total_tw_late_cost += st["tw_late_cost"]
            total_depot_late_cost += st["depot_late_cost"]
            total_capacity_cost += st["capacity_cost"]
            total_routes += 1

            Ak[vid] += st["worktime_min"]
            loc[vid] = dep_end

    total_cost = total_cost_day_routes + extra_cost
    meanA = sum(Ak) / K
    varA = sum((a - meanA) ** 2 for a in Ak) / K

    return {
        "scheme": scheme_name,
        "total_routes": total_routes,
        "total_dist_km": total_dist,
        "total_cost": total_cost,
        "route_operating_cost": total_cost_day_routes,
        "dispatch_cost": dispatch_cost,
        "fixed_cost": total_fixed_cost,
        "dist_cost": total_dist_cost,
        "penalty_cost": total_penalty_cost,
        "tw_late_min": total_tw_late_min,
        "depot_late_min": total_depot_late_min,
        "cap_excess": total_cap_excess,
        "tw_late_cost": total_tw_late_cost,
        "depot_late_cost": total_depot_late_cost,
        "capacity_cost": total_capacity_cost,
        "mean_worktime_min": meanA,
        "var_worktime": varA,
        "max_worktime_min": max(Ak) if Ak else 0.0,
        "min_worktime_min": min(Ak) if Ak else 0.0,
        "Ak": Ak,
    }


def export_stage2_vehicle_timeline(
    scheme_name: str,
    days_routes,
    depots,
    customers_days_active,
    mats_days,
    cfg,
    init_locs,
    route_to_vehicle,
    end_choice,
):
    T = len(days_routes)

    loc = init_locs[:]
    timeline_rows = []
    seq_rows = []

    for t in range(T):
        customers = customers_days_active[t]
        mats = mats_days[t]

        for r_idx, r in enumerate(days_routes[t]):
            vid = int(route_to_vehicle[t][r_idx])
            dep_start = int(loc[vid])
            dep_end = int(end_choice[t][r_idx])
            seq = r["route"]

            cost, st = route_cost_and_stats(
                dep_start, dep_end, seq, depots, customers,
                mats["dist_dc_km"], mats["dist_cc_km"], mats["dist_cd_km"],
                mats["time_dc_min"], mats["time_cc_min"], mats["time_cd_min"],
                cfg, return_timeline=True
            )

            cust_ids = [customers[cid].cust_id for cid in seq]
            seq_rows.append({
                "scheme": scheme_name,
                "day": t + 1,
                "route_id": r_idx,
                "vehicle_id": vid + 1,
                "start_depot": dep_start,
                "end_depot": dep_end,
                "start_time_min": depots[dep_start].tw[0],
                "end_time_min": st["back_time"],
                "start_time_clock": minute_to_clock_str(depots[dep_start].tw[0]),
                "end_time_clock": minute_to_clock_str(st["back_time"]),
                "customer_seq_internal": str(seq),
                "customer_seq_cust_id": str(cust_ids),
            })

            for stop_idx, item in enumerate(st["timeline"]):
                timeline_rows.append({
                    "scheme": scheme_name,
                    "day": t + 1,
                    "route_id": r_idx,
                    "vehicle_id": vid + 1,
                    "stop_order": stop_idx,
                    "node_type": item["node_type"],
                    "node_id": item["node_id"],
                    "cust_id": item["cust_id"],
                    "arrive_min": item["arrive_min"],
                    "start_service_min": item["start_service_min"],
                    "finish_min": item["finish_min"],
                    "late_min": item["late_min"],
                    "cum_dist_km": item["cum_dist_km"],
                    "cum_load": item["cum_load"],
                    "arrive_clock": minute_to_clock_str(item["arrive_min"]),
                    "start_service_clock": minute_to_clock_str(item["start_service_min"]),
                    "finish_clock": minute_to_clock_str(item["finish_min"]),
                })

            loc[vid] = dep_end

    return pd.DataFrame(timeline_rows), pd.DataFrame(seq_rows)


def build_run_result_rows(run_id: int, scheme_summary: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        "run_id": run_id,
        "scheme": scheme_summary["scheme"],
        "total_routes": scheme_summary["total_routes"],
        "total_dist_km": scheme_summary["total_dist_km"],
        "total_cost": scheme_summary["total_cost"],
        "route_operating_cost": scheme_summary["route_operating_cost"],
        "dispatch_cost": scheme_summary["dispatch_cost"],
        "fixed_cost": scheme_summary["fixed_cost"],
        "dist_cost": scheme_summary["dist_cost"],
        "penalty_cost": scheme_summary["penalty_cost"],
        "tw_late_min": scheme_summary["tw_late_min"],
        "depot_late_min": scheme_summary["depot_late_min"],
        "cap_excess": scheme_summary["cap_excess"],
        "tw_late_cost": scheme_summary["tw_late_cost"],
        "depot_late_cost": scheme_summary["depot_late_cost"],
        "capacity_cost": scheme_summary["capacity_cost"],
        "mean_worktime_min": scheme_summary["mean_worktime_min"],
        "var_worktime": scheme_summary["var_worktime"],
        "max_worktime_min": scheme_summary["max_worktime_min"],
        "min_worktime_min": scheme_summary["min_worktime_min"],
    }
    return row


def compute_alns_improvement_per_run(df_runs_long: pd.DataFrame):
    metrics = [
        "total_dist_km",
        "total_cost",
        "route_operating_cost",
        "dispatch_cost",
        "fixed_cost",
        "dist_cost",
        "penalty_cost",
        "tw_late_min",
        "depot_late_min",
        "cap_excess",
        "tw_late_cost",
        "depot_late_cost",
        "capacity_cost",
        "mean_worktime_min",
        "var_worktime",
        "max_worktime_min",
    ]

    rows = []
    for run_id in sorted(df_runs_long["run_id"].unique()):
        sub = df_runs_long[df_runs_long["run_id"] == run_id]
        row_b1 = sub[sub["scheme"] == "Baseline1"].iloc[0]
        row_b2 = sub[sub["scheme"] == "Baseline2"].iloc[0]
        row_s3 = sub[sub["scheme"] == "Stage2_Balanced"].iloc[0]

        for base_name, row_base in [("Baseline1", row_b1), ("Baseline2", row_b2)]:
            for m in metrics:
                base_val = float(row_base[m])
                alns_val = float(row_s3[m])
                abs_improve = base_val - alns_val
                pct_improve = 0.0 if abs(base_val) < 1e-12 else 100.0 * abs_improve / base_val
                rows.append({
                    "run_id": run_id,
                    "compare_to": base_name,
                    "metric": m,
                    "baseline_value": base_val,
                    "alns_value": alns_val,
                    "absolute_improvement": abs_improve,
                    "percent_improvement": pct_improve,
                })
    return pd.DataFrame(rows)


def compute_summary_tables(df_runs_long: pd.DataFrame):
    metrics = [
        "total_routes",
        "total_dist_km",
        "total_cost",
        "route_operating_cost",
        "dispatch_cost",
        "fixed_cost",
        "dist_cost",
        "penalty_cost",
        "tw_late_min",
        "depot_late_min",
        "cap_excess",
        "tw_late_cost",
        "depot_late_cost",
        "capacity_cost",
        "mean_worktime_min",
        "var_worktime",
        "max_worktime_min",
        "min_worktime_min",
    ]

    summary_rows = []
    best_rows = []

    for scheme in ["Baseline1", "Baseline2", "Stage2_Balanced"]:
        sub = df_runs_long[df_runs_long["scheme"] == scheme].copy()

        best_idx = sub["total_cost"].idxmin()
        best_row = sub.loc[best_idx].to_dict()
        best_rows.append(best_row)

        row = {"scheme": scheme}
        for m in metrics:
            row[f"{m}_mean"] = sub[m].mean()
            row[f"{m}_std"] = sub[m].std(ddof=1) if len(sub) > 1 else 0.0
            row[f"{m}_min"] = sub[m].min()
            row[f"{m}_max"] = sub[m].max()
        row["best_cost_run_id"] = int(sub.loc[best_idx, "run_id"])
        summary_rows.append(row)

    return pd.DataFrame(summary_rows), pd.DataFrame(best_rows)


def compute_alns_improvement_summary(df_improv: pd.DataFrame):
    rows = []
    for compare_to in ["Baseline1", "Baseline2"]:
        sub = df_improv[df_improv["compare_to"] == compare_to]
        for metric in sorted(sub["metric"].unique()):
            s = sub[sub["metric"] == metric]
            rows.append({
                "compare_to": compare_to,
                "metric": metric,
                "absolute_improvement_mean": s["absolute_improvement"].mean(),
                "absolute_improvement_std": s["absolute_improvement"].std(ddof=1) if len(s) > 1 else 0.0,
                "percent_improvement_mean": s["percent_improvement"].mean(),
                "percent_improvement_std": s["percent_improvement"].std(ddof=1) if len(s) > 1 else 0.0,
            })
    return pd.DataFrame(rows)


# =========================================================
# INSTANCE LOADING
# =========================================================
def load_instance_and_matrices(cfg, day_frames: Optional[List[pd.DataFrame]] = None):
    seed = int(cfg["SEED"])
    random.seed(seed)
    np.random.seed(seed)

    T = int(cfg["T"])
    M = int(cfg["N_DEPOTS"])

    # ---- depots (fixed, 5 days common) ----
    depot_ll = [
        (120.093, 36.074),
        (120.426, 36.143),
        (120.363, 36.337),
        (120.085, 36.218),
    ]
    depots = [Depot(idx=i, lon=float(lon), lat=float(lat), tw=cfg["DEPOT_TW"]) for i, (lon, lat) in enumerate(depot_ll)]

    # ---- OSRM depot-depot distance matrix (for baseline1 dispatch) ----
    print("Building OSRM depot-depot matrix (for dispatch baseline)...")
    dist_km_dd, dur_min_dd = osrm_table_blockwise(
        cfg["OSRM_BASE"],
        [(d.lon, d.lat) for d in depots],
        max_coords=int(cfg["OSRM_TABLE_MAX_COORDS"]),
        timeout=int(cfg["OSRM_TIMEOUT"]),
        cfg=cfg
    )
    dd_km = dist_km_dd  # (M,M)

    # ---- read T days CSVs (or use provided day_frames from MongoDB) ----
    required_cols = ["cust_id", "lon", "lat", "demand", "service", "tw_start", "tw_end"]
    customers_days_all: List[pd.DataFrame] = []
    customers_days_active: List[List[Customer]] = []
    mats_days: List[Dict[str, np.ndarray]] = []

    work_max = float(cfg["WORK_MINUTES"])

    if day_frames is not None and len(day_frames) != T:
        raise ValueError(f"day_frames 长度应为 T={T}，实际为 {len(day_frames)}")

    for t in range(T):
        if day_frames is not None:
            df = day_frames[t].copy()
            path = f"mongodb://day{t + 1}"
        else:
            path = cfg["CSV_PATTERN"].format(t + 1)
            df = read_csv_smart(path)
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"{path} 缺少字段: {missing}. 需要: {required_cols}")

        df = df.copy()
        df["lon"] = df["lon"].astype(float)
        df["lat"] = df["lat"].astype(float)
        df["demand"] = df["demand"].astype(float)
        df["service"] = df["service"].astype(float)
        df["tw_start"] = df["tw_start"].astype(float)
        df["tw_end"] = df["tw_end"].astype(float)
        if "cust_name" not in df.columns:
            df["cust_name"] = ""

        bad_tw = df[(df["tw_start"] < 0) | (df["tw_end"] > work_max) | (df["tw_end"] <= df["tw_start"])]
        if len(bad_tw) > 0:
            ex = bad_tw.head(5)[["cust_id", "tw_start", "tw_end"]]
            raise ValueError(f"{path} 时间窗数据不合法（示例前5行）：\n{ex.to_string(index=False)}\n"
                             f"要求 0 <= tw_start < tw_end <= {work_max}")

        customers_days_all.append(df)

        # active customers: demand>0 only for optimization
        df_act = df[df["demand"] > 0.0].reset_index(drop=True)
        act_customers: List[Customer] = []
        for i, row in df_act.iterrows():
            act_customers.append(Customer(
                idx=i,
                cust_id=row["cust_id"],
                lon=float(row["lon"]),
                lat=float(row["lat"]),
                demand=float(row["demand"]),
                service=float(row["service"]),
                tw=(float(row["tw_start"]), float(row["tw_end"]))
            ))
        customers_days_active.append(act_customers)

        # build OSRM matrices for this day using depots + active customers
        coords_all = [(d.lon, d.lat) for d in depots] + [(c.lon, c.lat) for c in act_customers]
        print(f"Day {t+1}: active_customers={len(act_customers)} | building OSRM matrices...")
        dist_km_all, dur_min_all = osrm_table_blockwise(
            cfg["OSRM_BASE"],
            coords_all,
            max_coords=int(cfg["OSRM_TABLE_MAX_COORDS"]),
            timeout=int(cfg["OSRM_TIMEOUT"]),
            cfg=cfg
        )

        N = len(act_customers)
        if N == 0:
            mats_days.append({
                "dist_dc_km": np.zeros((M, 0), dtype=float),
                "time_dc_min": np.zeros((M, 0), dtype=float),
                "dist_cc_km": np.zeros((0, 0), dtype=float),
                "time_cc_min": np.zeros((0, 0), dtype=float),
                "dist_cd_km": np.zeros((0, M), dtype=float),
                "time_cd_min": np.zeros((0, M), dtype=float),
            })
        else:
            dist_dc_km = dist_km_all[0:M, M:M+N]       # depot -> customer
            time_dc_min = dur_min_all[0:M, M:M+N]
            dist_cc_km = dist_km_all[M:M+N, M:M+N]     # customer -> customer
            time_cc_min = dur_min_all[M:M+N, M:M+N]
            dist_cd_km = dist_km_all[M:M+N, 0:M]       # customer -> depot
            time_cd_min = dur_min_all[M:M+N, 0:M]

            mats_days.append({
                "dist_dc_km": dist_dc_km,
                "time_dc_min": time_dc_min,
                "dist_cc_km": dist_cc_km,
                "time_cc_min": time_cc_min,
                "dist_cd_km": dist_cd_km,
                "time_cd_min": time_cd_min,
            })

    return {
        "depots": depots,
        "customers_days_all": customers_days_all,
        "customers_days_active": customers_days_active,
        "mats_days": mats_days,
        "dd_km": dd_km,
    }


# =========================================================
# SINGLE RUN
# =========================================================
def run_single_experiment(instance: Dict[str, Any], cfg: Dict[str, Any], run_id: int):
    depots = instance["depots"]
    customers_days_all = instance["customers_days_all"]
    customers_days_active = instance["customers_days_active"]
    mats_days = instance["mats_days"]
    dd_km = instance["dd_km"]

    T = int(cfg["T"])
    M = int(cfg["N_DEPOTS"])
    K = int(cfg["K_VEHICLES"])
    base_seed = int(cfg["SEED"])

    run_seed = base_seed + 10000 * run_id
    seed_stage1 = run_seed + 101
    seed_b1 = run_seed + 201
    seed_b2 = run_seed + 301
    seed_stage2_base = run_seed + 401

    print("\n======================================================")
    print(f"RUN {run_id + 1}/{cfg['N_RUNS']} | run_seed={run_seed}")
    print("======================================================")

    # =====================================================
    # Stage-1: daily independent CCDR-PSO
    # =====================================================
    days_routes: List[List[Dict[str, Any]]] = []
    day_cost_indep: List[float] = []

    print("\n=== Stage-1: Daily independent CCDR-PSO ===")
    for t in range(T):
        customers = customers_days_active[t]
        mats = mats_days[t]
        if len(customers) == 0:
            days_routes.append([])
            day_cost_indep.append(0.0)
            print(f"Run {run_id + 1} Day {t+1}: active=0 -> routes=0 indep_cost=0.00")
            continue

        solver = PSO_DaySolver(
            depots, customers,
            mats["dist_dc_km"], mats["dist_cc_km"], mats["dist_cd_km"],
            mats["time_dc_min"], mats["time_cc_min"], mats["time_cd_min"],
            cfg, seed=seed_stage1 + 100 * t, K=K
        )
        best_cost, best_sum = solver.optimize()
        routes = best_sum["routes"]
        if len(routes) > K:
            raise RuntimeError(f"[Run {run_id + 1} Day {t+1}] routes={len(routes)} > K={K}，请增大K或调参数。")
        days_routes.append(routes)
        day_cost_indep.append(best_cost)
        print(f"Run {run_id + 1} Day {t+1}: routes={len(routes)} indep_cost={best_cost:.2f}")

    need = start_need_from_stage1(days_routes, M)
    init_locs = build_init_locs_match_need(K, need[0])

    # =====================================================
    # Precompute table
    # =====================================================
    print("\nPrecomputing all-start/all-end table...")
    table_allstart = precompute_tables_allstart(days_routes, depots, customers_days_active, mats_days, cfg)
    next_scores = compute_next_start_scores(table_allstart, cfg)

    # =====================================================
    # Baseline1
    # =====================================================
    print("\n=== Baseline1 ===")
    b1 = baseline1_with_plan(
        days_routes, depots, customers_days_active, mats_days, cfg,
        init_locs=init_locs, dd_km=dd_km, seed=seed_b1
    )
    if b1 is None:
        raise RuntimeError(f"Run {run_id + 1}: Baseline1 infeasible。")

    # =====================================================
    # Baseline2
    # =====================================================
    print("\n=== Baseline2 ===")
    b2 = baseline2_route_to_next_need(days_routes, table_allstart, need, init_locs, cfg, seed=seed_b2)
    if b2 is None:
        raise RuntimeError(f"Run {run_id + 1}: Baseline2 infeasible。")
    b2_cost, b2_var, b2_day_cost, b2_Ak, b2_end, b2_rtov = b2

    # =====================================================
    # Stage-2: Pareto
    # =====================================================
    print("\n=== Stage-2 MO-ALNS ===")
    # use Baseline2 as reference scale
    Cref = max(1e-9, b2_cost)
    Vref = max(1e-9, b2_var)

    all_archive = []
    for i, lam in enumerate(cfg["LAMBDA_LIST"]):
        arc = mo_alns_main(
            days_routes, table_allstart, init_locs, next_scores, cfg,
            seed=seed_stage2_base + 97 * i,
            lam=float(lam), Cref=Cref, Vref=Vref
        )
        all_archive.extend(arc)

    pareto = []
    for sol in all_archive:
        pareto = pareto_update(pareto, sol, cfg)

    if not pareto:
        raise RuntimeError(f"Run {run_id + 1}: 主算法未得到 Pareto 解。")

    pareto_points = sorted([(s[0], s[1]) for s in pareto], key=lambda x: x[0])

    chosen = pick_balanced_pareto(pareto)
    chosen_cost, chosen_var, chosen_rtov, chosen_end, chosen_day_cost, chosen_Ak = chosen

    # =====================================================
    # Evaluate summaries
    # =====================================================
    b1_summary = evaluate_scheme_summary(
        scheme_name="Baseline1",
        days_routes=days_routes,
        depots=depots,
        customers_days_active=customers_days_active,
        mats_days=mats_days,
        cfg=cfg,
        init_locs=init_locs,
        route_to_vehicle=b1["route_to_vehicle"],
        end_choice=b1["end_choice"],
        extra_cost=sum(b1["dispatch_costs"]) + b1["pre_dispatch_cost"],
        dispatch_cost=sum(b1["dispatch_costs"]) + b1["pre_dispatch_cost"],
    )

    b2_summary = evaluate_scheme_summary(
        scheme_name="Baseline2",
        days_routes=days_routes,
        depots=depots,
        customers_days_active=customers_days_active,
        mats_days=mats_days,
        cfg=cfg,
        init_locs=init_locs,
        route_to_vehicle=b2_rtov,
        end_choice=b2_end,
        extra_cost=0.0,
        dispatch_cost=0.0,
    )

    s3_summary = evaluate_scheme_summary(
        scheme_name="Stage2_Balanced",
        days_routes=days_routes,
        depots=depots,
        customers_days_active=customers_days_active,
        mats_days=mats_days,
        cfg=cfg,
        init_locs=init_locs,
        route_to_vehicle=chosen_rtov,
        end_choice=chosen_end,
        extra_cost=0.0,
        dispatch_cost=0.0,
    )

    print("\nRun summary:")
    print(f"  Baseline1 cost={b1_summary['total_cost']:.2f}, var={b1_summary['var_worktime']:.4f}")
    print(f"  Baseline2 cost={b2_summary['total_cost']:.2f}, var={b2_summary['var_worktime']:.4f}")
    print(f"  Stage2    cost={s3_summary['total_cost']:.2f}, var={s3_summary['var_worktime']:.4f}")

    return {
        "run_id": run_id,
        "run_seed": run_seed,

        "depots": depots,
        "customers_days_all": customers_days_all,
        "customers_days_active": customers_days_active,
        "mats_days": mats_days,
        "days_routes": days_routes,
        "init_locs": init_locs,

        "baseline1": {
            "cost": b1_summary["total_cost"],
            "var_worktime": b1_summary["var_worktime"],
            "Ak": b1_summary["Ak"],
            "summary": b1_summary,
            "route_to_vehicle": b1["route_to_vehicle"],
            "end_choice": b1["end_choice"],
        },
        "baseline2": {
            "cost": b2_summary["total_cost"],
            "var_worktime": b2_summary["var_worktime"],
            "Ak": b2_summary["Ak"],
            "summary": b2_summary,
            "route_to_vehicle": b2_rtov,
            "end_choice": b2_end,
        },
        "stage2": {
            "pareto_points": pareto_points,
            "pareto_archive": pareto,
            "balanced_cost": chosen_cost,
            "balanced_var": chosen_var,
            "balanced_Ak": chosen_Ak,
            "balanced_rtov": chosen_rtov,
            "balanced_end": chosen_end,
            "summary": s3_summary,
        },
    }


# =========================================================
# MULTI-RUN
# =========================================================
class ExperimentCancelled(Exception):
    """用户请求停止实验时抛出。"""


def run_multi_experiments(instance: Dict[str, Any], cfg: Dict[str, Any], on_progress=None, should_stop=None):
    n_runs = int(cfg["N_RUNS"])

    all_run_data = []
    rows_long = []

    for run_id in range(n_runs):
        if should_stop is not None and should_stop():
            raise ExperimentCancelled(f"实验在第 {run_id + 1}/{n_runs} 次开始前被停止")

        if on_progress is not None:
            on_progress({
                "phase": "run_start",
                "run_id": run_id,
                "n_runs": n_runs,
                "message": f"开始第 {run_id + 1}/{n_runs} 次实验...",
            })

        run_data = run_single_experiment(instance, cfg, run_id)
        all_run_data.append(run_data)

        rows_long.append(build_run_result_rows(run_id, run_data["baseline1"]["summary"]))
        rows_long.append(build_run_result_rows(run_id, run_data["baseline2"]["summary"]))
        rows_long.append(build_run_result_rows(run_id, run_data["stage2"]["summary"]))

        if on_progress is not None:
            s2 = run_data["stage2"]["summary"]
            on_progress({
                "phase": "run_done",
                "run_id": run_id,
                "n_runs": n_runs,
                "message": (
                    f"完成第 {run_id + 1}/{n_runs} 次实验 | "
                    f"Stage2成本={s2['total_cost']:.2f} | "
                    f"里程={s2['total_dist_km']:.2f}km"
                ),
                "stage2_cost": float(s2["total_cost"]),
                "stage2_dist_km": float(s2["total_dist_km"]),
            })

        if should_stop is not None and should_stop():
            raise ExperimentCancelled(f"实验在第 {run_id + 1}/{n_runs} 次完成后被停止")

    df_runs_long = pd.DataFrame(rows_long)
    df_runs_long.to_csv(cfg["RUN_RESULTS_CSV"], index=False, encoding="utf-8-sig")
    print(f"[CSV] saved: {cfg['RUN_RESULTS_CSV']}")

    return all_run_data, df_runs_long


def select_representative_run(df_runs_long: pd.DataFrame):
    """
    代表性运行：
    以主算法每次 Balanced 解的 total_cost 为准，
    选择最接近其 10 次平均成本的那一次。
    """
    s = df_runs_long[df_runs_long["scheme"] == "Stage2_Balanced"].copy()
    mean_cost = s["total_cost"].mean()
    s["dist_to_mean"] = (s["total_cost"] - mean_cost).abs()
    rep_idx = s["dist_to_mean"].idxmin()
    rep_run_id = int(s.loc[rep_idx, "run_id"])
    return rep_run_id


def select_best_stage2_run(df_runs_long: pd.DataFrame):
    """
    最优主算法运行：
    在 10 次主算法 Balanced 解中，选 total_cost 最小的那次。
    """
    s = df_runs_long[df_runs_long["scheme"] == "Stage2_Balanced"].copy()
    best_idx = s["total_cost"].idxmin()
    best_run_id = int(s.loc[best_idx, "run_id"])
    return best_run_id


def produce_representative_figures(rep_run_id: int, all_run_data: List[Dict[str, Any]], cfg: Dict[str, Any]):
    run = all_run_data[rep_run_id]

    pareto = run["stage2"]["pareto_points"]
    b1 = run["baseline1"]
    b2 = run["baseline2"]
    balanced = (run["stage2"]["balanced_cost"], run["stage2"]["balanced_var"])

    plot_pareto_with_baselines(
        pareto_points=pareto,
        base1=(b1["cost"], b1["var_worktime"]),
        base2=(b2["cost"], b2["var_worktime"]),
        chosen=balanced,
        out_png=cfg["REP_PARETO_PNG"]
    )

    plot_vehicle_worktime_histograms(
        b1["Ak"],
        b2["Ak"],
        run["stage2"]["balanced_Ak"],
        out_png=cfg["REP_WORKTIME_PNG"]
    )


def produce_best_stage2_outputs(best_run_id: int, all_run_data: List[Dict[str, Any]], cfg: Dict[str, Any]):
    run = all_run_data[best_run_id]

    # map
    make_map_multi_day(
        depots=run["depots"],
        customers_days_all=run["customers_days_all"],
        customers_days_active=run["customers_days_active"],
        days_routes=run["days_routes"],
        chosen_rtov=run["stage2"]["balanced_rtov"],
        chosen_end=run["stage2"]["balanced_end"],
        init_locs=run["init_locs"],
        cfg=cfg,
        out_html=cfg["MAP_OUT_HTML"]
    )

    # timeline / route sequence
    timeline_df, seq_df = export_stage2_vehicle_timeline(
        scheme_name="Stage2_Balanced",
        days_routes=run["days_routes"],
        depots=run["depots"],
        customers_days_active=run["customers_days_active"],
        mats_days=run["mats_days"],
        cfg=cfg,
        init_locs=run["init_locs"],
        route_to_vehicle=run["stage2"]["balanced_rtov"],
        end_choice=run["stage2"]["balanced_end"],
    )
    timeline_df.to_csv(cfg["BEST_STAGE2_TIMELINE_CSV"], index=False, encoding="utf-8-sig")
    seq_df.to_csv(cfg["BEST_STAGE2_ROUTE_SEQ_CSV"], index=False, encoding="utf-8-sig")
    print(f"[CSV] saved: {cfg['BEST_STAGE2_TIMELINE_CSV']}")
    print(f"[CSV] saved: {cfg['BEST_STAGE2_ROUTE_SEQ_CSV']}")


# =========================================================
# MAIN
# =========================================================
def run_pipeline(
    cfg_overrides: Optional[Dict[str, Any]] = None,
    on_progress=None,
    should_stop=None,
    day_frames: Optional[List[pd.DataFrame]] = None,
) -> Dict[str, Any]:
    """
    执行完整实验流水线。可通过 cfg_overrides 覆盖配置（如 N_RUNS）。
    on_progress: 可选回调，接收进度字典。
    should_stop: 可选回调，返回 True 时中断实验。
    day_frames: 可选，直接传入各日客户 DataFrame（来自 MongoDB），否则读 CSV。
    """
    cfg = dict(CFG)
    if cfg_overrides:
        cfg.update(cfg_overrides)

    def _emit(payload: Dict[str, Any]):
        if on_progress is not None:
            on_progress(payload)

    def _check_stop(where: str = ""):
        if should_stop is not None and should_stop():
            raise ExperimentCancelled(f"实验被用户停止{(' @ ' + where) if where else ''}")

    print("=============== SETTINGS ===============")
    print(f"T={cfg['T']} | K={cfg['K_VEHICLES']} | M={cfg['N_DEPOTS']} | seed={cfg['SEED']}")
    print(f"N_RUNS={cfg['N_RUNS']}")
    print(f"PSO: particles={cfg['N_PARTICLES']} iters={cfg['N_ITERS']}")
    print(f"Stage-2 MO-ALNS iters={cfg['ALNS_ITERS']} | lambdas={cfg['LAMBDA_LIST']}")
    print("========================================\n")

    _check_stop("init")
    _emit({"phase": "init", "message": "正在加载算例与路网矩阵...", "progress": 2})

    # load instance once
    instance = load_instance_and_matrices(cfg, day_frames=day_frames)

    _check_stop("instance_ready")
    _emit({"phase": "instance_ready", "message": "算例加载完成，开始多轮实验...", "progress": 8})

    # multi-run
    all_run_data, df_runs_long = run_multi_experiments(
        instance, cfg, on_progress=on_progress, should_stop=should_stop
    )

    _check_stop("summarize")
    _emit({"phase": "summarize", "message": "正在汇总统计结果...", "progress": 92})

    # summaries
    df_summary, df_best = compute_summary_tables(df_runs_long)
    df_summary.to_csv(cfg["RUN_SUMMARY_CSV"], index=False, encoding="utf-8-sig")
    df_best.to_csv(cfg["BEST_RUN_SUMMARY_CSV"], index=False, encoding="utf-8-sig")
    print(f"[CSV] saved: {cfg['RUN_SUMMARY_CSV']}")
    print(f"[CSV] saved: {cfg['BEST_RUN_SUMMARY_CSV']}")

    # improvements
    df_improv = compute_alns_improvement_per_run(df_runs_long)
    df_improv.to_csv(cfg["ALNS_IMPROV_PER_RUN_CSV"], index=False, encoding="utf-8-sig")
    df_improv_summary = compute_alns_improvement_summary(df_improv)
    df_improv_summary.to_csv(cfg["ALNS_IMPROV_SUMMARY_CSV"], index=False, encoding="utf-8-sig")
    print(f"[CSV] saved: {cfg['ALNS_IMPROV_PER_RUN_CSV']}")
    print(f"[CSV] saved: {cfg['ALNS_IMPROV_SUMMARY_CSV']}")

    # representative run for pareto/hist
    rep_run_id = select_representative_run(df_runs_long)
    print(f"\nRepresentative run (for Pareto + worktime hist): run_id={rep_run_id}")
    produce_representative_figures(rep_run_id, all_run_data, cfg)

    # best stage2 run for map
    best_stage2_run_id = select_best_stage2_run(df_runs_long)
    print(f"Best Stage2 Balanced run (for map): run_id={best_stage2_run_id}")
    produce_best_stage2_outputs(best_stage2_run_id, all_run_data, cfg)

    print("\n=============== SUMMARY ===============")
    print(f"Representative run id : {rep_run_id}")
    print(f"Best Stage2 run id    : {best_stage2_run_id}")
    print("Run results CSV       :", cfg["RUN_RESULTS_CSV"])
    print("Run summary CSV       :", cfg["RUN_SUMMARY_CSV"])
    print("Best run summary CSV  :", cfg["BEST_RUN_SUMMARY_CSV"])
    print("ALNS improv per run   :", cfg["ALNS_IMPROV_PER_RUN_CSV"])
    print("ALNS improv summary   :", cfg["ALNS_IMPROV_SUMMARY_CSV"])
    print("Representative Pareto :", cfg["REP_PARETO_PNG"])
    print("Representative hist   :", cfg["REP_WORKTIME_PNG"])
    print("Best Stage2 map       :", cfg["MAP_OUT_HTML"])
    print("Best Stage2 timeline  :", cfg["BEST_STAGE2_TIMELINE_CSV"])
    print("Best Stage2 route seq :", cfg["BEST_STAGE2_ROUTE_SEQ_CSV"])
    print("=======================================")

    _emit({"phase": "done", "message": "全部实验完成。", "progress": 100})

    return {
        "n_runs": int(cfg["N_RUNS"]),
        "rep_run_id": int(rep_run_id),
        "best_stage2_run_id": int(best_stage2_run_id),
        "summary": df_summary.to_dict(orient="records"),
        "best_runs": df_best.to_dict(orient="records"),
        "runs": df_runs_long.to_dict(orient="records"),
        "alns_improvement": df_improv.to_dict(orient="records"),
        "alns_improvement_summary": df_improv_summary.to_dict(orient="records"),
        "outputs": {
            "run_results": cfg["RUN_RESULTS_CSV"],
            "run_summary": cfg["RUN_SUMMARY_CSV"],
            "best_run_summary": cfg["BEST_RUN_SUMMARY_CSV"],
            "alns_improv_per_run": cfg["ALNS_IMPROV_PER_RUN_CSV"],
            "alns_improv_summary": cfg["ALNS_IMPROV_SUMMARY_CSV"],
            "pareto_png": cfg["REP_PARETO_PNG"],
            "worktime_png": cfg["REP_WORKTIME_PNG"],
            "map_html": cfg["MAP_OUT_HTML"],
            "timeline_csv": cfg["BEST_STAGE2_TIMELINE_CSV"],
            "route_seq_csv": cfg["BEST_STAGE2_ROUTE_SEQ_CSV"],
        },
    }


def main():
    run_pipeline()


if __name__ == "__main__":
    main()
