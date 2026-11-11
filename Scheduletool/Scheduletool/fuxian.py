import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.spatial.distance import cdist
from . import read_para
from . import UniformPoint
from . import Fitnessvalue
from . import fuzzyEx
from . import non_domination_sort_mod_min
from . import tournamentselect_utility
from . import Knowledge_drival
from . import mating
from . import updateWeight
from . import updateWeightU
from . import S1_routing
from . import S2_besttime
from . import S3_groupDPtime
from . import S3_PLadjustment
from . import K_means
from .K_means import k_means
from . import random_permutation
from .Nature_DQN import DQN
import random
import argparse
import json

def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except Exception:
        pass

def parse_args():
    p = argparse.ArgumentParser()
    _default_instance = os.path.join(os.path.dirname(__file__), 'result', 'excel')
    _default_outdir = os.path.join(os.path.dirname(__file__), 'result')
    p.add_argument("--instance", type=str, default=_default_instance, help="instance folder path")
    p.add_argument("--outdir", type=str, default=_default_outdir, help="output dir for this run")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--run_id", type=int, default=1)
    return p.parse_args()

# 全局变量（根据实际需求调整作用域）
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


# 自定义函数占位符（需根据MATLAB代码补充实现）
# def read_para(PATH1, PATH2, PATH3):
#     # 实现数据读取逻辑，返回对应变量
#     pass


# def UniformPoint(population_num, obj_no):
#     # 生成均匀权重向量
#     if population_num <= 0 or obj_no <= 0:
#         return None  # 返回 None，可能需要调整
#     weight = np.random.rand(population_num, obj_no)  # 示例权重生成
#     return weight, population_num

#
# def Fitnessvalue(population):
#     # 计算适应度值
#     pass
#
#
# def fuzzyEx(ObjectF):
#     # 模糊化处理
#     pass
#
#
# def non_domination_sort_mod_min(merge, obj_num, MNumber):
#     # 非支配排序
#     pass
#
#
# def tournamentselect_utility(Pi, size, tournament_size):
#     # 基于效用的锦标赛选择
#     pass
#
#
# def Knowledge_drival(CV, KS, K):
#     # 知识驱动的算子选择
#     pass
#
#
# def mating(selectv, op, parent, population, P, MNumber, EP):
#     # 交叉和变异生成后代
#     pass
#
#
# def updateWeight(population_obj, Weight, Z, EP, rate, Pi):
#     # 更新权重策略A
#     pass
#
#
# def updateWeightU(population_obj, Weight, Z, EP, rate, Pi):
#     # 更新权重策略B
#     pass


