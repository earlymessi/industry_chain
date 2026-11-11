"""
冰箱组装产线布局
定义8个工位及对应的物料缓存区位置
产线遵循"串行为主、部分并行"的真实产线逻辑

工位布局：
工位1（钣金区）    -> 坐标 [50, 0]
工位2（吸塑区）    -> 坐标 [100, 0]
工位3（发泡区）    -> 坐标 [150, 0]
工位4（压缩机区）  -> 坐标 [200, 0] 和 [200, 30]
工位5（电气区）    -> 坐标 [250, 0]
工位6（总装区）    -> 坐标 [300, 0]
工位7（检测区）    -> 坐标 [350, 0]

中央仓库坐标: [0, 0]
"""

import numpy as np
from typing import Dict, List, Optional
from enum import Enum


class WorkstationType(Enum):
    """工位类型"""
    METAL_FORMING = "metal_forming"      # 钣金成型
    VACUUM_FORMING = "vacuum_forming"    # 内胆吸塑
    FOAM_FILLING = "foam_filling"        # 发泡填充
    COMPRESSOR = "compressor"            # 压缩机安装
    PIPE_WELDING = "pipe_welding"        # 管路焊接
    ELECTRICAL = "electrical"            # 电气元件装配
    FINAL_ASSEMBLY = "final_assembly"    # 总装合箱
    TEST_PACKING = "test_packing"        # 检测打包


