"""
动态生产线可视化API
提供甘特图驱动的动态演示接口
与生产线和冰箱作业模块集成
"""

import json
import pickle
import numpy as np
from typing import Dict, List, Any, Optional
from flask import Blueprint, jsonify, request, session
import copy

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

# 创建蓝图
production_visualization_bp = Blueprint('production_visualization', __name__)


class ProductionVisualizationManager:
    """
    生产线可视化管理器
    单例模式，维护全局生产线状态
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not ProductionVisualizationManager._initialized:
            self.production_line = None
            self.job_manager = None
            self.animator = None
            self.gantt_data = []
            self.is_initialized = False
            ProductionVisualizationManager._initialized = True
    
    def initialize(self, gantt_data: List[List[Any]] = None, n_jobs: int = 8):
        """初始化生产线可视化"""
        from utils.production_line import ProductionLine, GanttAnimator
        from utils.refrigerator_job import RefrigeratorJobManager
        
        if self.production_line is None:
            self.production_line = ProductionLine(n_jobs=n_jobs)
        
        if self.job_manager is None:
            self.job_manager = RefrigeratorJobManager(n_jobs=n_jobs)
            self.job_manager.set_production_line(self.production_line)
        
        if self.animator is None:
            self.animator = GanttAnimator(self.production_line)
        
        # 加载甘特图数据
        if gantt_data is not None:
            self.gantt_data = gantt_data
            self.animator.initialize(gantt_data)
            self.job_manager.load_from_gantt(gantt_data)
            self.is_initialized = True
        
        return self
    
    def get_current_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        if not self.is_initialized:
            return self._get_empty_state()
        
        # 获取生产线状态
        production_state = self.production_line.get_current_state()
        
        # 获取作业状态
        job_state = self.job_manager.get_current_state()
        
        # 获取动画状态
        animator_state = self.animator.get_current_frame() if self.animator else {}
        
        # 合并状态
        return {
            "ok": True,
            "data": {
                "production": production_state,
                "jobs": job_state,
                "animator": animator_state,
                "sync_data": self.production_line.export_gantt_sync_data() if self.production_line else {},
                "statistics": self.job_manager.get_statistics() if self.job_manager else {}
            }
        }
    
    def _get_empty_state(self) -> Dict[str, Any]:
        """获取空状态"""
        return {
            "ok": True,
            "data": {
                "production": {
                    "current_time": 0,
                    "workstations": [],
                    "jobs": [],
                    "total_jobs": 8,
                    "completed_jobs": 0
                },
                "jobs": {"jobs": [], "statistics": {}},
                "animator": {"is_playing": False, "progress": 0}
            }
        }
    
    def set_time(self, time: float):
        """设置当前时间"""
        if self.production_line:
            self.production_line.step_to_time(time)
            if self.job_manager:
                self.job_manager.load_from_gantt(self.gantt_data)
    
    def step(self, delta: float = 1.0):
        """前进一步"""
        if self.animator:
            self.animator.step_forward(delta)
    
    def play(self):
        """开始播放"""
        if self.animator:
            self.animator.play()
    
    def pause(self):
        """暂停播放"""
        if self.animator:
            self.animator.pause()
    
    def stop(self):
        """停止"""
        if self.animator:
            self.animator.stop()
    
    def set_speed(self, speed: float):
        """设置速度"""
        if self.animator:
            self.animator.set_speed(speed)


# 全局管理器实例
_manager = None

def get_manager() -> ProductionVisualizationManager:
    """获取管理器实例"""
    global _manager
    if _manager is None:
        _manager = ProductionVisualizationManager()
    return _manager

def reset_manager():
    """重置管理器实例"""
    global _manager
    _manager = None


def generate_demo_gantt_data(n_jobs: int = 8, max_time: float = 100.0) -> List[List[Any]]:
    """
    生成演示用的甘特图数据
    模拟8个冰箱订单在18个工位上的加工过程
    
    Returns:
        List of [start_time, duration, workstation_id, job_id, process_id]
    """
    np.random.seed(42)  # 固定种子确保可重复
    
    gantt_data = []
    
    # 工序定义（标准工时）
    process_times = {
        0: 8,   # 钣金成型
        1: 6,   # 内胆吸塑
        2: 12,  # 发泡填充
        3: 10,  # 压缩机安装
        4: 9,   # 管路焊接
        5: 7,   # 电气元件装配
        6: 11,  # 总装合箱
        7: 5,   # 检测调试
        8: 4    # 打包入库
    }
    
    # 工序到工位的映射（2个并行工位为一组）
    process_workstations = {
        0: [0, 1],      # 钣金成型
        1: [2, 3],      # 内胆吸塑
        2: [4, 5, 6],   # 发泡填充（3个工位）
        3: [7, 8],      # 压缩机安装
        4: [9, 10],     # 管路焊接
        5: [11, 12],    # 电气元件装配
        6: [13, 14],    # 总装合箱
        7: [15, 16],    # 检测调试
        8: [17]         # 打包入库（1个工位）
    }
    
    for job_id in range(n_jobs):
        # 每个作业的开始时间有随机偏移，实现错峰启动
        job_offset = np.random.uniform(0, 5) * job_id
        current_time = job_offset
        
        # 工序0: 钣金成型（首工序，无前置约束）
        process_id = 0
        duration = process_times[process_id] + np.random.uniform(-1, 2)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(current_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        current_time += duration
        
        # 工序1: 内胆吸塑
        process_id = 1
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-1, 1)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        current_time = start_time + duration
        
        # 工序2: 发泡填充（需等待工序0和1完成）
        process_id = 2
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-1, 3)
        ws_id = process_workstations[process_id][job_id % 3]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        current_time = start_time + duration
        
        # 工序3: 压缩机安装
        process_id = 3
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-1, 2)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        current_time = start_time + duration
        
        # 工序4和5可以并行（管路焊接和电气元件装配）
        # 这里简化为串行执行，因为真实的并行调度由QMIX智能体决定
        process_id = 4
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-1, 1.5)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        process_4_end = start_time + duration
        
        process_id = 5
        duration = process_times[process_id] + np.random.uniform(-1, 1)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        process_5_end = start_time + duration
        
        # 下一工序必须等两个并行工序都完成
        current_time = max(process_4_end, process_5_end)
        
        # 工序6: 总装合箱（需等待4和5完成）
        process_id = 6
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-1, 2)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        current_time = start_time + duration
        
        # 工序7: 检测调试
        process_id = 7
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-0.5, 1)
        ws_id = process_workstations[process_id][job_id % 2]
        gantt_data.append([float(start_time), float(duration), int(ws_id), int(job_id), int(process_id)])
        current_time = start_time + duration
        
        # 工序8: 打包入库
        process_id = 8
        start_time = current_time
        duration = process_times[process_id] + np.random.uniform(-0.5, 0.5)
        gantt_data.append([float(start_time), float(duration), 17, int(job_id), int(process_id)])
    
    # 按时间排序
    gantt_data.sort(key=lambda x: (x[0], x[3]))
    
    return gantt_data


# API端点

@production_visualization_bp.route('/api/production/initialize', methods=['POST'])
def api_initialize_production():
    """
    初始化生产线可视化
    POST body: {
        "n_jobs": 8,  // 可选，默认8
        "gantt_data": [...]  // 可选，使用提供的甘特图数据
    }
    """
    try:
        manager = get_manager()
        
        data = request.get_json() or {}
        n_jobs = data.get('n_jobs', 8)
        gantt_data = data.get('gantt_data')
        
        # 如果没有提供甘特图数据，生成演示数据
        if gantt_data is None:
            gantt_data = generate_demo_gantt_data(n_jobs=n_jobs)
        
        manager.initialize(gantt_data=gantt_data, n_jobs=n_jobs)
        
        # 返回初始化信息
        return jsonify({
            "ok": True,
            "data": {
                "initialized": True,
                "n_jobs": n_jobs,
                "n_workstations": 18,
                "n_processes": 9,
                "gantt_records": len(gantt_data),
                "max_time": max((r[0] + r[1] for r in gantt_data), default=100),
                "sync_data": manager.production_line.export_gantt_sync_data() if manager.production_line else {}
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/state', methods=['GET'])
def api_production_state():
    """获取当前生产线状态"""
    try:
        manager = get_manager()
        if not manager.is_initialized:
            return jsonify({
                "ok": True,
                "data": {
                    "initialized": False,
                    "message": "生产线未初始化，请先调用 /api/production/initialize"
                }
            })
        
        return jsonify(manager.get_current_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/time', methods=['POST'])
def api_set_time():
    """
    设置当前时间
    POST body: {"time": 50.0}
    """
    try:
        manager = get_manager()
        data = request.get_json() or {}
        time = float(data.get('time', 0))
        
        manager.set_time(time)
        
        return jsonify(manager.get_current_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/step', methods=['POST'])
def api_step():
    """
    前进一步
    POST body: {"delta": 1.0}
    """
    try:
        manager = get_manager()
        data = request.get_json() or {}
        delta = float(data.get('delta', 1.0))
        
        manager.step(delta)
        
        return jsonify(manager.get_current_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/play', methods=['POST'])
def api_play():
    """开始播放动画"""
    try:
        manager = get_manager()
        manager.play()
        return jsonify(manager.get_current_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/pause', methods=['POST'])
def api_pause():
    """暂停播放动画"""
    try:
        manager = get_manager()
        manager.pause()
        return jsonify(manager.get_current_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/stop', methods=['POST'])
def api_stop():
    """停止动画"""
    try:
        manager = get_manager()
        manager.stop()
        return jsonify(manager.get_current_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/speed', methods=['POST'])
def api_set_speed():
    """
    设置播放速度
    POST body: {"speed": 2.0}
    """
    try:
        manager = get_manager()
        data = request.get_json() or {}
        speed = float(data.get('speed', 1.0))
        
        manager.set_speed(speed)
        
        return jsonify({
            "ok": True,
            "data": {"speed": speed}
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/jobs', methods=['GET'])
def api_get_jobs():
    """获取冰箱作业列表"""
    try:
        manager = get_manager()
        if not manager.is_initialized or not manager.job_manager:
            return jsonify({
                "ok": True,
                "data": {"jobs": [], "statistics": {}}
            })
        
        from utils.refrigerator_job import JobVisualizationHelper
        helper = JobVisualizationHelper(manager.job_manager)
        
        return jsonify({
            "ok": True,
            "data": {
                "jobs": helper.format_jobs_for_frontend(),
                "statistics": manager.job_manager.get_statistics()
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/workstations', methods=['GET'])
def api_get_workstations():
    """获取工位状态列表"""
    try:
        manager = get_manager()
        if not manager.is_initialized or not manager.job_manager:
            return jsonify({
                "ok": True,
                "data": {"workstations": []}
            })
        
        from utils.refrigerator_job import JobVisualizationHelper
        helper = JobVisualizationHelper(manager.job_manager)
        
        return jsonify({
            "ok": True,
            "data": {
                "workstations": helper.format_workstations_for_frontend(),
                "total": len(manager.production_line.workstations) if manager.production_line else 0,
                "busy": len([ws for ws in manager.production_line.workstations.values() 
                            if ws.status.value == "busy"]) if manager.production_line else 0
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/flow', methods=['GET'])
def api_get_process_flow():
    """获取工序流程图数据"""
    try:
        manager = get_manager()
        if not manager.is_initialized or not manager.job_manager:
            return jsonify({
                "ok": True,
                "data": {"flow": [], "process_definitions": {}}
            })
        
        from utils.refrigerator_job import JobVisualizationHelper
        helper = JobVisualizationHelper(manager.job_manager)
        
        # 获取工序定义
        process_defs = {}
        if manager.production_line:
            for pid, pd in manager.production_line.PROCESS_DEFINITIONS.items():
                process_defs[pid] = {
                    "id": pd.process_id,
                    "name": pd.name,
                    "standard_time": pd.standard_time,
                    "color": pd.color,
                    "workstation_ids": pd.workstation_ids,
                    "parallel_capable": pd.parallel_capable
                }
        
        return jsonify({
            "ok": True,
            "data": {
                "flow": helper.format_process_flow(),
                "process_definitions": process_defs
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/gantt-data', methods=['GET'])
def api_get_gantt_data():
    """获取甘特图原始数据"""
    try:
        manager = get_manager()
        return jsonify({
            "ok": True,
            "data": {
                "gantt_data": manager.gantt_data,
                "max_time": max((r[0] + r[1] for r in manager.gantt_data), default=100) if manager.gantt_data else 100
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/statistics', methods=['GET'])
def api_get_statistics():
    """获取生产统计信息"""
    try:
        manager = get_manager()
        if not manager.is_initialized:
            return jsonify({
                "ok": True,
                "data": {
                    "current_time": 0,
                    "completion_rate": 0,
                    "throughput": 0,
                    "workstation_utilization": 0,
                    "avg_job_progress": 0,
                    "active_processes": 0
                }
            })
        
        stats = manager.production_line.get_statistics() if manager.production_line else {}
        job_stats = manager.job_manager.get_statistics() if manager.job_manager else {}
        
        return jsonify({
            "ok": True,
            "data": {
                **stats,
                "job_statistics": job_stats
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@production_visualization_bp.route('/api/production/demo-data', methods=['GET'])
def api_get_demo_data():
    """
    获取演示数据（用于在没有评估结果时展示）
    GET params: n_jobs=8
    """
    try:
        n_jobs = int(request.args.get('n_jobs', 8))
        
        # 生成演示数据
        gantt_data = generate_demo_gantt_data(n_jobs=n_jobs)
        
        # 计算最大时间
        max_time = float(max([r[0] + r[1] for r in gantt_data], default=100.0))
        
        # 工序定义（简单字典格式，避免dataclass编码问题）
        process_defs = {
            0: {"name": "钣金成型", "color": "#2563eb", "standard_time": 8.0, "workstation_ids": [0, 1]},
            1: {"name": "内胆吸塑", "color": "#7c3aed", "standard_time": 6.0, "workstation_ids": [2, 3]},
            2: {"name": "发泡填充", "color": "#0891b2", "standard_time": 12.0, "workstation_ids": [4, 5, 6]},
            3: {"name": "压缩机安装", "color": "#059669", "standard_time": 10.0, "workstation_ids": [7, 8]},
            4: {"name": "管路焊接", "color": "#d97706", "standard_time": 9.0, "workstation_ids": [9, 10]},
            5: {"name": "电气元件装配", "color": "#dc2626", "standard_time": 7.0, "workstation_ids": [11, 12]},
            6: {"name": "总装合箱", "color": "#7c2d12", "standard_time": 11.0, "workstation_ids": [13, 14]},
            7: {"name": "检测调试", "color": "#0d9488", "standard_time": 5.0, "workstation_ids": [15, 16]},
            8: {"name": "打包入库", "color": "#4b5563", "standard_time": 4.0, "workstation_ids": [17]}
        }
        
        return jsonify({
            "ok": True,
            "data": {
                "initialized": True,
                "gantt_data": gantt_data,
                "n_jobs": n_jobs,
                "max_time": max_time,
                "sync_data": {
                    "process_definitions": process_defs
                }
            }
        })
    except Exception as e:
        import traceback
        import sys
        exc_info = ''.join(traceback.format_exception(*sys.exc_info()))
        print(f"ERROR in demo-data: {e}\n{exc_info}", file=sys.stderr)
        return jsonify({
            "ok": False, 
            "error": str(e)
        }), 500
