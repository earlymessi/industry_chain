from numpy.matlib import zeros
import numpy as np

def fuzzy(fitness,mod):
    fitness = np.array(fitness, dtype=object)
    N,M=fitness.shape
    if mod == 1:
        # 计算单一的模糊数
        obj = np.zeros((N, 1))
        for i in range(N):
            # 计算三角模糊数的期望
            obj = (fitness[i, 0] + 2 * fitness[i, 1] + fitness[i, 2]) / 4
    else:
        # 计算目标函数模糊数
        obj = np.zeros((N, 2))
        for i in range(N):
            # 计算第一列三角模糊数的期望
            obj[i, 0] = (fitness[i, 0][0][0] + 2 * fitness[i, 0][0][1] + fitness[i, 0][0][2]) / 4
            # 计算第二列三角模糊数的期望
            obj[i, 1] = (fitness[i, 1][0] + 2 * fitness[i, 1][1] + fitness[i, 1][2]) / 4
    return obj