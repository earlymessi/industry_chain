import os
import json
import numpy as np
from sklearn.cluster import KMeans

# 无批量数据或读取失败时使用的默认坐标（经度，纬度）
# _DEFAULT_DATA = np.array([
#     [112.832330, 28.302640], [113.092127, 28.231744], [113.633155, 28.168243],
#     [112.568411, 28.281294], [109.990117, 27.547235], [112.615259, 26.901624],
#     [112.390124, 26.414101], [113.137384, 29.377603], [112.541996, 29.534275],
#     [112.912832, 27.868054], [111.721529, 29.036343], [111.486806, 28.898988],
#     [113.130763, 27.842323], [112.378146, 28.562254], [113.031825, 25.785383],
#     [111.982784, 27.731742], [111.463868, 27.230146], [110.458916, 29.151340],
#     [109.705021, 28.262148], [111.616579, 26.442428], [111.948999, 25.577865],
#     [110.601467, 27.909072], [112.858206, 26.418552], [113.594638, 28.708817],
#     [111.962693, 28.909360], [113.348943, 27.009172], [112.956367, 25.401779],
#     [111.324738, 27.728317], [111.744427, 27.264576], [109.595428, 27.965238],
#     [111.847813, 26.585114]
# ])


def _get_factory_coords(db):
    """从 customerinfo 中取工厂（customer_id 为 0 或 '0'）的坐标，返回 [经度, 纬度]；若无则返回 [0.0, 0.0]。"""
    for fid in (0, '0'):
        docs = db.fetch_all('customerinfo', {'customer_id': fid}) or []
        if docs:
            x, y = docs[0].get('address_X'), docs[0].get('address_Y')
            try:
                lon = float(x) if x is not None and x != '' else 0.0
            except (TypeError, ValueError):
                lon = 0.0
            try:
                lat = float(y) if y is not None and y != '' else 0.0
            except (TypeError, ValueError):
                lat = 0.0
            return [lon, lat]
    return [0.0, 0.0]


def _load_coordinates_from_batch_orders():
    """从当前被批量处理的订单对应的零售商读取坐标，按订单顺序返回。
    数组第 0 行为工厂坐标，第 1..n 行为零售商坐标。失败或为空时返回 None。"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, 'result', 'excel', 'last_batch_order_ids.json')
        if not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            order_ids = json.load(f)
        if not order_ids:
            return None

        from utils import db

        # 第 0 行：工厂坐标
        coords_list = [_get_factory_coords(db)]
        for oid in order_ids:
            oid_str = str(oid)
            order_docs = db.fetch_all('orderinfo', {'order_id': oid_str}) or []
            if not order_docs:
                try:
                    order_docs = db.fetch_all('orderinfo', {'order_id': int(oid)})
                except Exception:
                    pass
            if not order_docs:
                coords_list.append([0.0, 0.0])
                continue
            customer_id = order_docs[0].get('customer_id')
            if customer_id is None:
                coords_list.append([0.0, 0.0])
                continue
            cust_docs = db.fetch_all('customerinfo', {'customer_id': customer_id}) or []
            if not cust_docs:
                coords_list.append([0.0, 0.0])
                continue
            x = cust_docs[0].get('address_X')
            y = cust_docs[0].get('address_Y')
            try:
                lon = float(x) if x is not None and x != '' else 0.0
            except (TypeError, ValueError):
                lon = 0.0
            try:
                lat = float(y) if y is not None and y != '' else 0.0
            except (TypeError, ValueError):
                lat = 0.0
            coords_list.append([lon, lat])

        if not coords_list:
            return None
        return np.array(coords_list)
    except Exception:
        return None


def k_means(VNumber,MNumber):
        # 优先使用当前被批量处理的订单对应零售商的坐标（按订单顺序），否则使用默认死数据
    data = _load_coordinates_from_batch_orders()
    print("[_load_coordinates_from_batch_orders] data 供人工检查:\n", data)
    # if data is None or len(data) == 0:
    #     data = _DEFAULT_DATA.copy()


    # # 使用K-Means聚类
    # for i in range(6,16):
    #     n_clusters = i  # 可调整的簇数量
    #     kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    #     label = kmeans.fit_predict(data)
    #     # labels=np.array()
    # return label
    data_=data[0:MNumber+1]
    n_clusters = VNumber  # 可调整的簇数量
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    label = kmeans.fit_predict(data_)
    return label


# 示例调用
if __name__ == "__main__":
    import folium

    # 与 k_means() 使用相同数据源：批量订单对应零售商坐标或默认数据
    data = _load_coordinates_from_batch_orders()
    # if data is None or len(data) == 0:
    #     data = _DEFAULT_DATA.copy()

    labels = k_means()
    n_clusters = 6

    map_center = [data[:, 1].mean(), data[:, 0].mean()]
    m = folium.Map(location=map_center, zoom_start=7, tiles='CartoDB positron')
    colors = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#a65628']
    for idx, (lon, lat) in enumerate(data):
        cluster_id = labels[idx]
        color = colors[cluster_id % len(colors)]
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.7,
            popup=f"ID: {idx}\nCluster: {cluster_id}"
        ).add_to(m)
    m.save('hunan_kmeans_clusters.html')

    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    kmeans.fit(data)
    print("=== 聚类中心（经度, 纬度）===")
    for i, center in enumerate(kmeans.cluster_centers_):
        print(f"簇 {i}: [{center[0]:.6f}, {center[1]:.6f}]")
    print("\n=== 聚类成员分布 ===")
    for cluster_id in range(n_clusters):
        members = np.where(labels == cluster_id)[0]
        print(f"簇 {cluster_id}: 包含 {len(members)} 个点 - {members.tolist()}")

