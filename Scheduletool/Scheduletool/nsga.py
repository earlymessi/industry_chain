import numpy as np
import matplotlib.pyplot as plt


# ================== 基础数据结构定义 ==================
class Individual:
    def __init__(self):
        self.variables = []  # 决策变量
        self.objectives = []  # 目标函数值
        self.rank = None  # 前沿等级
        self.crowding_distance = 0.0  # 拥挤度距离


# ================== NSGA-II 核心函数 ==================
def nsga2(pop_size=500, generations=50, var_num=2, obj_num=2,
          var_range=(-5, 5), crossover_prob=0.9, mutation_prob=0.1, eta=20):
    """
    NSGA-II主函数
    参数：
        pop_size: 种群大小
        generations: 迭代次数
        var_num: 变量维度
        obj_num: 目标数量
        var_range: 变量范围
    """

    # ----------------- 初始化种群 -----------------
    population = [Individual() for _ in range(pop_size)]
    for ind in population:
        ind.variables = np.random.uniform(var_range[0], var_range[1], var_num)
        ind.objectives = evaluate(ind.variables)  # 目标函数评估

    # ----------------- 进化循环 -----------------
    for gen in range(generations):
        # 生成子代
        offspring = []
        for _ in range(pop_size // 2):
            # 选择父代
            parent1 = tournament_selection(population)
            parent2 = tournament_selection(population)

            # 交叉和变异
            child1, child2 = sbx_crossover(parent1, parent2, crossover_prob, eta, var_range)
            child1 = polynomial_mutation(child1, mutation_prob, eta, var_range)
            child2 = polynomial_mutation(child2, mutation_prob, eta, var_range)

            # 评估子代
            child1.objectives = evaluate(child1.variables)
            child2.objectives = evaluate(child2.variables)
            offspring.extend([child1, child2])

        # 合并父代和子代
        combined_pop = population + offspring

        # 非支配排序
        fronts = fast_non_dominated_sort(combined_pop)

        # 构建新种群
        new_pop = []
        front_index = 0
        while len(new_pop) + len(fronts[front_index]) <= pop_size:
            new_pop.extend(fronts[front_index])
            front_index += 1

        # 填充剩余空间（使用拥挤度距离）
        if len(new_pop) < pop_size:
            remaining = pop_size - len(new_pop)
            fronts[front_index].sort(key=lambda x: x.crowding_distance, reverse=True)
            new_pop.extend(fronts[front_index][:remaining])

        population = new_pop

    return population


# ================== 关键操作函数 ==================
def evaluate(x):
    """ 目标函数示例：ZDT1测试函数 """
    f1 = x[0]
    g = 1 + 9 * np.sum(x[1:]) / (len(x) - 1)
    f2 = g * (1 - np.sqrt(f1 / g))
    return [f1, f2]


def fast_non_dominated_sort(population):
    """ 快速非支配排序 """
    fronts = [[]]
    for ind in population:
        ind.domination_count = 0
        ind.dominated_set = []
        for other in population:
            if dominates(ind, other):
                ind.dominated_set.append(other)
            elif dominates(other, ind):
                ind.domination_count += 1
        if ind.domination_count == 0:
            ind.rank = 0
            fronts[0].append(ind)

    i = 0
    while fronts[i]:
        next_front = []
        for ind in fronts[i]:
            for dominated_ind in ind.dominated_set:
                dominated_ind.domination_count -= 1
                if dominated_ind.domination_count == 0:
                    dominated_ind.rank = i + 1
                    next_front.append(dominated_ind)
        i += 1
        fronts.append(next_front)

    return fronts[:-1]


def dominates(a, b):
    """ 判断个体a是否支配个体b """
    cond1 = all(a_obj <= b_obj for a_obj, b_obj in zip(a.objectives, b.objectives))
    cond2 = any(a_obj < b_obj for a_obj, b_obj in zip(a.objectives, b.objectives))
    return cond1 and cond2


def crowding_distance_assignment(front):
    """ 拥挤度距离计算 """
    obj_num = len(front[0].objectives)
    for ind in front:
        ind.crowding_distance = 0

    for i in range(obj_num):
        front.sort(key=lambda x: x.objectives[i])
        front[0].crowding_distance = front[-1].crowding_distance = float('inf')
        norm = front[-1].objectives[i] - front[0].objectives[i]
        for j in range(1, len(front) - 1):
            front[j].crowding_distance += (front[j + 1].objectives[i] - front[j - 1].objectives[i]) / norm


def tournament_selection(population, k=2):
    """ 二元锦标赛选择 """
    selected = np.random.choice(population, size=k)
    selected.sort(key=lambda x: (x.rank, -x.crowding_distance))
    return selected[0]


def sbx_crossover(p1, p2, pc, eta, var_range):
    """ 模拟二进制交叉 """
    c1, c2 = Individual(), Individual()
    for i in range(len(p1.variables)):
        if np.random.rand() < pc:
            x1 = min(p1.variables[i], p2.variables[i])
            x2 = max(p1.variables[i], p2.variables[i])
            beta = 1.0 + 2.0 * min((x1 - var_range[0]), (var_range[1] - x2)) / (x2 - x1)
            alpha = 2.0 - beta ** -(eta + 1)
            u = np.random.rand()
            if u <= 1.0 / alpha:
                beta_q = (u * alpha) ** (1.0 / (eta + 1))
            else:
                beta_q = (1.0 / (2.0 - u * alpha)) ** (1.0 / (eta + 1))
            c1_var = 0.5 * ((x1 + x2) - beta_q * (x2 - x1))
            c2_var = 0.5 * ((x1 + x2) + beta_q * (x2 - x1))
            c1.variables.append(np.clip(c1_var, var_range[0], var_range[1]))
            c2.variables.append(np.clip(c2_var, var_range[0], var_range[1]))
        else:
            c1.variables.append(p1.variables[i])
            c2.variables.append(p2.variables[i])
    return c1, c2


def polynomial_mutation(ind, pm, eta, var_range):
    """ 多项式变异 """
    mutated = Individual()
    mutated.variables = []
    for i in range(len(ind.variables)):
        if np.random.rand() < pm:
            x = ind.variables[i]
            delta1 = (x - var_range[0]) / (var_range[1] - var_range[0])
            delta2 = (var_range[1] - x) / (var_range[1] - var_range[0])
            u = np.random.rand()
            if u <= 0.5:
                delta = (2 * u) ** (1 / (eta + 1)) - 1
            else:
                delta = 1 - (2 * (1 - u)) ** (1 / (eta + 1))
            x_new = x + delta * (var_range[1] - var_range[0])
            mutated.variables.append(np.clip(x_new, var_range[0], var_range[1]))
        else:
            mutated.variables.append(ind.variables[i])
    return mutated


# ================== 运行与可视化 ==================
if __name__ == "__main__":
    final_pop = nsga2(pop_size=100, generations=100, var_num=30)

    # 绘制Pareto前沿
    objectives = np.array([ind.objectives for ind in final_pop])
    plt.scatter(objectives[:, 0], objectives[:, 1], c='red', s=30)
    plt.xlabel('Objective 1')
    plt.ylabel('Objective 2')
    plt.title('NSGA-II Pareto Front (ZDT1)')
    plt.show()