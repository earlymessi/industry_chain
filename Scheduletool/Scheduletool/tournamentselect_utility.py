import numpy as np


def tournamentselect_utility(utility, pool_size, tour_size):
    """
    基于效用函数的锦标赛选择法

    参数:
        utility (np.ndarray): 效用值数组，形状为 (total_num,)
        pool_size (int): 需要选出的个体数量
        tour_size (int): 每次锦标赛选择的个体数量

    返回:
        np.ndarray: 选中的个体索引数组，形状为 (pool_size,)
    """
    total_num = utility.shape[0]
    pool = []

    for _ in range(pool_size):
        # 生成随机排列（注意Python索引从0开始）
        select = np.random.permutation(total_num)
        # 选取前tour_size个候选
        candidates = select[:tour_size]
        # 找到效用值最大的候选索引
        max_index = np.argmax(utility[candidates])
        # 记录选中的个体（原始索引）
        selected = candidates[max_index]
        pool.append(selected)

    return np.array(pool)


# # 测试用例
# if __name__ == "__main__":
#     # 示例数据（效用值数组）
#     utility = np.array([0.3, 0.8, 0.5, 0.1, 0.9])
#     # 参数设置
#     pool_size = 3
#     tour_size = 2
#
#     selected = tournamentselect_utility(utility, pool_size, tour_size)
#     print("选中的个体索引:", selected)
#     print("对应的效用值:", utility[selected])