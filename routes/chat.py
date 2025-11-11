# routes/chat.py
from flask import Blueprint, request, session, jsonify
from ai_agent import get_ai_chat_response # 从 ai_agent 导入

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/chat_message', methods=['POST'])
def chat_message():
    if 'credentials' not in session:
        return jsonify({'error': '用户未登录'}), 401
    try:
        data = request.json
        user_message = data.get('message', '').strip()
        history = data.get('history', [])
        coordinates = data.get('coordinates') # 获取 GPS
        user_ip = request.remote_addr        # 获取 IP

        if not user_message:
            return jsonify({'error': '消息内容为空'}), 400

        history.append({'role': 'user', 'parts': [user_message]})

        ai_response_text = get_ai_chat_response(
            history,
            session['credentials'],
            coordinates,
            user_ip
        )

        history.append({'role': 'model', 'parts': [ai_response_text]})

        return jsonify({
            'reply': ai_response_text,
            'history': history
        })
    except Exception as e:
        print(f"--- [聊天错误] /chat_message 路由出错: {e} ---")
        return jsonify({'error': str(e)}), 500