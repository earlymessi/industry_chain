import numpy as np
from . import Fuzzypenaltytime

def objective(GST, GFT, GDT, GDTW, GSI, stockoccupy, produce, vfixcost, pc, holding, vvarcost,timewindows, X, occupy, timespan, Re, Rd):
    """计算多目标适应度值

    Args:
        GST (np.array): 生产开始时间矩阵[产线, 批次]
        GFT (np.array): 生产完成时间矩阵[产线, 批次]
        GDT (dict): 配送时间字典 {'start': [], 'end': []}
        GDTW (dict): 配送窗口数据字典
        GSI (np.array): 调度索引矩阵[车辆, 批次]
        stockoccupy (np.array): 库存占用量矩阵[产线, 批次]
        produce (np.array): 产品-产线矩阵
        vfixcost (np.array): 车辆固定成本数组
        pc (np.array): 单位生产成本数组
        holding (float): 单位库存持有成本
        vvarcost (np.array): 车辆可变成本函数
        Fuzzypenaltytime (function): 模糊惩罚时间计算函数

    Returns:
        dict: 包含两个目标的字典 {'cost': [c1,c2,c3], 'penalty': [p1,p2,p3]}
    """
    # ========== 初始化输出结构 ==========
    Z = {'cost': [0, 0, 0], 'penalty': [0, 0, 0]}

    # ========== 生产成本计算 ==========
    sum_number = np.sum(produce, axis=1)
    cost1 = np.dot(pc, sum_number)

    # ========== 库存成本计算 ==========
    R = GST.shape[1]
    PNumber = GST.shape[0]
    cost2 = np.zeros(3)

    for i in range(R):
        # 获取配送开始时间的模糊数
        start_time = GDT['start'][i]  # 假设为三元组[a,b,c]

        # 计算时间差 (GGDT - GFT)
        time_diff = np.array([start_time] * PNumber) - GFT[:, i].reshape(-1, 1)

        # 计算库存成本 (time_diff * stockoccupy * holding)
        batch_cost = np.sum(time_diff * stockoccupy[:, i].reshape(-1, 1), axis=0) * holding
        cost2 += batch_cost

    # ========== 车辆成本计算 ==========
    cost3 = np.zeros(3)
    vvcost = np.zeros(3)

    # 可变成本计算
    for i in range(R):
        vehicle_type = GDTW['vehicle'][i] - 1  # 转换为0-based索引
        transport_time = GDTW['transport_time'][i]
        vvcost += vvarcost[vehicle_type] * np.array(transport_time)

    # 固定成本计算
    vuse = GSI.shape[0]
    fixed_cost = 0
    for v in range(vuse):
        used_batches = np.count_nonzero(GSI[v, :])
        fixed_cost += used_batches * vfixcost[v]

    cost3 = fixed_cost + vvcost

    # ========== 惩罚时间计算 ==========
    total_penalty = np.zeros(3)
    for i in range(R):
        nodes = GDTW['nodes'][i]
        depart_time = GDT['start'][i]
        depart_time=np.array(depart_time)
        depart_time.reshape(1, 3)
        penalty = Fuzzypenaltytime.fuzzy_penalty_time(nodes, [depart_time], timewindows, X, occupy, timespan, Re, Rd)  # 假设返回三元组
        total_penalty += penalty

    # ========== 合并结果 ==========
    cost1_ary = np.full((1, 3), cost1)
    Z['cost'] = (cost1_ary + cost2 + cost3).tolist()
    # Z['cost'] = (np.array(cost1) + cost2 + cost3).tolist()
    Z['penalty'] = total_penalty.tolist()
    # z=[]
    # z.append(sum(Z['cost'][0]))
    # # z.append(sum(Z['penalty']))


    return Z
    # return z