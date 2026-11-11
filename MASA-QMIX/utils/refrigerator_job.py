"""
冰箱作业模块
管理8个并发冰箱订单的工序流转追踪
与甘特图数据同步，支持订单状态可视化
"""

from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from dataclasses import dataclass, field
from utils.production_line import ProductionLine, ProcessDefinition


class JobStatus(Enum):
    """作业状态"""
    WAITING = "waiting"           # 等待开始
    PROCESSING = "processing"     # 加工中
    WAITING_MATERIAL = "waiting_material"  # 等待物料
    COMPLETED = "completed"       # 已完成
    BLOCKED = "blocked"          # 被阻塞


@dataclass
class ProcessRecord:
    """工序执行记录"""
    process_id: int
    job_id: int
    start_time: float
    end_time: float
    duration: float
    workstation_id: int
    status: str = "completed"
    
    def to_list(self) -> List:
        """转换为列表格式 [start_time, duration, workstation_id, job_id, process_id]"""
        return [self.start_time, self.duration, self.workstation_id, self.job_id, self.process_id]


@dataclass
class RefrigeratorJob:
    """
    冰箱作业类
    追踪单个冰箱订单的9道工序流转
    """
    
    job_id: int
    priority: int = 1  # 优先级（数字越小优先级越高）
    
    # 工序状态
    current_process: Optional[int] = None
    completed_processes: List[int] = field(default_factory=list)
    
    # 时间追踪
    created_time: float = 0.0
    started_time: Optional[float] = None
    completed_time: Optional[float] = None
    
    # 位置（在工厂中的可视化位置）
    position: Tuple[float, float] = (0, 0)
    
    # 状态
    status: JobStatus = JobStatus.WAITING
    
    # 工序执行记录
    process_records: List[ProcessRecord] = field(default_factory=list)
    
    # 延迟信息
    delays: Dict[int, float] = field(default_factory=dict)  # {process_id: delay_time}
    
    def start_process(self, process_id: int, time: float, workstation_id: int):
        """开始执行工序"""
        self.current_process = process_id
        self.started_time = time if self.started_time is None else self.started_time
        self.status = JobStatus.PROCESSING
        
    def complete_process(self, process_id: int, time: float, actual_duration: float, 
                         expected_duration: float, workstation_id: int):
        """
        完成工序
        
        Args:
            process_id: 工序ID
            time: 完成时间
            actual_duration: 实际用时
            expected_duration: 预期用时
            workstation_id: 执行工位ID
        """
        if process_id in self.completed_processes:
            return
            
        self.completed_processes.append(process_id)
        
        # 记录工序执行
        record = ProcessRecord(
            process_id=process_id,
            job_id=self.job_id,
            start_time=time - actual_duration,
            end_time=time,
            duration=actual_duration,
            workstation_id=workstation_id
        )
        self.process_records.append(record)
        
        # 记录延迟
        if actual_duration > expected_duration:
            self.delays[process_id] = actual_duration - expected_duration
            
        self.current_process = None
        
        # 检查是否全部完成
        if len(self.completed_processes) == 9:  # 9道工序
            self.completed_time = time
            self.status = JobStatus.COMPLETED
    
    def can_start_process(self, process_id: int, process_defs: Dict[int, ProcessDefinition]) -> bool:
        """检查是否可以开始指定工序"""
        process_def = process_defs.get(process_id)
        if not process_def:
            return False
            
        # 检查前置工序是否完成
        for pred in process_def.predecessors:
            if pred not in self.completed_processes:
                return False
        return True
    
    def get_remaining_processes(self, process_defs: Dict[int, ProcessDefinition]) -> List[int]:
        """获取剩余可执行的工序"""
        remaining = []
        for pid in process_defs.keys():
            if pid not in self.completed_processes:
                if self.can_start_process(pid, process_defs):
                    remaining.append(pid)
        return sorted(remaining, key=lambda x: process_defs[x].standard_time)
    
    def get_total_delay(self) -> float:
        """获取总延迟时间"""
        return sum(self.delays.values())
    
    def get_completion_rate(self) -> float:
        """获取完成进度"""
        return len(self.completed_processes) / 9.0
    
    def get_process_info(self, process_id: int, process_defs: Dict[int, ProcessDefinition]) -> Dict:
        """获取工序详细信息"""
        process_def = process_defs.get(process_id)
        if not process_def:
            return {}
            
        # 查找该工序的执行记录
        record = next((r for r in self.process_records if r.process_id == process_id), None)
        
        return {
            "process_id": process_id,
            "name": process_def.name,
            "status": "completed" if process_id in self.completed_processes else 
                     "processing" if self.current_process == process_id else "pending",
            "standard_time": process_def.standard_time,
            "actual_time": record.duration if record else None,
            "start_time": record.start_time if record else None,
            "end_time": record.end_time if record else None,
            "delay": self.delays.get(process_id, 0),
            "workstation_id": record.workstation_id if record else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "job_id": self.job_id,
            "name": f"冰箱{self.job_id + 1}",
            "priority": self.priority,
            "status": self.status.value,
            "current_process": self.current_process,
            "completed_processes": self.completed_processes,
            "completion_rate": self.get_completion_rate(),
            "total_delay": self.get_total_delay(),
            "position": list(self.position),
            "created_time": self.created_time,
            "started_time": self.started_time,
            "completed_time": self.completed_time,
            "total_time": (self.completed_time - self.started_time) if self.completed_time and self.started_time else None
        }


