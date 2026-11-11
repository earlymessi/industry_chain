import numpy as np
from . import fuzzymax
#需要关注GSI问题
def S3_PLadjustment(G, GPT, GPN, GSI, GDTW, pallet):
    """生产调度与时间调整

    Args:
        G (list): 三维列表[车辆][批次][节点信息]
        GPT (np.array): 生产时间矩阵[产线, 批次]
        GPN (np.array): 产品数量矩阵[产线, 批次]
        GSI (np.array): 调度索引矩阵[车辆, 批次]
        GDTW (dict): 配送时间窗口数据
        pallet (np.array): 托盘容量数组
        fuzzymax (function): 模糊数最大值函数

    Returns:
        tuple: (GST, GFT, GDT, stockoccupy)
    """
    # ========== 初始化生产时间 ==========
    PNumber, R = GPT.shape
    GFT = np.cumsum(GPT, axis=1)  # 累计生产完成时间
    GST = GFT - GPT  # 生产开始时间

    # ========== 初始化配送时间矩阵 ==========
    GDT = {
        'start': [[] for _ in range(R)],
        'end': [[] for _ in range(R)]
    }

    # ========== 正向调整配送时间 ==========
    V, H = GSI.shape
    for i in range(R):
        # 查找对应的车辆和批次
        row, col = np.where(GSI == (i + 1))  # GSI是MATLAB式1-based索引
        row = row[0]
        col = col[0]

        # 计算dep时间
        dep = max(np.max(GFT[:, i]), GDTW['end'][i])

        if col == 0:  # Python索引从0开始
            # 该车第一个批次
            GDT['start'][i] = [dep, dep, dep]
            GDT['end'][i] = [
                GDT['start'][i][0] + GDTW['transport_time'][i][0],
                GDT['start'][i][1] + GDTW['transport_time'][i][1],
                GDT['start'][i][2] + GDTW['transport_time'][i][2]
            ]
        else:
            # 需要比较前一巡回环的结束时间
            prev_batch = GSI[row, col - 1] - 1  # 转换为Python索引
            prev_end = GDT['end'][prev_batch]
            GDT['start'][i] = fuzzymax.fuzzymax([dep, dep, dep], prev_end)
            GDT['end'][i] = [
                GDT['start'][i][0] + GDTW['transport_time'][i][0],
                GDT['start'][i][1] + GDTW['transport_time'][i][1],
                GDT['start'][i][2] + GDTW['transport_time'][i][2]
            ]

    # ========== 逆序调整生产时间 ==========
    for i in range(R - 1, -1, -1):
        if i == R - 1:
            GFT[:, i] = GDT['start'][i][0]
            GST[:, i] = GFT[:, i] - GPT[:, i]
        else:
            adj = np.column_stack((GST[:, i + 1],
                                   [GDT['start'][i][0]] * PNumber))
            GFT[:, i] = np.min(adj, axis=1)
            GST[:, i] = GFT[:, i] - GPT[:, i]

    # ========== 压缩生产间隔策略 ==========
    bestTW_start = np.array(GDTW['start'])
    bestTW_end = np.array(GDTW['end'])
    if not np.all(bestTW_start == bestTW_end):
        for i in range(R):
            if i == 0:
                adj1 = np.max(GPT[:, i])
                dep = max(adj1, GDTW['start'][i])

                if i != R - 1:
                    dep1 = np.full(PNumber, dep)
                    GFT[:, i] = np.min(np.column_stack((dep1, GST[:, i + 1])), axis=1)
                else:
                    GFT[:, i] = dep
                GST[:, i] = GFT[:, i] - GPT[:, i]

                GDT['start'][i] = [dep, dep, dep]
                GDT['end'][i] = [
                    dep + GDTW['transport_time'][i][0],
                    dep + GDTW['transport_time'][i][1],
                    dep + GDTW['transport_time'][i][2]
                ]
            else:
                row, col = np.where(GSI == (i + 1))
                row = row[0]
                col = col[0]

                adj1 = np.max(GFT[:, i - 1] + GPT[:, i])

                if col == 0:
                    dep = max(adj1, GDTW['start'][i])
                    if i != R - 1:
                        dep1 = np.full(PNumber, dep)
                        GFT[:, i] = np.min(np.column_stack((dep1, GST[:, i + 1])), axis=1)
                    else:
                        GFT[:, i] = dep
                    GST[:, i] = GFT[:, i] - GPT[:, i]

                    GDT['start'][i] = [dep, dep, dep]
                    GDT['end'][i] = [
                        dep + GDTW['transport_time'][i][0],
                        dep + GDTW['transport_time'][i][1],
                        dep + GDTW['transport_time'][i][2]
                    ]
                else:
                    dep = max(adj1, GDTW['start'][i])
                    prev_batch = GSI[row, col - 1] - 1
                    prev_end = GDT['end'][prev_batch]
                    GDT['start'][i] = fuzzymax.fuzzymax([dep, dep, dep], prev_end)
                    GDT['end'][i] = [
                        GDT['start'][i][0] + GDTW['transport_time'][i][0],
                        GDT['start'][i][1] + GDTW['transport_time'][i][1],
                        GDT['start'][i][2] + GDTW['transport_time'][i][2]
                    ]

                    if i != R - 1:
                        for j in range(PNumber):
                            GFT[j, i] = min(GDT['start'][i][0], GST[j, i + 1])
                        GST[:, i] = GFT[:, i] - GPT[:, i]
                    else:
                        GFT[:, i] = GDT['start'][i][0]
                        GST[:, i] = GFT[:, i] - GPT[:, i]

    # ========== 计算库存占用 ==========
    stockoccupy = np.zeros((PNumber, R))
    for i in range(PNumber):
        stockoccupy[i, :] = GPN[i, :] * pallet[i]

    return GST, GFT, GDT, stockoccupy

#
# # 需要实现的辅助函数示例
# def fuzzymax(a, b):
#     """模糊数最大值比较（示例实现需完善）"""
#     # 此处应实现实际的模糊数比较逻辑
#     return [max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])]