# 主算法
def KDCEA(args):
    os.makedirs(args.outdir, exist_ok=True)
    set_seed(args.seed)

    
    path = args.instance
    Data = ['traveltime', 'retailsneed', 'other']
    xlsx_tail = '.xlsx'
    PATH1 = os.path.join(path, Data[0] + xlsx_tail)
    PATH2 = os.path.join(path, Data[1] + xlsx_tail)
    PATH3 = os.path.join(path, Data[2] + xlsx_tail)
    data = read_para.read_para(PATH1, PATH2, PATH3)
    # 假设返回值为字典或元组，更新全局变量
    global_vars.update(data)

    respath = args.outdir
    print(f'Calculating {respath}')

    # 参数设置
    obj_no = 2       #目标函数个数
    Max_iteration = 50#最大迭代次数
    population_num = 500#每个子种群中个体数目
    U = 0.01#改进了效用函数U的基线
    IP = 0.7#执行自适应权值调整的迭代百分比
    NR = 1#每次更新NR中被替换的人数
    KL = 1000#知识集RL的记录长度
    K = 4#操作员数
    rate_update_weight = 0.05# 更新权重参数比例
    wag = 20#利用AWA的迭代间隔
    T = np.ceil(population_num / 10).astype(int)#邻居规模ch
    nEP = np.ceil(population_num * 1.5).astype(int)#外部精英的最大储存量
    Pi_1 = np.ones(population_num)#每个子问题的实用程序
    Pi_2 = np.ones(population_num)#每个子问题的实用程序

    # 权重向量初始化
    Weight, population_num= UniformPoint.UniformPoint(population_num, obj_no)
    Weight1 = 1 / Weight / np.sum(1 / Weight, axis=1, keepdims=True)
    Weight2 = Weight1.copy()

    # 邻居矩阵
    Neighbor = cdist(Weight1, Weight1, metric='euclidean')
    Neighbor = np.argsort(Neighbor, axis=1)[:, :T]

    # 初始种群
    #产线数#零售商数量
    PNumber, MNumber = global_vars['produce'].shape
    #车辆数
    VNumber = global_vars['vcapacity'].shape[0]
    #每个零售商所需总托盘数
    occupy = (global_vars['pallet'].T @ global_vars['produce']).T
    selectv = []
    #初始聚类

    #可承担每个零售商货物物流车
    for j in range(MNumber):
        valid_vehicles = np.where(global_vars['vcapacity'][:, 0] >= occupy[j])[0]
        selectv.append(valid_vehicles)
    rpopulation_1 = np.zeros((int(population_num/2), MNumber))
    rpopulation_2 = np.zeros((int(population_num/2), MNumber))
    lables=k_means(VNumber,MNumber)
    lables=lables[1:]
    permutation, permutations_num = random_permutation.generate_unique_permutations(VNumber, int(population_num / 2))
    permutation = np.array(permutation)

    for j in range(MNumber):
        rpopulation_1[:, j] = np.random.randint(0, len(selectv[j]), int(population_num / 2))
    for i in range(permutations_num):
        for j in range(MNumber):
            vindex = permutation[i, lables[j]]
            rpopulation_2[i, j] = vindex
    if (permutations_num < population_num // 2):
        for j in range(MNumber):
            rpopulation_2[permutations_num:population_num // 2, j] = np.random.randint(0, len(selectv[j]),
                                                                                       int(population_num // 2 - permutations_num))


    rpopulation=np.vstack((rpopulation_1, rpopulation_2))
    population = rpopulation

    # 适应度计算
    ObjectF = Fitnessvalue.Fitnessvalue(population,global_vars)
    Object = fuzzyEx.fuzzy(ObjectF,2)
    Z1 = np.min(Object, axis=0)
    Z2 = Z1.copy()
    Z_bad = np.max(Object, axis=0)
    ########
    Z1_dqn=np.min(Object, axis=0)
    # 种群排序
    merge = np.hstack((population, Object))
    merge = merge[np.lexsort((-merge[:, MNumber + 1], merge[:, MNumber]))]  # 多目标排序
    population1 = merge[:, :MNumber]
    population2 = merge[:, :MNumber]
    Object1 = merge[:, MNumber:MNumber + 2]
    Object2 = Object1.copy()
    Object_init1 = Object1.copy()
    Object_init2 = Object2.copy()

    # 初始化外部种群EP
    merge = np.unique(merge, axis=0)
    Final_population = non_domination_sort_mod_min.non_domination_sort_mod_min(merge, obj_no, MNumber)
    frontnumber = np.where(Final_population[:, MNumber + 2] == 1)[0][-1] + 1
    if frontnumber > nEP:
        total_EP = Final_population[:frontnumber, :MNumber + 4]
        f = total_EP[np.lexsort((-total_EP[:, MNumber + 3], total_EP[:, MNumber + 2]))]
        EP = f[:nEP, :MNumber + 2]
    else:
        EP = Final_population[:frontnumber, :MNumber + 2]

    # 优化循环
    CV_1 = np.zeros(K)
    CV_2 = np.zeros(K)
    KS_1 = np.zeros((2, KL))
    KS_2 = np.zeros((2, KL))

    # plt.ion()  # 启用交互式绘图
    #DQN算子选择
    N_ACTIONS = 4  # 候选算子的数量（比如有4种不同的操作可以选择）
    N_STATES = MNumber + obj_no
    #N_STATES = MNumber+obj_no+4  # 状态的维度（比如每个状态用30个数字描述）
    BATCH_SIZE = 16  # 每次从记忆中抽取16条数据来训练网络
    MEMORY_CAPACITY = 40  # 记忆缓冲区最多存储40条经验
    CountOpers = np.zeros(N_ACTIONS)  # 统计每个算子被选择的次数（初始全为0
    PopCountOpers = []  # 保存每个周期内算子的选择次数，用于后续绘图
    dqn=DQN(N_STATES,N_ACTIONS)
    SW = np.zeros((2, population_num * 4))
    n=4
    #迭代
    for iter in range(Max_iteration):
        print(f'Iteration {iter}')
        # 标准Tchebycheff聚合（子种群A）
        for subgeneration in range(5):
            #寻找边界
            Bounday = np.where(np.sum(Weight < 1e-3, axis=1) == (obj_no - 1))[0]
            #选择个体（交配池）
            I1 = np.concatenate([
                tournamentselect_utility.tournamentselect_utility(Pi_1, population_num // 5 - len(Bounday), 10),
                Bounday
            ])
            con_old = np.sum(Object1) / population_num
            div_old = 1 / (max(Object1[:, 0] - min(Object1[:, 0]) + Object1[:, 1] - min(Object1[:, 1])))
            #遍历个体
            for i in I1:
                #dqn_chose
                #gen = currentGen
                # state = np.hstack(([con_old], [div_old]))
                state = np.hstack((population1[i], Weight1[i]))
                #state = np.hstack((population1[i], Weight1[i],[con_old],[div_old],Object1[i]))
                state=state.flatten()
                if dqn.memory_counter > 1000:

                    a = dqn.choose_action(state)
                    # 如果有算子在滑动窗口里没有记录，那么就选它
                    for i in range(n):
                        if np.sum(SW[0] == i) == 0:
                            a = i
                            break
                else:
                    a = Knowledge_drival.Knowledge_drival(CV_1, KS_1, K)-1
                    # a = np.random.randint(0, n)
                #a = np.random.randint(0, n)
                #countOpers[a] += 1
                # if a == 0:  # 使用模拟二进制交叉
                #     offChrom = self.Opers[0].do(OldChrom, r0, neighbourVector)
                # elif a == 1:  # 使用M2m里的交叉
                #     offChrom = self.Opers[1].do(OldChrom, r0, neighbourVector, currentGen)
                # else:  # 使用差分算子
                #     offChrom = self.Opers[a].do(OldChrom, r0, neighbourVector)
                #self.state_ = np.hstack((offChrom[0], self.lambda_[r0]))
                #a=dqn.choose_action(i)
                # 选择邻域个体
                if np.random.rand() < 0.9:
                    P_dqn = Neighbor[i, np.random.permutation(T)]
                else:
                    P_dqn = np.random.permutation(population_num)
                #a = dqn.choose_action(i)
                op=a+1
                Offspring_dqn = mating.mating(selectv, op, population1[i], population1, P_dqn, MNumber, EP, global_vars)
                Offspring_dqn = Offspring_dqn.reshape(1, MNumber)
                Object_Off_dqn = fuzzyEx.fuzzy(Fitnessvalue.Fitnessvalue(Offspring_dqn, global_vars), 2)
                Object_Off_dqn = np.round(Object_Off_dqn)
                Z1_dqn = np.minimum(Z1_dqn, Object_Off_dqn)
                # 越小越优
                g_old_dqn = np.max(np.abs(Object1[P_dqn] - Z1_dqn) * Weight1[P_dqn], axis=1)
                g_new_dqn = np.max(np.abs(Object_Off_dqn - Z1_dqn) * Weight1[P_dqn], axis=1)
                replace_dqn = np.where(g_old_dqn > g_new_dqn)[0][:NR]
                # 变化率越大越好
                TIR = np.sum((g_old_dqn[replace_dqn] - g_new_dqn[replace_dqn]) / (g_old_dqn[replace_dqn] + 1e-6))
                if len(replace_dqn) > 0:

                    oldspring=population1[P_dqn[replace_dqn]]
                    oldobj=Object1[P_dqn[replace_dqn]]
                    population1[P_dqn[replace_dqn]] = Offspring_dqn
                    Object1[P_dqn[replace_dqn]] = Object_Off_dqn
                    con_new = np.sum(Object1) / population_num
                    #this
                    div_new = 1 / (max(Object1[:, 0] - min(Object1[:, 0]) + max(Object1[:, 1]) - min(Object1[:, 1])))
                    #r = TIR
                    FIR = (oldobj[0] - Object_Off_dqn[0]) / oldobj[0]
                    #r=FIR[0,0]*2+FIR[0,1]
                    # r = FIR.sum()
                    ######此处可能有问题-成了div_old r=con_old+div_old-con_new-div_old+FIR.sum()
                    #####r=con_old+div_old-con_new-div_old+FIR.sum()
                    r = TIR.sum()
                    #r = con_old + div_old - con_new - div_new + FIR.sum()
                    SW = np.concatenate((SW[:, 1:], np.array([[a], [r]])), axis=1)
                    #reward = np.sum(SW[1, SW[0, :] == a])
                    reward = np.max(SW[1, SW[0, :] == a])
                    # reward = reward/np.sum(SW[1,:])
                    # reward = np.max(SW[1, SW[0, :] == a])
                    #需要首先修改con、div和oldobj指标
                    s1 = np.hstack((oldspring, Weight1[P_dqn[replace_dqn]]))
                    #s1 = np.hstack((oldspring, Weight1[P_dqn[replace_dqn]],[[con_old]],[[div_old]],oldobj))
                    #归一化
                    s2 = np.hstack((population1[P_dqn[replace_dqn]], Weight1[P_dqn[replace_dqn]]))
                    #s2 = np.hstack((population1[P_dqn[replace_dqn]], Weight1[P_dqn[replace_dqn]],[[con_new]],[[div_new]],Object_Off_dqn))
                    s1=s1.flatten()
                    s2=s2.flatten()
                    #将当前状态、动作、奖励和下一个状态存储到经验回放缓冲区中
                    dqn.store_transition(s1, a, reward, s2)
                    if dqn.memory_counter > 500 and random.random() < 0.2:
                        dqn.learn()
                KS_1 = np.roll(KS_1, -1, axis=1)
                KS_1[:, -1] = [a, TIR]
                Reward = np.array([np.sum(KS_1[1, KS_1[0] == k]) for k in range(K)])
                CV_1 = Reward / (np.sum(Reward) + 1e-6)



                    # 更新Pi_1


                # op = Knowledge_drival.Knowledge_drival(CV_1, KS_1, K)
                # #选择邻域个体
                # if np.random.rand() < 0.9:
                #     P = Neighbor[i, np.random.permutation(T)]
                # else:
                #     P = np.random.permutation(population_num)
                # a=dqn.choose_action(i)
                # Offspring = mating.mating(selectv, op, population1[i], population1, P, MNumber, EP,global_vars)
                # Offspring =Offspring.reshape(1,MNumber)
                # Object_Off = fuzzyEx.fuzzy(Fitnessvalue.Fitnessvalue(Offspring,global_vars),2)
                # Object_Off = np.round(Object_Off)
                # Z1 = np.minimum(Z1, Object_Off)
                # g_old = np.max(np.abs(Object1[P] - Z1) * Weight1[P], axis=1)
                # g_new = np.max(np.abs(Object_Off - Z1) * Weight1[P], axis=1)
                # replace = np.where(g_old > g_new)[0][:NR]
                # if len(replace) > 0:
                #     population1[P[replace]] = Offspring
                #     Object1[P[replace]] = Object_Off
                # TIR = np.sum((g_old[replace] - g_new[replace]) / (g_old[replace] + 1e-6))
                # KS_1 = np.roll(KS_1, -1, axis=1)
                # KS_1[:, -1] = [op, TIR]
                # Reward = np.array([np.sum(KS_1[1, KS_1[0] == k]) for k in range(K)])
                # CV_1 = Reward / (np.sum(Reward) + 1e-6)

        # # 更新Pi_1
        # if iter == 0:
        #     oldObj1 = np.max(np.abs(Object_init1 - Z1) * Weight1, axis=1)
        # newObj1 = np.max(np.abs(Object1 - Z1) * Weight1, axis=1)
        # DELTA = np.abs(oldObj1 - newObj1) / oldObj1
        # Temp = DELTA < U
        # Pi_1[~Temp] = 1
        # Pi_1[Temp] = (0.95 + 0.05 * DELTA[Temp] / U) * Pi_1[Temp]
        # oldObj1 = newObj1.copy()

        #dqn更新
        if iter == 0:
            oldObj1_dqn = np.max(np.abs(Object_init1 - Z1_dqn) * Weight1, axis=1)
        newObj1_dqn = np.max(np.abs(Object1 - Z1_dqn) * Weight1, axis=1)
        DELTA_dqn = np.abs(oldObj1_dqn - newObj1_dqn) / oldObj1_dqn
        Temp_dqn = DELTA_dqn < U
        Pi_1[~Temp_dqn] = 1
        Pi_1[Temp_dqn] = (0.95 + 0.05 * DELTA_dqn[Temp_dqn] / U) * Pi_1[Temp_dqn]
        oldObj1_dqn = newObj1_dqn.copy()

        # 归一化Tchebycheff聚合（子种群B）
        # （类似子种群A的代码结构，需补充）
        # ------------------------- 归一化的切比雪夫聚合 -------------------------
        for subgeneration in range(5):
            # Choose I
            Bounday = np.where(np.sum(Weight < 1e-3, axis=1) == (obj_no - 1))[0]
            I2 = np.concatenate([
                tournamentselect_utility.tournamentselect_utility(Pi_2, population_num // 5 - len(Bounday), 10),
                Bounday
            ])

            # For each solution in I
            for idx in I2:
                # knowledge-drival operator selection
                op = Knowledge_drival.Knowledge_drival(CV_2, KS_2, K)

                # Choose the parents
                if np.random.rand() < 0.9:
                    # 从邻域中随机排列并选择
                    P = Neighbor[idx, np.random.permutation(Neighbor.shape[1])]
                else:
                    # 全局随机排列
                    P = np.random.permutation(population_num)

                # Generate an offspring based operator
                parent = population2[idx, :]
                Offspring = mating.mating(selectv, op, parent, population2, P, MNumber, EP,global_vars)

                # 计算适应度并模糊化
                Object_Off = fuzzyEx.fuzzy(Fitnessvalue.Fitnessvalue(Offspring.reshape(1, -1),global_vars),2)
                Object_Off = np.round(Object_Off)

                # Update the ideal point
                Z2 = np.minimum(Z2, Object_Off)

                # Update the solutions in P by Tchebycheff approach
                denominator = Z_bad - Z2 + 1e-6  # 防止除以零

                # 计算旧解的g值
                g_old = np.max(
                    (np.abs(Object2[P] - Z2) / denominator) * Weight2[P],
                    axis=1
                )

                # 计算新解的g值
                g_new = np.max(
                    (np.abs(Object_Off - Z2) / denominator) * Weight2[P],
                    axis=1
                )

                # 找到需要替换的解
                replace = np.where(g_old > g_new)[0][:NR]
                if len(replace) > 0:
                    for r_idx in replace:
                        population2[P[r_idx]] = Offspring
                        Object2[P[r_idx]] = Object_Off

                # Update knowledge set (FIFO队列)
                TIR = np.sum((g_old[replace] - g_new[replace]) / (g_old[replace] + 1e-6))
                # 移除旧知识，添加新知识
                KS_2 = np.roll(KS_2, -1, axis=1)
                KS_2[:, -1] = [op, TIR]

                # Update Credit value of each operator
                Reward = np.zeros(K)
                for k in range(K):
                    Reward[k] = np.sum(KS_2[1, KS_2[0] == k])
                CV_2 = Reward / (np.sum(Reward) + 1e-6)

        # Update Pi for each solution
        Z_bad_new = np.max(Object2, axis=0)
        if iter == 0:  # Python中iter从0开始
            oldObj2 = np.max(
                (np.abs(Object_init2 - Z2) / (Z_bad - Z2 + 1e-6)) * Weight2,
                axis=1
            )
        newObj2 = np.max(
            (np.abs(Object2 - Z2) / (Z_bad - Z2 + 1e-6)) * Weight2,
            axis=1
        )
        DELTA = np.abs(oldObj2 - newObj2) / (oldObj2 + 1e-6)  # 防止除以零
        Temp = DELTA < U
        Pi_2[~Temp] = 1
        Pi_2[Temp] = (0.95 + 0.05 * DELTA[Temp] / U) * Pi_2[Temp]
        oldObj2 = newObj2.copy()
        Z_bad = Z_bad_new.copy()
        # 合并更新EP
        merge = np.vstack((EP, np.hstack((population1, Object1)), np.hstack((population2, Object2))))
        merge = np.unique(merge, axis=0)
        Final_population = non_domination_sort_mod_min.non_domination_sort_mod_min(merge, obj_no, MNumber)
        frontnumber = np.where(Final_population[:, MNumber + 2] == 1)[0][-1] + 1
        if frontnumber > nEP:
            f = Final_population[:frontnumber][
                np.lexsort((-Final_population[:, MNumber + 3], Final_population[:, MNumber + 2]))]
            EP = f[:nEP, :MNumber + 2]
        else:
            EP = Final_population[:frontnumber, :MNumber + 2]

        if (iter % wag == 0) and (iter >= IP * Max_iteration):
            # 调用updateWeight和updateWeightU（需实现）
            population_object1_input = np.hstack((population1, Object1))
            population_object1, Weight1, Pi_1 = updateWeight.updateWeight(
                population_object1_input, Weight1, Z1_dqn, EP, rate_update_weight * population_num, Pi_1
            )
            population1 = population_object1[:, :MNumber]
            Object1 = population_object1[:, MNumber:MNumber + 2]

            # 处理第二个种群
            population_object2_input = np.hstack((population2, Object2))
            population_object2, Weight2, Pi_2 = updateWeightU.updateWeightU(
                population_object2_input, Weight2, Z2, EP, rate_update_weight * population_num, Pi_2
            )
            population2 = population_object2[:, :MNumber]
            Object2 = population_object2[:, MNumber:MNumber + 2]
            # pass

        # 可视化
        #子种群进化图

        # 可视化（建议：每隔若干代保存一次）
        if (iter % 10 == 0) or (iter == Max_iteration - 1):
            fig1 = plt.figure(1)
            plt.clf()
            plt.scatter(Object1[:, 0], Object1[:, 1], marker='*', s=5)
            plt.scatter(Object2[:, 0], Object2[:, 1], marker='o', s=5)
            plt.title('Evolutionary map of subpopulations')
            plt.xlabel('TC(yuan)')
            plt.ylabel('ETPT(hour)')
            plt.legend(['Subpopulation 1', 'Subpopulation 2'])
            fig1.savefig(os.path.join(respath, f'evolution_iter_{iter:03d}.png'), dpi=200, bbox_inches="tight")
            plt.close(fig1)

            fig2 = plt.figure(2)
            plt.clf()
            plt.scatter(EP[:, MNumber], EP[:, MNumber + 1], marker='*', s=10)
            plt.title('Pareto front')
            plt.xlabel('TC(yuan)')
            plt.ylabel('ETPT(hour)')
            fig2.savefig(os.path.join(respath, f'pareto_iter_{iter:03d}.png'), dpi=200, bbox_inches="tight")
            plt.close(fig2)

        # 保存结果
    print("Object1:", Object1)
    print("Object2:", Object2)
    print("EP:", EP)
    plt.figure(1).savefig(os.path.join(respath, 'evolution_process_text.png'))
    plt.figure(2).savefig(os.path.join(respath, 'pareto_front_text.png'))
    np.save(os.path.join(respath, 'EP_text1.npy'), EP)
    metrics = {
        "instance": args.instance,
        "run_id": args.run_id,
        "seed": args.seed,
        "final_ep_size": int(EP.shape[0]),
        "obj1_mean": [float(np.mean(Object1[:, 0])), float(np.mean(Object1[:, 1]))],
        "obj2_mean": [float(np.mean(Object2[:, 0])), float(np.mean(Object2[:, 1]))],
    }
    with open(os.path.join(respath, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    #决策结果输出
    """
              G:（根据时间窗急缓）根据编码生成车辆巡回路线
              G'：优化的回环路线;DBT：配送最佳时间矩阵
              GDTW:{团分策略优化获得的批次组成，理想最早晚配送时刻，运输模糊时间，路游时间}
              GSI:记录车辆巡回环的索引次序，并在后续的甘特图绘制中也需要用到
              GPT:储存批次在各产线上的生产持续时间
              GPN:储存批次在各产线上的产品数;
              GST:根据GDT逆序调整批次的排产
              GST:生产开始时间 产品*批次
              GFT:生产完成时间 产品*批次
              GDT:批次模糊配送时间 
              stockoccupy:
    """
    # G = S1_routing.S1_routing(np, global_vars['timewindows'], global_vars['vcapacity'], global_vars['occupy'],
    #                           global_vars['timespan'], global_vars['X'])
    # #需要修改代码
    # G, DBT = S2_besttime.S2_besttime(G, global_vars['timewindows'], global_vars['timespan'], global_vars['X'],
    #                                  global_vars['occupy'], global_vars['Re'], global_vars['Rd'])
    # GDTW, GSI, GPT, GPN = S3_groupDPtime.S3_groupDPtime(G, DBT, global_vars['produce'], global_vars['timespan'],
    #                                                     global_vars['X'], global_vars['takt'])
    # GST, GFT, GDT, stockoccupy = S3_PLadjustment.S3_PLadjustment(G, GPT, GPN, GSI, GDTW,global_vars['pallet'])
import numpy as np

class DynamicMinMaxScaler:
    def __init__(self, window_size=1000, feature_dim=6):
        self.window_size = window_size  # 滑动窗口大小（可调）
        self.feature_dim = feature_dim  # 数值特征维度（你的后6维）
        self.value_buffer = []  # 存储最近window_size个数值样本
        self.current_min = np.zeros(feature_dim)  # 当前窗口最小值
        self.current_max = np.zeros(feature_dim)  # 当前窗口最大值

    def update(self, new_num_vec):
        """新增数值样本，更新窗口和最值"""
        # new_num_vec：新的数值特征，shape=(6,)
        self.value_buffer.append(new_num_vec)
        # 窗口超过大小则剔除最旧样本
        if len(self.value_buffer) > self.window_size:
            self.value_buffer.pop(0)
        # 更新当前窗口的最值（至少有1个样本才更新）
        if len(self.value_buffer) > 0:
            buffer_array = np.array(self.value_buffer)  # shape=(N,6)
            self.current_min = buffer_array.min(axis=0)
            self.current_max = buffer_array.max(axis=0)

    def normalize(self, num_vec):
        """用当前窗口最值归一化数值特征"""
        # 防除零（若窗口只有1个样本，或某维度值全相同）
        range_vec = self.current_max - self.current_min
        range_vec = np.where(range_vec == 0, 1e-8, range_vec)
        # 缩放到[-1,1]
        normalized = ((num_vec - self.current_min) / range_vec) * 2 - 1
        # 可选：截断极端值（避免新样本超出窗口最值导致归一化后溢出）
        normalized = np.clip(normalized, -1.5, 1.5)
        return normalized
if __name__ == '__main__':
    args = parse_args()
    KDCEA(args)
