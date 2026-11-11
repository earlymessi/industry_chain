# # -*- coding: utf-8 -*-
# def _init():#初始化
#     global global_vars
#     global_vars = {}
#
# def set_value(key,value):
#     """ 定义一个全局变量 """
#     global_vars[key] = {
#         '''
#             'timespan': 零售商i到零售j的模糊旅途时间, 'X': 工厂到零售商的距离, 'produce': 零售商需求, 'timewindows': 时间窗, 'takt': 生产速度,
#             'pc': 产线成本, 'pallet': 单位产品占据托盘, 'vcapacity': 车辆容量, 'vfixcost': 车辆固定成本, 'vvarcost': 车辆可变成本,
#             'occupy': None, 'Re': 1, 'Rd': 3, 'holding': 10
#         '''
#         'timespan': None, 'X': None, 'produce': None, 'timewindows': None, 'takt': None,
#         'pc': None, 'pallet': None, 'vcapacity': None, 'vfixcost': None, 'vvarcost': None,
#         'occupy': None,
#         'Re': 1, 'Rd': 3, 'holding': 10
#     }
#
# def get_value(key,defValue=None):　　""" 获得一个全局变量,不存在则返回默认值 """
#     try:
#         return global_vars[key]
#     except KeyError:
#         return defValue
from .fuxian import global_vars
try:
    timespan_value = global_vars['timespan']
    print(f"timespan: {timespan_value}")

    X_value = global_vars['X']
    print(f"X: {X_value}")

    produce_value = global_vars['produce']
    print(f"produce: {produce_value}")

    timewindows_value = global_vars['timewindows']
    print(f"timewindows: {timewindows_value}")

    takt_value = global_vars['takt']
    print(f"takt: {takt_value}")

    pc_value = global_vars['pc']
    print(f"pc: {pc_value}")

    pallet_value = global_vars['pallet']
    print(f"pallet: {pallet_value}")

    vcapacity_value = global_vars['vcapacity']
    print(f"vcapacity: {vcapacity_value}")

    vfixcost_value = global_vars['vfixcost']
    print(f"vfixcost: {vfixcost_value}")

    vvarcost_value = global_vars['vvarcost']
    print(f"vvarcost: {vvarcost_value}")

    occupy_value = global_vars['occupy']
    print(f"occupy: {occupy_value}")

    Re_value = global_vars['Re']
    print(f"Re: {Re_value}")

    Rd_value = global_vars['Rd']
    print(f"Rd: {Rd_value}")

    holding_value = global_vars['holding']
    print(f"holding: {holding_value}")

except KeyError as e:
    print(f"KeyError: {e}")
