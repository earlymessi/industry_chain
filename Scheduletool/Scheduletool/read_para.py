import numpy as np
import pandas as pd
import os
import math

from scipy.spatial import distance_matrix


#距离计算
def haversine(lat1, lon1, lat2, lon2):
    # 将角度转换为弧度
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # 哈夫辛公式
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # 地球半径（单位：公里）
    R = 6371.0
    distance = R * c

    return distance

def read_orignpara(path):
    #读取位置数据
    file_path=path
    data= pd.read_excel(file_path)
    data=data.iloc[0:,[4,5]]
    data=np.array(data)
    points_num=len(data)
    distance_matrix=np.zeros((points_num,points_num))

    for i in range(points_num):
        for j in range(points_num):
            if i!=j:
                la1,lon1=data[i,0],data[i,1]
                la2,lon2=data[j,0],data[j,1]
                distance=haversine(la1,lon1,la2,lon2)
                distance_matrix[i,j]=distance
            else:
                distance_matrix[i,j]=0
    print(distance_matrix)
def read_para(PATH1, PATH2, PATH3):
    # 读取第一个文件（模糊时间数据）
    fuzzytime_df = pd.read_excel(PATH1, header=None)
    fuzzytime = fuzzytime_df.to_numpy()

    # 提取prtime和traveltime
    prtime = fuzzytime[0, :]
    traveltime = fuzzytime[1:, :]

    # 构建timespan字典（Python中需用元组作为键）
    timespan = {}
    n = traveltime.shape[0]
    for i in range(n):
        for j in range(i, n):
            # 注意MATLAB的索引从1开始，Python从0开始
            # 原MATLAB代码: traveltime(i, 3*j-2 : 3*j)
            start_col = 3 * j
            end_col = 3 * (j + 1)
            timespan[(i , j )] = traveltime[i, start_col:end_col].tolist()
            timespan[(j , i )] = timespan[(i , j )]
            # timespan[(i + 1, j + 1)] = traveltime[i, start_col:end_col].tolist()
            # timespan[(j + 1, i + 1)] = timespan[(i + 1, j + 1)]

    # 构建X（工厂到零售商的距离）
    X = {}
    for i in range(prtime.shape[0] // 3):
        X[i ] = prtime[3 * i: 3 * (i + 1)].tolist()

    # 读取第二个文件（零售商需求和时间窗）
    retailsneed_df = pd.read_excel(PATH2, header=None)
    retailsneed = retailsneed_df.to_numpy()

    # 提取produce和timewindows
    produce = retailsneed[:, :-2].T  # 转置
    timewindows = retailsneed[:, -2:]

    # 读取第三个文件（其他参数）
    other_df = pd.read_excel(PATH3, header=None)
    other = other_df.to_numpy()

    # 提取各列并去除非空值
    def extract_col(col_idx):
        col = other[:, col_idx]
        return col[~np.isnan(col)].astype(float)

    takt = extract_col(0)
    pc = extract_col(1)
    pallet = extract_col(2)
    vcapacity = extract_col(3).reshape(-1, 1)  # 保持二维结构
    vfixcost = extract_col(4)
    vvarcost = extract_col(5)
    occupy = np.dot(pallet.T, produce).T
    return (
        {'timespan':timespan,'X': X, 'produce': produce,'timewindows': timewindows,
         'takt':takt,'pc':  pc, 'pallet': pallet, 'vcapacity': vcapacity, 'vfixcost':vfixcost,  'vvarcost':vvarcost,'occupy':occupy}
    )

# 示例调用
if __name__ == "__main__":
    # PATH1 = "path/to/traveltime.xlsx"
    # PATH2 = "path/to/retailsneed.xlsx"
    # PATH3 = "path/to/other.xlsx"
    # result = read_para(PATH1, PATH2, PATH3)
    # timespan, X, produce, timewindows, takt, pc, pallet, vcapacity, vfixcost, vvarcost = result
    # 检查文件是否存在
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, 'result', 'excel', 'factory_and_retailers_locations.xlsx')
    if os.path.isfile(path):
        print("文件存在，准备读取...")
        read_orignpara(path)
        # 接下来的操作...
    else:
        print("文件未找到，请检查文件路径。")

    # 示例：经纬度
    lat1 = 34.052235  # 第一个点的纬度（例如洛杉矶）
    lon1 = -118.243683  # 第一个点的经度
    lat2 = 40.712776  # 第二个点的纬度（例如纽约）
    lon2 = -74.005974  # 第二个点的经度

    # 计算距离
    distance = haversine(lat1, lon1, lat2, lon2)
    print(f"两点之间的距离: {distance:.2f} 公里")
