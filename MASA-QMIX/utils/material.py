"""
物料管理系统
负责冰箱组装所需的物料供应管理

物料类型定义（对应冰箱组装的8道工序28种物料）：
工序0: 钣金成型 - 冷轧钢板、折弯模具、铆钉
工序1: 内胆吸塑 - ABS粒子、吸塑模具、加热管
工序2: 发泡填充 - 聚氨酯发泡料、发泡模具、密封胶
工序3: 压缩机安装 - 压缩机、铜管、固定螺栓、减震垫
工序4: 管路焊接 - 铜管、焊料、氮气瓶、焊枪
工序5: 电气元件装配 - 主控板、传感器、线束、开关
工序6: 总装合箱 - 门体、铰链、密封条、螺丝
工序7: 检测打包 - 检测仪器、包装箱、泡沫护角、合格证
"""

import numpy as np
from enum import Enum
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


class MaterialType(Enum):
    """物料类型枚举，对应冰箱组装的8道工序28种物料"""
    # 工序0: 钣金成型
    STEEL_PLATE = 0        # 冷轧钢板
    BENDING_MOLD = 1       # 折弯模具
    RIVET = 2              # 铆钉
    
    # 工序1: 内胆吸塑
    ABS_PARTICLE = 3       # ABS粒子
    VACUUM_MOLD = 4        # 吸塑模具
    HEATER = 5             # 加热管
    
    # 工序2: 发泡填充
    FOAM_MATERIAL = 6      # 聚氨酯发泡料
    FOAM_MOLD = 7          # 发泡模具
    SEALANT = 8            # 密封胶
    
    # 工序3: 压缩机安装
    COMPRESSOR = 9         # 压缩机
    COPPER_TUBE_SMALL = 10 # 铜管(小)
    BOLT = 11              # 固定螺栓
    VIBRATION_PAD = 12     # 减震垫
    
    # 工序4: 管路焊接
    COPPER_TUBE_LARGE = 13 # 铜管(大)
    SOLDER = 14            # 焊料
    NITROGEN_BOTTLE = 15   # 氮气瓶
    WELDING_GUN = 16       # 焊枪
    
    # 工序5: 电气元件装配
    CONTROL_BOARD = 17     # 主控板
    SENSOR = 18            # 传感器
    WIRE_HARNESS = 19      # 线束
    SWITCH = 20            # 开关
    
    # 工序6: 总装合箱
    DOOR_BODY = 21         # 门体
    HINGE = 22             # 铰链
    SEAL_STRIP = 23        # 密封条
    SCREW = 24             # 螺丝
    
    # 工序7: 检测打包
    TEST_EQUIPMENT = 25    # 检测仪器
    PACKING_BOX = 26       # 包装箱
    FOAM_CORNER = 27       # 泡沫护角
    CERTIFICATE = 28       # 合格证
    
    @classmethod
    def get_name(cls, value) -> str:
        """获取物料名称"""
        names = {
            0: "冷轧钢板", 1: "折弯模具", 2: "铆钉",
            3: "ABS粒子", 4: "吸塑模具", 5: "加热管",
            6: "聚氨酯发泡料", 7: "发泡模具", 8: "密封胶",
            9: "压缩机", 10: "铜管(小)", 11: "固定螺栓", 12: "减震垫",
            13: "铜管(大)", 14: "焊料", 15: "氮气瓶", 16: "焊枪",
            17: "主控板", 18: "传感器", 19: "线束", 20: "开关",
            21: "门体", 22: "铰链", 23: "密封条", 24: "螺丝",
            25: "检测仪器", 26: "包装箱", 27: "泡沫护角", 28: "合格证"
        }
        return names.get(value, "未知物料")
    
    @classmethod
    def get_by_name(cls, name: str) -> 'MaterialType':
        """通过名称获取枚举值"""
        name_map = {
            "冷轧钢板": cls.STEEL_PLATE, "折弯模具": cls.BENDING_MOLD, "铆钉": cls.RIVET,
            "ABS粒子": cls.ABS_PARTICLE, "吸塑模具": cls.VACUUM_MOLD, "加热管": cls.HEATER,
            "聚氨酯发泡料": cls.FOAM_MATERIAL, "发泡模具": cls.FOAM_MOLD, "密封胶": cls.SEALANT,
            "压缩机": cls.COMPRESSOR, "铜管": cls.COPPER_TUBE_SMALL, "铜管(小)": cls.COPPER_TUBE_SMALL,
            "固定螺栓": cls.BOLT, "减震垫": cls.VIBRATION_PAD,
            "铜管(大)": cls.COPPER_TUBE_LARGE, "焊料": cls.SOLDER, "氮气瓶": cls.NITROGEN_BOTTLE, "焊枪": cls.WELDING_GUN,
            "主控板": cls.CONTROL_BOARD, "传感器": cls.SENSOR, "线束": cls.WIRE_HARNESS, "开关": cls.SWITCH,
            "门体": cls.DOOR_BODY, "铰链": cls.HINGE, "密封条": cls.SEAL_STRIP, "螺丝": cls.SCREW,
            "检测仪器": cls.TEST_EQUIPMENT, "包装箱": cls.PACKING_BOX, "泡沫护角": cls.FOAM_CORNER, "合格证": cls.CERTIFICATE
        }
        return name_map.get(name)
    
    @classmethod
    def get_by_process(cls, process_id: int) -> List['MaterialType']:
        """获取指定工序对应的所有物料类型"""
        process_materials = {
            0: [cls.STEEL_PLATE, cls.BENDING_MOLD, cls.RIVET],
            1: [cls.ABS_PARTICLE, cls.VACUUM_MOLD, cls.HEATER],
            2: [cls.FOAM_MATERIAL, cls.FOAM_MOLD, cls.SEALANT],
            3: [cls.COMPRESSOR, cls.COPPER_TUBE_SMALL, cls.BOLT, cls.VIBRATION_PAD],
            4: [cls.COPPER_TUBE_LARGE, cls.SOLDER, cls.NITROGEN_BOTTLE, cls.WELDING_GUN],
            5: [cls.CONTROL_BOARD, cls.SENSOR, cls.WIRE_HARNESS, cls.SWITCH],
            6: [cls.DOOR_BODY, cls.HINGE, cls.SEAL_STRIP, cls.SCREW],
            7: [cls.TEST_EQUIPMENT, cls.PACKING_BOX, cls.FOAM_CORNER, cls.CERTIFICATE]
        }
        return process_materials.get(process_id, [])


