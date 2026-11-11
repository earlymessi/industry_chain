"""
AGV小车管理系统
负责物料运输和配送的智能体

AGV类型定义（参考工业AGV标准）：
AGV0: 重型AGV - 载重500kg，速度30m/min，负责压缩机、钣金件等重型物料
AGV1: 轻型AGV - 载重100kg，速度40m/min，负责电气元件、螺丝等轻型物料
AGV2: 流体AGV - 载重200kg，速度25m/min，负责发泡料、焊料、氮气瓶等
AGV3: 通用AGV - 载重150kg，速度35m/min，负责包装箱、护角等辅助物料
"""

import numpy as np
import math
from enum import Enum
from collections import deque
from typing import Dict, List, Optional, Tuple
from utils.material import MaterialType


class AGVStatus(Enum):
    """AGV状态枚举"""
    IDLE = 0        # 空闲
    MOVING = 1      # 移动中
    LOADING = 2     # 装载中
    UNLOADING = 3   # 卸载中
    CHARGING = 4    # 充电中
    BROKEN = 5      # 故障
    RETURNING = 6   # 返回中


class AGVType(Enum):
    """AGV类型枚举"""
    HEAVY = "HEAVY"       # 重型AGV
    LIGHT = "LIGHT"       # 轻型AGV  
    FLUID = "FLUID"       # 流体AGV
    UNIVERSAL = "UNIVERSAL"  # 通用AGV


class AGVConfig:
    """AGV详细配置类"""
    
    # AGV详细配置（参考工业AGV标准）
    CONFIGS = {
        0: {  # AGV0 - 重型AGV
            "type": AGVType.HEAVY,
            "name": "重型AGV0",
            "max_capacity": 500,       # 载重 kg
            "max_speed": 30,           # 行驶速度 m/min
            "battery_threshold": 20,   # 充电阈值 %
            "battery_consumption": 0.2,  # 移动耗电：每米消耗0.2%电量
            "charging_rate": 15,       # 充电速度 %/min
            "materials": [             # 负责物料类型
                MaterialType.STEEL_PLATE,
                MaterialType.BENDING_MOLD,
                MaterialType.COMPRESSOR,
                MaterialType.COPPER_TUBE_SMALL,
                MaterialType.COPPER_TUBE_LARGE,
                MaterialType.DOOR_BODY
            ],
            "initial_position": [0, 0],     # 中央仓库
            "charging_station": [0, 0],
            "load_time": 3.0,          # 装载时间 min
            "unload_time": 2.0,        # 卸载时间 min
            "description": "负责重型物料配送，如钣金件、压缩机、门体等"
        },
        1: {  # AGV1 - 轻型AGV
            "type": AGVType.LIGHT,
            "name": "轻型AGV1",
            "max_capacity": 100,
            "max_speed": 40,
            "battery_threshold": 20,
            "battery_consumption": 0.15,  # 移动耗电：每米消耗0.15%电量（较轻，移动更快）
            "charging_rate": 20,
            "materials": [
                MaterialType.RIVET,
                MaterialType.CONTROL_BOARD,
                MaterialType.SENSOR,
                MaterialType.WIRE_HARNESS,
                MaterialType.SWITCH,
                MaterialType.HINGE,
                MaterialType.SCREW
            ],
            "initial_position": [50, 25],
            "charging_station": [50, 25],
            "load_time": 1.5,
            "unload_time": 1.0,
            "description": "负责轻型精密物料配送，如电气元件、螺丝等"
        },
        2: {  # AGV2 - 流体AGV
            "type": AGVType.FLUID,
            "name": "流体AGV2",
            "max_capacity": 200,
            "max_speed": 25,
            "battery_threshold": 20,
            "battery_consumption": 0.25,  # 移动耗电：每米消耗0.25%电量（载重较大，速度较慢）
            "charging_rate": 12,
            "materials": [
                MaterialType.ABS_PARTICLE,
                MaterialType.FOAM_MATERIAL,
                MaterialType.SEALANT,
                MaterialType.SOLDER,
                MaterialType.NITROGEN_BOTTLE
            ],
            "initial_position": [100, 0],
            "charging_station": [100, 0],
            "load_time": 4.0,
            "unload_time": 3.0,
            "description": "负责流体和特殊物料配送，如发泡料、焊料、氮气等"
        },
        3: {  # AGV3 - 通用AGV
            "type": AGVType.UNIVERSAL,
            "name": "通用AGV3",
            "max_capacity": 150,
            "max_speed": 35,
            "battery_threshold": 20,
            "battery_consumption": 0.18,  # 移动耗电：每米消耗0.18%电量
            "charging_rate": 18,
            "materials": [
                MaterialType.VACUUM_MOLD,
                MaterialType.HEATER,
                MaterialType.FOAM_MOLD,
                MaterialType.VIBRATION_PAD,
                MaterialType.WELDING_GUN,
                MaterialType.SEAL_STRIP,
                MaterialType.TEST_EQUIPMENT,
                MaterialType.PACKING_BOX,
                MaterialType.FOAM_CORNER,
                MaterialType.CERTIFICATE
            ],
            "initial_position": [150, 50],
            "charging_station": [150, 50],
            "load_time": 2.0,
            "unload_time": 1.5,
            "description": "负责通用辅助物料配送，如模具、包装材料等"
        }
    }
    
    @classmethod
    def get_config(cls, agv_id: int) -> Dict:
        """获取指定AGV的配置"""
        return cls.CONFIGS.get(agv_id)
    
    @classmethod
    def get_all_agv_ids(cls) -> List[int]:
        """获取所有AGV的ID列表"""
        return list(cls.CONFIGS.keys())
    
    @classmethod
    def get_agvs_for_material(cls, material_type: MaterialType) -> List[int]:
        """获取可以配送指定物料的AGV列表"""
        agv_ids = []
        for agv_id, config in cls.CONFIGS.items():
            if material_type in config["materials"]:
                agv_ids.append(agv_id)
        return agv_ids


