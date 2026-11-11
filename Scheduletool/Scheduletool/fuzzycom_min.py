import numpy as np


def fuzzycom_min(F):
    """寻找一组三角模糊数中的最小值索引（基于雷德明比较方法）

    Args:
        F (ndarray): 三角模糊数列表，每个元素为[a, b, c]

    Returns:
        list: 最小模糊数的原始索引列表（MATLAB式1-based索引）
    """
    # 步骤1：构建比较矩阵V
    F0=F.shape[0]
    V = np.zeros((F0,4))
    for i in range(F0):
        V[i,0]=(F[i,0]+2*F[i,1]+F[i,2])/4
        V[i,1]=F[i,1]
        V[i,2] =F[i, 2]-F[i,1]
        V[i,3] =i
        # a, b, c = tfn
        # v1 = (a + 2 * b + c) / 4  # 计算期望值
        # v2 = b  # 核心值
        # v3 = c - a  # 模糊跨度
        # V.append((v1, v2, v3, idx ))  # 保存原始索引（从1开始）

    # 步骤2：三级筛选流程
    # 第一级筛选：最小期望值
    min_v1 = np.min(V[:, 0])  # 找到第一列的最小值
    indices = np.where(V[:, 0] == min_v1)[0]  # 找到等于最小值的索引#不止一个
    s1 = indices[0]  # 获取第一个索引
    V=V[indices]
    # V=[V[i] for i in indices]
    # min_v1 = min(item[0] for item in V)
    # stage1 = [item for item in V if item[0] == min_v1]

    if len(indices) == 1:
        return V[:,3]

    # 第二级筛选：最小核心值
    min_v2 = np.min(V[:, 1])  # 找到第一列的最小值
    indices = np.where(V[:, 1] == min_v2)[0]  # 找到等于最小值的索引
    s2 = indices[0]  # 获取第一个索引
    V = V[indices]
    # V=[V[i] for i in indices]
    # min_v2 = min(item[1] for item in s1)
    # stage2 = [item for item in s1 if item[1] == min_v2]

    if len(indices) == 1:
        return V[:,3]

    # 第三级筛选：最小模糊跨度 可能有多个
    min_v3 = np.min(V[:, 2])  # 找到第一列的最小值
    indices = np.where(V[:, 2] == min_v3)[0]  # 找到等于最小值的索引
    V = V[indices]
    # s3 = indices[0]  # 获取第一个索引
    # min_v3 = min(item[2] for item in stage2)
    # V3 = [item for item in stage2 if item[2] == min_v3]
    return  V[:,3]
    # return [item[3] for item in stage3]