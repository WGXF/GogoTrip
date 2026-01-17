# utils.py
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from email.header import Header
import config


def is_valid_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def send_verification_email(email, code, token, expiry_minutes, is_reset=False):
    """
    Send verification email with one-tap verification support.
    
    This is the STABLE API - do not rename this function.
    
    Args:
        email: Recipient email address
        code: Verification code
        token: JWT token for one-tap verification
        expiry_minutes: Code validity period (in minutes)
        is_reset: Whether this is a password reset email
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = config.MAIL_USERNAME
        msg['To'] = email
        
        if is_reset:
            msg['Subject'] = '🔐 Password Reset Verification Code'
            title = 'Reset Your Password'
            greeting = 'You requested to reset your password.'
        else:
            msg['Subject'] = '✨ Welcome to GogoTrip - Verify Your Email'
            title = 'Welcome to GogoTrip!'
            greeting = 'Thanks for signing up! Please verify your email address.'
        
        # One-tap verification URL
        onetap_url = f"https://gogotrip.teocodes.com/verify?token={token}"
        
        # HTML email template (no JavaScript for compatibility)
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #334155;
            background-color: #f1f5f9;
            margin: 0;
            padding: 0;
        }}
        .email-container {{
            max-width: 600px;
            margin: 40px auto;
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
        .header {{
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            padding: 40px 30px;
            text-align: center;
            color: white;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 700;
        }}
        .content {{
            padding: 40px 30px;
        }}
        .greeting {{
            font-size: 18px;
            color: #475569;
            margin-bottom: 30px;
        }}
        .code-container {{
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
            border: 2px dashed #0ea5e9;
            border-radius: 12px;
            padding: 30px;
            text-align: center;
            margin: 30px 0;
        }}
        .code-label {{
            font-size: 14px;
            color: #64748b;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 15px;
        }}
        .code {{
            font-size: 42px;
            font-weight: 700;
            color: #0284c7;
            letter-spacing: 8px;
            font-family: 'Courier New', monospace;
            margin: 15px 0;
            user-select: all;
            -webkit-user-select: all;
            -moz-user-select: all;
            -ms-user-select: all;
            cursor: text;
            padding: 10px;
            background: white;
            border-radius: 8px;
        }}
        .copy-instruction {{
            font-size: 13px;
            color: #64748b;
            margin-top: 15px;
            font-weight: 600;
        }}
        .onetap-section {{
            background: #f8fafc;
            border-radius: 12px;
            padding: 25px;
            margin: 25px 0;
            text-align: center;
            border: 2px solid #10b981;
        }}
        .onetap-text {{
            font-size: 15px;
            color: #64748b;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        .onetap-button {{
            display: inline-block;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white !important;
            padding: 16px 40px;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 700;
            font-size: 18px;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }}
        .onetap-button:hover {{
            background: linear-gradient(135deg, #059669 0%, #047857 100%);
        }}
        .expiry-info {{
            font-size: 13px;
            color: #94a3b8;
            margin-top: 20px;
            padding: 15px;
            background: #fef3c7;
            border-left: 4px solid #f59e0b;
            border-radius: 4px;
        }}
        .footer {{
            background: #f8fafc;
            padding: 30px;
            text-align: center;
            font-size: 13px;
            color: #94a3b8;
        }}
        .footer a {{
            color: #0ea5e9;
            text-decoration: none;
        }}
        .divider {{
            height: 1px;
            background: linear-gradient(to right, transparent, #e2e8f0, transparent);
            margin: 30px 0;
        }}
        .security-note {{
            font-size: 13px;
            color: #94a3b8;
            margin-top: 25px;
            padding: 15px;
            background: #fef2f2;
            border-left: 4px solid #ef4444;
            border-radius: 4px;
        }}
        .highlight-box {{
            background: #dbeafe;
            border: 2px solid #3b82f6;
            border-radius: 8px;
            padding: 15px;
            margin: 20px 0;
            text-align: center;
        }}
        .highlight-box strong {{
            color: #1e40af;
            font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1>🌍 {title}</h1>
        </div>
        
        <div class="content">
            <p class="greeting">
                Hi there! 👋<br>
                {greeting}
            </p>
            
            <!-- One-Tap verification -->
            <div class="onetap-section">
                <div class="onetap-text">
                    🚀 <strong>Recommended:</strong> Verify instantly with one click!
                </div>
                <a href="{onetap_url}" class="onetap-button">
                    ⚡ Click Here to Verify
                </a>
                <p style="margin-top: 15px; font-size: 12px; color: #64748b;">
                    This will auto-fill your verification code
                </p>
            </div>
            
            <div class="divider"></div>
            
            <!-- Verification code section -->
            <div class="highlight-box">
                <strong>Or use this verification code:</strong>
            </div>
            
            <div class="code-container">
                <div class="code-label">Your Verification Code</div>
                <div class="code" title="Click to select, then copy">{code}</div>
                <div class="copy-instruction">
                    👆 Tap the code above to select it, then copy and paste into the form
                </div>
            </div>
            
            <div class="expiry-info">
                ⏰ This code will expire in <strong>{expiry_minutes} minutes</strong>
            </div>
            
            <div class="security-note">
                🔒 <strong>Security Note:</strong> Never share this code with anyone. 
                GogoTrip will never ask for your verification code via phone or email.
            </div>
        </div>
        
        <div class="footer">
            <p>
                Having trouble? <a href="mailto:support@gogotrip.com">Contact Support</a>
            </p>
            <p>
                © 2024 GogoTrip. All rights reserved.<br>
                <a href="https://gogotrip.com">Visit our website</a> | 
                <a href="https://gogotrip.com/privacy">Privacy Policy</a>
            </p>
        </div>
    </div>
</body>
</html>
"""
        
        # Plain text fallback
        text_content = f"""
{title}

{greeting}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 RECOMMENDED: Verify instantly with one click!

Click this link:
{onetap_url}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Or use this verification code:

{code}

Copy the code above and paste it into the verification form.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⏰ This code will expire in {expiry_minutes} minutes.

🔒 Security Note: Never share this code with anyone.

---
GogoTrip Team
© 2024 GogoTrip. All rights reserved.
"""
        
        # Add email content
        part1 = MIMEText(text_content, 'plain', 'utf-8')
        part2 = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        server = smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT)
        server.starttls()
        server.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Verification email sent to: {email}")
        print(f"   Code: {code}")
        print(f"   Validity: {expiry_minutes} minutes")
        print(f"   One-tap URL: {onetap_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ Email sending failed: {str(e)}")
        return False


