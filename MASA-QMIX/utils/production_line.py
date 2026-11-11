"""
生产线模块
管理18个工位、9道工序约束、冰箱订单流转
与甘特图数据同步，支持真实调度场景演示
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, field
import copy


class WorkstationStatus(Enum):
    """工位状态"""
    IDLE = "idle"           # 空闲
    BUSY = "busy"          # 工作中
    BLOCKED = "blocked"     # 被阻塞（等待物料）
    MAINTENANCE = "maintenance"  # 维护中


class ProcessStatus(Enum):
    """工序状态"""
    PENDING = "pending"      # 等待开始
    IN_PROGRESS = "in_progress"  # 执行中
    COMPLETED = "completed"  # 已完成
    WAITING_MATERIAL = "waiting_material"  # 等待物料


@dataclass
class ProcessDefinition:
    """工序定义"""
    process_id: int
    name: str
    standard_time: float
    workstation_ids: List[int]  # 工序可用的工位列表
    predecessors: List[int]      # 前置工序
    parallel_capable: bool = False  # 是否可并行
    materials: List[str] = field(default_factory=list)
    color: str = "#3b82f6"      # 可视化颜色


@dataclass
class Workstation:
    """工位"""
    workstation_id: int
    process_id: int            # 对应工序
    position: Tuple[float, float]  # 布局位置
    status: WorkstationStatus = WorkstationStatus.IDLE
    current_job_id: Optional[int] = None  # 当前作业ID
    remaining_time: float = 0.0
    queue: List[int] = field(default_factory=list)  # 等待队列
    total_processed: int = 0
    utilization: float = 0.0
    
    # 缓存区（AGV配送物料）
    buffer_stock: Dict[str, int] = field(default_factory=dict)


class ProductionLine:
    """
    生产线管理器
    管理18个工位、9道工序、8个并发冰箱订单
    """
    
    # 工序定义（9道工序，18个工位）
    PROCESS_DEFINITIONS: Dict[int, ProcessDefinition] = {
        0: ProcessDefinition(
            process_id=0,
            name="钣金成型",
            standard_time=8.0,
            workstation_ids=[0, 1],  # 2个工位
            predecessors=[],
            materials=["冷轧钢板", "折弯模具", "铆钉"],
            color="#2563eb"
        ),
        1: ProcessDefinition(
            process_id=1,
            name="内胆吸塑",
            standard_time=6.0,
            workstation_ids=[2, 3],  # 2个工位
            predecessors=[0],
            materials=["ABS粒子", "吸塑模具", "加热管"],
            color="#7c3aed"
        ),
        2: ProcessDefinition(
            process_id=2,
            name="发泡填充",
            standard_time=12.0,
            workstation_ids=[4, 5, 6],  # 3个工位
            predecessors=[0, 1],
            materials=["聚氨酯发泡料", "发泡模具", "密封胶"],
            color="#0891b2"
        ),
        3: ProcessDefinition(
            process_id=3,
            name="压缩机安装",
            standard_time=10.0,
            workstation_ids=[7, 8],  # 2个工位
            predecessors=[2],
            materials=["压缩机", "铜管", "固定螺栓", "减震垫"],
            color="#059669"
        ),
        4: ProcessDefinition(
            process_id=4,
            name="管路焊接",
            standard_time=9.0,
            workstation_ids=[9, 10],  # 2个工位
            predecessors=[3],
            materials=["铜管", "焊料", "氮气瓶", "焊枪"],
            parallel_capable=True,
            color="#d97706"
        ),
        5: ProcessDefinition(
            process_id=5,
            name="电气元件装配",
            standard_time=7.0,
            workstation_ids=[11, 12],  # 2个工位
            predecessors=[3],
            materials=["主控板", "传感器", "线束", "开关"],
            parallel_capable=True,  # 可与管路焊接并行
            color="#dc2626"
        ),
        6: ProcessDefinition(
            process_id=6,
            name="总装合箱",
            standard_time=11.0,
            workstation_ids=[13, 14],  # 2个工位
            predecessors=[4, 5],  # 需管路焊接和电气装配完成
            materials=["门体", "铰链", "密封条", "螺丝"],
            color="#7c2d12"
        ),
        7: ProcessDefinition(
            process_id=7,
            name="检测调试",
            standard_time=5.0,
            workstation_ids=[15, 16],  # 2个工位
            predecessors=[6],
            materials=["检测仪器", "测试线束"],
            color="#0d9488"
        ),
        8: ProcessDefinition(
            process_id=8,
            name="打包入库",
            standard_time=4.0,
            workstation_ids=[17],  # 1个工位
            predecessors=[7],
            materials=["包装箱", "泡沫护角", "合格证"],
            color="#4b5563"
        ),
    }
    
    # 工位布局位置（2行9列网格）
    WORKSTATION_LAYOUT: List[Tuple[float, float]] = [
        # 第一行（工位0-8）
        (40, 20), (80, 20), (120, 20), (160, 20), (200, 20),
        (240, 20), (280, 20), (320, 20), (360, 20),
        # 第二行（工位9-17）
        (40, 80), (80, 80), (120, 80), (160, 80), (200, 80),
        (240, 80), (280, 80), (320, 80), (360, 80),
    ]
    
    def __init__(self, n_jobs: int = 8):
        """
        初始化生产线
        
        Args:
            n_jobs: 并发冰箱作业数量（默认8个）
        """
        self.n_jobs = n_jobs
        self.workstations: Dict[int, Workstation] = {}
        self.current_time: float = 0.0
        self.gantt_data: List[List[Any]] = []  # 甘特图数据
        self.job_progress: Dict[int, Dict] = {}  # 作业进度追踪
        self.is_playing: bool = False
        self.playback_index: int = 0
        
        # 初始化工位
        self._initialize_workstations()
        
    def _initialize_workstations(self):
        """初始化18个工位"""
        for ws_id in range(18):
            # 找到该工位对应的工序
            process_id = self._get_process_for_workstation(ws_id)
            process_def = self.PROCESS_DEFINITIONS[process_id]
            
            self.workstations[ws_id] = Workstation(
                workstation_id=ws_id,
                process_id=process_id,
                position=self.WORKSTATION_LAYOUT[ws_id]
            )
    
    def _get_process_for_workstation(self, ws_id: int) -> int:
        """获取工位对应的工序ID"""
        for process_id, process_def in self.PROCESS_DEFINITIONS.items():
            if ws_id in process_def.workstation_ids:
                return process_id
        return 0
    
    def load_gantt_data(self, gantt_data: List[List[Any]]):
        """
        加载甘特图数据进行回放
        
        Args:
            gantt_data: 甘特图数据，每条记录 [start_time, duration, workstation_id, job_id, process_id]
        """
        self.gantt_data = sorted(gantt_data, key=lambda x: x[0])
        self.playback_index = 0
        self._reset_state()
    
    def _reset_state(self):
        """重置生产线状态"""
        self.current_time = 0.0
        self.job_progress = {}
        
        # 重置所有工位
        for ws in self.workstations.values():
            ws.status = WorkstationStatus.IDLE
            ws.current_job_id = None
            ws.remaining_time = 0.0
            ws.queue = []
    
    def step(self, delta_time: float = 1.0) -> Dict[str, Any]:
        """
        执行一步模拟
        
        Args:
            delta_time: 时间步长（默认1个时间单位）
            
        Returns:
            当前状态快照
        """
        self.current_time += delta_time
        return self.get_current_state()
    
    def step_to_time(self, target_time: float) -> Dict[str, Any]:
        """
        快进到指定时间
        
        Args:
            target_time: 目标时间
        """
        self.current_time = target_time
        self._update_from_gantt()
        return self.get_current_state()
    
    def _update_from_gantt(self):
        """根据甘特图数据更新工位状态"""
        # 重置所有工位
        for ws in self.workstations.values():
            ws.status = WorkstationStatus.IDLE
            ws.current_job_id = None
            ws.remaining_time = 0.0
        
        # 遍历甘特图数据，更新工位状态
        for record in self.gantt_data:
            if len(record) >= 5:
                start_time, duration, ws_id, job_id, process_id = record[0], record[1], record[2], record[3], record[4]
                end_time = start_time + duration
                
                # 检查该工序是否在当前时间范围内
                if start_time <= self.current_time < end_time:
                    if ws_id in self.workstations:
                        ws = self.workstations[ws_id]
                        ws.status = WorkstationStatus.BUSY
                        ws.current_job_id = int(job_id)
                        ws.remaining_time = end_time - self.current_time
                        
                        # 更新作业进度
                        job_id_int = int(job_id)
                        if job_id_int not in self.job_progress:
                            self.job_progress[job_id_int] = {
                                "job_id": job_id_int,
                                "current_process": int(process_id),
                                "completed_processes": [],
                                "start_time": start_time,
                                "position": ws.position
                            }
                        else:
                            self.job_progress[job_id_int]["current_process"] = int(process_id)
                            self.job_progress[job_id_int]["position"] = ws.position
                            
                # 如果工序已完成
                elif self.current_time >= end_time:
                    job_id_int = int(job_id)
                    process_id_int = int(process_id)
                    if job_id_int not in self.job_progress:
                        self.job_progress[job_id_int] = {
                            "job_id": job_id_int,
                            "current_process": None,
                            "completed_processes": [process_id_int],
                            "start_time": start_time,
                            "end_time": end_time
                        }
                    else:
                        if process_id_int not in self.job_progress[job_id_int]["completed_processes"]:
                            self.job_progress[job_id_int]["completed_processes"].append(process_id_int)
                        self.job_progress[job_id_int]["current_process"] = None
    
    def get_current_state(self) -> Dict[str, Any]:
        """
        获取当前生产线状态
        
        Returns:
            完整状态快照
        """
        # 更新甘特图状态
        self._update_from_gantt()
        
        # 收集工位状态
        workstations_state = []
        for ws_id, ws in self.workstations.items():
            workstations_state.append({
                "id": int(ws_id),
                "process_id": int(ws.process_id),
                "process_name": self.PROCESS_DEFINITIONS[ws.process_id].name,
                "position": [float(ws.position[0]), float(ws.position[1])],
                "status": str(ws.status.value),
                "current_job_id": int(ws.current_job_id) if ws.current_job_id is not None else None,
                "remaining_time": float(round(ws.remaining_time, 1)),
                "color": str(self.PROCESS_DEFINITIONS[ws.process_id].color),
                "utilization": float(round(ws.utilization, 2))
            })
        
        # 收集作业状态
        jobs_state = []
        for job_id in range(self.n_jobs):
            progress = self.job_progress.get(job_id, {
                "job_id": job_id,
                "current_process": None,
                "completed_processes": [],
                "position": (0, 0)
            })
            
            completed = len(progress.get("completed_processes", []))
            total_processes = len(self.PROCESS_DEFINITIONS)
            
            # 确定作业位置
            if progress.get("current_process") is not None:
                process_id = progress["current_process"]
                # 找到当前工序对应的工位
                ws_id = self._find_workstation_for_job(job_id, process_id)
                if ws_id is not None:
                    position = list(self.workstations[ws_id].position)
                else:
                    position = list(progress.get("position", (0, 0)))
            else:
                position = list(progress.get("position", (0, 0)))
            
            jobs_state.append({
                "id": int(job_id),
                "name": f"冰箱{job_id + 1}",
                "current_process": int(process_id) if progress.get("current_process") is not None else None,
                "current_process_name": self.PROCESS_DEFINITIONS[progress.get("current_process", -1)].name if progress.get("current_process") is not None else "已完成" if completed == total_processes else "等待中",
                "completed_processes": [int(x) for x in progress.get("completed_processes", [])],
                "progress": float(completed / total_processes) if total_processes > 0 else 0.0,
                "completed_count": int(completed),
                "total_processes": int(total_processes),
                "position": [float(position[0]), float(position[1])],
                "status": "completed" if completed == total_processes else "processing" if progress.get("current_process") is not None else "waiting"
            })
        
        return {
            "current_time": float(round(self.current_time, 1)),
            "workstations": workstations_state,
            "jobs": jobs_state,
            "total_jobs": int(self.n_jobs),
            "completed_jobs": int(len([j for j in jobs_state if j["status"] == "completed"])),
            "processing_jobs": int(len([j for j in jobs_state if j["status"] == "processing"])),
            "waiting_jobs": int(len([j for j in jobs_state if j["status"] == "waiting"])),
            "total_workstations": int(len(self.workstations)),
            "busy_workstations": int(len([ws for ws in self.workstations.values() if ws.status == WorkstationStatus.BUSY])),
            "idle_workstations": int(len([ws for ws in self.workstations.values() if ws.status == WorkstationStatus.IDLE])),
            "gantt_total_records": int(len(self.gantt_data))
        }
    
    def _find_workstation_for_job(self, job_id: int, process_id: int) -> Optional[int]:
        """找到作业当前所在的工位"""
        for ws_id, ws in self.workstations.items():
            if ws.current_job_id == job_id and ws.process_id == process_id:
                return ws_id
        return None
    
    def get_workstation_for_process(self, process_id: int) -> List[int]:
        """获取指定工序可用的工位列表"""
        if process_id in self.PROCESS_DEFINITIONS:
            return self.PROCESS_DEFINITIONS[process_id].workstation_ids
        return []
    
    def get_available_workstation(self, process_id: int) -> Optional[int]:
        """获取指定工序的空闲工位"""
        available_ws = self.get_workstation_for_process(process_id)
        for ws_id in available_ws:
            if self.workstations[ws_id].status == WorkstationStatus.IDLE:
                return ws_id
        return None
    
    def get_process_definition(self, process_id: int) -> Optional[ProcessDefinition]:
        """获取工序定义"""
        return self.PROCESS_DEFINITIONS.get(process_id)
    
    def get_all_process_definitions(self) -> Dict[int, ProcessDefinition]:
        """获取所有工序定义"""
        return self.PROCESS_DEFINITIONS
    
    def get_process_sequence(self) -> List[List[int]]:
        """
        获取工序执行序列（考虑并行）
        
        Returns:
            按阶段分组的工序列表
        """
        return [
            [0],           # 阶段1: 钣金成型
            [1],           # 阶段2: 内胆吸塑
            [2],           # 阶段3: 发泡填充
            [3],           # 阶段4: 压缩机安装
            [4, 5],        # 阶段5: 管路焊接 和 电气元件装配（并行）
            [6],           # 阶段6: 总装合箱
            [7],           # 阶段7: 检测调试
            [8]            # 阶段8: 打包入库
        ]
    
    def calculate_completion_rate(self) -> float:
        """计算当前完成率"""
        if not self.job_progress:
            return 0.0
        total_completed = sum(len(j.get("completed_processes", [])) for j in self.job_progress.values())
        total_possible = self.n_jobs * len(self.PROCESS_DEFINITIONS)
        return total_completed / total_possible if total_possible > 0 else 0.0
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取生产线统计信息"""
        state = self.get_current_state()
        return {
            "current_time": state["current_time"],
            "completion_rate": self.calculate_completion_rate(),
            "throughput": state["completed_jobs"] / max(0.1, self.current_time) * 10,  # 台/10时间单位
            "workstation_utilization": state["busy_workstations"] / max(1, state["total_workstations"]),
            "avg_job_progress": sum(j["progress"] for j in state["jobs"]) / max(1, len(state["jobs"])),
            "active_processes": state["processing_jobs"]
        }
    
    def export_gantt_sync_data(self) -> Dict[str, Any]:
        """
        导出与甘特图同步所需的数据
        用于前端动画同步
        """
        # 按时间排序的事件
        events = []
        
        for record in self.gantt_data:
            if len(record) >= 5:
                start_time, duration, ws_id, job_id, process_id = record
                process_def = self.PROCESS_DEFINITIONS.get(process_id, {})
                
                events.append({
                    "time": float(start_time),
                    "type": "start",
                    "ws_id": int(ws_id),
                    "job_id": int(job_id),
                    "process_id": int(process_id),
                    "process_name": str(process_def.name) if process_def else f"工序{process_id}",
                    "color": str(process_def.color) if process_def else "#3b82f6"
                })
                
                events.append({
                    "time": float(start_time + duration),
                    "type": "end",
                    "ws_id": int(ws_id),
                    "job_id": int(job_id),
                    "process_id": int(process_id),
                    "process_name": str(process_def.name) if process_def else f"工序{process_id}",
                    "color": str(process_def.color) if process_def else "#3b82f6"
                })
        
        # 按时间排序
        events.sort(key=lambda x: x["time"])
        
        max_time = float(max([r[0] + r[1] for r in self.gantt_data], default=100.0))
        
        return {
            "events": events,
            "max_time": max_time,
            "total_workstations": int(len(self.workstations)),
            "total_jobs": int(self.n_jobs),
            "process_definitions": {
                int(pid): {
                    "name": str(pd.name),
                    "color": str(pd.color),
                    "standard_time": float(pd.standard_time),
                    "workstation_ids": [int(x) for x in pd.workstation_ids]
                }
                for pid, pd in self.PROCESS_DEFINITIONS.items()
            }
        }


