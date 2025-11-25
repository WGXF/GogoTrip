import os
from dotenv import load_dotenv

# 加载同目录下的 .env 文件
load_dotenv()

# --- Flask 基础配置 ---
# main_app.py 第14行使用
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev_secret_key_change_me")

# --- Google Gemini AI ---
# ai_agent.py 和 google_calendar.py 使用
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Google Maps / Places ---
# tools.py 使用
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# --- Weatherstack 天气 ---
# tools.py 使用
WEATHERSTACK_ACCESS_KEY = os.getenv("WEATHERSTACK_ACCESS_KEY")
WEATHERSTACK_API_URL = os.getenv("WEATHERSTACK_API_URL", "http://api.weatherstack.com/")

# --- 其他配置 ---
# google_calendar.py 使用

# --- Google OAuth 配置 ---

# 变量名必须保留叫 CLIENT_SECRETS_FILE，否则 auth.py 会报错
# 后面改成你的实际文件名 'credentials.json'
CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE", "credentials.json")

# 必须加上 SCOPES，因为报错日志显示 auth.py 也在用它
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]


TIMEZONE = os.getenv("TIMEZONE", "Asia/Kuala_Lumpur")


