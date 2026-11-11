"""
冰箱组装核心工序定义
参考家电工厂标准流程，定义8大核心工序

工序ID	工序名称	标准工时（分钟）	核心物料 / 零件	工序约束	对应产线工位
0	钣金成型	8	冷轧钢板、折弯模具、铆钉	首工序，无前置约束	工位 1（钣金区）
1	内胆吸塑	6	ABS 粒子、吸塑模具、加热管	需钣金工序完成后启动	工位 2（吸塑区）
2	发泡填充	12	聚氨酯发泡料、发泡模具、密封胶	需内胆 + 钣金工序完成	工位 3（发泡区）
3	压缩机安装	10	压缩机、铜管、固定螺栓、减震垫	需发泡工序完成	工位 4（压缩机区）
4	管路焊接	9	铜管、焊料、氮气（保护气）、焊枪	需压缩机安装完成	工位 4（压缩机区）
5	电气元件装配	7	主控板、传感器、线束、开关	可与管路焊接并行（节省工时）	工位 5（电气区）
6	总装合箱	11	门体、铰链、密封条、螺丝	需电气 + 管路工序完成	工位 6（总装区）
7	检测打包	5	检测仪器、包装箱、泡沫护角、合格证	最终工序	工位 7（检测区）
"""

from enum import Enum
from typing import List, Dict, Optional


class ProcessCategory(Enum):
    """工序类别"""
    METAL_FORMING = "metal_forming"      # 钣金成型
    VACUUM_FORMING = "vacuum_forming"    # 内胆吸塑
    FOAM_FILLING = "foam_filling"        # 发泡填充
    COMPRESSOR_INSTALL = "compressor_install"  # 压缩机安装
    PIPE_WELDING = "pipe_welding"        # 管路焊接
    ELECTRICAL_ASSEMBLY = "electrical_assembly"  # 电气元件装配
    FINAL_ASSEMBLY = "final_assembly"    # 总装合箱
    TEST_PACKING = "test_packing"        # 检测打包


class ProcessStatus(Enum):
    """工序执行状态"""
    PENDING = "pending"      # 等待执行
    IN_PROGRESS = "in_progress"  # 执行中
    COMPLETED = "completed"  # 已完成
    BLOCKED = "blocked"      # 被阻塞（缺料/前置未完成）
    FAILED = "failed"        # 失败


