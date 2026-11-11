import numpy as np
from Scheduletool import read_para
import os
import matplotlib.pyplot as plt
from pymoo.algorithms.moo.moead import MOEAD
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.indicators.hv import Hypervolume
from pymoo.indicators.gd import GD
from pymoo.indicators.igd import IGD
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
# class Spacing:
#     def __call__(self, F):
#         n = len(F)
#         if n <= 1:
#             return 0.0
#         d = np.linalg.norm(F[:, None, :] - F[None, :, :], axis=2)
#         np.fill_diagonal(d, np.inf)
#         d_min = np.min(d, axis=1)
#         d_mean = np.mean(d_min)
#         return np.sqrt(np.mean((d_min - d_mean)**2))


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
# # MOEA/D（适合分解型问题）
# algorithm = MOEAD(
#     n_neighbors=20,
#     decomposition="pbi",
#     prob_neighbor_mating=0.9,
#     seed=1
# )

EP1=np.load('EP.npy')
EP2=np.load('EP_text2real.npy')
path = 'D:/桌面/IPSVRP-STW-FTT-CASE/Real case data/'
Data = ['traveltime', 'retailsneed', 'other']
xlsx_tail = '.xlsx'
PATH1 = os.path.join(path, Data[0] + xlsx_tail)
PATH2 = os.path.join(path, Data[1] + xlsx_tail)
PATH3 = os.path.join(path, Data[2] + xlsx_tail)
data = read_para.read_para(PATH1, PATH2, PATH3)
# 假设返回值为字典或元组，更新全局变量
global_vars.update(data)

# 创建结果文件夹
respath = os.path.join('result', 'Data3-4-20')
os.makedirs(respath, exist_ok=True)
print(f'Calculating {respath}')

# 参数设置
obj_no = 2  # 目标函数个数
Max_iteration = 50  # 最大迭代次数
population_num = 500  # 每个子种群中个体数目
U = 0.01  # 改进了效用函数U的基线
IP = 0.7  # 执行自适应权值调整的迭代百分比
NR = 1  # 每次更新NR中被替换的人数
KL = 1000  # 知识集RL的记录长度
K = 4  # 操作员数
rate_update_weight = 0.05  # 更新权重参数比例
wag = 20  # 利用AWA的迭代间隔
T = np.ceil(population_num / 10).astype(int)  # 邻居规模ch
nEP = np.ceil(population_num * 1.5).astype(int)  # 外部精英的最大储存量
Pi_1 = np.ones(population_num)  # 每个子问题的实用程序
Pi_2 = np.ones(population_num)  # 每个子问题的实用程序
PNumber, MNumber = global_vars['produce'].shape

# 可视化
        #子种群进化图

#绘制Pareto前沿图
plt.figure(2, dpi=150)
plt.clf()
#plt.scatter(EP1[:, MNumber], EP1[:, MNumber + 1], c='b', marker='.',s=1)
plt.scatter(EP2[:, MNumber], EP2[:, MNumber + 1], c='r', marker='.',s=5)
# def add_coordinates(EP1,EP2, color):
#     for x, y in zip(EP1[:, MNumber]+EP2[:,MNumber], EP1[:,MNumber]+EP2[:, MNumber+1]):
#         plt.text(x, y,
#                  f'({x:.2f}, {y:.2f})',  # 格式化显示2位小数
#                  color=color,
#                  fontsize=8,
#                  ha='left',  # 水平对齐方式
#                  va='bottom', # 垂直对齐方式
#                  bbox=dict(boxstyle="round,pad=0.3",  # 文字框样式
#                            fc="white",  # 背景色
#                            ec=color,    # 边框颜色
#                            lw=1))       # 边框线宽
plt.title('Pareto front')
plt.xlabel('TC(yuan)')
plt.ylabel('ETPT(hour)')
plt.pause(0.1)


# 假设你从外部文件（如CSV）加载Pareto解集（目标空间值）
# 示例数据：双目标最小化解集（替换为你的实际数据）
pareto_front1 = EP1[:,MNumber:MNumber+2]
pareto_front2 = EP2[:,MNumber:MNumber+2]

# ================================================
# 步骤2：合并解集以确定统一的参考点
# ================================================
# 合并解集以确保参考点覆盖两个解集的极值
combined_front = np.vstack([pareto_front1, pareto_front2])
# 关键配置
# ----------------------
# 确定目标方向（最小化或最大化）
IS_MINIMIZATION = True  # 根据实际问题调整

# 设置参考点（根据目标方向调整）
if IS_MINIMIZATION:
    # 最小化问题：参考点取各目标最大值 + 偏移量
    pareto_point = np.max(combined_front, axis=0) + 0.1
else:
    # 最大化问题：参考点取各目标最小值 - 偏移量
    pareto_point = np.min(combined_front, axis=0) - 0.1


# ----------------------
# 计算超体积
# ----------------------

# 生成真实Pareto前沿（示例中使用ZDT1的真实前沿）
from pymoo.problems import get_problem
problem = get_problem("zdt1")
true_pareto = problem.pareto_front()  # 真实前沿

indicator_hv = Hypervolume(ref_point=pareto_point)
indicator_gd = GD(true_pareto)
indicator_igd = IGD(true_pareto)
# indicator_spacing = Spacing()

hv1 = indicator_hv(pareto_front1)
hv2 = indicator_hv(pareto_front2)
print(f"Hypervolume: {hv1}")
print(f"Hypervolume: {hv2}")


# 计算指标
def calculate_metrics(F, name):
    print(f"\n解集 {name} 的指标：")
    print("----------------------------------")
    print(f"- 超体积 (HV): {indicator_hv(F):.4f}")
    print(f"- 世代距离 (GD): {indicator_gd(F):.4f}")
    print(f"- 反向世代距离 (IGD): {indicator_igd(F):.4f}")
    #print(f"- 分布均匀性 (Spacing): {indicator_spacing(F):.4f}")

calculate_metrics(pareto_front1, "A")
calculate_metrics(pareto_front2, "B")