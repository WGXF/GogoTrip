# routes/auth.py
import os
# [修改 1] 记得在导入里加上 jsonify
from flask import Blueprint, redirect, request, session, url_for, jsonify
from google_auth_oauthlib.flow import Flow

import config
from utils import credentials_to_dict
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

auth_bp = Blueprint('auth', __name__)

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
    
    # [修改 2] 登录成功后，不再跳回 Flask 首页，而是跳回 React 前端 (localhost:3000)
    # 这样浏览器就会加载你的 React Dashboard
    return redirect("/")

@auth_bp.route('/revoke')
def revoke():
    session.pop('credentials', None)
    # [修改 3] 登出后也跳回前端
    return redirect("/")

# [新增] 这是一个给 React 调用的接口
# React 的 App.tsx 会访问这个地址，看 session 里有没有 credentials
@auth_bp.route('/check_login_status')
def check_login():
    if 'credentials' in session:
        return jsonify({"logged_in": True})
    else:
        return jsonify({"logged_in": False})