class RefrigeratorProcess:
    """冰箱组装核心工序定义类"""
    
    # 工序详细定义
    PROCESSES = {
        0: {
            "name": "钣金成型",
            "name_en": "Metal Forming",
            "category": ProcessCategory.METAL_FORMING,
            "standard_time": 8,  # 分钟
            "materials": [
                "冷轧钢板", "折弯模具", "铆钉"
            ],
            "predecessors": [],  # 首工序，无前置约束
            "workstation": "工位1（钣金区）",
            "workstation_id": 0,
            "parallel_capable": False,  # 是否可并行
            "critical_path": True,  # 是否在关键路径
            "description": "使用冷轧钢板经过折弯、冲压等工艺成型冰箱外壳"
        },
        1: {
            "name": "内胆吸塑",
            "name_en": "Vacuum Forming",
            "category": ProcessCategory.VACUUM_FORMING,
            "standard_time": 6,
            "materials": [
                "ABS粒子", "吸塑模具", "加热管"
            ],
            "predecessors": [0],  # 需钣金工序完成
            "workstation": "工位2（吸塑区）",
            "workstation_id": 1,
            "parallel_capable": False,
            "critical_path": True,
            "description": "使用ABS材料通过吸塑工艺成型冰箱内胆"
        },
        2: {
            "name": "发泡填充",
            "name_en": "Foam Filling",
            "category": ProcessCategory.FOAM_FILLING,
            "standard_time": 12,
            "materials": [
                "聚氨酯发泡料", "发泡模具", "密封胶"
            ],
            "predecessors": [0, 1],  # 需内胆+钣金完成
            "workstation": "工位3（发泡区）",
            "workstation_id": 2,
            "parallel_capable": False,
            "critical_path": True,
            "description": "在内外壳之间注入聚氨酯发泡料，形成保温层"
        },
        3: {
            "name": "压缩机安装",
            "name_en": "Compressor Installation",
            "category": ProcessCategory.COMPRESSOR_INSTALL,
            "standard_time": 10,
            "materials": [
                "压缩机", "铜管", "固定螺栓", "减震垫"
            ],
            "predecessors": [2],  # 需发泡工序完成
            "workstation": "工位4（压缩机区）",
            "workstation_id": 3,
            "parallel_capable": False,
            "critical_path": True,
            "description": "安装压缩机并连接减震系统和基础管路"
        },
        4: {
            "name": "管路焊接",
            "name_en": "Pipe Welding",
            "category": ProcessCategory.PIPE_WELDING,
            "standard_time": 9,
            "materials": [
                "铜管", "焊料", "氮气瓶", "焊枪"
            ],
            "predecessors": [3],  # 需压缩机安装完成
            "workstation": "工位4（压缩机区）",
            "workstation_id": 4,
            "parallel_capable": True,  # 可与电气元件装配并行
            "critical_path": True,
            "description": "焊接制冷管路系统，使用氮气保护防止氧化"
        },
        5: {
            "name": "电气元件装配",
            "name_en": "Electrical Assembly",
            "category": ProcessCategory.ELECTRICAL_ASSEMBLY,
            "standard_time": 7,
            "materials": [
                "主控板", "传感器", "线束", "开关"
            ],
            "predecessors": [3],  # 可与管路焊接并行
            "workstation": "工位5（电气区）",
            "workstation_id": 5,
            "parallel_capable": True,  # 可与管路焊接并行
            "critical_path": True,
            "description": "安装电气控制系统、传感器和线束"
        },
        6: {
            "name": "总装合箱",
            "name_en": "Final Assembly",
            "category": ProcessCategory.FINAL_ASSEMBLY,
            "standard_time": 11,
            "materials": [
                "门体", "铰链", "密封条", "螺丝"
            ],
            "predecessors": [4, 5],  # 需电气+管路完成
            "workstation": "工位6（总装区）",
            "workstation_id": 6,
            "parallel_capable": False,
            "critical_path": True,
            "description": "安装门体、密封条，完成冰箱总装"
        },
        7: {
            "name": "检测打包",
            "name_en": "Test & Packing",
            "category": ProcessCategory.TEST_PACKING,
            "standard_time": 5,
            "materials": [
                "检测仪器", "包装箱", "泡沫护角", "合格证"
            ],
            "predecessors": [6],  # 最终工序
            "workstation": "工位7（检测区）",
            "workstation_id": 7,
            "parallel_capable": False,
            "critical_path": True,
            "description": "质量检测、性能测试和包装入库"
        }
    }
    
    # 物料到工序的映射（用于快速查找）
    MATERIAL_TO_PROCESS = {}
    
    @classmethod
    def initialize_mapping(cls):
        """初始化物料到工序的映射"""
        if not cls.MATERIAL_TO_PROCESS:
            for process_id, process_info in cls.PROCESSES.items():
                for material in process_info["materials"]:
                    if material not in cls.MATERIAL_TO_PROCESS:
                        cls.MATERIAL_TO_PROCESS[material] = []
                    cls.MATERIAL_TO_PROCESS[material].append(process_id)
    
    @classmethod
    def get_process(cls, process_id: int) -> Optional[Dict]:
        """获取工序定义"""
        return cls.PROCESSES.get(process_id)
    
    @classmethod
    def get_processes_by_category(cls, category: ProcessCategory) -> List[Dict]:
        """获取指定类别的所有工序"""
        return [p for p in cls.PROCESSES.values() if p["category"] == category]
    
    @classmethod
    def get_workstation_processes(cls, workstation_id: int) -> List[Dict]:
        """获取指定工位的所有工序"""
        return [p for p in cls.PROCESSES.values() if p["workstation_id"] == workstation_id]
    
    @classmethod
    def get_material_processes(cls, material: str) -> List[int]:
        """获取使用指定物料的所有工序ID"""
        cls.initialize_mapping()
        return cls.MATERIAL_TO_PROCESS.get(material, [])
    
    @classmethod
    def get_predecessors(cls, process_id: int) -> List[int]:
        """获取工序的前置工序列表"""
        process = cls.get_process(process_id)
        return process["predecessors"] if process else []
    
    @classmethod
    def get_successors(cls, process_id: int) -> List[int]:
        """获取工序的后续工序列表"""
        successors = []
        for pid, process in cls.PROCESSES.items():
            if process_id in process["predecessors"]:
                successors.append(pid)
        return successors
    
    @classmethod
    def can_start_process(cls, process_id: int, completed_processes: List[int]) -> bool:
        """检查是否可以开始执行指定工序"""
        predecessors = cls.get_predecessors(process_id)
        return all(pred in completed_processes for pred in predecessors)
    
    @classmethod
    def get_parallel_processes(cls) -> Dict[int, List[int]]:
        """获取可并行的工序组"""
        parallel_groups = {}
        for pid, process in cls.PROCESSES.items():
            if process["parallel_capable"]:
                # 找到共享前置的工序组
                predecessors = tuple(sorted(process["predecessors"]))
                if predecessors not in parallel_groups:
                    parallel_groups[predecessors] = []
                parallel_groups[predecessors].append(pid)
        return parallel_groups
    
    @classmethod
    def get_critical_path_time(cls) -> int:
        """计算关键路径总时间"""
        # 简化的关键路径计算
        return sum(p["standard_time"] for p in cls.PROCESSES.values() if p["critical_path"])
    
    @classmethod
    def get_process_time_with_delay(cls, process_id: int, delay_minutes: float = 0) -> float:
        """计算工序时间（考虑延迟）"""
        process = cls.get_process(process_id)
        if not process:
            return 0
        
        base_time = process["standard_time"]
        
        # 物料延迟配送，工序工时增加20%
        if delay_minutes > 0:
            return base_time * 1.2
        return base_time
    
    @classmethod
    def get_workstation_id(cls, process_id: int) -> int:
        """获取工序对应的工位ID"""
        process = cls.get_process(process_id)
        return process["workstation_id"] if process else -1
    
    @classmethod
    def get_all_workstation_ids(cls) -> List[int]:
        """获取所有工位ID"""
        return list(set(p["workstation_id"] for p in cls.PROCESSES.values()))
    
    @classmethod
    def get_all_materials(cls) -> List[str]:
        """获取所有物料名称"""
        materials = set()
        for process in cls.PROCESSES.values():
            materials.update(process["materials"])
        return sorted(list(materials))


