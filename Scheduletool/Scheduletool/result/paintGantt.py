import matplotlib

# 使用非交互式后端，适合在服务器中生成图片
matplotlib.use('Agg')

import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Polygon, Rectangle
import numpy as np
import os
from Scheduletool import read_para
from Scheduletool import S1_routing
from Scheduletool import S2_besttime
from Scheduletool import S3_groupDPtime
from Scheduletool import S3_PLadjustment
import io
import base64
# 假设已加载相关数据和变量，此处需根据实际情况替换
# 示例数据（需根据实际数据结构调整）
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

DEFAULT_EP_PATH = os.path.join(BASE_DIR, 'EP_text1.npy')
EP_PATH = os.getenv('SCHEDULETOOL_EP_PATH', DEFAULT_EP_PATH)

_data_loaded = False
EP = None
ep_codes = None
ep_codes_num = 0


def reload_data():
    """强制重新加载数据（KDCEA 求解完成后调用）。"""
    global _data_loaded
    _data_loaded = False
    _ensure_data_loaded()


def _ensure_data_loaded():
    """延迟加载数据文件，仅在实际调用绘图/计算时执行。"""
    global _data_loaded, EP, ep_codes, ep_codes_num
    if _data_loaded:
        return
    data = read_para.read_para(PATH1, PATH2, PATH3)
    global_vars.update(data)
    EP = np.load(EP_PATH)
    if EP.ndim != 2 or EP.shape[1] < 2:
        raise ValueError(f"EP 数据格式异常，期望至少 2 列（最后两列为目标值），当前形状: {EP.shape}")
    # 与 readEP 保持一致：前面列为编码，最后两列为目标值
    ep_codes = EP[:, :-2]
    ep_codes_num = ep_codes.shape[0]
    _data_loaded = True


def conculate(i):
    _ensure_data_loaded()
    # i 是排序后的索引，需要转换为原始EP的索引
    from . import readEP
    if readEP._ep_sort_index is None:
        readEP.getEp()  # 确保排序索引已计算
    original_index = readEP._ep_sort_index[i]  # 转换为原始索引
    print(f"[conculate] sorted_index={i}, original_index={original_index}")

    ep_code = ep_codes[original_index, :]  # 使用原始索引
    # ep_code=[5,5,6,6,4,5,6,5,6,6,4,5,6,5,5,4,6,5,6,4,6,5,6,4,5,5,5,6,5,6]
    # ep_code=[x-1 for x in ep_code]
    # ep_code=np.array(ep_code)
    G = S1_routing.S1_routing(ep_code, global_vars['timewindows'], global_vars['vcapacity'], global_vars['occupy'],
                              global_vars['timespan'], global_vars['X'])
    G, DBT = S2_besttime.S2_besttime(G, global_vars['timewindows'], global_vars['timespan'], global_vars['X'],
                                     global_vars['occupy'], global_vars['Re'], global_vars['Rd'])


    GDTW, GSI, GPT, GPN = S3_groupDPtime.S3_groupDPtime(G, DBT, global_vars['produce'], global_vars['timespan'],
                                                        global_vars['X'], global_vars['takt'])
    GST, GFT, GDT, stockoccupy = S3_PLadjustment.S3_PLadjustment(G, GPT, GPN, GSI, GDTW, global_vars['pallet'])
    return G,DBT,GDTW, GSI, GPT, GPN,GST, GFT, GDT, stockoccupy
