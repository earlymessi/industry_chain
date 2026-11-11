import numpy as np
import random


def OP4(x, EP, selectv, MNumber):
    """
    基于外部种群的进化操作（两点交叉 + 多点变异）

    参数:
        x (np.ndarray): 当前个体编码，形状为(1, MNumber)
        EP (np.ndarray): 外部种群矩阵，形状为(nEP, MNumber)
        selectv (list): 每个位置的可选车辆列表，selectv[pos] = [可用车辆索引]
        MNumber (int): 编码长度（如零售商数量）

    返回:
        np.ndarray: 更新后的个体编码，形状为(1, MNumber)
    """
    # 1. 初始化新个体
    N = x.copy()

    # 2. 两点交叉 -----------------------------------------------------------
    # 随机选择一个精英个体（0-based索引）
    ep_idx = np.random.randint(0, EP.shape[0])

    # 生成两个不同的交叉点并排序（0-based索引）
    dian = random.sample(range(MNumber), 2)
    dian_1, dian_2 = sorted(dian)
    N=np.reshape(N, (1, MNumber))
    # 执行交叉（注意Python切片是左闭右开，需+1）
    N[0, dian_1:dian_2 + 1] = EP[ep_idx, dian_1:dian_2 + 1]

    # 3. 多点变异 -----------------------------------------------------------
    # 确定变异位置数量（至少变异1个位置）
    num_mutations = max(1, int(np.ceil(0.1 * MNumber)))
    mutation_positions = random.sample(range(MNumber), num_mutations)

    for pos in mutation_positions:
        # 获取当前车辆编码（0-based）
        current_vehicle = N[0, pos]

        # 获取可选车辆（排除当前车辆并保持顺序）
        available_vehicles = selectv[pos]
        selv = [v for v in available_vehicles if v != current_vehicle]

        # 如果有可选车辆，随机选择新车辆
        if selv:
            new_vehicle = random.choice(selv)
            N[0, pos] = new_vehicle
        # 若无可用车辆（理论上不应发生），保持原值

    return N


# 测试用例
if __name__ == "__main__":
    # 示例数据（假设MNumber=5，车辆编号为0-based）
    x = np.array([[1, 0, 2, 1, 3]])  # 当前个体
    EP = np.array([  # 外部种群
        [2, 1, 0, 3, 1],
        [1, 2, 1, 0, 2]
    ])
    selectv = [
        [0, 1, 2],  # 位置0可选车辆
        [0, 1, 2],  # 位置1
        [0, 1, 2],  # 位置2
        [0, 1, 2, 3],  # 位置3
        [1, 2, 3]  # 位置4
    ]
    MNumber = 5

    new_x = OP4(x, EP, selectv, MNumber)
    print("原始编码:", x)
    print("更新编码:", new_x)