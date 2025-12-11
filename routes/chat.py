# routes/chat.py
from flask import Blueprint, request, session, jsonify
from ai_agent import get_ai_chat_response 

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/chat_message', methods=['POST'])
def chat_message():
    # 1. 不再强制检查登录，而是尝试获取凭证
    # 如果没登录，user_credentials 就是 None
    user_credentials = session.get('credentials')

    try:
        data = request.json
        user_message = data.get('message', '').strip()
        history = data.get('history', [])
        coordinates = data.get('coordinates')
        user_ip = request.remote_addr

        if not user_message:
            return jsonify({'error': '消息内容为空'}), 400

        history.append({'role': 'user', 'parts': [user_message]})

        # 2. 调用 AI 函数，传入凭证 (可能是 None，也可能是字典)
        ai_response_text = get_ai_chat_response(
            history,
            user_credentials, # <--- 传入这个变量
            coordinates=coordinates,
            user_ip=user_ip
        )

        history.append({'role': 'model', 'parts': [ai_response_text]})

        return jsonify({
            'reply': ai_response_text,
            'history': history
        })
    except Exception as e:
        print(f"--- [聊天错误] /chat_message 路由出错: {e} ---")
        return jsonify({'error': str(e)}), 500