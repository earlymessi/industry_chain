import numpy as np


def Knowledge_drival(CV, KS, K):
    """
    知识驱动的算子选择策略

    参数:
        CV (np.ndarray): 信用值数组，形状为(K,)
        KS (np.ndarray): 知识集矩阵，形状为(2, KL)
        K (int): 操作符总数

    返回:
        int: 选择的操作符编号（1-based，与MATLAB一致）
    """
    # 条件1：所有信用值为零 或 知识集首行存在零（知识集未满/无有效操作）
    if np.all(CV == 0) or np.any(KS[0] == 0):
        return np.random.randint(1, K + 1)  # 1-based

    # 条件2：存在零信用值操作符
    elif np.any(CV == 0):
        if np.random.rand() < 0.5:
            op = RouletteWheelSelection(CV)
        else:
            # 获取所有零信用值操作符的1-based索引
            zero_indices = np.where(CV == 0)[0] + 1
            op = np.random.choice(zero_indices)
        return op if op != -1 else np.random.randint(1, K + 1)

    # 其他情况：直接轮盘赌选择
    else:
        op = RouletteWheelSelection(CV)
        return op if op != -1 else np.random.randint(1, K + 1)


def RouletteWheelSelection(weights):
    """与之前转换的轮盘赌函数保持一致"""
    weights = np.array(weights).flatten()
    if np.sum(weights) == 0:
        return -1
    accumulation = np.cumsum(weights)
    p = np.random.rand() * accumulation[-1]
    for index in range(len(accumulation)):
        if accumulation[index] > p:
            return index + 1  # 返回1-based索引
    return len(accumulation)  # 处理浮点误差


# 测试用例
if __name__ == "__main__":
    # 测试场景1：全零信用值
    CV = np.array([0, 0, 0, 0])
    KS = np.array([[1, 2, 3, 0], [0.1, 0.2, 0.3, 0.4]])  # 首行包含0
    print("测试1:", Knowledge_drival(CV, KS, 4))  # 应返回1-4

    # 测试场景2：存在零信用值操作符
    CV = np.array([0.2, 0, 0.3, 0.5])
    KS = np.array([[1, 2, 3, 4], [0.1, 0.2, 0.3, 0.4]])
    selected = []
    for _ in range(1000):
        selected.append(Knowledge_drival(CV, KS, 4))
    print("测试2中操作符2的出现次数:", np.sum(np.array(selected) == 2))

    # 测试场景3：正常轮盘赌
    CV = np.array([0.1, 0.3, 0.6])
    print("测试3示例选择:", [Knowledge_drival(CV, np.ones((2, 10)), 3) for _ in range(5)])