from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_login import UserMixin

# Initialize db object
db = SQLAlchemy()

# ----------------------
# 1. User Table (Users)
# ----------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    google_id = db.Column(db.String(255), unique=True)
    full_name = db.Column(db.String(100))
    avatar_url = db.Column(db.Text)
    is_email_verified = db.Column(db.Boolean, default=False)
    
    # Google Calendar Token storage
    google_access_token = db.Column(db.Text)
    google_refresh_token = db.Column(db.Text)
    google_token_expiry = db.Column(db.DateTime)
    
    stripe_customer_id = db.Column(db.String(255))

    
    role = db.Column(db.String(50), default='User', nullable=False) 
    last_login = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='pending_verification', nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    
    # 🆕 User Preferences
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)  # Opt-in for admin notification emails
    preferred_language = db.Column(db.String(10), default='en', nullable=False)  # UI language: en, zh, ms
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    trips = db.relationship('Trip', backref='user', lazy=True, cascade="all, delete-orphan")
    calendar_events = db.relationship('CalendarEvent', backref='user', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='recipient', lazy=True, cascade="all, delete-orphan", foreign_keys='Notification.user_id')
    sent_notifications = db.relationship('Notification', backref='sender', lazy=True, foreign_keys='Notification.sent_by', passive_deletes=True)
    subscriptions = db.relationship('Subscription', backref='user', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='user', lazy=True, cascade="all, delete-orphan")
    scheduler_items = db.relationship('SchedulerItem', backref='user', lazy=True, cascade="all, delete-orphan")
    system_logs = db.relationship('SystemLog', backref='admin', lazy=True, 
                                   foreign_keys='SystemLog.admin_id',
                                   passive_deletes=True)

    # =========================================================================
    # 🎯 PREMIUM STATUS - Single Source of Truth (SUBSCRIPTION TABLE ONLY)
    # =========================================================================
    
    @property
    def is_premium_active(self) -> bool:
        """
        ✅ THE ONLY WAY TO CHECK PREMIUM STATUS
        
        User is Premium if they have at least one Subscription where:
        - status = 'active'
        - start_date <= now
        - end_date > now OR end_date is NULL (lifetime)
        
        ❌ NO LONGER checks user.is_premium flag
        ❌ NO LONGER checks user.subscription_end_date
        """
        now = datetime.utcnow()
        for sub in self.subscriptions:
            if (sub.status == 'active' and 
                sub.start_date and sub.start_date <= now and
                (sub.end_date is None or sub.end_date > now)):
                return True
        return False
    
    def get_active_subscription(self):
        """
        Get the current active subscription (if any).
        Returns the subscription with the latest end_date, or lifetime if exists.
        """
        now = datetime.utcnow()
        active_subs = [
            sub for sub in self.subscriptions 
            if (sub.status == 'active' and 
                sub.start_date and sub.start_date <= now and
                (sub.end_date is None or sub.end_date > now))
        ]
        
        if not active_subs:
            return None
        
        # Prioritize lifetime (end_date is None)
        lifetime_subs = [s for s in active_subs if s.end_date is None]
        if lifetime_subs:
            return lifetime_subs[0]
        
        # Return the one with the latest end_date
        return max(active_subs, key=lambda s: s.end_date)
    
    def get_subscription_end_date(self):
        """
        Get the effective subscription end date from active subscriptions.
        Returns None if user has lifetime or no active subscription.
        """
        active_sub = self.get_active_subscription()
        if active_sub:
            return active_sub.end_date  # None for lifetime
        return None
    
    def get_remaining_premium_days(self) -> int:
        """
        Get remaining days of premium.
        Returns -1 for lifetime, 0 for no subscription.
        """
        active_sub = self.get_active_subscription()
        if not active_sub:
            return 0
        if active_sub.end_date is None:
            return -1  # Lifetime
        
        remaining = (active_sub.end_date - datetime.utcnow()).days
        return max(0, remaining)
    
    def get_current_plan_level(self) -> int:
        """
        Get the plan level of current active subscription.
        Returns 0 if no active subscription.
        """
        active_sub = self.get_active_subscription()
        if active_sub and active_sub.plan:
            return active_sub.plan.level
        return 0

    def to_dict(self):
        """Convert user to dictionary for API responses"""
        active_sub = self.get_active_subscription()
        end_date = self.get_subscription_end_date()
        
        # Determine auth provider
        if self.google_id and not self.password_hash:
            auth_provider = 'google'
        elif self.password_hash:
            auth_provider = 'email'
        else:
            auth_provider = 'unknown'
        
        return {
            "id": self.id,
            "email": self.email,
            "name": self.full_name or "User",
            "role": self.role,
            "status": self.status,
            "createdAt": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            "lastLogin": self.last_login.strftime("%Y-%m-%d %H:%M") if self.last_login else "Never",
            "avatarUrl": self.avatar_url or "",
            "isVerified": self.is_email_verified,
            # ✅ Uses Subscription table as single source of truth
            "isPremium": self.is_premium_active,
            "subscriptionEndDate": end_date.strftime("%Y-%m-%d") if end_date else None,
            "isLifetime": active_sub.end_date is None if active_sub else False,
            "remainingDays": self.get_remaining_premium_days(),
            "hasGoogleCalendar": bool(self.google_refresh_token),
            # 🆕 Google Account Linking
            "hasGoogleLinked": bool(self.google_id),  # True if Google account is linked
            "authProvider": auth_provider,  # 'google', 'email', or 'unknown'
            # 🆕 User Preferences
            "emailNotifications": self.email_notifications,
            "preferredLanguage": self.preferred_language or 'en'
        }
    
    def to_admin_dict(self):
        """Extended dictionary for admin views"""
        base_dict = self.to_dict()
        active_sub = self.get_active_subscription()
        
        base_dict.update({
            "updatedAt": self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None,
            "deletedAt": self.deleted_at.strftime("%Y-%m-%d %H:%M") if self.deleted_at else None,
            "hasPassword": bool(self.password_hash),
            "hasGoogleId": bool(self.google_id),
            "stripeCustomerId": self.stripe_customer_id,
            "relatedData": self.get_related_data_summary(),
            "currentPlanLevel": self.get_current_plan_level(),
            "currentPlanName": active_sub.plan.name if active_sub and active_sub.plan else None
        })
        return base_dict
    
    def get_related_data_summary(self):
        """Get summary of all related data"""
        return {
            "trips": len(self.trips) if self.trips else 0,
            "calendarEvents": len(self.calendar_events) if self.calendar_events else 0,
            "subscriptions": len(self.subscriptions) if self.subscriptions else 0,
            "notifications": len(self.notifications) if self.notifications else 0,
            "expenses": len(self.expenses) if self.expenses else 0,
            "schedulerItems": len(self.scheduler_items) if self.scheduler_items else 0,
            "hasActiveSubscription": self.is_premium_active
        }
    
    def can_login(self):
        """Only active status accounts can login"""
        return self.status == 'active' and self.is_email_verified
    
    def is_pending_verification(self):
        """Check if account is pending verification"""
        return self.status == 'pending_verification' and not self.is_email_verified
    
    def activate(self):
        """Activate account after email verification"""
        self.is_email_verified = True
        self.status = 'active'
        self.updated_at = datetime.utcnow()
    
    def soft_delete(self):
        """Soft delete user account"""
        self.status = 'deleted'
        self.deleted_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.google_access_token = None
        self.google_refresh_token = None
        self.google_token_expiry = None
    
    def hard_delete(self):
        """Prepare for hard delete"""
        for log in self.system_logs:
            log.admin_id = None
        
    def suspend(self):
        """Suspend user account"""
        self.status = 'suspended'
        self.updated_at = datetime.utcnow()
    
    def reactivate(self):
        """Reactivate a suspended or deleted account"""
        self.status = 'active'
        self.deleted_at = None
        self.updated_at = datetime.utcnow()


