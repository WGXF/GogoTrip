import os

# ============================================
# gRPC / AI Stability Configuration
# ============================================
# These must be set BEFORE importing any Google/gRPC libraries
# Prevents deadlocks in multi-threaded server environments
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "false"
os.environ["GRPC_POLL_STRATEGY"] = "poll"

from flask import Flask, send_from_directory, redirect, jsonify
from flask_cors import CORS
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash
from flask_login import LoginManager
import config

# Import models
from models import (
    db, User, EmailVerification, Place, Trip, TripItem, 
    Expense, CalendarEvent, Subscription, LoginHeroConfig, 
    HeroImage, NotificationTab, UserNotificationRead, Inquiry,
    Blog, BlogLike, BlogComment, BlogSubscription, BlogReport
)


# Import blueprints
from routes.main import main_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.proxy import proxy_bp
from routes.calendar import calendar_bp 
from routes.translate import translate_bp
from routes.tts import tts_bp
from routes.admin import admin_bp
from routes.trips import trips_bp
from routes.info import info_bp
from routes.profile import profile_bp
from routes.payment import payment_bp
from routes.articles import articles_bp
from routes.places import places_bp
from routes.expenses import expenses_bp
from routes.admin_subscription import admin_subscription_bp
from routes.advertisements import advertisements_bp  
from routes.dashboard import dashboard_bp 
from routes.places_admin import places_admin_bp
from routes.login_hero import login_hero_bp
from routes.notifications import notifications_bp, announcements_bp
from routes.tickets import tickets_bp
from routes.admin_messages import admin_messages_bp
from routes.admin_chat import admin_chat_bp
from routes.realtime import init_socketio, socketio
from routes.auth_settings_extensions import settings_auth_bp
from routes.public_inquiries import public_inquiries_bp
from routes.blogs import blogs_bp


# 🆕 Import real-time translation handlers
from routes.translate_realtime import init_realtime_translation
from routes.translate_streaming import init_streaming_translation
# ============================================
# Initialize Flask Application
# ============================================
app = Flask(__name__)

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login_email'

# App configuration
app.config.from_object(config)
app.secret_key = config.FLASK_SECRET_KEY

# Initialize database
db.init_app(app)

# Initialize Flask-Admin
admin = Admin(app, name='GogoTrip Admin')
admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(EmailVerification, db.session))
admin.add_view(ModelView(Place, db.session))
admin.add_view(ModelView(Trip, db.session))
admin.add_view(ModelView(TripItem, db.session))
admin.add_view(ModelView(Expense, db.session))
admin.add_view(ModelView(CalendarEvent, db.session))
admin.add_view(ModelView(Subscription, db.session))
admin.add_view(ModelView(LoginHeroConfig, db.session))
admin.add_view(ModelView(HeroImage, db.session))
admin.add_view(ModelView(Inquiry, db.session))

# ============================================
# CORS Configuration
# ============================================
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": app.config.get('ALLOWED_ORIGINS', config.ALLOWED_ORIGINS)
    }
})

# ============================================
# Register Blueprints
# ============================================
# Core routes
app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)

# Notification routes
app.register_blueprint(notifications_bp)
app.register_blueprint(announcements_bp)

# Admin routes
app.register_blueprint(admin_bp, url_prefix='/api/admin')

# Feature routes
app.register_blueprint(chat_bp)
app.register_blueprint(proxy_bp)
# Register calendar with /api prefix (routes in file are /calendar/...) -> /api/calendar/...
app.register_blueprint(calendar_bp, url_prefix='/api')

# 🆕 Translation routes (includes /translate, /translate/audio, /translate/languages)
# Register with /api prefix -> /api/translate
app.register_blueprint(translate_bp, url_prefix='/api')

app.register_blueprint(tts_bp)
app.register_blueprint(info_bp, url_prefix='/api/info')
app.register_blueprint(profile_bp, url_prefix='/user')
app.register_blueprint(payment_bp, url_prefix='/api/payment')
app.register_blueprint(articles_bp, url_prefix='/api/articles')
app.register_blueprint(places_bp)
# Trips blueprint now has no internal prefix, so we define it here
app.register_blueprint(trips_bp, url_prefix='/api/trips')
app.register_blueprint(admin_subscription_bp, url_prefix='/api/admin-subscription')
app.register_blueprint(expenses_bp, url_prefix='/api/expenses')
app.register_blueprint(advertisements_bp, url_prefix='/api/advertisements')
app.register_blueprint(dashboard_bp, url_prefix='/api')
app.register_blueprint(places_admin_bp)
app.register_blueprint(tickets_bp)
app.register_blueprint(admin_chat_bp)
app.register_blueprint(admin_messages_bp)
app.register_blueprint(login_hero_bp)
app.register_blueprint(settings_auth_bp)
app.register_blueprint(public_inquiries_bp)
app.register_blueprint(blogs_bp)

# ============================================
# SPA Fallback Route (Automatic Path Detection)
# ============================================

