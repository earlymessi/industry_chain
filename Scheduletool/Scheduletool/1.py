def longest_substring_with_k_changes(n, q, s, queries):
    results = []

    # 处理每一个查询
    for k, c in queries:
        max_length = 0
        left = 0  # 窗口的左边界
        change_count = 0  # 当前窗口内需要修改的字符数

        for right in range(n):
            # 如果当前字符不是c，则需要修改
            if s[right] != c:
                change_count += 1

            # 如果需要修改的字符数超过了k，缩小窗口
            while change_count > k:
                if s[left] != c:
                    change_count -= 1
                left += 1

            # 计算当前窗口的长度
            max_length = max(max_length, right - left + 1)

        # 将结果加入结果列表
        results.append(max_length)

    return results


# 读取输入
n, q = map(int, input().split())
s = input()
queries = [tuple(input().split()) for _ in range(q)]
queries = [(int(k), c) for k, c in queries]

# 获取结果
results = longest_substring_with_k_changes(n, q, s, queries)

# 输出结果
for res in results:
    print(res)