class AGVTask:
    """AGV任务类"""
    
    TASK_TYPES = ['pickup', 'delivery', 'return']
    
    def __init__(self, task_id: int, task_type: str, source_storage, target_site, 
                 material_type: MaterialType, quantity: int, priority: int = 2):
        self.task_id = task_id
        self.task_type = task_type  # 'pickup', 'delivery', 'return'
        self.source_storage = source_storage  # 起始存储点
        self.target_site = target_site  # 目标站点
        self.material_type = material_type  # 物料类型
        self.quantity = quantity  # 运输数量
        self.priority = priority  # 优先级: 1=高, 2=中, 3=低
        self.status = 'pending'  # pending, in_progress, completed, failed
        self.assigned_agv = None
        self.start_time = None
        self.end_time = None
        self.path = []  # 路径规划结果
        self.estimated_duration = None  # 预计耗时
    
    def assign_to_agv(self, agv_id: int):
        """分配给AGV"""
        self.assigned_agv = agv_id
        self.status = 'in_progress'
        self.start_time = 0  # 会被环境设置
    
    def complete(self):
        """完成任务"""
        self.status = 'completed'
        self.end_time = 0  # 会被环境设置
    
    def fail(self):
        """任务失败"""
        self.status = 'failed'
    
    def __lt__(self, other):
        """用于优先级队列排序（优先级高的在前）"""
        if not isinstance(other, AGVTask):
            return NotImplemented
        return self.priority < other.priority


