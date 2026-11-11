import os
import glob
import json
import pickle
import traceback
from typing import Tuple, Optional, Dict, Any, List

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

import numpy as np
from environment import ScheduleEnv

from runner import Runner
from common.arguments import (
    get_common_args,
    get_coma_args,
    get_mixer_args,
    get_centralv_args,
    get_reinforce_args,
    get_commnet_args,
    get_g2anet_args,
)
from common.data_file_utils import get_data_file_path, get_data_dir
from api_factory_visualization import factory_visualization_bp
from api_production_visualization import production_visualization_bp


# ---- 模型文件预检查，避免运行时才失败 ----------------------------------------
def _find_model_files(n_agents: int, model_num: str, base_dir: str = "./model/qmix/boatschedule") -> Optional[Tuple[str, str]]:
    """
    返回可用的 (rnn_path, qmix_path)，优先新格式 agents{n}_{id}_*.pkl，回退旧格式 {id}_*.pkl。
    """
    candidates = [
        f"agents{n_agents}_{model_num}",
        f"{model_num}",
    ]
    for prefix in candidates:
        rnn = os.path.join(base_dir, f"{prefix}_rnn_net_params.pkl")
        qmix = os.path.join(base_dir, f"{prefix}_qmix_net_params.pkl")
        if os.path.exists(rnn) and os.path.exists(qmix):
            return rnn, qmix
    return None


# ---- 数据加载与指标计算 -------------------------------------------------------
def _safe_remove(path: str):
    if os.path.exists(path):
        os.remove(path)


def _load_lines_as_float(path: str) -> List[float]:
    if not os.path.exists(path):
        return []
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(float(line))
            except ValueError:
                continue
    return data


def _load_rewards(n_agents: int) -> List[float]:
    rewards_file = get_data_file_path(
        get_data_dir(), "accumulated_rewards.txt", n_agents, is_training=False
    )
    return _load_lines_as_float(rewards_file)


def _load_makespans(n_agents: int) -> List[float]:
    times_file = get_data_file_path(
        get_data_dir(), "times.txt", n_agents, is_training=False
    )
    return _load_lines_as_float(times_file)


