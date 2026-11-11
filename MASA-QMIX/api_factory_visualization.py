"""
工厂可视化后端API
提供工厂布局、工位状态、AGV位置、物料库存等实时数据
包含零件厂、组装厂、供应链物流的完整可视化
"""

import json
import os
import pickle
import random
import numpy as np
from typing import Dict, List, Any, Optional
from flask import Blueprint, jsonify, request

# 创建蓝图
factory_visualization_bp = Blueprint('factory_visualization', __name__)


def get_factory_layout() -> Dict[str, Any]:
    """获取工厂布局信息（基础版）"""
    layout = {
        "central_warehouse": {
            "position": [0, 0],
            "capacity": 1000,
            "name": "中央仓库"
        },
        "workstations": [
            {
                "id": 0,
                "name": "钣金成型工位",
                "position": [50, 0],
                "buffer_position": [45, 5],
                "buffer_capacity": 50,
                "process_id": 0,
                "process_name": "钣金成型",
                "standard_time": 8
            },
            {
                "id": 1,
                "name": "内胆吸塑工位",
                "position": [100, 0],
                "buffer_position": [95, 5],
                "buffer_capacity": 40,
                "process_id": 1,
                "process_name": "内胆吸塑",
                "standard_time": 6
            },
            {
                "id": 2,
                "name": "发泡填充工位",
                "position": [150, 0],
                "buffer_position": [145, 5],
                "buffer_capacity": 60,
                "process_id": 2,
                "process_name": "发泡填充",
                "standard_time": 12
            },
            {
                "id": 3,
                "name": "压缩机安装工位",
                "position": [200, 0],
                "buffer_position": [195, 5],
                "buffer_capacity": 50,
                "process_id": 3,
                "process_name": "压缩机安装",
                "standard_time": 10
            },
            {
                "id": 4,
                "name": "管路焊接工位",
                "position": [200, 30],
                "buffer_position": [195, 35],
                "buffer_capacity": 40,
                "process_id": 4,
                "process_name": "管路焊接",
                "standard_time": 9
            },
            {
                "id": 5,
                "name": "电气元件装配工位",
                "position": [250, 0],
                "buffer_position": [245, 5],
                "buffer_capacity": 40,
                "process_id": 5,
                "process_name": "电气元件装配",
                "standard_time": 7
            },
            {
                "id": 6,
                "name": "总装合箱工位",
                "position": [300, 0],
                "buffer_position": [295, 5],
                "buffer_capacity": 60,
                "process_id": 6,
                "process_name": "总装合箱",
                "standard_time": 11
            },
            {
                "id": 7,
                "name": "检测打包工位",
                "position": [350, 0],
                "buffer_position": [345, 5],
                "buffer_capacity": 50,
                "process_id": 7,
                "process_name": "检测打包",
                "standard_time": 5
            }
        ],
        "charging_stations": [
            {"id": 0, "position": [0, 0], "name": "充电站1"},
            {"id": 1, "position": [50, 50], "name": "充电站2"},
            {"id": 2, "position": [100, 50], "name": "充电站3"},
            {"id": 3, "position": [150, 50], "name": "充电站4"}
        ],
        "paths": [
            # 主要路径网络
            {"from": [0, 0], "to": [50, 0]},
            {"from": [50, 0], "to": [100, 0]},
            {"from": [100, 0], "to": [150, 0]},
            {"from": [150, 0], "to": [200, 0]},
            {"from": [200, 0], "to": [250, 0]},
            {"from": [250, 0], "to": [300, 0]},
            {"from": [300, 0], "to": [350, 0]},
            {"from": [200, 0], "to": [200, 30]},
            {"from": [200, 30], "to": [200, 50]},
            {"from": [0, 0], "to": [0, 50]},
            {"from": [50, 0], "to": [50, 50]},
            {"from": [100, 0], "to": [100, 50]},
            {"from": [150, 0], "to": [150, 50]}
        ]
    }
    return layout