# 🔥 Backward Compatibility Alias
# Keep this for any code still using the old name
def send_verification_email_improved(email, code, token, expiry_minutes, is_reset=False):
    """
    DEPRECATED: Use send_verification_email() instead.
    
    This function is kept for backward compatibility only.
    It simply calls the main send_verification_email function.
    """
    import warnings
    warnings.warn(
        "send_verification_email_improved() is deprecated. "
        "Use send_verification_email() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return send_verification_email(email, code, token, expiry_minutes, is_reset)


def credentials_to_dict(credentials):
    """Convert Google Credentials object to dictionary for session storage."""
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }


def send_system_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = None
) -> bool:
    """
    Send a system/transactional email (non-verification emails).
    
    This is a generic email sender for system notifications like:
    - Subscription purchase confirmations
    - Subscription updates (admin changes)
    - Admin broadcast notifications (when user has opted in)
    
    ⚠️ DO NOT USE for verification emails - use send_verification_email() instead.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML formatted email body
        text_content: Plain text fallback (optional, will be auto-generated if not provided)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not is_valid_email(to_email):
        print(f"❌ Invalid email address: {to_email}")
        return False
    
    try:
        # Create email message
        msg = MIMEMultipart('alternative')
        msg['From'] = config.MAIL_USERNAME
        msg['To'] = to_email
        msg['Subject'] = Header(subject, 'utf-8')
        
        # Generate plain text fallback if not provided
        if text_content is None:
            # Simple HTML to text conversion
            import re
            text_content = re.sub(r'<[^>]+>', '', html_content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()
        
        # Attach both text and HTML parts
        part1 = MIMEText(text_content, 'plain', 'utf-8')
        part2 = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        server = smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT)
        server.starttls()
        server.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ System email sent to: {to_email}")
        print(f"   Subject: {subject}")
        
        return True
        
    except Exception as e:
        print(f"❌ System email sending failed: {str(e)}")
        return False


def generate_subscription_email_html(
    user_name: str,
    plan_name: str,
    end_date: str,
    is_lifetime: bool,
    action_type: str = 'purchase'
) -> tuple:
    """
    Generate HTML email content for subscription notifications.
    
    Args:
        user_name: User's display name
        plan_name: Subscription plan name
        end_date: Subscription end date (formatted string)
        is_lifetime: Whether this is a lifetime subscription
        action_type: 'purchase', 'admin_grant', 'admin_extend', 'admin_cancel'
    
    Returns:
        tuple: (subject, html_content, text_content)
    """
    
    # Determine email content based on action type
    if action_type == 'purchase':
        subject = "🎉 Welcome to GogoTrip Premium!"
        title = "Subscription Activated!"
        greeting = f"Congratulations {user_name}! Your premium subscription is now active."
        icon = "🎉"
    elif action_type == 'admin_grant':
        subject = "🎁 Premium Subscription Granted"
        title = "Subscription Granted!"
        greeting = f"Hi {user_name}! An administrator has granted you a premium subscription."
        icon = "🎁"
    elif action_type == 'admin_extend':
        subject = "⏰ Your Subscription Has Been Extended"
        title = "Subscription Extended!"
        greeting = f"Hi {user_name}! Your premium subscription has been extended by an administrator."
        icon = "⏰"
    elif action_type == 'admin_cancel':
        subject = "📋 Subscription Update Notice"
        title = "Subscription Cancelled"
        greeting = f"Hi {user_name}, your premium subscription has been cancelled by an administrator."
        icon = "📋"
    else:
        subject = "📧 Subscription Update"
        title = "Subscription Update"
        greeting = f"Hi {user_name}, here's an update about your subscription."
        icon = "📧"
    
    # Subscription details
    if is_lifetime:
        validity_text = "Lifetime Access"
        validity_detail = "Your subscription never expires!"
    elif action_type == 'admin_cancel':
        validity_text = "Cancelled"
        validity_detail = "Your premium access has ended."
    else:
        validity_text = f"Valid until {end_date}"
        validity_detail = f"Your premium features are active until {end_date}."
    
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #334155;
            background-color: #f1f5f9;
            margin: 0;
            padding: 0;
        }}
        .email-container {{
            max-width: 600px;
            margin: 40px auto;
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
        .header {{
            background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
            padding: 40px 30px;
            text-align: center;
            color: white;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 700;
        }}
        .header .icon {{
            font-size: 48px;
            margin-bottom: 16px;
        }}
        .content {{
            padding: 40px 30px;
        }}
        .greeting {{
            font-size: 18px;
            color: #475569;
            margin-bottom: 30px;
        }}
        .details-box {{
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 25px;
            margin: 25px 0;
        }}
        .detail-row {{
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #e2e8f0;
        }}
        .detail-row:last-child {{
            border-bottom: none;
        }}
        .detail-label {{
            font-weight: 600;
            color: #64748b;
        }}
        .detail-value {{
            font-weight: 700;
            color: #1e293b;
        }}
        .cta-button {{
            display: inline-block;
            background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
            color: white !important;
            padding: 16px 40px;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 700;
            font-size: 16px;
            margin-top: 20px;
        }}
        .footer {{
            background: #f8fafc;
            padding: 30px;
            text-align: center;
            font-size: 13px;
            color: #94a3b8;
        }}
        .footer a {{
            color: #8b5cf6;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="icon">{icon}</div>
            <h1>{title}</h1>
        </div>
        
        <div class="content">
            <p class="greeting">{greeting}</p>
            
            <div class="details-box">
                <div class="detail-row">
                    <span class="detail-label">Plan</span>
                    <span class="detail-value">{plan_name}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Status</span>
                    <span class="detail-value">{'Cancelled' if action_type == 'admin_cancel' else 'Active'}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Validity</span>
                    <span class="detail-value">{validity_text}</span>
                </div>
            </div>
            
            <p style="color: #64748b;">{validity_detail}</p>
            
            <div style="text-align: center; margin-top: 30px;">
                <a href="https://gogotrip.com/billing" class="cta-button">
                    View My Subscription
                </a>
            </div>
        </div>
        
        <div class="footer">
            <p>Thank you for choosing GogoTrip!</p>
            <p>
                <a href="https://gogotrip.com">Visit our website</a> | 
                <a href="mailto:support@gogotrip.com">Contact Support</a>
            </p>
            <p>© 2024 GogoTrip. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""
    
    text_content = f"""
{title}

