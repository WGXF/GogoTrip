from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from models import db, User, Subscription, SubscriptionPlan, Voucher, VoucherUsage, Notification
from datetime import datetime, timedelta
from functools import wraps
from utils import send_system_email, generate_subscription_email_html

admin_subscription_bp = Blueprint('admin_subscription', __name__)


# =============================================================================
# 🔥 STANDARDIZED ROLE ENUM (Same as admin.py)
# =============================================================================
class UserRole:
    """Standardized role values - use these constants everywhere"""
    SUPER_ADMIN = 'super_admin'
    ADMIN = 'admin'
    USER = 'user'
    
    ALL_ROLES = [SUPER_ADMIN, ADMIN, USER]
    ADMIN_ROLES = [SUPER_ADMIN, ADMIN]
    
    # Legacy role mapping (for backward compatibility)
    LEGACY_MAP = {
        'Administrator': SUPER_ADMIN,
        'Admin': ADMIN,
        'User': USER,
        'administrator': SUPER_ADMIN,
        'ADMIN': ADMIN,
        'USER': USER,
    }
    
    @classmethod
    def normalize(cls, role: str) -> str:
        """Convert legacy role names to standardized enum values"""
        if role in cls.ALL_ROLES:
            return role
        return cls.LEGACY_MAP.get(role, cls.USER)
    
    @classmethod
    def is_admin(cls, role: str) -> bool:
        """Check if role has admin privileges"""
        normalized = cls.normalize(role)
        return normalized in cls.ADMIN_ROLES
    
    @classmethod
    def is_super_admin(cls, role: str) -> bool:
        """Check if role is super_admin"""
        return cls.normalize(role) == cls.SUPER_ADMIN


# =============================================================================
# Admin Permission Decorator (Updated)
# =============================================================================
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        # Support both legacy and new role names
        if not UserRole.is_admin(current_user.role):
            if current_user.role not in ["Administrator", "super_admin", "Admin"]:
                return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# 🔥 Helper: Get filtered user query based on admin role
# =============================================================================
def get_filtered_user_query():
    """
    Returns a filtered User query based on current admin's role.
    - super_admin: Can see ALL users
    - admin: Can ONLY see users with role='user'
    """
    current_admin_role = UserRole.normalize(current_user.role)
    
    query = User.query.filter(User.status != 'deleted')
    
    # 🔥 CORE PERMISSION LOGIC
    if current_admin_role == UserRole.SUPER_ADMIN:
        # Super admin can see ALL users
        pass
    elif current_admin_role == UserRole.ADMIN:
        # Regular admin can ONLY see normal users (role='user')
        # Filter out admin and super_admin users
        query = query.filter(
            ~User.role.in_([
                UserRole.SUPER_ADMIN, 
                UserRole.ADMIN,
                'Administrator',
                'Admin'
            ])
        )
    
    return query, current_admin_role


def check_user_permission(user):
    """
    Check if current admin can access/modify this user.
    Returns (allowed: bool, error_message: str or None)
    """
    current_admin_role = UserRole.normalize(current_user.role)
    target_user_role = UserRole.normalize(user.role)
    
    if current_admin_role == UserRole.ADMIN:
        if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
            return False, 'Permission denied: Cannot access admin users'
    
    return True, None


# =============================================================================
# Helper Functions
# =============================================================================
def get_user_active_subscription(user):
    """Get user's current active subscription"""
    now = datetime.utcnow()
    active_subs = [
        sub for sub in user.subscriptions 
        if (sub.status == 'active' and 
            sub.start_date and sub.start_date <= now and
            (sub.end_date is None or sub.end_date > now))
    ]
    
    if not active_subs:
        return None
    
    lifetime_subs = [s for s in active_subs if s.end_date is None]
    if lifetime_subs:
        return lifetime_subs[0]
    
    return max(active_subs, key=lambda s: s.end_date)


def calculate_new_end_date(user, additional_days):
    """Calculate new end_date with accumulation logic"""
    now = datetime.utcnow()
    active_sub = get_user_active_subscription(user)
    
    if active_sub and active_sub.end_date:
        base_date = max(active_sub.end_date, now)
    else:
        base_date = now
    
    if additional_days is None:
        return None  # Lifetime
    
    return base_date + timedelta(days=additional_days)


