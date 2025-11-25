# routes/auth.py
import os
from flask import Blueprint, redirect, request, session, url_for
from google_auth_oauthlib.flow import Flow

import config
from utils import credentials_to_dict # 从 utils 导入

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES)
    flow.redirect_uri = url_for('auth.oauth2callback', _external=True)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'  # <---【关键修改】添加这一行，强制显示同意屏幕
    )
    
    session['state'] = state
    return redirect(authorization_url)

@auth_bp.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES, state=state)
    flow.redirect_uri = url_for('auth.oauth2callback', _external=True)
    # 使用 request.url 获取 Google 重定向回来的完整 URL
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials) # 使用导入的函数
    session['message'] = "授权成功！您的 Google 日历已连接。"
    return redirect(url_for('main.index')) # 重定向回主页蓝图的 index

@auth_bp.route('/revoke')
def revoke():
    session.pop('credentials', None)
    session['message'] = "您已成功断开与 Google 日历的连接。"

    return redirect(url_for('main.index'))
