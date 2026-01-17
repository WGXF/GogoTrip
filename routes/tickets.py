# routes/tickets.py
# 🎫 Ticket 系统 API 路由

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, User, Ticket, TicketMessage, SystemNotification
from datetime import datetime, timedelta
from functools import wraps

tickets_bp = Blueprint('tickets', __name__, url_prefix='/api/tickets')


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
# 👤 USER ENDPOINTS - 用户端
# ================================================

@tickets_bp.route('/user', methods=['GET'])
@login_required
def get_user_tickets():
    """获取当前用户的所有工单"""
    try:
        status = request.args.get('status', 'all')
        
        query = Ticket.query.filter_by(user_id=current_user.id)
        
        if status != 'all':
            query = query.filter_by(status=status)
        
        tickets = query.order_by(Ticket.created_at.desc()).all()
        
        # 检查并更新过期状态
        for ticket in tickets:
            if ticket.is_expired() and ticket.status not in ['resolved', 'closed', 'expired']:
                ticket.status = 'expired'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'tickets': [t.to_preview_dict() for t in tickets]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/user', methods=['POST'])
@login_required
def create_ticket():
    """用户创建新工单"""
    try:
        data = request.get_json()
        
        # 检查是否有未解决的工单（可选：限制同时只能有一个活跃工单）
        active_tickets = Ticket.query.filter(
            Ticket.user_id == current_user.id,
            Ticket.status.in_(['pending', 'accepted', 'in_progress'])
        ).count()
        
        if active_tickets >= 3:
            return jsonify({
                'error': 'You already have 3 active tickets. Please wait for them to be resolved.'
            }), 400
        
        # 创建工单
        ticket = Ticket(
            user_id=current_user.id,
            subject=data['subject'],
            category=data.get('category', 'general'),
            priority=data.get('priority', 'normal')
        )
        db.session.add(ticket)
        db.session.flush()  # 获取 ticket.id
        
        # 添加初始消息
        if data.get('message'):
            first_message = TicketMessage(
                ticket_id=ticket.id,
                sender_id=current_user.id,
                sender_type='user',
                content=data['message']
            )
            db.session.add(first_message)
        
        # 创建系统通知给所有 Admin
        notification = SystemNotification(
            recipient_type='all_admins',
            title=f'New Support Ticket: {ticket.subject}',
            content=f'{current_user.full_name} has submitted a new ticket.',
            notification_type='ticket_new',
            related_type='ticket',
            related_id=ticket.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'ticket': ticket.to_dict(),
            'message': 'Ticket created successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/user/<int:ticket_id>', methods=['GET'])
@login_required
def get_user_ticket_detail(ticket_id):
    """获取工单详情（用户端）"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        # 验证权限
        if ticket.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        # 获取消息
        messages = TicketMessage.query.filter_by(ticket_id=ticket_id).order_by(
            TicketMessage.created_at.asc()
        ).all()
        
        # 标记 Admin 消息为已读
        unread_msgs = TicketMessage.query.filter(
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.sender_type == 'admin',
            TicketMessage.is_read == False
        ).all()
        
        for msg in unread_msgs:
            msg.is_read = True
            msg.read_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'ticket': ticket.to_dict(),
            'messages': [m.to_dict() for m in messages]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/user/<int:ticket_id>/message', methods=['POST'])
@login_required
def user_send_message(ticket_id):
    """用户在工单中发送消息"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        # 验证权限
        if ticket.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        # 检查工单状态
        if ticket.status in ['expired', 'closed']:
            return jsonify({'error': 'This ticket is no longer active'}), 400
        
        if ticket.status == 'pending':
            return jsonify({'error': 'Please wait for an admin to accept your ticket'}), 400
        
        data = request.get_json()
        
        message = TicketMessage(
            ticket_id=ticket_id,
            sender_id=current_user.id,
            sender_type='user',
            content=data['content'],
            message_type=data.get('messageType', 'text'),
            attachment_url=data.get('attachmentUrl'),
            attachment_name=data.get('attachmentName')
        )
        db.session.add(message)
        
        # 更新工单时间
        ticket.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/user/<int:ticket_id>/close', methods=['POST'])
