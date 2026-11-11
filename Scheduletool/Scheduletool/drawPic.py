import numpy as np
from . import read_para
import  os
from scipy.spatial.distance import cdist
from . import fuzzyEx

def construct_gram_matrix(distance_matrix):
    # M_ij = (D_1j^2 + D_i1^2 - D_ij^2) / 2
    row, col = distance_matrix.shape
    gram = np.zeros([row, col])
    for i in range(row):
        for j in range(col):
            gram[i][j] = 0.5 * ((distance_matrix[0][j])**2 + (distance_matrix[i][0])**2 - (distance_matrix[i][j])**2)
    return gram

def get_coordinates_by_distance(distance_matrix):
    eps = 1e-5

    gram_matrix = construct_gram_matrix(distance_matrix)
    # get eigenvalue and eigenvectors
    feature_values, feature_vectors = np.linalg.eig(gram_matrix)
    select_feature_values = []

    # if eigenvalue == 0, delete it and its eigenvector
    for i in range(len(feature_values) - 1, -1, -1):
        if feature_values[i] > eps:
            select_feature_values.append(feature_values[i])
        else:
            feature_vectors = np.delete(feature_vectors, i, axis=1)
    eye_matrix = np.eye(len(select_feature_values))
    select_feature_values.reverse()
    # sqrt(eigenvalues) * eigenvectors
    for i in range(len(select_feature_values)):
        eye_matrix[i, i] = select_feature_values[i]
    return np.dot(feature_vectors, eye_matrix**0.5)

if __name__ == '__main__':
    global_vars = {
        '''
            'timespan': 零售商i到零售j的模糊旅途时间, 'X': 工厂到零售商的距离, 'produce': 零售商需求, 'timewindows': 时间窗, 'takt': 生产速度,
            'pc': 产线成本, 'pallet': 单位产品占据托盘, 'vcapacity': 车辆容量, 'vfixcost': 车辆固定成本, 'vvarcost': 车辆可变成本,
            'occupy': None, 'Re': 1, 'Rd': 3, 'holding': 10
        '''
        'timespan': 1, 'X': None, 'produce': None, 'timewindows': None, 'takt': None,
        'pc': None, 'pallet': None, 'vcapacity': None, 'vfixcost': None, 'vvarcost': None,
        'occupy': None,
        'Re': 1, 'Rd': 3, 'holding': 10
    }
    path =  'D:/桌面/IPSVRP-STW-FTT-CASE/Real case data/'
    Data = ['traveltime', 'retailsneed', 'other']
    xlsx_tail = '.xlsx'
    PATH1 = os.path.join(path, Data[0] + xlsx_tail)
    PATH2 = os.path.join(path, Data[1] + xlsx_tail)
    PATH3 = os.path.join(path, Data[2] + xlsx_tail)
    data = read_para.read_para(PATH1, PATH2, PATH3)
    # path ='D:/桌面/IPSVRP-STW-FTT-CASE/Factory historical data (original )/'
    # Data = '(original) Factory and retailers  locations'
    # xlsx_tail = '.xlsx'
    # PATH4 = os.path.join(path, Data + xlsx_tail)
    # data1=read_para.read_para(PATH4)
    # 假设返回值为字典或元组，更新全局变量
    global_vars.update(data)
    dic=global_vars.get("timespan")
    needNum=global_vars.get("produce")
    needNum=needNum.shape[1]
    weight = np.zeros((needNum,needNum))
    for(i,j),value in dic.items():
        weight[i,j]=fuzzyEx.fuzzy([value],1)

    points = np.array([[0, 0], [1, 0], [2, 1], [1,2]])
    origin_dist_matrix = cdist(points, points, 'euclidean')
    coordinates = get_coordinates_by_distance(origin_dist_matrix)
    new_dist_matrix = cdist(coordinates, coordinates, 'euclidean')
    #new_dist_matrix = cdist(coordinates, coordinates, 'euclidean')
    #print(origin_dist_matrix)
    print(new_dist_matrix)
    print(coordinates)