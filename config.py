import os
from dotenv import load_dotenv

# 在开发环境中加载 .env 文件 (生产环境由系统提供)
# (您需要先: pip install python-dotenv)
load_dotenv() 

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "credentials.json")
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Google MAP 配置
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# Gemini API 配置
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

# Weatherstack API 配置
WEATHERSTACK_ACCESS_KEY = os.environ.get("WEATHERSTACK_ACCESS_KEY")

# Flask 配置
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", 'your_default_secret_key_for_dev_only')
# ...

# 检查关键密钥是否存在
if not GOOGLE_MAPS_API_KEY or not GEMINI_API_KEY or not WEATHERSTACK_ACCESS_KEY:
    print("警告：一个或多个 API 密钥未在环境变量中设置！")

# 其他设置
TIMEZONE = 'Asia/Kuala_Lumpur'

# OAuthLib 修复
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