# =============================================================================
# SubscriptionPlan - 订阅计划 (UPDATED with Level)
# =============================================================================
class SubscriptionPlan(db.Model):
    """
    订阅计划 - Admin 可管理
    支持上架/下架，不影响已购买用户
    
    🆕 Added `level` field for upgrade/downgrade logic:
    - level 1 = basic/free
    - level 2 = monthly
    - level 3 = yearly
    - level 4 = pro
    - level 5 = lifetime/admin_grant
    """
    __tablename__ = 'subscription_plans'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 基本信息
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    # 🆕 Plan Level for upgrade/downgrade comparison
    level = db.Column(db.Integer, default=1, nullable=False)
    
    # 价格
    price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='MYR')
    
    # 时长
    duration_days = db.Column(db.Integer, nullable=True)  # null = lifetime
    duration_type = db.Column(db.String(20), default='days')
    
    # 状态
    status = db.Column(db.String(20), default='active')
    is_featured = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    
    # 时间
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'level': self.level,
            'price': self.price,
            'currency': self.currency,
            'durationDays': self.duration_days,
            'durationType': self.duration_type,
            'status': self.status,
            'isFeatured': self.is_featured,
            'sortOrder': self.sort_order,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'isLifetime': self.duration_days is None
        }


# =============================================================================
# Voucher - 优惠券/激活码
# =============================================================================
class Voucher(db.Model):
    """
    优惠券/激活码
    支持两种类型：
    - discount: 折扣码 (百分比或固定金额)
    - activation: 激活码 (直接激活会员，累加时间)
    """
    __tablename__ = 'vouchers'
    
    id = db.Column(db.Integer, primary_key=True)
    
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100))
    description = db.Column(db.Text)
    
    voucher_type = db.Column(db.String(20), nullable=False)  # discount | activation
    
    # Discount config
    discount_type = db.Column(db.String(20))  # percentage | fixed
    discount_value = db.Column(db.Float)
    min_amount = db.Column(db.Float, default=0)
    max_discount = db.Column(db.Float)
    
    # Activation config
    activation_plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plans.id'))
    activation_days = db.Column(db.Integer)  # null = lifetime
    
    # Usage limits
    max_uses = db.Column(db.Integer, default=1)
    current_uses = db.Column(db.Integer, default=0)
    max_uses_per_user = db.Column(db.Integer, default=1)
    
    # Applicable scope
    applicable_plans = db.Column(db.JSON, default=list)
    
    # Validity
    valid_from = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime)
    
    # Status
    status = db.Column(db.String(20), default='active')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    activation_plan = db.relationship('SubscriptionPlan', foreign_keys=[activation_plan_id])
    
    def is_valid(self):
        """Check if voucher is valid"""
        if self.status != 'active':
            return False
        if self.current_uses >= self.max_uses:
            return False
        
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
            
        return True
    
    def can_use_by_user(self, user_id):
        """Check if user can use this voucher"""
        if not self.is_valid():
            return False, "Voucher is not valid or has expired"
        
        user_uses = VoucherUsage.query.filter_by(
            voucher_id=self.id, 
            user_id=user_id
        ).count()
        
        if user_uses >= self.max_uses_per_user:
            return False, "You have reached the maximum usage limit for this voucher"
        
        return True, "OK"
    
    def calculate_discount(self, original_amount):
        """Calculate discount amount"""
        if self.voucher_type != 'discount':
            return 0
        
        if original_amount < self.min_amount:
            return 0
        
        if self.discount_type == 'percentage':
            discount = original_amount * (self.discount_value / 100)
        else:
            discount = self.discount_value
        
        if self.max_discount:
            discount = min(discount, self.max_discount)
        
        return round(discount, 2)
    
    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'voucherType': self.voucher_type,
            'discountType': self.discount_type,
            'discountValue': self.discount_value,
            'minAmount': self.min_amount,
            'maxDiscount': self.max_discount,
            'activationDays': self.activation_days,
            'activationPlanId': self.activation_plan_id,
            'maxUses': self.max_uses,
            'currentUses': self.current_uses,
            'maxUsesPerUser': self.max_uses_per_user,
            'applicablePlans': self.applicable_plans,
            'validFrom': self.valid_from.strftime("%Y-%m-%d %H:%M") if self.valid_from else None,
            'validUntil': self.valid_until.strftime("%Y-%m-%d %H:%M") if self.valid_until else None,
            'status': self.status,
            'isValid': self.is_valid(),
            'remainingUses': max(0, self.max_uses - self.current_uses),
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


# =============================================================================
# VoucherUsage - Voucher 使用记录
# =============================================================================
class VoucherUsage(db.Model):
    __tablename__ = 'voucher_usages'
    
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.id', ondelete='SET NULL'))
    
    usage_type = db.Column(db.String(20))
    discount_amount = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    voucher = db.relationship('Voucher', backref='usages')
    user = db.relationship('User', backref='voucher_usages')
    subscription = db.relationship('Subscription', backref='voucher_usage')