class MaterialPriority(Enum):
    """物料配送优先级"""
    HIGH = 1     # 高优先级: 压缩机、发泡料（缺料导致工序完全停滞）
    MEDIUM = 2   # 中优先级: 电气元件、钣金件
    LOW = 3      # 低优先级: 包装箱、护角等辅助物料
    
    @classmethod
    def get_by_material(cls, material_type: MaterialType) -> 'MaterialPriority':
        """根据物料类型获取优先级"""
        high_priority = [
            MaterialType.COMPRESSOR, MaterialType.FOAM_MATERIAL,
            MaterialType.FOAM_MOLD, MaterialType.SEALANT
        ]
        medium_priority = [
            MaterialType.STEEL_PLATE, MaterialType.BENDING_MOLD,
            MaterialType.CONTROL_BOARD, MaterialType.SENSOR,
            MaterialType.COPPER_TUBE_SMALL, MaterialType.COPPER_TUBE_LARGE
        ]
        
        if material_type in high_priority:
            return cls.HIGH
        elif material_type in medium_priority:
            return cls.MEDIUM
        else:
            return cls.LOW


class MaterialStatus(Enum):
    """物料供应状态"""
    SUFFICIENT = 0    # 充足
    LOW = 1          # 不足
    CRITICAL = 2     # 严重不足
    OUT_OF_STOCK = 3 # 缺货


