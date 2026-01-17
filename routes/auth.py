# routes/auth.py

import os
import random
import datetime
import time
import re
import jwt
import string

import requests
from flask import Blueprint, redirect, request, session, url_for, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from google_auth_oauthlib.flow import Flow
from flask_login import login_user, logout_user, login_required, current_user

import config
from models import db, User
from utils import credentials_to_dict, is_valid_email, send_verification_email

# Allow OAuth over HTTP (dev environment)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

auth_bp = Blueprint('auth', __name__)

# JWT Secret Key (should be from environment in production)
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-super-secret-jwt-key-change-in-production')

# Allowed upload formats
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# 🔥 Resend cooldown tracking (in-memory, should use Redis in production)
_resend_cooldown_cache = {}
RESEND_COOLDOWN_SECONDS = 60


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# reCAPTCHA configuration
RECAPTCHA_SECRET_KEY = "6LewjjUsAAAAADMVF7ZJxEy38wIU118CotxC2uwy"


def verify_recaptcha(token):
    """Verify reCAPTCHA Token"""
    if not token:
        return False, "Missing verification token"
        
    verify_url = 'https://www.google.com/recaptcha/api/siteverify'
    payload = {
        'secret': RECAPTCHA_SECRET_KEY,
        'response': token
    }
    
    try:
        response = requests.post(verify_url, data=payload)
        result = response.json()
        
        print("--------------------------------------------------")
        print(f"🕵️‍♂️ reCAPTCHA Result: {result}")
        print(f"📊 Score: {result.get('score')}")
        print(f"✅ Success: {result.get('success')}")
        print("--------------------------------------------------")

        if result.get('success') and result.get('score', 0) >= 0.5:
            return True, ""
        else:
            print(f"⛔ Verification blocked! Reason: Low score or invalid token")
            return False, "Human verification failed"
            
    except Exception as e:
        print(f"❌ Verification error: {str(e)}")
        return False, str(e)


def check_password_strength(password):
    """Backend password strength validation"""
    if not password:
        return False, "Password cannot be empty"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character (!@#$ etc)"
    
    return True, ""


# ---------------------------------------------------------
# Verification Code Generation
# ---------------------------------------------------------

def generate_verification_code(code_type='numeric', length=6):
    """
    Generate verification code
    Args:
        code_type: 'numeric', 'alphanumeric', or 'alpha'
        length: Code length (4-8)
    """
    if code_type == 'numeric':
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])
    elif code_type == 'alphanumeric':
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choice(chars) for _ in range(length))
    elif code_type == 'alpha':
        return ''.join(random.choice(string.ascii_uppercase) for _ in range(length))
    else:
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])


def create_verification_token(user_id, email, code, code_type, expiry_minutes):
    """
    Create verification JWT token
    """
    payload = {
        'user_id': user_id,
        'email': email,
        'code': code,
        'code_type': code_type,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=expiry_minutes),
        'iat': datetime.datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')
    return token


