# routes/realtime.py
# 🔌 Real-time WebSocket 通信系统
# 包含：Ticket 聊天 + Admin 内部消息 + Admin Chatbox

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_login import current_user
from models import db, User, Ticket, TicketMessage, AdminMessage, AdminMessageRead, SystemNotification
from models import AdminChatRoom, AdminChatMember, AdminChatMessage  # 🔴 Admin Chatbox Models
from datetime import datetime
from functools import wraps

# ================================================
# 🔌 SocketIO 初始化
# ================================================
socketio = None

def init_socketio(app):
    """
    初始化 SocketIO
    在 main_app.py 中调用：
    
    from routes.realtime import init_socketio
    socketio = init_socketio(app)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    
    Redis Message Queue:
    - Enables SocketIO to work across multiple worker processes
    - Required for production with Gunicorn/uWSGI
    - Set REDIS_URL env var or defaults to localhost:6379
    """
    global socketio
    
    # Get Redis URL from config (defaults to None if not set)
    message_queue = app.config.get('SOCKETIO_MESSAGE_QUEUE')
    
    # For local development, default to localhost Redis if available
    if message_queue is None:
        message_queue = 'redis://localhost:6379/0'
    
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode='threading',
        message_queue=message_queue,
        engineio_logger=False
    )
    
    register_handlers(socketio)
    print("✅ SocketIO initialized successfully")
    return socketio


def get_socketio():
    """获取 socketio 实例"""
    return socketio


# ================================================
# 🔒 认证装饰器
# ================================================
def authenticated_only(f):
    """确保用户已登录"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
            return
        return f(*args, **kwargs)
    return wrapped


def admin_only(f):
    """确保是管理员"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
            return
        if current_user.role not in ['Administrator', 'Admin', 'super_admin']:
            emit('error', {'message': 'Admin access required'})
            return
        return f(*args, **kwargs)
    return wrapped