class AssemblyLineLayout:
    """冰箱组装产线布局类"""
    
    # 中央仓库位置
    CENTRAL_WAREHOUSE = {
        "position": [0, 0],
        "capacity": 1000,
        "name": "中央仓库",
        "description": "存放所有类型物料的主仓库"
    }
    
    # 8个工位及物料缓存区定义
    WORKSTATIONS = {
        0: {  # 工位1 - 钣金区
            "name": "钣金成型工位",
            "name_en": "Metal Forming Station",
            "type": WorkstationType.METAL_FORMING,
            "position": [50, 0],           # 实际工位位置
            "buffer_position": [45, 5],     # 物料缓存区位置
            "buffer_capacity": 50,          # 缓存区容量
            "process_id": 0,
            "coordinates": (50, 0),
            "adjacent_stations": [1],       # 邻近工位
            "parallel_with": None,          # 可并行的工位
            "description": "使用冷轧钢板经过折弯、冲压等工艺成型冰箱外壳"
        },
        1: {  # 工位2 - 吸塑区
            "name": "内胆吸塑工位",
            "name_en": "Vacuum Forming Station",
            "type": WorkstationType.VACUUM_FORMING,
            "position": [100, 0],
            "buffer_position": [95, 5],
            "buffer_capacity": 40,
            "process_id": 1,
            "coordinates": (100, 0),
            "adjacent_stations": [0, 2],
            "parallel_with": None,
            "description": "使用ABS材料通过吸塑工艺成型冰箱内胆"
        },
        2: {  # 工位3 - 发泡区
            "name": "发泡填充工位",
            "name_en": "Foam Filling Station",
            "type": WorkstationType.FOAM_FILLING,
            "position": [150, 0],
            "buffer_position": [145, 5],
            "buffer_capacity": 60,
            "process_id": 2,
            "coordinates": (150, 0),
            "adjacent_stations": [1, 3],
            "parallel_with": None,
            "description": "在内外壳之间注入聚氨酯发泡料，形成保温层"
        },
        3: {  # 工位4 - 压缩机区（压缩机安装）
            "name": "压缩机安装工位",
            "name_en": "Compressor Installation Station",
            "type": WorkstationType.COMPRESSOR,
            "position": [200, 0],
            "buffer_position": [195, 5],
            "buffer_capacity": 50,
            "process_id": 3,
            "coordinates": (200, 0),
            "adjacent_stations": [2, 4, 5],
            "parallel_with": None,
            "description": "安装压缩机并连接减震系统和基础管路"
        },
        4: {  # 工位4 - 管路焊接区（同工位4，物理位置略有不同）
            "name": "管路焊接工位",
            "name_en": "Pipe Welding Station",
            "type": WorkstationType.PIPE_WELDING,
            "position": [200, 30],
            "buffer_position": [195, 35],
            "buffer_capacity": 40,
            "process_id": 4,
            "coordinates": (200, 30),
            "adjacent_stations": [3, 6],
            "parallel_with": 5,  # 可与电气元件装配并行
            "description": "焊接制冷管路系统，使用氮气保护防止氧化"
        },
        5: {  # 工位5 - 电气区
            "name": "电气元件装配工位",
            "name_en": "Electrical Assembly Station",
            "type": WorkstationType.ELECTRICAL,
            "position": [250, 0],
            "buffer_position": [245, 5],
            "buffer_capacity": 40,
            "process_id": 5,
            "coordinates": (250, 0),
            "adjacent_stations": [3, 6],
            "parallel_with": 4,  # 可与管路焊接并行
            "description": "安装电气控制系统、传感器和线束"
        },
        6: {  # 工位6 - 总装区
            "name": "总装合箱工位",
            "name_en": "Final Assembly Station",
            "type": WorkstationType.FINAL_ASSEMBLY,
            "position": [300, 0],
            "buffer_position": [295, 5],
            "buffer_capacity": 60,
            "process_id": 6,
            "coordinates": (300, 0),
            "adjacent_stations": [4, 5, 7],
            "parallel_with": None,
            "description": "安装门体、密封条，完成冰箱总装"
        },
        7: {  # 工位7 - 检测区
            "name": "检测打包工位",
            "name_en": "Test & Packing Station",
            "type": WorkstationType.TEST_PACKING,
            "position": [350, 0],
            "buffer_position": [345, 5],
            "buffer_capacity": 50,
            "process_id": 7,
            "coordinates": (350, 0),
            "adjacent_stations": [6],
            "parallel_with": None,
            "description": "质量检测、性能测试和包装入库"
        }
    }
    
    # 充电站位置
    CHARGING_STATIONS = {
        0: [0, 0],        # AGV0充电站（中央仓库）
        1: [50, 50],      # AGV1充电站
        2: [100, 50],     # AGV2充电站
        3: [150, 50]      # AGV3充电站
    }
    
    # 障碍物位置（固定障碍）
    OBSTACLES = [
        [25, 15],   # 柱子1
        [75, 15],   # 柱子2
        [125, 15],  # 柱子3
        [175, 15],  # 柱子4
        [225, 15],  # 柱子5
        [275, 15],  # 柱子6
        [325, 15],  # 柱子7
    ]
    
    # 类属性：缓存区实例（延迟初始化）
    _buffers = None
    
    @classmethod
    def get_workstation(cls, workstation_id: int) -> Optional[Dict]:
        """获取指定工位信息"""
        return cls.WORKSTATIONS.get(workstation_id)
    
    @classmethod
    def get_all_workstation_ids(cls) -> List[int]:
        """获取所有工位ID"""
        return list(cls.WORKSTATIONS.keys())
    
    @classmethod
    def get_workstation_position(cls, workstation_id: int) -> np.ndarray:
        """获取工位位置坐标"""
        workstation = cls.get_workstation(workstation_id)
        if workstation:
            return np.array(workstation["position"])
        return np.array([0, 0])
    
    @classmethod
    def get_buffer_position(cls, workstation_id: int) -> np.ndarray:
        """获取物料缓存区位置坐标"""
        workstation = cls.get_workstation(workstation_id)
        if workstation:
            return np.array(workstation["buffer_position"])
        return np.array([0, 0])
    
    @classmethod
    def get_workstation_by_process(cls, process_id: int) -> Optional[Dict]:
        """根据工序ID获取工位信息"""
        for workstation in cls.WORKSTATIONS.values():
            if workstation["process_id"] == process_id:
                return workstation
        return None
    
    @classmethod
    def get_parallel_workstation(cls, workstation_id: int) -> Optional[int]:
        """获取可与指定工位并行的工位ID"""
        workstation = cls.get_workstation(workstation_id)
        if workstation and workstation["parallel_with"]:
            return workstation["parallel_with"]
        return None
    
    @classmethod
    def get_adjacent_workstations(cls, workstation_id: int) -> List[int]:
        """获取邻近的工位列表"""
        workstation = cls.get_workstation(workstation_id)
        return workstation["adjacent_stations"] if workstation else []
    
    @classmethod
    def get_workstation_sequence(cls) -> List[List[int]]:
        """获取推荐的工位执行序列（考虑并行）"""
        return [
            [0],           # 阶段1: 钣金成型
            [1],           # 阶段2: 内胆吸塑
            [2],           # 阶段3: 发泡填充
            [3],           # 阶段4: 压缩机安装
            [4, 5],        # 阶段5: 管路焊接 和 电气元件装配（并行）
            [6],           # 阶段6: 总装合箱
            [7]            # 阶段7: 检测打包
        ]
    
    @classmethod
    def calculate_distance(cls, pos1: List[float], pos2: List[float]) -> float:
        """计算两点间的欧氏距离"""
        return np.linalg.norm(np.array(pos2) - np.array(pos1))
    
    @classmethod
    def get_distance_to_warehouse(cls, position: List[float]) -> float:
        """计算到仓库的距离"""
        return cls.calculate_distance(position, cls.CENTRAL_WAREHOUSE["position"])
    
    @classmethod
    def get_distance_between_workstations(cls, ws1_id: int, ws2_id: int) -> float:
        """计算两个工位之间的距离"""
        pos1 = cls.get_workstation_position(ws1_id)
        pos2 = cls.get_workstation_position(ws2_id)
        return cls.calculate_distance(pos1.tolist(), pos2.tolist())
    
    @classmethod
    def initialize_buffers(cls) -> Dict[int, 'WorkstationBuffer']:
        """初始化所有工位缓存区"""
        if cls._buffers is None:
            cls._buffers = {}
            for ws_id, workstation in cls.WORKSTATIONS.items():
                buffer = WorkstationBuffer(
                    buffer_id=ws_id,
                    position=workstation["buffer_position"],
                    capacity=workstation["buffer_capacity"]
                )
                cls._buffers[ws_id] = buffer
        return cls._buffers
    
    @classmethod
    def get_buffer(cls, workstation_id: int) -> Optional['WorkstationBuffer']:
        """获取指定工位的缓存区"""
        if cls._buffers is None:
            cls.initialize_buffers()
        return cls._buffers.get(workstation_id)
    
    @classmethod
    def get_all_buffers(cls) -> Dict[int, 'WorkstationBuffer']:
        """获取所有缓存区"""
        if cls._buffers is None:
            cls.initialize_buffers()
        return cls._buffers