def _load_schedule_data(n_agents: int) -> Dict[str, Any]:
    pickle_path = get_data_file_path(
        get_data_dir(), "schedule_data.pkl", n_agents, is_training=False
    )
    if not os.path.exists(pickle_path):
        return {}
    try:
        with open(pickle_path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def _compute_episode_count(n_agents: int, fallback: int) -> int:
    rewards = _load_rewards(n_agents)
    makespans = _load_makespans(n_agents)
    schedule = _load_schedule_data(n_agents).get("all_schedule_data", [])
    return max(fallback, len(rewards), len(makespans), len(schedule))


def _to_scalar(x):
    try:
        if hasattr(x, "item"):
            return x.item()
    except Exception:
        pass
    if isinstance(x, (int, float, str, bool)) or x is None:
        return x
    try:
        return float(x)
    except Exception:
        return None


def _normalize_gantt(data: Any) -> List[List[Any]]:
    """将甘特数据中的 numpy/tuple 转为纯 Python 列表/标量，避免 JSON 序列化失败。"""
    result = []
    if not isinstance(data, list):
        return result
    for item in data:
        if isinstance(item, (list, tuple)):
            result.append([_to_scalar(v) for v in item])
    return result


# ---- 核心评估逻辑（与 evaluate_model_10/8 一致，做成函数便于 API 复用） --------
def run_evaluation(n_agents: int, model_num: str, evaluate_epoch: int) -> Dict[str, Any]:
    # 公共参数
    args = get_common_args()
    args.model_dir = "./model"  # 兼容当前模型目录
    args.learn = False
    args.load_model = True
    args.model_num = str(model_num)
    args.evaluate_epoch = int(evaluate_epoch)

    # 补全算法相关参数
    if args.alg.find("coma") > -1:
        args = get_coma_args(args)
    elif args.alg.find("central_v") > -1:
        args = get_centralv_args(args)
    elif args.alg.find("reinforce") > -1:
        args = get_reinforce_args(args)
    else:
        args = get_mixer_args(args)
    if args.alg.find("commnet") > -1:
        args = get_commnet_args(args)
    if args.alg.find("g2anet") > -1:
        args = get_g2anet_args(args)

    # 预检查模型文件存在性
    model_check = _find_model_files(n_agents, args.model_num)
    if not model_check:
        raise FileNotFoundError(
            f"未找到模型文件，n_agents={n_agents}, model_num={args.model_num}，期望路径例如 ./model/qmix/boatschedule/agents{n_agents}_{args.model_num}_*.pkl 或 {args.model_num}_*.pkl"
        )

    # 构建环境并同步形状参数
    env = ScheduleEnv(n_agents=n_agents)
    env.reset()
    env_info = env.get_env_info()
    args.n_actions = env_info["n_actions"]
    args.n_agents = env_info["n_agents"]
    args.state_shape = env_info["state_shape"]
    args.obs_shape = env_info["obs_shape"]
    args.episode_limit = env_info["episode_limit"]

    runner = Runner(env, args)

    evaluation_epsilon = 0.01
    base_seed = 2
    all_schedule_data = []
    win_number = 0
    episode_rewards_sum = 0.0
    episode_rewards_list: List[float] = []
    episode_times_list: List[float] = []

    # 清理旧的评估文件，避免多次评估数据混淆
    data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    eval_files = [
        get_data_file_path(data_dir, "scheduleresults.txt", n_agents, is_training=False),
        get_data_file_path(data_dir, "schedule_data.pkl", n_agents, is_training=False),
        get_data_file_path(data_dir, "accumulated_rewards.txt", n_agents, is_training=False),
        get_data_file_path(data_dir, "times.txt", n_agents, is_training=False),
        get_data_file_path(data_dir, "havealook.txt", n_agents, is_training=False),
        get_data_file_path(data_dir, "loss.txt", n_agents, is_training=False),
    ]
    for f in eval_files:
        _safe_remove(f)

    for epoch in range(args.evaluate_epoch):
        episode_seed = base_seed + epoch
        np.random.seed(episode_seed)
        env.seed(episode_seed)

        # 临时放宽 epsilon，增加少量随机性
        original_epsilon = runner.rolloutWorker.epsilon
        runner.rolloutWorker.epsilon = evaluation_epsilon

        _, episode_reward, win_tag, for_gant, episode_time = runner.rolloutWorker.generate_episode(
            epoch, evaluate=True
        )

        runner.rolloutWorker.epsilon = original_epsilon
        episode_rewards_sum += float(episode_reward)
        episode_rewards_list.append(float(episode_reward))
        episode_times_list.append(float(episode_time) if episode_time else 0.0)
        if win_tag:
            win_number += 1
        all_schedule_data.append(for_gant if for_gant is not None else [])

    win_rate = win_number / args.evaluate_epoch if args.evaluate_epoch else 0.0
    avg_reward = episode_rewards_sum / args.evaluate_epoch if args.evaluate_epoch else 0.0

    # 保存文本
    scheduleresults_path = get_data_file_path(
        data_dir, "scheduleresults.txt", args.n_agents, is_training=False
    )
    with open(scheduleresults_path, "w", encoding="utf-8") as f:
        print("=" * 50, file=f)
        print(f"模型编号: {args.model_num}", file=f)
        print(f"评估episode数: {args.evaluate_epoch}", file=f)
        print(f"平均奖励: {avg_reward}", file=f)
        print("=" * 50, file=f)
        for idx, schedule_data in enumerate(all_schedule_data):
            print(f"\nEpisode {idx+1} 调度数据:", file=f)
            if schedule_data:
                print(schedule_data, file=f)
            else:
                print("[] (episode未正常终止或没有调度数据)", file=f)

    # 保存 pickle
    pickle_path = get_data_file_path(
        data_dir, "schedule_data.pkl", args.n_agents, is_training=False
    )
    with open(pickle_path, "wb") as f:
        import pickle

        pickle.dump(
            {
                "model_num": args.model_num,
                "evaluate_epoch": args.evaluate_epoch,
                "avg_reward": avg_reward,
                "win_rate": win_rate,
                "all_schedule_data": all_schedule_data,
            },
            f,
        )

    # 其他文件路径（rollout / qmix 内部会写）
    rewards_file = get_data_file_path(
        data_dir, "accumulated_rewards.txt", args.n_agents, is_training=False
    )
    times_file = get_data_file_path(
        data_dir, "times.txt", args.n_agents, is_training=False
    )
    havealook_file = get_data_file_path(
        data_dir, "havealook.txt", args.n_agents, is_training=False
    )
    loss_file = get_data_file_path(
        data_dir, "loss.txt", args.n_agents, is_training=False
    )

    # 评估完成后加载指标，确保返回给前端
    # 优先使用内存中的数据
    makespans = episode_times_list if episode_times_list else _load_makespans(args.n_agents)
    rewards_list = episode_rewards_list if episode_rewards_list else _load_rewards(args.n_agents)
    gantt_data = [_normalize_gantt(g) for g in all_schedule_data]
    episode_count = _compute_episode_count(args.n_agents, args.evaluate_epoch)

    result = {
        "ok": True,
        "n_agents": int(args.n_agents),
        "model_num": str(args.model_num),
        "evaluate_epoch": int(args.evaluate_epoch),
        "avg_reward": float(avg_reward),
        "win_rate": float(win_rate),
        "makespans": makespans,
        "rewards": rewards_list,
        "episode_count": int(episode_count),
        # 直接返回甘特数据，前端可立即渲染，避免再读文件
        "gantt": gantt_data,
        "files": {
            "scheduleresults": scheduleresults_path,
            "pickle": pickle_path,
            "accumulated_rewards": rewards_file,
            "times": times_file,
            "havealook": havealook_file,
            "loss": loss_file,
        },
    }
    return result


# ---- Flask 应用 -------------------------------------------------------------
# 统一由 Flask 提供前端静态文件和后端 API，避免再使用 python -m http.server
app = Flask(__name__, static_folder="frontend", static_url_path="")

# 自定义JSON编码器，处理numpy类型
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def numpy_jsonify(data):
    """使用numpy兼容的JSON序列化"""
    return app.response_class(
        json.dumps(data, cls=NumpyEncoder),
        mimetype='application/json'
    )

# 应用自定义JSON编码器
app.json_encoder = NumpyEncoder

# 允许跨域（即便前后端同源，保留不影响）
CORS(app, resources={r"/*": {"origins": "*"}})


@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"

    # 统一规范响应头中的 charset 为 utf-8，避免浏览器/审计工具大小写或缺失警告
    # HTML
    if resp.mimetype == "text/html":
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # CSS
    elif resp.mimetype == "text/css":
        resp.headers["Content-Type"] = "text/css; charset=utf-8"
    # JS
    elif resp.mimetype in ("application/javascript", "text/javascript"):
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    # JSON
    elif resp.mimetype in ("application/json", "text/json"):
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.route("/", methods=["GET"])
def index():
    """前端入口页面，返回 frontend/index.html。"""
    # 使用 static_folder 提供的文件
    return app.send_static_file("index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    """提供静态资源（css/js），方便缓存控制或定制路径。"""
    root_dir = os.path.join(os.path.dirname(__file__), "frontend")
    return send_from_directory(root_dir, filename)


@app.route("/evaluate", methods=["POST", "OPTIONS"])
def evaluate():
    try:
        # 处理预检请求
        if request.method == "OPTIONS":
            return "", 204

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"ok": False, "error": "请求体需要 JSON"}), 400

        scene_mode = str(data.get("scene_mode", "assembly"))
        n_agents = int(data.get("n_agents", 10))
        n_agvs = int(data.get("n_agvs", 4))
        model_num = str(data.get("model_num", "35"))
        evaluate_epoch = int(data.get("evaluate_epoch", 20))

        # 组合校验：支持 6/8/10，可按需扩展
        # 更新后的模型使用数字前缀命名
        allowed_aliases = {
            6: ["6"],
            8: ["8"],
            10: ["10"],
        }
        if n_agents not in allowed_aliases:
            return jsonify({"ok": False, "error": "仅支持 n_agents 为 6、8、10"}), 400
        # 规范化比较（小写）
        mn = str(model_num).lower()
        allowed_for_n = [a.lower() for a in allowed_aliases[n_agents]]
        if mn not in allowed_for_n:
            return jsonify(
                {
                    "ok": False,
                    "error": f"n_agents={n_agents} 仅支持 model_num in {allowed_aliases[n_agents]}",
                }
            ), 400

        if scene_mode == "joint":
            result = run_joint_evaluation(n_agents, n_agvs, model_num, evaluate_epoch)
        else:
            result = run_evaluation(n_agents, model_num, evaluate_epoch)
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(e),
                    "trace": traceback.format_exc(limit=5),
                }
            ),
            500,
        )


@app.route("/api/evaluation/<int:n_agents>", methods=["GET", "OPTIONS"])
def get_evaluation(n_agents: int):
    if request.method == "OPTIONS":
        return "", 204
    try:
        makespans = _load_makespans(n_agents)
        rewards = _load_rewards(n_agents)
        schedule = _load_schedule_data(n_agents)
        all_schedule_data = schedule.get("all_schedule_data", [])
        all_schedule_data = [_normalize_gantt(g) for g in all_schedule_data]
        episode_count = _compute_episode_count(n_agents, 0)
        return jsonify(
            {
                "ok": True,
                "n_agents": n_agents,
                "makespans": makespans,
                "rewards": rewards,
                "episode_count": episode_count,
                "has_schedule": bool(all_schedule_data),
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(e),
                    "trace": traceback.format_exc(limit=5),
                }
            ),
            500,
        )


@app.route("/api/evaluation/<int:n_agents>/gantt/<int:episode_id>", methods=["GET", "OPTIONS"])
def get_gantt(n_agents: int, episode_id: int):
    if request.method == "OPTIONS":
        return "", 204
    try:
        schedule = _load_schedule_data(n_agents)
        all_schedule_data = schedule.get("all_schedule_data", [])
        if not all_schedule_data:
            return jsonify({"ok": False, "error": "暂无调度数据"}), 404
        idx = episode_id - 1
        if idx < 0 or idx >= len(all_schedule_data):
            return jsonify({"ok": False, "error": "episode_id 超出范围"}), 400
        return jsonify(
            {
                "ok": True,
                "episode_id": episode_id,
                "data": _normalize_gantt(all_schedule_data[idx]),
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(e),
                    "trace": traceback.format_exc(limit=5),
                }
            ),
            500,
        )


def run_joint_evaluation(n_agents: int, n_agvs: int, model_num: str, evaluate_epoch: int) -> Dict[str, Any]:
    """运行联合场景评估（AGV + 冰箱组装）"""
    from joint_trainer import JointTrainer

    try:
        # 创建联合训练器，传入AGV数量参数
        trainer = JointTrainer(n_agvs=n_agvs)

        # 初始化环境
        if not trainer.initialize_trainers():
            raise RuntimeError("Failed to initialize joint trainer")

        # 运行评估
        results = trainer.evaluate(evaluate_epoch)

        # 构建返回结果
        result = {
            "ok": True,
            "scene_mode": "joint",
            "n_agents": n_agents,
            "n_agvs": n_agvs,
            "model_num": model_num,
            "evaluate_epoch": evaluate_epoch,
            "agv_reward_mean": results.get("agv_reward_mean", 0),
            "assembly_reward_mean": results.get("assembly_reward_mean", 0),
            "joint_reward_mean": results.get("joint_reward_mean", 0),
            "material_shortages_mean": results.get("material_shortages_mean", 0),
            "completion_time_mean": results.get("completion_time_mean", results.get("completion_time_mean", 0)),
            # 关键：返回真实的makespans和rewards
            "makespans": results.get("makespans", []),
            "rewards": results.get("rewards", []),
            "avg_reward": float(results.get("avg_reward", results.get("joint_reward_mean", 0))),
            "win_rate": results.get("win_rate", 0.0),
            "episode_count": evaluate_epoch,
            # 工位状态
            "workstation_states": results.get("workstation_states", []),
            # AGV车队状态
            "agv_utilization": float(results.get("avg_agv_utilization", 0.75)),
            "agv_busy_count": float(results.get("avg_busy_agvs", 3)),
            "agv_total_count": int(results.get("total_agvs", n_agvs)),
            "agv_states": results.get("agv_states", []),
            # 运输统计
            "total_deliveries": int(results.get("total_deliveries", 0)),
            "on_time_delivery_rate": float(results.get("on_time_rate", 0)),
        }

        # 保存AGV状态到文件，供前端API接口读取
        import pickle
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        agv_state_path = os.path.join(data_dir, "agv_states.pkl")
        with open(agv_state_path, "wb") as f:
            pickle.dump({
                "agv_states": result["agv_states"],
                "avg_utilization": result["agv_utilization"],
                "avg_busy_agvs": result["agv_busy_count"],
                "total_agvs": result["agv_total_count"],
                "total_deliveries": result["total_deliveries"],
                "on_time_rate": result["on_time_delivery_rate"],
                "timestamp": __import__('time').time()
            }, f)

        return result

    except Exception as e:
        print(f"Joint evaluation failed: {e}")
        raise


# 注册工厂可视化蓝图
app.register_blueprint(factory_visualization_bp)
# 注册生产线动态可视化蓝图
app.register_blueprint(production_visualization_bp)


if __name__ == "__main__":
    # 启动 Flask 服务，监听 5000 端口
    app.run(host="0.0.0.0", port=5000, debug=False)
