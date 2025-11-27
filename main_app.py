# main_app.py
from flask import Flask
from flask_cors import CORS
# 从配置导入
import config

# 导入蓝图
from routes.main import main_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.proxy import proxy_bp
from routes.calendar import calendar_bp

# 初始化 Flask 应用
app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

# 4. 配置允许跨域 (React 端口通常是 3000)
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": ["http://localhost:3000", "https://gogotrip.teocodes.com/"]
    }
})

# 注册蓝图
app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(proxy_bp)
app.register_blueprint(calendar_bp)

# 运行应用
if __name__ == '__main__':
    # 确保在 127.0.0.1 (本地) 运行，端口 5000，开启调试模式

    app.run('0.0.0.0', 5000, debug=True)


