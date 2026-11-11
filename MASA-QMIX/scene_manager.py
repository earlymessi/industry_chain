"""
场景管理器
负责协调AGV前序场景和冰箱组装主场景的运行
"""

import numpy as np
import threading
import time
import queue
from enum import Enum
from environment import ScheduleEnv
from agv_environment import AGVScheduleEnv
from utils.material import MaterialManager, MaterialDemand, MaterialType


class SceneMode(Enum):
    """场景运行模式"""
    SERIAL = 0      # 串行模式：先AGV准备，再冰箱组装
    PARALLEL = 1    # 并行模式：两个场景同时运行
    HYBRID = 2      # 混合模式：根据条件动态切换


class CommunicationChannel:
    """场景间通信通道"""

    def __init__(self):
        self.material_demands = queue.Queue()  # 物料需求队列
        self.material_supplies = queue.Queue()  # 物料供应队列
        self.control_signals = queue.Queue()   # 控制信号队列
        self.shared_state = {}  # 共享状态

    def send_material_demand(self, demand):
        """发送物料需求"""
        self.material_demands.put(demand)

    def receive_material_demand(self, timeout=1.0):
        """接收物料需求"""
        try:
            return self.material_demands.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_material_supply(self, supply_info):
        """发送物料供应信息"""
        self.material_supplies.put(supply_info)

    def receive_material_supply(self, timeout=1.0):
        """接收物料供应信息"""
        try:
            return self.material_supplies.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_control_signal(self, signal):
        """发送控制信号"""
        self.control_signals.put(signal)

    def receive_control_signal(self, timeout=1.0):
        """接收控制信号"""
        try:
            return self.control_signals.get(timeout=timeout)
        except queue.Empty:
            return None

    def update_shared_state(self, key, value):
        """更新共享状态"""
        self.shared_state[key] = value

    def get_shared_state(self, key, default=None):
        """获取共享状态"""
        return self.shared_state.get(key, default)


