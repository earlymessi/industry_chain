import numpy as np
import random


def OP3(x, neighborhood_population, selectv, MNumber):
    """
    基于最少使用频率的车辆替换策略

    参数:
        x (np.ndarray): 当前个体编码（车辆分配方案），形状为(1, MNumber)
        neighborhood_population (np.ndarray): 邻域种群矩阵，每行代表一个个体
        selectv (list): 各零售商的可选车辆列表，selectv[retailer] = [可用车辆索引]
        MNumber (int): 零售商数量

    返回:
        np.ndarray: 更新后的个体编码
    """
    # 1. 初始化新个体
    N = x.copy()  # 深拷贝原始解

    # 2. 将当前个体加入邻域种群（注意MATLAB是行堆叠）
    neighborhood_population = np.vstack([neighborhood_population, N])

    # 3. 随机选择要修改的位置数量（至少修改30%的位置）
    min_sp = int(np.ceil(MNumber * 0.3))
    max_sp = MNumber - min_sp
    sp = random.randint(1, max_sp) + min_sp  # 保证sp在[min_sp, MNumber]之间

    # 4. 随机选择sp个不重复的零售商位置（0-based索引）
    Mob = random.sample(range(MNumber), sp)

    # 5. 对每个选中的位置进行车辆替换
    for k in Mob:
        # 获取该位置所有出现过的车辆（0-based）
        chuxian_v = np.unique(neighborhood_population[:, k])

        # 检查可选车辆是否未完全出现
        available_vehicles = selectv[k]  # 该位置实际可选的车辆（0-based）
        diffv = list(set(available_vehicles) - set(chuxian_v))

        if len(diffv) > 0:
            # 情况1：从未出现的车辆中随机选择
            new_vehicle = random.choice(diffv)
        else:
            # 情况2：统计出现次数，选择最少出现的车辆
            counts = np.bincount(neighborhood_population[:, k].astype(int))

            # 过滤无效计数（确保索引不超过实际车辆数）
            valid_counts = counts[:len(available_vehicles)]
            min_count = np.min(valid_counts)
            min_indices = np.where(valid_counts == min_count)[0]

            # 如果有多个最小值，随机选择
            selected_idx = random.choice(min_indices)
            new_vehicle = available_vehicles[selected_idx]

        # 更新编码（注意MATLAB是1-based，Python保持0-based）
        N[k] = new_vehicle
        # N[0, k] = new_vehicle

    return N


# 测试用例
if __name__ == "__main__":
    # 示例数据（假设MNumber=5，每个零售商可选车辆为[0,1,2]）
    x = np.array([[1, 1, 0, 2, 1]])  # 注意MATLAB是1-based，这里用0-based
    neighborhood_population = np.array([
        [1, 0, 2, 1, 0],
        [0, 1, 1, 2, 1]
    ])
    selectv = [
        [0, 1, 2], [0, 1, 2], [0, 1, 2], [0, 1, 2], [0, 1, 2]
    ]
    MNumber = 5

    new_x = OP3(x, neighborhood_population, selectv, MNumber)
    print("原始编码:", x)
    print("更新编码:", new_x)