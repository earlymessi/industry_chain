from flask import Flask, redirect

def create_app():
    app=Flask(__name__)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['MIME_TYPES'] = {'.css': 'text/css'}  # 显式设置 MIME 类型
    app.secret_key="adhgoagnglaiejaklndduhosn"

    @app.after_request
    def _ensure_utf8_charset(response):
        ct = response.content_type or ''
        if ct and 'charset=' not in ct.lower():
            if 'text/html' in ct or 'application/json' in ct:
                response.headers['Content-Type'] = f'{ct}; charset=utf-8'
        return response

    from .views import schedulePage
    from .views import  datashow
    app.register_blueprint(schedulePage.schePage)
    app.register_blueprint(datashow.ds)

    @app.route("/")
    def index():
        return redirect("/schedulePage/dataShow")
    return app