def get_extended_factory_layout() -> Dict[str, Any]:
    """
    获取扩展的工厂布局信息
    包含零件厂、中央仓库、组装车间、成品仓库的完整供应链结构
    """
    # 固定随机种子确保一致性
    random.seed(42)
    np.random.seed(42)
    
    # ===== 零件供应商区 =====
    parts_factories = [
        {
            "id": 0,
            "name": "压缩机供应商",
            "short_name": "压缩机",
            "position": [-80, -60],
            "produces": ["compressor", "compressor_mount"],  # 产出物料
            "capacity": 50,  # 日产能
            "delivery_time": 15,  # 配送时间(min)
            "type": "supplier",
            "color": "#ef4444",
            "icon": "🏭",
            "status": "normal",
            "current_output": 45,
            "order_queue": 12
        },
        {
            "id": 1,
            "name": "电气元件供应商",
            "short_name": "电气",
            "position": [-80, -20],
            "produces": ["circuit_board", "sensor", "wire_harness", "switch"],
            "capacity": 100,
            "delivery_time": 10,
            "type": "supplier",
            "color": "#3b82f6",
            "icon": "⚡",
            "status": "normal",
            "current_output": 88,
            "order_queue": 8
        },
        {
            "id": 2,
            "name": "钣金件供应商",
            "short_name": "钣金",
            "position": [-80, 20],
            "produces": ["metal_panel", "door_frame", "inner_liner"],
            "capacity": 80,
            "delivery_time": 12,
            "type": "supplier",
            "color": "#a78bfa",
            "icon": "🔧",
            "status": "normal",
            "current_output": 72,
            "order_queue": 15
        },
        {
            "id": 3,
            "name": "发泡料供应商",
            "short_name": "发泡料",
            "position": [-80, 60],
            "produces": ["foam_material", "sealant"],
            "capacity": 30,
            "delivery_time": 20,
            "type": "supplier",
            "color": "#22c55e",
            "icon": "🧴",
            "status": "normal",
            "current_output": 28,
            "order_queue": 5
        },
        {
            "id": 4,
            "name": "门体配件供应商",
            "short_name": "门体",
            "position": [-40, 80],
            "produces": ["door_gasket", "hinge", "handle"],
            "capacity": 60,
            "delivery_time": 8,
            "type": "supplier",
            "color": "#f59e0b",
            "icon": "🚪",
            "status": "normal",
            "current_output": 55,
            "order_queue": 6
        },
        {
            "id": 5,
            "name": "包装材料供应商",
            "short_name": "包装",
            "position": [-40, -80],
            "produces": ["packing_box", "foam_corner", "certificate"],
            "capacity": 200,
            "delivery_time": 5,
            "type": "supplier",
            "color": "#6b7280",
            "icon": "📦",
            "status": "normal",
            "current_output": 180,
            "order_queue": 20
        }
    ]
    
    # ===== 中央仓库 =====
    central_warehouse = {
        "id": "central_warehouse",
        "name": "中央仓库",
        "position": [0, 0],
        "capacity": 5000,
        "zones": [
            {
                "id": "raw_material",
                "name": "原料存储区",
                "position": [-30, -40],
                "capacity": 2000,
                "current_stock": 1650,
                "color": "#fbbf24"
            },
            {
                "id": "parts_buffer",
                "name": "零件缓存区",
                "position": [0, 0],
                "capacity": 1500,
                "current_stock": 1200,
                "color": "#38bdf8"
            },
            {
                "id": "finished_goods",
                "name": "成品暂存区",
                "position": [30, 40],
                "capacity": 500,
                "current_stock": 180,
                "color": "#a3e635"
            }
        ],
        "inventory": {
            "compressor": {"quantity": 45, "capacity": 100, "status": "normal"},
            "circuit_board": {"quantity": 120, "capacity": 200, "status": "normal"},
            "metal_panel": {"quantity": 80, "capacity": 150, "status": "normal"},
            "foam_material": {"quantity": 25, "capacity": 50, "status": "warning"},
            "door_gasket": {"quantity": 95, "capacity": 100, "status": "normal"},
            "wire_harness": {"quantity": 60, "capacity": 100, "status": "normal"},
            "sensor": {"quantity": 150, "capacity": 200, "status": "normal"},
            "packing_box": {"quantity": 200, "capacity": 300, "status": "normal"}
        }
    }
    
    # ===== 组装车间（8个工位）=====
    assembly_factory = {
        "id": "assembly_factory",
        "name": "冰箱组装车间",
        "position": [150, 0],
        "production_lines": [
            {
                "id": 0,
                "name": "A线",
                "workstations": list(range(8)),
                "status": "running",
                "throughput": 4.2  # 台/小时
            },
            {
                "id": 1,
                "name": "B线",
                "workstations": list(range(8, 16)),
                "status": "standby",  # 待机
                "throughput": 0
            }
        ],
        "workstations": [
            {
                "id": 0, "name": "钣金成型", "position": [50, 0],
                "process_id": 0, "standard_time": 8,
                "required_materials": ["metal_panel", "door_frame"],
                "produces": "metal_frame"
            },
            {
                "id": 1, "name": "内胆吸塑", "position": [100, 0],
                "process_id": 1, "standard_time": 6,
                "required_materials": ["inner_liner"],
                "produces": "inner_liner_assembly"
            },
            {
                "id": 2, "name": "发泡填充", "position": [150, 0],
                "process_id": 2, "standard_time": 12,
                "required_materials": ["foam_material", "sealant"],
                "produces": "foam_assembly"
            },
            {
                "id": 3, "name": "压缩机安装", "position": [200, 0],
                "process_id": 3, "standard_time": 10,
                "required_materials": ["compressor", "compressor_mount"],
                "produces": "compressor_assembly"
            },
            {
                "id": 4, "name": "管路焊接", "position": [200, 25],
                "process_id": 4, "standard_time": 9,
                "required_materials": [],
                "produces": "pipe_system"
            },
            {
                "id": 5, "name": "电气元件装配", "position": [250, 0],
                "process_id": 5, "standard_time": 7,
                "required_materials": ["circuit_board", "sensor", "wire_harness", "switch"],
                "produces": "electrical_assembly"
            },
            {
                "id": 6, "name": "总装合箱", "position": [300, 0],
                "process_id": 6, "standard_time": 11,
                "required_materials": ["door_gasket", "hinge", "handle"],
                "produces": "finished_unit"
            },
            {
                "id": 7, "name": "检测打包", "position": [350, 0],
                "process_id": 7, "standard_time": 5,
                "required_materials": ["packing_box", "foam_corner", "certificate"],
                "produces": "shipped_product"
            }
        ]
    }
    
    # ===== 物流路径定义 =====
    logistics_paths = [
        # 入厂物流：零件厂 → 中央仓库
        {"from": [parts_factories[0]["position"][0]+30, parts_factories[0]["position"][1]],
         "to": central_warehouse["zones"][0]["position"],
         "type": "inbound", "color": "#4ade80", "label": "压缩机配送"},
        {"from": [parts_factories[1]["position"][0]+30, parts_factories[1]["position"][1]],
         "to": central_warehouse["zones"][0]["position"],
         "type": "inbound", "color": "#4ade80", "label": "电气元件配送"},
        {"from": [parts_factories[2]["position"][0]+30, parts_factories[2]["position"][1]],
         "to": central_warehouse["zones"][0]["position"],
         "type": "inbound", "color": "#4ade80", "label": "钣金件配送"},
        {"from": [parts_factories[3]["position"][0]+30, parts_factories[3]["position"][1]],
         "to": central_warehouse["zones"][0]["position"],
         "type": "inbound", "color": "#4ade80", "label": "发泡料配送"},
        {"from": [parts_factories[4]["position"][0]+30, parts_factories[4]["position"][1]],
         "to": central_warehouse["zones"][0]["position"],
         "type": "inbound", "color": "#4ade80", "label": "门体配件配送"},
        {"from": [parts_factories[5]["position"][0]+30, parts_factories[5]["position"][1]],
         "to": central_warehouse["zones"][0]["position"],
         "type": "inbound", "color": "#4ade80", "label": "包装材料配送"},
        
        # 内部物流：原料区 → 零件缓存区
        {"from": central_warehouse["zones"][0]["position"],
         "to": central_warehouse["zones"][1]["position"],
         "type": "internal", "color": "#60a5fa", "label": "物料转运"},
        
        # 配送物流：零件缓存区 → 各工位
        {"from": central_warehouse["zones"][1]["position"],
         "to": assembly_factory["workstations"][0]["position"],
         "type": "material", "color": "#facc15", "label": "配送钣金件"},
        {"from": central_warehouse["zones"][1]["position"],
         "to": assembly_factory["workstations"][1]["position"],
         "type": "material", "color": "#facc15", "label": "配送内胆件"},
        {"from": central_warehouse["zones"][1]["position"],
         "to": assembly_factory["workstations"][2]["position"],
         "type": "material", "color": "#facc15", "label": "配送发泡料"},
        {"from": central_warehouse["zones"][1]["position"],
         "to": assembly_factory["workstations"][3]["position"],
         "type": "material", "color": "#facc15", "label": "配送压缩机"},
        {"from": central_warehouse["zones"][1]["position"],
         "to": assembly_factory["workstations"][5]["position"],
         "type": "material", "color": "#facc15", "label": "配送电气件"},
        {"from": central_warehouse["zones"][1]["position"],
         "to": assembly_factory["workstations"][6]["position"],
         "type": "material", "color": "#facc15", "label": "配送门体件"},
        
        # 生产流程（组装线内部）
        {"from": assembly_factory["workstations"][0]["position"],
         "to": assembly_factory["workstations"][1]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][1]["position"],
         "to": assembly_factory["workstations"][2]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][2]["position"],
         "to": assembly_factory["workstations"][3]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][3]["position"],
         "to": assembly_factory["workstations"][4]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][3]["position"],
         "to": assembly_factory["workstations"][5]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][4]["position"],
         "to": assembly_factory["workstations"][6]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][5]["position"],
         "to": assembly_factory["workstations"][6]["position"],
         "type": "production", "color": "#a78bfa"},
        {"from": assembly_factory["workstations"][6]["position"],
         "to": assembly_factory["workstations"][7]["position"],
         "type": "production", "color": "#a78bfa"},
        
        # 成品出库
        {"from": assembly_factory["workstations"][7]["position"],
         "to": central_warehouse["zones"][2]["position"],
         "type": "outbound", "color": "#f87171", "label": "成品入库"}
    ]
    
    # ===== 工序依赖关系图 =====
    process_dependency = {
        "nodes": [
            {"id": 0, "name": "钣金成型", "group": "assembly", "color": "#2563eb", 
             "description": "冰箱外壳成型", "workstation": "工位0"},
            {"id": 1, "name": "内胆吸塑", "group": "assembly", "color": "#7c3aed",
             "description": "ABS内胆成型", "workstation": "工位1"},
            {"id": 2, "name": "发泡填充", "group": "assembly", "color": "#0891b2",
             "description": "聚氨酯保温层", "workstation": "工位2"},
            {"id": 3, "name": "压缩机安装", "group": "assembly", "color": "#059669",
             "description": "压缩机就位固定", "workstation": "工位3"},
            {"id": 4, "name": "管路焊接", "group": "assembly", "color": "#d97706",
             "description": "制冷管路连接", "workstation": "工位4", "parallel_with": 5},
            {"id": 5, "name": "电气元件装配", "group": "assembly", "color": "#dc2626",
             "description": "电控系统安装", "workstation": "工位5", "parallel_with": 4},
            {"id": 6, "name": "总装合箱", "group": "assembly", "color": "#7c2d12",
             "description": "门体安装密封", "workstation": "工位6"},
            {"id": 7, "name": "检测打包", "group": "assembly", "color": "#0d9488",
             "description": "质检包装入库", "workstation": "工位7"}
        ],
        "links": [
            {"source": 0, "target": 2, "type": "sequential", "description": "钣金→发泡"},
            {"source": 1, "target": 2, "type": "sequential", "description": "内胆→发泡"},
            {"source": 2, "target": 3, "type": "sequential", "description": "发泡→压缩机"},
            {"source": 3, "target": 4, "type": "sequential", "description": "压缩机→管路"},
            {"source": 3, "target": 5, "type": "parallel", "description": "并行作业"},
            {"source": 4, "target": 6, "type": "sequential", "description": "管路→总装"},
            {"source": 5, "target": 6, "type": "sequential", "description": "电气→总装"},
            {"source": 6, "target": 7, "type": "sequential", "description": "总装→检测"}
        ]
    }
    
    return {
        "parts_factories": parts_factories,
        "central_warehouse": central_warehouse,
        "assembly_factory": assembly_factory,
        "logistics_paths": logistics_paths,
        "process_dependency": process_dependency,
        # 布局元数据
        "layout_info": {
            "view_box": {"x": -150, "y": -100, "width": 600, "height": 250},
            "grid_size": 50,
            "animation_enabled": True
        }
    }