class MaterialStorage:
    """物料存储点类（仓库或工位缓存区）"""
    
    def __init__(self, storage_id: int, position: List[float], capacity: int = 100, 
                 is_warehouse: bool = False, name: str = "存储点"):
        self.storage_id = storage_id
        self.position = np.array(position)  # [x, y] 坐标
        self.capacity = capacity  # 存储容量
        self.inventory = defaultdict(int)  # 各类型物料库存 {MaterialType: quantity}
        self.reserved = defaultdict(int)   # 预留物料 {MaterialType: quantity}
        self.is_warehouse = is_warehouse  # 是否为中央仓库
        self.name = name
        
    def add_material(self, material_type: MaterialType, quantity: int) -> bool:
        """添加物料"""
        if self.inventory[material_type] + quantity <= self.capacity:
            self.inventory[material_type] += quantity
            return True
        return False
    
    def remove_material(self, material_type: MaterialType, quantity: int) -> bool:
        """移除物料"""
        available = self.inventory[material_type] - self.reserved[material_type]
        if available >= quantity:
            self.inventory[material_type] -= quantity
            return True
        return False
    
    def reserve_material(self, material_type: MaterialType, quantity: int) -> bool:
        """预留物料"""
        available = self.inventory[material_type] - self.reserved[material_type]
        if available >= quantity:
            self.reserved[material_type] += quantity
            return True
        return False
    
    def release_reservation(self, material_type: MaterialType, quantity: int) -> bool:
        """释放预留"""
        if self.reserved[material_type] >= quantity:
            self.reserved[material_type] -= quantity
            return True
        return False
    
    def get_available_quantity(self, material_type: MaterialType) -> int:
        """获取可用数量"""
        return self.inventory[material_type] - self.reserved[material_type]
    
    def get_status(self, material_type: MaterialType) -> MaterialStatus:
        """获取物料状态"""
        available = self.get_available_quantity(material_type)
        if available == 0:
            return MaterialStatus.OUT_OF_STOCK
        elif available < 5:  # 阈值可配置
            return MaterialStatus.CRITICAL
        elif available < 15:
            return MaterialStatus.LOW
        else:
            return MaterialStatus.SUFFICIENT
    
    def get_all_status(self) -> Dict[MaterialType, MaterialStatus]:
        """获取所有物料状态"""
        return {mt: self.get_status(mt) for mt in MaterialType}


class MaterialDemand:
    """物料需求类"""
    
    def __init__(self, site_id: int, material_type: MaterialType, quantity: int, 
                 urgency: float = 1.0, refrigerator_id: int = None, process_id: int = None):
        self.site_id = site_id  # 需求站点ID（工位ID）
        self.material_type = material_type  # 物料类型
        self.quantity = quantity  # 需求数量
        self.urgency = urgency  # 紧急程度 0-1
        self.timestamp = 0  # 需求时间戳
        self.fulfilled = False  # 是否已满足
        self.refrigerator_id = refrigerator_id  # 关联的冰箱工单ID
        self.process_id = process_id  # 关联的工序ID
        self.priority = MaterialPriority.get_by_material(material_type)
    
    def mark_fulfilled(self):
        """标记需求已满足"""
        self.fulfilled = True
    
    def is_expired(self, current_time: int, timeout: int = 50) -> bool:
        """检查需求是否过期"""
        return (current_time - self.timestamp) > timeout and not self.fulfilled


