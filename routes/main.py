# routes/main.py
from flask import Blueprint, session, render_template_string


main_bp = Blueprint('main', __name__)

def index():
    # 以前是返回 HTML 页面，现在 React 接管了前端
    # 这里只需要返回一个简单的 JSON 告诉我们后端活着就行
    return jsonify({
        "status": "online",
        "message": "GogoTrip Backend API is running. Please visit localhost:3000 for the frontend."
    })