class RefrigeratorOrder:
    """冰箱工单类（代表一个待组装的冰箱）"""
    
    def __init__(self, order_id: int, priority: int = 1):
        self.order_id = order_id
        self.priority = priority  # 优先级，数字越小优先级越高
        self.state = {
            "created_time": 0,
            "started_time": None,
            "completed_time": None,
            "current_process": None,
            "completed_processes": [],  # 已完成的工序ID列表
            "process_start_times": {},  # {process_id: start_time}
            "process_end_times": {},    # {process_id: end_time}
            "material_consumed": {},    # {material: quantity}
            "delays": {}                # {process_id: delay_minutes}
        }
        self.status = ProcessStatus.PENDING
        self.total_elapsed_time = 0
    
    def start_process(self, process_id: int, current_time: float):
        """开始执行工序"""
        self.state["current_process"] = process_id
        self.state["process_start_times"][process_id] = current_time
        self.status = ProcessStatus.IN_PROGRESS
    
    def complete_process(self, process_id: int, current_time: float, actual_time: float):
        """完成工序"""
        if process_id in self.state["completed_processes"]:
            return
        
        self.state["completed_processes"].append(process_id)
        self.state["process_end_times"][process_id] = current_time
        self.state["current_process"] = None
        
        # 计算延迟
        process = RefrigeratorProcess.get_process(process_id)
        if process:
            base_time = process["standard_time"]
            delay = actual_time - base_time
            if delay > 0:
                self.state["delays"][process_id] = delay
    
    def is_complete(self) -> bool:
        """检查是否完成所有工序"""
        return len(self.state["completed_processes"]) == len(RefrigeratorProcess.PROCESSES)
    
    def can_start_process(self, process_id: int) -> bool:
        """检查是否可以开始指定工序"""
        return RefrigeratorProcess.can_start_process(
            process_id, self.state["completed_processes"]
        )
    
    def get_remaining_processes(self) -> List[int]:
        """获取剩余可执行的工序"""
        remaining = []
        for pid in RefrigeratorProcess.PROCESSES.keys():
            if pid not in self.state["completed_processes"]:
                if self.can_start_process(pid):
                    remaining.append(pid)
        return remaining
    
    def get_total_delay(self) -> float:
        """获取总延迟时间"""
        return sum(self.state["delays"].values())
    
    def get_completion_rate(self) -> float:
        """获取完成进度"""
        return len(self.state["completed_processes"]) / len(RefrigeratorProcess.PROCESSES)