# =============================================================================
# Subscription - 订阅记录 (THE SINGLE SOURCE OF TRUTH)
# =============================================================================
class Subscription(db.Model):
    """
    订阅/订单记录
    
    ✅ THIS IS THE SINGLE SOURCE OF TRUTH FOR PREMIUM STATUS
    
    Premium determination:
    - status = 'active'
    - start_date <= now
    - end_date > now OR end_date is NULL (lifetime)
    """
    __tablename__ = 'subscriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    order_reference = db.Column(db.String(100), unique=True, nullable=False)
    bill_code = db.Column(db.String(100))
    
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plans.id'), nullable=True)
    plan_type = db.Column(db.String(20), nullable=False)
    
    amount = db.Column(db.Float, nullable=False)
    original_amount = db.Column(db.Float, nullable=True)
    discount_amount = db.Column(db.Float, default=0)
    
    # Status: pending | active | paid | cancelled | expired | failed | refunded
    # 🆕 Changed: 'paid' subscriptions should also be 'active' for premium checks
    status = db.Column(db.String(20), default='pending')
    
    payment_method = db.Column(db.String(50), default='toyyibpay')
    payment_date = db.Column(db.DateTime)
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)  # NULL = lifetime
    
    cancelled_at = db.Column(db.DateTime, nullable=True)
    expired_at = db.Column(db.DateTime, nullable=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=True)
    payment_url = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    plan = db.relationship('SubscriptionPlan', backref='subscriptions')
    voucher = db.relationship('Voucher', backref='used_subscriptions')
    
    PENDING_EXPIRY_MINUTES = 5
    
    def is_currently_active(self) -> bool:
        """
        Check if this subscription grants premium access right now.
        """
        if self.status != 'active':
            return False
        
        now = datetime.utcnow()
        if not self.start_date or self.start_date > now:
            return False
        
        if self.end_date is None:
            return True  # Lifetime
        
        return self.end_date > now
    
    def is_pending_expired(self):
        """Check if pending order is past expiry"""
        if self.status != 'pending':
            return False
        expiry_time = self.created_at + timedelta(minutes=self.PENDING_EXPIRY_MINUTES)
        return datetime.utcnow() > expiry_time
    
    def auto_cancel_if_expired(self):
        """Auto-cancel expired pending orders"""
        if self.is_pending_expired():
            self.status = 'expired'
            self.expired_at = datetime.utcnow()
            return True
        return False
    
    def get_remaining_payment_time(self):
        """Get remaining payment time in seconds"""
        if self.status != 'pending':
            return 0
        expiry_time = self.created_at + timedelta(minutes=self.PENDING_EXPIRY_MINUTES)
        remaining = (expiry_time - datetime.utcnow()).total_seconds()
        return max(0, int(remaining))
    
    def to_dict(self):
        self.auto_cancel_if_expired()
        
        return {
            'id': self.id,
            'userId': self.user_id,
            'orderReference': self.order_reference,
            'billCode': self.bill_code,
            'planId': self.plan_id,
            'planType': self.plan_type,
            'planName': self.plan.name if self.plan else self.plan_type.title(),
            'planLevel': self.plan.level if self.plan else 0,
            'amount': self.amount,
            'originalAmount': self.original_amount,
            'discountAmount': self.discount_amount,
            'status': self.status,
            'isCurrentlyActive': self.is_currently_active(),
            'paymentMethod': self.payment_method,
            'paymentUrl': self.payment_url,
            'paymentDate': self.payment_date.strftime("%Y-%m-%d %H:%M") if self.payment_date else None,
            'startDate': self.start_date.strftime("%Y-%m-%d") if self.start_date else None,
            'endDate': self.end_date.strftime("%Y-%m-%d") if self.end_date else None,
            'isLifetime': self.end_date is None and self.status == 'active',
            'cancelledAt': self.cancelled_at.strftime("%Y-%m-%d %H:%M") if self.cancelled_at else None,
            'expiredAt': self.expired_at.strftime("%Y-%m-%d %H:%M") if self.expired_at else None,
            'voucherId': self.voucher_id,
            'voucherCode': self.voucher.code if self.voucher else None,
            'notes': self.notes,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'canContinuePayment': (
                self.status == 'pending' and 
                not self.is_pending_expired() and 
                bool(self.payment_url)
            ),
            'remainingPaymentTime': self.get_remaining_payment_time()
        }
    
    def to_admin_dict(self):
        """Admin view with more info"""
        data = self.to_dict()
        data['user'] = {
            'id': self.user.id,
            'email': self.user.email,
            'name': self.user.full_name
        } if self.user else None
        return data


