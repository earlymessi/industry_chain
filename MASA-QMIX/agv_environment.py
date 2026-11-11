"""
AGV调度环境
负责物料运输和配送的MARL环境
"""

import numpy as np
import gym
from gym import spaces
from gym.utils import seeding
import math
from utils.agv import AGVFleet, AGVTask, AGVStatus
from utils.material import MaterialManager, MaterialDemand, MaterialType, MaterialStatus
from utils.site import Sites
import copy


class AGVScheduleEnv(gym.Env):
    """AGV调度环境"""

    environment_name = "AGV Material Transport"

    def __init__(self, n_agvs=4, max_steps=200):
        self.n_agvs = n_agvs
        self.max_steps = max_steps

        # 初始化组件
        self.agv_fleet = AGVFleet(n_agvs)
        self.material_manager = MaterialManager()
        self.sites_obj = Sites()
        self.sites = self.sites_obj.sites_object_list

        # 环境状态
        self.current_step = 0
        self.done = False
        self.episode_time = 0
        self.total_transport_time = 0

        # 任务管理
        self.pending_tasks = []
        self.completed_tasks = []
        self.task_counter = 0

        # 性能指标
        self.total_delays = 0
        self.on_time_deliveries = 0

        # 动作空间：每个AGV可以选择的任务或空闲
        # 0: 空闲, 1-n: 分配给对应任务
        # 设定一个保守的最大待处理任务数（包含空闲动作）
        self.max_pending_tasks = 21
        self.action_space = spaces.MultiDiscrete([self.max_pending_tasks] * n_agvs)

        # 状态空间设计
        # 包含：AGV状态、物料需求状态、任务状态
        obs_dim = self._calculate_obs_dim()
        self.observation_space = spaces.Box(low=0, high=1, shape=(obs_dim,), dtype=np.float32)

        # 随机数种子
        self.np_random = None

        print(f"AGV Environment initialized with {n_agvs} AGVs")

    def _calculate_obs_dim(self):
        """计算观测空间维度"""
        # AGV状态：每个AGV的位置(2) + 状态(1) + 载重(1) + 电量(1) + 货物类型数(9)
        agv_dim = self.n_agvs * (2 + 1 + 1 + 1 + 9)

        # 物料需求状态：每个站点每个物料类型的状态(1)
        demand_dim = len(self.sites) * len(MaterialType)

        # 任务队列状态：待处理任务数 + 平均等待时间
        task_dim = 2

        return agv_dim + demand_dim + task_dim

    def seed(self, seed=None):
        """设置随机种子"""
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def reset(self):
        """重置环境"""
        # 重置所有组件
        self.agv_fleet = AGVFleet(self.n_agvs)
        self.material_manager = MaterialManager()
        self.current_step = 0
        self.done = False
        self.episode_time = 0
        self.total_transport_time = 0
        self.pending_tasks = []
        self.completed_tasks = []
        self.total_delays = 0
        self.on_time_deliveries = 0

        # 生成初始物料需求
        self._generate_initial_demands()

        return self._get_observation()

    def _generate_initial_demands(self):
        """生成初始物料需求"""
        # 为每个站点生成一些初始需求
        for site in self.sites[:6]:  # 前6个站点
            for material_type in MaterialType:
                if self.np_random.random() < 0.3:  # 30%概率有需求
                    quantity = self.np_random.integers(1, 5)
                    demand = MaterialDemand(site.site_id, material_type, quantity)
                    self.material_manager.add_demand(demand)

                    # 创建对应的运输任务
                    storage = self.material_manager.find_nearest_storage(site.site_id)
                    if storage:
                        task = self.agv_fleet.create_transport_task(
                            storage, site, material_type, quantity
                        )
                        self.pending_tasks.append(task)

    def step(self, actions):
        """执行一步"""
        self.current_step += 1
        self.episode_time += 1

        rewards = [0.0] * self.n_agvs
        task_assignments = []

        # 处理智能体动作
        for agv_id, action in enumerate(actions):
            if action == 0:  # 空闲
                continue
            elif action <= len(self.pending_tasks):
                task_idx = action - 1
                if task_idx < len(self.pending_tasks):
                    task = self.pending_tasks[task_idx]
                    if task.status == 'pending':
                        task_assignments.append((agv_id, task))

        # 执行任务分配
        for agv_id, task in task_assignments:
            success = self.agv_fleet.agvs[agv_id].assign_task(task)
            if success:
                try:
                    self.pending_tasks.remove(task)
                except ValueError:
                    # 任务可能已被其他AGV抢占并移除，忽略该错误
                    pass
                rewards[agv_id] += 0.5  # 分配成功奖励

        # 更新AGV状态
        self.agv_fleet.update_all_agvs()

        # 检查任务完成
        completed_tasks = []
        for agv in self.agv_fleet.agvs:
            if agv.current_task and agv.current_task.status == 'completed':
                completed_tasks.append(agv.current_task)
                agv.current_task = None

        # 处理完成的任务
        for task in completed_tasks:
            self.completed_tasks.append(task)
            self.total_transport_time += (task.end_time - task.start_time)

            # 找到对应的需求并标记完成
            for demand in self.material_manager.demands:
                if (demand.site_id == task.target_site.site_id and
                    demand.material_type == task.material_type and
                    demand.quantity == task.quantity):
                    demand.mark_fulfilled()
                    break

            # 奖励所有相关AGV
            for i, agv in enumerate(self.agv_fleet.agvs):
                if agv.agv_id == task.assigned_agv:
                    rewards[i] += 1.0  # 任务完成奖励

        # 生成新的物料需求
        self._generate_new_demands()

        # 计算全局奖励
        fleet_status = self.agv_fleet.get_fleet_status()
        utilization_reward = fleet_status['busy_agvs'] / max(1, fleet_status['total_agvs']) * 0.1

        # 物料充足性奖励
        material_status = self.material_manager.get_material_status_overview()
        material_reward = sum(1 for status in material_status.values()
                            if status['status'].value == 0) * 0.05  # SUFFICIENT状态

        global_reward = utilization_reward + material_reward

        # 检查终止条件
        if self.current_step >= self.max_steps:
            self.done = True

        # 记录时间戳
        for task in self.pending_tasks:
            task.end_time = self.episode_time

        return self._get_observation(), global_reward, self.done, {
            'rewards': rewards,
            'fleet_status': fleet_status,
            'material_status': material_status,
            'pending_tasks': len(self.pending_tasks),
            'completed_tasks': len(self.completed_tasks)
        }

    def _generate_new_demands(self):
        """生成新的物料需求"""
        if self.np_random.random() < 0.2:  # 20%概率生成新需求
            site = self.np_random.choice(self.sites)
            material_type = self.np_random.choice(list(MaterialType))
            quantity = self.np_random.integers(1, 3)

            demand = MaterialDemand(site.site_id, material_type, quantity)
            self.material_manager.add_demand(demand)

            # 创建运输任务
            storage = self.material_manager.find_nearest_storage(site.site_id)
            if storage:
                task = self.agv_fleet.create_transport_task(
                    storage, site, material_type, quantity
                )
                self.pending_tasks.append(task)

    def _get_observation(self):
        """获取观测状态"""
        obs = []

        # AGV状态
        for agv in self.agv_fleet.agvs:
            agv_state = agv.get_state()
            obs.extend([
                agv_state['position'][0] / 50.0,  # 归一化位置
                agv_state['position'][1] / 50.0,
                agv_state['status'] / len(AGVStatus),  # 状态归一化
                agv_state['current_load'] / agv.max_capacity,  # 载重比例
                agv_state['battery_level'] / 100.0,  # 电量比例
            ])
            # 货物状态（9种物料类型）
            for material_type in MaterialType:
                obs.append(agv_state['cargo'].get(material_type, 0) / agv.max_capacity)

        # 物料需求状态
        # 物料需求状态：用 MaterialStatus 枚举的 value 做归一化
        status_overview = self.material_manager.get_material_status_overview()
        denom = max(1, len(MaterialStatus))
        for site in self.sites:
            for material_type in MaterialType:
                status_entry = status_overview.get(material_type, {'status': MaterialStatus.SUFFICIENT})
                status_enum = status_entry.get('status', MaterialStatus.SUFFICIENT)
                # 如果返回的是枚举则取 value，否则尝试转换为 int
                status_value = status_enum.value if hasattr(status_enum, 'value') else int(status_enum)
                obs.append(status_value / denom)

        # 任务队列状态
        obs.extend([
            len(self.pending_tasks) / 20.0,  # 归一化待处理任务数
            min(1.0, self.episode_time / 100.0)  # 时间进度
        ])

        return np.array(obs, dtype=np.float32)

    def get_avail_agent_actions(self, agent_id):
        """获取智能体的可用动作
        
        返回长度为 max_pending_tasks 的列表：
        - 索引 0: 空闲动作（始终可用）
        - 索引 1 到 n: 对应待处理任务的分配动作
        """
        avail_actions = []
        
        # 动作0: 空闲（总是可用）
        avail_actions.append(1)
        
        # 动作1到max_pending_tasks-1: 分配给对应任务
        agv = self.agv_fleet.agvs[agent_id]
        for i in range(self.max_pending_tasks - 1):
            task_idx = i
            if task_idx < len(self.pending_tasks):
                task = self.pending_tasks[task_idx]
                # 只有空闲且不需要充电的AGV才能接收任务
                if agv.status == AGVStatus.IDLE and not agv.needs_charging() and task.status == 'pending':
                    avail_actions.append(1)
                else:
                    avail_actions.append(0)
            else:
                # 没有对应任务时该动作不可用
                avail_actions.append(0)
        
        return avail_actions

    def get_state(self):
        """获取全局状态"""
        return self._get_observation()

    def get_obs(self):
        """获取所有智能体的观测"""
        return [self._get_observation()] * self.n_agvs  # 目前所有AGV共享相同观测

    def get_obs_agent(self, agent_id):
        """获取单个智能体的观测"""
        return self._get_observation()

    def get_env_info(self):
        """获取环境信息"""
        # n_actions 是每个智能体的动作候选数（包含空闲）
        # 使用 max_pending_tasks 作为保守上界，确保 Runner 初始化不会因为动作数太小而失败
        return {
            "n_actions": self.max_pending_tasks,
            "n_agents": self.n_agvs,
            "state_shape": len(self.get_state()),
            "obs_shape": len(self.get_obs()[0]),
            "episode_limit": self.max_steps
        }

    def render(self, mode='human'):
        """渲染环境状态"""
        fleet_status = self.agv_fleet.get_fleet_status()
        print(f"Step: {self.current_step}")
        print(f"AGVs - Idle: {fleet_status['idle_agvs']}, Busy: {fleet_status['busy_agvs']}")
        print(f"Tasks - Pending: {len(self.pending_tasks)}, Completed: {len(self.completed_tasks)}")
        print(f"Battery Level: {fleet_status['avg_battery']:.1f}%")

    def get_fleet_status(self):
        """获取车队状态（便捷方法，代理到agv_fleet）"""
        return self.agv_fleet.get_fleet_status()
    
    def get_agv_details(self):
        """获取所有AGV的详细信息列表"""
        details = []
        for agv in self.agv_fleet.agvs:
            details.append({
                'id': agv.agv_id,
                'name': f"AGV{agv.agv_id}",
                'type': agv.config.get('type', 'UNKNOWN'),
                'status': agv.status.name if hasattr(agv.status, 'name') else str(agv.status),
                'position': agv.position.tolist() if hasattr(agv.position, 'tolist') else list(agv.position),
                'battery_level': agv.battery_level,
                'current_load': agv.current_load,
                'max_capacity': agv.max_capacity,
                'max_speed': agv.max_speed,
                'total_tasks': agv.total_tasks,
                'successful_tasks': agv.successful_tasks,
                'failed_tasks': agv.failed_tasks,
                'total_distance': agv.total_distance,
                'current_material': str(agv.current_material_type) if agv.current_material_type else None,
                'current_task_id': agv.current_task.task_id if agv.current_task else None,
                'task_queue_size': len(agv.task_queue)
            })
        return details
    
    def get_transport_stats(self):
        """获取运输统计信息"""
        fleet_status = self.agv_fleet.get_fleet_status()
        return {
            'total_tasks_created': self.task_counter,
            'pending_tasks': len(self.pending_tasks),
            'completed_tasks': len(self.completed_tasks),
            'success_rate': fleet_status.get('successful_tasks', 0) / max(1, fleet_status.get('total_tasks', 1)),
            'avg_transport_time': self.total_transport_time / max(1, len(self.completed_tasks)),
            'on_time_delivery_rate': self.on_time_deliveries / max(1, len(self.completed_tasks)),
            'delay_count': self.total_delays
        }

    def close(self):
        """关闭环境"""
        pass
