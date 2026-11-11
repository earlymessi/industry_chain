import numpy as np
from . import fuzzyEx
# from fuzzyEx import fuzzy  # 假设已实现模糊评估函数


# def S1_routing(individual, timewindows, vcapacity, occupy, timespan, X):
#     """
#     根据个体编码生成车辆的巡回路线（考虑容量和时间窗约束）
#
#     参数:
#         individual (np.ndarray): 个体编码，表示每个零售商的分配车辆（0-based索引）
#         timewindows (np.ndarray): 零售商时间窗矩阵，每行包含[最早时间, 最晚时间]
#         vcapacity (np.ndarray): 车辆容量数组，每个元素表示车辆的容量
#         occupy (np.ndarray): 各零售商的托盘占用量
#         timespan (dict): 字典，键为元组(i,j)，值为零售商i到j的模糊时间列表
#         X (dict): 字典，键为零售商编号，值为工厂到该零售商的模糊时间列表
#
#     返回:
#         list: 车辆的巡回路线表G，格式为G[车辆编号] = [环1, 环2, ...]，每个环是零售商的索引列表
#     """
#     VNumber = vcapacity.shape[0]
#     G = [[] for _ in range(VNumber)]  # 初始化车辆路线表
#     for k in range(VNumber):  # 0-based车辆索引
#         # 获取分配给当前车辆的所有零售商索引
#         temp = np.where(individual == k)[0].tolist()
#         if not temp:
#             continue
#
#         # 按时间窗排序：先按最晚时间升序，再按最早时间升序
#         st = timewindows[temp, :]
#         if len(temp) > 1:
#             # 获取排序索引（注意lexsort参数顺序）
#             sorted_indices = np.lexsort((st[:, 0], st[:, 1]))  # 先按第2列，再按第1列
#             temp_sorted = [temp[i] for i in sorted_indices]
#         else:
#             temp_sorted = temp.copy()
#
#         voccupy = 0  # 当前环累计占用量
#         h = 0  # 当前车辆的环计数器
#         L = 0  # 当前环的起始索引
#
#         for t in range(len(temp_sorted)):
#             current_retailer = temp_sorted[t]
#
#             # ========== 第一个零售商的特殊处理 ==========
#             if t == 0 and len(temp_sorted) > 1:
#                 voccupy += occupy[current_retailer]
#
#             # ========== 中间零售商处理逻辑 ==========
#             elif 0 < t < len(temp_sorted) - 1:
#                 voccupy += occupy[current_retailer]
#
#                 # 容量超限处理
#                 if voccupy > vcapacity[k]:
#                     G[k].append(temp_sorted[L:t])
#                     L = t
#                     h += 1
#                     voccupy = occupy[current_retailer]
#                 else:
#                     # 计算当前环的模糊时间
#                     vphtime = 0
#                     for m in range(L, t):
#                         vphtime +=timespan[temp(1,m),temp(1,m+1)]+vphtime
#                     vphtime +=timewindows[temp(1,L),2]+vphtime
#                     #     if m == L:
#                     #         # 工厂到第一个零售商的时间
#                     #         vphtime += timespan[temp(1,m),temp(1,m+1)]#X.get(temp_sorted[m], [0])[0]
#                     #     else:
#                     #         # 零售商间行驶时间
#                     #         vphtime +=timespan[temp(1,m),temp(1,m+1)] #timespan.get((temp_sorted[m - 1], temp_sorted[m]), [0])[0]
#                     # vphtime += timewindows[temp_sorted[L], 1]  # 最晚到达时间
#
#                     # 计算新环的模糊时间
#                     if t == L + 1:
#                         vnhtime = (timewindows[temp_sorted[L], 1] +
#                                    X.get(temp_sorted[L], [0])[0] +
#                                    X.get(temp_sorted[t], [0])[0])
#                     else:
#                         vnhtime = 0
#                         for m in range(L, t - 1):
#                             vnhtime += timespan.get(
#                                 (temp_sorted[m], temp_sorted[m + 1]), [0]
#                             )[0]
#                         vnhtime += (timewindows[temp_sorted[L], 1] +
#                                     X.get(temp_sorted[t - 1], [0])[0] +
#                                     X.get(temp_sorted[t], [0])[0])
#
#                     # 模糊时间评估
#                     if (fuzzyEx.fuzzy([vphtime]) < timewindows[current_retailer, 0]
#                             and(fuzzyEx.fuzzy([vnhtime]) < timewindows[current_retailer, 1])):
#                              G[k].append(temp_sorted[L:t])
#                              L = t
#                              h += 1
#                              voccupy = occupy[current_retailer]
#
#             # ========== 最后一个零售商处理 ==========
#             else:
#                 voccupy += occupy[current_retailer]
#                 if voccupy > vcapacity[k]:
#                     G[k].append(temp_sorted[L:t])
#                     G[k].append([current_retailer])
#                 else:
#                     G[k].append(temp_sorted[L:t + 1])
#
#                     # 清理空路线
#     G = [route for route in G if route]
#     return G
def S1_routing(individual, timewindows, vcapacity, occupy, timespan, X):
    """
    根据个体编码生成车辆的巡回路线（考虑容量和时间窗约束）

    参数:
        individual (np.ndarray): 个体编码，表示每个零售商的分配车辆（0-based索引）
        timewindows (np.ndarray): 零售商时间窗矩阵，每行包含[最早时间, 最晚时间]
        vcapacity (np.ndarray): 车辆容量数组，每个元素表示车辆的容量
        occupy (np.ndarray): 各零售商的托盘占用量
        timespan (dict): 字典，键为元组(i,j)，值为零售商i到j的模糊时间列表
        X (dict): 字典，键为零售商编号，值为工厂到该零售商的模糊时间列表

    返回:
        list: 车辆的巡回路线表G，格式为G[车辆编号] = [环1, 环2, ...]，每个环是零售商的索引列表
    """
    VNumber = vcapacity.shape[0]  # 车辆总数
    G = [[] for _ in range(VNumber)]  # 初始化巡回路线表

    for k in range(VNumber):
        # 找到分配给当前车辆的零售商索引（MATLAB的k+1对应Python的k）
        temp = np.where(individual == k)[0].tolist()  # 转换为列表以便索引操作
        # is_individual=individual == k
        # is_individual=np.where(is_individual)

        if not temp:  # 无零售商分配给该车辆
            continue

        # 按时间窗排序：先按终止升序，再按起始升序
        st = timewindows[temp, :]
        # 获取排序索引（注意np.lexsort的键顺序是逆序的）
        index2 = np.lexsort((st[:, 0], st[:, 1]))
        temp_sorted = [temp[i] for i in index2]  # 排序后的零售商索引

        voccupy = 0  # 当前巡回环的累计占用量
        L = 0  # 当前环的起始位置
        h = 0  # 当前车辆的环计数器

        for t in range(len(temp_sorted)):
            current_retailer = temp_sorted[t]#当前零售商

            # 处理第一个零售商（且总数量>1）
            if t == 0 and len(temp_sorted) > 1:
                voccupy += occupy[current_retailer]
            #基于第一个零售商计算的
            # 中间零售商处理逻辑
            elif 0 < t < len(temp_sorted) - 1:
                voccupy += occupy[current_retailer]

                # 容量超限，分割巡回环
                if voccupy > vcapacity[k]:
                    G[k].append(temp_sorted[L:t])
                    L = t
                    h += 1
                    voccupy = occupy[current_retailer]  # 重置负载
                else:
                    # 计算当前环的模糊时间
                    vphtime = np.zeros((1,3))
                    for m in range(L, t):#L到第t-1个零售商
                        sort=temp_sorted[m],temp_sorted[m+1]#变成字典的形状
                        # tsp=timespan.get((sort))
                        vphtime += timespan.get((sort))
                        # vphtime =[i +vphtime for i in timespan.get((sort))]######不断叠加
                        # vphtime =timewindows(temp(1,L),2)+vphtime
                        # if m == L:
                        #     vphtime += timespan.get(temp_sorted[m], temp_sorted[0])  # 工厂到第一个零售商的时间
                        # else:
                        #     vphtime += timespan.get((temp_sorted[m - 1], temp_sorted[m]), [0])

                    vphtime += timewindows[temp_sorted[L], 1]  # 加上最晚到达时间

                    # 计算新环的模糊时间
                    if t == L + 1:
                        twd=timewindows[temp_sorted[L], 1]
                        X_tp=np.array(X.get(temp_sorted[L]))+np.array(X.get(temp_sorted[t]))####有问题会报错###已处理
                        ####这里的temp_sorted[L]+1要不要+1
                        vnhtime= [[i +twd for i in X_tp]]#修改一下
                        # vnhtime = (timewindows[temp_sorted[L], 1] +
                        #            X.get(temp_sorted[L]) +
                        #            X.get(temp_sorted[t]))
                    else:
                        vnhtime =np.zeros((1,3))
                        for m in range(L, t - 1):
                            vnhtime += timespan.get((temp_sorted[m], temp_sorted[m + 1]))#int list 不断叠加
                        vnhtime += (timewindows[temp_sorted[L], 1] +
                                    X.get(temp_sorted[t - 1]) +
                                    X.get(temp_sorted[t]))

                    ############x的问题
                    # 模糊时间评估  ####这里大小
                    if (fuzzyEx.fuzzy(vphtime,1) < timewindows[current_retailer, 0] and
                            fuzzyEx.fuzzy(vnhtime,1) < timewindows[current_retailer, 1]):#出现[[]]情况
                        G[k].append(temp_sorted[L:t])
                        L = t
                        h += 1
                        voccupy = occupy[current_retailer]

            # 处理最后一个零售商
            else:
                voccupy += occupy[current_retailer]
                if voccupy > vcapacity[k]:
                    G[k].append(temp_sorted[L:t])
                    G[k].append([current_retailer])
                else:
                    G[k].append(temp_sorted[L:t + 1])

    # 清理空列表
    # G = [route for route in G if route]
    return G


