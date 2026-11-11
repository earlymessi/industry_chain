def fuzzy_superposition(X_TFN, k, w1, w2, mode):
    """模糊叠加操作

    Args:
        X_TFN (list): 三角模糊数 [a, b, c]
        k (float): 叠加轴位置
        w1 (float): 左侧权重
        w2 (float): 右侧权重
        mode (int): 叠加模式 (0: 左到右, 1: 右到左)

    Returns:
        list: 处理后的三角模糊数 [min, original_mid, max]
    """
    SX = []
    for i in range(3):
        x = X_TFN[i]
        if x == k:
            SX.append(k)
        else:
            if mode == 0:
                term = 0.5 * ((w2 - w1) * x + (1 + w1) * k) + \
                       0.5 * abs(x - k) * ((w1 + w2) * x - (1 + w1) * k) / (x - k)
            else:
                term = 0.5 * ((w1 - w2) * x + (1 + w2) * k) + \
                       0.5 * abs(x - k) * ((1 + w1) * k - (w1 + w2) * x) / (x - k)
            SX.append(term)

    # 保持原MATLAB的中间点选择逻辑
    return [min(SX), SX[1], max(SX)]

#
# # 测试案例
# if __name__ == "__main__":
#     # 模式0测试
#     print(fuzzy_superposition([2, 3, 4], 3, 0.5, 1.2, 0))  # 应返回 [min_val, 中间计算结果, max_val]
#
#     # 含k值的测试
#     print(fuzzy_superposition([2, 3, 3], 3, 0.5, 1.2, 1))  # 第三个元素等于k