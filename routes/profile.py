from fileinput import filename
import os
from flask import Blueprint, request, jsonify, url_for, current_app

from werkzeug.utils import secure_filename
from models import db, User  # 导入你的 User model 和 db
from flask_login import current_user, login_required # 假设你用了 Flask-Login
from datetime import datetime

profile_bp = Blueprint('profile', __name__)

# 配置允许上传的图片格式
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@profile_bp.route('/update-profile', methods=['PUT'])
@login_required  # 确保只有登录用户能改
def update_profile():
    try:
        user = User.query.get(current_user.id)
        if not user:
            return jsonify({'message': 'User not found'}), 404

        # 1. 更新普通文字信息 (Full Name)
        full_name = request.form.get('name') # 注意：用 request.form 获取文字
        if full_name:
            user.full_name = full_name

        # 🆕 2. 更新 Email Notifications Preference
        email_notifs = request.form.get('emailNotifications')
        if email_notifs is not None:
            # Handle string 'true'/'false' from FormData
            user.email_notifications = email_notifs.lower() == 'true' if isinstance(email_notifs, str) else bool(email_notifs)

        # 🆕 3. 更新 Language Preference (i18n)
        preferred_language = request.form.get('preferredLanguage')
        if preferred_language is not None:
            # Validate language code (only allow supported languages)
            supported_languages = ['en', 'zh', 'ms']
            if preferred_language in supported_languages:
                user.preferred_language = preferred_language

        # 3. 处理头像上传
        if 'avatar' in request.files:
            file = request.files['avatar']
            
            if file and allowed_file(file.filename):
                # 确保文件名安全
                file.seek(0, os.SEEK_END)
                file_length = file.tell()
                
                # 限制为 1MB (1 * 1024 * 1024 Bytes)
                if file_length > 1 * 1024 * 1024:
                    return jsonify({
                        'status': 'error',
                        'message': 'File size exceeds 1MB limit.'
                    }), 400
                
                # 重要：检查完大小后，必须把指针重置回开头，否则保存时是空文件！
                file.seek(0)
                filename = secure_filename(file.filename)
                
                # 为了防止文件名冲突，最好加上用户ID或时间戳
                # 例如: avatar_123.jpg
                timestamp = int(datetime.now().timestamp())
                unique_filename = f"avatar_{user.id}_{timestamp}.{filename.rsplit('.', 1)[1].lower()}"
                
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
                os.makedirs(upload_folder, exist_ok=True)
                
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                
                # 注意：这里加了 /api 前缀吗？如果没有，直接 /static 也可以
                # 建议统一加上 host，或者直接相对路径
                user.avatar_url = f"/static/uploads/avatars/{unique_filename}"
        
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': 'Profile updated successfully',
            'user': user.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 500