# ================================================
# 🎫 Ticket - 用户支持工单
# ================================================
class Ticket(db.Model):
    """
    用户发起的支持工单
    User 必须通过 Ticket 与 Admin 沟通
    """
    __tablename__ = 'tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 发起者
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # 📝 工单信息
    subject = db.Column(db.String(255), nullable=False)          # 主题
    category = db.Column(db.String(50), default='general')       # general / billing / technical / feedback
    priority = db.Column(db.String(20), default='normal')        # low / normal / high / urgent
    
    # 📊 状态
    status = db.Column(db.String(20), default='pending')         # pending / accepted / in_progress / resolved / expired / closed
    
    # 👨‍💼 处理者
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    accepted_at = db.Column(db.DateTime)                         # Admin 接受时间
    
    # ⏰ 时间管理
    expires_at = db.Column(db.DateTime, nullable=False)          # 过期时间（创建后24小时）
    resolved_at = db.Column(db.DateTime)                         # 解决时间
    
    # 🔔 通知状态
    expiry_notified = db.Column(db.Boolean, default=False)       # 是否已发送过期通知
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = db.relationship('User', foreign_keys=[user_id], backref='tickets')
    assigned_admin = db.relationship('User', foreign_keys=[assigned_admin_id])
    messages = db.relationship('TicketMessage', backref='ticket', lazy='dynamic', cascade='all, delete-orphan')
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 自动设置24小时后过期
        if not self.expires_at:
            self.expires_at = datetime.utcnow() + timedelta(hours=24)
    
    def is_expired(self):
        """检查是否已过期"""
        return datetime.utcnow() > self.expires_at and self.status not in ['resolved', 'closed']
    
    def time_remaining(self):
        """剩余时间（秒）"""
        if self.status in ['resolved', 'closed']:
            return 0
        remaining = (self.expires_at - datetime.utcnow()).total_seconds()
        return max(0, remaining)
    
    def accept(self, admin_id):
        """Admin 接受工单"""
        self.assigned_admin_id = admin_id
        self.accepted_at = datetime.utcnow()
        self.status = 'accepted'
        # 重置过期时间（接受后再给24小时）
        self.expires_at = datetime.utcnow() + timedelta(hours=24)
    
    def resolve(self):
        """标记为已解决"""
        self.status = 'resolved'
        self.resolved_at = datetime.utcnow()
    
    def to_dict(self):
        return {
            'id': self.id,
            'userId': self.user_id,
            'userName': self.user.full_name if self.user else None,
            'userEmail': self.user.email if self.user else None,
            'userAvatar': self.user.avatar_url if self.user else None,
            'subject': self.subject,
            'category': self.category,
            'priority': self.priority,
            'status': self.status,
            'assignedAdminId': self.assigned_admin_id,
            'assignedAdminName': self.assigned_admin.full_name if self.assigned_admin else None,
            'acceptedAt': self.accepted_at.isoformat() if self.accepted_at else None,
            'expiresAt': self.expires_at.isoformat() if self.expires_at else None,
            'resolvedAt': self.resolved_at.isoformat() if self.resolved_at else None,
            'timeRemaining': self.time_remaining(),
            'isExpired': self.is_expired(),
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'messageCount': self.messages.count() if self.messages else 0
        }
    
    def to_preview_dict(self):
        """列表预览"""
        return {
            'id': self.id,
            'subject': self.subject,
            'category': self.category,
            'priority': self.priority,
            'status': self.status,
            'userName': self.user.full_name if self.user else 'Unknown',
            'userAvatar': self.user.avatar_url if self.user else None,
            'timeRemaining': self.time_remaining(),
            'isExpired': self.is_expired(),
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'lastMessage': self._get_last_message_preview()
        }
    
    def _get_last_message_preview(self):
        """获取最后一条消息预览"""
        last_msg = self.messages.order_by(TicketMessage.created_at.desc()).first()
        if last_msg:
            return {
                'text': last_msg.content[:50] + '...' if len(last_msg.content) > 50 else last_msg.content,
                'senderType': last_msg.sender_type,
                'time': last_msg.created_at.strftime("%H:%M") if last_msg.created_at else None
            }
        return None


