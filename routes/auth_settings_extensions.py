# routes/auth_settings_extensions.py
import datetime
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User

# 🔥 Import existing functions from auth.py (NO MODIFICATIONS to auth.py)
from routes.auth import (
    # Verification utilities
    generate_verification_code,
    create_verification_token,
    verify_verification_token,
    # reCAPTCHA
    
    # Password validation
    check_password_strength,
    # Cooldown management
    check_resend_cooldown,
    set_resend_cooldown,
    RESEND_COOLDOWN_SECONDS
)

# Email sending utility
from utils import send_verification_email, is_valid_email


# Create blueprint for settings extensions
settings_auth_bp = Blueprint('settings_auth', __name__)


# =============================================================
# 🔐 TWO-FACTOR PASSWORD CHANGE
# Security: Current Password + Email Verification Code
# =============================================================

@settings_auth_bp.route('/auth/password-change/send-code', methods=['POST'])
@login_required
def password_change_send_code():
    """
    Step 1: Verify current password and send verification code to email
    
    Required:
    - current_password: User's current password
    - recaptcha_token: reCAPTCHA v3 token
    
    Returns:
    - token: JWT token for verification
    """
    try:
        data = request.get_json()
        user = current_user
        
        current_password = data.get('current_password')
        
        
        # Validation
        if not current_password:
            return jsonify({
                'status': 'error',
                'message': 'Current password is required'
            }), 400
        
        # Check if Google-only account
        if not user.password_hash:
            return jsonify({
                'status': 'error',
                'message': 'Google accounts cannot change password'
            }), 400
        

        
        # Verify current password
        if not check_password_hash(user.password_hash, current_password):
            return jsonify({
                'status': 'error',
                'message': 'Current password is incorrect'
            }), 400
        
        # Check cooldown
        cooldown_key = f"pwchange_{user.email}"
        can_send, seconds_remaining = check_resend_cooldown(cooldown_key)
        if not can_send:
            return jsonify({
                'status': 'error',
                'message': f'Please wait {seconds_remaining} seconds before requesting another code',
                'cooldown_remaining': seconds_remaining
            }), 429
        
        # Generate verification code using existing function
        code = generate_verification_code('numeric', 6)
        
        # Create token using existing function
        token = create_verification_token(
            user_id=user.id,
            email=user.email,
            code=code,
            code_type='password_change',
            expiry_minutes=10
        )
        
        # Send email using existing function
        email_sent = send_verification_email(
            email=user.email,
            code=code,
            token=token,
            expiry_minutes=10,
            is_reset=True,  # Use password reset template
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        # Set cooldown
        set_resend_cooldown(cooldown_key)
        
        print(f"✅ Password change code sent to: {user.email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Verification code sent to your email',
            'token': token,
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS
        })
        
    except Exception as e:
        print(f"❌ Password change send-code failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_auth_bp.route('/auth/password-change/resend-code', methods=['POST'])
@login_required
def password_change_resend_code():
    """
    Resend password change verification code
    """
    try:
        data = request.get_json()
        user = current_user

        # Check cooldown
        cooldown_key = f"pwchange_{user.email}"
        can_send, seconds_remaining = check_resend_cooldown(cooldown_key)
        if not can_send:
            return jsonify({
                'status': 'error',
                'message': f'Please wait {seconds_remaining} seconds',
                'cooldown_remaining': seconds_remaining
            }), 429
        
        # Generate new code
        code = generate_verification_code('numeric', 6)
        
        # Create new token
        token = create_verification_token(
            user_id=user.id,
            email=user.email,
            code=code,
            code_type='password_change',
            expiry_minutes=10
        )
        
        # Send email
        email_sent = send_verification_email(
            email=user.email,
            code=code,
            token=token,
            expiry_minutes=10,
            is_reset=True,
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        set_resend_cooldown(cooldown_key)
        
        return jsonify({
            'status': 'success',
            'message': 'Verification code resent',
            'token': token,
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS
        })
        
    except Exception as e:
        print(f"❌ Password change resend failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_auth_bp.route('/auth/password-change/confirm', methods=['POST'])
@login_required
def password_change_confirm():
    """
    Step 2: Verify code and set new password
    
    Required:
    - token: JWT verification token
    - code: 6-digit verification code
    - new_password: New password (must meet strength requirements)
    """
    try:
        data = request.get_json()
        user = current_user
        
        token = data.get('token')
        code = data.get('code')
        new_password = data.get('new_password')
        
        # Validation
        if not token or not code or not new_password:
            return jsonify({
                'status': 'error',
                'message': 'Token, code, and new password are required'
            }), 400
        
        # Verify token using existing function
        is_valid, payload = verify_verification_token(token)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': payload  # Error message
            }), 400
        
        # Verify token belongs to current user
        if payload.get('user_id') != user.id:
            return jsonify({
                'status': 'error',
                'message': 'Invalid token'
            }), 400
        
        # Verify code type
        if payload.get('code_type') != 'password_change':
            return jsonify({
                'status': 'error',
                'message': 'Invalid token type'
            }), 400
        
        # Verify code (case-insensitive)
        if code.upper() != payload['code'].upper():
            return jsonify({
                'status': 'error',
                'message': 'Invalid verification code'
            }), 400
        
        # Validate password strength using existing function
        is_strong, error_msg = check_password_strength(new_password)
        if not is_strong:
            return jsonify({
                'status': 'error',
                'message': error_msg
            }), 400
        
        # Update password
        user.password_hash = generate_password_hash(new_password)
        user.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        
        print(f"✅ Password changed successfully: {user.email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Password changed successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Password change confirm failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# =============================================================
# 📧 SECURE EMAIL CHANGE
# Flow: Verify Current Email → Update → Verify New Email
# =============================================================

@settings_auth_bp.route('/auth/email-change/send-code', methods=['POST'])
@login_required
def email_change_send_code():
    """
    Step 1: Request email change - send verification to CURRENT email
    
    Required:
    - new_email: The new email address
    - recaptcha_token: reCAPTCHA v3 token
    """
    try:
        data = request.get_json()
        user = current_user
        
        new_email = data.get('new_email', '').lower().strip()

        # Validation
        if not new_email:
            return jsonify({
                'status': 'error',
                'message': 'New email is required'
            }), 400
        
        if not is_valid_email(new_email):
            return jsonify({
                'status': 'error',
                'message': 'Invalid email format'
            }), 400
        
        if new_email == user.email:
            return jsonify({
                'status': 'error',
                'message': 'New email must be different from current email'
            }), 400
        
        # Check if new email is already registered
        existing_user = User.query.filter_by(email=new_email).first()
        if existing_user:
            return jsonify({
                'status': 'error',
                'message': 'This email is already registered'
            }), 400
        

        
        # Check cooldown
        cooldown_key = f"emailchange_{user.email}"
        can_send, seconds_remaining = check_resend_cooldown(cooldown_key)
        if not can_send:
            return jsonify({
                'status': 'error',
                'message': f'Please wait {seconds_remaining} seconds',
                'cooldown_remaining': seconds_remaining
            }), 429
        
        # Generate code
        code = generate_verification_code('numeric', 6)
        
        # Create token with new_email stored in it
        token = create_verification_token(
            user_id=user.id,
            email=user.email,  # Current email for verification
            code=code,
            code_type='email_change_verify_current',
            expiry_minutes=10
        )
        
        # Send verification to CURRENT email
        email_sent = send_verification_email(
            email=user.email,
            code=code,
            token=token,
            expiry_minutes=10,
            is_reset=False,
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        set_resend_cooldown(cooldown_key)
        
        print(f"✅ Email change verification sent to current email: {user.email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Verification code sent to your current email',
            'token': token,
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS
        })
        
    except Exception as e:
        print(f"❌ Email change send-code failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_auth_bp.route('/auth/email-change/verify-current', methods=['POST'])
@login_required
def email_change_verify_current():
    """
    Step 2: Verify code from current email, then update email and send code to new email
    
    Required:
    - token: JWT verification token
    - code: 6-digit verification code
    - new_email: The new email address
    """
    try:
        data = request.get_json()
        user = current_user
        
        token = data.get('token')
        code = data.get('code')
        new_email = data.get('new_email', '').lower().strip()
        
        # Validation
        if not token or not code or not new_email:
            return jsonify({
                'status': 'error',
                'message': 'Token, code, and new email are required'
            }), 400
        
        # Verify token
        is_valid, payload = verify_verification_token(token)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': payload
            }), 400
        
        # Verify token belongs to current user
        if payload.get('user_id') != user.id:
            return jsonify({
                'status': 'error',
                'message': 'Invalid token'
            }), 400
        
        # Verify token type
        if payload.get('code_type') != 'email_change_verify_current':
            return jsonify({
                'status': 'error',
                'message': 'Invalid token type'
            }), 400
        
        # Verify code
        if code.upper() != payload['code'].upper():
            return jsonify({
                'status': 'error',
                'message': 'Invalid verification code'
            }), 400
        
        # Double check new email is still available
        existing_user = User.query.filter_by(email=new_email).first()
        if existing_user:
            return jsonify({
                'status': 'error',
                'message': 'This email is already registered'
            }), 400
        
        # Store old email for logging
        old_email = user.email
        
        # Update email (will be pending verification on new email)
        user.email = new_email
        user.is_email_verified = False
        user.status = 'pending_email_verification'
        user.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        
        # Generate code for new email verification
        new_code = generate_verification_code('numeric', 6)
        
        # Create token for new email verification
        new_token = create_verification_token(
            user_id=user.id,
            email=new_email,
            code=new_code,
            code_type='email_change_verify_new',
            expiry_minutes=10
        )
        
        # Send verification to NEW email
        email_sent = send_verification_email(
            email=new_email,
            code=new_code,
            token=new_token,
            expiry_minutes=10,
            is_reset=False,
        )
        
        if not email_sent:
            # Rollback email change if we can't send verification
            user.email = old_email
            user.is_email_verified = True
            user.status = 'active'
            db.session.commit()
            
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification to new email'
            }), 500
        
        print(f"✅ Email updated from {old_email} to {new_email} (pending verification)")
        
        return jsonify({
            'status': 'success',
            'message': 'Email updated. Please verify your new email address.',
            'token': new_token,
            'user': user.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Email change verify-current failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_auth_bp.route('/auth/email-change/verify-new', methods=['POST'])
@login_required
def email_change_verify_new():
    """
    Step 3: Verify code from new email to complete email change
    
    Required:
    - token: JWT verification token
    - code: 6-digit verification code
    """
    try:
        data = request.get_json()
        user = current_user
        
        token = data.get('token')
        code = data.get('code')
        
        # Validation
        if not token or not code:
            return jsonify({
                'status': 'error',
                'message': 'Token and code are required'
            }), 400
        
        # Verify token
        is_valid, payload = verify_verification_token(token)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': payload
            }), 400
        
        # Verify token belongs to current user
        if payload.get('user_id') != user.id:
            return jsonify({
                'status': 'error',
                'message': 'Invalid token'
            }), 400
        
        # Verify token type
        if payload.get('code_type') != 'email_change_verify_new':
            return jsonify({
                'status': 'error',
                'message': 'Invalid token type'
            }), 400
        
        # Verify code
        if code.upper() != payload['code'].upper():
            return jsonify({
                'status': 'error',
                'message': 'Invalid verification code'
            }), 400
        
        # Activate user with new email
        user.is_email_verified = True
        user.status = 'active'
        user.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        
        print(f"✅ New email verified: {user.email}")
        
        return jsonify({
            'status': 'success',
            'message': 'Email verified successfully',
            'user': user.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Email change verify-new failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_auth_bp.route('/auth/email-change/resend-code', methods=['POST'])
@login_required
def email_change_resend_code():
    """
    Resend email change verification code
    
    Required:
    - token: Current JWT token
    - step: 'verify_current' or 'verify_new'
    - recaptcha_token: reCAPTCHA v3 token
    """
    try:
        data = request.get_json()
        user = current_user
        
        token = data.get('token')
        step = data.get('step')

        
        # Check cooldown
        cooldown_key = f"emailchange_{user.id}"
        can_send, seconds_remaining = check_resend_cooldown(cooldown_key)
        if not can_send:
            return jsonify({
                'status': 'error',
                'message': f'Please wait {seconds_remaining} seconds',
                'cooldown_remaining': seconds_remaining
            }), 429
        
        # Determine which email to send to
        if step == 'verify_current':
            target_email = user.email
            code_type = 'email_change_verify_current'
            subject = 'Email Change Verification'
        elif step == 'verify_new':
            target_email = user.email  # Already updated to new email
            code_type = 'email_change_verify_new'
            subject = 'Verify Your New Email Address'
        else:
            return jsonify({
                'status': 'error',
                'message': 'Invalid step'
            }), 400
        
        # Generate new code
        code = generate_verification_code('numeric', 6)
        
        # Create new token
        new_token = create_verification_token(
            user_id=user.id,
            email=target_email,
            code=code,
            code_type=code_type,
            expiry_minutes=10
        )
        
        # Send email
        email_sent = send_verification_email(
            email=target_email,
            code=code,
            token=new_token,
            expiry_minutes=10,
            is_reset=False,
        )
        
        if not email_sent:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send verification email'
            }), 500
        
        set_resend_cooldown(cooldown_key)
        
        return jsonify({
            'status': 'success',
            'message': 'Verification code resent',
            'token': new_token,
            'cooldown_seconds': RESEND_COOLDOWN_SECONDS
        })
        
    except Exception as e:
        print(f"❌ Email change resend failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