class SceneManager:
    """场景管理器"""

    def __init__(self, mode=None, n_agvs=4, n_assembly_agents=6):
        # 兼容传入 None 的情况，默认并行模式
        if mode is None:
            self.mode = SceneMode.PARALLEL
        elif isinstance(mode, SceneMode):
            self.mode = mode
        else:
            # 如果传入字符串或其他可解析的类型，尝试映射
            try:
                self.mode = SceneMode[mode] if isinstance(mode, str) and mode in SceneMode.__members__ else SceneMode.PARALLEL
            except Exception:
                self.mode = SceneMode.PARALLEL
        self.n_agvs = n_agvs
        self.n_assembly_agents = n_assembly_agents

        # 初始化环境
        self.agv_env = None
        self.assembly_env = None
        self.communication = CommunicationChannel()

        # 运行状态
        self.is_running = False
        self.threads = []
        self.episode_count = 0

        # 性能统计
        self.stats = {
            'total_episodes': 0,
            'assembly_completion_rate': [],
            'agv_utilization_rate': [],
            'material_shortage_events': 0,
            'average_setup_time': 0
        }

        # 物料管理集成
        self.material_manager = MaterialManager()

        # 使用 self.mode.name 打印，确保不会因为传入 None 导致异常
        print(f"Scene Manager initialized with mode: {self.mode.name}")

    def initialize_environments(self):
        """初始化两个环境"""
        try:
            self.agv_env = AGVScheduleEnv(n_agvs=self.n_agvs)
            self.assembly_env = ScheduleEnv(n_agents=self.n_assembly_agents)

            # 设置环境信息
            agv_info = self.agv_env.get_env_info()
            assembly_info = self.assembly_env.get_env_info()

            print("Environments initialized successfully")
            print(f"AGV Environment: {agv_info['n_agents']} agents, {agv_info['n_actions']} actions")
            print(f"Assembly Environment: {assembly_info['n_agents']} agents, {assembly_info['n_actions']} actions")

            return True
        except Exception as e:
            print(f"Failed to initialize environments: {e}")
            return False

    def run_serial_mode(self, max_episodes=10):
        """串行模式运行"""
        print("Starting Serial Mode...")

        for episode in range(max_episodes):
            print(f"\n--- Episode {episode + 1} ---")

            # Phase 1: AGV准备阶段
            print("Phase 1: AGV Material Preparation")
            agv_done = False
            agv_step = 0
            material_ready = False

            while not agv_done and agv_step < 100:  # 限制AGV准备时间
                agv_obs = self.agv_env.reset()
                agv_done = False

                while not agv_done and agv_step < 100:
                    # 简单的随机动作作为示例
                    agv_actions = [int(self.agv_env.np_random.integers(0, 2)) for _ in range(self.n_agvs)]
                    next_obs, agv_reward, agv_done, agv_info = self.agv_env.step(agv_actions)
                    agv_step += 1

                    # 检查物料准备状态
                    material_status = self.material_manager.get_material_status_overview()
                    sufficient_count = sum(1 for status in material_status.values()
                                         if status['status'].value == 0)  # SUFFICIENT

                    if sufficient_count >= 7:  # 大部分物料充足
                        material_ready = True
                        break

                if material_ready:
                    break

            print(f"AGV preparation completed in {agv_step} steps")

            # Phase 2: 冰箱组装阶段
            print("Phase 2: Assembly Process")
            assembly_obs = self.assembly_env.reset()
            assembly_done = False
            assembly_step = 0

            while not assembly_done:
                # 检查物料供应
                if self._check_material_availability():
                    # 随机动作作为示例
                    assembly_actions = [int(self.assembly_env.np_random.integers(0, 19))
                                      for _ in range(self.n_assembly_agents)]
                    next_obs, assembly_reward, assembly_done, assembly_info = \
                        self.assembly_env.step(assembly_actions)
                    assembly_step += 1
                else:
                    # 物料不足，等待AGV补充
                    print("Material shortage detected, waiting for AGV...")
                    time.sleep(0.1)  # 模拟等待
                    continue

            print(f"Assembly completed in {assembly_step} steps")

            # 记录统计
            self._update_statistics(episode, agv_info, assembly_info)

        print("Serial mode completed")

    def run_parallel_mode(self, max_episodes=10):
        """并行模式运行"""
        print("Starting Parallel Mode...")

        # 创建线程
        agv_thread = threading.Thread(target=self._run_agv_scene, args=(max_episodes,))
        assembly_thread = threading.Thread(target=self._run_assembly_scene, args=(max_episodes,))

        self.threads = [agv_thread, assembly_thread]
        self.is_running = True

        # 启动线程
        for thread in self.threads:
            thread.start()

        # 等待完成
        for thread in self.threads:
            thread.join()

        self.is_running = False
        print("Parallel mode completed")

    def _run_agv_scene(self, max_episodes):
        """运行AGV场景线程"""
        for episode in range(max_episodes):
            agv_obs = self.agv_env.reset()
            done = False
            step_count = 0

            while not done and self.is_running:
                # 处理来自冰箱组装场景的物料需求
                demand = self.communication.receive_material_demand(timeout=0.1)
                if demand:
                    self._process_material_demand(demand)

                # 执行AGV动作
                actions = self._generate_agv_actions()
                next_obs, reward, done, info = self.agv_env.step(actions)
                step_count += 1

                # 发送物料供应状态
                supply_info = {
                    'material_status': self.material_manager.get_material_status_overview(),
                    'agv_status': self.agv_env.agv_fleet.get_fleet_status()
                }
                self.communication.send_material_supply(supply_info)

                time.sleep(0.05)  # 控制执行速度

            print(f"AGV Episode {episode + 1} completed in {step_count} steps")

    def _run_assembly_scene(self, max_episodes):
        """运行冰箱组装场景线程"""
        for episode in range(max_episodes):
            assembly_obs = self.assembly_env.reset()
            done = False
            step_count = 0

            while not done and self.is_running:
                # 检查物料供应状态
                supply_info = self.communication.receive_material_supply(timeout=0.1)
                if supply_info:
                    material_available = self._check_material_from_supply(supply_info)
                    if not material_available:
                        # 发送物料需求
                        self._send_material_demand_to_agv()
                        time.sleep(0.1)  # 等待物料
                        continue

                # 执行组装动作
                actions = self._generate_assembly_actions()
                next_obs, reward, done, info = self.assembly_env.step(actions)
                step_count += 1

                time.sleep(0.05)  # 控制执行速度

            print(f"Assembly Episode {episode + 1} completed in {step_count} steps")

    def _process_material_demand(self, demand):
        """处理物料需求"""
        # 将需求添加到物料管理器
        self.material_manager.add_demand(demand)

        # 为AGV创建运输任务
        storage = self.material_manager.find_nearest_storage(demand.site_id)
        if storage:
            task = self.agv_env.agv_fleet.create_transport_task(
                storage,
                self.assembly_env.sites[demand.site_id],
                demand.material_type,
                demand.quantity
            )
            self.agv_env.pending_tasks.append(task)

    def _check_material_availability(self):
        """检查物料可用性"""
        # 简单的检查逻辑
        status_overview = self.material_manager.get_material_status_overview()
        critical_count = sum(1 for status in status_overview.values()
                           if status['status'].value >= 2)  # CRITICAL or OUT_OF_STOCK

        return critical_count == 0  # 没有严重缺货

    def _check_material_from_supply(self, supply_info):
        """从供应信息检查物料"""
        material_status = supply_info.get('material_status', {})
        critical_count = sum(1 for status in material_status.values()
                           if status['status'].value >= 2)

        return critical_count == 0

    def _send_material_demand_to_agv(self):
        """向AGV发送物料需求"""
        # 生成当前需要的物料需求
        for site in self.assembly_env.sites:
            for material_type in MaterialType:
                # 检查是否需要补充
                available, storage = self.material_manager.check_demand_fulfillment(
                    site.site_id, material_type, 1
                )
                if not available:
                    demand = MaterialDemand(site.site_id, material_type, 2)  # 请求2个单位
                    self.communication.send_material_demand(demand)

    def _generate_agv_actions(self):
        """生成AGV动作（简单策略）"""
        actions = []
        for i in range(self.n_agvs):
            if len(self.agv_env.pending_tasks) > 0:
                # 随机选择一个待处理任务
                # np.random.Generator.integers: high is exclusive, mirror randint behavior
                high = min(3, len(self.agv_env.pending_tasks) + 1)
                action = int(self.agv_env.np_random.integers(1, high))
            else:
                action = 0  # 空闲
            actions.append(action)
        return actions

    def _generate_assembly_actions(self):
        """生成组装动作（简单策略）"""
        actions = []
        for i in range(self.n_assembly_agents):
            # 随机动作，实际应该使用训练好的策略
            action = int(self.assembly_env.np_random.integers(0, 19))
            actions.append(action)
        return actions

    def _update_statistics(self, episode, agv_info, assembly_info):
        """更新统计信息"""
        self.stats['total_episodes'] = episode + 1

        # 组装完成率
        if 'episodes_situation' in assembly_info:
            completion_rate = len(assembly_info['episodes_situation']) / 100.0  # 简化计算
            self.stats['assembly_completion_rate'].append(completion_rate)

        # AGV利用率
        if 'fleet_status' in agv_info:
            utilization = agv_info['fleet_status']['busy_agvs'] / max(1, self.n_agvs)
            self.stats['agv_utilization_rate'].append(utilization)

    def get_statistics(self):
        """获取统计信息"""
        stats = self.stats.copy()
        if self.stats['assembly_completion_rate']:
            stats['avg_assembly_completion'] = np.mean(self.stats['assembly_completion_rate'])
        if self.stats['agv_utilization_rate']:
            stats['avg_agv_utilization'] = np.mean(self.stats['agv_utilization_rate'])

        return stats

    def run(self, max_episodes=10):
        """运行场景管理器"""
        if not self.initialize_environments():
            return False

        if self.mode == SceneMode.SERIAL:
            self.run_serial_mode(max_episodes)
        elif self.mode == SceneMode.PARALLEL:
            self.run_parallel_mode(max_episodes)
        else:
            print(f"Mode {self.mode} not implemented yet")
            return False

        return True

    def stop(self):
        """停止运行"""
        self.is_running = False
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=1.0)

    def __del__(self):
        """清理资源"""
        self.stop()
