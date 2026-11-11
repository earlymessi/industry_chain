import numpy as np


from Scheduletool import read_para
import os
from Scheduletool import S1_routing
from Scheduletool import S2_besttime
from Scheduletool import S3_groupDPtime
from Scheduletool import S3_PLadjustment
# current_dir = os.path.dirname(os.path.abspath(__file__))
# # 构建到EP.npy的相对路径
# file_path = os.path.join(current_dir, 'Data3-4-20', 'EP.npy')
# EP = np.load(file_path)
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.dirname(BASE_DIR)
DEFAULT_DATA_DIR = os.path.join(PACKAGE_DIR, 'result', 'excel')
DATA_DIR = os.getenv('SCHEDULETOOL_DATA_DIR', DEFAULT_DATA_DIR)

path = DATA_DIR
Data = ['traveltime', 'retailsneed', 'other']
xlsx_tail = '.xlsx'
PATH1 = os.path.join(path, Data[0] + xlsx_tail)
PATH2 = os.path.join(path, Data[1] + xlsx_tail)
PATH3 = os.path.join(path, Data[2] + xlsx_tail)
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

DEFAULT_EP_PATH = os.path.join(BASE_DIR, 'EP_text1.npy')
EP_PATH = os.getenv('SCHEDULETOOL_EP_PATH', DEFAULT_EP_PATH)

_data_loaded = False
EP = None
ep_codes = None
ep_codes_num = 0
_ep_sort_index = None


def reload_data():
    """强制重新加载数据（KDCEA 求解完成后调用）。"""
    global _data_loaded, _ep_sort_index
    _data_loaded = False
    _ep_sort_index = None
    _ensure_data_loaded()


def _ensure_data_loaded():
    """延迟加载数据文件，仅在实际需要时执行。"""
    global _data_loaded, EP, ep_codes, ep_codes_num
    if _data_loaded:
        return
    data = read_para.read_para(PATH1, PATH2, PATH3)
    global_vars.update(data)
    EP = np.load(EP_PATH)
    if EP.ndim != 2 or EP.shape[1] < 2:
        raise ValueError(f"EP 数据格式异常，期望至少 2 列（最后两列为目标值），当前形状: {EP.shape}")
    # 自适应列数：前面列为编码，最后两列为目标值
    ep_codes = EP[:, :-2]
    ep_codes_num = ep_codes.shape[0]
    _data_loaded = True


def getEp():
    _ensure_data_loaded()
    global _ep_sort_index
    ep=EP[:, -2:]

    def _percent_better_in_comparable(values):
        """
        计算“优于多少百分比的解”（最小化目标）：
        - 只在严格可比较样本中计算（忽略与当前值相等的解）
        - 优于比例 = 严格更差数量 / (严格更好数量 + 严格更差数量)
        这样同值解同分，并且不会因为并列项被稀释。
        """
        values = np.asarray(values, dtype=float)
        n = values.shape[0]
        if n == 0:
            return np.zeros(n, dtype=float)
        better_counts = (values[None, :] < values[:, None]).sum(axis=1)  # 严格更好（更小）
        worse_counts = (values[None, :] > values[:, None]).sum(axis=1)   # 严格更差（更大）
        comparable = better_counts + worse_counts
        percent = np.zeros(n, dtype=float)
        mask = comparable > 0
        percent[mask] = (worse_counts[mask] / comparable[mask]) * 100.0
        return percent

    cost_percent = _percent_better_in_comparable(ep[:, 0])
    time_percent = _percent_better_in_comparable(ep[:, 1])
    ep_persentage = np.column_stack((cost_percent, time_percent))

    ep=np.hstack((ep, ep_persentage))
    ep_index=np.lexsort((ep[:, 1], ep[:, 0]))
    _ep_sort_index = ep_index  # 保存排序索引映射
    ep=ep[ep_index]
    return ep


def readinf(i):
    _ensure_data_loaded()
    global _ep_sort_index
    if _ep_sort_index is None:
        getEp()  # 确保排序索引已计算
    original_index = _ep_sort_index[i]  # 转换为原始索引
    
    ep_code = ep_codes[original_index, :]  # 使用原始索引
    G = S1_routing.S1_routing(ep_code, global_vars['timewindows'], global_vars['vcapacity'], global_vars['occupy'],
                              global_vars['timespan'], global_vars['X'])
    G, DBT = S2_besttime.S2_besttime(G, global_vars['timewindows'], global_vars['timespan'], global_vars['X'],
                                     global_vars['occupy'], global_vars['Re'], global_vars['Rd'])
    GDTW, GSI, GPT, GPN = S3_groupDPtime.S3_groupDPtime(G, DBT, global_vars['produce'], global_vars['timespan'],
                                                        global_vars['X'], global_vars['takt'])
    GST, GFT, GDT, stockoccupy = S3_PLadjustment.S3_PLadjustment(G, GPT, GPN, GSI, GDTW, global_vars['pallet'])

    # np.savez('data.npz', array1=G, array2=DBT, array3=GDTW, array4=GSI, array5=GPT, array6=GPN, array7=GST, array8=GFT,
    #          array9=GDT, array10=stockoccupy)
    infos=[]
    infos_2=[]
    ###数据可视化
    #按批次输出信息
    info=f"""
    成本：{EP[original_index, -2]}
    效率指标：{EP[original_index, -1]}
    """
    # print(info)
    infos.append(info)
    batchnum=GST.shape[1]
    for j in range(batchnum):
        message = []

        batch=j+1
        node=GDTW.get("nodes")[j]
        nodeshow=[num+1 for num in node]
        vnumber=GDTW.get("vehicle")[j]
        vstart=GDTW.get("start")[j]
        vend=GDTW.get("end")[j]
        transport_time=GDTW.get("transport_time")[j]
        productnumber=GST.shape[0]
        productstart=GST[:,j]
        productend=GFT[:,j]
        stockinfo=vstart-productend
        # message.append(batch)
        # message.append(nodeshow)
        # message.append(vnumber)
        # message.append(vstart)
        # message.append(transport_time)
        # message.append(stockinfo.tolist())
        # message.append(productstart.tolist())
        # message.append(productend.tolist())
        info=f"""
        批次信息: 第{batch}批 订单序号为:{nodeshow}
        车辆信息: 运输车辆编号:{vnumber} 车辆开始运输时间:{vstart}
        运输信息: 整体运输时间: {transport_time}
        仓储信息: 每个产品完成生产后预计等待运输的时间:{stockinfo}
        生产信息: 生产开始时间: {productstart} 生产完成时间: {productend}
        """

        info_2={
            "batch": batch,
            "nodeshow": nodeshow,
            "vnumber": vnumber,
            "vstart": vstart,
            "transport_time": transport_time,
            "stockinfo": stockinfo.tolist(),
            "productstart": productstart.tolist(),
            "productend": productend.tolist()
        }
        # print(info)
        infos.append(info)

        infos_2.append(info_2)
        # 批次信息:第i批GSI 哪些订单GDTW nodes
        # 车辆信息:车辆编号 GDTW vehicle
        # 运输信息:整体运输时间 GDTW transport_time
        # 仓储信息:
        # 生产信息:生产开始时间 生产完成时间
        # 批次信息:第i批 订单号为：node
        # 车辆信息:运输车辆编号：vnumber
        # 运输信息:整体运输时间: transport_time
        # 仓储信息:
        # 生产信息:生产开始时间:productstart 生产完成时间:productend
    return infos,infos_2


if __name__ == '__main__':
    while(1):
        n = input("请输入前沿解索引：")
        readinf(int(n))