class ProcessConstraint:
    """工序约束检查类"""
    
    @staticmethod
    def check_workstation_constraint(workstation_id: int, occupied_by: int = None) -> bool:
        """
        检查工位约束
        
        约束：同一工位同一时间仅能处理1个冰箱工单
        """
        # 实际实现需要与场景管理器交互
        # 这里提供接口，具体实现在场景中
        return True
    
    @staticmethod
    def check_material_constraint(process_id: int, material_status: Dict) -> tuple:
        """
        检查物料前置约束
        
        约束：工序启动前，所需物料必须由AGV配送至物料缓存区
        
        Returns:
            (can_start: bool, missing_materials: List[str])
        """
        process = RefrigeratorProcess.get_process(process_id)
        if not process:
            return False, []
        
        missing = []
        for material in process["materials"]:
            if material not in material_status:
                missing.append(material)
            elif material_status[material] <= 0:
                missing.append(material)
        
        return len(missing) == 0, missing
    
    @staticmethod
    def check_predecessor_constraint(process_id: int, completed_processes: List[int]) -> bool:
        """检查前置工序约束"""
        return RefrigeratorProcess.can_start_process(process_id, completed_processes)
    
    @staticmethod
    def apply_time_elasticity(base_time: float, delay_minutes: float) -> float:
        """
        应用工时弹性
        
        规则：若物料延迟配送，工序工时增加20%
        """
        if delay_minutes > 0:
            return base_time * 1.2
        return base_time


# 便捷函数
def get_process_info(process_id: int) -> Dict:
    """获取工序信息"""
    return RefrigeratorProcess.get_process(process_id)


def get_all_processes() -> Dict:
    """获取所有工序定义"""
    return RefrigeratorProcess.PROCESSES


def calculate_total_production_time() -> int:
    """计算标准生产总时间"""
    return RefrigeratorProcess.get_critical_path_time()


def get_process_sequence_for_parallel() -> List[List[int]]:
    """获取可并行执行的工序序列"""
    # 返回推荐的工序执行序列（考虑并行）
    return [
        [0],           # 阶段1: 钣金成型
        [1],           # 阶段2: 内胆吸塑
        [2],           # 阶段3: 发泡填充
        [3],           # 阶段4: 压缩机安装
        [4, 5],        # 阶段5: 管路焊接 和 电气元件装配（并行）
        [6],           # 阶段6: 总装合箱
        [7]            # 阶段7: 检测打包
    ]