# ================================================
# 💬 TicketMessage - 工单消息
# ================================================
class TicketMessage(db.Model):
    """
    工单内的聊天消息
    支持 User ↔ Admin 双向对话
    """
    __tablename__ = 'ticket_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 关联工单
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False)
    
    # 👤 发送者
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    sender_type = db.Column(db.String(20), nullable=False)       # user / admin
    
    # 📝 消息内容
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='text')      # text / image / file / system
    
    # 📎 附件
    attachment_url = db.Column(db.Text)
    attachment_name = db.Column(db.String(255))
    
    # 📊 状态
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime)
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    sender = db.relationship('User', foreign_keys=[sender_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticketId': self.ticket_id,
            'senderId': self.sender_id,
            'senderType': self.sender_type,
            'senderName': self.sender.full_name if self.sender else 'System',
            'senderAvatar': self.sender.avatar_url if self.sender else None,
            'content': self.content,
            'messageType': self.message_type,
            'attachmentUrl': self.attachment_url,
            'attachmentName': self.attachment_name,
            'isRead': self.is_read,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


# ================================================
# 📢 AdminMessage - Admin 内部消息
# ================================================
class AdminMessage(db.Model):
    """
    Admin ↔ Admin 内部沟通
    Super Admin 可以向单个或所有 Admin 发送消息
    """
    __tablename__ = 'admin_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 👤 发送者（必须是 Admin）
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    
    # 🎯 接收者（null = 广播给所有 Admin）
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    is_broadcast = db.Column(db.Boolean, default=False)
    
    # 📝 消息内容
    subject = db.Column(db.String(255))
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='message')   # message / announcement / alert / task
    priority = db.Column(db.String(20), default='normal')        # low / normal / high / urgent
    
    # 📎 附件
    attachment_url = db.Column(db.Text)
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])
    read_status = db.relationship('AdminMessageRead', backref='message', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'senderId': self.sender_id,
            'senderName': self.sender.full_name if self.sender else 'System',
            'senderAvatar': self.sender.avatar_url if self.sender else None,
            'recipientId': self.recipient_id,
            'recipientName': self.recipient.full_name if self.recipient else 'All Admins',
            'isBroadcast': self.is_broadcast,
            'subject': self.subject,
            'content': self.content,
            'messageType': self.message_type,
            'priority': self.priority,
            'attachmentUrl': self.attachment_url,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


# ================================================
# ✅ AdminMessageRead - Admin 消息已读状态
# ================================================
class AdminMessageRead(db.Model):
    """
    追踪 Admin 消息的已读状态（用于广播消息）
    """
    __tablename__ = 'admin_message_reads'
    
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('admin_messages.id', ondelete='CASCADE'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('message_id', 'admin_id', name='unique_admin_message_read'),
    )

# ================================================
# 💬 AdminChatRoom - Admin 聊天室
# ================================================
class AdminChatRoom(db.Model):
    """
    Admin 聊天室（支持私聊和群聊）
    - 私聊：两个 Admin 之间
    - 群聊：多个 Admin（可选功能）
    """
    __tablename__ = 'admin_chat_rooms'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 🏷️ 聊天室类型
    room_type = db.Column(db.String(20), default='private')  # private / group
    name = db.Column(db.String(100))  # 群聊名称（私聊为 null）
    
    # 👥 参与者（多对多关系通过 AdminChatMember）
    
    # 📊 状态
    is_active = db.Column(db.Boolean, default=True)
    last_message_at = db.Column(db.DateTime)
    last_message_preview = db.Column(db.String(100))
    
    # ⏰ 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    
    # 关系
    members = db.relationship('AdminChatMember', backref='room', lazy='dynamic', cascade='all, delete-orphan')
    messages = db.relationship('AdminChatMessage', backref='room', lazy='dynamic', cascade='all, delete-orphan', order_by='AdminChatMessage.created_at')
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def to_dict(self, current_user_id=None):
        """转换为字典"""
        # 获取对方信息（私聊时）
        other_member = None
        if self.room_type == 'private' and current_user_id:
            other = self.members.filter(AdminChatMember.admin_id != current_user_id).first()
            if other and other.admin:
                other_member = {
                    'id': other.admin.id,
                    'name': other.admin.full_name,
                    'avatar': other.admin.avatar_url,
                    'role': other.admin.role
                }
        
        # 获取未读数
        unread_count = 0
        if current_user_id:
            member = self.members.filter_by(admin_id=current_user_id).first()
            if member:
                unread_count = member.unread_count
        
        return {
            'id': self.id,
            'roomType': self.room_type,
            'name': self.name or (other_member['name'] if other_member else 'Chat'),
            'otherMember': other_member,
            'lastMessageAt': self.last_message_at.isoformat() if self.last_message_at else None,
            'lastMessagePreview': self.last_message_preview,
            'unreadCount': unread_count,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def get_or_create_private_room(cls, admin1_id, admin2_id):
        """获取或创建私聊房间"""
        # 查找现有房间
        existing = db.session.query(cls).join(AdminChatMember).filter(
            cls.room_type == 'private',
            AdminChatMember.admin_id.in_([admin1_id, admin2_id])
        ).group_by(cls.id).having(
            db.func.count(AdminChatMember.id) == 2
        ).first()
        
        if existing:
            # 验证确实是这两个人的房间
            member_ids = [m.admin_id for m in existing.members.all()]
            if set(member_ids) == {admin1_id, admin2_id}:
                return existing
        
        # 创建新房间
        room = cls(room_type='private', created_by=admin1_id)
        db.session.add(room)
        db.session.flush()
        
        # 添加成员
        member1 = AdminChatMember(room_id=room.id, admin_id=admin1_id)
        member2 = AdminChatMember(room_id=room.id, admin_id=admin2_id)
        db.session.add_all([member1, member2])
        
        return room


# ================================================
# 👥 AdminChatMember - 聊天室成员
# ================================================
class AdminChatMember(db.Model):
    """聊天室成员"""
    __tablename__ = 'admin_chat_members'
    
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('admin_chat_rooms.id', ondelete='CASCADE'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # 📊 状态
    unread_count = db.Column(db.Integer, default=0)
    last_read_at = db.Column(db.DateTime)
    is_muted = db.Column(db.Boolean, default=False)
    
    # ⏰ 时间戳
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    admin = db.relationship('User', foreign_keys=[admin_id])
    
    __table_args__ = (
        db.UniqueConstraint('room_id', 'admin_id', name='unique_room_member'),
    )


# ================================================
# 💬 AdminChatMessage - 聊天消息
# ================================================
class AdminChatMessage(db.Model):
    """Admin 聊天消息"""
    __tablename__ = 'admin_chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 关联
    room_id = db.Column(db.Integer, db.ForeignKey('admin_chat_rooms.id', ondelete='CASCADE'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    
    # 📝 消息内容
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='text')  # text / image / file / system
    
    # 📎 附件（可选）
    attachment_url = db.Column(db.Text)
    attachment_name = db.Column(db.String(255))
    
    # 📊 状态
    is_deleted = db.Column(db.Boolean, default=False)
    
    # ⏰ 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    sender = db.relationship('User', foreign_keys=[sender_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'roomId': self.room_id,
            'senderId': self.sender_id,
            'senderName': self.sender.full_name if self.sender else 'Unknown',
            'senderAvatar': self.sender.avatar_url if self.sender else None,
            'content': self.content if not self.is_deleted else '[Message deleted]',
            'messageType': self.message_type,
            'attachmentUrl': self.attachment_url,
            'attachmentName': self.attachment_name,
            'isDeleted': self.is_deleted,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


# ================================================
# 🔔 SystemNotification - 系统通知（扩展）
# ================================================
class SystemNotification(db.Model):
    """
    系统自动生成的通知
    用于：新用户注册、购买 Premium、Ticket 变更等
    """
    __tablename__ = 'system_notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 🎯 接收者类型
    recipient_type = db.Column(db.String(20), nullable=False)    # admin / user / all_admins
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    
    # 📝 通知内容
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text)
    notification_type = db.Column(db.String(50), nullable=False)  # new_user / premium_purchase / ticket_new / ticket_expired / ticket_resolved
    
    # 🔗 关联实体
    related_type = db.Column(db.String(50))                      # user / ticket / subscription
    related_id = db.Column(db.Integer)
    
    # 📊 状态
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime)
    
    # 📧 邮件状态
    email_sent = db.Column(db.Boolean, default=False)
    email_sent_at = db.Column(db.DateTime)
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'recipientType': self.recipient_type,
            'recipientId': self.recipient_id,
            'title': self.title,
            'content': self.content,
            'notificationType': self.notification_type,
            'relatedType': self.related_type,
            'relatedId': self.related_id,
            'isRead': self.is_read,
            'emailSent': self.email_sent,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


# ----------------------
# Notification Table
# ----------------------
#class Notification(db.Model):
 #   __tablename__ = 'notifications'
#
 #   id = db.Column(db.Integer, primary_key=True)
  #  user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
   # text = db.Column(db.String(255), nullable=False)
    #is_read = db.Column(db.Boolean, default=False)
    #created_at = db.Column(db.DateTime, default=datetime.utcnow)
#
 #   def to_dict(self):
  #      return {
   #         "id": self.id,
    #        "text": self.text,
     #       "unread": not self.is_read,
      #      "time": self.created_at.strftime("%H:%M") 
       # }


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

# ----------------------
# Email Verification Table
# ----------------------
class EmailVerification(db.Model):
    __tablename__ = 'email_verifications'
    
    email = db.Column(db.String(255), primary_key=True)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.email,
            'email': self.email,
            'code': self.code,
            'is_verified': False, 
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }

# ----------------------
# Place Cache Table
# ----------------------
class Place(db.Model):
    __tablename__ = 'places'
    
    id = db.Column(db.Integer, primary_key=True)
    google_place_id = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    address = db.Column(db.Text)
    rating = db.Column(db.Float)
    business_status = db.Column(db.String(50))
    is_open_now = db.Column(db.Boolean)
    opening_hours = db.Column(db.JSON) 
    phone = db.Column(db.String(50))
    website = db.Column(db.Text)
    price_level = db.Column(db.String(50)) 
    coordinates = db.Column(db.String(100)) 
    photo_reference = db.Column(db.Text) 
    review_list = db.Column(db.JSON)     
    cached_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_manual = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'google_place_id': self.google_place_id,
            'name': self.name,
            'address': self.address,
            'rating': self.rating,
            'coordinates': self.coordinates,
            'is_manual': bool(self.is_manual)  # 🔴 SINGLE SOURCE OF TRUTH - ensure boolean
        }

