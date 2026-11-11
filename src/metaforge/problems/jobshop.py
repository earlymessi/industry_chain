import numpy as np
import random
import math


class Task:
    def __init__(self, machine_id, duration, id=None, name=None, machine_options=None, machine_group=None, duration_by_machine=None):
        """
        工序类
        :param machine_id: 机器ID
        :param duration: 持续时间
        :param id: 工序在工件中的索引ID
        :param name: 工序名称 (如: "车削", "钻孔")
        """
        self.machine_id = machine_id
        self.duration = duration
        self.duration_by_machine = {int(k): float(v) for k, v in (duration_by_machine or {}).items()}
        self.id = id
        self.machine_group = machine_group
        self.machine_options = machine_options[:] if machine_options else (
            [machine_id] if machine_id is not None else []
        )
        # 如果没有提供名字，默认叫 "Op-{id}"
        self.name = name if name else f"Op-{id}" if id is not None else "Operation"

    def duration_on(self, machine_id):
        value = float(self.duration_by_machine.get(int(machine_id), self.duration))
        if not math.isfinite(value) or value < 0:
            raise ValueError("工序时间必须为有限非负数")
        return value

    def candidate_machines(self):
        """返回该工序可选机台列表（用于设备组/替代机台建模）。"""
        if self.machine_options:
            return list(dict.fromkeys(int(m) for m in self.machine_options if m is not None))
        if self.machine_id is None:
            return []
        return [int(self.machine_id)]

    def __repr__(self):
        return (
            f"Task(name={self.name}, machine={self.machine_id}, "
            f"options={self.machine_options}, duration={self.duration})"
        )


class Job:
    # [修改] 增加了 priority 参数，默认为 10
    def __init__(self, tasks, id=None, arrival_time=0, due_date=None, due_date_k_factor=2.5, priority=10):
        """
        工件类
        """
        self.tasks = tasks  # List[Task]
        self.id = id
        self.arrival_time = arrival_time
        self.priority = priority  # [新增] 存储优先级

        # 用户填写为显式交期；未填则在 problem_builder.refine_auto_due_dates 中按车间负载修正
        self.due_date_explicit = due_date is not None
        if due_date is not None:
            self.due_date = float(due_date)
        else:
            total_processing_time = sum(task.duration for task in self.tasks)
            self.due_date = self.arrival_time + total_processing_time * due_date_k_factor
            self.due_date_explicit = False

    def __len__(self):
        return len(self.tasks)

    def __repr__(self):
        return f"Job(id={self.id}, priority={self.priority}, tasks={self.tasks})"


class Machine:
    def __init__(self, id):
        self.id = id
        self.mode = 'normal'
        self.cost_rate_multiplier = {
            'normal': 1.0,
            'overtime': 1.5
        }
        self.calendar = []
        self.maintenance = []

    def get_current_cost_rate(self):
        return self.cost_rate_multiplier.get(self.mode, 1.0)

    def __repr__(self):
        return f"Machine(id={self.id})"


