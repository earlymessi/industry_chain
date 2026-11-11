import numpy
import numpy as np
from . import fuzzyEx
from . import Fuzzypenaltytime
from . import fuzzycom_min
def S2_besttime(G, timewindows, timespan, X,occupy,Re,Rd):
    """
    计算最佳配送时间区间并优化批次顺序
    Args:
        G (list): 三维列表[车辆][批次][节点信息]
        timewindows (np.array): 时间窗矩阵，形状为(N,2)
        timespan (dict): 计算两个节点间行程时间的函数
        X (dict): 获取服务时间的函数
        fuzzyEx (function): 模糊期望计算函数
        Fuzzypenaltytime (function): 模糊惩罚时间计算函数
        fuzzycom_min (function): 模糊数最小值比较函数
    Returns:
        tuple: (优化后的G, 最佳时间矩阵DBT)
    """
    V = len(G)  # 车辆数
    H=max(len(sub_list) for sub_list in G)
    # H = len(G[0]) if V > 0 else 0  # 最大批次数
    DBT = [[[] for _ in range(H)] for _ in range(V)]  # 初始化DBT

    for v in range(V):  # 遍历每辆车
        TDBT = np.array([], dtype=object).reshape(0, 2)
        # TDBT=np.zeros((H,2))影响后续行数计算
        # TDBT = []  # 临时存储时间区间数据
        valid_batches = []  # 记录有效批次索引

        for h in range(H):  # 遍历每个批次
            if h<=len(G[v])-1:  # 非空批次处理
            # if G[v][h] | | len(G[v]) - 1 < h:  # 非空批次处理

                # 深拷贝当前批次数据
                # M = [G[v][h]]
                M = np.array([G[v][h]])
                # M = [row.copy() for row in G[v][h]]
                new_rows=np.zeros((2,len(M[0])))
                M=np.vstack((M,new_rows))
                # ========== 时间节点计算 ==========
                for k in range(len(M[0])):  # 遍历每个节点

                    current_node = int(M[0][k])  # 当前节点编号

                    if k == 0:
                        # 第一个节点时间计算

                        service_time = fuzzyEx.fuzzy([X.get(current_node)],1)
                        #M[1][k] = timewindows[current_node - 1, 0] - service_time的-1去掉
                        # np.insert(M,timewindows[current_node , 0] - service_time)
                        # np.stack(M, timewindows[current_node , 1] - service_time)
                        M[1][k] = timewindows[current_node , 0] - service_time
                        M[2][k] = timewindows[current_node , 1] - service_time
                    else:
                        # 后续节点时间计算
                        M[1][k] = timewindows[current_node , 0]
                        # 累减前面所有行程时间
                        for z in range(k):
                            from_node = M[0][z]
                            to_node = M[0][z + 1]
                            tsp=timespan.get((from_node, to_node))
                            travel_time = fuzzyEx.fuzzy([tsp],1)
                            M[1][k] -= travel_time
                        # 减去第一个节点的服务时间
                        first_service = fuzzyEx.fuzzy([X.get(M[0][0])],1)
                        M[1][k] -= first_service
                        # 计算时间窗结束边界
                        M[2][k] = M[1][k] + (timewindows[current_node , 1] - timewindows[current_node , 0])
                        # M[2][k] = M[1][k] + (timewindows[current_node - 1, 1] - timewindows[current_node - 1, 0])

                # ========== 时间数据处理 ==========
                # 提取并处理时间节点
                time_matrix = np.array(M[1:])
                time_points = np.round(time_matrix.flatten(), 1)
                time_points = np.unique(time_points)
                time_points[time_points < 0] = 0  # 时间不早于0

                # time_points.sort()
                edtc =np.inf*np.ones((time_points.shape[0],3))
                # time_points = time_points.tolist()   ##变为列表##报错
                # ========== 惩罚时间计算 ==========
                min_penalty = float('inf')
                best_times = []

                # 遍历所有候选时间点
                for t in range(time_points.shape[0]):
                    # 计算当前时间点的惩罚
                    #数值有问题
                    edpc = Fuzzypenaltytime.fuzzy_penalty_time(G[v][h], time_points[t],timewindows,X, occupy, timespan, Re, Rd)  # 输入需要模糊数形式
                    edtc[t,:] = edpc
                    # 比较惩罚值
                    # current_penalty = fuzzycom_min.fuzzycom_min([edtc])[0]
                    #
                    # if current_penalty < min_penalty:
                    #     min_penalty = current_penalty
                    #     best_times = [t]
                    # elif current_penalty == min_penalty:
                    #     best_times.append(t)
                #最小值索引
                mini =fuzzycom_min.fuzzycom_min(edtc)#
                mini=np.array(mini,dtype=int)
                #最佳出发时间
                DBT[v][h] = time_points[mini]#出现超限报错
                #
                TDBT=np.vstack((TDBT,[DBT[v][h][0],DBT[v][h][len(DBT[v][h])-1]]))
                # TDBT.append([DBT[v][h][0],DBT[v][h][len(DBT[v][h])-1]])
                # TDBT[h][0] = DBT[v][h][0]
                # TDBT[h][1] = DBT[v][h][len(DBT[v][h])-1]
                # # 存储最佳时间（取第一个最小值）
                # DBT[v][h] = best_times
                # if best_times:
                #     TDBT.append({
                #         'start': min(best_times),
                #         'end': max(best_times),
                #         'original_index': h
                #     })
                # valid_batches.append(h)

        # ========== 批次顺序优化 ==========
        if TDBT.size!=0:
            # 多条件排序：先按最早时间，再按最晚时间
            index5 = np.lexsort((TDBT[:, 1], TDBT[:, 0]))
            # sorted_indices = np.lexsort(([t[1] for t in TDBT], [t[0] for t in TDBT]))

            # 重新排列批次顺序
            DBT[v] = [DBT[v][i] for i in index5]
            G[v] = [G[v][i] for i in index5]
            # # 按开始时间和结束时间排序
            # sorted_batches = sorted(TDBT, key=lambda x: (x['start'], x['end']))
            #
            # # 创建新顺序
            # new_order = [item['original_index'] for item in sorted_batches]
            #
            # # 重新排列G和DBT
            # new_G = [G[v][i] for i in new_order]
            # new_DBT = [DBT[v][i] for i in new_order]
            #
            # # 填充空位
            # for idx, h in enumerate(valid_batches):
            #     if idx < len(new_order):
            #         G[v][h] = new_G[idx]
            #         DBT[v][h] = new_DBT[idx]
            #     else:
            #         G[v][h] = []
            #         DBT[v][h] = []

    return G, DBT