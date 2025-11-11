# utils.py
import re
from google.oauth2.credentials import Credentials

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