# ================================================
# 📡 注册所有事件处理器
# ================================================
def register_handlers(sio):
    """注册所有 SocketIO 事件处理器"""
    
    # =====================================
    # 🔗 连接管理
    # =====================================
    
    @sio.on('connect')
    def handle_connect():
        """客户端连接"""
        if current_user.is_authenticated:
            user_room = f'user_{current_user.id}'
            join_room(user_room)
            
            if current_user.role in ['Administrator', 'Admin', 'super_admin']:
                join_room('admins')
            
            print(f'✅ User {current_user.id} ({current_user.full_name}) connected')
            emit('connected', {
                'userId': current_user.id,
                'userName': current_user.full_name,
                'isAdmin': current_user.role in ['Administrator', 'Admin', 'super_admin']
            })
        else:
            print('❌ Unauthenticated connection attempt')
            disconnect()
    
    
    @sio.on('disconnect')
    def handle_disconnect():
        """客户端断开"""
        if current_user.is_authenticated:
            print(f'👋 User {current_user.id} disconnected')
    
    
    # =====================================
    # 🎫 Ticket 聊天
    # =====================================
    
    @sio.on('join_ticket')
    @authenticated_only
    def handle_join_ticket(data):
        """加入工单聊天室"""
        ticket_id = data.get('ticketId')
        if not ticket_id:
            emit('error', {'message': 'Ticket ID required'})
            return
        
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            emit('error', {'message': 'Ticket not found'})
            return
        
        is_admin = current_user.role in ['Administrator', 'Admin', 'super_admin']
        if not is_admin and ticket.user_id != current_user.id:
            emit('error', {'message': 'Access denied'})
            return
        
        room = f'ticket_{ticket_id}'
        join_room(room)
        
        print(f'📩 User {current_user.id} joined ticket room: {room}')
        emit('joined_ticket', {'ticketId': ticket_id, 'room': room})
    
    
    @sio.on('leave_ticket')
    @authenticated_only
    def handle_leave_ticket(data):
        """离开工单聊天室"""
        ticket_id = data.get('ticketId')
        if ticket_id:
            room = f'ticket_{ticket_id}'
            leave_room(room)
            print(f'👋 User {current_user.id} left ticket room: {room}')
    
    
    @sio.on('ticket_message')
    @authenticated_only
    def handle_ticket_message(data):
        """发送工单消息"""
        ticket_id = data.get('ticketId')
        content = data.get('content', '').strip()
        message_type = data.get('messageType', 'text')
        
        if not ticket_id or not content:
            emit('error', {'message': 'Ticket ID and content required'})
            return
        
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            emit('error', {'message': 'Ticket not found'})
            return
        
        is_admin = current_user.role in ['Administrator', 'Admin', 'super_admin']
        
        if not is_admin:
            if ticket.user_id != current_user.id:
                emit('error', {'message': 'Access denied'})
                return
            if ticket.status not in ['accepted', 'in_progress']:
                emit('error', {'message': 'Ticket not active'})
                return
            sender_type = 'user'
        else:
            sender_type = 'admin'
            if ticket.status == 'accepted':
                ticket.status = 'in_progress'
        
        message = TicketMessage(
            ticket_id=ticket_id,
            sender_id=current_user.id,
            sender_type=sender_type,
            content=content,
            message_type=message_type
        )
        db.session.add(message)
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        
        message_data = {
            'id': message.id,
            'ticketId': ticket_id,
            'senderId': current_user.id,
            'senderType': sender_type,
            'senderName': current_user.full_name,
            'senderAvatar': current_user.avatar_url,
            'content': content,
            'messageType': message_type,
            'createdAt': message.created_at.isoformat()
        }
        
        room = f'ticket_{ticket_id}'
        emit('new_ticket_message', message_data, room=room)
        
        if sender_type == 'user':
            emit('ticket_activity', {
                'type': 'new_message',
                'ticketId': ticket_id,
                'ticketSubject': ticket.subject,
                'userName': current_user.full_name,
                'preview': content[:50] + '...' if len(content) > 50 else content
            }, room='admins')
        else:
            user_room = f'user_{ticket.user_id}'
            emit('ticket_activity', {
                'type': 'admin_reply',
                'ticketId': ticket_id,
                'ticketSubject': ticket.subject,
                'adminName': current_user.full_name,
                'preview': content[:50] + '...' if len(content) > 50 else content
            }, room=user_room)
        
        print(f'💬 New message in ticket {ticket_id} from {sender_type} {current_user.id}')
    
    
    @sio.on('ticket_typing')
    @authenticated_only
    def handle_ticket_typing(data):
        """输入状态通知"""
        ticket_id = data.get('ticketId')
        is_typing = data.get('isTyping', False)
        
        if not ticket_id:
            return
        
        is_admin = current_user.role in ['Administrator', 'Admin', 'super_admin']
        
        room = f'ticket_{ticket_id}'
        emit('user_typing', {
            'ticketId': ticket_id,
            'userId': current_user.id,
            'userName': current_user.full_name,
            'isAdmin': is_admin,
            'isTyping': is_typing
        }, room=room, include_self=False)
    
    
    # =====================================
    # 📢 Admin 内部消息（Admin Messaging）
    # =====================================
    
    @sio.on('admin_message')
    @admin_only
    def handle_admin_message(data):
        """Admin 发送内部消息"""
        is_broadcast = data.get('isBroadcast', False)
        recipient_id = data.get('recipientId')
        subject = data.get('subject')
        content = data.get('content', '').strip()
        priority = data.get('priority', 'normal')
        
        if not content:
            emit('error', {'message': 'Content required'})
            return
        
        if not is_broadcast and not recipient_id:
            emit('error', {'message': 'Recipient or broadcast flag required'})
            return
        
        message = AdminMessage(
            sender_id=current_user.id,
            recipient_id=recipient_id if not is_broadcast else None,
            is_broadcast=is_broadcast,
            subject=subject,
            content=content,
            priority=priority
        )
        db.session.add(message)
        db.session.commit()
        
        message_data = {
            'id': message.id,
            'senderId': current_user.id,
            'senderName': current_user.full_name,
            'senderAvatar': current_user.avatar_url,
            'recipientId': recipient_id,
            'isBroadcast': is_broadcast,
            'subject': subject,
            'content': content,
            'priority': priority,
            'createdAt': message.created_at.isoformat()
        }
        
        if is_broadcast:
            emit('new_admin_message', message_data, room='admins')
            print(f'📢 Admin broadcast from {current_user.id}')
        else:
            recipient_room = f'user_{recipient_id}'
            emit('new_admin_message', message_data, room=recipient_room)
            emit('admin_message_sent', message_data)
            print(f'✉️ Admin message from {current_user.id} to {recipient_id}')
    
    
    # =====================================
    # 💬 Admin Chatbox（即时聊天）
    # =====================================
    
    @sio.on('join_admin_chat')
    @admin_only
    def handle_join_admin_chat(data):
        """加入 Admin 聊天室"""
        room_id = data.get('roomId')
        if not room_id:
            emit('error', {'message': 'Room ID required'})
            return
        
        member = AdminChatMember.query.filter_by(
            room_id=room_id,
            admin_id=current_user.id
        ).first()
        
        if not member:
            emit('error', {'message': 'Access denied'})
            return
        
        socket_room = f'admin_chat_{room_id}'
        join_room(socket_room)
        
        member.unread_count = 0
        member.last_read_at = datetime.utcnow()
        db.session.commit()
        
        print(f'💬 Admin {current_user.id} joined chat room: {socket_room}')
        emit('joined_admin_chat', {'roomId': room_id})
    
    
    @sio.on('leave_admin_chat')
    @admin_only
    def handle_leave_admin_chat(data):
        """离开 Admin 聊天室"""
        room_id = data.get('roomId')
        if room_id:
            socket_room = f'admin_chat_{room_id}'
            leave_room(socket_room)
            print(f'👋 Admin {current_user.id} left chat room: {socket_room}')
    
    
    @sio.on('admin_chat_message')
    @admin_only
    def handle_admin_chat_message(data):
        """发送 Admin 聊天消息"""
        room_id = data.get('roomId')
        content = data.get('content', '').strip()
        message_type = data.get('messageType', 'text')
        
        if not room_id or not content:
            emit('error', {'message': 'Room ID and content required'})
            return
        
        member = AdminChatMember.query.filter_by(
            room_id=room_id,
            admin_id=current_user.id
        ).first()
        
        if not member:
            emit('error', {'message': 'Access denied'})
            return
        
        message = AdminChatMessage(
            room_id=room_id,
            sender_id=current_user.id,
            content=content,
            message_type=message_type
        )
        db.session.add(message)
        
        room = AdminChatRoom.query.get(room_id)
        room.last_message_at = datetime.utcnow()
        room.last_message_preview = content[:50] + ('...' if len(content) > 50 else '')
        
        other_members = AdminChatMember.query.filter(
            AdminChatMember.room_id == room_id,
            AdminChatMember.admin_id != current_user.id
        ).all()
        
        for m in other_members:
            m.unread_count += 1
        
        db.session.commit()
        
        message_data = {
            'id': message.id,
            'roomId': room_id,
            'senderId': current_user.id,
            'senderName': current_user.full_name,
            'senderAvatar': current_user.avatar_url,
            'content': content,
            'messageType': message_type,
            'createdAt': message.created_at.isoformat()
        }
        
        socket_room = f'admin_chat_{room_id}'
        emit('new_admin_chat_message', message_data, room=socket_room)
        
        for m in other_members:
            user_room = f'user_{m.admin_id}'
            emit('admin_chat_notification', {
                'type': 'new_message',
                'roomId': room_id,
                'senderName': current_user.full_name,
                'preview': content[:30] + ('...' if len(content) > 30 else '')
            }, room=user_room)
        
        print(f'💬 Admin chat message in room {room_id} from {current_user.id}')
    
    
    @sio.on('admin_chat_typing')
    @admin_only
    def handle_admin_chat_typing(data):
        """Admin Chatbox 输入状态"""
        room_id = data.get('roomId')
        is_typing = data.get('isTyping', False)
        
        if not room_id:
            return
        
        socket_room = f'admin_chat_{room_id}'
        emit('admin_chat_user_typing', {
            'roomId': room_id,
            'userId': current_user.id,
            'userName': current_user.full_name,
            'isTyping': is_typing
        }, room=socket_room, include_self=False)
    
    
    @sio.on('admin_chat_read')
    @admin_only
    def handle_admin_chat_read(data):
        """标记 Admin Chatbox 已读"""
        room_id = data.get('roomId')
        if not room_id:
            return
        
        member = AdminChatMember.query.filter_by(
            room_id=room_id,
            admin_id=current_user.id
        ).first()
        
        if member:
            member.unread_count = 0
            member.last_read_at = datetime.utcnow()
            db.session.commit()
            emit('admin_chat_marked_read', {'roomId': room_id})
    
    
    # =====================================
    # 🔔 系统通知
    # =====================================
    
    @sio.on('mark_notification_read')
    @authenticated_only
    def handle_mark_notification_read(data):
        """标记通知为已读"""
        notification_id = data.get('notificationId')
        if notification_id:
            notif = SystemNotification.query.get(notification_id)
            if notif:
                notif.is_read = True
                notif.read_at = datetime.utcnow()
                db.session.commit()
                emit('notification_read', {'notificationId': notification_id})
    
    
    print("✅ All WebSocket handlers registered")


