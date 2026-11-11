import numpy as np
from . import RouletteWheelSelection
from . import S1_routing
def OP1(x, selectv, global_vars):
    """
    基于负载率的车辆替换策略

    参数:
        x (np.ndarray): 当前个体编码
        selectv (list): 每个零售商的可选车辆列表，selectv[retailer] = [可用车辆索引]
        vcapacity (np.ndarray): 车辆容量数组，vcapacity[vehicle] = 容量
        occupy (np.ndarray): 各零售商的托盘占用量，occupy[retailer] = 占用量
        S1_routing (function): 路径划分函数，返回G[车辆][批次] = [零售商列表]
        RouletteWheelSelection (function): 轮盘赌选择函数

    返回:
        np.ndarray: 更新后的个体编码
    """
    # 初始化变量
    N = x.copy()  # 深拷贝原始解
    G = S1_routing.S1_routing(x, global_vars['timewindows'], global_vars['vcapacity'], global_vars['occupy'],global_vars['timespan'] ,global_vars['X'] )  # 获取路径划分结果
    V = len(G)  # 车辆数
    H = max(len(vehicle) for vehicle in G) if V > 0 else 0  # 最大批次数量
    occupy=global_vars['occupy']
    vcapacity=global_vars['vcapacity']
    # 计算各批次负载率
    GLR = []  # 存储批次信息，格式: [ (零售商列表, 负载率), ... ]
    for i in range(V):
        for j in range(len(G[i])):
            batch = G[i][j]
            if not batch:  # 跳过空批次
                continue
            # 计算当前批次总占用量
            total_occupy = sum(occupy[retailer - 1] for retailer in batch)  # 注意occupy是0-based
            # 计算负载率：总占用量 / 车辆容量
            load_ratio = total_occupy / vcapacity[i]
            GLR.append((batch, load_ratio))

    # 按负载率升序排序（负载率低的排在前面）
    GLR_sorted = sorted(GLR, key=lambda x: x[1])

    # 计算信用值（负载率越低，信用值越高）
    CV = []
    for idx, (_, lr) in enumerate(GLR_sorted):
        # 信用值公式：1 / (负载率 * (排名+1))，排名从1开始
        CV.append(1 / (lr * (idx + 1) + 1e-6))  # 加小量防止除零

    # 轮盘赌选择要替换的批次
    selected_idx = RouletteWheelSelection.RouletteWheelSelection(CV) - 1  # 转为0-based索引
    selected_batch = GLR_sorted[selected_idx][0]

    # 随机更换车辆
    for retailer in selected_batch:
        # 获取该零售商可用的车辆列表
        available_vehicles = selectv[retailer - 1]  # 注意selectv是0-based
        if available_vehicles.size == 0:
            continue
        # 随机选择一个可用车辆（1-based编码）
        new_vehicle = np.random.choice(available_vehicles)
        # new_vehicle = np.random.choice(available_vehicles) + 1  # 转为1-based
        N[retailer - 1] = new_vehicle  # 更新个体编码

    return N

#
# # 测试用例
# if __name__ == "__main__":
#     # 假设参数
#     x = np.array([1, 2, 1, 3])  # 个体编码（4个零售商分配的车辆）
#     selectv = [
#         np.array([0, 1]),  # 零售商1可选车辆0,1（0-based）
#         np.array([1, 2]),  # 零售商2可选车辆1,2
#         np.array([0]),  # 零售商3可选车辆0
#         np.array([2])  # 零售商4可选车辆2
#     ]
#     vcapacity = np.array([50, 100, 80])  # 车辆容量（0-based）
#     occupy = np.array([20, 30, 25, 40])  # 各零售商占用量（0-based）
#
#
#     # 模拟S1_routing函数（返回示例路径）
#     def mock_S1_routing(x):
#         # 假设路径划分结果：车辆0批次0包含零售商1、2；车辆2批次0包含零售商4
#         return [
#             [[1, 2]],  # 车辆0的批次
#             [],  # 车辆1无批次
#             [[4]]  # 车辆2的批次
#         ]
#
#
#     # 模拟轮盘赌函数（固定选择第一个）
#     def mock_RouletteWheelSelection(weights):
#         return 1  # 返回1-based索引
#
#
#     # 调用函数
#     new_x = OP1(x, selectv, vcapacity, occupy, mock_S1_routing, mock_RouletteWheelSelection)
#
#     print("原始编码:", x)
#     print("更新后编码:", new_x)