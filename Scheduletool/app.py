import os
from flask import Flask, render_template, request,jsonify

from Scheduletool import create_app

# import Scheduletool.fuxian as moea_d_algorithm
# from Scheduletool import create_app


#request 传递通过url传过来的参数 request.args.get method 加post说明接受用户通过post传参 request.form postman伪造项目浏览器请求

app = create_app()
# /index?input_data=...
# /index
#     请求体:xx=...yy=... request.form｛"xx"=...,"yy"=...｝request.json

#
# @app.route('/', methods=['GET', 'POST'])
# def index():
#     # if request.method == 'POST':
#     #     # 获取用户输入
#     #     input_data = request.form.get('input_data')
#     #
#     #     # 调用算法
#     #     result = moea_d_algorithm.KDCEA()
#     #
#     #     # 返回结果到页面
#     #     return render_template('index.html', result=result)
#     #
#     # # GET请求时显示空白表单
#     return render_template('index.html')

if __name__ == '__main__':
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )

