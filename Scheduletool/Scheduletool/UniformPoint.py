import numpy as np
from scipy.special import comb
from itertools import combinations


def UniformPoint(N, M):
    """
    生成均匀分布的权重向量（用于多目标优化算法，如MOEA/D）

    参数:
        N (int): 初始请求的权重向量数量
        M (int): 目标函数维度

    返回:
        W (np.ndarray): 生成的权重矩阵，形状为 (最终N, M)
        N (int): 实际生成的权重向量数量
    """
    H1 = 1
    # 计算H1: 满足组合数 C(H1+M-1, M-1) > N 的最小H1
    while comb(H1 + M - 1, M - 1, exact=True) <= N:
        H1 += 1
    H1 -= 1  # 回退到最后一个满足条件的值

    # 生成第一部分权重 W1
    if M == 1:
        W = np.ones((1, 1))
    else:
        # 生成组合索引: C(H1+M-1, M-1)
        indices = np.array(list(combinations(range(1, H1 + M), M - 1)))
        # 构建权重矩阵
        W = indices - np.arange(M - 1) - 1
        W = W.astype(float)
        # 拼接列并标准化
        W = (np.hstack([W, np.full((W.shape[0], 1), H1)]) -
             np.hstack([np.zeros((W.shape[0], 1)), W])) / H1

    # 如果H1 < M，生成第二部分权重 W2
    if H1 < M and M > 1:
        H2 = 0
        # 计算H2: 满足 C(H1+M-1, M-1) + C(H2+M-1, M-1) > N 的最小H2
        while (comb(H1 + M - 1, M - 1, exact=True) +
               comb(H2 + M - 1, M - 1, exact=True)) <= N:
            H2 += 1
        H2 -= 1

        if H2 > 0:
            # 生成W2
            indices2 = np.array(list(combinations(range(1, H2 + M), M - 1)))
            W2 = indices2 - np.arange(M - 1) - 1
            W2 = (np.hstack([W2, np.full((W2.shape[0], 1), H2)]) -
                  np.hstack([np.zeros((W2.shape[0], 1)), W2])) / H2
            # 合并W1和W2
            W = np.vstack([W, W2 / 2 + 1 / (2 * M)])

    # 确保权重非负
    W = np.maximum(W, 1e-6)
    # 归一化每个权重向量（确保和为1）
    W /= W.sum(axis=1, keepdims=True)
    return W, W.shape[0]


# # 示例调用
# if __name__ == "__main__":
#     W, N = UniformPoint(500, 2)
#     print(f"Generated {N} weight vectors:\n{W}")