class GanttAnimator:
    """
    甘特图动画控制器
    控制动态演示与甘特图的同步播放
    """
    
    def __init__(self, production_line: ProductionLine):
        self.production_line = production_line
        self.current_index = 0
        self.is_playing = False
        self.speed = 1.0  # 播放速度倍数
        self.sync_data = None
        
    def initialize(self, gantt_data: List[List[Any]]):
        """初始化动画数据"""
        self.production_line.load_gantt_data(gantt_data)
        self.sync_data = self.production_line.export_gantt_sync_data()
        self.current_index = 0
        
    def play(self):
        """开始播放"""
        self.is_playing = True
        
    def pause(self):
        """暂停播放"""
        self.is_playing = False
        
    def stop(self):
        """停止并重置"""
        self.is_playing = False
        self.current_index = 0
        self.production_line.step_to_time(0)
        
    def set_speed(self, speed: float):
        """设置播放速度"""
        self.speed = max(0.1, min(10.0, speed))
        
    def step_forward(self, delta: float = 1.0):
        """前进一步"""
        new_time = self.production_line.current_time + delta * self.speed
        max_time = self.sync_data["max_time"] if self.sync_data else 100
        self.production_line.step_to_time(min(new_time, max_time))
        
    def step_backward(self, delta: float = 1.0):
        """后退一步"""
        new_time = self.production_line.current_time - delta * self.speed
        self.production_line.step_to_time(max(new_time, 0))
        
    def seek_to(self, time: float):
        """跳转到指定时间"""
        self.production_line.step_to_time(time)
        
    def get_current_frame(self) -> Dict[str, Any]:
        """获取当前帧数据"""
        state = self.production_line.get_current_state()
        return {
            **state,
            "is_playing": self.is_playing,
            "speed": self.speed,
            "max_time": self.sync_data["max_time"] if self.sync_data else 100,
            "progress": state["current_time"] / max(0.1, self.sync_data["max_time"]) if self.sync_data else 0
        }
    
    def get_upcoming_events(self, look_ahead: float = 5.0) -> List[Dict]:
        """获取即将发生的事件"""
        if not self.sync_data:
            return []
        
        current_time = self.production_line.current_time
        events = []
        
        for event in self.sync_data["events"]:
            if current_time < event["time"] <= current_time + look_ahead:
                events.append(event)
                
        return events[:10]  # 最多返回10个
    
    def get_process_colors(self) -> Dict[int, str]:
        """获取工序颜色映射"""
        if self.sync_data:
            return {int(k): v["color"] for k, v in self.sync_data["process_definitions"].items()}
        return {i: self.production_line.PROCESS_DEFINITIONS[i].color 
                for i in self.production_line.PROCESS_DEFINITIONS}