class JobShopProblem:
    """
    Job Shop 调度问题核心模型
    """

    def __init__(self, jobs, instance_name="Job Shop Instance", tardiness_penalty_per_unit=100,
                 overtime_cost_per_unit=10, initial_machine_ready=None):
        self.instance_name = instance_name
        self.jobs = jobs
        self.num_jobs = len(jobs)

        # 动态计算机器数量 (遍历所有工序找最大的机器ID)
        all_machine_ids = []
        for job in jobs:
            for task in job.tasks:
                all_machine_ids.extend(task.candidate_machines())
        self.num_machines = max(all_machine_ids) + 1 if all_machine_ids else 0
        self.machines = [Machine(i) for i in range(self.num_machines)]
        self.initial_machine_ready = [0.0] * self.num_machines
        if initial_machine_ready:
            for i in range(min(len(initial_machine_ready), self.num_machines)):
                self.initial_machine_ready[i] = float(initial_machine_ready[i])

        # 成本参数
        self.TARDINESS_PENALTY = tardiness_penalty_per_unit
        self.OVERTIME_COST = overtime_cost_per_unit

    @staticmethod
    def _select_machine_for_task(task, machine_ready_time, preferred_machine=None):
        """
        从候选机台中选择可最早开工的机台；若并列，优先 preferred_machine，再按机台 ID 升序。
        """
        candidates = task.candidate_machines()
        if not candidates:
            raise ValueError(f"Task has no available machine candidates: {task}")

        best_machine = candidates[0]
        best_ready = machine_ready_time[best_machine]
        for mid in candidates[1:]:
            ready = machine_ready_time[mid]
            if ready < best_ready:
                best_ready = ready
                best_machine = mid
            elif ready == best_ready:
                if preferred_machine is not None and mid == preferred_machine and best_machine != preferred_machine:
                    best_machine = mid
                elif mid < best_machine and best_machine != preferred_machine:
                    best_machine = mid
        return best_machine

    def _earliest_feasible_start(self, machine_id: int, earliest: float, duration: float = 0.0) -> float:
        """
        考虑机台 maintenance / calendar 停机窗口，返回不早于 earliest 的最早可开工时刻。
        窗口格式: {"start": float, "end": float}
        """
        t = float(earliest)
        if machine_id < 0 or machine_id >= self.num_machines:
            return t
        blocks = []
        machine = self.machines[machine_id]
        for key in ("maintenance", "calendar"):
            for block in getattr(machine, key, []) or []:
                if isinstance(block, dict):
                    blocks.append((float(block.get("start", 0)), float(block.get("end", 0))))
                elif isinstance(block, (list, tuple)) and len(block) >= 2:
                    blocks.append((float(block[0]), float(block[1])))
        if not blocks:
            return t
        blocks.sort(key=lambda x: x[0])
        changed = True
        while changed:
            changed = False
            for start, end in blocks:
                if end > start and ((start <= t < end) or (duration > 0 and t < end and t + duration > start)):
                    t = end
                    changed = True
        return t

    def iter_schedule(self, operation_order):
        """One timing decoder shared by search, displayed Gantt and metrics."""
        job_ptr = [0] * self.num_jobs
        machine_ready = self.initial_machine_ready[:]
        job_ready = [float(getattr(j, "arrival_time", 0) or 0) for j in self.jobs]
        for jid in operation_order:
            if not isinstance(jid, (int, np.integer)) or not 0 <= jid < self.num_jobs:
                raise ValueError("工序序列包含无效工单索引")
            job = self.jobs[jid]
            oid = job_ptr[jid]
            if oid >= len(job):
                continue
            task = job.tasks[oid]
            choices = []
            for mid in task.candidate_machines():
                if not 0 <= mid < self.num_machines:
                    raise ValueError("工序引用不存在的机台")
                duration = task.duration_on(mid)
                start = self._earliest_feasible_start(mid, max(machine_ready[mid], job_ready[jid]), duration)
                choices.append((start + duration, mid != task.machine_id, mid, start))
            if not choices:
                raise ValueError("工序没有可用候选机台")
            end, _, mid, start = min(choices)
            machine_ready[mid] = end
            job_ready[jid] = end
            job_ptr[jid] += 1
            yield {"job_id": int(jid), "priority": job.priority, "operation_id": oid,
                   "operation_name": task.name, "machine_id": mid,
                   "machine_options": task.candidate_machines(), "machine_group": task.machine_group,
                   "start": start, "end": end}

    def evaluate(self, operation_order):
        """
        计算 Makespan (最大完工时间)
        :param operation_order: 工件索引的序列 (e.g., [0, 1, 0, 2, ...])
        """
        return max((op["end"] for op in self.iter_schedule(operation_order)), default=0.0)

    def get_schedule(self, operation_order):
        """
        生成详细的调度时间表 (用于前端画甘特图)
        """
        return list(self.iter_schedule(operation_order))

    def generate_random_solution(self):
        """生成一个随机的可行解序列"""
        operation_order = []
        for job_id, job in enumerate(self.jobs):
            operation_order += [job_id] * len(job)
        random.shuffle(operation_order)
        return operation_order

    def perturb(self, operation_order):
        """邻域搜索：随机交换两个位置"""
        neighbor = operation_order[:]
        if len(neighbor) < 2:
            return neighbor
        i, j = random.sample(range(len(neighbor)), 2)
        neighbor[i], neighbor[j] = neighbor[j], neighbor[i]
        return neighbor

    def get_move(self, old_solution, new_solution):
        """(用于禁忌搜索) 识别两个解之间的差异 moves"""
        for i in range(len(old_solution)):
            if old_solution[i] != new_solution[i]:
                for j in range(i + 1, len(old_solution)):
                    if (old_solution[i] == new_solution[j] and
                            old_solution[j] == new_solution[i]):
                        return (i, j)
        return None