# =============================================================================
# Statistics (FIXED: With role-based filtering)
# =============================================================================
@admin_subscription_bp.route('/statistics', methods=['GET'])
@admin_required
def get_statistics():
    """Get subscription statistics - filtered by admin role"""
    try:
        today = datetime.utcnow().date()
        now = datetime.utcnow()
        month_start = datetime(today.year, today.month, 1)
        
        # 🔥 Get filtered query based on role
        user_query, current_admin_role = get_filtered_user_query()
        
        # Get visible user IDs for subscription filtering
        visible_user_ids = [u.id for u in user_query.filter(User.status == 'active').all()]
        
        total_users = user_query.filter(User.status == 'active').count()
        
        # ✅ FIXED: Count premium users from Subscription table (with role filter)
        premium_user_ids_query = db.session.query(Subscription.user_id).filter(
            Subscription.status == 'active',
            Subscription.start_date <= now,
            db.or_(
                Subscription.end_date.is_(None),
                Subscription.end_date > now
            )
        )
        
        # 🔥 Apply role-based filter
        if current_admin_role == UserRole.ADMIN:
            premium_user_ids_query = premium_user_ids_query.filter(
                Subscription.user_id.in_(visible_user_ids)
            )
        
        premium_user_ids = premium_user_ids_query.distinct().subquery()
        
        premium_users = User.query.filter(
            User.status == 'active',
            User.id.in_(premium_user_ids)
        ).count()
        
        # Today's subscriptions
        today_subs_query = Subscription.query.filter(
            Subscription.status == 'active',
            db.func.date(Subscription.payment_date) == today
        )
        if current_admin_role == UserRole.ADMIN:
            today_subs_query = today_subs_query.filter(Subscription.user_id.in_(visible_user_ids))
        today_subscriptions = today_subs_query.count()
        
        # Monthly revenue
        revenue_query = db.session.query(db.func.sum(Subscription.amount)).filter(
            Subscription.status == 'active',
            Subscription.payment_date >= month_start
        )
        if current_admin_role == UserRole.ADMIN:
            revenue_query = revenue_query.filter(Subscription.user_id.in_(visible_user_ids))
        monthly_revenue = revenue_query.scalar() or 0
        
        # ✅ FIXED: Expiring soon - query from Subscription table
        seven_days_later = now + timedelta(days=7)
        expiring_query = Subscription.query.filter(
            Subscription.status == 'active',
            Subscription.end_date.isnot(None),
            Subscription.end_date <= seven_days_later,
            Subscription.end_date > now
        )
        if current_admin_role == UserRole.ADMIN:
            expiring_query = expiring_query.filter(Subscription.user_id.in_(visible_user_ids))
        expiring_soon = expiring_query.distinct(Subscription.user_id).count()
        
        # Pending orders
        pending_query = Subscription.query.filter_by(status='pending')
        if current_admin_role == UserRole.ADMIN:
            pending_query = pending_query.filter(Subscription.user_id.in_(visible_user_ids))
        pending_orders = pending_query.count()
        
        # Voucher stats (not filtered by role - vouchers are global)
        active_vouchers = Voucher.query.filter_by(status='active').count()
        voucher_uses_today = VoucherUsage.query.filter(
            db.func.date(VoucherUsage.created_at) == today
        ).count()
        
        # Lifetime subscriptions count
        lifetime_query = Subscription.query.filter(
            Subscription.status == 'active',
            Subscription.end_date.is_(None),
            Subscription.start_date <= now
        )
        if current_admin_role == UserRole.ADMIN:
            lifetime_query = lifetime_query.filter(Subscription.user_id.in_(visible_user_ids))
        lifetime_count = lifetime_query.distinct(Subscription.user_id).count()
        
        return jsonify({
            'total_users': total_users,
            'premium_users': premium_users,
            'premium_percentage': round(premium_users / total_users * 100, 1) if total_users > 0 else 0,
            'today_subscriptions': today_subscriptions,
            'monthly_revenue': round(monthly_revenue, 2),
            'expiring_soon': expiring_soon,
            'pending_orders': pending_orders,
            'active_vouchers': active_vouchers,
            'voucher_uses_today': voucher_uses_today,
            'lifetime_subscriptions': lifetime_count,
            # 🔥 Include permission info for frontend
            'currentAdminRole': current_admin_role,
            'viewScope': 'all_users' if current_admin_role == UserRole.SUPER_ADMIN else 'regular_users_only'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# All Transactions (Admin) - With role filtering
# =============================================================================
@admin_subscription_bp.route('/transactions', methods=['GET'])
@admin_required
def get_all_transactions():
    """Get all transactions - filtered by admin role"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('status')
        user_id = request.args.get('user_id', type=int)
        plan_type = request.args.get('plan_type')
        search = request.args.get('search', '').strip()
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        # 🔥 Get current admin role
        current_admin_role = UserRole.normalize(current_user.role)
        
        query = Subscription.query.join(User)
        
        # 🔥 Apply role-based filter
        if current_admin_role == UserRole.ADMIN:
            query = query.filter(
                ~User.role.in_([
                    UserRole.SUPER_ADMIN, 
                    UserRole.ADMIN,
                    'Administrator',
                    'Admin'
                ])
            )
        
        if status_filter and status_filter != 'all':
            query = query.filter(Subscription.status == status_filter)
        if user_id:
            query = query.filter(Subscription.user_id == user_id)
        if plan_type:
            query = query.filter(Subscription.plan_type == plan_type)
        if search:
            query = query.filter(
                db.or_(
                    User.email.ilike(f'%{search}%'),
                    User.full_name.ilike(f'%{search}%'),
                    Subscription.order_reference.ilike(f'%{search}%')
                )
            )
        if date_from:
            query = query.filter(Subscription.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(Subscription.created_at <= datetime.fromisoformat(date_to))
        
        pagination = query.order_by(Subscription.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        transactions = []
        for sub in pagination.items:
            sub.auto_cancel_if_expired()
            transactions.append(sub.to_admin_dict())
        
        db.session.commit()
        
        return jsonify({
            'transactions': transactions,
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            },
            # 🔥 Include permission info
            'currentAdminRole': current_admin_role
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Plan Management (No role filtering - plans are global)
# =============================================================================
@admin_subscription_bp.route('/plans', methods=['GET'])
@admin_required
def get_plans():
    """Get all plans"""
    try:
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        
        query = SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order)
        if not include_inactive:
            query = query.filter_by(status='active')
        
        plans = query.all()
        return jsonify({'plans': [p.to_dict() for p in plans]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/plans', methods=['POST'])
@admin_required
def create_plan():
    """Create new plan"""
    try:
        data = request.get_json()
        
        if not data.get('name') or not data.get('slug') or data.get('price') is None:
            return jsonify({'error': 'Name, slug, and price are required'}), 400
        
        if SubscriptionPlan.query.filter_by(slug=data['slug']).first():
            return jsonify({'error': 'Slug already exists'}), 400
        
        plan = SubscriptionPlan(
            name=data['name'],
            slug=data['slug'],
            description=data.get('description'),
            level=data.get('level', 1),
            price=float(data['price']),
            currency=data.get('currency', 'MYR'),
            duration_days=data.get('durationDays'),
            duration_type=data.get('durationType', 'days'),
            status=data.get('status', 'active'),
            is_featured=data.get('isFeatured', False),
            sort_order=data.get('sortOrder', 0),
            created_by=current_user.id
        )
        
        db.session.add(plan)
        db.session.commit()
        
        return jsonify({'success': True, 'plan': plan.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/plans/<int:plan_id>', methods=['GET'])
@admin_required
def get_plan(plan_id):
    """Get single plan"""
    plan = SubscriptionPlan.query.get_or_404(plan_id)
    
    subscription_count = Subscription.query.filter_by(plan_id=plan_id, status='active').count()
    
    data = plan.to_dict()
    data['subscriptionCount'] = subscription_count
    
    return jsonify({'plan': data})


@admin_subscription_bp.route('/plans/<int:plan_id>', methods=['PUT'])
@admin_required
def update_plan(plan_id):
    """Update plan"""
    try:
        plan = SubscriptionPlan.query.get_or_404(plan_id)
        data = request.get_json()
        
        updatable_fields = {
            'name': 'name',
            'description': 'description',
            'price': 'price',
            'level': 'level',
            'status': 'status',
            'isFeatured': 'is_featured',
            'sortOrder': 'sort_order'
        }
        
        for json_field, db_field in updatable_fields.items():
            if json_field in data:
                setattr(plan, db_field, data[json_field])
        
        db.session.commit()
        return jsonify({'success': True, 'plan': plan.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/plans/<int:plan_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_plan_status(plan_id):
    """Toggle plan status"""
    try:
        plan = SubscriptionPlan.query.get_or_404(plan_id)
        plan.status = 'inactive' if plan.status == 'active' else 'active'
        db.session.commit()
        
        action = 'activated' if plan.status == 'active' else 'deactivated'
        
        return jsonify({
            'success': True,
            'plan': plan.to_dict(),
            'message': f"Plan {action} successfully"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Voucher Management (No role filtering - vouchers are global)
# =============================================================================
@admin_subscription_bp.route('/vouchers', methods=['GET'])
@admin_required
def get_vouchers():
    """Get all vouchers"""
    try:
        status_filter = request.args.get('status')
        voucher_type = request.args.get('type')
        
        query = Voucher.query.order_by(Voucher.created_at.desc())
        
        if status_filter:
            query = query.filter_by(status=status_filter)
        if voucher_type:
            query = query.filter_by(voucher_type=voucher_type)
        
        vouchers = query.all()
        
        # Auto-calibrate usage counts
        for v in vouchers:
            actual_count = VoucherUsage.query.filter_by(voucher_id=v.id).count()
            if v.current_uses != actual_count:
                v.current_uses = actual_count
                
        db.session.commit()
        
        return jsonify({'vouchers': [v.to_dict() for v in vouchers]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/vouchers', methods=['POST'])
@admin_required
def create_voucher():
    """Create voucher"""
    try:
        data = request.get_json()
        
        if not data.get('code') or not data.get('voucherType'):
            return jsonify({'error': 'Code and voucher type are required'}), 400
        
        code = data['code'].upper().strip()
        if Voucher.query.filter_by(code=code).first():
            return jsonify({'error': 'Voucher code already exists'}), 400
        
        valid_until = None
        if data.get('validUntil'):
            date_str = data['validUntil'].split('T')[0]
            dt = datetime.fromisoformat(date_str)
            valid_until = dt.replace(hour=23, minute=59, second=59)
        
        voucher = Voucher(
            code=code,
            name=data.get('name'),
            description=data.get('description'),
            voucher_type=data['voucherType'],
            discount_type=data.get('discountType'),
            discount_value=data.get('discountValue'),
            min_amount=data.get('minAmount', 0),
            max_discount=data.get('maxDiscount'),
            activation_plan_id=data.get('activationPlanId'),
            activation_days=data.get('activationDays'),
            max_uses=data.get('maxUses', 1),
            max_uses_per_user=data.get('maxUsesPerUser', 1),
            applicable_plans=data.get('applicablePlans', []),
            valid_from=datetime.fromisoformat(data['validFrom'].split('T')[0]) if data.get('validFrom') else datetime.utcnow(),
            valid_until=valid_until,
            status=data.get('status', 'active'),
            created_by=current_user.id
        )
        
        db.session.add(voucher)
        db.session.commit()
        
        return jsonify({'success': True, 'voucher': voucher.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/vouchers/<int:voucher_id>', methods=['GET'])
@admin_required
def get_voucher(voucher_id):
    """Get single voucher"""
    voucher = Voucher.query.get_or_404(voucher_id)
    
    actual_count = VoucherUsage.query.filter_by(voucher_id=voucher.id).count()
    if voucher.current_uses != actual_count:
        voucher.current_uses = actual_count
        db.session.commit()
    
    data = voucher.to_dict()
    data['usages'] = [{
        'id': u.id,
        'userId': u.user_id,
        'userName': u.user.full_name if u.user else None,
        'userEmail': u.user.email if u.user else None,
        'usageType': u.usage_type,
        'discountAmount': u.discount_amount,
        'createdAt': u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else None
    } for u in voucher.usages]
    
    return jsonify({'voucher': data})


@admin_subscription_bp.route('/vouchers/<int:voucher_id>', methods=['PUT'])
@admin_required
def update_voucher(voucher_id):
    """Update voucher"""
    try:
        voucher = Voucher.query.get_or_404(voucher_id)
        data = request.get_json()
        
        updatable_fields = {
            'name': 'name',
            'description': 'description',
            'discountType': 'discount_type',
            'discountValue': 'discount_value',
            'minAmount': 'min_amount',
            'maxDiscount': 'max_discount',
            'maxUses': 'max_uses',
            'maxUsesPerUser': 'max_uses_per_user',
            'applicablePlans': 'applicable_plans',
            'status': 'status',
            'activationDays': 'activation_days',
            'activationPlanId': 'activation_plan_id',
            'voucherType': 'voucher_type'
        }
        
        for json_field, db_field in updatable_fields.items():
            if json_field in data:
                val = data[json_field]
                if json_field == 'applicablePlans' and val is None:
                    val = []
                setattr(voucher, db_field, val)
        
        if 'validUntil' in data:
            if data['validUntil']:
                date_str = data['validUntil'].split('T')[0]
                dt = datetime.fromisoformat(date_str)
                voucher.valid_until = dt.replace(hour=23, minute=59, second=59)
            else:
                voucher.valid_until = None
                
        if 'validFrom' in data:
            if data['validFrom']:
                date_str = data['validFrom'].split('T')[0]
                voucher.valid_from = datetime.fromisoformat(date_str)
        
        db.session.commit()
        return jsonify({'success': True, 'voucher': voucher.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/vouchers/<int:voucher_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_voucher_status(voucher_id):
    """Toggle voucher status"""
    try:
        voucher = Voucher.query.get_or_404(voucher_id)
        voucher.status = 'inactive' if voucher.status == 'active' else 'active'
        db.session.commit()
        
        return jsonify({'success': True, 'voucher': voucher.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/vouchers/<int:voucher_id>/usages', methods=['GET'])
@admin_required
def get_voucher_usages(voucher_id):
    """Get voucher usage records"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    pagination = VoucherUsage.query.filter_by(voucher_id=voucher_id)\
        .join(User)\
        .order_by(VoucherUsage.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    usages = [{
        'id': u.id,
        'userId': u.user_id,
        'userName': u.user.full_name if u.user else None,
        'userEmail': u.user.email if u.user else None,
        'usageType': u.usage_type,
        'discountAmount': u.discount_amount,
        'subscriptionId': u.subscription_id,
        'createdAt': u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else None
    } for u in pagination.items]
    
    return jsonify({
        'usages': usages,
        'pagination': {
            'page': page,
            'perPage': per_page,
            'total': pagination.total,
            'pages': pagination.pages
        }
    })


