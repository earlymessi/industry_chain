import numpy as np
from scipy.spatial.distance import cdist


def updateWeight(pop_best, W, Z, EP, nus, Pi):
    """
    MOEA/D-AWA 权重调整策略：删除过密子问题并添加新子问题

    参数:
        pop_best (np.ndarray): 当前最优种群，形状为 (N, M+2)，后两列为目标值
        W (np.ndarray): 权重矩阵，形状为 (N, M)
        Z (np.ndarray): 理想参考点，形状为 (M,)
        EP (np.ndarray): 外部精英种群，形状为 (nEP, M+2)
        nus (int): 需调整的权重向量数量
        Pi (np.ndarray): 效用值数组，形状为 (N,)

    返回:
        tuple: (更新后的种群pop_best, 权重矩阵W, 效用值数组Pi)
    """
    # 初始化参数
    N, total_cols = pop_best.shape
    M = total_cols - 2  # 决策变量维度

    # ------------------------- 1. 用EP更新当前种群 -------------------------
    # 合并种群和精英种群
    merge = np.vstack((pop_best, EP))
    # 计算目标值与参考点的绝对偏差
    mergeObj = np.abs(merge[:, M:M + 2] - Z)
    # 计算每个解在所有权重下的切比雪夫聚合值
    g = np.zeros((merge.shape[0], W.shape[0]))
    for i in range(W.shape[0]):
        weighted = mergeObj * W[i, :]
        g[:, i] = np.max(weighted, axis=1)
    # 选择每个权重对应的最佳个体
    best_indices = np.argmin(g, axis=0)
    pop_best = merge[best_indices, :]

    # ------------------------- 2. 删除过密子问题 -------------------------
    # 计算种群个体间的欧氏距离
    objectives = pop_best[:, M:M + 2]
    Dis = cdist(objectives, objectives)
    np.fill_diagonal(Dis, np.inf)  # 将对角线设为无穷大
    Del = np.zeros(pop_best.shape[0], dtype=bool)

    # 循环删除最拥挤的个体
    while np.sum(Del) < min(nus, EP.shape[0]):
        Remain = np.where(~Del)[0]
        if len(Remain) == 0:
            break
        # 计算剩余个体的最小两个距离的乘积
        subDis = np.sort(Dis[Remain][:, Remain], axis=1)
        min_k = min(2, subDis.shape[1])
        prod_values = np.prod(subDis[:, :min_k], axis=1)
        # 找到乘积最小的个体（最拥挤）
        worst = np.argmin(prod_values)
        Del[Remain[worst]] = True

    # 执行删除操作
    pop_best = pop_best[~Del, :]
    W = W[~Del, :]
    # 调整效用值数组Pi
    # Pi = Pi[:len(pop_best)].copy()
    # Pi = np.append(Pi, np.max(Pi))  # 添加最大值
    Pi[len(pop_best)+1:] = np.max(Pi)

    # ------------------------- 3. 添加新子问题 -------------------------
    merge = np.vstack((pop_best, EP))
    Selected = np.zeros(merge.shape[0], dtype=bool)
    Selected[:pop_best.shape[0]] = True
    Dis = cdist(merge[:, M:M + 2], merge[:, M:M + 2])
    np.fill_diagonal(Dis, np.inf)

    # 选择最分散的个体加入
    while np.sum(Selected) < min(N, merge.shape[0]):
        # 计算未选个体到已选个体的距离
        unselected = np.where(~Selected)[0]
        selected = np.where(Selected)[0]
        if len(selected) == 0:
            break
        subDis = Dis[unselected][:, selected]
        subDis_sorted = np.sort(subDis, axis=1)
        min_k = min(2, subDis_sorted.shape[1])
        prod_values = np.prod(subDis_sorted[:, :min_k], axis=1)
        # 选择乘积最大的个体（最分散）
        best = np.argmax(prod_values)
        Selected[unselected[best]] = True

    # 添加新个体并更新权重
    new_pop = merge[Selected, :]
    newObjs = new_pop[pop_best.shape[0]:, M:M + 2]
    temp = 1.0 / (newObjs - Z + 1e-6)
    new_weights = temp / np.sum(temp, axis=1, keepdims=True)
    W = np.vstack((W, new_weights))
    pop_best = new_pop

    return pop_best, W, Pi


# # 测试用例
# if __name__ == "__main__":
#     # 构造测试数据
#     np.random.seed(42)
#     pop_best = np.random.rand(10, 4)  # M=2, 总列数=4
#     W = np.random.dirichlet(np.ones(2), size=10)
#     Z = np.array([0.1, 0.1])
#     EP = np.random.rand(5, 4)
#     nus = 3
#     Pi = np.random.rand(10)
#
#     new_pop, new_W, new_Pi = updateWeight(pop_best, W, Z, EP, nus, Pi)
#     print("更新后的种群形状:", new_pop.shape)
#     print("更新后的权重形状:", new_W.shape)
#     print("更新后的效用值形状:", new_Pi.shape)