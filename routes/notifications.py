# routes/notifications.py
# 通知系统完整路由 - 包含 /api/announcements 别名路由

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, Notification, NotificationTab, UserNotificationRead, User
from datetime import datetime
from functools import wraps
from utils import send_system_email, generate_admin_notification_email_html

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

# 🔥 新增：Announcements Blueprint（别名路由）
announcements_bp = Blueprint('announcements', __name__, url_prefix='/api/announcements')


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


# ================================================
# 👤 USER ENDPOINTS - 用户端接口
# ================================================

@notifications_bp.route('/user', methods=['GET'])
@login_required
def get_user_notifications():
    """
    获取当前用户的所有通知
    包括：个人通知 + 群发通知
    """
    try:
        user_id = current_user.id
        
        # 1. 获取个人通知
        personal_notifs = Notification.query.filter_by(
            user_id=user_id
        ).order_by(Notification.created_at.desc()).limit(50).all()
        
        # 2. 获取群发通知（user_id 为 null 且 is_broadcast=True）
        broadcast_notifs = Notification.query.filter(
            Notification.is_broadcast == True,
            Notification.user_id == None
        ).order_by(Notification.created_at.desc()).limit(50).all()
        
        # 3. 获取用户已读的群发通知ID
        read_broadcast_ids = set(
            r.notification_id for r in 
            UserNotificationRead.query.filter_by(user_id=user_id).all()
        )
        
        # 4. 合并通知
        result = []
        
        for notif in personal_notifs:
            result.append(notif.to_dict())
        
        for notif in broadcast_notifs:
            notif_dict = notif.to_dict()
            # 检查群发通知是否已读
            notif_dict['unread'] = notif.id not in read_broadcast_ids
            result.append(notif_dict)
        
        # 5. 按时间排序
        result.sort(key=lambda x: x['createdAt'] or '', reverse=True)
        
        # 6. 统计未读数
        unread_count = sum(1 for n in result if n['unread'])
        
        return jsonify({
            'success': True,
            'notifications': result[:30],  # 最多返回30条
            'unreadCount': unread_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/user/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    """标记通知为已读"""
    try:
        notif = Notification.query.get_or_404(notif_id)
        
        if notif.is_broadcast:
            # 群发通知：记录到 UserNotificationRead
            existing = UserNotificationRead.query.filter_by(
                user_id=current_user.id,
                notification_id=notif_id
            ).first()
            
            if not existing:
                read_record = UserNotificationRead(
                    user_id=current_user.id,
                    notification_id=notif_id
                )
                db.session.add(read_record)
                db.session.commit()
        else:
            # 个人通知：直接更新
            if notif.user_id == current_user.id:
                notif.is_read = True
                notif.read_at = datetime.utcnow()
                db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/user/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """标记所有通知为已读"""
    try:
        user_id = current_user.id
        
        # 1. 标记个人通知
        Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).update({'is_read': True, 'read_at': datetime.utcnow()})
        
        # 2. 标记群发通知
        broadcast_notifs = Notification.query.filter(
            Notification.is_broadcast == True,
            Notification.user_id == None
        ).all()
        
        for notif in broadcast_notifs:
            existing = UserNotificationRead.query.filter_by(
                user_id=user_id,
                notification_id=notif.id
            ).first()
            
            if not existing:
                read_record = UserNotificationRead(
                    user_id=user_id,
                    notification_id=notif.id
                )
                db.session.add(read_record)
        
        db.session.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/user/<int:notif_id>', methods=['DELETE'])
@login_required
def delete_user_notification(notif_id):
    """删除用户通知（仅限个人通知）"""
    try:
        notif = Notification.query.get_or_404(notif_id)
        
        if notif.user_id != current_user.id:
            return jsonify({'error': 'Cannot delete this notification'}), 403
        
        db.session.delete(notif)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# 📄 TAB ENDPOINTS - 公告详情页
# ================================================

@notifications_bp.route('/tabs/<int:tab_id>', methods=['GET'])
@login_required
def get_notification_tab(tab_id):
    """获取公告Tab详情（用户查看）"""
    try:
        tab = NotificationTab.query.get_or_404(tab_id)
        
        # 检查是否有效
        if not tab.is_active() and current_user.role not in ['Administrator', 'Admin']:
            return jsonify({'error': 'This announcement is not available'}), 404
        
        # 检查受众
        if tab.target_audience != 'all':
            if tab.target_audience == 'premium' and not current_user.is_premium_active:
                return jsonify({'error': 'This announcement is for premium users only'}), 403
            elif tab.target_audience == 'free' and current_user.is_premium_active:
                return jsonify({'error': 'This announcement is for free users only'}), 403
        
        # 增加浏览量
        tab.views += 1
        db.session.commit()
        
        return jsonify({
            'success': True,
            'tab': tab.to_dict()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/tabs/<int:tab_id>/cta-click', methods=['POST'])
@login_required
def track_cta_click(tab_id):
    """记录CTA点击"""
    try:
        tab = NotificationTab.query.get_or_404(tab_id)
        tab.cta_clicks += 1
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# 🔥 ANNOUNCEMENTS ENDPOINTS - 公告别名路由
# 用于前端 /api/announcements 调用
# ================================================

@announcements_bp.route('', methods=['GET'])
@login_required
def get_announcements_list():
    """
    获取公告列表
    GET /api/announcements
    """
    try:
        # 获取所有活跃的公告Tab
        tabs = NotificationTab.query.filter_by(status='active').order_by(
            NotificationTab.priority.desc(),
            NotificationTab.created_at.desc()
        ).all()
        
        # 过滤：只返回当前有效的公告
        active_tabs = [t for t in tabs if t.is_active()]
        
        # 过滤：根据用户类型
        filtered_tabs = []
        for tab in active_tabs:
            if tab.target_audience == 'all':
                filtered_tabs.append(tab)
            elif tab.target_audience == 'premium' and current_user.is_premium_active:
                filtered_tabs.append(tab)
            elif tab.target_audience == 'free' and not current_user.is_premium_active:
                filtered_tabs.append(tab)
        
        announcements = []
        for tab in filtered_tabs:
            announcements.append({
                'id': tab.id,
                'title': tab.title,
                'subtitle': tab.subtitle,
                'content': tab.content[:200] + '...' if len(tab.content) > 200 else tab.content,
                'coverImage': tab.cover_image,
                'category': tab.category,
                'priority': tab.priority,
                'views': tab.views,
                'createdAt': tab.created_at.isoformat() if tab.created_at else None
            })
        
        return jsonify({
            'success': True,
            'announcements': announcements
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@announcements_bp.route('/<int:announcement_id>', methods=['GET'])
@login_required
def get_announcement_detail(announcement_id):
    """
    获取公告详情
    GET /api/announcements/:id
    """
    try:
        tab = NotificationTab.query.get_or_404(announcement_id)
        
        # 检查是否有效
        if not tab.is_active() and current_user.role not in ['Administrator', 'Admin', 'super_admin']:
            return jsonify({'error': 'This announcement is not available'}), 404
        
        # 检查受众权限
        if tab.target_audience != 'all':
            if tab.target_audience == 'premium' and not current_user.is_premium_active:
                return jsonify({'error': 'This announcement is for premium users only'}), 403
            elif tab.target_audience == 'free' and current_user.is_premium_active:
                return jsonify({'error': 'This announcement is for free users only'}), 403
        
        # 增加浏览量
        tab.views += 1
        db.session.commit()
        
        announcement = {
            'id': tab.id,
            'title': tab.title,
            'subtitle': tab.subtitle,
            'content': tab.content,
            'contentType': tab.content_type,
            'coverImage': tab.cover_image,
            'bannerImage': tab.banner_image,
            'ctaText': tab.cta_text,
            'ctaLink': tab.cta_link,
            'ctaStyle': tab.cta_style,
            'category': tab.category,
            'priority': tab.priority,
            'views': tab.views,
            'createdAt': tab.created_at.isoformat() if tab.created_at else None
        }
        
        return jsonify({
            'success': True,
            'announcement': announcement
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ================================================
# 👨‍💼 ADMIN ENDPOINTS - 管理端接口
# ================================================

@notifications_bp.route('/admin/tabs', methods=['GET'])
@login_required
@admin_required
def admin_get_tabs():
    """获取所有公告Tab列表"""
    try:
        status = request.args.get('status', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        query = NotificationTab.query
        
        if status != 'all':
            query = query.filter_by(status=status)
        
        tabs = query.order_by(NotificationTab.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'tabs': [t.to_preview_dict() for t in tabs.items],
            'total': tabs.total,
            'pages': tabs.pages,
            'currentPage': page
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/tabs', methods=['POST'])
@login_required
@admin_required
def admin_create_tab():
    """创建新的公告Tab"""
    try:
        data = request.get_json()
        
        tab = NotificationTab(
            title=data['title'],
            subtitle=data.get('subtitle'),
            content=data['content'],
            content_type=data.get('contentType', 'markdown'),
            cover_image=data.get('coverImage'),
            banner_image=data.get('bannerImage'),
            cta_text=data.get('ctaText'),
            cta_link=data.get('ctaLink'),
            cta_style=data.get('ctaStyle', 'primary'),
            target_audience=data.get('targetAudience', 'all'),
            category=data.get('category', 'announcement'),
            priority=data.get('priority', 0),
            status=data.get('status', 'draft'),
            start_at=datetime.fromisoformat(data['startAt']) if data.get('startAt') else None,
            end_at=datetime.fromisoformat(data['endAt']) if data.get('endAt') else None,
            created_by=current_user.id
        )
        
        db.session.add(tab)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'tab': tab.to_dict(),
            'message': 'Tab created successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/tabs/<int:tab_id>', methods=['GET'])
@login_required
@admin_required
def admin_get_tab(tab_id):
    """获取单个Tab详情"""
    try:
        tab = NotificationTab.query.get_or_404(tab_id)
        return jsonify({
            'success': True,
            'tab': tab.to_dict()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/tabs/<int:tab_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_tab(tab_id):
    """更新公告Tab"""
    try:
        tab = NotificationTab.query.get_or_404(tab_id)
        data = request.get_json()
        
        # 更新字段
        for field in ['title', 'subtitle', 'content', 'content_type', 
                      'cover_image', 'banner_image', 'cta_text', 'cta_link',
                      'cta_style', 'target_audience', 'category', 'priority', 'status']:
            camel_field = ''.join(word.capitalize() if i else word 
                                  for i, word in enumerate(field.split('_')))
            if camel_field in data:
                setattr(tab, field, data[camel_field])
        
        if 'startAt' in data:
            tab.start_at = datetime.fromisoformat(data['startAt']) if data['startAt'] else None
        if 'endAt' in data:
            tab.end_at = datetime.fromisoformat(data['endAt']) if data['endAt'] else None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'tab': tab.to_dict(),
            'message': 'Tab updated successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/tabs/<int:tab_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_tab(tab_id):
    """删除公告Tab"""
    try:
        tab = NotificationTab.query.get_or_404(tab_id)
        db.session.delete(tab)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Tab deleted successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/send', methods=['POST'])
@login_required
@admin_required
def admin_send_notification():
    """
    发送通知
    支持：单发、群发、绑定Tab
    
    🆕 NEW: Optional email sending (respects user email preferences)
    """
    try:
        data = request.get_json()
        
        send_type = data.get('sendType', 'broadcast')  # broadcast / single / targeted
        title = data.get('title')
        text = data.get('text')
        notif_type = data.get('type', 'info')
        icon = data.get('icon')
        tab_id = data.get('tabId')
        target_user_ids = data.get('targetUserIds', [])
        target_audience = data.get('targetAudience', 'all')  # all / premium / free
        send_email = data.get('sendEmail', False)  # 🆕 NEW: Optional email flag
        
        notifications_created = []
        emails_sent = 0
        emails_skipped = 0
        
        if send_type == 'broadcast':
            # 群发通知
            notif = Notification(
                user_id=None,
                title=title,
                text=text,
                type=notif_type,
                icon=icon,
                tab_id=tab_id,
                is_broadcast=True,
                sent_by=current_user.id
            )
            db.session.add(notif)
            notifications_created.append(notif)
            
            # 🆕 Send emails if requested (respects user email preferences)
            if send_email:
                # For broadcast, send to all active users who have email notifications enabled
                users_to_email = User.query.filter(
                    User.status == 'active',
                    User.email.isnot(None)
                ).all()
                
                for user in users_to_email:
                    # Check user email preference (default: enabled)
                    # 🆕 Now reads from database field
                    user_allows_email = user.email_notifications if user.email_notifications is not None else True
                    
                    if user_allows_email:
                        try:
                            subject, html_content, text_content = generate_admin_notification_email_html(
                                user_name=user.full_name or 'User',
                                title=title or '',
                                message=text,
                                notification_type=notif_type
                            )
                            if send_system_email(user.email, subject, html_content, text_content):
                                emails_sent += 1
                            else:
                                emails_skipped += 1
                        except Exception as email_error:
                            print(f"⚠️ Email error for {user.email}: {str(email_error)}")
                            emails_skipped += 1
                    else:
                        emails_skipped += 1
                
        elif send_type == 'single':
            # 单发给指定用户
            for user_id in target_user_ids:
                user = User.query.get(user_id)
                if not user:
                    continue
                    
                notif = Notification(
                    user_id=user_id,
                    title=title,
                    text=text,
                    type=notif_type,
                    icon=icon,
                    tab_id=tab_id,
                    is_broadcast=False,
                    sent_by=current_user.id
                )
                db.session.add(notif)
                notifications_created.append(notif)
                
                # 🆕 Send email if requested (respects user email preference)
                if send_email and user.email:
                    user_allows_email = user.email_notifications if user.email_notifications is not None else True
                    
                    if user_allows_email:
                        try:
                            subject, html_content, text_content = generate_admin_notification_email_html(
                                user_name=user.full_name or 'User',
                                title=title or '',
                                message=text,
                                notification_type=notif_type
                            )
                            if send_system_email(user.email, subject, html_content, text_content):
                                emails_sent += 1
                            else:
                                emails_skipped += 1
                        except Exception as email_error:
                            print(f"⚠️ Email error for {user.email}: {str(email_error)}")
                            emails_skipped += 1
                    else:
                        emails_skipped += 1
                
        elif send_type == 'targeted':
            # 按条件群发（premium/free）
            users = User.query.filter(User.status == 'active').all()
            
            if target_audience not in ('premium', 'free'):
                users = []
            if target_audience == 'premium':
                users = [u for u in users if u.is_premium_active]
            elif target_audience == 'free':
                users = [u for u in users if not u.is_premium_active]
            
            for user in users:
                notif = Notification(
                    user_id=user.id,
                    title=title,
                    text=text,
                    type=notif_type,
                    icon=icon,
                    tab_id=tab_id,
                    is_broadcast=False,
                    sent_by=current_user.id
                )
                db.session.add(notif)
                notifications_created.append(notif)
                
                # 🆕 Send email if requested (respects user email preference)
                if send_email and user.email:
                    user_allows_email = user.email_notifications if user.email_notifications is not None else True
                    
                    if user_allows_email:
                        try:
                            subject, html_content, text_content = generate_admin_notification_email_html(
                                user_name=user.full_name or 'User',
                                title=title or '',
                                message=text,
                                notification_type=notif_type
                            )
                            if send_system_email(user.email, subject, html_content, text_content):
                                emails_sent += 1
                            else:
                                emails_skipped += 1
                        except Exception as email_error:
                            print(f"⚠️ Email error for {user.email}: {str(email_error)}")
                            emails_skipped += 1
                    else:
                        emails_skipped += 1
        
        db.session.commit()
        
        # Build response message
        message = f'Notification sent to {len(notifications_created)} recipient(s)'
        if send_email:
            message += f'. Emails: {emails_sent} sent, {emails_skipped} skipped (opted out or failed)'
        
        return jsonify({
            'success': True,
            'message': message,
            'count': len(notifications_created),
            'emailsSent': emails_sent if send_email else 0,
            'emailsSkipped': emails_skipped if send_email else 0
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/list', methods=['GET'])
@login_required
@admin_required
def admin_list_notifications():
    """获取所有发送过的通知"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # 只获取群发和管理员发送的通知
        notifs = Notification.query.filter(
            (Notification.is_broadcast == True) | (Notification.sent_by != None)
        ).order_by(Notification.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'notifications': [n.to_dict() for n in notifs.items],
            'total': notifs.total,
            'pages': notifs.pages,
            'currentPage': page
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notifications_bp.route('/admin/stats', methods=['GET'])
@login_required
@admin_required
def admin_notification_stats():
    """获取通知统计"""
    try:
        total_tabs = NotificationTab.query.count()
        active_tabs = NotificationTab.query.filter_by(status='active').count()
        total_notifications = Notification.query.filter(
            (Notification.is_broadcast == True) | (Notification.sent_by != None)
        ).count()
        
        # 最近7天通知数
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_notifs = Notification.query.filter(
            Notification.created_at >= week_ago
        ).count()
        
        # Tab浏览统计
        top_tabs = NotificationTab.query.order_by(
            NotificationTab.views.desc()
        ).limit(5).all()
        
        return jsonify({
            'success': True,
            'stats': {
                'totalTabs': total_tabs,
                'activeTabs': active_tabs,
                'totalNotifications': total_notifications,
                'recentNotifications': recent_notifs,
                'topTabs': [
                    {'id': t.id, 'title': t.title, 'views': t.views}
                    for t in top_tabs
                ]
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500