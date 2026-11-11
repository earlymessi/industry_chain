"""
JIT物料配送调度器
核心逻辑：当某工序站的待处理工单进入"前序工序完成前5分钟"时，
系统触发AGV配送任务

配送优先级规则：
1. 高优先级：压缩机、发泡料（缺料导致工序完全停滞）
2. 中优先级：电气元件、钣金件
3. 低优先级：包装箱、护角等辅助物料
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from enum import Enum
from collections import deque

from utils.agv import AGVFleet, AGVTask, AGVStatus
from utils.material import MaterialManager, MaterialDemand, MaterialType, MaterialPriority
from utils.assembly_line import AssemblyLineLayout
from utils.refrigerator_process import RefrigeratorProcess, RefrigeratorOrder


class DeliveryStatus(Enum):
    """配送状态"""
    PENDING = "pending"       # 等待配送
    ASSIGNED = "assigned"     # 已分配AGV
    IN_TRANSIT = "in_transit"  # 运输中
    DELIVERED = "delivered"   # 已送达
    FAILED = "failed"         # 配送失败


class JITMaterialDispatcher:
    """JIT物料配送调度器
    
    核心功能：
    1. 监控各工位物料消耗情况
    2. 在工序开始前5分钟触发物料配送
    3. 根据物料类型选择合适的AGV
    4. 动态调整配送优先级
    """
    
    # JIT触发阈值（分钟）
    TRIGGER_BEFORE_COMPLETION = 5
    
    def __init__(self, agv_fleet: AGVFleet, material_manager: MaterialManager):
        self.agv_fleet = agv_fleet
        self.material_manager = material_manager
        self.layout = AssemblyLineLayout
        
        # 待配送任务队列
        self.pending_deliveries = []  # 待配送任务
        self.active_deliveries = {}   # 活跃配送任务 {task_id: task}
        self.completed_deliveries = []  # 已完成配送
        self.failed_deliveries = []   # 失败配送
        
        # 配送统计
        self.stats = {
            "total_deliveries": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "average_delivery_time": 0,
            "on_time_deliveries": 0
        }
        
        # 物料消耗速率估算（用于预测缺料时间）
        self.consumption_rates = {}  # {workstation_id: {material_name: rate}}
        
    def check_and_trigger_delivery(self, workstation_id: int, refrigerator: RefrigeratorOrder,
                                     current_time: float) -> List[AGVTask]:
        """
        检查并触发物料配送
        
        当工序即将开始且物料不足时，触发AGV配送
        
        Args:
            workstation_id: 工位ID
            refrigerator: 冰箱工单
            current_time: 当前时间
            
        Returns:
            触发的配送任务列表
        """
        triggered_tasks = []
        
        # 获取该工位对应的工序
        workstation = self.layout.get_workstation(workstation_id)
        if not workstation:
            return triggered_tasks
        
        process_id = workstation["process_id"]
        
        # 检查是否需要开始当前工序
        remaining_processes = refrigerator.get_remaining_processes()
        if process_id not in remaining_processes:
            return triggered_tasks
        
        # 获取该工序需要的物料
        process = RefrigeratorProcess.get_process(process_id)
        if not process:
            return triggered_tasks
        
        materials_needed = process["materials"]
        
        # 检查每种物料是否需要配送
        for material_name in materials_needed:
            material_type = MaterialType.get_by_name(material_name)
            if not material_type:
                continue
            
            # 检查缓存区物料是否充足
            buffer = self.layout.get_buffer(workstation_id)
            if not buffer:
                continue
            
            available = buffer.get_material_quantity(material_name)
            
            # 如果物料不足，触发配送
            if available < 2:  # 少于2个单位时触发
                # 估算需要的配送时间
                delivery_time = self.estimate_delivery_time(workstation_id, material_type)
                
                # 检查是否需要在TRIGGER_BEFORE_COMPLETION分钟内送达
                if delivery_time > self.TRIGGER_BEFORE_COMPLETION:
                    # 立即触发配送
                    task = self._create_delivery_task(
                        workstation_id, material_type, current_time
                    )
                    if task:
                        triggered_tasks.append(task)
                        self.pending_deliveries.append(task)
        
        return triggered_tasks
    
    def _create_delivery_task(self, workstation_id: int, material_type: MaterialType,
                               current_time: float, quantity: int = 5) -> Optional[AGVTask]:
        """创建配送任务"""
        # 获取物料优先级
        priority_value = MaterialPriority.get_by_material(material_type).value
        
        # 从仓库取货
        warehouse = self.material_manager.storages[0]  # 中央仓库
        
        # 获取目标缓存区
        target_buffer = self.layout.get_buffer(workstation_id)
        if not target_buffer:
            return None
        
        # 创建配送任务
        task = self.agv_fleet.create_delivery_task(
            source_storage=warehouse,
            target_buffer=target_buffer,
            material_type=material_type,
            quantity=quantity,
            priority=priority_value
        )
        
        # 设置预计送达时间
        delivery_time = self.estimate_delivery_time(workstation_id, material_type)
        task.estimated_duration = delivery_time
        
        return task
    
    def estimate_delivery_time(self, workstation_id: int, material_type: MaterialType) -> float:
        """估算配送时间（分钟）"""
        # 获取最近的有该物料的存储点
        source = self.material_manager.find_storage_for_material(material_type)
        if not source:
            source = self.material_manager.storages[0]
        
        # 获取目标缓存区
        target = self.layout.get_buffer(workstation_id)
        if not target:
            return float('inf')
        
        # 计算距离
        distance = np.linalg.norm(source.position - target.position)
        
        # 获取可用的AGV（选择最近的）
        available_agvs = self.agv_fleet.get_available_agvs_for_material(material_type)
        
        if not available_agvs:
            return float('inf')
        
        # 选择最近的AGV
        best_agv = min(available_agvs, key=lambda agv: np.linalg.norm(agv.position - source.position))
        
        # 估算时间 = 移动时间 + 装载时间 + 卸载时间
        agv_speed = best_agv.max_speed  # m/min
        load_time = best_agv.load_time
        unload_time = best_agv.unload_time
        
        # 移动时间（考虑AGV当前位置到仓库的距离）
        agv_to_source = np.linalg.norm(best_agv.position - source.position)
        source_to_target = distance
        
        move_time = agv_to_source / agv_speed + source_to_target / agv_speed
        
        return move_time + load_time + unload_time
    
    def assign_delivery_task(self, task: AGVTask) -> bool:
        """分配配送任务给AGV"""
        # 使用优先级分配
        success = self.agv_fleet.assign_task_with_priority(task)
        
        if success:
            task.status = DeliveryStatus.ASSIGNED.value
            if task.task_id in self.active_deliveries:
                del self.active_deliveries[task.task_id]
            self.active_deliveries[task.task_id] = task
            self.stats["total_deliveries"] += 1
        
        return success
    
    def update_delivery_status(self, current_time: float):
        """更新所有配送任务状态"""
        # 检查已完成的任务
        completed = []
        for task_id, task in self.active_deliveries.items():
            if task.status == 'completed':
                completed.append(task_id)
        
        for task_id in completed:
            task = self.active_deliveries.pop(task_id)
            self.completed_deliveries.append(task)
            self.stats["successful_deliveries"] += 1
            
            # 更新缓存区库存
            if task.target_site and hasattr(task.target_site, 'buffer_id'):
                buffer = self.layout.get_buffer(task.target_site.buffer_id)
                if buffer:
                    buffer.add_material(
                        MaterialType.get_name(task.material_type.value),
                        task.quantity
                    )
        
        # 检查超时的任务
        for task in self.pending_deliveries:
            if current_time - task.start_time > 30:  # 30分钟超时
                task.status = DeliveryStatus.FAILED.value
                self.failed_deliveries.append(task)
                self.stats["failed_deliveries"] += 1
        
        # 清理已完成和失败的任务
        self.pending_deliveries = [
            t for t in self.pending_deliveries 
            if t.status not in ['completed', 'failed']
        ]
    
    def get_pending_deliveries(self, priority: MaterialPriority = None) -> List[AGVTask]:
        """获取待配送任务（可按优先级过滤）"""
        if priority is None:
            return self.pending_deliveries.copy()
        
        return [
            t for t in self.pending_deliveries 
            if t.priority == priority.value
        ]
    
    def get_delivery_stats(self) -> Dict:
        """获取配送统计信息"""
        total = self.stats["total_deliveries"]
        successful = self.stats["successful_deliveries"]
        failed = self.stats["failed_deliveries"]
        
        return {
            "total_deliveries": total,
            "successful_deliveries": successful,
            "failed_deliveries": failed,
            "success_rate": successful / max(1, total) * 100,
            "pending_deliveries": len(self.pending_deliveries),
            "active_deliveries": len(self.active_deliveries),
            "completed_deliveries": len(self.completed_deliveries)
        }
    
    def get_material_status_for_workstation(self, workstation_id: int) -> Dict:
        """获取工位物料状态"""
        workstation = self.layout.get_workstation(workstation_id)
        if not workstation:
            return {}
        
        process_id = workstation["process_id"]
        process = RefrigeratorProcess.get_process(process_id)
        if not process:
            return {}
        
        buffer = self.layout.get_buffer(workstation_id)
        
        status = {
            "workstation_id": workstation_id,
            "workstation_name": workstation["name"],
            "process_id": process_id,
            "process_name": process["name"],
            "materials": {}
        }
        
        for material_name in process["materials"]:
            material_type = MaterialType.get_by_name(material_name)
            if not material_type:
                continue
            
            available = 0
            if buffer:
                available = buffer.get_material_quantity(material_name)
            
            # 预测缺料时间
            shortage_time = self.estimate_shortage_time(workstation_id, material_name)
            
            status["materials"][material_name] = {
                "available": available,
                "material_type": material_type.name,
                "priority": MaterialPriority.get_by_material(material_type).name,
                "estimated_shortage_time": shortage_time,
                "need_delivery": available < 2 and shortage_time < self.TRIGGER_BEFORE_COMPLETION
            }
        
        return status
    
    def estimate_shortage_time(self, workstation_id: int, material_name: str) -> float:
        """估算缺料时间（分钟）"""
        buffer = self.layout.get_buffer(workstation_id)
        if not buffer:
            return 0
        
        available = buffer.get_material_quantity(material_name)
        if available == 0:
            return 0
        
        # 使用默认消耗速率
        rate = self.consumption_rates.get(workstation_id, {}).get(material_name, 1.0/8.0)
        
        return available * rate  # 假设每8分钟消耗1个单位
    
    def update_consumption_rate(self, workstation_id: int, material_name: str, 
                                 consumption_time: float):
        """更新物料消耗速率"""
        if workstation_id not in self.consumption_rates:
            self.consumption_rates[workstation_id] = {}
        
        # 根据实际消耗时间更新速率
        self.consumption_rates[workstation_id][material_name] = 1.0 / max(0.1, consumption_time)


class DeliveryTaskManager:
    """配送任务管理器"""
    
    def __init__(self):
        self.tasks = {}  # {task_id: AGVTask}
        self.task_queue = deque()
        self.completed_tasks = []
        self.failed_tasks = []
    
    def add_task(self, task: AGVTask):
        """添加配送任务"""
        self.tasks[task.task_id] = task
        self.task_queue.append(task)
    
    def get_next_task(self, priority: int = None) -> Optional[AGVTask]:
        """获取下一个任务"""
        if not self.task_queue:
            return None
        
        if priority is None:
            return self.task_queue[0]
        
        # 按优先级查找
        for task in self.task_queue:
            if task.priority == priority:
                return task
        
        return self.task_queue[0]
    
    def complete_task(self, task_id: int):
        """完成任务"""
        if task_id in self.tasks:
            task = self.tasks.pop(task_id)
            self.completed_tasks.append(task)
            
            # 从队列中移除
            try:
                self.task_queue.remove(task)
            except ValueError:
                pass
    
    def fail_task(self, task_id: int, reason: str = ""):
        """标记任务失败"""
        if task_id in self.tasks:
            task = self.tasks.pop(task_id)
            task.status = DeliveryStatus.FAILED.value
            self.failed_tasks.append(task)
            
            try:
                self.task_queue.remove(task)
            except ValueError:
                pass
    
    def get_queue_status(self) -> Dict:
        """获取队列状态"""
        return {
            "queue_length": len(self.task_queue),
            "total_tasks": len(self.tasks),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "high_priority_count": sum(1 for t in self.task_queue if t.priority == 1),
            "medium_priority_count": sum(1 for t in self.task_queue if t.priority == 2),
            "low_priority_count": sum(1 for t in self.task_queue if t.priority == 3)
        }


# 便捷函数
def create_dispatcher(agv_fleet: AGVFleet, material_manager: MaterialManager) -> JITMaterialDispatcher:
    """创建JIT配送调度器"""
    return JITMaterialDispatcher(agv_fleet, material_manager)