def get_material_types() -> List[Dict[str, Any]]:
    """获取所有物料类型信息"""
    from utils.material import MaterialType, MaterialPriority
    
    materials = []
    for i, mat_type in enumerate(MaterialType):
        name = MaterialType.get_name(i)
        priority = MaterialPriority.get_by_material(mat_type)
        materials.append({
            "id": i,
            "name": name,
            "priority": priority.value,
            "priority_name": priority.name
        })
    return materials


def get_agv_types() -> List[Dict[str, Any]]:
    """获取AGV类型配置"""
    from utils.agv import AGVConfig, AGVType
    from utils.material import MaterialType
    
    agv_types = []
    for agv_id, config in AGVConfig.CONFIGS.items():
        materials = []
        for mat in config["materials"]:
            materials.append({
                "id": mat.value,
                "name": MaterialType.get_name(mat.value)
            })
        agv_types.append({
            "id": agv_id,
            "type": config["type"].value,
            "name": config["name"],
            "max_capacity": config["max_capacity"],
            "max_speed": config["max_speed"],
            "materials": materials,
            "description": config.get("description", "")
        })
    return agv_types


def get_process_definitions() -> List[Dict[str, Any]]:
    """获取工序定义"""
    from utils.refrigerator_process import RefrigeratorProcess
    
    processes = []
    for pid, proc in RefrigeratorProcess.PROCESSES.items():
        processes.append({
            "id": pid,
            "name": proc["name"],
            "standard_time": proc["standard_time"],
            "materials": proc["materials"],
            "predecessors": proc["predecessors"],
            "workstation": proc["workstation"],
            "workstation_id": proc["workstation_id"],
            "parallel_capable": proc["parallel_capable"],
            "critical_path": proc["critical_path"]
        })
    return processes


