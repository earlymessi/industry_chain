"""
路径规划模块
基于Dijkstra算法的AGV路径规划
支持动态障碍物避让、多AGV路径协调
"""

import heapq
from typing import List, Tuple, Dict, Set, Optional
import numpy as np


class PathPlanner:
    """基于Dijkstra的路径规划器"""
    
    def __init__(self, grid_size: int = 50):
        self.grid_size = grid_size
        self.obstacles: Set[Tuple] = set()  # 障碍物位置
        self.traffic: Dict[Tuple, float] = {}  # 路段拥堵状态
    
    def plan_path(self, start: List[float], goal: List[float], 
                  obstacles: Set[Tuple] = None, 
                  agv_positions: List[List[float]] = None) -> Tuple[List, float]:
        """
        使用Dijkstra算法规划最短路径
        
        Args:
            start: 起点坐标 [x, y]
            goal: 终点坐标 [x, y]
            obstacles: 障碍物集合
            agv_positions: 其他AGV位置列表（用于避障）
            
        Returns:
            path: 路径点列表
            distance: 总距离
        """
        start_node = tuple(start)
        goal_node = tuple(goal)
        
        # 合并障碍物
        all_obstacles = set(self.obstacles)
        if obstacles:
            all_obstacles.update(obstacles)
        if agv_positions:
            for pos in agv_positions:
                all_obstacles.add(tuple(pos))
        
        # Dijkstra算法
        distances = {start_node: 0}
        predecessors = {start_node: None}
        pq = [(0, start_node)]
        visited = set()
        
        while pq:
            current_dist, current_node = heapq.heappop(pq)
            
            if current_node in visited:
                continue
            visited.add(current_node)
            
            if current_node == goal_node:
                break
            
            # 获取相邻节点（8方向移动）
            neighbors = self._get_neighbors(current_node, all_obstacles)
            
            for neighbor in neighbors:
                neighbor_tuple = tuple(neighbor)
                if neighbor_tuple in visited:
                    continue
                
                # 计算移动距离（考虑拥堵）
                move_cost = self._calculate_move_cost(current_node, neighbor_tuple)
                new_dist = current_dist + move_cost
                
                if neighbor_tuple not in distances or new_dist < distances[neighbor_tuple]:
                    distances[neighbor_tuple] = new_dist
                    predecessors[neighbor_tuple] = current_node
                    heapq.heappush(pq, (new_dist, neighbor_tuple))
        
        # 重建路径
        path = self._reconstruct_path(predecessors, start_node, goal_node)
        total_distance = distances.get(goal_node, float('inf'))
        
        return path, total_distance
    
    def _get_neighbors(self, node: Tuple, obstacles: Set[Tuple]) -> List[List[float]]:
        """获取相邻节点（8方向）"""
        x, y = node
        neighbors = []
        directions = [
            (0, 1), (1, 0), (0, -1), (-1, 0),  # 4方向
            (1, 1), (1, -1), (-1, 1), (-1, -1)  # 对角线方向
        ]
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            # 边界检查
            if 0 <= nx <= self.grid_size and 0 <= ny <= self.grid_size:
                if (nx, ny) not in obstacles:
                    neighbors.append([float(nx), float(ny)])
        
        return neighbors
    
    def _calculate_move_cost(self, from_node: Tuple, to_node: Tuple) -> float:
        """计算移动成本（考虑拥堵）"""
        base_cost = 1.0
        
        # 拥堵系数
        edge_key = (from_node, to_node) if from_node < to_node else (to_node, from_node)
        congestion = self.traffic.get(edge_key, 0)  # 0-1 拥堵程度
        
        # 拥堵时成本增加
        cost = base_cost * (1 + congestion * 2)
        
        return cost
    
    def _reconstruct_path(self, predecessors: Dict, start: Tuple, goal: Tuple) -> List:
        """重建路径"""
        path = []
        current = goal
        
        while current is not None:
            path.append([float(current[0]), float(current[1])])
            current = predecessors.get(current)
        
        path.reverse()
        
        if not path or tuple(path[0]) != start:
            return []  # 无法到达
        
        return path
    
    def update_traffic(self, position: Tuple, congestion: float):
        """更新路段拥堵状态"""
        self.traffic[position] = congestion
    
    def get_shortest_path_info(self, start: List[float], goal: List[float]) -> Dict:
        """获取最短路径信息（包含距离和时间估算）"""
        path, distance = self.plan_path(start, goal)
        
        if not path:
            return {
                "path": [],
                "distance": float('inf'),
                "estimated_time": float('inf'),
                "possible": False
            }
        
        # 估算时间（简化计算）
        avg_speed = 30  # 假设平均速度30m/min
        estimated_time = distance / avg_speed
        
        return {
            "path": path,
            "distance": distance,
            "estimated_time": estimated_time,
            "possible": True
        }


