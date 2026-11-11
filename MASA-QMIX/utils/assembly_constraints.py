"""
产线资源约束管理系统
实现冰箱组装产线的各类资源约束：
1. 工序独占性约束
2. 物料前置约束
3. AGV资源约束
4. 工时弹性约束
"""

from typing import Dict, List, Optional, Tuple
from enum import Enum
from utils.refrigerator_process import RefrigeratorProcess, ProcessStatus
from utils.assembly_line import AssemblyLineLayout, ProductionLine


class ConstraintType(Enum):
    """约束类型"""
    WORKSTATION_OCCUPANCY = "workstation_occupancy"  # 工位占用
    MATERIAL_PREREQUISITE = "material_prerequisite"  # 物料前置
    AGV_CAPACITY = "agv_capacity"                    # AGV容量
    TIME_ELASTICITY = "time_elasticity"              # 工时弹性
    PRECEDENCE = "precedence"                        # 工序顺序


class ConstraintStatus(Enum):
    """约束检查状态"""
    SATISFIED = "satisfied"      # 满足
    VIOLATED = "violated"        # 违反
    PENDING = "pending"          # 待检查
    NOT_APPLICABLE = "n/a"       # 不适用


class AssemblyConstraints:
    """产线资源约束管理器"""
    
    def __init__(self):
        self.production_line = ProductionLine()
        self.constraint_history = []  # 约束检查历史
        self.active_constraints = {}  # 当前活跃的约束
    
    # ==================== 工序独占性约束 ====================
    
    def check_workstation_constraint(self, workstation_id: int, refrigerator_id: int) -> Tuple[bool, str]:
        """
        检查工位约束
        
        约束1: 同一工序站同一时间仅能处理1个冰箱工单
        
        Returns:
            (是否满足, 状态描述)
        """
        is_available = self.production_line.is_workstation_available(workstation_id)
        
        if is_available:
            return True, "工位可用"
        
        # 检查是否被自己占用
        status = self.production_line.get_workstation_status(workstation_id)
        if status.get("occupied_by") == refrigerator_id:
            return True, "工位已被当前工单占用"
        
        return False, f"工位已被工单 {status.get('occupied_by')} 占用"
    
    def occupy_workstation(self, workstation_id: int, refrigerator_id: int) -> bool:
        """占用工位"""
        return self.production_line.occupy_workstation(workstation_id, refrigerator_id)
    
    def release_workstation(self, workstation_id: int, refrigerator_id: int) -> bool:
        """释放工位"""
        return self.production_line.release_workstation(workstation_id, refrigerator_id)
    
    # ==================== 物料前置约束 ====================
    
    def check_material_constraint(self, process_id: int, workstation_id: int,
                                   buffer_status: Dict = None) -> Tuple[bool, str, List[str]]:
        """
        检查物料前置约束
        
        约束2: 工序启动前，所需物料必须由AGV配送至工序站的物料缓存区
        
        Returns:
            (是否满足, 状态描述, 缺失物料列表)
        """
        process = RefrigeratorProcess.get_process(process_id)
        if not process:
            return False, "工序不存在", []
        
        required_materials = process["materials"]
        missing_materials = []
        
        # 获取缓存区状态
        if buffer_status is None:
            buffer = AssemblyLineLayout.get_buffer(workstation_id)
            if buffer:
                buffer_status = buffer.materials
        
        # 检查每种物料
        for material_name in required_materials:
            available = buffer_status.get(material_name, 0) if buffer_status else 0
            if available <= 0:
                missing_materials.append(material_name)
        
        if not missing_materials:
            return True, "物料充足", []
        
        return False, f"缺少物料: {', '.join(missing_materials)}", missing_materials
    
    def are_materials_delivered(self, workstation_id: int, material_names: List[str]) -> bool:
        """检查指定物料是否已配送"""
        buffer = AssemblyLineLayout.get_buffer(workstation_id)
        if not buffer:
            return False
        
        for material_name in material_names:
            if buffer.get_material_quantity(material_name) <= 0:
                return False
        
        return True
    
    # ==================== 工序顺序约束 ====================
    
    def check_predecessor_constraint(self, process_id: int, 
                                      completed_processes: List[int]) -> Tuple[bool, str]:
        """
        检查前置工序约束
        
        约束: 工序必须在前置工序完成后才能开始
        
        Returns:
            (是否满足, 状态描述)
        """
        can_start = RefrigeratorProcess.can_start_process(process_id, completed_processes)
        
        if can_start:
            return True, "前置工序已完成"
        
        predecessors = RefrigeratorProcess.get_predecessors(process_id)
        missing = [p for p in predecessors if p not in completed_processes]
        
        return False, f"前置工序 {missing} 尚未完成"
    
    def get_available_processes(self, completed_processes: List[int]) -> List[int]:
        """获取当前可执行的工序列表"""
        available = []
        for pid in RefrigeratorProcess.PROCESSES.keys():
            if RefrigeratorProcess.can_start_process(pid, completed_processes):
                available.append(pid)
        return available
    
    # ==================== AGV资源约束 ====================
    
    def check_agv_constraint(self, agv, material_type, quantity: int) -> Tuple[bool, str]:
        """
        检查AGV资源约束
        
        约束3: 每台AGV同一时间仅能配送1类物料
        
        Returns:
            (是否满足, 状态描述)
        """
        # 检查当前是否正在运输物料
        if agv.current_material_type is not None:
            if agv.current_material_type != material_type:
                return False, f"AGV正在运输 {agv.current_material_type}，不能配送 {material_type}"
        
        # 检查载重
        if quantity > agv.max_capacity - agv.current_load:
            return False, f"载重不足: 需要 {quantity}, 剩余 {agv.max_capacity - agv.current_load}"
        
        return True, "AGV可用"
    
    def check_agv_battery(self, agv) -> Tuple[bool, str]:
        """检查AGV电量约束"""
        if agv.needs_charging():
            return False, f"AGV电量不足 ({agv.battery_level}%)，需要充电"
        return True, "电量充足"
    
    # ==================== 工时弹性约束 ====================
    
    def apply_time_elasticity(self, base_time: float, delay_minutes: float) -> float:
        """
        应用工时弹性
        
        约束4: 若物料延迟配送，工序工时增加20%
        
        Args:
            base_time: 基准工时（分钟）
            delay_minutes: 延迟时间（分钟）
            
        Returns:
            实际工时
        """
        if delay_minutes > 0:
            return base_time * 1.2  # 增加20%
        return base_time
    
    def calculate_process_time(self, process_id: int, delay_minutes: float = 0) -> float:
        """计算工序实际耗时"""
        process = RefrigeratorProcess.get_process(process_id)
        if not process:
            return 0
        
        base_time = process["standard_time"]
        return self.apply_time_elasticity(base_time, delay_minutes)
    
    # ==================== 综合约束检查 ====================
    
    def check_all_constraints(self, workstation_id: int, process_id: int,
                               refrigerator_id: int, completed_processes: List[int],
                               agv=None, material_type=None, quantity=1,
                               buffer_status: Dict = None) -> Dict:
        """
        综合检查所有约束
        
        Returns:
            约束检查结果
        """
        result = {
            "workstation": {"satisfied": False, "message": ""},
            "material": {"satisfied": False, "message": "", "missing": []},
            "precedence": {"satisfied": False, "message": ""},
            "agv": {"satisfied": True, "message": ""},
            "all_satisfied": False
        }
        
        # 检查工位约束
        ws_ok, ws_msg = self.check_workstation_constraint(workstation_id, refrigerator_id)
        result["workstation"]["satisfied"] = ws_ok
        result["workstation"]["message"] = ws_msg
        
        # 检查物料约束
        mat_ok, mat_msg, missing = self.check_material_constraint(
            process_id, workstation_id, buffer_status
        )
        result["material"]["satisfied"] = mat_ok
        result["material"]["message"] = mat_msg
        result["material"]["missing"] = missing
        
        # 检查前置约束
        pred_ok, pred_msg = self.check_predecessor_constraint(process_id, completed_processes)
        result["precedence"]["satisfied"] = pred_ok
        result["precedence"]["message"] = pred_msg
        
        # 检查AGV约束（如果提供了AGV）
        if agv and material_type:
            agv_ok, agv_msg = self.check_agv_constraint(agv, material_type, quantity)
            battery_ok, battery_msg = self.check_agv_battery(agv)
            
            result["agv"]["satisfied"] = agv_ok and battery_ok
            result["agv"]["message"] = agv_msg if not agv_ok else battery_msg
        
        # 综合判断
        result["all_satisfied"] = (
            result["workstation"]["satisfied"] and
            result["material"]["satisfied"] and
            result["precedence"]["satisfied"] and
            result["agv"]["satisfied"]
        )
        
        return result
    
    def get_constraint_status_summary(self) -> Dict:
        """获取约束状态摘要"""
        return {
            "workstation_availability": self.production_line.get_all_workstation_status(),
            "active_constraints": len(self.active_constraints),
            "constraint_history_size": len(self.constraint_history)
        }
    
    def log_constraint_check(self, check_result: Dict, timestamp: float):
        """记录约束检查结果"""
        self.constraint_history.append({
            "timestamp": timestamp,
            "result": check_result
        })
        
        # 限制历史记录大小
        if len(self.constraint_history) > 1000:
            self.constraint_history = self.constraint_history[-500:]


class ConstraintViolationError(Exception):
    """约束违反异常"""
    
    def __init__(self, constraint_type: ConstraintType, message: str):
        self.constraint_type = constraint_type
        self.message = message
        super().__init__(f"约束违反 [{constraint_type.value}]: {message}")


# 便捷函数
def check_workstation_available(workstation_id: int, refrigerator_id: int) -> Tuple[bool, str]:
    """检查工位是否可用"""
    constraints = AssemblyConstraints()
    return constraints.check_workstation_constraint(workstation_id, refrigerator_id)

def check_material_available(process_id: int, workstation_id: int) -> Tuple[bool, str, List[str]]:
    """检查物料是否可用"""
    constraints = AssemblyConstraints()
    return constraints.check_material_constraint(process_id, workstation_id)

def calculate_actual_time(process_id: int, delay_minutes: float = 0) -> float:
    """计算工序实际时间"""
    constraints = AssemblyConstraints()
    return constraints.calculate_process_time(process_id, delay_minutes)