# API端点
@factory_visualization_bp.route('/api/factory/layout', methods=['GET'])
def api_factory_layout():
    """获取工厂布局"""
    try:
        layout = get_factory_layout()
        return jsonify({
            "ok": True,
            "data": layout
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@factory_visualization_bp.route('/api/factory/materials', methods=['GET'])
def api_factory_materials():
    """获取物料类型列表"""
    try:
        materials = get_material_types()
        return jsonify({
            "ok": True,
            "data": materials
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@factory_visualization_bp.route('/api/factory/agv-types', methods=['GET'])
def api_factory_agv_types():
    """获取AGV类型配置"""
    try:
        agv_types = get_agv_types()
        return jsonify({
            "ok": True,
            "data": agv_types
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@factory_visualization_bp.route('/api/factory/processes', methods=['GET'])
def api_factory_processes():
    """获取工序定义"""
    try:
        processes = get_process_definitions()
        return jsonify({
            "ok": True,
            "data": processes
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@factory_visualization_bp.route('/api/factory/simulation', methods=['GET'])
def api_simulation_state():
    """获取当前模拟状态（从保存的pickle文件加载，或返回模拟数据）"""
    try:
        import os
        from common.data_file_utils import get_data_dir, get_data_file_path
        
        data_dir = get_data_dir()
        sim_state_path = os.path.join(data_dir, "simulation_state.pkl")
        
        # 尝试从pickle文件加载
        if os.path.exists(sim_state_path):
            with open(sim_state_path, 'rb') as f:
                sim_state = pickle.load(f)
            return jsonify({
                "ok": True,
                "data": sim_state
            })
        
        # 返回模拟的AGV数据（使用固定种子确保每次调用结果一致）
        import random
        import numpy as np
        
        # 使用固定随机种子确保数据一致
        random.seed(42)
        np.random.seed(42)
        
        # 生成固定的AGV数据（多数处于活跃状态）
        agv_data = [
            {
                "id": 0, "name": "AGV0", "type": "重型",
                "status_name": "MOVING",
                "position": [120, 25],
                "battery_level": 85.5,
                "current_load": 150,
                "max_capacity": 500
            },
            {
                "id": 1, "name": "AGV1", "type": "轻型",
                "status_name": "LOADING",
                "position": [60, 0],
                "battery_level": 92.3,
                "current_load": 80,
                "max_capacity": 100
            },
            {
                "id": 2, "name": "AGV2", "type": "流体",
                "status_name": "MOVING",
                "position": [240, 15],
                "battery_level": 72.8,
                "current_load": 200,
                "max_capacity": 200
            },
            {
                "id": 3, "name": "AGV3", "type": "通用",
                "status_name": "IDLE",
                "position": [0, 0],
                "battery_level": 100.0,
                "current_load": 0,
                "max_capacity": 150
            }
        ]
        
        # 生成工位数据 - 模拟真实生产线：大部分工位有生产任务
        # 实际生产中，产线应该是流水线的形式，多个工位同时工作
        # 冰箱生产有8个工序：钣金成型 -> 内胆吸塑 -> 发泡填充 -> 压缩机安装 -> 管路焊接 -> 电气元件 -> 总装合箱 -> 检测打包
        # 正常情况下，前工序(钣金、内胆、发泡)会同时工作，后续工序根据节拍协同工作
        workstation_data = []
        # 定义每个工位的典型处理时间（分钟）和利用率
        workstation_configs = [
            {"occupied_prob": 0.9, "remaining_range": (2, 8)},   # 钣金成型 - 高利用率
            {"occupied_prob": 0.85, "remaining_range": (1, 6)},  # 内胆吸塑 - 高利用率
            {"occupied_prob": 0.8, "remaining_range": (3, 12)},   # 发泡填充 - 较长时间
            {"occupied_prob": 0.75, "remaining_range": (2, 10)}, # 压缩机安装
            {"occupied_prob": 0.7, "remaining_range": (1, 9)},   # 管路焊接
            {"occupied_prob": 0.8, "remaining_range": (1, 7)},   # 电气元件 - 装配工序
            {"occupied_prob": 0.85, "remaining_range": (2, 11)},# 总装合箱 - 核心工序
            {"occupied_prob": 0.9, "remaining_range": (1, 5)}    # 检测打包 - 出货前检测
        ]
        for i, config in enumerate(workstation_configs):
            is_occupied = random.random() < config["occupied_prob"]
            remaining_time = random.randint(*config["remaining_range"]) if is_occupied else 0
            workstation_data.append({
                "id": i,
                "occupied": is_occupied,
                "remaining_time": remaining_time
            })
        
        return jsonify({
            "ok": True,
            "data": {
                "agvs": agv_data,
                "workstations": workstation_data,
                "materials": {},
                "timestamp": 0
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：统计概览接口
@factory_visualization_bp.route('/api/stats/overview', methods=['GET'])
def api_stats_overview():
    """获取系统统计概览"""
    try:
        import os
        from common.data_file_utils import get_data_dir
        
        data_dir = get_data_dir()
        
        # 读取评估结果
        makespans = []
        rewards = []
        
        makespan_path = os.path.join(data_dir, "times.txt")
        reward_path = os.path.join(data_dir, "accumulated_rewards.txt")
        
        if os.path.exists(makespan_path):
            with open(makespan_path, 'r') as f:
                makespans = [float(line.strip()) for line in f if line.strip()]
        
        if os.path.exists(reward_path):
            with open(reward_path, 'r') as f:
                rewards = [float(line.strip()) for line in f if line.strip()]
        
        avg_makespan = sum(makespans) / len(makespans) if makespans else 0
        avg_reward = sum(rewards) / len(rewards) if rewards else 0
        
        return jsonify({
            "ok": True,
            "data": {
                "total_episodes": len(makespans),
                "avg_makespan": round(avg_makespan, 2),
                "avg_reward": round(avg_reward, 4),
                "min_makespan": min(makespans) if makespans else 0,
                "max_makespan": max(makespans) if makespans else 0,
                "win_rate": len([m for m in makespans if m < 100]) / len(makespans) if makespans else 0
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：AGV车队状态接口
@factory_visualization_bp.route('/api/agv/fleet', methods=['GET'])
def api_agv_fleet():
    """获取AGV车队状态"""
    try:
        import pickle
        from common.data_file_utils import get_data_dir
        
        data_dir = get_data_dir()
        agv_state_path = os.path.join(data_dir, "agv_states.pkl")
        
        # 尝试从pickle文件加载真实AGV状态
        if os.path.exists(agv_state_path):
            try:
                with open(agv_state_path, 'rb') as f:
                    saved_data = pickle.load(f)
                
                agv_states = saved_data.get("agv_states", [])
                if agv_states:
                    return jsonify({
                        "ok": True,
                        "data": {
                            "total": saved_data.get("total_agvs", len(agv_states)),
                            "active": saved_data.get("avg_busy_agvs", 0),
                            "utilization": saved_data.get("avg_utilization", 0),
                            "agvs": agv_states
                        }
                    })
            except Exception:
                pass  # 如果读取失败，使用默认数据
        
        # 如果没有真实数据，使用模拟数据（用于非联合评估场景）
        agv_fleet = [
            {
                "id": i,
                "name": f"AGV{i}",
                "type": ["重型", "轻型", "流体", "通用"][i % 4],
                "status_name": "MOVING" if i < 3 else "IDLE",
                "position": [60 + i * 80, 25],
                "battery_level": 85 - i * 5,
                "current_load": 150 if i < 3 else 0,
                "max_capacity": [500, 100, 200, 150][i % 4],
                "speed": [30, 40, 25, 35][i % 4],
                "total_distance": 500 + i * 100,
                "total_deliveries": 15 + i * 3
            }
            for i in range(4)
        ]
        
        return jsonify({
            "ok": True,
            "data": {
                "total": 4,
                "active": 3,
                "utilization": 0.75,
                "agvs": agv_fleet
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：物料库存接口
@factory_visualization_bp.route('/api/material/inventory', methods=['GET'])
def api_material_inventory():
    """获取物料库存信息"""
    try:
        materials = [
            {"id": 1, "name": "钣金件", "quantity": 450, "capacity": 500, "percent": 90, "status": "充足"},
            {"id": 2, "name": "内胆件", "quantity": 320, "capacity": 400, "percent": 80, "status": "充足"},
            {"id": 3, "name": "发泡料", "quantity": 180, "capacity": 300, "percent": 60, "status": "充足"},
            {"id": 4, "name": "压缩机", "quantity": 95, "capacity": 100, "percent": 95, "status": "充足"},
            {"id": 5, "name": "铜管", "quantity": 280, "capacity": 400, "percent": 70, "status": "充足"},
            {"id": 6, "name": "电气元件", "quantity": 520, "capacity": 600, "percent": 87, "status": "充足"},
            {"id": 7, "name": "包装材料", "quantity": 380, "capacity": 500, "percent": 76, "status": "充足"},
            {"id": 8, "name": "检测设备", "quantity": 45, "capacity": 50, "percent": 90, "status": "充足"}
        ]
        
        return jsonify({
            "ok": True,
            "data": {
                "total_types": len(materials),
                "sufficient_count": len([m for m in materials if m["percent"] > 30]),
                "low_stock_count": len([m for m in materials if m["percent"] <= 30]),
                "materials": materials
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：扩展工厂布局接口
@factory_visualization_bp.route('/api/factory/layout/extended', methods=['GET'])
def api_extended_factory_layout():
    """获取扩展的工厂布局（包含零件厂、供应链、物流路径）"""
    try:
        layout = get_extended_factory_layout()
        return jsonify({
            "ok": True,
            "data": layout
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：供应链状态接口
@factory_visualization_bp.route('/api/supply-chain/status', methods=['GET'])
def api_supply_chain_status():
    """获取完整供应链状态"""
    try:
        # 生成实时模拟数据
        random.seed(int(__import__('time').time()) % 1000)
        
        # 在途配送
        in_transit = [
            {
                "id": f"TR{1001+i}",
                "supplier_id": i % 6,
                "supplier_name": ["压缩机供应商", "电气元件供应商", "钣金件供应商", 
                                  "发泡料供应商", "门体配件供应商", "包装材料供应商"][i % 6],
                "material": ["compressor", "circuit_board", "metal_panel", 
                            "foam_material", "door_gasket", "packing_box"][i % 6],
                "quantity": random.randint(10, 50),
                "departure_time": random.uniform(0, 30),
                "estimated_arrival": random.uniform(5, 25),
                "status": random.choice(["on_the_way", "arriving", "delayed"]),
                "vehicle_id": f"VH{random.randint(1, 10):03d}",
                "progress": random.uniform(0.3, 0.9)
            }
            for i in range(6)
        ]
        
        # 配送计划
        delivery_schedule = [
            {
                "scheduled_time": t,
                "supplier_id": s,
                "material": ["compressor", "circuit_board", "metal_panel", 
                           "foam_material", "door_gasket", "packing_box"][s],
                "quantity": random.randint(20, 80),
                "priority": random.choice(["normal", "urgent", "low"])
            }
            for s, t in [(0, 10), (1, 15), (2, 12), (3, 8), (4, 20), (5, 18)]
        ]
        
        # 关键缺料预警
        shortages = [
            {"material": "foam_material", "severity": "high", "message": "发泡料库存低于安全库存", "affected_workstation": "发泡填充"},
            {"material": "compressor", "severity": "medium", "message": "压缩机库存紧张", "affected_workstation": "压缩机安装"}
        ] if random.random() > 0.5 else []
        
        # 供应商性能
        supplier_performance = [
            {
                "supplier_id": i,
                "name": ["压缩机供应商", "电气元件供应商", "钣金件供应商", 
                        "发泡料供应商", "门体配件供应商", "包装材料供应商"][i],
                "on_time_rate": random.uniform(0.85, 0.99),
                "quality_rate": random.uniform(0.95, 0.999),
                "avg_delivery_time": random.uniform(8, 22),
                "status": random.choice(["normal", "warning", "critical"])
            }
            for i in range(6)
        ]
        
        return jsonify({
            "ok": True,
            "data": {
                "in_transit": in_transit,
                "delivery_schedule": delivery_schedule,
                "critical_shortages": shortages,
                "supplier_performance": supplier_performance,
                "summary": {
                    "total_suppliers": 6,
                    "active_deliveries": len(in_transit),
                    "pending_deliveries": len(delivery_schedule),
                    "shortage_alerts": len(shortages)
                }
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：物流路径实时状态
@factory_visualization_bp.route('/api/logistics/paths', methods=['GET'])
def api_logistics_paths():
    """获取物流路径实时状态"""
    try:
        random.seed(42)
        
        paths = [
            # 入厂物流
            {"path_id": "inbound_0", "type": "inbound", "status": "active", 
             "throughput": 12.5, "utilization": random.uniform(0.6, 0.9)},
            {"path_id": "inbound_1", "type": "inbound", "status": "active",
             "throughput": 18.2, "utilization": random.uniform(0.5, 0.8)},
            {"path_id": "inbound_2", "type": "inbound", "status": "active",
             "throughput": 15.8, "utilization": random.uniform(0.4, 0.7)},
            {"path_id": "inbound_3", "type": "inbound", "status": "congested",
             "throughput": 8.5, "utilization": 0.95},
            # 内部物流
            {"path_id": "internal_0", "type": "internal", "status": "active",
             "throughput": 45.0, "utilization": random.uniform(0.5, 0.75)},
            # 配送物流
            {"path_id": "material_0", "type": "material", "status": "active",
             "throughput": 6.2, "utilization": random.uniform(0.3, 0.6)},
            {"path_id": "material_1", "type": "material", "status": "active",
             "throughput": 5.8, "utilization": random.uniform(0.3, 0.6)},
            {"path_id": "material_2", "type": "material", "status": "active",
             "throughput": 7.1, "utilization": random.uniform(0.4, 0.7)},
            # 成品出库
            {"path_id": "outbound_0", "type": "outbound", "status": "active",
             "throughput": 3.5, "utilization": random.uniform(0.2, 0.5)}
        ]
        
        return jsonify({
            "ok": True,
            "data": {
                "paths": paths,
                "total_throughput": sum(p["throughput"] for p in paths),
                "avg_utilization": sum(p["utilization"] for p in paths) / len(paths)
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：工序依赖关系API
@factory_visualization_bp.route('/api/process/dependency', methods=['GET'])
def api_process_dependency():
    """获取工序依赖关系图数据"""
    try:
        layout = get_extended_factory_layout()
        process_dep = layout.get("process_dependency", {})
        
        # 添加实时状态
        random.seed(42)
        nodes_with_status = []
        for node in process_dep.get("nodes", []):
            node_copy = node.copy()
            node_copy["current_load"] = random.uniform(0.5, 0.95)
            node_copy["queue_length"] = random.randint(0, 5)
            node_copy["avg_waiting_time"] = random.uniform(2, 15)
            node_copy["status"] = random.choice(["running", "running", "running", "idle", "blocked"])
            nodes_with_status.append(node_copy)
        
        return jsonify({
            "ok": True,
            "data": {
                "nodes": nodes_with_status,
                "links": process_dep.get("links", []),
                "parallel_groups": [
                    {"processes": [4, 5], "shared_predecessor": 3, "name": "管路焊接 & 电气元件装配"}
                ],
                "critical_path": [0, 2, 3, 5, 6, 7]  # 关键路径
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# 新增：实时物料流动数据
@factory_visualization_bp.route('/api/material/flow', methods=['GET'])
def api_material_flow():
    """获取实时物料流动数据（用于动画）"""
    try:
        random.seed(int(__import__('time').time()) % 1000)
        
        # 物料流动批次
        material_flows = [
            {
                "flow_id": f"MF{1000+i}",
                "material": ["compressor", "metal_panel", "foam_material", 
                           "circuit_board", "door_gasket"][i % 5],
                "material_name": ["压缩机", "钣金件", "发泡料", "电路板", "门体密封条"][i % 5],
                "from_location": ["压缩机供应商", "钣金件供应商", "发泡料供应商", 
                                 "电气元件供应商", "门体配件供应商"][i % 5],
                "to_location": "中央仓库",
                "quantity": random.randint(10, 30),
                "start_time": random.uniform(0, 50),
                "estimated_end": random.uniform(10, 60),
                "current_position": random.uniform(0, 1),  # 0=起点, 1=终点
                "status": random.choice(["transporting", "arrived", "loading", "unloading"])
            }
            for i in range(8)
        ]
        
        # 工位物料消耗预测
        consumption_forecast = [
            {
                "workstation_id": i,
                "workstation_name": ["钣金成型", "内胆吸塑", "发泡填充", "压缩机安装",
                                     "管路焊接", "电气元件装配", "总装合箱", "检测打包"][i],
                "required_materials": [
                    {"material": ["metal_panel"], "quantity": random.randint(1, 3), "supply_status": "sufficient"},
                    {"material": ["inner_liner"], "quantity": random.randint(1, 2), "supply_status": "sufficient"},
                    {"material": ["foam_material"], "quantity": random.randint(2, 4), "supply_status": "low"},
                    {"material": ["compressor"], "quantity": 1, "supply_status": "sufficient"},
                    {"material": ["copper_tube"], "quantity": random.randint(1, 2), "supply_status": "sufficient"},
                    {"material": ["circuit_board"], "quantity": 1, "supply_status": "sufficient"},
                    {"material": ["door_gasket"], "quantity": random.randint(1, 2), "supply_status": "sufficient"},
                    {"material": ["packing_box"], "quantity": 1, "supply_status": "sufficient"}
                ][i]
            }
            for i in range(8)
        ]
        
        return jsonify({
            "ok": True,
            "data": {
                "material_flows": material_flows,
                "consumption_forecast": consumption_forecast,
                "total_active_flows": len([f for f in material_flows if f["status"] == "transporting"])
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def save_simulation_state(state: Dict[str, Any]):
    """保存模拟状态到pickle文件"""
    import os
    from common.data_file_utils import get_data_dir
    
    data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    
    sim_state_path = os.path.join(data_dir, "simulation_state.pkl")
    
    with open(sim_state_path, 'wb') as f:
        pickle.dump(state, f)


def export_simulation_snapshot(
    refrigerators: List,
    agv_fleet,
    production_line,
    material_manager,
    current_time: float
) -> Dict[str, Any]:
    """导出当前模拟状态的快照"""
    
    # 冰箱状态
    fridge_states = []
    for fridge in refrigerators:
        fridge_states.append({
            "id": fridge.order_id,
            "priority": fridge.priority,
            "current_process": fridge.current_process,
            "completed_processes": fridge.completed_processes,
            "status": fridge.status.value if hasattr(fridge.status, 'value') else str(fridge.status),
            "position": fridge.position if hasattr(fridge, 'position') else None
        })
    
    # AGV状态
    agv_states = []
    if agv_fleet:
        for agv in agv_fleet.agvs:
            agv_states.append({
                "id": agv.agv_id,
                "name": agv.config.get("name", f"AGV{agv.agv_id}"),
                "position": agv.position.tolist() if hasattr(agv.position, 'tolist') else list(agv.position),
                "status": agv.status.value if hasattr(agv.status, 'value') else str(agv.status),
                "status_name": agv.status.name if hasattr(agv.status, 'name') else str(agv.status),
                "battery_level": agv.battery_level,
                "current_load": agv.current_load,
                "max_capacity": agv.max_capacity,
                "cargo": {str(k): v for k, v in agv.cargo.items()} if hasattr(agv, 'cargo') else {},
                "target_position": agv.target_position.tolist() if agv.target_position is not None else None
            })
    
    # 工位状态
    workstation_states = []
    if production_line:
        for ws_id, workstation in production_line.workstations.items():
            workstation_states.append({
                "id": ws_id,
                "name": workstation.get("name", f"工位{ws_id}"),
                "occupied": workstation.get("occupied", False),
                "current_refrigerator": workstation.get("current_refrigerator"),
                "remaining_time": workstation.get("remaining_time", 0)
            })
    
    # 物料库存
    material_stock = {}
    if material_manager:
        # 获取所有物料库存
        for mat_type in material_manager.storage.keys():
            stock = material_manager.get_stock(mat_type)
            material_stock[str(mat_type.value)] = {
                "name": MaterialType.get_name(mat_type.value),
                "quantity": stock
            }
    
    snapshot = {
        "timestamp": current_time,
        "refrigerators": fridge_states,
        "agvs": agv_states,
        "workstations": workstation_states,
        "materials": material_stock,
        "stats": {
            "completed_count": len([f for f in fridge_states if f.get("current_process") == 7]),
            "in_progress_count": len([f for f in fridge_states if f.get("status") == "in_progress"])
        }
    }
    
    return snapshot
