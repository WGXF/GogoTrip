# routes/admin_chat.py
# 💬 Admin Realtime Chatbox API & WebSocket
# 独立于 Admin Messaging，专用于即时聊天

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, User
from models import AdminChatRoom, AdminChatMember, AdminChatMessage
from datetime import datetime
from functools import wraps

admin_chat_bp = Blueprint('admin_chat', __name__, url_prefix='/api/admin-chat')

# ================================================
# 🔒 权限装饰器
# ================================================
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in ['Administrator', 'Admin', 'super_admin']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


# ================================================
# 📋 获取聊天室列表
# ================================================
@admin_chat_bp.route('/rooms', methods=['GET'])
@admin_required
def get_chat_rooms():
    """获取当前 Admin 的所有聊天室"""
    rooms = AdminChatRoom.query.join(AdminChatMember).filter(
        AdminChatMember.admin_id == current_user.id,
        AdminChatRoom.is_active == True
    ).order_by(AdminChatRoom.last_message_at.desc().nullslast()).all()
    
    return jsonify({
        'success': True,
        'rooms': [room.to_dict(current_user.id) for room in rooms]
    })


# ================================================
# 👥 获取可聊天的 Admin 列表
# ================================================
@admin_chat_bp.route('/admins', methods=['GET'])
@admin_required
def get_admin_list():
    """获取所有可聊天的 Admin（排除自己）"""
    admins = User.query.filter(
        User.role.in_(['Administrator', 'Admin', 'super_admin']),
        User.id != current_user.id,
        User.status == 'active'
    ).all()
    
    return jsonify({
        'success': True,
        'admins': [{
            'id': admin.id,
            'name': admin.full_name,
            'email': admin.email,
            'avatar': admin.avatar_url,
            'role': admin.role
        } for admin in admins]
    })


# ================================================
# 💬 开始/获取私聊
# ================================================
@admin_chat_bp.route('/start/<int:admin_id>', methods=['POST'])
@admin_required
def start_chat(admin_id):
    """开始与另一个 Admin 的私聊"""
    # 验证目标 Admin
    target_admin = User.query.get(admin_id)
    if not target_admin or target_admin.role not in ['Administrator', 'Admin', 'super_admin']:
        return jsonify({'success': False, 'error': 'Admin not found'}), 404
    
    if target_admin.id == current_user.id:
        return jsonify({'success': False, 'error': 'Cannot chat with yourself'}), 400
    
    # 获取或创建聊天室
    room = AdminChatRoom.get_or_create_private_room(current_user.id, admin_id)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'room': room.to_dict(current_user.id)
    })


# ================================================
# 📩 获取聊天室消息
# ================================================
@admin_chat_bp.route('/rooms/<int:room_id>/messages', methods=['GET'])
@admin_required
def get_messages(room_id):
    """获取聊天室的消息历史"""
    # 验证是否为成员
    member = AdminChatMember.query.filter_by(
        room_id=room_id,
        admin_id=current_user.id
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    # 获取分页参数
    limit = request.args.get('limit', 50, type=int)
    before_id = request.args.get('before', None, type=int)
    
    # 查询消息
    query = AdminChatMessage.query.filter_by(room_id=room_id)
    
    if before_id:
        query = query.filter(AdminChatMessage.id < before_id)
    
    messages = query.order_by(AdminChatMessage.created_at.desc()).limit(limit).all()
    
    # 清除未读计数
    member.unread_count = 0
    member.last_read_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'messages': [msg.to_dict() for msg in reversed(messages)],
        'hasMore': len(messages) == limit
    })


# ================================================
# ✉️ 发送消息（HTTP 备用，主要用 Socket）
# ================================================
@admin_chat_bp.route('/rooms/<int:room_id>/messages', methods=['POST'])
@admin_required
def send_message(room_id):
    """发送消息（HTTP 方式，作为 Socket 失败时的备用）"""
    # 验证是否为成员
    member = AdminChatMember.query.filter_by(
        room_id=room_id,
        admin_id=current_user.id
    ).first()
    
    if not member:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    data = request.get_json()
    content = data.get('content', '').strip()
    
    if not content:
        return jsonify({'success': False, 'error': 'Content required'}), 400
    
    # 创建消息
    message = AdminChatMessage(
        room_id=room_id,
        sender_id=current_user.id,
        content=content,
        message_type=data.get('messageType', 'text')
    )
    db.session.add(message)
    
    # 更新聊天室
    room = AdminChatRoom.query.get(room_id)
    room.last_message_at = datetime.utcnow()
    room.last_message_preview = content[:50] + ('...' if len(content) > 50 else '')
    
    # 更新其他成员的未读计数
    other_members = AdminChatMember.query.filter(
        AdminChatMember.room_id == room_id,
        AdminChatMember.admin_id != current_user.id
    ).all()
    
    for m in other_members:
        m.unread_count += 1
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': message.to_dict()
    })


# ================================================
# ✅ 标记已读
# ================================================
@admin_chat_bp.route('/rooms/<int:room_id>/read', methods=['POST'])
@admin_required
def mark_read(room_id):
    """标记聊天室为已读"""
    member = AdminChatMember.query.filter_by(
        room_id=room_id,
        admin_id=current_user.id
    ).first()
    
    if member:
        member.unread_count = 0
        member.last_read_at = datetime.utcnow()
        db.session.commit()
    
    return jsonify({'success': True})


# ================================================
# 🔔 获取总未读数
# ================================================
@admin_chat_bp.route('/unread-count', methods=['GET'])
@admin_required
def get_unread_count():
    """获取所有聊天室的总未读消息数"""
    total = db.session.query(db.func.sum(AdminChatMember.unread_count)).filter(
        AdminChatMember.admin_id == current_user.id
    ).scalar() or 0
    
    return jsonify({
        'success': True,
        'unreadCount': total
    })
