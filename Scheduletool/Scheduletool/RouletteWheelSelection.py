import numpy as np
import random


def RouletteWheelSelection(weights):
    """
    轮盘赌选择法（权重越大选中概率越高）

    参数:
        weights (np.ndarray/list): 权重向量，支持任意维度

    返回:
        int: 被选中的索引（1-based，与MATLAB一致）
            如果所有权重为0则返回-1
    """
    # 转换为numpy数组并展平
    weights = np.array(weights).flatten()

    # 处理全零权重
    if np.sum(weights) == 0:
        return -1

    # 计算累积和
    accumulation = np.cumsum(weights)

    # 生成随机位置
    p = random.random() * accumulation[-1]

    # 搜索选中位置（1-based索引）
    chosen_index = -1
    for index in range(len(accumulation)):
        if accumulation[index] > p:
            chosen_index = index + 1  # 转为1-based索引
            break

    return chosen_index

#
# # 测试用例
# if __name__ == "__main__":
#     # 测试场景1：正常权重
#     weights = np.array([1, 2, 3])
#     print("测试1选择结果:", [RouletteWheelSelection(weights) for _ in range(5)])
#
#     # 测试场景2：全零权重
#     weights = np.array([0, 0, 0])
#     print("测试2选择结果:", RouletteWheelSelection(weights))
#
#     # 测试场景3：单个元素
#     weights = np.array([5])
#     print("测试3选择结果:", RouletteWheelSelection(weights))