# utils.py
import re
import smtplib # 新增
from email.mime.text import MIMEText # 新增
from email.header import Header # 新增
from google.oauth2.credentials import Credentials

import config

def is_valid_email(email):
    """使用正则表达式简单检查邮箱格式是否有效。"""
    if not isinstance(email, str):
        return False
    # 修复了一个小拼写错误 .9 -> 0-9
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None

def credentials_to_dict(credentials):
    """将 Google Credentials 对象转换为字典以便存入 session。"""
    return {'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes}


def send_verification_email(to_email, code):
    """
    发送 6 位验证码到指定邮箱
    """
    if not is_valid_email(to_email):
        print(f"❌ 邮件格式错误: {to_email}")
        return False

    sender_email = config.MAIL_USERNAME
    sender_password = config.MAIL_PASSWORD
    
    # 简单的 HTML 邮件模板
    html_content = f"""
    <html>
        <body style="background: #f5f7fa; font-family: 'Segoe UI', Arial, sans-serif; padding: 40px;">

            <div style="
                max-width: 480px;
                margin: auto;
                background: #ffffff;
                padding: 30px 35px;
                border-radius: 12px;
                box-shadow: 0 6px 25px rgba(0,0,0,0.08);
                border: 1px solid #e6e9ef;
            ">
                <!-- Logo (optional) -->
                <div style="text-align: center; margin-bottom: 25px;">
                    <h2 style="
                        margin: 0;
                        font-size: 26px;
                        font-weight: 700;
                        color: #007BFF;
                        letter-spacing: 1px;
                    ">GogoTrip</h2>
                </div>

                <h3 style="font-size: 20px; color: #333; margin-bottom: 10px;">验证码验证</h3>

                <p style="font-size: 15px; color: #555; line-height: 1.7;">
                    您正在进行注册或登录操作，请使用以下验证码完成验证：
                </p>

                <div style="
                    text-align: center;
                    margin: 30px 0;
                    padding: 15px 0;
                    background: #f0f7ff;
                    border-radius: 10px;
                    border: 1px solid #cfe2ff;
                ">
                    <span style="
                        display: inline-block;
                        font-size: 36px;
                        font-weight: 700;
                        color: #007BFF;
                        letter-spacing: 8px;
                    ">{code}</span>
                </div>

                <p style="font-size: 14px; color: #666; line-height: 1.6;">
                    验证码有效期为 <strong>10 分钟</strong>。请勿将此验证码提供给任何人。
                </p>

                <p style="font-size: 13px; color: #999; margin-top: 25px;">
                    如果这不是您本人的操作，请忽略此邮件。
                </p>

                <hr style="border: 0; border-top: 1px solid #eee; margin: 25px 0;">

                <p style="font-size: 12px; color: #bbb; text-align: center;">
                    © 2077 GogoTrip. All left reserved.
                </p>
            </div>

        </body>
    </html>

    """

    message = MIMEText(html_content, 'html', 'utf-8')
    message['From'] = Header(f"GogoTrip <{sender_email}>", 'utf-8')
    message['To'] = to_email
    message['Subject'] = Header("【GogoTrip】您的验证码", 'utf-8')

    try:
        with smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT) as server:
            server.starttls() # 启用加密
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, message.as_string())
        
        print(f"✅ 邮件已成功发送给 {to_email}")
        return True

    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        return False