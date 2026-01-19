import requests
import time
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from models import db, User, Subscription, SubscriptionPlan, Voucher, VoucherUsage, Notification
from datetime import datetime, timedelta
import config
from utils import send_system_email, generate_subscription_email_html

payment_bp = Blueprint('payment', __name__)


# =============================================================================
# Helper Functions
# =============================================================================

def get_user_active_subscription(user):
    """
    Get user's current active subscription with the latest end_date.
    Returns None if no active subscription.
    """
    now = datetime.utcnow()
    active_subs = [
        sub for sub in user.subscriptions 
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


def calculate_new_end_date(user, additional_days):
    """
    ✅ CORRECT LOGIC: Calculate new end_date by accumulating time
    
    new_end_date = max(current_end_date, now) + additional_days
    
    This ensures:
    - 3020 days remaining + 300 day code = 3320 days total
    - Expired user + 300 day code = now + 300 days
    """
    now = datetime.utcnow()
    
    active_sub = get_user_active_subscription(user)
    
    if active_sub and active_sub.end_date:
        # User has active subscription with end_date
        base_date = max(active_sub.end_date, now)
    else:
        # No active subscription or lifetime - start from now
        base_date = now
    
    if additional_days is None:
        return None  # Lifetime
    
    return base_date + timedelta(days=additional_days)


def can_user_purchase_plan(user, new_plan):
    """
    ✅ CORRECT LOGIC: Check if user can purchase a plan based on LEVEL, not days

    Returns: (can_purchase, action_type, message)
    - action_type: 'purchase', 'renew', 'upgrade', 'blocked'
    """
    current_sub = get_user_active_subscription(user)

    if not current_sub:
        # No active subscription at all - can purchase any plan
        return True, 'purchase', 'New subscription'

    if not current_sub.plan:
        # Active subscription exists but without a linked plan (e.g., from activation code)
        # Treat as upgrade to ensure days accumulate properly
        return True, 'upgrade', 'Upgrade from activation subscription'

    current_level = current_sub.plan.level if current_sub.plan else 0
    new_level = new_plan.level

    if new_level > current_level:
        # Upgrade allowed
        return True, 'upgrade', f'Upgrade from Level {current_level} to Level {new_level}'
    elif new_level == current_level:
        # Same level - Renew (extend time)
        return True, 'renew', 'Renew current plan'
    else:
        # Downgrade blocked
        return False, 'blocked', 'Your current plan is higher level. Cannot downgrade.'


# =============================================================================
# 获取可用的订阅计划 (公开)
# =============================================================================
@payment_bp.route('/plans', methods=['GET'])
def get_available_plans():
    """获取所有 active 的订阅计划，包含用户的购买状态"""
    try:
        plans = SubscriptionPlan.query.filter_by(status='active')\
            .order_by(SubscriptionPlan.sort_order).all()
        
        plans_data = []
        for p in plans:
            plan_dict = p.to_dict()
            
            # If user is logged in, add purchase eligibility info
            if current_user.is_authenticated:
                can_purchase, action_type, message = can_user_purchase_plan(current_user, p)
                plan_dict['canPurchase'] = can_purchase
                plan_dict['actionType'] = action_type
                plan_dict['actionMessage'] = message
            
            plans_data.append(plan_dict)
        
        # Add user's current subscription info
        user_info = None
        if current_user.is_authenticated:
            active_sub = get_user_active_subscription(current_user)
            if active_sub:
                remaining_days = current_user.get_remaining_premium_days()
                user_info = {
                    'isPremium': True,
                    'currentPlanId': active_sub.plan_id,
                    'currentPlanLevel': active_sub.plan.level if active_sub.plan else 0,
                    'currentPlanName': active_sub.plan.name if active_sub.plan else None,
                    'remainingDays': remaining_days,
                    'isLifetime': remaining_days == -1,
                    'endDate': active_sub.end_date.strftime("%Y-%m-%d") if active_sub.end_date else None
                }
        
        return jsonify({
            'plans': plans_data,
            'userSubscription': user_info
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# 创建订阅订单 (支持 Voucher)
# =============================================================================
@payment_bp.route('/create-subscription', methods=['POST'])
@login_required
def create_subscription():
    """
    创建订阅订单
    
    ✅ KEY CHANGES:
    - Plan level check instead of days check
    - Accumulates remaining days on upgrade
    - Does NOT set user.is_premium or user.subscription_end_date
    """
    try:
        data = request.get_json()
        plan_id = data.get('planId')
        plan_type = data.get('planType')
        voucher_code = data.get('voucherCode', '').strip().upper()
        
        # =========================================================
        # Handle Voucher (especially Activation Code)
        # =========================================================
        voucher = None
        if voucher_code:
            voucher = Voucher.query.filter_by(code=voucher_code).first()
            
            if not voucher:
                return jsonify({'error': 'Invalid voucher code'}), 400
            
            can_use, msg = voucher.can_use_by_user(current_user.id)
            if not can_use:
                return jsonify({'error': msg}), 400
                
            # Activation code - use accumulating logic
            if voucher.voucher_type == 'activation':
                return activate_by_voucher(voucher, current_user)

        # =========================================================
        # Normal subscription flow (needs Plan)
        # =========================================================
        
        plan = None
        if plan_id:
            plan = SubscriptionPlan.query.get(plan_id)
        elif plan_type:
            plan = SubscriptionPlan.query.filter_by(slug=plan_type, status='active').first()
        
        if not plan or plan.status != 'active':
            return jsonify({'error': 'Invalid or inactive plan'}), 400
        
        # ✅ Check if user can purchase (by LEVEL, not days)
        can_purchase, action_type, message = can_user_purchase_plan(current_user, plan)
        if not can_purchase:
            return jsonify({
                'error': message,
                'actionType': action_type
            }), 400
        
        # Calculate discount
        original_amount = plan.price
        discount_amount = 0
        
        if voucher:
            if voucher.applicable_plans and plan.id not in voucher.applicable_plans:
                return jsonify({'error': 'Voucher not applicable to this plan'}), 400
            discount_amount = voucher.calculate_discount(original_amount)
        
        final_amount = max(0, original_amount - discount_amount)
        
        # Generate order reference
        timestamp = int(time.time())
        order_reference = f"order_{current_user.id}_{timestamp}"
        
        # Create order (pending status)
        subscription = Subscription(
            user_id=current_user.id,
            order_reference=order_reference,
            plan_id=plan.id,
            plan_type=plan.slug,
            original_amount=original_amount,
            discount_amount=discount_amount,
            amount=final_amount,
            status='pending',
            payment_method='toyyibpay',
            voucher_id=voucher.id if voucher else None
        )
        db.session.add(subscription)
        db.session.commit()
        
        print(f"📝 Order created: {order_reference}, Action: {action_type}, Amount: RM{final_amount}")
        
        # Free subscription (100% discount)
        if final_amount <= 0:
            return complete_subscription(subscription, plan, action_type)
        
        # Create ToyyibPay payment
        amount_sen = int(final_amount * 100)
        
        payload = {
            'userSecretKey': config.TOYYIBPAY_SECRET_KEY,
            'categoryCode': config.TOYYIBPAY_CATEGORY_CODE,
            'billName': f"GogoTrip {plan.name}",
            'billDescription': plan.description or f'{plan.name} subscription',
            'billPriceSetting': 1,
            'billPayorInfo': 1,
            'billAmount': amount_sen,
            'billReturnUrl': f"{config.DOMAIN}/receipt?order_id={order_reference}",
            'billCallbackUrl': f"{config.DOMAIN}/api/payment/toyyib-callback",
            'billExternalReferenceNo': order_reference,
            'billTo': current_user.full_name or "User",
            'billEmail': current_user.email,
            'billPhone': '0123456789',
            'billSplitPayment': 0,
            'billPaymentChannel': '0',
        }
        
        response = requests.post(config.TOYYIBPAY_URL, data=payload)
        response_data = response.json()
        
        if isinstance(response_data, list) and len(response_data) > 0 and 'BillCode' in response_data[0]:
            bill_code = response_data[0]['BillCode']
            payment_url = f"https://dev.toyyibpay.com/{bill_code}"
            
            subscription.bill_code = bill_code
            subscription.payment_url = payment_url
            db.session.commit()
            
            return jsonify({
                'success': True,
                'paymentUrl': payment_url,
                'orderReference': order_reference,
                'billCode': bill_code,
                'amount': final_amount,
                'originalAmount': original_amount,
                'discountAmount': discount_amount,
                'actionType': action_type,
                'expiresIn': Subscription.PENDING_EXPIRY_MINUTES * 60
            })
        else:
            subscription.status = 'failed'
            db.session.commit()
            return jsonify({'error': 'Failed to create payment', 'details': response_data}), 400
            
    except Exception as e:
        print(f"❌ Create subscription error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# 统一的订单完成逻辑 (Core Logic)
# =============================================================================
def complete_subscription(subscription, plan, action_type='purchase'):
    """
    ✅ Complete a subscription (Single Source of Truth)
    
    Handles:
    1. Idempotency check (prevent double processing)
    2. Date calculation (accumulating)
    3. Status updates
    4. Voucher usage recording
    """
    # 🛡️ 1. Idempotency Check (防止并发双写)
    # 如果订单已经是 active，直接返回成功，不做任何数据库变更
    if subscription.status == 'active':
        print(f"⚠️ Order {subscription.order_reference} already active. Skipping processing.")
        return jsonify({
            'success': True,
            'message': 'Subscription already active',
            'subscription': subscription.to_dict(),
            'redirectTo': '/billing?success=true'
        })

    user = User.query.get(subscription.user_id)
    now = datetime.utcnow()
    
    # 2. Calculate end_date with accumulating logic
    if action_type in ['upgrade', 'renew']:
        # Upgrade/Renew: Add new days to remaining days
        new_end_date = calculate_new_end_date(user, plan.duration_days)
    else:
        # New purchase: Start from now
        if plan.duration_days:
            new_end_date = now + timedelta(days=plan.duration_days)
        else:
            new_end_date = None  # Lifetime
    
    # 3. Update subscription
    # ✅ start_date MUST be now to ensure immediate effect (especially for upgrades)
    subscription.status = 'active'
    subscription.payment_date = now
    subscription.start_date = now 
    subscription.end_date = new_end_date
    
    # 4. Record voucher usage (Only once!)
    if subscription.voucher_id:
        voucher = Voucher.query.get(subscription.voucher_id)
        if voucher:
            voucher.current_uses += 1
            if voucher.current_uses >= voucher.max_uses:
                voucher.status = 'exhausted'
            
            usage = VoucherUsage(
                voucher_id=voucher.id,
                user_id=user.id,
                subscription_id=subscription.id,
                usage_type='discount',
                discount_amount=subscription.discount_amount
            )
            db.session.add(usage)
    
    db.session.commit()
    
    print(f"✅ Subscription finalized: {subscription.order_reference}, End: {new_end_date}")
    
    # =================================================================
    # 🔔 TRANSACTIONAL: Create in-app notification + Send email receipt
    # These are ALWAYS sent regardless of user email preferences
    # =================================================================
    try:
        # Create in-app notification
        plan_name = plan.name if plan else 'Premium'
        notif_title = "🎉 Subscription Activated!"
        notif_text = f"Your {plan_name} subscription is now active."
        
        if new_end_date:
            notif_text += f" Valid until {new_end_date.strftime('%Y-%m-%d')}."
        else:
            notif_text += " Enjoy lifetime access!"
        
        notification = Notification(
            user_id=user.id,
            title=notif_title,
            text=notif_text,
            type='success',
            is_broadcast=False
        )
        db.session.add(notification)
        db.session.commit()
        print(f"📬 In-app notification created for user {user.id}")
        
        # Send transactional email (always sent, ignores email preference)
        subject, html_content, text_content = generate_subscription_email_html(
            user_name=user.full_name or 'Valued Customer',
            plan_name=plan_name,
            end_date=new_end_date.strftime('%Y-%m-%d') if new_end_date else None,
            is_lifetime=(new_end_date is None),
            action_type='purchase'
        )
        send_system_email(user.email, subject, html_content, text_content)
        
    except Exception as notif_error:
        # Don't fail the subscription if notification fails
        print(f"⚠️ Notification/email error (non-fatal): {str(notif_error)}")
    
    return jsonify({
        'success': True,
        'message': 'Subscription activated',
        'subscription': subscription.to_dict(),
        'redirectTo': '/billing?success=true'
    })

def activate_by_voucher(voucher, user):
    """
    ✅ Activation code logic with TIME ACCUMULATION
    
    KEY RULE:
    new_end_date = max(current_end_date, now) + activation_days
    
    This ensures:
    - 3020 days + 300 day code = 3320 days
    - Expired user + 300 day code = now + 300 days
    
    ❌ Does NOT set user.is_premium or user.subscription_end_date
    """
    timestamp = int(time.time())
    order_reference = f"activation_{user.id}_{timestamp}"
    
    now = datetime.utcnow()
    
    # ✅ CORRECT: Calculate end_date with accumulation
    new_end_date = calculate_new_end_date(user, voucher.activation_days)
    
    # Check if user already has an active subscription to extend
    active_sub = get_user_active_subscription(user)
    
    if active_sub and active_sub.end_date:
        # Extend existing subscription
        active_sub.end_date = new_end_date
        active_sub.notes = (active_sub.notes or '') + f"\n[{now.strftime('%Y-%m-%d')}] Extended by code: {voucher.code} (+{voucher.activation_days} days)"
        
        subscription = active_sub  # Reference for response
        
        print(f"✅ Extended existing subscription {active_sub.id} to {new_end_date}")
    else:
        # Create new subscription record
        # Use the activation plan or create a default one
        plan_id = voucher.activation_plan_id
        plan_type = 'activation'
        
        if plan_id:
            plan = SubscriptionPlan.query.get(plan_id)
            if plan:
                plan_type = plan.slug
        
        subscription = Subscription(
            user_id=user.id,
            order_reference=order_reference,
            plan_id=plan_id,
            plan_type=plan_type,
            original_amount=0,
            discount_amount=0,
            amount=0,
            status='active',  # ✅ Use 'active' for premium checks
            payment_method='activation_code',
            payment_date=now,
            start_date=now,
            end_date=new_end_date,
            voucher_id=voucher.id,
            notes=f'Activated by code: {voucher.code}'
        )
        db.session.add(subscription)
    
    # ❌ REMOVED: user.is_premium = True
    # ❌ REMOVED: user.subscription_end_date = new_end_date
    
    # Update voucher usage
    voucher.current_uses += 1
    if voucher.current_uses >= voucher.max_uses:
        voucher.status = 'exhausted'
    
    # Record usage
    usage = VoucherUsage(
        voucher_id=voucher.id,
        user_id=user.id,
        subscription_id=subscription.id,
        usage_type='activation'
    )
    db.session.add(usage)
    
    db.session.commit()
    
    print(f"✅ User {user.id} activated by code: {voucher.code}, End: {new_end_date}")
    
    # =================================================================
    # 🔔 TRANSACTIONAL: Create in-app notification + Send email receipt
    # These are ALWAYS sent regardless of user email preferences
    # =================================================================
    try:
        # Determine plan name
        plan_name = 'Premium'
        if voucher.activation_plan_id:
            plan = SubscriptionPlan.query.get(voucher.activation_plan_id)
            if plan:
                plan_name = plan.name
        
        # Create in-app notification
        notif_title = "🎉 Premium Activated!"
        if new_end_date:
            notif_text = f"Your {plan_name} subscription is now active until {new_end_date.strftime('%Y-%m-%d')}."
        else:
            notif_text = f"Your {plan_name} lifetime subscription is now active!"
        
        notification = Notification(
            user_id=user.id,
            title=notif_title,
            text=notif_text,
            type='success',
            is_broadcast=False
        )
        db.session.add(notification)
        db.session.commit()
        print(f"📬 In-app notification created for user {user.id}")
        
        # Send transactional email (always sent, ignores email preference)
        subject, html_content, text_content = generate_subscription_email_html(
            user_name=user.full_name or 'Valued Customer',
            plan_name=plan_name,
            end_date=new_end_date.strftime('%Y-%m-%d') if new_end_date else None,
            is_lifetime=(new_end_date is None),
            action_type='purchase'
        )
        send_system_email(user.email, subject, html_content, text_content)
        
    except Exception as notif_error:
        # Don't fail the activation if notification fails
        print(f"⚠️ Notification/email error (non-fatal): {str(notif_error)}")
    
    return jsonify({
        'success': True,
        'activated': True,
        'message': 'Premium membership activated!',
        'subscription': subscription.to_dict(),
        'endDate': new_end_date.strftime("%Y-%m-%d") if new_end_date else 'Lifetime',
        'redirectTo': '/billing?activated=true'
    })

# =============================================================================
# ToyyibPay Callback
# =============================================================================
@payment_bp.route('/toyyib-callback', methods=['POST'])
def toyyib_callback():
    """
    ToyyibPay payment callback
    ✅ REFACTORED: Now uses complete_subscription to ensure single logic path
    """
    try:
        bill_code = request.form.get('billcode')
        order_reference = request.form.get('billExternalReferenceNo')
        status_id = request.form.get('billpaymentStatus')
        
        print(f"📨 ToyyibPay callback: {order_reference}, Status: {status_id}")
        
        subscription = Subscription.query.filter_by(order_reference=order_reference).first()
        
        if not subscription:
            print(f"❌ Order not found: {order_reference}")
            return 'Order not found', 404
        
        if status_id == '1':  # Payment success
            # Check if already processed to save DB hits
            if subscription.status == 'active':
                return 'OK', 200

            user = User.query.get(subscription.user_id)
            plan = subscription.plan or SubscriptionPlan.query.filter_by(slug=subscription.plan_type).first()
            
            if user and plan:
                # Calculate action type needed for complete_subscription
                _, action_type, _ = can_user_purchase_plan(user, plan)
                
                # ✅ Call the shared finalize function
                # We ignore the JSON return value here, just need the side effects
                complete_subscription(subscription, plan, action_type)
        
        elif status_id == '3':  # Payment failed
            if subscription.status == 'pending':
                subscription.status = 'failed'
                db.session.commit()
                print(f"❌ Payment failed: {order_reference}")
        
        return 'OK', 200
        
    except Exception as e:
        print(f"❌ Callback error: {str(e)}")
        # ToyyibPay expects 200 OK even if we error internally to stop retrying
        return 'Error', 200 

# =============================================================================
# Verify Order Manual (Receipt page)
# =============================================================================
@payment_bp.route('/verify-order/<order_reference>', methods=['POST'])
@login_required
def verify_order_manual(order_reference):
    """
    Manual order verification
    ✅ USES SHARED LOGIC
    """
    try:
        subscription = Subscription.query.filter_by(
            order_reference=order_reference
        ).first()
        
        if not subscription:
            return jsonify({'error': 'Order not found'}), 404
        
        if subscription.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Fast return if already active (Front-end will see success)
        if subscription.status == 'active':
            return jsonify({
                'success': True,
                'message': 'Order already verified',
                'order': subscription.to_dict()
            })
        
        if subscription.bill_code:
            try:
                # Double check with ToyyibPay API
                url = "https://dev.toyyibpay.com/index.php/api/getBillTransactions"
                payload = {
                    'billCode': subscription.bill_code,
                    'billpaymentStatus': '1'
                }
                
                response = requests.post(url, data=payload)
                transactions = response.json()
                
                if isinstance(transactions, list) and len(transactions) > 0:
                    plan = subscription.plan or SubscriptionPlan.query.filter_by(slug=subscription.plan_type).first()
                    action_type = 'purchase'
                    if plan:
                        _, action_type, _ = can_user_purchase_plan(current_user, plan)
                    
                    # ✅ Call the shared finalize function
                    return complete_subscription(subscription, plan, action_type)
                    
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Payment not completed yet',
                        'status': 'pending'
                    })
                    
            except Exception as query_error:
                print(f"❌ ToyyibPay query error: {str(query_error)}")
                return jsonify({'success': False, 'error': 'Failed to verify payment status'}), 500
        else:
            return jsonify({'success': False, 'error': 'Bill code not found'}), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# Subscription Status
# =============================================================================
@payment_bp.route('/subscription-status', methods=['GET'])
@login_required
def get_subscription_status():
    """Get current user's subscription status"""
    try:
        # Get active subscription from Subscription table (Single Source of Truth)
        active_sub = get_user_active_subscription(current_user)
        
        # Get pending order
        pending_order = Subscription.query.filter_by(
            user_id=current_user.id,
            status='pending'
        ).order_by(Subscription.created_at.desc()).first()
        
        pending_info = None
        if pending_order and not pending_order.is_pending_expired():
            pending_info = {
                'orderReference': pending_order.order_reference,
                'amount': pending_order.amount,
                'remainingTime': pending_order.get_remaining_payment_time(),
                'paymentUrl': pending_order.payment_url
            }
        
        # ✅ Use Subscription table as single source of truth
        end_date = active_sub.end_date if active_sub else None
        
        return jsonify({
            'isPremium': current_user.is_premium_active,  # From Subscription table
            'subscriptionEndDate': end_date.strftime("%Y-%m-%d") if end_date else None,
            'isLifetime': active_sub.end_date is None if active_sub else False,
            'remainingDays': current_user.get_remaining_premium_days(),
            'currentPlanLevel': current_user.get_current_plan_level(),
            'currentSubscription': active_sub.to_dict() if active_sub else None,
            'pendingOrder': pending_info
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Validate Voucher
# =============================================================================
@payment_bp.route('/validate-voucher', methods=['POST'])
@login_required
def validate_voucher():
    """Validate voucher code"""
    try:
        data = request.get_json()
        code = data.get('code', '').upper().strip()
        plan_id = data.get('planId')
        
        if not code:
            return jsonify({'valid': False, 'error': 'Code is required'}), 400
        
        voucher = Voucher.query.filter_by(code=code).first()
        
        if not voucher:
            return jsonify({'valid': False, 'error': 'Invalid voucher code'}), 400
        
        can_use, msg = voucher.can_use_by_user(current_user.id)
        if not can_use:
            return jsonify({'valid': False, 'error': msg}), 400
        
        if voucher.applicable_plans and plan_id and plan_id not in voucher.applicable_plans:
            return jsonify({'valid': False, 'error': 'Voucher not applicable to this plan'}), 400
        
        # Calculate discount preview
        preview = None
        if voucher.voucher_type == 'discount' and plan_id:
            plan = SubscriptionPlan.query.get(plan_id)
            if plan:
                discount = voucher.calculate_discount(plan.price)
                preview = {
                    'originalPrice': plan.price,
                    'discount': discount,
                    'finalPrice': max(0, plan.price - discount)
                }
        
        # For activation codes, show time accumulation preview
        activation_preview = None
        if voucher.voucher_type == 'activation':
            current_remaining = current_user.get_remaining_premium_days()
            if voucher.activation_days:
                if current_remaining > 0:
                    new_total = current_remaining + voucher.activation_days
                else:
                    new_total = voucher.activation_days
                activation_preview = {
                    'currentDays': max(0, current_remaining),
                    'addedDays': voucher.activation_days,
                    'newTotalDays': new_total,
                    'isLifetime': False
                }
            else:
                activation_preview = {
                    'currentDays': max(0, current_remaining),
                    'addedDays': None,
                    'newTotalDays': None,
                    'isLifetime': True
                }
        
        return jsonify({
            'valid': True,
            'voucher': {
                'code': voucher.code,
                'name': voucher.name,
                'type': voucher.voucher_type,
                'discountType': voucher.discount_type,
                'discountValue': voucher.discount_value,
                'activationDays': voucher.activation_days,
                'description': voucher.description
            },
            'preview': preview,
            'activationPreview': activation_preview
        })
        
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)}), 500


# =============================================================================
# Get Transactions
# =============================================================================
@payment_bp.route('/transactions', methods=['GET'])
@login_required
def get_transactions():
    """Get user's transaction history"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('status')
        
        query = Subscription.query.filter_by(user_id=current_user.id)
        
        if status_filter and status_filter != 'all':
            query = query.filter_by(status=status_filter)
        
        pagination = query.order_by(Subscription.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        transactions = []
        for sub in pagination.items:
            sub.auto_cancel_if_expired()
            transactions.append(sub.to_dict())
        
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
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Continue Payment
# =============================================================================
@payment_bp.route('/continue-payment/<order_reference>', methods=['GET'])
@login_required
def continue_payment(order_reference):
    """
    Continue incomplete payment

    ✅ FIXED: Prevent reusing ToyyibPay payment URLs
    - ToyyibPay payment sessions end when user exits the payment page
    - Reusing the same BillCode results in "Please wait 10 minutes" error
    - Solution: Block Continue Payment, force user to create new payment
    """
    try:
        subscription = Subscription.query.filter_by(
            order_reference=order_reference,
            user_id=current_user.id
        ).first()

        if not subscription:
            return jsonify({'error': 'Order not found'}), 404

        # ✅ FIX: If payment_url exists, user already opened payment page once
        # Don't allow reuse - ToyyibPay will reject it
        if subscription.payment_url and subscription.status == 'pending':
            subscription.status = 'expired'
            subscription.expired_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'error': 'Previous payment session has ended. Please create a new payment.',
                'reason': 'payment_url_reuse_blocked',
                'status': 'expired'
            }), 400

        if subscription.is_pending_expired():
            subscription.status = 'expired'
            subscription.expired_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'error': 'Order has expired. Please create a new order.',
                'status': 'expired'
            }), 400

        if subscription.status != 'pending':
            return jsonify({
                'error': f'Cannot continue payment for order with status: {subscription.status}'
            }), 400

        if not subscription.payment_url:
            return jsonify({'error': 'Payment URL not available'}), 400

        # This code path should never be reached now due to the fix above
        # Kept for backwards compatibility
        return jsonify({
            'success': True,
            'paymentUrl': subscription.payment_url,
            'order': subscription.to_dict(),
            'remainingTime': subscription.get_remaining_payment_time()
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Cancel Order
# =============================================================================
@payment_bp.route('/cancel-order/<order_reference>', methods=['POST'])
@login_required
def cancel_order(order_reference):
    """Cancel pending order"""
    try:
        subscription = Subscription.query.filter_by(
            order_reference=order_reference
        ).first()
        
        if not subscription:
            return jsonify({'error': 'Order not found'}), 404
        
        if subscription.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        if subscription.status != 'pending':
            return jsonify({
                'error': f'Cannot cancel order with status: {subscription.status}'
            }), 400
        
        subscription.status = 'cancelled'
        subscription.cancelled_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Order cancelled successfully',
            'order': subscription.to_dict()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Get Order Details
# =============================================================================
@payment_bp.route('/order/<order_reference>', methods=['GET'])
@login_required
def get_order_details(order_reference):
    """Get order details"""
    try:
        subscription = Subscription.query.filter_by(
            order_reference=order_reference
        ).first()
        
        if not subscription:
            return jsonify({'error': 'Order not found'}), 404
        
        if subscription.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        subscription.auto_cancel_if_expired()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'order': subscription.to_dict(),
            'plan': subscription.plan.to_dict() if subscription.plan else None,
            'user': {
                'name': current_user.full_name,
                'email': current_user.email
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Legacy compatibility
# =============================================================================
@payment_bp.route('/subscription-history', methods=['GET'])
@login_required
def get_subscription_history():
    """Get user's subscription history (legacy compatibility)"""
    return get_transactions()