class RefrigeratorJobManager:
    """
    冰箱作业管理器
    管理8个并发冰箱订单，处理工序调度逻辑
    """
    
    def __init__(self, n_jobs: int = 8):
        """
        初始化作业管理器
        
        Args:
            n_jobs: 并发作业数量（默认8个）
        """
        self.n_jobs = n_jobs
        self.jobs: Dict[int, RefrigeratorJob] = {}
        self.production_line: Optional[ProductionLine] = None
        
        # 初始化作业
        self._initialize_jobs()
        
    def _initialize_jobs(self):
        """初始化所有冰箱作业"""
        for i in range(self.n_jobs):
            self.jobs[i] = RefrigeratorJob(job_id=i, priority=i % 3 + 1)
            
    def set_production_line(self, production_line: ProductionLine):
        """设置关联的生产线"""
        self.production_line = production_line
        
    def load_from_gantt(self, gantt_data: List[List[Any]]):
        """
        从甘特图数据加载作业状态
        
        Args:
            gantt_data: 甘特图数据 [start_time, duration, workstation_id, job_id, process_id]
        """
        # 按作业分组
        jobs_data: Dict[int, List[List]] = {}
        for record in gantt_data:
            if len(record) >= 5:
                job_id = int(record[3])
                if job_id not in jobs_data:
                    jobs_data[job_id] = []
                jobs_data[job_id].append(record)
        
        # 更新作业状态
        for job_id, records in jobs_data.items():
            if job_id in self.jobs:
                job = self.jobs[job_id]
                job.completed_processes = []
                job.process_records = []
                
                for record in records:
                    start_time, duration, ws_id, jid, process_id = record
                    job.completed_processes.append(int(process_id))
                    
                    # 创建执行记录
                    rec = ProcessRecord(
                        process_id=int(process_id),
                        job_id=int(jid),
                        start_time=float(start_time),
                        end_time=float(start_time + duration),
                        duration=float(duration),
                        workstation_id=int(ws_id)
                    )
                    job.process_records.append(rec)
                    
                # 更新当前工序（根据当前时间）
                if self.production_line:
                    current_time = self.production_line.current_time
                    current_process = None
                    for rec in sorted(job.process_records, key=lambda x: x.start_time):
                        if rec.start_time <= current_time < rec.end_time:
                            current_process = rec.process_id
                            break
                    job.current_process = current_process
                    
                    # 更新状态
                    if len(job.completed_processes) == 9:
                        job.status = JobStatus.COMPLETED
                        job.completed_time = max(r.end_time for r in job.process_records)
                    elif current_process is not None:
                        job.status = JobStatus.PROCESSING
                    elif len(job.completed_processes) > 0:
                        job.status = JobStatus.PROCESSING
                    else:
                        job.status = JobStatus.WAITING
                        
                # 更新位置
                if self.production_line:
                    if job.current_process is not None:
                        # 找到当前工序对应的工位
                        available_ws = self.production_line.get_workstation_for_process(job.current_process)
                        for ws_id in available_ws:
                            if self.production_line.workstations[ws_id].current_job_id == job_id:
                                job.position = self.production_line.workstations[ws_id].position
                                break
    
    def get_job(self, job_id: int) -> Optional[RefrigeratorJob]:
        """获取指定作业"""
        return self.jobs.get(job_id)
    
    def get_all_jobs(self) -> List[RefrigeratorJob]:
        """获取所有作业"""
        return list(self.jobs.values())
    
    def get_completed_jobs(self) -> List[RefrigeratorJob]:
        """获取已完成的作业"""
        return [j for j in self.jobs.values() if j.status == JobStatus.COMPLETED]
    
    def get_processing_jobs(self) -> List[RefrigeratorJob]:
        """获取正在加工的作业"""
        return [j for j in self.jobs.values() if j.status == JobStatus.PROCESSING]
    
    def get_job_at_workstation(self, workstation_id: int) -> Optional[RefrigeratorJob]:
        """获取指定工位上的作业"""
        if self.production_line:
            ws = self.production_line.workstations.get(workstation_id)
            if ws and ws.current_job_id is not None:
                return self.jobs.get(ws.current_job_id)
        return None
    
    def get_jobs_by_process(self, process_id: int) -> List[RefrigeratorJob]:
        """获取正在执行指定工序的作业"""
        return [j for j in self.jobs.values() if j.current_process == process_id]
    
    def get_process_sequence(self) -> List[List[int]]:
        """
        获取工序执行序列（考虑并行约束）
        
        Returns:
            按阶段分组的工序列表
        """
        if self.production_line:
            return self.production_line.get_process_sequence()
        return [[i] for i in range(9)]
    
    def export_gantt_data(self) -> List[List[Any]]:
        """
        导出所有作业的甘特图数据
        
        Returns:
            甘特图数据列表 [start_time, duration, workstation_id, job_id, process_id]
        """
        gantt_data = []
        for job in self.jobs.values():
            for record in job.process_records:
                gantt_data.append(record.to_list())
        return sorted(gantt_data, key=lambda x: (x[0], x[3]))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取作业统计信息"""
        completed = self.get_completed_jobs()
        processing = self.get_processing_jobs()
        
        total_completion_rate = 0.0
        total_delay = 0.0
        completion_times = []
        
        for job in self.jobs.values():
            total_completion_rate += job.get_completion_rate()
            total_delay += job.get_total_delay()
            if job.completed_time and job.started_time:
                completion_times.append(job.completed_time - job.started_time)
        
        avg_completion_time = sum(completion_times) / len(completion_times) if completion_times else 0
        
        avg_makespan = 0
        if completed:
            makespans = [j.completed_time - j.started_time for j in completed if j.completed_time and j.started_time]
            avg_makespan = max(makespans) if makespans else 0
        
        return {
            "total_jobs": self.n_jobs,
            "completed_jobs": len(completed),
            "processing_jobs": len(processing),
            "waiting_jobs": self.n_jobs - len(completed) - len(processing),
            "avg_completion_rate": total_completion_rate / max(1, self.n_jobs),
            "total_delay": total_delay,
            "avg_completion_time": avg_completion_time,
            "avg_makespan": avg_makespan
        }
    
    def get_current_state(self) -> Dict[str, Any]:
        """
        获取当前作业状态
        
        Returns:
            作业状态详情
        """
        jobs_state = []
        
        for job_id, job in self.jobs.items():
            # 获取工序详细信息
            process_details = []
            if self.production_line:
                for pid in range(9):
                    info = job.get_process_info(pid, self.production_line.get_all_process_definitions())
                    if info:
                        process_details.append(info)
            
            jobs_state.append({
                "job_id": job.job_id,
                "name": f"冰箱{job.job_id + 1}",
                "status": job.status.value,
                "priority": job.priority,
                "current_process": job.current_process,
                "completed_processes": job.completed_processes,
                "completion_rate": job.get_completion_rate(),
                "total_delay": job.get_total_delay(),
                "position": list(job.position),
                "process_details": process_details,
                "created_time": job.created_time,
                "started_time": job.started_time,
                "completed_time": job.completed_time
            })
        
        return {
            "jobs": jobs_state,
            "statistics": self.get_statistics()
        }


class JobVisualizationHelper:
    """
    作业可视化辅助工具
    提供用于前端展示的格式化数据
    """
    
    def __init__(self, job_manager: RefrigeratorJobManager):
        self.job_manager = job_manager
        
    # 工序名称映射
    PROCESS_NAMES = {
        0: "钣金成型",
        1: "内胆吸塑", 
        2: "发泡填充",
        3: "压缩机安装",
        4: "管路焊接",
        5: "电气元件装配",
        6: "总装合箱",
        7: "检测调试",
        8: "打包入库"
    }
    
    # 工序颜色
    PROCESS_COLORS = {
        0: "#2563eb",  # 蓝色
        1: "#7c3aed",  # 紫色
        2: "#0891b2",  # 青色
        3: "#059669",  # 绿色
        4: "#d97706",  # 橙色
        5: "#dc2626",  # 红色
        6: "#7c2d12",  # 深红
        7: "#0d9488",  # 青色
        8: "#4b5563"   # 灰色
    }
    
    def format_jobs_for_frontend(self) -> List[Dict[str, Any]]:
        """格式化作业数据用于前端展示"""
        jobs_data = []
        
        for job in self.job_manager.get_all_jobs():
            # 进度条显示
            progress_bar = self._generate_progress_bar(job.get_completion_rate())
            
            jobs_data.append({
                "id": job.job_id,
                "name": f"冰箱{job.job_id + 1}",
                "status": job.status.value,
                "status_text": self._get_status_text(job.status),
                "status_color": self._get_status_color(job.status),
                "current_process": job.current_process,
                "current_process_name": self.PROCESS_NAMES.get(job.current_process, "已完成") if job.current_process is not None else None,
                "current_process_color": self.PROCESS_COLORS.get(job.current_process, "#6b7280") if job.current_process is not None else "#6b7280",
                "completed_count": len(job.completed_processes),
                "total_processes": 9,
                "completion_rate": job.get_completion_rate(),
                "progress_bar": progress_bar,
                "progress_text": f"{len(job.completed_processes)}/9",
                "position": list(job.position),
                "total_delay": f"+{job.get_total_delay():.1f}min" if job.get_total_delay() > 0 else "0min",
                "priority": job.priority,
                "priority_class": f"priority-{job.priority}"
            })
        
        return jobs_data
    
    def format_workstations_for_frontend(self) -> List[Dict[str, Any]]:
        """格式化工位数据用于前端展示"""
        if not self.job_manager.production_line:
            return []
            
        workstations_data = []
        process_defs = self.job_manager.production_line.get_all_process_definitions()
        
        for ws_id, ws in self.job_manager.production_line.workstations.items():
            process_def = process_defs.get(ws.process_id, {})
            
            # 获取当前工件的工序信息
            job_process_info = None
            if ws.current_job_id is not None:
                job = self.job_manager.get_job(ws.current_job_id)
                if job and job.current_process is not None:
                    job_process_info = job.get_process_info(job.current_process, process_defs)
            
            workstations_data.append({
                "id": ws_id,
                "process_id": ws.process_id,
                "process_name": process_def.get("name", f"工序{ws.process_id}") if process_def else f"工序{ws.process_id}",
                "process_color": self.PROCESS_COLORS.get(ws.process_id, "#6b7280"),
                "position": list(ws.position),
                "status": ws.status.value,
                "status_text": self._get_workstation_status_text(ws.status),
                "status_color": self._get_workstation_status_color(ws.status),
                "current_job_id": ws.current_job_id,
                "current_job_name": f"冰箱{ws.current_job_id + 1}" if ws.current_job_id is not None else None,
                "remaining_time": ws.remaining_time,
                "queue_size": len(ws.queue),
                "utilization": ws.utilization
            })
        
        return workstations_data
    
    def format_process_flow(self) -> List[Dict[str, Any]]:
        """格式化工序流程图数据"""
        flow = []
        
        for stage_id, process_ids in enumerate(self.job_manager.get_process_sequence()):
            stage_processes = []
            for pid in process_ids:
                stage_processes.append({
                    "id": pid,
                    "name": self.PROCESS_NAMES.get(pid, f"工序{pid}"),
                    "color": self.PROCESS_COLORS.get(pid, "#6b7280")
                })
            
            flow.append({
                "stage": stage_id,
                "processes": stage_processes,
                "is_parallel": len(process_ids) > 1
            })
        
        return flow
    
    def _generate_progress_bar(self, rate: float, length: int = 9) -> str:
        """生成ASCII进度条"""
        filled = int(rate * length)
        return "█" * filled + "░" * (length - filled)
    
    def _get_status_text(self, status: JobStatus) -> str:
        """获取作业状态文本"""
        texts = {
            JobStatus.WAITING: "等待中",
            JobStatus.PROCESSING: "加工中",
            JobStatus.WAITING_MATERIAL: "等待物料",
            JobStatus.COMPLETED: "已完成",
            JobStatus.BLOCKED: "被阻塞"
        }
        return texts.get(status, str(status))
    
    def _get_status_color(self, status: JobStatus) -> str:
        """获取作业状态颜色"""
        colors = {
            JobStatus.WAITING: "#6b7280",
            JobStatus.PROCESSING: "#3b82f6",
            JobStatus.WAITING_MATERIAL: "#f59e0b",
            JobStatus.COMPLETED: "#22c55e",
            JobStatus.BLOCKED: "#ef4444"
        }
        return colors.get(status, "#6b7280")
    
    def _get_workstation_status_text(self, status) -> str:
        """获取工位状态文本"""
        from utils.production_line import WorkstationStatus
        texts = {
            WorkstationStatus.IDLE: "空闲",
            WorkstationStatus.BUSY: "工作中",
            WorkstationStatus.BLOCKED: "等待物料",
            WorkstationStatus.MAINTENANCE: "维护中"
        }
        return texts.get(status, "未知")
    
    def _get_workstation_status_color(self, status) -> str:
        """获取工位状态颜色"""
        from utils.production_line import WorkstationStatus
        colors = {
            WorkstationStatus.IDLE: "#6b7280",
            WorkstationStatus.BUSY: "#22c55e",
            WorkstationStatus.BLOCKED: "#f59e0b",
            WorkstationStatus.MAINTENANCE: "#8b5cf6"
        }
        return colors.get(status, "#6b7280")