def paintGantt(index):
    fig = None
    try:
        G, DBT, GDTW, GSI, GPT, GPN, GST, GFT, GDT, stockoccupy = conculate(index)
        tournum = GST.shape[1]
        batch_count = GST.shape[0]
    # c = [[0.4765625,0.10546875,0.42578125],
    #      [0.73828125,0.21484375,0.3203125],
    #      [0.92578125,0.40625,0.14453125],
    #      [0.98046875,0.703125,0.1015625],
    #      [0.984375,0.6171875,0.49609375],
    #      [0.71484375,0.70703125,0.625],
    #      [0.15234375,0.6171875,0.734375],
    #      [0.0703125,0.40625,0.51171875],
    #      [0.0078125,0.1875,0.27734375],
    #      [0,0,0.98828125],
    #      [0.91015625,0.95703125,0.62890625],
    #      [0.49609375,0.79296875,0.640625],
    #      [0.29296875,0.39453125,0.68359375],
    #      [0.65625,0.8515625,0.85546875],
    #      [0.46843,0.40392,0.93333],
    #      [0,0,0]]
    # e = [0,0,0]
    # 绘制水平基准线（车辆和批次轨道）
        colors = [
        (0.4765625, 0.10546875, 0.42578125),
        (0.73828125, 0.21484375, 0.3203125),
        (0.92578125, 0.40625, 0.14453125),
        (0.98046875, 0.703125, 0.1015625),
        (0.984375, 0.6171875, 0.49609375),
        (0.71484375, 0.70703125, 0.625),
        (0.15234375, 0.6171875, 0.734375),
        (0.0703125, 0.40625, 0.51171875),
        (0.0078125, 0.1875, 0.27734375),
        (0.0, 0.0, 0.98828125),
        (0.91015625, 0.95703125, 0.62890625),
        (0.49609375, 0.79296875, 0.640625),
        (0.29296875, 0.39453125, 0.68359375),
        (0.65625, 0.8515625, 0.85546875),
        (0.46843, 0.40392, 0.93333),
        (0.0, 0.0, 0.0)  # c{16}为黑色
    ]

        # --------------------- 绘图参数设置 ---------------------
        O_Font = 'Times New Roman'
        n_Font = 'Times New Roman'
        n_size = 7
        O_size = 9
        dot_size = 6
        O_up = 2.2
        dot_up = 1.8
        h1 = 1  # 批次矩形高度
        h2 = 1  # 三角高度
        x_tick_step = 10
        x_padding = 10
        lane_step = 4
        base_y = 4
        axis_top_padding = 12.0

        # 根据当前排程时间动态计算X轴上限，避免固定值导致图形截断
        time_candidates = []
        if GST.size:
            time_candidates.append(float(np.nanmax(GST)))
        if GFT.size:
            time_candidates.append(float(np.nanmax(GFT)))

        startGDT = GDT.get("start") or []
        endGDT = GDT.get("end") or []
        for fuzzy_time in list(startGDT) + list(endGDT):
            if fuzzy_time is None:
                continue
            try:
                time_candidates.extend([float(t) for t in fuzzy_time])
            except TypeError:
                time_candidates.append(float(fuzzy_time))

        max_time = max(time_candidates) if time_candidates else 0.0
        x_limit = max(
            x_tick_step,
            int(np.ceil((max_time + x_padding) / x_tick_step)) * x_tick_step
        )

        # --------------------- 创建图形 ---------------------
        fig, ax = plt.subplots(figsize=(12, 6), dpi=300)  # 对应MATLAB的Position设置
        ax.set_xlim(0, x_limit)
        ax.set_xticks(np.arange(0, x_limit + 1, x_tick_step))
        ax.set_yticks([])
        ax.grid(axis='x', linestyle='--', alpha=0.7)

        # --------------------- 绘制水平基准线 ---------------------
        vehicles = GDTW.get("vehicle") or []
        valid_vehicle_ids = [int(v) for v in vehicles if v is not None]
        vehicle_count = (max(valid_vehicle_ids) + 1) if valid_vehicle_ids else 1
        total_lanes = vehicle_count + batch_count

        lane_ys = [base_y + lane_step * idx for idx in range(total_lanes)]
        vehicle_ys = list(reversed(lane_ys[:vehicle_count]))
        batch_ys = list(reversed(lane_ys[vehicle_count:]))
        top_reference_y = max(batch_ys) if batch_ys else max(vehicle_ys)
        ax.set_ylim(0, top_reference_y + axis_top_padding)

        for y in vehicle_ys + batch_ys:
            ax.hlines(y, 0, x_limit, color=colors[15], linewidth=1)  # c{16}为黑色

        # --------------------- 标注车辆和批次编号 ---------------------
        # 车辆标注（V6到V1）
        for idx, y in enumerate(vehicle_ys, 1):
            ax.text(-3, y, 'V', fontname=O_Font, fontsize=O_size)
            ax.text(-2, y - 0.5, str(idx), fontname=n_Font, fontsize=n_size)

        # 批次标注（P5到P1）
        for idx, y in enumerate(batch_ys, 1):
            ax.text(-3, y, 'P', fontname=O_Font, fontsize=O_size)
            ax.text(-2, y - 0.5, str(idx), fontname=n_Font, fontsize=n_size)

        # --------------------- 主循环：绘制每个巡回环 ---------------------
        nodes = GDTW.get("nodes")
        # 记录每条车辆轨道上最近一次 R 标签的 x，用于跨巡回环避让
        vehicle_last_label_x = {}
        vehicle_label_layer = {}
        # 记录每条车辆轨道上最近一次“时间数值标签”的位置，用于专门避让数值重叠
        vehicle_last_time_x = {}
        vehicle_time_layer = {}
        for i in range(tournum):
            # 颜色索引（MATLAB mod(i,14)对应Python (i-1)%14，因为MATLAB从1开始）
            color_idx = (i) % 14 if i != 0 else 0
            color = colors[color_idx]

            # 获取车辆编号对应的Y坐标（GDTW{5,i}假设为车辆索引，需根据实际数据调整）
            vehicle_idx = int(vehicles[i]) if i < len(vehicles) else 0
            if vehicle_idx >= vehicle_count and 0 < vehicle_idx <= vehicle_count:
                # 兼容1-based车辆编号
                vehicle_idx -= 1
            vehicle_idx = max(0, min(vehicle_idx, vehicle_count - 1))
            vy = vehicle_ys[vehicle_idx]

            # --------------------- 绘制批次矩形 ---------------------
            for bid in range(batch_count):
                y = batch_ys[bid]
                start = GST[bid, i]
                end = GFT[bid, i]
                rect = Rectangle(
                    xy=(start, y),
                    width=end - start,
                    height=h1,
                    facecolor=color,
                    alpha=0.5
                )
                ax.add_patch(rect)

            # --------------------- 绘制出发对齐线 ---------------------
            if i < len(startGDT):
                departure_time = startGDT[i][0]  # 假设GDT[i][0]是出发时间三角的中间值
                ax.plot([departure_time, departure_time], [vy, top_reference_y], color=color, linewidth=1)

            # --------------------- 绘制巡回环时间三角 ---------------------
            gdt = []
            gdt.append(startGDT[i])
            gdt.append(endGDT[i])

            num = len(GSI)
            is_first_tour = (np.where(GSI == i + 1)[1][0] == 0) if i < len(GSI) else True
            # 若为第一个巡回环
            if is_first_tour or (gdt[0][0] == gdt[0][1] == gdt[0][2]):
                # 处理单个时间点的三角
                t = gdt[0][0]
                triangle = Polygon(
                    [(t, vy), (t + 0.2, vy), (t + 0.1, vy + h2)],
                    facecolor=color,
                    alpha=0.5
                )
                ax.add_patch(triangle)
                ax.text(t - 2.5, vy + 1, f'{t:.1f}', fontname=n_Font, fontsize=n_size)
            else:
                # 处理模糊时间三角
                a, m, b = gdt[0]
                triangle = Polygon(
                    [(a, vy), (m, vy + h2), (b, vy)],
                    facecolor=color,
                    alpha=0.5
                )
                ax.add_patch(triangle)
                ax.text(m - 2.5, vy + 1, f'({a:.1f},{m:.1f},{b:.1f})', fontname=n_Font, fontsize=n_size)

            # --------------------- 绘制返回时间三角 ---------------------
            a_r, m_r, b_r = gdt[1]
            triangle_r = Polygon(
                [(a_r, vy), (m_r, vy - h2), (b_r, vy)],
                facecolor=color,
                alpha=0.5
            )
            ax.add_patch(triangle_r)
            ax.text(m_r - 2.5, vy - 1, f'({a_r:.1f},{m_r:.1f},{b_r:.1f})', fontname=n_Font, fontsize=n_size)

            # --------------------- 绘制零售商访问时间三角（模拟逻辑）---------------------
            early, ness, last = 30, 35, 40  # 模拟初始时间
            node = nodes[i]
            nodenum = len(node)
            X = global_vars["X"]
            timespan = global_vars["timespan"]
            min_label_gap = 3.0  # 标签最小横向间距（跨巡回环也生效）

            for j in range(nodenum):  # 假设每个巡回环访问3个零售商
                if j == 0:
                    early = gdt[0][0] + X.get(node[j])[0]  # + np.random.uniform(1, 5)
                    ness = gdt[0][1] + X.get(node[j])[1]  # + np.random.uniform(1, 5)
                    last = gdt[0][2] + X.get(node[j])[2]  # + np.random.uniform(1, 5)
                else:
                    tp = (node[j], node[j - 1])
                    early += timespan.get(tp)[0]  # np.random.uniform(2, 4)
                    ness += timespan.get(tp)[0]  # np.random.uniform(2, 4)
                    last += timespan.get(tp)[0]  # np.random.uniform(2, 4)

                rt_triangle = Polygon(
                    [(early, vy), (ness, vy + h2), (last, vy)],
                    facecolor=color,
                    alpha=0.5
                )
                ax.add_patch(rt_triangle)
                # 时间数值标签（对应 R1/R2 的数值）做独立避让，减少互相覆盖
                time_text = f'{early:.1f}/{ness:.1f}/{last:.1f}'
                est_time_width = max(2.4, len(time_text) * 0.24)  # 估算文本占用宽度（数据坐标）
                last_time_x = vehicle_last_time_x.get(vehicle_idx, -1e9)
                time_label_x = ness if (ness - last_time_x >= est_time_width) else (last_time_x + est_time_width)
                vehicle_last_time_x[vehicle_idx] = time_label_x
                time_layer = vehicle_time_layer.get(vehicle_idx, 0)
                if time_label_x > ness + 1e-8:
                    time_layer = (time_layer + 1) % 4
                else:
                    time_layer = j % 2
                vehicle_time_layer[vehicle_idx] = time_layer
                # 增大纵向分层间距，避免数值标签上下挤压
                time_label_y = vy + 0.25 + 1.15 * time_layer

                ax.plot(
                    [ness, time_label_x], [vy + h2, time_label_y - 0.08],
                    color=color, linewidth=0.6, alpha=0.55
                )
                ax.text(
                    time_label_x, time_label_y, time_text,
                    fontsize=n_size - 0.2, fontname=n_Font, ha='center', va='bottom', alpha=0.9,
                    bbox=dict(facecolor='white', edgecolor='none', alpha=0.72, pad=0.35)
                )

                # 节点标签采用单个 "Rk" 文本，并确保最小横向间距防止互相遮挡
                last_x = vehicle_last_label_x.get(vehicle_idx, -1e9)
                r_label_x = ness if (ness - last_x >= min_label_gap) else (last_x + min_label_gap)
                vehicle_last_label_x[vehicle_idx] = r_label_x

                # 若发生挤压位移则切换到更高一层，减少重叠
                layer = vehicle_label_layer.get(vehicle_idx, 0)
                if r_label_x > ness + 1e-8:
                    layer = (layer + 1) % 3
                else:
                    layer = j % 2
                vehicle_label_layer[vehicle_idx] = layer
                # R 标签层间距也同步拉大
                r_label_y = vy + O_up + 1.25 * layer

                # 连接线：指明标签对应的实际节点位置
                ax.plot(
                    [ness, r_label_x], [vy + h2, r_label_y - 0.1],
                    color=color, linewidth=0.7, alpha=0.7
                )
                ax.text(
                    r_label_x, r_label_y, f'R{j + 1}',
                    fontname=O_Font, fontsize=O_size - 1, ha='center', va='bottom',
                    bbox=dict(facecolor='white', edgecolor='none', alpha=0.82, pad=0.45)
                )

        # --------------------- 最终设置 ---------------------
        plt.title('Production-Distribution Fuzzy Gantt Chart', fontname=O_Font, fontsize=11)
        plt.xlabel('Time', fontname=O_Font, fontsize=9)
        plt.tight_layout()

        # 将图片转为Base64
        buffer = io.BytesIO()
        fig.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        buffer.close()
        return image_base64
    finally:
        if fig is not None:
            plt.close(fig)
if __name__ == '__main__':
    paintGantt(4)