# ----------------------
# Trip Table
# ----------------------
class Trip(db.Model):
    __tablename__ = 'trips'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(100))
    destination = db.Column(db.String(100))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    budget_limit = db.Column(db.Float, default=0.0) 
    status = db.Column(db.String(20), default='planning') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    items = db.relationship('TripItem', backref='trip', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'destination': self.destination,
            'startDate': self.start_date.isoformat() if self.start_date else None,
            'endDate': self.end_date.isoformat() if self.end_date else None,
            'budgetLimit': self.budget_limit,
            'status': self.status,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }

# ----------------------
# Trip Item Table
# ----------------------
class TripItem(db.Model):
    __tablename__ = 'trip_items'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id', ondelete='CASCADE'), nullable=False)
    place_id = db.Column(db.Integer, db.ForeignKey('places.id'))
    day_number = db.Column(db.Integer, nullable=False)
    order_index = db.Column(db.Integer, default=0)
    custom_title = db.Column(db.String(255))
    custom_notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='planning') 
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    item_type = db.Column(db.String(50), default='place')
    
    place = db.relationship('Place', backref='trip_items')
    
    def to_dict(self):
        return {
            'id': self.id,
            'tripId': self.trip_id,
            'placeId': self.place_id,
            'dayNumber': self.day_number,
            'orderIndex': self.order_index,
            'customTitle': self.custom_title,
            'customNotes': self.custom_notes,
            'startTime': self.start_time.strftime("%H:%M") if self.start_time else None,
            'endTime': self.end_time.strftime("%H:%M") if self.end_time else None,
            'itemType': self.item_type,
            'place': self.place.to_dict() if self.place else None
        }

# ----------------------
# Expense Table
# ----------------------
class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id', ondelete='CASCADE'), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='MYR')
    category = db.Column(db.String(50))
    date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'amount': self.amount,
            'currency': self.currency,
            'category': self.category,
            'date': self.date.isoformat() if self.date else None,
            'notes': self.notes,
            'tripId': self.trip_id
        }

# ----------------------
# Scheduler Item Table
# ----------------------
class SchedulerItem(db.Model):
    __tablename__ = 'scheduler_items'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    all_day = db.Column(db.Boolean, default=False)
    color = db.Column(db.String(20))
    status = db.Column(db.String(20), default='scheduled')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'startTime': self.start_time.isoformat() if self.start_time else None,
            'endTime': self.end_time.isoformat() if self.end_time else None,
            'allDay': self.all_day,
            'color': self.color,
            'status': self.status
        }
    
class Advertisement(db.Model):
    __tablename__ = 'advertisements'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 基本信息
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # 🆕 Localization (Added via migration)
    title_zh = db.Column(db.Text)
    description_zh = db.Column(db.Text)
    title_ms = db.Column(db.Text)
    description_ms = db.Column(db.Text)
    
    image_url = db.Column(db.Text)
    link = db.Column(db.Text, nullable=False)  # 广告跳转链接
    
    # 状态和优先级
    status = db.Column(db.String(20), default='active')  # active, paused, expired
    priority = db.Column(db.Integer, default=0)  # 优先级，数字越大越优先显示
    
    # 统计数据
    views = db.Column(db.Integer, default=0)  # 展示次数
    clicks = db.Column(db.Integer, default=0)  # 点击次数
    
    # 创建者
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            # 🆕 Include localized fields
            'title_zh': self.title_zh,
            'description_zh': self.description_zh,
            'title_ms': self.title_ms,
            'description_ms': self.description_ms,
            
            'imageUrl': self.image_url,
            'link': self.link,
            'status': self.status,
            'priority': self.priority,
            'views': self.views,
            'clicks': self.clicks,
            'createdBy': self.created_by,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'updatedAt': self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None,
            'ctr': round((self.clicks / self.views * 100), 2) if self.views > 0 else 0  # Click-through rate
        }

# ----------------------
# Calendar Event Table
# ----------------------
class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    trip_item_id = db.Column(db.Integer, db.ForeignKey('trip_items.id', ondelete='SET NULL'))
    google_event_id = db.Column(db.String(255))
    title = db.Column(db.String(255))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    sync_status = db.Column(db.String(20), default='pending')

# ----------------------
# Article Table
# ----------------------
class Article(db.Model):
    __tablename__ = 'articles'

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(50))
    content = db.Column(db.Text)
    cover_image = db.Column(db.Text)
    status = db.Column(db.String(20), default='draft')
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "views": self.views,
            "date": self.created_at.strftime("%Y-%m-%d"),
            "coverImage": self.cover_image,
            "content": self.content
        }

# ----------------------
# Search Cache Table
# ----------------------
class SearchCache(db.Model):
    __tablename__ = 'search_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    location_key = db.Column(db.String(50), nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_query_location', 'query', 'location_key'),
    )

# ----------------------
# System Log Table
# ----------------------
class SystemLog(db.Model):
    __tablename__ = 'system_logs'

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(20))
    action = db.Column(db.String(100))
    details = db.Column(db.Text)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------
# Login Hero Config Table
# ----------------------
class LoginHeroConfig(db.Model):
    __tablename__ = 'login_hero_config'
    
    id = db.Column(db.Integer, primary_key=True)
    display_mode = db.Column(db.String(20), default='single', nullable=False)
    transition_interval = db.Column(db.Integer, default=5)
    auto_play = db.Column(db.Boolean, default=True)
    image_source = db.Column(db.String(20), default='url', nullable=False)
    images_config = db.Column(db.JSON, nullable=False, default=list)
    title = db.Column(db.Text)
    subtitle = db.Column(db.Text)
    description = db.Column(db.Text)
    enable_gradient = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'displayMode': self.display_mode,
            'transitionInterval': self.transition_interval,
            'autoPlay': self.auto_play,
            'imageSource': self.image_source,
            'imagesConfig': self.images_config,
            'title': self.title,
            'subtitle': self.subtitle,
            'description': self.description,
            'enableGradient': self.enable_gradient,
            'isActive': self.is_active,
            'createdBy': self.created_by,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'updatedAt': self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None
        }

