# routes/auth.py
import os
import random
import datetime  # [修复 1] 必须导入 datetime
from flask import Blueprint, redirect, request, session, url_for, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from google_auth_oauthlib.flow import Flow

import config
# [修复 2] 必须从 models 导入 db，否则无法进行数据库操作
from models import db, User, EmailVerification 
from utils import credentials_to_dict, is_valid_email, send_verification_email

# 允许 OAuth 使用 HTTP (开发环境)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

auth_bp = Blueprint('auth', __name__)

# [新增] 发送验证码接口
@auth_bp.route('/auth/send-code', methods=['POST'])
def send_code_api():
    """第一步：用户输入邮箱，点击发送验证码"""
    data = request.json
    email = data.get('email')

    if not email or not is_valid_email(email):
        return jsonify({"status": "error", "message": "无效的邮箱格式"}), 400

    # --- 互斥逻辑检查 ---
    user = User.query.filter_by(email=email).first()
    if user:
        # 如果用户存在，且有 Google ID，但没有密码 -> 说明他是通过 Google 注册的
        if user.google_id and not user.password_hash:
            return jsonify({
                "status": "error", 
                "message": "此邮箱已绑定 Google 账号，请直接使用 Google 登录。"
            }), 400
        
        # 如果用户存在，且有密码 -> 说明已经注册过了
        if user.password_hash:
             return jsonify({
                 "status": "error",
                 "message": "该邮箱已注册，请直接登录。"
             }), 400  # <--- 改成 return 400，前端就会收到错误，不会进入验证码界面

    # 生成验证码
    code = str(random.randint(100000, 999999))
    # 使用 datetime 设置 10 分钟有效期
    expires = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)

    # 存入数据库 (EmailVerification 表)
    # 先删除旧的记录
    EmailVerification.query.filter_by(email=email).delete()
    
    new_verify = EmailVerification(email=email, code=code, expires_at=expires)
    db.session.add(new_verify) # 现在 db 已经导入，可以正常使用了
    db.session.commit()

    # 发送邮件
    is_sent = send_verification_email(email, code)
    
    if is_sent:
        return jsonify({"status": "success", "message": "验证码已发送，请查收邮件"})
    else:
        return jsonify({"status": "error", "message": "邮件发送失败，请稍后重试"}), 500


@auth_bp.route('/auth/signup-verify', methods=['POST'])
def signup_verify_api():
    """第二步：用户输入验证码和密码，完成注册"""
    data = request.json
    email = data.get('email')
    code = data.get('code')
    password = data.get('password') # 用户设置的新密码

    # 1. 验证码校验
    record = EmailVerification.query.filter_by(email=email).first()
    
    if not record or record.code != code:
        return jsonify({"status": "error", "message": "验证码错误或不存在"}), 400
    
    if datetime.datetime.utcnow() > record.expires_at:
        return jsonify({"status": "error", "message": "验证码已过期"}), 400

    # 2. 创建或更新用户
    user = User.query.filter_by(email=email).first()
    
    if user:
        # 如果用户已存在
        if user.google_id:
             return jsonify({"status": "error", "message": "该账号已通过 Google 注册，请用 Google 登录"}), 400
        else:
             return jsonify({"status": "error", "message": "账号已存在，请去登录页面"}), 400

    # 新用户注册
    new_user = User(
        email=email,
        password_hash=generate_password_hash(password), # 密码加密存储
        is_email_verified=True,
        full_name=email.split('@')[0] # 默认名字
    )
    db.session.add(new_user)
    
    # 删除验证码记录
    db.session.delete(record)
    db.session.commit()

    # 自动登录
    session['user_id'] = new_user.id
    session['user_email'] = new_user.email
    
    return jsonify({"status": "success", "message": "注册成功", "user": new_user.to_dict()})


@auth_bp.route('/auth/login-email', methods=['POST'])
def login_email_api():
    """邮箱密码登录接口"""
    data = request.json
    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email).first()

    if not user:
        return jsonify({"status": "error", "message": "用户不存在"}), 404
    
    # 互斥检查：如果是 Google 账号且没密码
    if user.google_id and not user.password_hash:
        return jsonify({"status": "error", "message": "请使用 Google 账号登录"}), 400

    # 验证密码
    if check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        session['user_email'] = user.email
        # 模拟 credentials 以兼容 ai_agent
        session['credentials'] = {"token": "dummy_token_for_email_user"} 
        return jsonify({"status": "success", "message": "登录成功", "user": user.to_dict()})
    else:
        return jsonify({"status": "error", "message": "密码错误"}), 400
    
@auth_bp.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES)
    flow.redirect_uri = url_for('auth.oauth2callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@auth_bp.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES, state=state)
    flow.redirect_uri = url_for('auth.oauth2callback', _external=True)
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)

    # 获取 Google 用户信息
    from googleapiclient.discovery import build
    service = build('oauth2', 'v2', credentials=credentials)
    user_info = service.userinfo().get().execute()
    
    g_email = user_info.get('email')
    g_id = user_info.get('id')
    g_name = user_info.get('name')
    g_picture = user_info.get('picture')

    # 查库
    user = User.query.filter_by(email=g_email).first()
    
    if not user:
        # 创建新用户
        new_user = User(
            email=g_email,
            google_id=g_id,
            full_name=g_name,
            avatar_url=g_picture,
            is_email_verified=True
        )
        db.session.add(new_user)
        db.session.commit()
        session['user_id'] = new_user.id
    else:
        # 更新现有用户
        if not user.google_id:
            user.google_id = g_id # 绑定 Google ID
            user.is_email_verified = True
        session['user_id'] = user.id
        db.session.commit()

    return redirect("https://gogotrip.teocodes.com/")

@auth_bp.route('/check_login_status')
def check_login():
    # 1. 尝试获取 session 中的 user_id
    user_id = session.get('user_id')
    
    if user_id:
        # 2. 从数据库查出完整用户信息
        user = User.query.get(user_id)
        if user:
            return jsonify({
                "logged_in": True, 
                "user": user.to_dict(), # 关键：返回用户信息给前端恢复状态
                "role": user.role
            })
    
    return jsonify({"logged_in": False})

@auth_bp.route('/auth/logout', methods=['POST'])
def logout():
    session.clear() # 清空服务端 Session，这就导致 Cookie 失效
    
    return jsonify({"status": "success", "message": "已成功登出"})