class WorkstationBuffer:
    """工位物料缓存区类"""
    
    def __init__(self, buffer_id: int, position: List[float], capacity: int = 50):
        self.buffer_id = buffer_id
        self.position = np.array(position)  # [x, y] 坐标
        self.capacity = capacity  # 缓存区总容量
        self.current_load = 0  # 当前载重
        self.materials = {}  # {material_name: quantity}
        self.occupied = False  # 是否被占用（同一时间仅处理1个冰箱工单）
        self.occupied_by = None  # 占用者的ID
    
    def add_material(self, material_name: str, quantity: int) -> bool:
        """添加物料到缓存区"""
        if self.current_load + quantity <= self.capacity:
            self.materials[material_name] = self.materials.get(material_name, 0) + quantity
            self.current_load += quantity
            return True
        return False
    
    def remove_material(self, material_name: str, quantity: int) -> bool:
        """从缓存区移除物料"""
        if self.materials.get(material_name, 0) >= quantity:
            self.materials[material_name] -= quantity
            self.current_load -= quantity
            if self.materials[material_name] == 0:
                del self.materials[material_name]
            return True
        return False
    
    def reserve(self, refrigerator_id: int) -> bool:
        """预占缓存区（用于工序开始前）"""
        if not self.occupied:
            self.occupied = True
            self.occupied_by = refrigerator_id
            return True
        return False
    
    def release(self, refrigerator_id: int) -> bool:
        """释放缓存区"""
        if self.occupied and self.occupied_by == refrigerator_id:
            self.occupied = False
            self.occupied_by = None
            return True
        return False
    
    def is_full(self) -> bool:
        """检查缓存区是否满载"""
        return self.current_load >= self.capacity
    
    def is_available(self) -> bool:
        """检查缓存区是否可用"""
        return not self.occupied and self.current_load < self.capacity
    
    def check_material_availability(self, material_name: str, quantity: int = 1) -> bool:
        """检查物料是否可用"""
        return self.materials.get(material_name, 0) >= quantity
    
    def get_material_quantity(self, material_name: str) -> int:
        """获取指定物料的数量"""
        return self.materials.get(material_name, 0)
    
    def get_status(self) -> Dict:
        """获取缓存区状态"""
        return {
            "buffer_id": self.buffer_id,
            "position": self.position.tolist(),
            "capacity": self.capacity,
            "current_load": self.current_load,
            "utilization": self.current_load / self.capacity if self.capacity > 0 else 0,
            "occupied": self.occupied,
            "occupied_by": self.occupied_by,
            "materials": self.materials.copy()
        }


