import numpy as np


def S3_groupDPtime(G, DBT, produce, timespan, X, takt):
    """批次调度与生产时间计算

    Args:
        G (list): 三维列表[车辆][批次][节点信息]
        DBT (list): 二维列表[车辆][批次]最佳时间区间
        produce (np.array): 产品-产线矩阵，形状为(PNumber, N)
        timespan (dict): 行程时间计算函数
        X_func (dict): 服务时间获取函数
        takt (np.array): 产线节拍时间数组

    Returns:
        tuple: (GDTW, GSI, GPT, GPN)
    """
    # ========== 第一阶段：构建批次时间表 ==========
    V = len(DBT)  # 车辆数
    H = max(len(sub_list) for sub_list in DBT) if V > 0 else 0  # 最大批次数
    batch_list = []

    # 收集所有有效批次
    r=0
    for v in range(V):
        for h in range(H):
            # a=len(DBT[v])-1
            #
            # if ((h<=len(DBT[v])-1)and((len(DBT[v])-1)>-1)):# 非空判定
            if h <= len(DBT[v]) - 1 and is_valid_dbt_item(DBT[v][h]):
                batch_data = {
                    "nodes": G[v][h],
                    # "nodes": G[v][h][0], # 零售商序列
                    "start_time": DBT[v][h][0],
                    "end_time": DBT[v][h][-1],
                    # "vehicle": v,
                    "vehicle": v,  # MATLAB索引转Python从1开始记录
                    "index":r
                }
                r+=1
                batch_list.append(batch_data)

    # 按开始时间和结束时间排序
    sorted_batches = sorted(batch_list, key=lambda x: (x['start_time'], x['end_time']))
    index_GDTW=[item['index'] for item in sorted_batches]

    # 构建GDTW矩阵（转置后）
    GDTW = {
        'nodes': [],
        'start': [],
        'end': [],
        'transport_time': [],
        'vehicle': []
    }
    for batch in sorted_batches:
        GDTW['nodes'].append(batch['nodes'])
        GDTW['start'].append(batch['start_time'])
        GDTW['end'].append(batch['end_time'])
        GDTW['vehicle'].append(batch['vehicle'])

    # ========== 第二阶段：生成调度索引矩阵GSI ==========
    e=0

    GSI = np.zeros((V, H), dtype=int)
    # index_mapping = {id(orig): idx for idx, orig in enumerate(batch_list)}
    for v in range(V):
        for h in range(H):
            # if h<=len(DBT[v])-1:# 非空判定
            # if DBT[v][h]:
            ##########
            if h <= len(DBT[v]) - 1 and is_valid_dbt_item(DBT[v][h]):
                # 找到原始批次在排序后的位置
                # orig_id = id({'nodes': G[v][h], 'vehicle': v + 1})  # 假设唯一性
                # GSI[v, h] = index_mapping.get(orig_id, 0) + 1  # MATLAB式1-based索引
                GSI[v,h]=index_GDTW.index(e)+1
                e+=1

    # ========== 第三阶段：计算运输模糊时间 ==========
    transport_times = []
    for nodes in GDTW['nodes']:
        if len(nodes) == 1:  # 单个订单
            # GDTW['transport_time'].append(X.get(nodes[0])*2)
            tt = [x * 2 for x in X.get(nodes[0])]
        else:  # 多个订单
            tran = [0, 0, 0]
            for j in range(len(nodes) - 1):
                travel = timespan.get((nodes[j], nodes[j + 1]))
                tran = [tran[i] + travel[i] for i in range(3)]
            service_start = X.get(nodes[0])
            service_end = X.get(nodes[-1])
            total = [service_start[i] + service_end[i] + tran[i] for i in range(3)]
            tt = total
        transport_times.append(tt)
    GDTW['transport_time'] = transport_times

    # ========== 第四阶段：生产计划计算 ==========
    PNumber = produce.shape[0]  # 产线数量
    GNumber = len(sorted_batches)  # 总批次数量
    GPN = np.zeros((PNumber, GNumber))  # 产品数量矩阵
    GPT = np.zeros((PNumber, GNumber))  # 生产时间矩阵

    for j in range(GNumber):
        nodes = sorted_batches[j]['nodes']
        for node in nodes:
            GPN[:, j] += produce[:, node]  # 节点索引从1开始

    for i in range(PNumber):
        GPT[i, :] = np.round(GPN[i, :] * takt[i], 4)

    return GDTW, GSI, GPT, GPN
import numpy as np

def is_valid_dbt_item(item):
    # None 直接无效
    if item is None:
        return False

    # 如果直接是 ndarray：认为只要有非零或非空就有效
    if isinstance(item, np.ndarray):
        return item.size > 0 and np.any(item != 0)

    # 正常情况：list/tuple
    if isinstance(item, (list, tuple)):
        if len(item) == 0:
            return False
        # 批次里每段可能是 list/ndarray/标量
        for seg in item:
            if seg is None:
                continue
            if isinstance(seg, np.ndarray):
                if seg.size > 0 and np.any(seg != 0):
                    return True
            elif isinstance(seg, (list, tuple)):
                if len(seg) > 0 and any(float(x) != 0 for x in seg):
                    return True
            else:
                # 标量
                try:
                    if float(seg) != 0:
                        return True
                except:
                    pass
        # 全是 0/空 => 无效
        return False

    # 其它标量类型
    try:
        return float(item) != 0
    except:
        return bool(item)