class AGV:
    """AGV小车类"""
    
    def __init__(self, agv_id: int, config: Dict = None):
        self.agv_id = agv_id
        self.config = config or AGVConfig.get_config(agv_id)
        
        # 位置信息
        initial_pos = self.config.get("initial_position", [0, 0])
        self.position = np.array(initial_pos, dtype=float)  # 当前位置 [x, y]
        self.target_position = None  # 目标位置
        
        # 状态信息
        self.status = AGVStatus.IDLE
        self.max_capacity = self.config.get("max_capacity", 100)
        self.current_load = 0  # 当前载重
        self.max_speed = self.config.get("max_speed", 30)
        self.current_speed = 0  # 当前速度
        
        # 电池信息
        self.battery_level = 100.0
        self.battery_threshold = self.config.get("battery_threshold", 20)
        self.battery_consumption = self.config.get("battery_consumption", 0.05)
        self.charging_rate = self.config.get("charging_rate", 15)
        
        # 时间和距离
        self.load_time = self.config.get("load_time", 2.0)
        self.unload_time = self.config.get("unload_time", 1.5)
        self.total_distance = 0.0
        
        # 任务相关
        self.current_task = None
        self.task_queue = deque()  # 任务队列
        self.current_path = []  # 当前路径
        self.path_index = 0  # 路径索引
        
        # 统计信息
        self.total_tasks = 0
        self.successful_tasks = 0
        self.failed_tasks = 0
        
        # 货物信息
        self.cargo = {}  # {MaterialType: quantity}
        self.current_material_type = None  # 当前运输的物料类型
    
    def assign_task(self, task: AGVTask) -> bool:
        """分配任务"""
        if self.status == AGVStatus.IDLE:
            # 检查是否能够承载该物料
            if task.material_type not in self.config["materials"]:
                return False
            
            # 检查载重
            if task.quantity > self.max_capacity:
                return False
            
            self.current_task = task
            task.assign_to_agv(self.agv_id)
            self.status = AGVStatus.MOVING
            self.current_material_type = task.material_type
            
            # 计算路径到起始点
            if task.task_type == 'pickup':
                self.target_position = np.array(task.source_storage.position, dtype=float)
            elif task.task_type == 'delivery':
                self.target_position = np.array(task.target_site.absolute_position, dtype=float)
            elif task.task_type == 'return':
                charging_station = self.config.get("charging_station", self.config.get("initial_position"))
                self.target_position = np.array(charging_station, dtype=float)
            
            return True
        else:
            # 添加到队列
            self.task_queue.append(task)
            return False
    
    def move(self, time_step: float = 1.0):
        """移动一步"""
        if self.target_position is None or self.status != AGVStatus.MOVING:
            return
        
        # 计算方向向量
        direction = self.target_position - self.position
        distance = np.linalg.norm(direction)
        
        if distance < 0.5:  # 到达目标
            self.position = self.target_position.copy()
            self.arrive_at_destination()
            return
        
        # 计算移动距离
        move_distance = min(self.max_speed * time_step / 60.0, distance)  # 转换为分钟
        if distance > 0:
            direction = direction / distance
            self.position += direction * move_distance
            self.total_distance += move_distance
            # 耗电：每移动1米消耗 battery_consumption% 电量
            # battery_consumption 典型值：0.1-0.5，表示每米消耗0.1%-0.5%
            # 例如：battery_consumption=0.2，移动100米消耗20%电量
            battery_consumed = move_distance * self.battery_consumption
            self.battery_level = max(0, min(100, self.battery_level - battery_consumed))  # 限制范围[0,100]


    
    def arrive_at_destination(self):
        """到达目的地"""
        if self.current_task.task_type == 'pickup':
            self.status = AGVStatus.LOADING
            self.load_material()
        elif self.current_task.task_type == 'delivery':
            self.status = AGVStatus.UNLOADING
            self.unload_material()
        elif self.current_task.task_type == 'return':
            self.status = AGVStatus.CHARGING
    
    def load_material(self):
        """装载物料"""
        if self.current_task:
            material_type = self.current_task.material_type
            quantity = min(self.current_task.quantity,
                         self.max_capacity - self.current_load)
            
            self.cargo[material_type] = self.cargo.get(material_type, 0) + quantity
            self.current_load += quantity
            self.status = AGVStatus.MOVING
            
            # 设置下一个目标
            self.target_position = np.array(self.current_task.target_site.absolute_position, dtype=float)
    
    def unload_material(self):
        """卸载物料"""
        if self.current_task:
            material_type = self.current_task.material_type
            quantity = min(self.cargo.get(material_type, 0),
                         self.current_task.quantity)
            
            if quantity > 0:
                self.cargo[material_type] -= quantity
                self.current_load -= quantity
                self.current_task.complete()
                self.successful_tasks += 1
                self.total_tasks += 1
        
        self.status = AGVStatus.IDLE
        self.current_task = None
        self.target_position = None
        self.current_material_type = None
        
        # 检查队列中是否有任务
        self.check_task_queue()
    
    def check_task_queue(self):
        """检查任务队列"""
        if self.task_queue and self.status == AGVStatus.IDLE:
            next_task = self.task_queue.popleft()
            self.assign_task(next_task)
    
    def get_distance_to_target(self) -> float:
        """获取到目标的距离"""
        if self.target_position is not None:
            return np.linalg.norm(self.target_position - self.position)
        return 0
    
    def needs_charging(self) -> bool:
        """是否需要充电"""
        return self.battery_level < self.battery_threshold
    
    def charge(self, time_step: float = 1.0):
        """充电"""
        if self.status == AGVStatus.CHARGING:
            self.battery_level = min(100, self.battery_level + self.charging_rate * time_step)
            
            # 充电完成
            if self.battery_level >= 100:
                self.status = AGVStatus.IDLE
    
    def return_to_charging_station(self):
        """返回充电站"""
        if not self.needs_charging() and self.status == AGVStatus.IDLE:
            return
        
        charging_station = self.config.get("charging_station", self.config.get("initial_position"))
        self.target_position = np.array(charging_station, dtype=float)
        self.status = AGVStatus.RETURNING
        
        # 创建返回充电站的任务
        return_task = AGVTask(
            task_id=-1,
            task_type='return',
            source_storage=None,
            target_site=None,
            material_type=None,
            quantity=0,
            priority=3
        )
        return_task.assign_to_agv(self.agv_id)
        self.current_task = return_task
    
    def can_transport_material(self, material_type: MaterialType) -> bool:
        """检查是否可以运输指定物料"""
        return material_type in self.config["materials"]
    
    def get_state(self) -> Dict:
        """获取AGV状态"""
        return {
            'agv_id': self.agv_id,
            'name': self.config.get("name", f"AGV{self.agv_id}"),
            'position': self.position.tolist(),
            'status': self.status.value,
            'status_name': self.status.name,
            'current_load': self.current_load,
            'max_capacity': self.max_capacity,
            'battery_level': self.battery_level,
            'cargo': {str(k): v for k, v in self.cargo.items()},
            'has_task': self.current_task is not None,
            'queue_length': len(self.task_queue),
            'total_distance': self.total_distance,
            'successful_tasks': self.successful_tasks
        }
    
    def get_utilization(self) -> float:
        """获取利用率"""
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / max(1, self.total_tasks)


