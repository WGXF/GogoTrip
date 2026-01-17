# models_update.py - 通知系统扩展
# 将以下内容添加到你的 models.py 文件中

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()

# ================================================
# 🔔 NotificationTab - 公告内容页面（核心新增）
# ================================================
class NotificationTab(db.Model):
    """
    公告内容Tab - 类似 B站/Steam 的公告详情页
    Admin 创建的完整公告内容，Notification 只是入口
    """
    __tablename__ = 'notification_tabs'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 基础信息
    title = db.Column(db.String(255), nullable=False)          # Tab标题
    subtitle = db.Column(db.String(255))                        # 副标题
    content = db.Column(db.Text, nullable=False)                # 正文内容 (Markdown/HTML)
    content_type = db.Column(db.String(20), default='markdown') # markdown / html / plain
    
    # 🖼️ 媒体
    cover_image = db.Column(db.Text)                            # 封面图
    banner_image = db.Column(db.Text)                           # Banner图
    
    # 🔗 行为按钮 (CTA)
    cta_text = db.Column(db.String(50))                         # "立即查看" / "升级会员"
    cta_link = db.Column(db.String(255))                        # /billing / /trips
    cta_style = db.Column(db.String(20), default='primary')     # primary / secondary / danger
    
    # 🎯 目标受众
    target_audience = db.Column(db.String(50), default='all')   # all / premium / free / new_users
    
    # 📊 分类与优先级
    category = db.Column(db.String(50), default='announcement') # announcement / promotion / update / alert
    priority = db.Column(db.Integer, default=0)                 # 0=normal, 1=important, 2=urgent
    
    # ⏰ 生命周期
    status = db.Column(db.String(20), default='draft')          # draft / active / scheduled / archived
    start_at = db.Column(db.DateTime)                           # 定时上线
    end_at = db.Column(db.DateTime)                             # 自动下线
    
    # 📈 统计
    views = db.Column(db.Integer, default=0)                    # 浏览次数
    cta_clicks = db.Column(db.Integer, default=0)               # CTA点击次数
    
    # 🔒 元数据
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联
    notifications = db.relationship('Notification', backref='tab', lazy=True)
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def is_active(self):
        """检查Tab是否在有效期内"""
        now = datetime.utcnow()
        if self.status != 'active':
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'subtitle': self.subtitle,
            'content': self.content,
            'contentType': self.content_type,
            'coverImage': self.cover_image,
            'bannerImage': self.banner_image,
            'ctaText': self.cta_text,
            'ctaLink': self.cta_link,
            'ctaStyle': self.cta_style,
            'targetAudience': self.target_audience,
            'category': self.category,
            'priority': self.priority,
            'status': self.status,
            'startAt': self.start_at.isoformat() if self.start_at else None,
            'endAt': self.end_at.isoformat() if self.end_at else None,
            'views': self.views,
            'ctaClicks': self.cta_clicks,
            'createdBy': self.created_by,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'updatedAt': self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None,
            'isActive': self.is_active(),
            'creatorName': self.creator.full_name if self.creator else None
        }
    
    def to_preview_dict(self):
        """列表预览用的精简版"""
        return {
            'id': self.id,
            'title': self.title,
            'subtitle': self.subtitle,
            'coverImage': self.cover_image,
            'category': self.category,
            'status': self.status,
            'views': self.views,
            'createdAt': self.created_at.strftime("%Y-%m-%d") if self.created_at else None,
            'isActive': self.is_active()
        }


# ================================================
# 🔔 Notification - 更新版（添加Tab关联）
# ================================================
class Notification(db.Model):
    """
    通知表 - 用户看到的通知入口
    可以关联到 NotificationTab 查看详情
    """
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 关联用户 (null = 群发)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    
    # 📝 通知内容
    title = db.Column(db.String(100))                           # 通知标题 (新增)
    text = db.Column(db.String(255), nullable=False)            # 通知摘要
    
    # 🔗 关联Tab (核心新增)
    tab_id = db.Column(db.Integer, db.ForeignKey('notification_tabs.id', ondelete='SET NULL'), nullable=True)
    
    # 🎨 类型与样式
    type = db.Column(db.String(20), default='info')             # info / success / warning / alert
    icon = db.Column(db.String(50))                             # lucide icon name
    
    # 📊 状态
    is_read = db.Column(db.Boolean, default=False)
    is_broadcast = db.Column(db.Boolean, default=False)         # 是否群发
    
    # ⏰ 时间
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)                            # 阅读时间
    
    # 🔒 发送者
    sent_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "text": self.text,
            "type": self.type,
            "icon": self.icon,
            "unread": not self.is_read,
            "tabId": self.tab_id,
            "hasTab": self.tab_id is not None,
            "actionUrl": f"/announcements/{self.tab_id}" if self.tab_id else None,
            "time": self._format_time(),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "isBroadcast": self.is_broadcast
        }
    
    def _format_time(self):
        """智能时间格式化"""
        if not self.created_at:
            return "Unknown"
        
        now = datetime.utcnow()
        diff = now - self.created_at
        
        if diff.days == 0:
            if diff.seconds < 60:
                return "Just now"
            elif diff.seconds < 3600:
                return f"{diff.seconds // 60} min ago"
            else:
                return f"{diff.seconds // 3600} hours ago"
        elif diff.days == 1:
            return "Yesterday"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return self.created_at.strftime("%b %d")


# ================================================
# 🔔 UserNotificationRead - 群发通知的已读状态追踪
# ================================================
class UserNotificationRead(db.Model):
    """
    追踪群发通知的用户已读状态
    因为群发通知 user_id 为 null，需要单独记录
    """
    __tablename__ = 'user_notification_reads'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id', ondelete='CASCADE'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'notification_id', name='unique_user_notification'),
    )


# ================================================
# 📋 记得在 main_app.py 中注册到 Flask-Admin
# ================================================
"""
在 main_app.py 中添加:

from models import NotificationTab, UserNotificationRead

admin.add_view(ModelView(NotificationTab, db.session))
admin.add_view(ModelView(UserNotificationRead, db.session))
"""
