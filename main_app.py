# main_app.py
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_cors import CORS  # 1. 必须导入 CORS
from flask_admin import Admin  # 1. 导入
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash
from routes.info import info_bp
import config


# 导入蓝图
from models import db, User, EmailVerification, Place, Trip, TripItem, Expense, CalendarEvent
from routes.main import main_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.proxy import proxy_bp  # 2. 新增导入 proxy
from routes.calendar import calendar_bp 
from routes.translate import translate_bp
from routes.tts import tts_bp

# 初始化 Flask 应用
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.from_object(config)
app.secret_key = config.FLASK_SECRET_KEY

db.init_app(app)

admin = Admin(app, name='GogoTrip Admin')

admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(EmailVerification, db.session))
admin.add_view(ModelView(Place, db.session))
admin.add_view(ModelView(Trip, db.session))
admin.add_view(ModelView(TripItem, db.session))
admin.add_view(ModelView(Expense, db.session))
admin.add_view(ModelView(CalendarEvent, db.session))

# 4. 配置允许跨域 (React 端口通常是 3000)
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": app.config.get('ALLOWED_ORIGINS', config.ALLOWED_ORIGINS)
    }
})

# 注册蓝图
app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
#app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(chat_bp)
app.register_blueprint(proxy_bp) # 5. 注册 proxy
app.register_blueprint(calendar_bp) # 6. 注释掉这行
app.register_blueprint(translate_bp)
app.register_blueprint(tts_bp)
app.register_blueprint(info_bp)


with app.app_context():
    db.create_all()
    print("--- [系统] 数据库表已检查/创建 ---")

    # ==========================================
    # 👇 [新增] 硬编码创建一个 Super Admin
    # ==========================================
    admin_email = "admin@gogotrip.com"
    admin_password = "admin123"  # 请修改为你想要的复杂密码

    # 1. 检查是否存在
    existing_admin = User.query.filter_by(email=admin_email).first()
    
    if not existing_admin:
        # 2. 创建管理员
        super_admin = User(
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            full_name="Super Administrator",
            role="super_admin",       # 确保这是你在 models.py 里定义的角色值
            is_email_verified=True,   # 直接设为已验证
            avatar_url="https://ui-avatars.com/api/?name=Super+Admin&background=0D8ABC&color=fff"
        )
        db.session.add(super_admin)
        db.session.commit()
        print(f"--- [系统] Super Admin 账号已自动创建: {admin_email} / {admin_password} ---")
    else:
        print("--- [系统] Super Admin 账号已存在，跳过创建 ---")

# 运行应用
if __name__ == '__main__':
    # 确保在 0.0.0.0 运行，以便局域网也能访问
    print("应用正在启动: http://127.0.0.1:5000")

    app.run('0.0.0.0', 5000, debug=True)