{greeting}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Subscription Details:
- Plan: {plan_name}
- Status: {'Cancelled' if action_type == 'admin_cancel' else 'Active'}
- Validity: {validity_text}

{validity_detail}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

View your subscription: https://gogotrip.com/billing

---
Thank you for choosing GogoTrip!
© 2024 GogoTrip. All rights reserved.
"""
    
    return subject, html_content, text_content


def generate_admin_notification_email_html(
    user_name: str,
    title: str,
    message: str,
    notification_type: str = 'info'
) -> tuple:
    """
    Generate HTML email content for admin broadcast notifications.
    
    Args:
        user_name: User's display name
        title: Notification title
        message: Notification message
        notification_type: 'info', 'success', 'warning', 'alert'
    
    Returns:
        tuple: (subject, html_content, text_content)
    """
    
    # Color scheme based on type
    color_map = {
        'info': ('#3b82f6', '#dbeafe', 'ℹ️'),
        'success': ('#10b981', '#d1fae5', '✅'),
        'warning': ('#f59e0b', '#fef3c7', '⚠️'),
        'alert': ('#ef4444', '#fee2e2', '🚨')
    }
    
    primary_color, bg_color, icon = color_map.get(notification_type, color_map['info'])
    
    subject = f"📢 {title}" if title else "📢 New Notification from GogoTrip"
    
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #334155;
            background-color: #f1f5f9;
            margin: 0;
            padding: 0;
        }}
        .email-container {{
            max-width: 600px;
            margin: 40px auto;
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
        .header {{
            background: linear-gradient(135deg, {primary_color} 0%, {primary_color}dd 100%);
            padding: 40px 30px;
            text-align: center;
            color: white;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 700;
        }}
        .header .icon {{
            font-size: 48px;
            margin-bottom: 16px;
        }}
        .content {{
            padding: 40px 30px;
        }}
        .greeting {{
            font-size: 16px;
            color: #64748b;
            margin-bottom: 20px;
        }}
        .message-box {{
            background: {bg_color};
            border-left: 4px solid {primary_color};
            border-radius: 8px;
            padding: 20px 25px;
            margin: 25px 0;
        }}
        .message-title {{
            font-size: 18px;
            font-weight: 700;
            color: #1e293b;
            margin-bottom: 10px;
        }}
        .message-text {{
            font-size: 15px;
            color: #475569;
            white-space: pre-wrap;
        }}
        .footer {{
            background: #f8fafc;
            padding: 30px;
            text-align: center;
            font-size: 13px;
            color: #94a3b8;
        }}
        .footer a {{
            color: {primary_color};
            text-decoration: none;
        }}
        .unsubscribe {{
            margin-top: 20px;
            font-size: 12px;
            color: #94a3b8;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="icon">{icon}</div>
            <h1>New Notification</h1>
        </div>
        
        <div class="content">
            <p class="greeting">Hi {user_name},</p>
            
            <div class="message-box">
                {f'<p class="message-title">{title}</p>' if title else ''}
                <p class="message-text">{message}</p>
            </div>
            
            <div style="text-align: center; margin-top: 30px;">
                <a href="https://gogotrip.com" style="display: inline-block; background: {primary_color}; color: white; padding: 14px 32px; border-radius: 10px; text-decoration: none; font-weight: 600;">
                    Go to GogoTrip
                </a>
            </div>
        </div>
        
        <div class="footer">
            <p>
                <a href="https://gogotrip.com">Visit our website</a> | 
                <a href="mailto:support@gogotrip.com">Contact Support</a>
            </p>
            <p class="unsubscribe">
                You received this email because you opted in to notifications.<br>
                <a href="https://gogotrip.com/settings">Manage your email preferences</a>
            </p>
            <p>© 2024 GogoTrip. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""
    
    text_content = f"""