@login_required
def user_close_ticket(ticket_id):
    """用户关闭工单"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        if ticket.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        ticket.status = 'closed'
        ticket.resolved_at = datetime.utcnow()
        
        # 添加系统消息
        system_msg = TicketMessage(
            ticket_id=ticket_id,
            sender_type='system',
            content='Ticket closed by user.',
            message_type='system'
        )
        db.session.add(system_msg)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Ticket closed successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================================
# 👨‍💼 ADMIN ENDPOINTS - 管理端
# ================================================

@tickets_bp.route('/admin', methods=['GET'])
@login_required
@admin_required
def admin_get_tickets():
    """Admin 获取所有工单"""
    try:
        status = request.args.get('status', 'all')
        category = request.args.get('category', 'all')
        assigned = request.args.get('assigned', 'all')  # all / me / unassigned
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        query = Ticket.query
        
        # 状态过滤
        if status != 'all':
            query = query.filter_by(status=status)
        
        # 分类过滤
        if category != 'all':
            query = query.filter_by(category=category)
        
        # 分配过滤
        if assigned == 'me':
            query = query.filter_by(assigned_admin_id=current_user.id)
        elif assigned == 'unassigned':
            query = query.filter_by(assigned_admin_id=None)
        
        # 检查并更新过期状态
        expired_tickets = Ticket.query.filter(
            Ticket.expires_at < datetime.utcnow(),
            Ticket.status.in_(['pending', 'accepted', 'in_progress'])
        ).all()
        
        for ticket in expired_tickets:
            ticket.status = 'expired'
            # 发送过期通知（如果还没发）
            if not ticket.expiry_notified:
                _send_expiry_notification(ticket)
                ticket.expiry_notified = True
        
        db.session.commit()
        
        # 分页
        tickets = query.order_by(
            Ticket.priority.desc(),
            Ticket.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        # 统计
        stats = {
            'total': Ticket.query.count(),
            'pending': Ticket.query.filter_by(status='pending').count(),
            'inProgress': Ticket.query.filter(Ticket.status.in_(['accepted', 'in_progress'])).count(),
            'resolved': Ticket.query.filter_by(status='resolved').count(),
            'expired': Ticket.query.filter_by(status='expired').count(),
            'myTickets': Ticket.query.filter_by(assigned_admin_id=current_user.id).count()
        }
        
        return jsonify({
            'success': True,
            'tickets': [t.to_preview_dict() for t in tickets.items],
            'total': tickets.total,
            'pages': tickets.pages,
            'currentPage': page,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/admin/<int:ticket_id>', methods=['GET'])
@login_required
@admin_required
def admin_get_ticket_detail(ticket_id):
    """Admin 获取工单详情"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        # 获取消息
        messages = TicketMessage.query.filter_by(ticket_id=ticket_id).order_by(
            TicketMessage.created_at.asc()
        ).all()
        
        # 标记 User 消息为已读
        unread_msgs = TicketMessage.query.filter(
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.sender_type == 'user',
            TicketMessage.is_read == False
        ).all()
        
        for msg in unread_msgs:
            msg.is_read = True
            msg.read_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'ticket': ticket.to_dict(),
            'messages': [m.to_dict() for m in messages]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/admin/<int:ticket_id>/accept', methods=['POST'])
@login_required
@admin_required
def admin_accept_ticket(ticket_id):
    """Admin 接受工单"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        if ticket.status != 'pending':
            return jsonify({'error': 'This ticket has already been processed'}), 400
        
        if ticket.is_expired():
            return jsonify({'error': 'This ticket has expired'}), 400
        
        # 接受工单
        ticket.accept(current_user.id)
        
        # 添加系统消息
        system_msg = TicketMessage(
            ticket_id=ticket_id,
            sender_type='system',
            content=f'{current_user.full_name} has accepted this ticket.',
            message_type='system'
        )
        db.session.add(system_msg)
        
        # 通知用户
        notification = SystemNotification(
            recipient_type='user',
            recipient_id=ticket.user_id,
            title='Your ticket has been accepted',
            content=f'An admin has accepted your ticket: {ticket.subject}',
            notification_type='ticket_accepted',
            related_type='ticket',
            related_id=ticket.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'ticket': ticket.to_dict(),
            'message': 'Ticket accepted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/admin/<int:ticket_id>/message', methods=['POST'])
@login_required
@admin_required
def admin_send_message(ticket_id):
    """Admin 在工单中发送消息"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        # 检查是否是负责人
        if ticket.assigned_admin_id != current_user.id:
            # 允许其他 Admin 协助，但记录
            pass
        
        # 检查工单状态
        if ticket.status in ['expired', 'closed']:
            return jsonify({'error': 'This ticket is no longer active'}), 400
        
        data = request.get_json()
        
        message = TicketMessage(
            ticket_id=ticket_id,
            sender_id=current_user.id,
            sender_type='admin',
            content=data['content'],
            message_type=data.get('messageType', 'text'),
            attachment_url=data.get('attachmentUrl'),
            attachment_name=data.get('attachmentName')
        )
        db.session.add(message)
        
        # 更新工单状态
        if ticket.status == 'accepted':
            ticket.status = 'in_progress'
        
        ticket.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/admin/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@admin_required
