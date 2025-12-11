import os
from dotenv import load_dotenv

# --- 基础路径配置 ---
# 获取当前文件所在的绝对目录，确保在Server上也能找到同级文件
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# 加载同目录下的 .env 文件
load_dotenv(os.path.join(BASE_DIR, '.env'))

# --- Flask 基础配置 ---
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "your_super_secret_key_change_me")

# --- Database 配置 (新增) ---
# 优先读取环境变量，如果没有则使用本地 SQLite 文件
SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'gogotrip.db'))
SQLALCHEMY_TRACK_MODIFICATIONS = False

# --- Google Gemini AI ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Google Maps / Places ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# --- Weatherstack 天气 ---
WEATHERSTACK_ACCESS_KEY = os.getenv("WEATHERSTACK_ACCESS_KEY")
WEATHERSTACK_API_URL = os.getenv("WEATHERSTACK_API_URL", "http://api.weatherstack.com/")

# --- Email Configuration (新增) ---
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587)) # 端口需要转为整数
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD") # 务必在 .env 中设置应用专用密码

# --- CORS Allowed Origins (新增) ---
ALLOWED_ORIGINS = [
    "https://gogotrip.teocodes.com/",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.0.100:3000", # 如果你需要局域网测试
]

# --- Google OAuth 配置 ---
# 使用 os.path.join 确保路径正确
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, os.getenv("CLIENT_SECRETS_FILENAME", "credentials.json"))

SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

TIMEZONE = os.getenv("TIMEZONE", "Asia/Kuala_Lumpur")