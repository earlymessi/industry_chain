import numpy as np


def non_domination_sort_mod_min(x, M, V):
    """
    非支配排序与拥挤度计算（NSGA-II核心步骤）

    参数:
        x (np.ndarray): 输入矩阵，形状为(N, M + V + ?)，N为种群数量，前V列为决策变量，随后M列为目标函数值
        M (int): 目标函数数量
        V (int): 决策变量数量

    返回:
        np.ndarray: 排序后的矩阵，添加了前沿编号和拥挤度距离列
    """
    N = x.shape[0]
    x = np.hstack((x, np.zeros((N, 2))))  # 添加前沿编号和拥挤度列
    #这一步循环可以放到下一步支配关系内
    # 初始化个体数据结构
    individuals = []
    for i in range(N):
        individuals.append({'n': 0, 'p': []})#n:支配个体i的数量;p:支配个体i的支配列表

    # ------------------------- 非支配排序 -------------------------
    fronts = [[]]  # 前沿列表，fronts[0]为第一前沿

    # 计算支配关系
    for i in range(N):
        for j in range(N):#遍历i,j比较个体i,j支配关系
            #这里有没有存在必要 自己和自己不需比较
            if i == j:
                continue
            # 比较目标值（假设均为最小化）
            dom_less = 0
            dom_equal = 0
            dom_more = 0
            for k in range(M):
                val_i = x[i, V + k]
                val_j = x[j, V + k]
                if val_i < val_j:#i好
                    dom_less += 1
                elif val_i == val_j:#ij持平
                    dom_equal += 1
                else:
                    dom_more += 1#j好

            # 更新支配关系
            if dom_less == 0 and dom_equal != M:  # i被支配数
                individuals[i]['n'] += 1
            elif dom_more == 0 and dom_equal != M:  # i支配的
                individuals[i]['p'].append(j)

        # 记录第一前沿个体
        if individuals[i]['n'] == 0:
            x[i, V + M] = 1  # 前沿编号从1开始
            fronts[0].append(i)#记录前沿个体

    # 分层处理后续前沿
    current_front = 0
    while len(fronts[current_front]) > 0:#遍历每一层前沿
        Q = []
        for i in fronts[current_front]:
            for j in individuals[i]['p']:#遍历被个体i支配的个体
                individuals[j]['n'] -= 1
                if individuals[j]['n'] == 0:#如果减去i后，j不被任何个体支配
                    x[j, V + M] = current_front + 2  # 下一前沿编号
                    Q.append(j)
        current_front += 1
        fronts.append(Q)

    # 按前沿编号排序
    sorted_indices = np.argsort(x[:, V + M])
    sorted_pop = x[sorted_indices]

    # ------------------------- 拥挤度计算 -------------------------
    current_index = 0
    for front in fronts[:-1]:  # 最后一层是空列表
        if not front:
            break

        # 提取当前前沿个体
        front_size = len(front)
        front_pop = sorted_pop[current_index:current_index + front_size]

        # 初始化拥挤度 ###需不需要加这么多行
        front_pop = np.hstack((front_pop, np.zeros((front_size, M ))))

        # 对每个目标计算拥挤度
        for obj_idx in range(M):
            # 按目标值排序
            sorted_obj_indices = np.argsort(front_pop[:, V + obj_idx])
            sorted_front = front_pop[sorted_obj_indices]

            # 获取最大最小值
            f_min = sorted_front[0, V + obj_idx]
            f_max = sorted_front[-1, V + obj_idx]

            # 边界个体拥挤度设为无穷大
            front_pop[sorted_obj_indices[0], V + M + 2 + obj_idx] = np.inf
            front_pop[sorted_obj_indices[-1], V + M + 2 + obj_idx] = np.inf

            # 计算中间个体的拥挤度
            if f_max != f_min:#在支配情况下更新每个解的距离
                for j in range(1, front_size - 1):#[1,front_size - 2]
                    next_val = sorted_front[j + 1, V + obj_idx]
                    prev_val = sorted_front[j - 1, V + obj_idx]
                    front_pop[sorted_obj_indices[j], V + M + 2 + obj_idx] = \
                        (next_val - prev_val) / (f_max - f_min)
            else:
                for j in range(1, front_size - 1):
                    front_pop[sorted_obj_indices[j], V + M + 2 + obj_idx] = 0

        # 总拥挤度为各目标拥挤度之和
        front_pop[:, V + M + 1] = np.sum(
            front_pop[:, V + M + 2: V + M + 2+ M], axis=1
        )

        # 更新排序后的种群
        sorted_pop[current_index:current_index + front_size,:] = front_pop[:, :V + M + 2]
        current_index += front_size

    return sorted_pop


# # 测试用例
# if __name__ == "__main__":
#     # 生成测试数据（3个个体，2个目标）
#     x = np.array([
#         [1.0, 2.0, 0.5, 1.5],  # 变量1,变量2,目标1,目标2
#         [0.8, 1.5, 0.6, 1.2],
#         [1.2, 2.5, 0.4, 2.0]
#     ])
#     M = 2  # 目标数量
#     V = 2  # 变量数量
#
#     sorted_pop = non_domination_sort_mod_min(x, M, V)
#     print("排序后的种群矩阵:")
#     print(sorted_pop)