def admin_resolve_ticket(ticket_id):
    """Admin 标记工单为已解决"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        if ticket.status in ['resolved', 'closed', 'expired']:
            return jsonify({'error': 'This ticket is already closed'}), 400
        
        ticket.resolve()
        
        # 添加系统消息
        system_msg = TicketMessage(
            ticket_id=ticket_id,
            sender_type='system',
            content='This ticket has been marked as resolved.',
            message_type='system'
        )
        db.session.add(system_msg)
        
        # 通知用户
        notification = SystemNotification(
            recipient_type='user',
            recipient_id=ticket.user_id,
            title='Your ticket has been resolved',
            content=f'Your ticket "{ticket.subject}" has been resolved.',
            notification_type='ticket_resolved',
            related_type='ticket',
            related_id=ticket.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Ticket resolved successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@tickets_bp.route('/admin/<int:ticket_id>/transfer', methods=['POST'])
@login_required
@admin_required
def admin_transfer_ticket(ticket_id):
    """转移工单给其他 Admin"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        data = request.get_json()
        
        new_admin_id = data.get('adminId')
        new_admin = User.query.get(new_admin_id)
        
        if not new_admin or new_admin.role not in ['Administrator', 'Admin', 'super_admin']:
            return jsonify({'error': 'Invalid admin user'}), 400
        
        old_admin_name = ticket.assigned_admin.full_name if ticket.assigned_admin else 'Unassigned'
        ticket.assigned_admin_id = new_admin_id
        
        # 添加系统消息
        system_msg = TicketMessage(
            ticket_id=ticket_id,
            sender_type='system',
            content=f'Ticket transferred from {old_admin_name} to {new_admin.full_name}.',
            message_type='system'
        )
        db.session.add(system_msg)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Ticket transferred to {new_admin.full_name}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ================================================
# 📊 统计 ENDPOINTS
# ================================================

@tickets_bp.route('/admin/stats', methods=['GET'])
@login_required
@admin_required
def get_ticket_stats():
    """获取工单统计"""
    try:
        from datetime import timedelta
        
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        
        stats = {
            'total': Ticket.query.count(),
            'pending': Ticket.query.filter_by(status='pending').count(),
            'accepted': Ticket.query.filter_by(status='accepted').count(),
            'inProgress': Ticket.query.filter_by(status='in_progress').count(),
            'resolved': Ticket.query.filter_by(status='resolved').count(),
            'expired': Ticket.query.filter_by(status='expired').count(),
            'closed': Ticket.query.filter_by(status='closed').count(),
            
            'thisWeek': Ticket.query.filter(Ticket.created_at >= week_ago).count(),
            'thisMonth': Ticket.query.filter(Ticket.created_at >= month_ago).count(),
            
            'byCategory': {
                'general': Ticket.query.filter_by(category='general').count(),
                'billing': Ticket.query.filter_by(category='billing').count(),
                'technical': Ticket.query.filter_by(category='technical').count(),
                'feedback': Ticket.query.filter_by(category='feedback').count(),
            },
            
            'byPriority': {
                'urgent': Ticket.query.filter_by(priority='urgent').count(),
                'high': Ticket.query.filter_by(priority='high').count(),
                'normal': Ticket.query.filter_by(priority='normal').count(),
                'low': Ticket.query.filter_by(priority='low').count(),
            },
            
            # 平均响应时间（已接受的工单）
            'avgResponseTime': _calculate_avg_response_time()
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# 🔧 辅助函数
# ================================================

def _send_expiry_notification(ticket):
    """发送工单过期通知"""
    # 通知用户
    notification = SystemNotification(
        recipient_type='user',
        recipient_id=ticket.user_id,
        title='Your ticket has expired',
        content=f'Your ticket "{ticket.subject}" has expired without being resolved. Please create a new ticket if you still need assistance.',
        notification_type='ticket_expired',
        related_type='ticket',
        related_id=ticket.id
    )
    db.session.add(notification)
    
    # TODO: 发送邮件
    # send_ticket_expired_email(ticket)


def _calculate_avg_response_time():
    """计算平均响应时间（秒）"""
    try:
        accepted_tickets = Ticket.query.filter(
            Ticket.accepted_at.isnot(None)
        ).all()
        
        if not accepted_tickets:
            return 0
        
        total_seconds = sum(
            (t.accepted_at - t.created_at).total_seconds()
            for t in accepted_tickets
        )
        
        return int(total_seconds / len(accepted_tickets))
    except:
        return 0