# # 示例模糊评估函数（需根据实际逻辑完善）
# def fuzzy(fitness):
#     N = len(fitness)
#     if N == 0:
#         return []
#     M = len(fitness[0])
#     obj = []
#     if M == 1:
#         for i in range(N):
#             term = fitness[i][0]
#             val = (term[0] + 2 * term[1] + term[2]) / 4
#             obj.append(val)
#     else:
#         for i in range(N):
#             term1 = fitness[i][0]
#             term2 = fitness[i][1]
#             val1 = (term1[0] + 2 * term1[1] + term1[2]) / 4
#             val2 = (term2[0] + 2 * term2[1] + term2[2]) / 4
#             obj.append([val1, val2])
#     return obj
#
#
# # 测试用例
# if __name__ == "__main__":
#     # 构造测试数据
#     individual = np.array([0, 0, 1, 1, 2])  # 3辆车，零售商0-4的分配
#     timewindows = np.array([
#         [8, 12],  # 零售商0的时间窗
#         [9, 15],  # 零售商1
#         [10, 16],  # 零售商2
#         [7, 14],  # 零售商3
#         [11, 18]  # 零售商4
#     ])
#     vcapacity = np.array([50, 50, 50])  # 车辆容量
#     occupy = np.array([20, 30, 25, 35, 15])  # 各零售商占用量
#     timespan = {
#         (0, 1): [2], (1, 0): [2],
#         (1, 2): [3], (2, 1): [3],
#         (3, 4): [4], (4, 3): [4]
#     }
#     X = {
#         0: [5], 1: [6], 2: [7], 3: [4], 4: [5]
#     }
#
#     routes = S1_routing(individual, timewindows, vcapacity, occupy, timespan, X)
#     print("生成的巡回路线:")
#     for i, vehicle_routes in enumerate(routes):
#         print(f"车辆 {i}:")
#         for j, route in enumerate(vehicle_routes):
#             print(f"  环 {j + 1}: {route}")