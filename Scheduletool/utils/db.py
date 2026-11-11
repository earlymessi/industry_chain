from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from datetime import datetime
from bson import ObjectId
import os

# MongoDB连接配置
MONGO_HOST = os.getenv('MONGO_HOST', '127.0.0.1')
MONGO_PORT = int(os.getenv('MONGO_PORT', 27017))
MONGO_DB = os.getenv('MONGO_DB', 'schedule_flask')
MONGO_USERNAME = os.getenv('MONGO_USERNAME', None)
MONGO_PASSWORD = os.getenv('MONGO_PASSWORD', None)

# 创建MongoDB连接
try:
    if MONGO_USERNAME and MONGO_PASSWORD:
        MONGO_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}?authSource=admin"
    else:
        MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"
    
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # 测试连接
    client.server_info()
    db = client[MONGO_DB]
    print(f"成功连接到MongoDB: {MONGO_DB}")
except ConnectionFailure as e:
    print(f"MongoDB连接失败: {e}")
    raise


# 为了兼容旧的SQL接口，提供类似的函数
def fetch_one(collection_name, query, projection=None):
    """
    查询单条记录（兼容旧接口）
    注意：为了兼容，第一个参数改为collection_name，第二个参数是查询条件字典
    """
    collection = db[collection_name]
    result = collection.find_one(query, projection)
    if result and '_id' in result:
        result['_id'] = str(result['_id'])
    return result


def fetch_all(collection_name, query=None, projection=None):
    """
    查询多条记录（兼容旧接口）
    """
    collection = db[collection_name]
    if query is None:
        query = {}
    results = list(collection.find(query, projection))
    # 将ObjectId转换为字符串
    for result in results:
        if '_id' in result:
            result['_id'] = str(result['_id'])
    return results


def create(collection_name, data):
    """
    创建记录
    """
    collection = db[collection_name]
    if isinstance(data, dict):
        data['created_at'] = datetime.now()
        result = collection.insert_one(data)
        return str(result.inserted_id)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                item['created_at'] = datetime.now()
        result = collection.insert_many(data)
        return [str(id) for id in result.inserted_ids]
    return None


def update(collection_name, query, update_data, upsert=False):
    """
    更新记录
    """
    collection = db[collection_name]
    update_data['updated_at'] = datetime.now()
    result = collection.update_one(query, {'$set': update_data}, upsert=upsert)
    return result.modified_count


def update_many(collection_name, query, update_data):
    """
    批量更新记录
    """
    collection = db[collection_name]
    update_data['updated_at'] = datetime.now()
    result = collection.update_many(query, {'$set': update_data})
    return result.modified_count


def delete(collection_name, query):
    """
    删除记录
    """
    collection = db[collection_name]
    result = collection.delete_one(query)
    return result.deleted_count


def delete_many(collection_name, query):
    """
    批量删除记录
    """
    collection = db[collection_name]
    result = collection.delete_many(query)
    return result.deleted_count


def find_by_id(collection_name, id_str):
    """
    根据ID查找记录
    """
    try:
        obj_id = ObjectId(id_str)
        result = db[collection_name].find_one({'_id': obj_id})
        if result and '_id' in result:
            result['_id'] = str(result['_id'])
        return result
    except:
        return None


# MongoDB特定的辅助函数
def get_collection(collection_name):
    """
    获取集合对象
    """
    return db[collection_name]


def aggregate(collection_name, pipeline):
    """
    聚合查询
    """
    collection = db[collection_name]
    # 调试：打印调用信息（注意生产环境应关闭或减小日志量）
    try:
        print(f"[db.aggregate] collection={collection_name} pipeline={pipeline}")
    except Exception:
        pass

    results = list(collection.aggregate(pipeline))

    # 打印返回数量（仅用于开发调试）
    try:
        print(f"[db.aggregate] returned {len(results)} documents")
        if len(results) > 0:
            # 打印首条的字段名以便快速检查结构
            first = results[0]
            print(f"[db.aggregate] first keys: {list(first.keys())}")
    except Exception:
        pass

    for result in results:
        if '_id' in result:
            if isinstance(result['_id'], ObjectId):
                result['_id'] = str(result['_id'])
    return results
