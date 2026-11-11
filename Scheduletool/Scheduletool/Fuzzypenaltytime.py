import numpy as np
# from dask.sizeof import sizeof
# from sqlalchemy import false
from . import fuzzy_superposition
def fuzzy_penalty_time(G, departure_time, timewindows, X, occupy, timespan, Re, Rd):
    """计算一个配送批次的模糊加权惩罚时间

    Args:
        G (list): 批次零售商序列，格式为[[node1, node2,...]]
        departure_time (np.array): 出发时间模糊数，如[a,b,c]
        timewindows (np.array): 时间窗矩阵，形状为(N,2)
        X (dict/list): 各节点的服务时间模糊数
        occupy (dict/list): 各节点的容量权重
        timespan (dict): 计算两节点间行程时间的函数
        Re (float): 提前到达惩罚系数
        Rd (float): 延迟到达惩罚系数
        fuzzy_superposition (function): 模糊叠加函数

    Returns:
        list: 累计惩罚时间模糊数，如[sum_a, sum_b, sum_c]
    """
    edpc = [0.0, 0.0, 0.0]  # 初始惩罚值
    if not G :
        return edpc
    if isinstance(departure_time, (int, float, bool, str, tuple)):
        departure_time=np.full((1,3), departure_time)
    num_retailers = len(G)
    current_nodes = G
    # current_nodes = G[0]  # 获取零售商序列，如[1,3,2]
    atime=[0,0,0]
    for j in range(num_retailers):
        node = current_nodes[j]  # 当前节点编号（MATLAB式1-based）

        # ========== 计算到达时间 ==========
        if j == 0:
            # 第一个节点：出发时间 + 服务时间
            service_time = X.get(node )
            # service_time = X.get([node - 1])  # X使用0-based索引
            atime = np.add(departure_time , service_time)
            # atime = [departure_time + service_time[i] for i in range(3)]
        else:
            # 后续节点：前个节点到达时间 + 行程时间
            from_node = current_nodes[j - 1]
            to_node = node
            travel_time = timespan.get((from_node, to_node))
            atime =np.add(atime,travel_time)
            # atime = [atime[i] + travel_time[i] for i in range(3)]

        # ========== 计算惩罚时间 ==========
        tw_start = timewindows[node , 0]
        tw_end = timewindows[node , 1]
        # tw_start = timewindows[node - 1, 0]
        # tw_end = timewindows[node - 1, 1]
        penalty = [0.0, 0.0, 0.0]

        for i in range(3):
            # 计算实际到达时间的偏离
            # actual_time = atime[i]
            actual_time = atime[0,i]
            clamped_time = min(tw_end, max(tw_start, actual_time))#min（时间窗末，max（时间窗起，实际到达时间））
            # clamped_time = min(tw_end, max(tw_start, tw_end))
            penalty[i] = actual_time - clamped_time  # <0提前，>0延迟

        # ========== 模糊叠加与加权 ==========
        super_penalty = fuzzy_superposition.fuzzy_superposition(penalty, 0, Re, Rd, 0)
        weight = occupy[node]  # occupy使用0-based索引

        # 累加惩罚值
        edpc = [edpc[i] + super_penalty[i] * weight for i in range(3)]

    return list(edpc)


# # 模糊叠加函数示例（需根据实际逻辑实现）
# def fuzzy_superposition(penalty, _, Re, Rd, __):
#     """模糊叠加操作（示例实现）
#
#     Args:
#         penalty (list): 惩罚时间三元组
#         Re (float): 提前惩罚系数
#         Rd (float): 延迟惩罚系数
#
#     Returns:
#         list: 叠加后的惩罚值
#     """
#     return [
#         penalty[0] * Rd if penalty[0] > 0 else abs(penalty[0]) * Re,
#         penalty[1] * Rd if penalty[1] > 0 else abs(penalty[1]) * Re,
#         penalty[2] * Rd if penalty[2] > 0 else abs(penalty[2]) * Re
#     ]