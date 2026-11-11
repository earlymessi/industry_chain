import numpy as np
from . import S1_routing
from . import S2_besttime
from . import S3_groupDPtime
from . import S3_PLadjustment
from . import Fuzzypenaltytime
from . import fuzzyEx

# 字典提取函数
# def extract_column(data, i):
#     result = []
#     for key in data:
#         try:
#             value = data[key][i]
#             result.append(value)
#         except IndexError:
#             print(f"键 {key} 的列表长度小于 {i + 1}，无法提取第 {i + 1} 个元素。")
#     return result
def OP2(x,selectv,global_vars):
    """
    为加权惩罚时间最大的批次更换车辆编号

    参数:
        x (np.ndarray): 当前个体编码（车辆分配方案）
        selectv (list): 各零售商的可选车辆列表，selectv[retailer] = [可用车辆索引]
        S1_routing (function): 路径划分函数
        S2_besttime (function): 最佳配送时间计算函数
        S3_groupDPtime (function): 生产批次分组函数
        S3_PLadjustment (function): 生产调度调整函数
        Fuzzypenaltytime (function): 模糊惩罚时间计算函数
        fuzzyEx (function): 模糊评估函数

    返回:
        np.ndarray: 更新后的个体编码
    """
    #测试数据


    # 1. 初始化
    N = x.copy()  # 深拷贝原始解

    # 2. 路径划分与时间计算
    G = S1_routing.S1_routing(x, global_vars['timewindows'],  global_vars['vcapacity'],  global_vars['occupy'],  global_vars['timespan'],  global_vars['X'])
    G, DBT = S2_besttime.S2_besttime(G,  global_vars['timewindows'],  global_vars['timespan'],  global_vars['X'], global_vars['occupy'], global_vars['Re'], global_vars['Rd'])  # 假设返回格式为(G, DBT)

    # 3. 生产调度调整
    GDTW, GSI, GPT, GPN = S3_groupDPtime.S3_groupDPtime(G, DBT,  global_vars['produce'],  global_vars['timespan'],  global_vars['X'],  global_vars['takt'])
    GST, GFT, GDT, stockoccupy = S3_PLadjustment.S3_PLadjustment(G, GPT, GPN, GSI, GDTW, global_vars['pallet'])

    # 4. 计算各批次惩罚值
    batch_penalties = []
    for i in range(GST.shape[1]):
        nodes=GDTW['nodes'][i]
        depart_time=GDT['start'][i]
        # tempGDTW=extract_column(GDTW, i)
        # tempGDT=extract_column(GDT, i)
        edpc = Fuzzypenaltytime.fuzzy_penalty_time(nodes, [depart_time], global_vars['timewindows'], global_vars['X'],
                                                   global_vars['occupy'], global_vars['timespan'], global_vars['Re'],
                                                   global_vars['Rd'])
        # edpc=Fuzzypenaltytime.fuzzy_penalty_time(GDTW[1,i],GDT[1,i],global_vars['timewindows'],  global_vars['X'],  global_vars['occupy'],  global_vars['timespan'],  global_vars['Re'],  global_vars['Rd'])
        penalty = fuzzyEx.fuzzy([edpc], 1)
        batch_penalties.append(penalty)
    # for i in range(len(GDTW)):  # 遍历所有批次
    #     if not GDTW[i]:  # 跳过空批次
    #         continue
    #     # 计算模糊惩罚时间#这里的参数
    #     edpc = Fuzzypenaltytime.fuzzy_penalty_time(GDTW[i], GDT[i],  global_vars['timewindows'],  global_vars['X'],  global_vars['occupy'],  global_vars['timespan'],  global_vars['Re'],  global_vars['Rd'])
    #     # 模糊评估得到标量惩罚值
    #     penalty = fuzzyEx.fuzzy(edpc,1)
    #     batch_penalties.append(penalty)

    if not batch_penalties:
        return N  # 无有效批次时返回原解

    # 5. 选择惩罚最大的批次
    batch_select = np.argmax(batch_penalties)
    G_A = GDTW['nodes'][batch_select]  # 获取目标批次的零售商列表

    # 6. 随机更换车辆
    for retailer in G_A:
        # 获取该零售商可选车辆（注意索引转换）
        available_vehicles = selectv[retailer - 1]  # 假设selectv是0-based
        if not available_vehicles.size:
            continue
        # 随机选择新车辆（1-based编码）
        new_vehicle = np.random.choice(available_vehicles)
        # new_vehicle = np.random.choice(available_vehicles) + 1
        N[retailer - 1] = new_vehicle  # 更新编码

    return N

#
# # 测试用例
# if __name__ == "__main__":
#     # 假设参数（需根据实际函数实现调整）
#     x = np.array([1, 2, 1, 3])  # 4个零售商的车辆分配（1-based）
#     selectv = [
#         np.array([0, 1]),  # 零售商1可选车辆0,1（实际车辆编号1,2）
#         np.array([1, 2]),  # 零售商2可选车辆1,2
#         np.array([0]),  # 零售商3可选车辆0
#         np.array([2])  # 零售商4可选车辆2
#     ]
#
#
#     # 模拟依赖函数（需根据实际实现修改）
#     def mock_S1_routing(x):
#         # 返回示例路径结构
#         return [[[1, 2]], [[3]], [[4]]]
#
#
#     def mock_S2_besttime(G):
#         # 返回示例时间数据
#         DBT = [[8.5], [9.0], [10.0]]
#         return G, DBT
#
#
#     def mock_S3_groupDPtime(G, DBT):
#         # 返回示例分组数据
#         return ([[1, 2], [3], [4]], [], [], [])
#
#
#     def mock_S3_PLadjustment(*args):
#         # 返回示例调度数据
#         return (None, None, [[10.0], [11.0], [12.0]], None)
#
#
#     def mock_Fuzzypenaltytime(batch, times):
#         # 返回示例惩罚值
#         return [5.0, 3.0, 7.0]  # 对应三个批次
#
#
#     def mock_fuzzyEx(penalties):
#         # 返回最大惩罚值
#         return max(penalties)
#
#
#     # 执行函数
#     new_x = OP2(
#         x, selectv,
#         mock_S1_routing, mock_S2_besttime,
#         mock_S3_groupDPtime, mock_S3_PLadjustment,
#         mock_Fuzzypenaltytime, mock_fuzzyEx
#     )
#
#     print("原始编码:", x)
#     print("更新编码:", new_x)