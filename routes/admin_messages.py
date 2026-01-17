# routes/admin_messages.py
# 📢 Admin 内部消息系统 API 路由

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, User, AdminMessage, AdminMessageRead, SystemNotification
from datetime import datetime
from functools import wraps

admin_messages_bp = Blueprint('admin_messages', __name__, url_prefix='/api/admin-messages')


# ================================================
# 🔒 权限装饰器
# ================================================
def admin_required(f):
    """需要管理员权限"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Unauthorized'}), 401
        if current_user.role not in ['Administrator', 'Admin', 'super_admin']:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    """需要超级管理员权限"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Unauthorized'}), 401
        if current_user.role not in ['super_admin', 'Administrator']:
            return jsonify({'error': 'Super Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


# ================================================
# 📬 获取消息
# ================================================

@admin_messages_bp.route('', methods=['GET'])
@login_required
@admin_required
def get_admin_messages():
    """获取当前 Admin 的所有消息"""
    try:
        message_type = request.args.get('type', 'all')  # all / received / sent
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        if message_type == 'sent':
            # 我发送的消息
            query = AdminMessage.query.filter_by(sender_id=current_user.id)
        elif message_type == 'received':
            # 我收到的消息（包括广播）
            query = AdminMessage.query.filter(
                (AdminMessage.recipient_id == current_user.id) |
                (AdminMessage.is_broadcast == True)
            )
        else:
            # 所有相关消息
            query = AdminMessage.query.filter(
                (AdminMessage.sender_id == current_user.id) |
                (AdminMessage.recipient_id == current_user.id) |
                (AdminMessage.is_broadcast == True)
            )
        
        messages = query.order_by(AdminMessage.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # 获取已读状态
        read_message_ids = set(
            r.message_id for r in 
            AdminMessageRead.query.filter_by(admin_id=current_user.id).all()
        )
        
        result = []
        for msg in messages.items:
            msg_dict = msg.to_dict()
            # 判断是否已读
            if msg.sender_id == current_user.id:
                msg_dict['isRead'] = True  # 自己发的默认已读
            else:
                msg_dict['isRead'] = msg.id in read_message_ids
            result.append(msg_dict)
        
        # 统计未读数
        unread_count = AdminMessage.query.filter(
            ((AdminMessage.recipient_id == current_user.id) | (AdminMessage.is_broadcast == True)),
            AdminMessage.sender_id != current_user.id,
            ~AdminMessage.id.in_(read_message_ids) if read_message_ids else True
        ).count()
        
        return jsonify({
            'success': True,
            'messages': result,
            'total': messages.total,
            'pages': messages.pages,
            'currentPage': page,
            'unreadCount': unread_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_messages_bp.route('/<int:message_id>', methods=['GET'])
@login_required
@admin_required
def get_message_detail(message_id):
    """获取消息详情"""
    try:
        message = AdminMessage.query.get_or_404(message_id)
        
        # 验证访问权限
        if not (message.is_broadcast or 
                message.sender_id == current_user.id or 
                message.recipient_id == current_user.id):
            return jsonify({'error': 'Access denied'}), 403
        
        # 标记为已读
        if message.sender_id != current_user.id:
            existing = AdminMessageRead.query.filter_by(
                message_id=message_id,
                admin_id=current_user.id
            ).first()
            
            if not existing:
                read_record = AdminMessageRead(
                    message_id=message_id,
                    admin_id=current_user.id
                )
                db.session.add(read_record)
                db.session.commit()
        
        msg_dict = message.to_dict()
        msg_dict['isRead'] = True
        
        return jsonify({
            'success': True,
            'message': msg_dict
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# ✉️ 发送消息（Super Admin）
# ================================================

@admin_messages_bp.route('/send', methods=['POST'])
@login_required
@super_admin_required
def send_admin_message():
    """
    Super Admin 发送消息
    可以发送给单个 Admin 或广播给所有 Admin
    """
    try:
        data = request.get_json()
        
        is_broadcast = data.get('isBroadcast', False)
        recipient_id = data.get('recipientId')
        
        # 验证
        if not is_broadcast and not recipient_id:
            return jsonify({'error': 'Please specify a recipient or send as broadcast'}), 400
        
        if recipient_id:
            recipient = User.query.get(recipient_id)
            if not recipient or recipient.role not in ['Administrator', 'Admin', 'super_admin']:
                return jsonify({'error': 'Invalid recipient'}), 400
        
        # 创建消息
        message = AdminMessage(
            sender_id=current_user.id,
            recipient_id=recipient_id if not is_broadcast else None,
            is_broadcast=is_broadcast,
            subject=data.get('subject'),
            content=data['content'],
            message_type=data.get('messageType', 'message'),
            priority=data.get('priority', 'normal'),
            attachment_url=data.get('attachmentUrl')
        )
        db.session.add(message)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message.to_dict(),
            'info': 'Message sent to all admins' if is_broadcast else f'Message sent to {recipient.full_name}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_messages_bp.route('/broadcast', methods=['POST'])
@login_required
@super_admin_required
def broadcast_to_admins():
    """
    Super Admin 广播消息给所有 Admin
    """
    try:
        data = request.get_json()
        
        message = AdminMessage(
            sender_id=current_user.id,
            recipient_id=None,
            is_broadcast=True,
            subject=data.get('subject'),
            content=data['content'],
            message_type=data.get('messageType', 'announcement'),
            priority=data.get('priority', 'high'),
            attachment_url=data.get('attachmentUrl')
        )
        db.session.add(message)
        db.session.commit()
        
        # 统计接收人数
        admin_count = User.query.filter(
            User.role.in_(['Administrator', 'Admin', 'super_admin']),
            User.id != current_user.id
        ).count()
        
        return jsonify({
            'success': True,
            'message': message.to_dict(),
            'recipientCount': admin_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================================
# ✅ 标记已读
# ================================================

@admin_messages_bp.route('/<int:message_id>/read', methods=['POST'])
@login_required
@admin_required
def mark_message_read(message_id):
    """标记消息为已读"""
    try:
        message = AdminMessage.query.get_or_404(message_id)
        
        existing = AdminMessageRead.query.filter_by(
            message_id=message_id,
            admin_id=current_user.id
        ).first()
        
        if not existing:
            read_record = AdminMessageRead(
                message_id=message_id,
                admin_id=current_user.id
            )
            db.session.add(read_record)
            db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_messages_bp.route('/read-all', methods=['POST'])
@login_required
@admin_required
def mark_all_messages_read():
    """标记所有消息为已读"""
    try:
        # 获取所有未读消息
        unread_messages = AdminMessage.query.filter(
            ((AdminMessage.recipient_id == current_user.id) | (AdminMessage.is_broadcast == True)),
            AdminMessage.sender_id != current_user.id
        ).all()
        
        for msg in unread_messages:
            existing = AdminMessageRead.query.filter_by(
                message_id=msg.id,
                admin_id=current_user.id
            ).first()
            
            if not existing:
                read_record = AdminMessageRead(
                    message_id=msg.id,
                    admin_id=current_user.id
                )
                db.session.add(read_record)
        
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# 👥 获取 Admin 列表（用于选择接收者）
# ================================================

@admin_messages_bp.route('/admins', methods=['GET'])
@login_required
@admin_required
def get_admin_list():
    """获取所有 Admin 列表（用于消息发送选择）"""
    try:
        admins = User.query.filter(
            User.role.in_(['Administrator', 'Admin', 'super_admin']),
            User.status == 'active'
        ).all()
        
        result = []
        for admin in admins:
            result.append({
                'id': admin.id,
                'name': admin.full_name,
                'email': admin.email,
                'role': admin.role,
                'avatarUrl': admin.avatar_url,
                'isCurrentUser': admin.id == current_user.id
            })
        
        return jsonify({
            'success': True,
            'admins': result
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# 🔔 系统通知（Admin 端）
# ================================================

@admin_messages_bp.route('/system-notifications', methods=['GET'])
@login_required
@admin_required
def get_system_notifications():
    """获取 Admin 的系统通知"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # 获取发给所有 Admin 或特定 Admin 的通知
        notifications = SystemNotification.query.filter(
            (SystemNotification.recipient_type == 'all_admins') |
            ((SystemNotification.recipient_type == 'admin') & 
             (SystemNotification.recipient_id == current_user.id))
        ).order_by(SystemNotification.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # 统计未读
        unread_count = SystemNotification.query.filter(
            ((SystemNotification.recipient_type == 'all_admins') |
             ((SystemNotification.recipient_type == 'admin') & 
              (SystemNotification.recipient_id == current_user.id))),
            SystemNotification.is_read == False
        ).count()
        
        return jsonify({
            'success': True,
            'notifications': [n.to_dict() for n in notifications.items],
            'total': notifications.total,
            'pages': notifications.pages,
            'currentPage': page,
            'unreadCount': unread_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_messages_bp.route('/system-notifications/<int:notif_id>/read', methods=['POST'])
@login_required
@admin_required
def mark_system_notification_read(notif_id):
    """标记系统通知为已读"""
    try:
        notification = SystemNotification.query.get_or_404(notif_id)
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
