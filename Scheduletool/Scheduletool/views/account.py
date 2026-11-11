from flask import Blueprint, render_template, redirect, request, url_for, session, flash, abort
from utils import db

# ac=Blueprint('account',__name__,url_prefix='/account',template_folder='templates')
# ac=Blueprint("account",__name__,template_folder='templates')
ac=Blueprint("account",__name__)

@ac.route('/login',methods=['GET','POST'])
def login():
    if request.method=='GET':
        return render_template("login.html")
    user=request.form.get("text" )
    pwd=request.form.get("password")
        # 添加打印语句查看输入
    print(f"用户输入的用户名: {user}")
    print(f"用户输入的密码: {pwd}")
    # 获取数据库字典 - 使用MongoDB
    user_dict=db.fetch_one("users", {"user": user, "password": pwd})
    # sql = """
    #     SELECT
    #     orderinfo.*,
    #     order_items.*,
    #     productinf.name AS product_name,
    #     customerinfo.customer_name AS customer_name
    #     FROM
    #         orderinfo
    #     LEFT JOIN
    #         order_items ON orderinfo.order_id = order_items.order_id
    #     LEFT JOIN
    #         productinf ON order_items.product_id = productinf.id
    #     LEFT JOIN
    #         customerinfo ON orderinfo.customer_id = customerinfo.customer_id;
    #     """
    # orders = db.fetch_all(sql, [])
    if user_dict:
        # MongoDB返回的_id字段
        user_id = user_dict.get('_id') or user_dict.get('id')
        session["user"]={"id": user_id, "role":'管理员'}

        return redirect('/schedulePage/dataShow')
    return render_template("login.html",error="用户名或密码错误")

@ac.route('/register',methods=['GET','POST'])
def user():
    return "用户"