def verify_verification_token(token):
    """
    Verify JWT token
    Returns:
        tuple: (success: bool, data: dict or error_message: str)
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        return True, payload
    except jwt.ExpiredSignatureError:
        return False, 'Token has expired'
    except jwt.InvalidTokenError:
        return False, 'Invalid token'


# 🔥 Resend cooldown helper functions
def check_resend_cooldown(email):
    """
    Check if email is in cooldown period
    Returns: (can_resend: bool, seconds_remaining: int)
    """
    now = time.time()
    last_sent = _resend_cooldown_cache.get(email, 0)
    elapsed = now - last_sent
    
    if elapsed < RESEND_COOLDOWN_SECONDS:
        return False, int(RESEND_COOLDOWN_SECONDS - elapsed)
    return True, 0


def set_resend_cooldown(email):
    """Set cooldown timestamp for email"""
    _resend_cooldown_cache[email] = time.time()


# ---------------------------------------------------------
# 1. Registration (with Resend Cooldown)
# ---------------------------------------------------------

@auth_bp.route('/auth/send-code-v2', methods=['POST'])
def send_verification_code_v2():
    """
    Send verification code with cooldown enforcement
    """
    try:
        data = request.get_json()
        
        email = data.get('email')
        password = data.get('password')
        name = data.get('name')
        code_type = data.get('code_type', 'numeric')
        code_length = data.get('code_length', 6)
        expiry_minutes = data.get('expiry_minutes', 10)
        recaptcha_token = data.get('recaptcha_token')
        is_resend = data.get('is_resend', False)  # 🔥 Flag for resend requests
        
        # Validate required fields
        if not email or not password or not name:
            return jsonify({
                'status': 'error',
                'message': 'Email, password, and name are required'
            }), 400
        
        # Validate email format
        if not is_valid_email(email):
            return jsonify({
                'status': 'error',
                'message': 'Invalid email format'
            }), 400
        
        # 🔥 Check resend cooldown (only for resend requests)
        if is_resend:
            can_resend, seconds_remaining = check_resend_cooldown(email)
            if not can_resend:
                return jsonify({
                    'status': 'error',
                    'message': f'Please wait {seconds_remaining} seconds before requesting another code',
                    'cooldown_remaining': seconds_remaining
                }), 429
        
        # Validate password strength
        is_strong, error_msg = check_password_strength(password)
        if not is_strong:
            return jsonify({
                'status': 'error',
                'message': error_msg
            }), 400
        
        # Verify reCAPTCHA
        is_valid, error_msg = verify_recaptcha(recaptcha_token)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': error_msg or 'reCAPTCHA verification failed'
            }), 400
        
        # Check if user exists
        existing_user = User.query.filter_by(email=email).first()
        
        if existing_user:
            # 🔥 Normalize status comparison (handle both cases)
            status_lower = (existing_user.status or '').lower()
            
            if status_lower == 'active':
                return jsonify({
                    'status': 'error',
                    'message': 'Email already registered. Please login.'
                }), 400
            elif existing_user.is_pending_verification():
                print(f"📧 Reusing pending_verification account: {email}")
                user = existing_user
                user.password_hash = generate_password_hash(password)
                user.full_name = name
                user.updated_at = datetime.datetime.utcnow()
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'This email is not available for registration.'
                }), 400
        else:
            print(f"📧 Creating new user: {email}")
            user = User(
                email=email,
                password_hash=generate_password_hash(password),
                full_name=name,
                status='pending_verification',
                is_email_verified=False,
                created_at=datetime.datetime.utcnow()
            )
            db.session.add(user)
        
        db.session.commit()
        
        # Generate verification code
        code = generate_verification_code(code_type, code_length)
        
        # Generate JWT token
        token = create_verification_token(
            user_id=user.id,
            email=email,
            code=code,
            code_type=code_type,
            expiry_minutes=expiry_minutes
        )
        
        # Send verification email
        email_sent = send_verification_email(
            email=email,
            code=code,
            token=token,
            expiry_minutes=expiry_minutes,
            is_reset=False
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        # 🔥 Set resend cooldown
        set_resend_cooldown(email)
        
        return jsonify({
            'status': 'success',
            'message': 'Verification code sent successfully',
            'token': token,
            'code_info': {
                'type': code_type,
                'length': code_length,
                'expiry_minutes': expiry_minutes
            },
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS  # 🔥 Tell frontend the cooldown
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Failed to send verification code: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# 🔥 NEW: Resend verification endpoint (simpler, dedicated)
@auth_bp.route('/auth/resend-verification', methods=['POST'])
def resend_verification():
    """
    Dedicated resend verification endpoint with strict cooldown
    """
    try:
        data = request.get_json()
        
        email = data.get('email')
        token = data.get('token')  # Current token to get code_type etc.
        recaptcha_token = data.get('recaptcha_token')
        
        if not email:
            return jsonify({
                'status': 'error',
                'message': 'Email is required'
            }), 400
        
        # 🔥 Check cooldown FIRST
        can_resend, seconds_remaining = check_resend_cooldown(email)
        if not can_resend:
            return jsonify({
                'status': 'error',
                'message': f'Please wait {seconds_remaining} seconds before requesting another code',
                'cooldown_remaining': seconds_remaining
            }), 429
        
        # Verify reCAPTCHA
        is_valid, error_msg = verify_recaptcha(recaptcha_token)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': error_msg or 'reCAPTCHA verification failed'
            }), 400
        
        # Find user
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not found'
            }), 404
        
        # Check if already verified
        if user.status == 'active' and user.is_email_verified:
            return jsonify({
                'status': 'error',
                'message': 'Email already verified',
                'already_verified': True
            }), 400
        
        # Get code settings from original token if available
        code_type = 'numeric'
        code_length = 6
        expiry_minutes = 10
        
        if token:
            is_valid_token, payload = verify_verification_token(token)
            if is_valid_token:
                code_type = payload.get('code_type', 'numeric')
                code_length = len(payload.get('code', '123456'))
        
        # Generate new code
        code = generate_verification_code(code_type, code_length)
        
        # Generate new token
        new_token = create_verification_token(
            user_id=user.id,
            email=email,
            code=code,
            code_type=code_type,
            expiry_minutes=expiry_minutes
        )
        
        # Send email
        email_sent = send_verification_email(
            email=email,
            code=code,
            token=new_token,
            expiry_minutes=expiry_minutes,
            is_reset=False
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        # 🔥 Set cooldown
        set_resend_cooldown(email)
        
        return jsonify({
            'status': 'success',
            'message': 'Verification email sent successfully',
            'token': new_token,
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS
        })
        
    except Exception as e:
        print(f"❌ Resend failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# 🔥 NEW: Check verification status endpoint (for cross-tab sync)
@auth_bp.route('/auth/check-verification-status', methods=['POST'])
def check_verification_status():
    """
    Check if a user's email has been verified.
    Used by frontend to detect when verification is completed in another tab.
    """
    try:
        data = request.get_json()
        
        email = data.get('email')
        token = data.get('token')
        
        if not email and not token:
            return jsonify({
                'status': 'error',
                'message': 'Email or token is required'
            }), 400
        
        # If token provided, extract email from it
        if token:
            is_valid, payload = verify_verification_token(token)
            if is_valid:
                email = payload.get('email')
            else:
                return jsonify({
                    'status': 'error',
                    'message': payload,  # Error message
                    'verified': False
                }), 400
        
        # Find user
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not found',
                'verified': False
            }), 404
        
        # 🔥 Check if verified
        is_verified = user.status == 'active' and user.is_email_verified
        
        response_data = {
            'status': 'success',
            'verified': is_verified,
            'email': email
        }
        
        # If verified, include user data for auto-login
        if is_verified:
            response_data['user'] = user.to_dict()
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Status check failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'verified': False
        }), 500


@auth_bp.route('/auth/signup-verify-v2', methods=['POST'])
def signup_verify_v2():
    """
    Verify signup with code
    """
    try:
        data = request.get_json()
        
        token = data.get('token')
        code = data.get('code')
        
        if not token or not code:
            return jsonify({
                'status': 'error',
                'message': 'Token and code are required'
            }), 400
        
        # Verify JWT token
        is_valid, payload = verify_verification_token(token)
        
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': payload
            }), 400
        
        # Verify code
        if code.upper() != payload['code'].upper():
            return jsonify({
                'status': 'error',
                'message': 'Invalid verification code'
            }), 400
        
        # Get user
        user_id = payload.get('user_id')
        if not user_id:
            return jsonify({
                'status': 'error',
                'message': 'Invalid token: missing user_id'
            }), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not found'
            }), 404
        
        # Activate user
        user.activate()
        user.last_login = datetime.datetime.utcnow()
        db.session.commit()
        
        # Auto login
        login_user(user)
        
        print(f"✅ User verified and logged in: {user.email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Email verified successfully',
            'user': user.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Verification failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ---------------------------------------------------------
# 2. Forgot Password
# ---------------------------------------------------------

@auth_bp.route('/auth/forgot-password/send-code-v2', methods=['POST'])
def forgot_password_send_code_v2():
    """
    Send password reset code with cooldown
    """
    try:
        data = request.get_json()
        
        email = data.get('email')
        code_type = data.get('code_type', 'numeric')
        code_length = data.get('code_length', 6)
        expiry_minutes = data.get('expiry_minutes', 10)
        recaptcha_token = data.get('recaptcha_token')
        
        if not email:
            return jsonify({
                'status': 'error',
                'message': 'Email is required'
            }), 400
        
        # 🔥 Check cooldown
        can_resend, seconds_remaining = check_resend_cooldown(f"reset_{email}")
        if not can_resend:
            return jsonify({
                'status': 'error',
                'message': f'Please wait {seconds_remaining} seconds before requesting another code',
                'cooldown_remaining': seconds_remaining
            }), 429
        
        # Verify reCAPTCHA
        is_valid, error_msg = verify_recaptcha(recaptcha_token)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': error_msg or 'reCAPTCHA verification failed'
            }), 400
        
        # Check user exists and is active
        user = User.query.filter_by(email=email).first()
        if not user or user.status.lower() != 'active':
            return jsonify({
                'status': 'error',
                'message': 'Email not found or account not activated'
            }), 404
        
        # Generate code
        code = generate_verification_code(code_type, code_length)
        
        # Generate token
        token = create_verification_token(
            user_id=user.id,
            email=email,
            code=code,
            code_type=code_type,
            expiry_minutes=expiry_minutes
        )
        
        # Send email
        email_sent = send_verification_email(
            email=email,
            code=code,
            token=token,
            expiry_minutes=expiry_minutes,
            is_reset=True
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        # 🔥 Set cooldown
        set_resend_cooldown(f"reset_{email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Verification code sent successfully',
            'token': token,
            'code_info': {
                'type': code_type,
                'length': code_length,
                'expiry_minutes': expiry_minutes
            },
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS
        })
        
    except Exception as e:
        print(f"❌ Failed to send reset code: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@auth_bp.route('/auth/reset-password-v2', methods=['POST'])
def reset_password_v2():
    """
    Reset password with code
    """
    try:
        data = request.get_json()
        
        token = data.get('token')
        code = data.get('code')
        new_password = data.get('new_password')
        
        if not token or not code or not new_password:
            return jsonify({
                'status': 'error',
                'message': 'Token, code, and new password are required'
            }), 400
        
        # Validate password strength
        is_strong, error_msg = check_password_strength(new_password)
        if not is_strong:
            return jsonify({
                'status': 'error',
                'message': error_msg
            }), 400
        
        # Verify token
        is_valid, payload = verify_verification_token(token)
        
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': payload
            }), 400
        
        # Verify code
        if code.upper() != payload['code'].upper():
            return jsonify({
                'status': 'error',
                'message': 'Invalid verification code'
            }), 400
        
        # Find user
        user_id = payload.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not found'
            }), 404
        
        # Update password
        user.password_hash = generate_password_hash(new_password)
        user.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        
        print(f"✅ Password reset successful: {user.email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Password reset successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Password reset failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ---------------------------------------------------------
# 3. One-tap Verification
# ---------------------------------------------------------

@auth_bp.route('/auth/verify-onetap', methods=['POST'])
def verify_onetap():
    """
    One-Tap verification - returns email and code for frontend auto-fill
    """
    try:
        data = request.get_json()
        token = data.get('token')
        
        if not token:
            return jsonify({
                'status': 'error',
                'message': 'Token is required'
            }), 400
        
        # Verify token
        is_valid, payload = verify_verification_token(token)
        
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': payload
            }), 400
        
        # Return email and code for auto-fill
        return jsonify({
            'status': 'success',
            'data': {
                'email': payload['email'],
                'code': payload['code']
            }
        })
        
    except Exception as e:
        print(f"❌ One-tap verification failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ---------------------------------------------------------
# 4. Email Login
# ---------------------------------------------------------

@auth_bp.route('/auth/login-email', methods=['POST'])
def login_email():
    """
    Email login
    """
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({
                'status': 'error',
                'message': 'Email and password are required'
            }), 400
        
        user = User.query.filter_by(email=email).first()
        
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({
                'status': 'error',
                'message': 'Invalid email or password'
            }), 401
        
        # Check account status
        if not user.can_login():
            if user.is_pending_verification():
                return jsonify({
                    'status': 'error',
                    'message': 'Please verify your email first. Check your inbox for the verification link.',
                    'needs_verification': True
                }), 403
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'Account is {user.status}. Please contact support.'
                }), 403
        
        # Login successful
        login_user(user)
        user.last_login = datetime.datetime.utcnow()
        db.session.commit()
        
        print(f"✅ User logged in: {email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Login successful',
            'user': user.to_dict()
        })
        
    except Exception as e:
        print(f"❌ Login failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ---------------------------------------------------------
# 5. Google OAuth - 🔥 FIXED
# ---------------------------------------------------------

@auth_bp.route('/authorize')
def authorize():
    """Google login step 1: redirect"""
    flow = Flow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES)
    flow.redirect_uri = url_for('auth.oauth2callback', _external=True)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['state'] = state
    return redirect(authorization_url)


@auth_bp.route('/oauth2callback')
def oauth2callback():
    """
    Google login step 2: callback
    
    🔥 FIXED: 
    1. Properly handle pending_verification users
    2. Case-insensitive status comparison
    3. Link Google account to existing email account
    """
    try:
        state = session.get('state')
        if not state:
            return redirect("https://gogotrip.teocodes.com/login?error=session_expired")
            
        flow = Flow.from_client_secrets_file(
            config.CLIENT_SECRETS_FILE, scopes=config.SCOPES, state=state)
        flow.redirect_uri = url_for('auth.oauth2callback', _external=True)
        
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }

        from googleapiclient.discovery import build
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        
        g_email = user_info.get('email')
        g_id = user_info.get('id')
        g_name = user_info.get('name')
        g_picture = user_info.get('picture')

        user = User.query.filter_by(email=g_email).first()
        
        if not user:
            # New user - create account
            new_user = User(
                email=g_email,
                google_id=g_id,
                full_name=g_name,
                avatar_url=g_picture,
                is_email_verified=True,  # Google verified the email
                status='active',  # 🔥 Use lowercase 'active'
                role='User'
            )
            new_user.last_login = datetime.datetime.utcnow()
            # 🆕 Save Google tokens for Calendar access
            if credentials.refresh_token:
                new_user.google_refresh_token = credentials.refresh_token
            if credentials.token:
                new_user.google_access_token = credentials.token
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user, remember=True)
            print(f"✅ New user created via Google: {g_email}")
            
        else:
            # Existing user - 🔥 FIXED: handle all statuses properly
            status_lower = (user.status or '').lower()
            
            # 🔥 Handle pending_verification users
            if status_lower == 'pending_verification' or user.is_pending_verification():
                # User registered with email but not verified yet
                # Google OAuth verifies their email, so we can activate them
                print(f"🔄 Activating pending user via Google OAuth: {g_email}")
                
                user.google_id = g_id
                user.is_email_verified = True
                user.status = 'active'
                if not user.avatar_url:
                    user.avatar_url = g_picture
                if not user.full_name:
                    user.full_name = g_name
                user.last_login = datetime.datetime.utcnow()
                # 🆕 Save Google tokens for Calendar access
                if credentials.refresh_token:
                    user.google_refresh_token = credentials.refresh_token
                if credentials.token:
                    user.google_access_token = credentials.token
                db.session.commit()
                login_user(user, remember=True)
                
            elif status_lower == 'active':
                # Normal active user
                if not user.google_id:
                    user.google_id = g_id
                    user.is_email_verified = True
                user.last_login = datetime.datetime.utcnow()
                # 🆕 Save/Update Google tokens for Calendar access
                if credentials.refresh_token:
                    user.google_refresh_token = credentials.refresh_token
                if credentials.token:
                    user.google_access_token = credentials.token
                db.session.commit()
                login_user(user, remember=True)
                print(f"✅ Existing user logged in via Google: {g_email}")
                
            elif status_lower in ['suspended', 'deleted']:
                # Account is suspended or deleted
                print(f"⛔ Blocked Google login for {status_lower} account: {g_email}")
                return redirect(f"https://gogotrip.teocodes.com/login?error=account_{status_lower}")
                
            else:
                # Unknown status - treat as error
                print(f"⚠️ Unknown status '{user.status}' for user: {g_email}")
                return redirect("https://gogotrip.teocodes.com/login?error=account_error")

        return redirect("https://gogotrip.teocodes.com/")
        
    except Exception as e:
        print(f"❌ Google OAuth error: {str(e)}")
        return redirect(f"https://gogotrip.teocodes.com/login?error=oauth_failed")


# ---------------------------------------------------------
# 6. Other Auth Routes
# ---------------------------------------------------------

@auth_bp.route('/check_login_status')
def check_login():
    """Check login status"""
    if current_user.is_authenticated:
        return jsonify({
            "logged_in": True, 
            "user": current_user.to_dict(),
            "role": current_user.role
        })
    return jsonify({"logged_in": False})


@auth_bp.route('/auth/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    response = jsonify({"status": "success", "message": "Logged out successfully"})
    response.delete_cookie('session', path='/')
    response.delete_cookie('remember_token', path='/')
    return response


@auth_bp.route('/auth/update-profile', methods=['PUT'])
@login_required
def update_profile():
    user = current_user
    
    try:
        if 'avatar' in request.files:
            file = request.files['avatar']
            
            if file and allowed_file(file.filename):
                file.seek(0, os.SEEK_END)
                if file.tell() > 1 * 1024 * 1024:
                    return jsonify({'status': 'error', 'message': 'File too large (Max 1MB)'}), 400
                file.seek(0)

                filename = secure_filename(file.filename)
                timestamp = int(time.time())
                unique_filename = f"avatar_{user.id}_{timestamp}.{filename.rsplit('.', 1)[1].lower()}"
                
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
                os.makedirs(upload_folder, exist_ok=True)
                
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                
                user.avatar_url = f"https://gogotrip.teocodes.com/static/uploads/avatars/{unique_filename}"
        
        full_name = request.form.get('name')
        if full_name:
            user.full_name = full_name
            
        email_notifications = request.form.get('emailNotifications')
        if email_notifications is not None:
            user.email_notifications = email_notifications.lower() == 'true'

        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Profile updated', 'user': user.to_dict()})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@auth_bp.route('/auth/change-password', methods=['POST'])
@login_required
def change_password_api():
    user = current_user
    
    data = request.json
    current_password = data.get('currentPassword')
    new_password = data.get('newPassword')

    if not current_password or not new_password:
        return jsonify({"status": "error", "message": "Please fill in all fields"}), 400

    if not user.password_hash:
        return jsonify({"status": "error", "message": "Google accounts cannot change password"}), 400

    if not check_password_hash(user.password_hash, current_password):
        return jsonify({"status": "error", "message": "Current password is incorrect"}), 400

    is_strong, reason = check_password_strength(new_password)
    if not is_strong:
        return jsonify({"status": "error", "message": f"New password too weak: {reason}"}), 400

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({"status": "success", "message": "Password changed successfully"})


# ---------------------------------------------------------
# 7. Google Account Linking (for Email/Password Users)
# ---------------------------------------------------------

@auth_bp.route('/auth/link-google')
@login_required
def link_google():
    """
    Google Account LINKING endpoint (NOT login)
    
    This endpoint is used when an email/password user wants to link
    their Google account for Calendar features.
    
    It differs from /authorize by:
    1. Requiring existing authentication (@login_required)
    2. Associating the Google account with current_user
    3. Redirecting back to Settings page, not home
    """
    # Check if user already has Google linked
    if current_user.google_id:
        return redirect("https://gogotrip.teocodes.com/settings?error=already_linked")
    
    flow = Flow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES)
    flow.redirect_uri = url_for('auth.link_google_callback', _external=True)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['state'] = state
    session['linking_user_id'] = current_user.id  # Track who is linking
    return redirect(authorization_url)


@auth_bp.route('/auth/link-google-callback')
def link_google_callback():
    """
    Callback for Google Account LINKING
    
    Handles the OAuth callback when linking Google account to existing user.
    """
    try:
        state = session.get('state')
        linking_user_id = session.get('linking_user_id')
        
        if not state or not linking_user_id:
            print("❌ Google linking: Session expired or missing linking_user_id")
            return redirect("https://gogotrip.teocodes.com/settings?error=session_expired")
        
        # Get the user who initiated linking
        user = User.query.get(linking_user_id)
        if not user:
            print(f"❌ Google linking: User {linking_user_id} not found")
            return redirect("https://gogotrip.teocodes.com/settings?error=user_not_found")
            
        flow = Flow.from_client_secrets_file(
            config.CLIENT_SECRETS_FILE, scopes=config.SCOPES, state=state)
        flow.redirect_uri = url_for('auth.link_google_callback', _external=True)
        
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        
        # Store credentials in session for Calendar operations
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }

        # Get Google user info
        from googleapiclient.discovery import build
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        
        g_id = user_info.get('id')
        g_email = user_info.get('email')
        
        print(f"🔗 Google linking attempt: User {user.email} -> Google {g_email}")
        
        # Check if this Google account is already linked to another user
        existing_google_user = User.query.filter_by(google_id=g_id).first()
        if existing_google_user and existing_google_user.id != user.id:
            print(f"⚠️ Google account {g_email} already linked to user {existing_google_user.email}")
            return redirect("https://gogotrip.teocodes.com/settings?error=google_already_linked")
        
        # Link Google account to current user
        user.google_id = g_id
        if credentials.refresh_token:
            user.google_refresh_token = credentials.refresh_token
        if credentials.token:
            user.google_access_token = credentials.token
        
        db.session.commit()
        
        # Clean up session
        session.pop('linking_user_id', None)
        
        # Log the user in (refresh their session)
        login_user(user, remember=True)
        
        print(f"✅ Google account linked successfully: {user.email} -> {g_email}")
        return redirect("https://gogotrip.teocodes.com/settings?success=google_linked")
        
    except Exception as e:
        print(f"❌ Google linking error: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect("https://gogotrip.teocodes.com/settings?error=linking_failed")


@auth_bp.route('/auth/unlink-google', methods=['POST'])
@login_required
def unlink_google():
    """
    Unlink Google account from user
    
    Only allowed if user has a password set (can still login after unlinking)
    """
    user = current_user
    
    # Safety check: User must have password to unlink Google
    if not user.password_hash:
        return jsonify({
            'status': 'error',
            'message': 'Cannot unlink Google account. You need to set a password first since you logged in with Google.'
        }), 400
    
    # Check if Google is actually linked
    if not user.google_id:
        return jsonify({
            'status': 'error',
            'message': 'No Google account is linked.'
        }), 400
    
    # Clear Google data
    user.google_id = None
    user.google_refresh_token = None
    user.google_access_token = None
    user.google_token_expiry = None
    
    # Clear session credentials
    session.pop('credentials', None)
    
    db.session.commit()
    
    print(f"✅ Google account unlinked for user: {user.email}")
    
    return jsonify({
        'status': 'success',
        'message': 'Google account unlinked successfully',
        'user': user.to_dict()
    })