# ================================================
# 🔔 辅助函数：从外部发送实时通知
# ================================================

def notify_new_ticket(ticket):
    """通知所有 Admin 有新工单"""
    sio = get_socketio()
    if sio:
        sio.emit('new_ticket', {
            'type': 'new_ticket',
            'ticketId': ticket.id,
            'subject': ticket.subject,
            'userName': ticket.user.full_name if ticket.user else 'Unknown',
            'userAvatar': ticket.user.avatar_url if ticket.user else None,
            'category': ticket.category,
            'priority': ticket.priority,
            'createdAt': ticket.created_at.isoformat()
        }, room='admins')


def notify_ticket_accepted(ticket, admin):
    """通知用户工单已被接受"""
    sio = get_socketio()
    if sio:
        user_room = f'user_{ticket.user_id}'
        sio.emit('ticket_accepted', {
            'ticketId': ticket.id,
            'subject': ticket.subject,
            'adminName': admin.full_name,
            'adminAvatar': admin.avatar_url
        }, room=user_room)


def notify_ticket_resolved(ticket):
    """通知用户工单已解决"""
    sio = get_socketio()
    if sio:
        user_room = f'user_{ticket.user_id}'
        sio.emit('ticket_resolved', {
            'ticketId': ticket.id,
            'subject': ticket.subject
        }, room=user_room)


def notify_user(user_id, event, data):
    """通用：通知特定用户"""
    sio = get_socketio()
    if sio:
        user_room = f'user_{user_id}'
        sio.emit(event, data, room=user_room)


def notify_all_admins(event, data):
    """通用：通知所有 Admin"""
    sio = get_socketio()
    if sio:
        sio.emit(event, data, room='admins')