class MaterialManager:
    """物料管理器"""
    
    def __init__(self, warehouse_position: List[float] = [0, 0]):
        self.storages = []  # 存储点列表
        self.demands = []   # 当前需求列表
        self.demand_history = []  # 历史需求记录
        self.warehouse_position = warehouse_position
        self.setup_default_storages()
    
    def setup_default_storages(self):
        """设置默认存储点配置"""
        # 中央仓库
        central_storage = MaterialStorage(
            storage_id=0, 
            position=self.warehouse_position, 
            capacity=1000, 
            is_warehouse=True,
            name="中央仓库"
        )
        # 初始化各类型物料库存（仓库库存充足）
        for material_type in MaterialType:
            central_storage.add_material(material_type, 100)
        self.storages.append(central_storage)
        
        # 分布式缓存区（靠近组装工位）
        from utils.assembly_line import AssemblyLineLayout
        layout = AssemblyLineLayout()
        
        for ws_id, workstation in layout.WORKSTATIONS.items():
            buffer_pos = workstation["buffer_position"]
            buffer_cap = workstation["buffer_capacity"]
            
            buffer = MaterialStorage(
                storage_id=ws_id + 1,
                position=buffer_pos,
                capacity=buffer_cap,
                is_warehouse=False,
                name=f"{workstation['name']}缓存区"
            )
            
            # 缓存区初始库存较少（模拟JIT配送）
            for material_type in MaterialType:
                buffer.add_material(material_type, 5)  # 初始5个单位
            self.storages.append(buffer)
    
    def add_demand(self, demand: MaterialDemand):
        """添加物料需求"""
        demand.timestamp = len(self.demands)  # 简单的时间戳
        self.demands.append(demand)
        self.demand_history.append(demand)
    
    def check_demand_fulfillment(self, site_id: int, material_type: MaterialType, 
                                  quantity: int) -> Tuple[bool, MaterialStorage]:
        """检查是否能满足需求"""
        storage = self.find_nearest_storage(site_id)
        if storage and storage.get_available_quantity(material_type) >= quantity:
            return True, storage
        return False, None
    
    def fulfill_demand(self, demand: MaterialDemand, storage: MaterialStorage) -> bool:
        """满足物料需求"""
        if storage.reserve_material(demand.material_type, demand.quantity):
            demand.mark_fulfilled()
            return True
        return False
    
    def find_nearest_storage(self, site_id: int) -> MaterialStorage:
        """为站点找到最近的存储点"""
        from utils.assembly_line import AssemblyLineLayout
        layout = AssemblyLineLayout()
        
        # 优先查找对应的缓存区
        if site_id in layout.WORKSTATIONS:
            buffer_idx = site_id + 1  # 缓存区存储ID偏移
            for storage in self.storages:
                if storage.storage_id == buffer_idx:
                    return storage
        
        # 否则返回中央仓库
        return self.storages[0] if self.storages else None
    
    def find_storage_for_material(self, material_type: MaterialType) -> MaterialStorage:
        """查找有指定物料的存储点"""
        for storage in self.storages:
            if storage.get_available_quantity(material_type) > 0:
                return storage
        return None
    
    def get_pending_demands(self) -> List[MaterialDemand]:
        """获取待处理的物料需求"""
        return [d for d in self.demands if not d.fulfilled]
    
    def get_pending_demands_by_priority(self, priority: MaterialPriority) -> List[MaterialDemand]:
        """按优先级获取待处理需求"""
        return [d for d in self.get_pending_demands() if d.priority == priority]
    
    def get_material_status_overview(self) -> Dict[MaterialType, Dict]:
        """获取物料状态总览"""
        status_overview = {}
        for material_type in MaterialType:
            total_available = sum(s.get_available_quantity(material_type) for s in self.storages)
            status_overview[material_type] = {
                'total_available': total_available,
                'status': MaterialStatus.SUFFICIENT if total_available > 50 else
                         MaterialStatus.LOW if total_available > 10 else
                         MaterialStatus.CRITICAL if total_available > 0 else
                         MaterialStatus.OUT_OF_STOCK
            }
        return status_overview
    
    def update_inventory(self, storage_id: int, material_type: MaterialType, 
                         quantity_change: int) -> bool:
        """更新库存"""
        for storage in self.storages:
            if storage.storage_id == storage_id:
                if quantity_change > 0:
                    return storage.add_material(material_type, quantity_change)
                else:
                    return storage.remove_material(material_type, abs(quantity_change))
        return False
    
    def consume_material(self, site_id: int, material_type: MaterialType, 
                         quantity: int = 1) -> bool:
        """在指定站点消耗物料"""
        storage = self.find_nearest_storage(site_id)
        if storage:
            return storage.remove_material(material_type, quantity)
        return False
    
    def get_buffer_status(self, site_id: int) -> Dict[MaterialType, int]:
        """获取指定站点的缓存区物料状态"""
        storage = self.find_nearest_storage(site_id)
        if storage:
            return {mt: storage.get_available_quantity(mt) for mt in MaterialType}
        return {}


# 便捷函数
def get_material_name(material_type: MaterialType) -> str:
    """获取物料名称"""
    return MaterialType.get_name(material_type.value)

def get_material_priority(material_type: MaterialType) -> MaterialPriority:
    """获取物料优先级"""
    return MaterialPriority.get_by_material(material_type)

def get_process_materials(process_id: int) -> List[MaterialType]:
    """获取指定工序的物料列表"""
    return MaterialType.get_by_process(process_id)
