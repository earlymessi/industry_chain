"""
数据文件路径工具函数
用于统一管理训练和评估数据的文件命名，区分不同智能体数量和训练/评估模式
"""
import os


def get_data_file_path(base_dir, filename, n_agents, is_training=True):
    """
    生成带前缀的数据文件路径
    
    参数:
        base_dir: 基础目录路径
        filename: 原始文件名（如 'accumulated_rewards.txt'）
        n_agents: 智能体数量
        is_training: 是否为训练模式（True=训练, False=评估）
    
    返回:
        完整的文件路径
    """
    # 确定类型前缀
    type_prefix = 'train' if is_training else 'eval'
    
    # 确定智能体数量前缀
    agents_prefix = f'agents{n_agents}_'
    
    # 生成新文件名
    new_filename = f'{type_prefix}_{agents_prefix}{filename}'
    
    # 返回完整路径
    return os.path.join(base_dir, new_filename)


def get_data_dir():
    """
    获取数据保存的基础目录
    
    返回:
        数据目录路径
    """
    return './my_data_and_graph/historydata'