class TrafficAwarePlanner(PathPlanner):
    """交通感知路径规划器
    
    扩展基础路径规划器，支持：
    1. 实时交通状态更新
    2. 多AGV路径协调
    3. 动态重新规划
    """
    
    def __init__(self, grid_size: int = 50):
        super().__init__(grid_size)
        self.agv_positions: Dict[int, Tuple] = {}  # {agv_id: position}
        self.path_history: Dict[int, List[Tuple]] = {}  # {agv_id: [path_history]}
        
    def update_agv_position(self, agv_id: int, position: List[float]):
        """更新AGV位置"""
        self.agv_positions[agv_id] = tuple(position)
        
        # 更新障碍物（AGV当前位置成为临时障碍）
        if agv_id not in self.path_history:
            self.path_history[agv_id] = []
        self.path_history[agv_id].append(tuple(position))
    
    def plan_path_with_avoidance(self, start: List[float], goal: List[float], 
                                   exclude_agvs: List[int] = None) -> Tuple[List, float]:
        """规划路径（避开其他AGV）"""
        exclude_agvs = exclude_agvs or []
        
        # 获取需要避开的AGV位置
        obstacles = set(self.obstacles)
        for agv_id, pos in self.agv_positions.items():
            if agv_id not in exclude_agvs:
                obstacles.add(pos)
        
        # 规划路径
        return self.plan_path(start, goal, obstacles=obstacles)
    
    def detect_conflicts(self, agv_id: int, planned_path: List) -> List[Dict]:
        """检测路径冲突"""
        conflicts = []
        
        for other_id, other_pos in self.agv_positions.items():
            if other_id == agv_id:
                continue
            
            # 检查是否会在同一时间到达同一位置
            for step, pos in enumerate(planned_path):
                if tuple(pos) == other_pos:
                    conflicts.append({
                        "agv_id": other_id,
                        "position": pos,
                        "step": step,
                        "type": "position_conflict"
                    })
        
        return conflicts
    
    def replan_if_needed(self, agv_id: int, current_pos: List[float], 
                         goal: List[float], conflict_threshold: int = 3) -> Tuple[List, float]:
        """必要时重新规划路径"""
        planned_path, distance = self.plan_path_with_avoidance(current_pos, goal, [agv_id])
        
        conflicts = self.detect_conflicts(agv_id, planned_path)
        
        if len(conflicts) > conflict_threshold:
            # 冲突过多，需要重新规划
            return self.plan_path_with_avoidance(current_pos, goal, [agv_id])
        
        return planned_path, distance


# 便捷函数
def create_path_planner(grid_size: int = 50) -> PathPlanner:
    """创建路径规划器"""
    return PathPlanner(grid_size)

def calculate_distance(pos1: List[float], pos2: List[float]) -> float:
    """计算两点间距离"""
    return np.linalg.norm(np.array(pos2) - np.array(pos1))

def find_shortest_path(start: List[float], goal: List[float], 
                       obstacles: List[List[float]] = None) -> Tuple[List, float]:
    """找最短路径"""
    planner = PathPlanner()
    obs = [tuple(o) for o in obstacles] if obstacles else None
    return planner.plan_path(start, goal, obstacles=obs)