# ----------------------
# Hero Image Table
# ----------------------
class HeroImage(db.Model):
    __tablename__ = 'hero_images'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    image_type = db.Column(db.String(20), default='url', nullable=False)
    image_url = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(20), default='external')
    source_place_id = db.Column(db.Integer, db.ForeignKey('places.id'), nullable=True)
    alt_text = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    added_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    place = db.relationship('Place', foreign_keys=[source_place_id])
    
    def to_dict(self):
        if self.image_type == 'proxy':
            display_url = f'/proxy_image?ref={self.image_url}'
        else:
            display_url = self.image_url
        
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'imageType': self.image_type,
            'imageUrl': display_url,
            'rawImageUrl': self.image_url,
            'source': self.source,
            'sourcePlaceId': self.source_place_id,
            'altText': self.alt_text,
            'sortOrder': self.sort_order,
            'isActive': self.is_active,
            'addedBy': self.added_by,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'updatedAt': self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None,
            'place': {
                'id': self.place.id,
                'name': self.place.name,
                'address': self.place.address
            } if self.place else None
        }
    
def create_system_notification(
    recipient_type: str,
    notification_type: str,
    title: str,
    content: str = None,
    recipient_id: int = None,
    related_type: str = None,
    related_id: int = None
):
    """
    创建系统通知的辅助函数
    
    Args:
        recipient_type: 'admin' / 'user' / 'all_admins'
        notification_type: 'new_user' / 'premium_purchase' / 'ticket_new' / 'ticket_expired' / 'ticket_resolved'
        title: 通知标题
        content: 通知内容
        recipient_id: 接收者 ID（如果是 all_admins 则为 None）
        related_type: 关联实体类型 ('user' / 'ticket' / 'subscription')
        related_id: 关联实体 ID
    
    Returns:
        SystemNotification: 创建的通知对象
    """
    notif = SystemNotification(
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        title=title,
        content=content,
        notification_type=notification_type,
        related_type=related_type,
        related_id=related_id
    )
    db.session.add(notif)
    return notif


# =============================================================================
# 📝 Blog System - User Blogs with Social Features
# =============================================================================

