import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import haversine_distances
import folium

# 原始坐标数据（经度，纬度）
data = np.array([
    [112.832330, 28.302640],  # 0
    [113.092127, 28.231744],  # 1
    [113.633155, 28.168243],  # 2
    [112.568411, 28.281294],  # 3
    [109.990117, 27.547235],  # 4
    [112.615259, 26.901624],  # 5
    [112.390124, 26.414101],  # 6
    [113.137384, 29.377603],  # 7
    [112.541996, 29.534275],  # 8
    [112.912832, 27.868054],  # 9
    [111.721529, 29.036343],  # 10
    [111.486806, 28.898988],  # 11
    [113.130763, 27.842323],  # 12
    [112.378146, 28.562254],  # 13
    [113.031825, 25.785383],  # 14
    [111.982784, 27.731742],  # 15
    [111.463868, 27.230146],  # 16
    [110.458916, 29.151340],  # 17
    [109.705021, 28.262148],  # 18
    [111.616579, 26.442428],  # 19
    [111.948999, 25.577865],  # 20
    [110.601467, 27.909072],  # 21
    [112.858206, 26.418552],  # 22
    [113.594638, 28.708817],  # 23
    [111.962693, 28.909360],  # 24
    [113.348943, 27.009172],  # 25
    [112.956367, 25.401779],  # 26
    [111.324738, 27.728317],  # 27
    [111.744427, 27.264576],  # 28
    [109.595428, 27.965238],  # 29
    [111.847813, 26.585114]  # 30
])

# 转换为弧度坐标
coords_rad = np.radians(data)

# 计算Haversine距离矩阵（单位：公里）
dist_matrix = haversine_distances(coords_rad) * 6371

# DBSCAN聚类
db = DBSCAN(eps=50, min_samples=2, metric='precomputed')
labels = db.fit_predict(dist_matrix)

# 统计聚类结果
n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
n_noise = list(labels).count(-1)
print(f"聚类数量: {n_clusters}")
print(f"噪声点数量: {n_noise}")

# 可视化地图
map_center = [data[:, 1].mean(), data[:, 0].mean()]
m = folium.Map(location=map_center, zoom_start=7, tiles='CartoDB positron')

# 颜色配置（支持最多6个簇）
colors = ['#e41a1c', '#377eb8', '#4daf4a',
          '#984ea3', '#ff7f00', '#ffff33']

# 添加标记
for idx, (lon, lat) in enumerate(data):
    cluster_id = labels[idx]
    color = colors[cluster_id % len(colors)] if cluster_id != -1 else '#999999'

    folium.CircleMarker(
        location=[lat, lon],
        radius=6,
        color=color,
        fill=True,
        fill_opacity=0.7,
        popup=f"ID: {idx}\nCluster: {cluster_id}"
    ).add_to(m)

# 保存地图
m.save('hunan_clusters.html')

# 输出每个簇的成员
print("\n聚类详情：")
for cluster_id in set(labels):
    if cluster_id == -1:
        continue
    members = np.where(labels == cluster_id)[0]
    print(f"簇 {cluster_id}: 包含点 {members.tolist()}")
    print(f"    经度范围: {data[members, 0].min():.2f} - {data[members, 0].max():.2f}")
    print(f"    纬度范围: {data[members, 1].min():.2f} - {data[members, 1].max():.2f}\n")