# 🟢 Define all possible frontend build directories
# Flask will check these directories in order until index.html is found
POSSIBLE_FRONTEND_PATHS = [
    # 1. Your production absolute path (Highest priority)
    '/home/tohyuankai/web/gogotrip.teocodes.com/public_html',
    
    # 2. Development relative path
    os.path.join(os.path.dirname(__file__), '..', 'gogotrip_backup', 'dist'),
    
    # 3. Current directory templates (Some deployment scripts place html here)
    os.path.join(os.path.dirname(__file__), 'templates'),
    
    # 4. Current directory static (Fallback)
    os.path.join(os.path.dirname(__file__), 'static'),
]

# Frontend Route Allowlist
FRONTEND_ROUTES = (
    'chat', 'blogs', 'profile', 'settings', 'travel', 
    'trips', 'calendar', 'translate', 'translates', # 🟢 Ensure translates is here
    'login', 'register', 'dashboard', 'shared'
)

# Backend API Prefixes
BACKEND_PREFIXES = (
    'api', 'auth', 'user', 'tts', 'places', 'chat_message', 
    'proxy_image', 'static', 'socket.io', 'admin', 
    'check_login_status', 'authorize', 'oauth2callback', 'create_event'
)

def find_frontend_dir():
    """Traverse possible frontend paths, return the first path containing index.html"""
    for path in POSSIBLE_FRONTEND_PATHS:
        if os.path.exists(os.path.join(path, 'index.html')):
            print(f"✅ Found frontend at: {path}")
            return path
    print("❌ Could not find frontend in any known paths.")
    return None

# Cache found path to avoid disk lookup on every request
CACHED_FRONTEND_DIR = None

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_spa(path):
    global CACHED_FRONTEND_DIR
    
    try:
        normalized_path = path.strip('/')

        # 1. Exclude Backend APIs
        if any(normalized_path == p or normalized_path.startswith(p + '/') for p in BACKEND_PREFIXES):
            return jsonify({'error': 'Not found'}), 404

        # 2. Determine frontend directory
        if CACHED_FRONTEND_DIR is None:
            CACHED_FRONTEND_DIR = find_frontend_dir()
        
        frontend_dir = CACHED_FRONTEND_DIR

        # 3. If directory found, try to serve file
        if frontend_dir:
            # Prioritize finding specific files (js/css/images)
            file_path = os.path.join(frontend_dir, path)
            if path and os.path.isfile(file_path):
                return send_from_directory(frontend_dir, path)
            
            # Otherwise return index.html
            return send_from_directory(frontend_dir, 'index.html')
        
        else:
            # 4. If all paths fail, try final render_template
            # This is useful if index.html is in templates folder but assets are elsewhere
            try:
                return render_template('index.html')
            except Exception as e:
                # Truly could not find it
                return jsonify({
                    'error': 'Frontend not found',
                    'message': 'Could not locate index.html in any configured path.',
                    'paths_checked': POSSIBLE_FRONTEND_PATHS
                }), 500

    except Exception as e:
        print(f"❌ [SPA Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

# ============================================
# User Loader
# ============================================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ============================================
# Database Initialization
# ============================================
with app.app_context():
    db.create_all()
    print("--- [System] Database tables checked/created ---")

    # Create Super Admin if not exists
    admin_email = "admin@gogotrip.com"
    admin_password = "admin123"

    existing_admin = User.query.filter_by(email=admin_email).first()
    
    if not existing_admin:
        super_admin = User(
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            full_name="Super Administrator",
            role="super_admin",
            is_email_verified=True,
            status="active",
            avatar_url="https://ui-avatars.com/api/?name=Super+Admin&background=0D8ABC&color=fff"
        )
        db.session.add(super_admin)
        db.session.commit()
        print(f"--- [System] Super Admin created: {admin_email} ---")
    else:
        print(f"--- [System] Super Admin exists (status={existing_admin.status}, role={existing_admin.role}) ---")
        if existing_admin.status != "active" or existing_admin.role not in ["Administrator", "super_admin", "Admin"]:
            existing_admin.status = "active"
            existing_admin.role = "super_admin"
            existing_admin.is_email_verified = True
            db.session.commit()
            print(f"--- [System] Admin account fixed ---")

# ============================================
# Initialize WebSocket (SocketIO)
# ============================================
socketio = init_socketio(app)

# 🆕 Initialize real-time translation WebSocket handlers
init_realtime_translation(socketio)
init_streaming_translation(socketio)
# ============================================
# Run Application
# ============================================


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 GogoTrip Server Starting")
    print("=" * 60)
    print("📡 HTTP Server: http://127.0.0.1:5000")
    print("🔌 WebSocket: ws://127.0.0.1:5000/socket.io/")
    print("🌐 Translation WS: ws://127.0.0.1:5000/translate")
    print("=" * 60)
    print("\n📋 Translation Endpoints:")
    print("  POST /translate          - Text translation (all users)")
    print("  POST /translate/audio    - Audio file translation (all users)")
    print("  GET  /translate/languages - Get supported languages")
    print("  GET  /translate/live/check - Check premium access")
    print("  WS   /translate          - Real-time voice (premium)")
    print("=" * 60)
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)