class Blog(db.Model):
    """
    User-created blog posts
    Status workflow: draft -> pending -> published / rejected
    """
    __tablename__ = 'blogs'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 Author
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # 📝 Content
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.String(500))  # Short summary for feed
    cover_image = db.Column(db.Text)  # Cover image URL
    
    # 🏷️ Categorization
    category = db.Column(db.String(50), default='general')  # travel, food, tips, experience, other
    tags = db.Column(db.JSON, default=list)  # ["malaysia", "budget", "food"]
    
    # 📊 Status: draft / pending / published / rejected / hidden
    status = db.Column(db.String(20), default='draft')
    rejection_reason = db.Column(db.Text)  # If rejected by admin
    
    # 📈 Statistics
    views = db.Column(db.Integer, default=0)
    
    # ⏰ Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = db.Column(db.DateTime)  # When status changed to published
    
    # Relationships
    author = db.relationship('User', backref='blogs', foreign_keys=[author_id])
    likes = db.relationship('BlogLike', backref='blog', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('BlogComment', backref='blog', lazy='dynamic', cascade='all, delete-orphan')
    reports = db.relationship('BlogReport', backref='blog', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_likes_count(self):
        return self.likes.count()
    
    def get_comments_count(self):
        return self.comments.filter_by(status='visible').count()
    
    def is_liked_by(self, user_id):
        return self.likes.filter_by(user_id=user_id).first() is not None
    
    def to_dict(self, current_user_id=None):
        return {
            'id': self.id,
            'authorId': self.author_id,
            'authorName': self.author.full_name if self.author else 'Unknown',
            'authorAvatar': self.author.avatar_url if self.author else None,
            'title': self.title,
            'content': self.content,
            'excerpt': self.excerpt or (self.content[:200] + '...' if len(self.content) > 200 else self.content),
            'coverImage': self.cover_image,
            'category': self.category,
            'tags': self.tags or [],
            'status': self.status,
            'rejectionReason': self.rejection_reason,
            'views': self.views,
            'likesCount': self.get_likes_count(),
            'commentsCount': self.get_comments_count(),
            'isLiked': self.is_liked_by(current_user_id) if current_user_id else False,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'updatedAt': self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None,
            'publishedAt': self.published_at.strftime("%Y-%m-%d %H:%M") if self.published_at else None
        }
    
    def to_preview_dict(self, current_user_id=None):
        """Lighter version for feed lists"""
        return {
            'id': self.id,
            'authorId': self.author_id,
            'authorName': self.author.full_name if self.author else 'Unknown',
            'authorAvatar': self.author.avatar_url if self.author else None,
            'title': self.title,
            'excerpt': self.excerpt or (self.content[:150] + '...' if len(self.content) > 150 else self.content),
            'coverImage': self.cover_image,
            'category': self.category,
            'status': self.status,
            'views': self.views,
            'likesCount': self.get_likes_count(),
            'commentsCount': self.get_comments_count(),
            'isLiked': self.is_liked_by(current_user_id) if current_user_id else False,
            'publishedAt': self.published_at.strftime("%Y-%m-%d") if self.published_at else None
        }


class BlogLike(db.Model):
    """User likes on blog posts"""
    __tablename__ = 'blog_likes'
    
    id = db.Column(db.Integer, primary_key=True)
    blog_id = db.Column(db.Integer, db.ForeignKey('blogs.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='blog_likes')
    
    __table_args__ = (
        db.UniqueConstraint('blog_id', 'user_id', name='unique_blog_like'),
    )


class BlogComment(db.Model):
    """Comments on blog posts"""
    __tablename__ = 'blog_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    blog_id = db.Column(db.Integer, db.ForeignKey('blogs.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # 📝 Content
    content = db.Column(db.Text, nullable=False)
    
    # 💬 Reply support (optional parent comment)
    parent_id = db.Column(db.Integer, db.ForeignKey('blog_comments.id', ondelete='CASCADE'), nullable=True)
    
    # 📊 Status: visible / hidden / deleted
    status = db.Column(db.String(20), default='visible')
    
    # ⏰ Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='blog_comments')
    replies = db.relationship('BlogComment', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'blogId': self.blog_id,
            'userId': self.user_id,
            'userName': self.user.full_name if self.user else 'Unknown',
            'userAvatar': self.user.avatar_url if self.user else None,
            'content': self.content,
            'parentId': self.parent_id,
            'status': self.status,
            'repliesCount': self.replies.filter_by(status='visible').count(),
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'updatedAt': self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else None
        }


class BlogSubscription(db.Model):
    """
    User subscriptions/follows for blog authors
    subscriber_id follows author_id
    """
    __tablename__ = 'blog_subscriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    subscriber = db.relationship('User', foreign_keys=[subscriber_id], backref='following')
    author = db.relationship('User', foreign_keys=[author_id], backref='followers')
    
    __table_args__ = (
        db.UniqueConstraint('subscriber_id', 'author_id', name='unique_blog_subscription'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'subscriberId': self.subscriber_id,
            'authorId': self.author_id,
            'authorName': self.author.full_name if self.author else 'Unknown',
            'authorAvatar': self.author.avatar_url if self.author else None,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


class BlogReport(db.Model):
    """
    User reports on blog posts
    For admin moderation
    """
    __tablename__ = 'blog_reports'
    
    id = db.Column(db.Integer, primary_key=True)
    blog_id = db.Column(db.Integer, db.ForeignKey('blogs.id', ondelete='CASCADE'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # 📝 Report Details
    reason = db.Column(db.String(50), nullable=False)  # spam / inappropriate / harassment / misinformation / other
    description = db.Column(db.Text)  # Additional details
    
    # 📊 Status: pending / reviewed / resolved / dismissed
    status = db.Column(db.String(20), default='pending')
    
    # 👨‍💼 Admin Handling
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    admin_notes = db.Column(db.Text)
    action_taken = db.Column(db.String(50))  # none / warning / hidden / deleted
    
    # ⏰ Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    
    # Relationships
    reporter = db.relationship('User', foreign_keys=[reporter_id], backref='blog_reports_filed')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    
    __table_args__ = (
        db.UniqueConstraint('blog_id', 'reporter_id', name='unique_blog_report'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'blogId': self.blog_id,
            'blogTitle': self.blog.title if self.blog else 'Deleted Blog',
            'blogAuthorId': self.blog.author_id if self.blog else None,
            'blogAuthorName': self.blog.author.full_name if self.blog and self.blog.author else 'Unknown',
            'reporterId': self.reporter_id,
            'reporterName': self.reporter.full_name if self.reporter else 'Unknown',
            'reason': self.reason,
            'description': self.description,
            'status': self.status,
            'reviewedBy': self.reviewed_by,
            'reviewerName': self.reviewer.full_name if self.reviewer else None,
            'adminNotes': self.admin_notes,
            'actionTaken': self.action_taken,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            'reviewedAt': self.reviewed_at.strftime("%Y-%m-%d %H:%M") if self.reviewed_at else None
        }
    
    def to_preview_dict(self):
        """Lighter version for list view"""
        return {
            'id': self.id,
            'blogId': self.blog_id,
            'blogTitle': self.blog.title if self.blog else 'Deleted Blog',
            'reporterName': self.reporter.full_name if self.reporter else 'Unknown',
            'reason': self.reason,
            'status': self.status,
            'createdAt': self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


class Inquiry(db.Model):
    """
    Public inquiries from Info Site (Merchants / Contact pages)
    No user_id required as these are from public visitors
    """
    __tablename__ = 'inquiries'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 📌 Inquiry Type
    inquiry_type = db.Column(db.String(20), nullable=False)  # merchant / contact
    
    # 👤 Contact Info (not linked to users table - public visitors)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    business_name = db.Column(db.String(255), nullable=True)  # For merchant inquiries
    
    # 📝 Message Content
    subject = db.Column(db.String(255), nullable=True)  # For contact inquiries
    message = db.Column(db.Text, nullable=False)
    
    # 📊 Status
    status = db.Column(db.String(20), default='pending')  # pending / in_progress / resolved / closed
    priority = db.Column(db.String(20), default='normal')  # low / normal / high
    
    # 👨‍💼 Admin Handling
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)  # Internal notes for admins
    
    # ⏰ Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # 🔔 Notification Status
    admin_notified = db.Column(db.Boolean, default=False)
    
    # Relationships
    assigned_admin = db.relationship('User', foreign_keys=[assigned_admin_id])
    
    def to_preview_dict(self):
        """Preview dict for list view - 🔥 FIXED: Include assignedAdminName"""
        # 🔥 FIX: Get assigned admin name
        assigned_admin_name = None
        if self.assigned_admin_id:
            from models import User  # Import if needed
            admin = User.query.get(self.assigned_admin_id)
            if admin:
                assigned_admin_name = admin.full_name or admin.email
        
        return {
            'id': self.id,
            'inquiryType': self.inquiry_type,
            'name': self.name,
            'email': self.email,
            'businessName': self.business_name,
            'subject': self.subject,
            'status': self.status,
            'priority': self.priority,
            'assignedAdminId': self.assigned_admin_id,
            'assignedAdminName': assigned_admin_name,  # 🔥 ADD THIS LINE
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def to_dict(self):
        """Full dict for detail view"""
        # 🔥 FIX: Get assigned admin name
        assigned_admin_name = None
        if self.assigned_admin_id:
            from models import User
            admin = User.query.get(self.assigned_admin_id)
            if admin:
                assigned_admin_name = admin.full_name or admin.email
        
        return {
            'id': self.id,
            'inquiryType': self.inquiry_type,
            'name': self.name,
            'email': self.email,
            'businessName': self.business_name,
            'subject': self.subject,
            'message': self.message,
            'status': self.status,
            'priority': self.priority,
            'assignedAdminId': self.assigned_admin_id,
            'assignedAdminName': assigned_admin_name,  # 🔥 ADD THIS LINE
            'adminNotes': self.admin_notes,
            'adminNotified': self.admin_notified,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'resolvedAt': self.resolved_at.isoformat() if self.resolved_at else None,
        }