# =============================================================================
# Admin Grant Subscription (With role permission check)
# =============================================================================
@admin_subscription_bp.route('/add-subscription', methods=['POST'])
@admin_required
def add_subscription():
    """
    ✅ Admin grant subscription
    🔥 With role-based permission check
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        subscription_type = data.get('subscription_type', 'preset')
        plan_type = data.get('plan_type', 'monthly')
        custom_days = data.get('custom_days')
        amount = data.get('amount', 0)
        notes = data.get('notes', '')
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # 🔥 PERMISSION CHECK
        allowed, error_msg = check_user_permission(user)
        if not allowed:
            return jsonify({'error': error_msg}), 403
        
        # Determine duration
        plan = None
        plan_id = None
        if subscription_type == 'preset':
            plan = SubscriptionPlan.query.filter_by(slug=plan_type).first()
            duration_days = plan.duration_days if plan else 30
            plan_id = plan.id if plan else None
        else:
            duration_days = int(custom_days) if custom_days else 30
            plan_type = 'admin_grant'
            plan_id = None
        
        # ✅ Calculate end_date with accumulation
        new_end_date = calculate_new_end_date(user, duration_days)
        
        # Create order reference
        import time
        order_reference = f"admin_{user_id}_{int(time.time())}"
        
        now = datetime.utcnow()
        
        # Create subscription
        subscription = Subscription(
            user_id=user_id,
            order_reference=order_reference,
            plan_id=plan_id,
            plan_type=plan_type,
            amount=float(amount),
            original_amount=float(amount),
            discount_amount=0,
            status='active',
            payment_method='admin_granted',
            payment_date=now,
            start_date=now,
            end_date=new_end_date,
            notes=f"Granted by Admin: {current_user.full_name or current_user.email}. {notes}"
        )
        
        db.session.add(subscription)
        db.session.commit()
        
        # 🔔 TRANSACTIONAL: Create in-app notification + Send email
        try:
            plan_name = plan.name if plan else 'Premium'
            
            notif_title = "🎁 Premium Subscription Granted!"
            if new_end_date:
                notif_text = f"An administrator has granted you {plan_name} subscription until {new_end_date.strftime('%Y-%m-%d')}."
            else:
                notif_text = f"An administrator has granted you lifetime {plan_name} access!"
            
            notification = Notification(
                user_id=user.id,
                title=notif_title,
                text=notif_text,
                type='success',
                is_broadcast=False
            )
            db.session.add(notification)
            db.session.commit()
            print(f"📬 Admin grant notification created for user {user.id}")
            
            subject, html_content, text_content = generate_subscription_email_html(
                user_name=user.full_name or 'Valued Customer',
                plan_name=plan_name,
                end_date=new_end_date.strftime('%Y-%m-%d') if new_end_date else None,
                is_lifetime=(new_end_date is None),
                action_type='admin_grant'
            )
            send_system_email(user.email, subject, html_content, text_content)
            
        except Exception as notif_error:
            print(f"⚠️ Notification/email error (non-fatal): {str(notif_error)}")
        
        return jsonify({
            'success': True,
            'subscription': subscription.to_dict(),
            'user': user.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Admin Cancel Subscription (With role permission check)
# =============================================================================
@admin_subscription_bp.route('/cancel-subscription', methods=['POST'])
@admin_required
def cancel_subscription():
    """
    ✅ Admin cancel subscription
    🔥 With role-based permission check
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # 🔥 PERMISSION CHECK
        allowed, error_msg = check_user_permission(user)
        if not allowed:
            return jsonify({'error': error_msg}), 403
        
        now = datetime.utcnow()
        cancelled_count = 0
        
        # ✅ Cancel all active subscriptions
        for sub in user.subscriptions:
            if sub.status == 'active':
                sub.status = 'cancelled'
                sub.cancelled_at = now
                sub.notes = (sub.notes or '') + f"\n[{now.strftime('%Y-%m-%d')}] Cancelled by Admin: {current_user.full_name or current_user.email}"
                cancelled_count += 1
        
        db.session.commit()
        
        # 🔔 TRANSACTIONAL: Create in-app notification + Send email
        if cancelled_count > 0:
            try:
                notification = Notification(
                    user_id=user.id,
                    title="📋 Subscription Cancelled",
                    text="Your premium subscription has been cancelled by an administrator.",
                    type='warning',
                    is_broadcast=False
                )
                db.session.add(notification)
                db.session.commit()
                print(f"📬 Admin cancel notification created for user {user.id}")
                
                subject, html_content, text_content = generate_subscription_email_html(
                    user_name=user.full_name or 'Valued Customer',
                    plan_name='Premium',
                    end_date=None,
                    is_lifetime=False,
                    action_type='admin_cancel'
                )
                send_system_email(user.email, subject, html_content, text_content)
                
            except Exception as notif_error:
                print(f"⚠️ Notification/email error (non-fatal): {str(notif_error)}")
        
        return jsonify({
            'success': True,
            'message': f'Cancelled {cancelled_count} subscription(s)',
            'user': user.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Extend Subscription (With role permission check)
# =============================================================================
@admin_subscription_bp.route('/extend-subscription', methods=['POST'])
@admin_required
def extend_subscription():
    """
    ✅ Admin extend existing subscription
    🔥 With role-based permission check
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        days_to_add = data.get('days', 30)
        notes = data.get('notes', '')
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # 🔥 PERMISSION CHECK
        allowed, error_msg = check_user_permission(user)
        if not allowed:
            return jsonify({'error': error_msg}), 403
        
        active_sub = get_user_active_subscription(user)
        
        if not active_sub:
            return jsonify({'error': 'User has no active subscription to extend'}), 400
        
        if active_sub.end_date is None:
            return jsonify({'error': 'Cannot extend lifetime subscription'}), 400
        
        # ✅ Accumulate time
        old_end = active_sub.end_date
        new_end_date = calculate_new_end_date(user, days_to_add)
        
        active_sub.end_date = new_end_date
        now = datetime.utcnow()
        active_sub.notes = (active_sub.notes or '') + f"\n[{now.strftime('%Y-%m-%d')}] Extended +{days_to_add} days by Admin: {current_user.full_name or current_user.email}. {notes}"
        
        db.session.commit()
        
        # 🔔 TRANSACTIONAL: Create in-app notification + Send email
        try:
            plan_name = active_sub.plan.name if active_sub.plan else 'Premium'
            
            notification = Notification(
                user_id=user.id,
                title="⏰ Subscription Extended!",
                text=f"Your subscription has been extended by {days_to_add} days. New expiry: {new_end_date.strftime('%Y-%m-%d')}.",
                type='success',
                is_broadcast=False
            )
            db.session.add(notification)
            db.session.commit()
            print(f"📬 Admin extend notification created for user {user.id}")
            
            subject, html_content, text_content = generate_subscription_email_html(
                user_name=user.full_name or 'Valued Customer',
                plan_name=plan_name,
                end_date=new_end_date.strftime('%Y-%m-%d'),
                is_lifetime=False,
                action_type='admin_extend'
            )
            send_system_email(user.email, subject, html_content, text_content)
            
        except Exception as notif_error:
            print(f"⚠️ Notification/email error (non-fatal): {str(notif_error)}")
        
        return jsonify({
            'success': True,
            'message': f'Extended subscription by {days_to_add} days',
            'oldEndDate': old_end.strftime("%Y-%m-%d"),
            'newEndDate': new_end_date.strftime("%Y-%m-%d"),
            'subscription': active_sub.to_dict(),
            'user': user.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Get Users (With role filtering)
# =============================================================================
@admin_subscription_bp.route('/users', methods=['GET'])
@admin_required
def get_users():
    """Get users list - filtered by admin role"""
    try:
        search = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        premium_only = request.args.get('premium_only', 'false').lower() == 'true'
        
        # 🔥 Get filtered query based on role
        query, current_admin_role = get_filtered_user_query()
        
        if search:
            query = query.filter(
                db.or_(
                    User.email.ilike(f'%{search}%'),
                    User.full_name.ilike(f'%{search}%')
                )
            )
        
        if premium_only:
            # ✅ FIXED: Filter by Subscription table, not User.is_premium
            now = datetime.utcnow()
            premium_user_ids = db.session.query(Subscription.user_id).filter(
                Subscription.status == 'active',
                Subscription.start_date <= now,
                db.or_(
                    Subscription.end_date.is_(None),
                    Subscription.end_date > now
                )
            ).distinct().subquery()
            
            query = query.filter(User.id.in_(premium_user_ids))
        
        pagination = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        users = []
        for u in pagination.items:
            # Get subscription info from Subscription table
            active_sub = get_user_active_subscription(u)
            end_date = active_sub.end_date if active_sub else None
            
            users.append({
                'id': u.id,
                'email': u.email,
                'full_name': u.full_name,
                'role': UserRole.normalize(u.role),  # 🔥 Include normalized role
                'is_premium': u.is_premium_active,
                'subscription_end_date': end_date.strftime("%Y-%m-%d") if end_date else None,
                'is_lifetime': active_sub.end_date is None if active_sub else False,
                'current_plan': active_sub.plan.name if active_sub and active_sub.plan else None,
                'created_at': u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else None
            })
        
        return jsonify({
            'users': users,
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            },
            # 🔥 Include permission info for frontend
            'currentAdminRole': current_admin_role,
            'canManageAdmins': current_admin_role == UserRole.SUPER_ADMIN
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_subscription_bp.route('/users/<int:user_id>/subscriptions', methods=['GET'])
@admin_required
def get_user_subscriptions(user_id):
    """Get user's subscription history - with permission check"""
    user = User.query.get_or_404(user_id)
    
    # 🔥 PERMISSION CHECK
    allowed, error_msg = check_user_permission(user)
    if not allowed:
        return jsonify({'error': error_msg}), 403
    
    subscriptions = Subscription.query.filter_by(user_id=user_id)\
        .order_by(Subscription.created_at.desc()).all()
    
    for sub in subscriptions:
        sub.auto_cancel_if_expired()
    db.session.commit()
    
    # Get active subscription info
    active_sub = get_user_active_subscription(user)
    end_date = active_sub.end_date if active_sub else None
    
    return jsonify({
        'user': {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'role': UserRole.normalize(user.role),  # 🔥 Include normalized role
            'is_premium': user.is_premium_active,
            'subscription_end_date': end_date.strftime("%Y-%m-%d") if end_date else None,
            'is_lifetime': active_sub.end_date is None if active_sub else False,
            'remaining_days': user.get_remaining_premium_days(),
            'current_plan_level': user.get_current_plan_level()
        },
        'subscriptions': [s.to_dict() for s in subscriptions]
    })