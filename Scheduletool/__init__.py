from flask import Flask, request, session, redirect


#拦截器
def auth():
    if request.path.startswith('/static'):
        return
    if request.path =='/login':
        return
    user=session.get("user")
    if user :
        return
    return redirect('/login')

def create_app():
    app=Flask(__name__)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['MIME_TYPES'] = {'.css': 'text/css'}  # 显式设置 MIME 类型
    app.secret_key="adhgoagnglaiejaklndduhosn"

    from .views import account
    from .views import schedulePage
    from .views import  datashow
    app.register_blueprint(account.ac)#注册到app
    app.register_blueprint(schedulePage.schePage)
    app.register_blueprint(datashow.ds)

    app.before_request(auth)
    return app