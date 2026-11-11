import random


def generate_unique_permutations(n_elements, sample_size):
    """
    生成指定数量的唯一随机排列
    :param n_elements: 元素范围（0到n_elements-1）
    :param sample_size: 需要生成的排列数量
    :return: 包含唯一排列的列表
    """
    seen = set()
    permutations = []

    # 计算最大尝试次数防止无限循环
    max_attempts = sample_size * 10
    attempts = 0

    while len(permutations) < sample_size and attempts < max_attempts:
        # 生成随机排列
        arr = list(range(n_elements))
        random.shuffle(arr)
        arr_tuple = tuple(arr)

        # 检查是否已存在
        if arr_tuple not in seen:
            seen.add(arr_tuple)
            permutations.append(arr)

        attempts += 1

    if len(permutations) < sample_size:
        print(f"警告：仅生成 {len(permutations)} 个唯一排列")
    permutations_num = len(permutations)
    return permutations, permutations_num


# 生成0-5的200种随机排列
n = 6  # 0到5共6个元素
sample_size = 200
unique_perms = generate_unique_permutations(n, sample_size)

# 验证结果
print(f"已生成唯一排列数量：{len(unique_perms)}")
print("示例排列：")
for p in unique_perms[:3]:
    print(p)