class AGVFleet:
    """AGV车队管理类"""
    
    def __init__(self, num_agvs: int = 4):
        self.agvs = []
        self.task_counter = 0
        self.setup_fleet(num_agvs)
    
    def setup_fleet(self, num_agvs: int):
        """初始化AGV车队"""
        for i in range(min(num_agvs, 4)):  # 最多4台AGV
            config = AGVConfig.get_config(i)
            if config:
                agv = AGV(i, config)
                self.agvs.append(agv)
    
    def get_agv(self, agv_id: int) -> AGV:
        """获取指定AGV"""
        for agv in self.agvs:
            if agv.agv_id == agv_id:
                return agv
        return None
    
    def get_idle_agvs(self) -> List[AGV]:
        """获取所有空闲的AGV"""
        return [agv for agv in self.agvs if agv.status == AGVStatus.IDLE]
    
    def get_available_agvs_for_material(self, material_type: MaterialType) -> List[AGV]:
        """获取可以运输指定物料的空闲AGV"""
        available = []
        for agv in self.agvs:
            if agv.status == AGVStatus.IDLE and agv.can_transport_material(material_type):
                available.append(agv)
        return available
    
    def assign_task_to_best_agv(self, task: AGVTask) -> bool:
        """将任务分配给最合适的AGV"""
        best_agv = None
        min_cost = float('inf')
        
        for agv in self.agvs:
            if agv.status == AGVStatus.IDLE and not agv.needs_charging():
                # 检查是否可以运输该物料
                if not agv.can_transport_material(task.material_type):
                    continue
                
                # 计算分配代价（距离 + 队列长度）
                distance = 0
                if task.task_type == 'pickup':
                    distance = np.linalg.norm(
                        np.array(task.source_storage.position) - agv.position
                    )
                elif task.task_type == 'delivery':
                    distance = np.linalg.norm(
                        np.array(task.target_site.absolute_position) - agv.position
                    )
                
                # 考虑任务优先级
                priority_penalty = (3 - task.priority) * 20
                cost = distance + len(agv.task_queue) * 10 + priority_penalty
                
                if cost < min_cost:
                    min_cost = cost
                    best_agv = agv
        
        if best_agv:
            best_agv.assign_task(task)
            return True
        return False
    
    def assign_task_with_priority(self, task: AGVTask) -> bool:
        """按优先级分配任务（高优先级任务优先分配）"""
        # 优先分配给可以运输该物料且空闲的AGV
        available_agvs = self.get_available_agvs_for_material(task.material_type)
        
        if not available_agvs:
            return False
        
        # 选择距离最近的AGV
        best_agv = min(available_agvs, key=lambda agv: np.linalg.norm(
            agv.position - np.array(task.source_storage.position)
        ))
        
        return best_agv.assign_task(task)
    
    def create_transport_task(self, source_storage, target_site, material_type: MaterialType, 
                               quantity: int, priority: int = 2) -> AGVTask:
        """创建运输任务"""
        task_id = self.task_counter
        self.task_counter += 1
        
        task = AGVTask(
            task_id=task_id,
            task_type='pickup',
            source_storage=source_storage,
            target_site=target_site,
            material_type=material_type,
            quantity=quantity,
            priority=priority
        )
        
        return task
    
    def create_delivery_task(self, source_storage, target_buffer, material_type: MaterialType, 
                              quantity: int, priority: int = 2) -> AGVTask:
        """创建配送任务（从仓库到缓存区）"""
        task_id = self.task_counter
        self.task_counter += 1
        
        task = AGVTask(
            task_id=task_id,
            task_type='delivery',
            source_storage=source_storage,
            target_site=target_buffer,
            material_type=material_type,
            quantity=quantity,
            priority=priority
        )
        
        return task
    
    def update_all_agvs(self, time_step: float = 1.0):
        """更新所有AGV状态"""
        for agv in self.agvs:
            if agv.status == AGVStatus.MOVING:
                agv.move(time_step)
            elif agv.status == AGVStatus.CHARGING:
                agv.charge(time_step)
            elif agv.needs_charging() and agv.status == AGVStatus.IDLE:
                # 自动返回充电站
                agv.return_to_charging_station()
            else:
                agv.check_task_queue()
    
    def get_fleet_status(self) -> Dict:
        """获取车队状态"""
        idle_count = sum(1 for agv in self.agvs if agv.status == AGVStatus.IDLE)
        busy_count = sum(1 for agv in self.agvs if agv.status != AGVStatus.IDLE)
        charging_count = sum(1 for agv in self.agvs if agv.status == AGVStatus.CHARGING)
        returning_count = sum(1 for agv in self.agvs if agv.status == AGVStatus.RETURNING)
        
        total_tasks = sum(agv.total_tasks for agv in self.agvs)
        successful_tasks = sum(agv.successful_tasks for agv in self.agvs)
        total_distance = sum(agv.total_distance for agv in self.agvs)
        avg_battery = np.mean([agv.battery_level for agv in self.agvs]) if self.agvs else 0
        
        return {
            'total_agvs': len(self.agvs),
            'idle_agvs': idle_count,
            'busy_agvs': busy_count,
            'charging_agvs': charging_count,
            'returning_agvs': returning_count,
            'avg_battery': avg_battery,
            'total_completed_tasks': total_tasks,
            'successful_tasks': successful_tasks,
            'total_distance': total_distance,
            'utilization_rate': successful_tasks / max(1, total_tasks)
        }
    
    def get_agv_states(self) -> List[Dict]:
        """获取所有AGV状态"""
        return [agv.get_state() for agv in self.agvs]
    
    def get_pending_tasks_count(self) -> int:
        """获取待处理任务总数"""
        return sum(len(agv.task_queue) for agv in self.agvs)
    
    def check_all_batteries(self) -> List[AGV]:
        """检查需要充电的AGV"""
        return [agv for agv in self.agvs if agv.needs_charging()]