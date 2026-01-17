import os
from dotenv import load_dotenv

# --- Base Path Configuration ---
# Ensure correct path resolution on server
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Load .env from the same directory
load_dotenv(os.path.join(BASE_DIR, '.env'))

# --- Flask Core Config ---
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

# --- Database Configuration ---
# Prefer DATABASE_URL from environment, fallback to local SQLite
SQLALCHEMY_DATABASE_URI = os.getenv(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(BASE_DIR, "gogotrip.db")
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# --- Google Gemini AI ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Google Maps / Places ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# --- Weatherstack ---
WEATHERSTACK_ACCESS_KEY = os.getenv("WEATHERSTACK_ACCESS_KEY")
WEATHERSTACK_API_URL = os.getenv(
    "WEATHERSTACK_API_URL",
    "http://api.weatherstack.com/"
)

# --- Email Configuration ---
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")  # App password required

# --- CORS Allowed Origins ---
ALLOWED_ORIGINS = [
    "https://gogotrip.teocodes.com",
    "https://info.gogotrip.teocodes.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.0.100:3000",
]

# --- Google OAuth ---
CLIENT_SECRETS_FILE = os.path.join(
    BASE_DIR,
    os.getenv("CLIENT_SECRETS_FILENAME", "credentials.json")
)

# --- Stripe ---
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

# --- Payment Gateways (ToyyibPay / HitPay) ---
TOYYIBPAY_URL = os.getenv('TOYYIBPAY_URL', 'https://dev.toyyibpay.com/index.php/api/createBill')
TOYYIBPAY_SECRET_KEY = os.getenv('TOYYIBPAY_SECRET_KEY') 
TOYYIBPAY_CATEGORY_CODE = os.getenv('TOYYIBPAY_CATEGORY_CODE')
TOYYIBPAY_REDIRECT_URL = os.getenv('TOYYIBPAY_REDIRECT_URL', 'https://gogotrip.teocodes.com/billing?status=success')

HITPAY_API_KEY = os.getenv('HITPAY_API_KEY')
HITPAY_SALT = os.getenv('HITPAY_SALT')
HITPAY_API_URL = os.getenv('HITPAY_API_URL', 'https://api.sandbox.hit-pay.com')

# --- Translation / Features ---
TIMEZONE = os.getenv('TIMEZONE', 'Asia/Kuala_Lumpur')

# Scopes for Google OAuth
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

# --- Redis / SocketIO ---
SOCKETIO_MESSAGE_QUEUE = os.getenv('REDIS_URL', None) 