New Notification from GogoTrip

Hi {user_name},

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{title}

{message}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Visit GogoTrip: https://gogotrip.com

---
You received this email because you opted in to notifications.
Manage preferences: https://gogotrip.com/settings

© 2024 GogoTrip. All rights reserved.
"""
    
    return subject, html_content, text_content


def send_temp_password_email(to_email, temp_password):
    """
    Send temporary password email when admin creates a user.
    """
    if not is_valid_email(to_email):
        return False

    sender_email = config.MAIL_USERNAME
    sender_password = config.MAIL_PASSWORD

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <div style="max-width: 500px; margin: auto; border: 1px solid #eee; padding: 20px; border-radius: 10px;">
                <h2 style="color: #007BFF;">Welcome to GogoTrip</h2>
                <p>An administrator has created an account for you.</p>
                <p>Your login email: <strong>{to_email}</strong></p>
                <p>Your temporary password:</p>
                <div style="background: #f0f0f0; padding: 10px; text-align: center; font-size: 20px; font-weight: bold; letter-spacing: 2px;">
                    {temp_password}
                </div>
                <p style="color: #666; font-size: 12px; margin-top: 20px;">We recommend changing your password after logging in.</p>
            </div>
        </body>
    </html>
    """

    message = MIMEText(html_content, 'html', 'utf-8')
    message['From'] = Header(f"GogoTrip Admin <{sender_email}>", 'utf-8')
    message['To'] = to_email
    message['Subject'] = Header("【GogoTrip】Your Temporary Account Password", 'utf-8')

    try:
        with smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, message.as_string())
        print(f"✅ Temporary password sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email sending failed: {str(e)}")
        return False