class ProductionLine:
    """生产线整体管理类"""
    
    def __init__(self):
        self.layout = AssemblyLineLayout
        self.buffers = AssemblyLineLayout.initialize_buffers()
        self.workstation_status = {}  # {workstation_id: status}
        self.refrigerator_positions = {}  # {refrigerator_id: workstation_id}
        self.initialize_status()
    
    def initialize_status(self):
        """初始化工位状态"""
        for ws_id in self.layout.get_all_workstation_ids():
            self.workstation_status[ws_id] = {
                "occupied": False,
                "occupied_by": None,
                "current_refrigerator": None,
                "process_start_time": None
            }
    
    def occupy_workstation(self, workstation_id: int, refrigerator_id: int) -> bool:
        """占用工位"""
        if workstation_id not in self.workstation_status:
            return False
        
        status = self.workstation_status[workstation_id]
        if status["occupied"]:
            return False
        
        status["occupied"] = True
        status["occupied_by"] = refrigerator_id
        self.refrigerator_positions[refrigerator_id] = workstation_id
        
        # 同时占用缓存区
        buffer = self.buffers.get(workstation_id)
        if buffer:
            buffer.reserve(refrigerator_id)
        
        return True
    
    def release_workstation(self, workstation_id: int, refrigerator_id: int) -> bool:
        """释放工位"""
        if workstation_id not in self.workstation_status:
            return False
        
        status = self.workstation_status[workstation_id]
        if status["occupied_by"] != refrigerator_id:
            return False
        
        status["occupied"] = False
        status["occupied_by"] = None
        
        # 释放缓存区
        buffer = self.buffers.get(workstation_id)
        if buffer:
            buffer.release(refrigerator_id)
        
        if refrigerator_id in self.refrigerator_positions:
            del self.refrigerator_positions[refrigerator_id]
        
        return True
    
    def is_workstation_available(self, workstation_id: int) -> bool:
        """检查工位是否可用"""
        if workstation_id not in self.workstation_status:
            return False
        return not self.workstation_status[workstation_id]["occupied"]
    
    def get_workstation_status(self, workstation_id: int) -> Dict:
        """获取工位状态"""
        return self.workstation_status.get(workstation_id, {})
    
    def get_all_workstation_status(self) -> Dict[int, Dict]:
        """获取所有工位状态"""
        return self.workstation_status.copy()
    
    def get_production_flow(self) -> List[Dict]:
        """获取生产流程信息"""
        flow = []
        for ws_id in self.layout.get_all_workstation_ids():
            workstation = self.layout.get_workstation(ws_id)
            status = self.workstation_status.get(ws_id, {})
            buffer = self.buffers.get(ws_id)
            
            flow.append({
                "workstation_id": ws_id,
                "name": workstation["name"],
                "position": workstation["position"],
                "buffer_position": workstation["buffer_position"],
                "process_id": workstation["process_id"],
                "occupied": status.get("occupied", False),
                "occupied_by": status.get("occupied_by"),
                "buffer_status": buffer.get_status() if buffer else None,
                "parallel_with": workstation["parallel_with"]
            })
        
        return flow


# 便捷函数
def get_workstation(workstation_id: int) -> Dict:
    """获取工位信息"""
    return AssemblyLineLayout.get_workstation(workstation_id)

def get_buffer(workstation_id: int) -> WorkstationBuffer:
    """获取缓存区"""
    return AssemblyLineLayout.get_buffer(workstation_id)

def get_all_workstations() -> Dict[int, Dict]:
    """获取所有工位"""
    return AssemblyLineLayout.WORKSTATIONS

def calculate_distance(pos1: List[float], pos2: List[float]) -> float:
    """计算两点间距离"""
    return AssemblyLineLayout.calculate_distance(pos1, pos2)

def get_warehouse_position() -> List[float]:
    """获取仓库位置"""
    return AssemblyLineLayout.CENTRAL_WAREHOUSE["position"]

def get_workstation_position(workstation_id: int) -> List[float]:
    """获取工位位置"""
    pos = AssemblyLineLayout.get_workstation_position(workstation_id)
    return pos.tolist()
