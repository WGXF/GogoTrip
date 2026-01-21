# admin.py - COMPLETE VERSION WITH ROLE-BASED PERMISSIONS
"""
Admin API routes for managing users, places, trips, and all data
Provides complete admin functionality for the GogoTrip platform

UPDATES:
1. Standardized role enum: super_admin | admin | user
2. Role-based user visibility:
   - super_admin: Can view ALL users (including admin/super_admin)
   - admin: Can ONLY view users with role='user'
3. Role modification restrictions based on current admin's role
4. ALL original functions preserved
"""
import random
import string
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from functools import wraps
from utils import send_temp_password_email
from models import db, User, SchedulerItem, Expense, Trip, TripItem, Place, Subscription, Article, EmailVerification, Notification, CalendarEvent
from datetime import datetime, timedelta
from sqlalchemy import func, extract


admin_bp = Blueprint('admin_api', __name__)

# ----------------------
# 🔥 STANDARDIZED ROLE ENUM
# ----------------------
class UserRole:
    """Standardized role values - use these constants everywhere"""
    SUPER_ADMIN = 'super_admin'
    ADMIN = 'admin'
    USER = 'user'
    
    # All valid roles
    ALL_ROLES = [SUPER_ADMIN, ADMIN, USER]
    
    # Roles that have admin panel access
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


# ----------------------
# 🔥 UPDATED: Admin Authorization Decorator
# ----------------------
def admin_required(f):
    """
    Require admin access for protected routes
    Supports multiple admin role names for flexibility
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Login required'}), 401
        
        # 🔥 Use standardized role check with legacy support
        if not UserRole.is_admin(current_user.role):
            # Also check legacy role names for backward compatibility
            allowed_admin_roles = ['Admin', 'super_admin', 'Administrator', 'admin']
            if current_user.role not in allowed_admin_roles:
                return jsonify({
                    'error': 'Admin access required',
                    'current_role': current_user.role
                }), 403
        
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    """
    Require super_admin access for sensitive operations
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Login required'}), 401
        
        if not UserRole.is_super_admin(current_user.role):
            return jsonify({
                'error': 'Super Admin access required',
                'current_role': current_user.role
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function


# ==========================================
# 👥 USER MANAGEMENT - WITH ROLE-BASED FILTERING
# ==========================================

@admin_bp.route('/users', methods=['GET'])
@login_required
@admin_required
def get_all_users():
    """
    Get list of users with ROLE-BASED FILTERING
    
    Permission Logic:
    - super_admin: Can see ALL users (including other admins)
    - admin: Can ONLY see users with role='user'
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '')
        status = request.args.get('status', '')
        include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'
        
        # Get current admin's normalized role
        current_admin_role = UserRole.normalize(current_user.role)
        
        query = User.query
        
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
                    # Also exclude legacy role names
                    'Administrator',
                    'Admin'
                ])
            )
        
        # Exclude soft-deleted users by default
        if not include_deleted:
            query = query.filter(User.status != 'deleted')
        
        # Search filter
        if search:
            query = query.filter(
                (User.email.ilike(f'%{search}%')) |
                (User.full_name.ilike(f'%{search}%'))
            )
        
        # Status filter
        if status:
            query = query.filter_by(status=status)
        
        query = query.order_by(User.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        users = pagination.items
        
        users_data = []
        for user in users:
            user_dict = user.to_dict()
            # Normalize the role in response
            user_dict['role'] = UserRole.normalize(user.role)
            user_dict['notesCount'] = SchedulerItem.query.filter_by(user_id=user.id).count()
            user_dict['expensesCount'] = Expense.query.filter_by(user_id=user.id).count()
            user_dict['tripsCount'] = Trip.query.filter_by(user_id=user.id).count()
            user_dict['subscriptionsCount'] = Subscription.query.filter_by(user_id=user.id).count()
            user_dict['calendarEventsCount'] = CalendarEvent.query.filter_by(user_id=user.id).count()
            users_data.append(user_dict)
        
        return jsonify({
            'users': users_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            },
            # 🔥 Include current admin's permission level for frontend
            'currentAdminRole': current_admin_role,
            'canManageAdmins': current_admin_role == UserRole.SUPER_ADMIN
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==========================================
# 🔥 UPDATED: User Resource Handler with Role Checks
# ==========================================
@admin_bp.route('/users/<int:user_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def handle_user_resource(user_id):
    """Handle get, update, and delete operations for a single user"""
    try:
        user = User.query.get_or_404(user_id)
        current_admin_role = UserRole.normalize(current_user.role)
        target_user_role = UserRole.normalize(user.role)

        # 🔥 PERMISSION CHECK: Regular admin cannot access admin/super_admin users
        if current_admin_role == UserRole.ADMIN:
            if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({
                    'error': 'Permission denied: You cannot access admin users',
                    'required_role': 'super_admin'
                }), 403

        # 1. GET Request - Get user details
        if request.method == 'GET':
            user_dict = user.to_dict()
            user_dict['role'] = target_user_role  # Normalized role
            user_dict['relatedData'] = get_user_related_data_summary(user)
            return jsonify(user_dict), 200

        # 2. PUT Request - Update user
        if request.method == 'PUT':
            data = request.get_json()
            
            # Email update
            if 'email' in data:
                existing = User.query.filter(User.email == data['email'], User.id != user_id).first()
                if existing:
                    return jsonify({'error': 'Email already in use by another user'}), 400
                user.email = data['email']
            
            # 🔥 ROLE UPDATE with permission check
            if 'role' in data:
                new_role = UserRole.normalize(data['role'])
                
                # Regular admin cannot promote users to admin roles
                if current_admin_role == UserRole.ADMIN:
                    if new_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                        return jsonify({
                            'error': 'Permission denied: Only super_admin can assign admin roles'
                        }), 403
                
                # Only super_admin can create other super_admins
                if new_role == UserRole.SUPER_ADMIN:
                    if current_admin_role != UserRole.SUPER_ADMIN:
                        return jsonify({
                            'error': 'Permission denied: Only super_admin can create super_admin users'
                        }), 403
                
                user.role = new_role
            
            # Status update
            if 'status' in data:
                user.status = data['status']
                if data['status'] == 'active':
                    user.is_email_verified = True
            
            if 'name' in data:
                user.full_name = data['name']
            
            user.updated_at = datetime.utcnow()
            db.session.commit()
            
            response_dict = user.to_dict()
            response_dict['role'] = UserRole.normalize(user.role)
            return jsonify(response_dict), 200

        # 3. DELETE Request
        if request.method == 'DELETE':
            # 🔥 Cannot delete users with higher or equal admin privilege
            if target_user_role == UserRole.SUPER_ADMIN:
                if current_admin_role != UserRole.SUPER_ADMIN:
                    return jsonify({
                        'error': 'Permission denied: Cannot delete super_admin users'
                    }), 403
            
            if target_user_role == UserRole.ADMIN:
                if current_admin_role != UserRole.SUPER_ADMIN:
                    return jsonify({
                        'error': 'Permission denied: Only super_admin can delete admin users'
                    }), 403
            
            return delete_user_handler(user)

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


def get_user_related_data_summary(user):
    """
    Get summary of user's related data
    Used to warn admin before deletion
    """
    return {
        'trips': Trip.query.filter_by(user_id=user.id).count(),
        'expenses': Expense.query.filter_by(user_id=user.id).count(),
        'notes': SchedulerItem.query.filter_by(user_id=user.id).count(),
        'subscriptions': Subscription.query.filter_by(user_id=user.id).count(),
        'calendarEvents': CalendarEvent.query.filter_by(user_id=user.id).count(),
        'notifications': Notification.query.filter_by(user_id=user.id).count(),
    }


def delete_user_handler(user):
    """
    Proper user deletion with cascade support
    
    Query params:
    - mode: 'soft' (default) or 'hard'
    - force: 'true' to skip confirmation for users with data
    """
    # Prevent self-deletion
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    # Get delete mode from query params
    delete_mode = request.args.get('mode', 'soft')
    force = request.args.get('force', 'false').lower() == 'true'
    
    # Get related data summary
    related_data = get_user_related_data_summary(user)
    total_related = sum(related_data.values())
    has_data = total_related > 0
    
    email = user.email
    
    # =============================================
    # SOFT DELETE (Recommended - preserves data)
    # =============================================
    if delete_mode == 'soft':
        user.status = 'deleted'
        user.updated_at = datetime.utcnow()
        # Clear sensitive tokens
        user.google_access_token = None
        user.google_refresh_token = None
        user.google_token_expiry = None
        
        db.session.commit()
        
        return jsonify({
            'message': f'User {email} has been soft deleted',
            'mode': 'soft',
            'relatedDataPreserved': True,
            'relatedData': related_data
        }), 200
    
    # =============================================
    # HARD DELETE (Permanent - deletes all data)
    # =============================================
    else:
        # If user has data and force is not set, return warning
        if has_data and not force:
            return jsonify({
                'error': 'User has related data',
                'requiresConfirmation': True,
                'relatedData': related_data,
                'totalRelatedRecords': total_related,
                'message': f'This user has {total_related} related records. Add ?force=true to confirm permanent deletion, or use ?mode=soft for soft delete.'
            }), 409  # 409 Conflict
        
        try:
            # Manually delete related data in correct order
            # This ensures deletion works even if cascade isn't set up in DB
            
            # 1. Delete calendar events
            CalendarEvent.query.filter_by(user_id=user.id).delete()
            
            # 2. Delete notifications  
            Notification.query.filter_by(user_id=user.id).delete()
            
            # 3. Delete scheduler items (notes)
            SchedulerItem.query.filter_by(user_id=user.id).delete()
            
            # 4. Delete expenses (both user-level and trip-level will be handled)
            Expense.query.filter_by(user_id=user.id).delete()
            
            # 5. Delete trip items first (child of trips)
            user_trip_ids = [t.id for t in Trip.query.filter_by(user_id=user.id).all()]
            if user_trip_ids:
                TripItem.query.filter(TripItem.trip_id.in_(user_trip_ids)).delete(synchronize_session=False)
            
            # 6. Delete trips
            Trip.query.filter_by(user_id=user.id).delete()
            
            # 7. Delete subscriptions
            Subscription.query.filter_by(user_id=user.id).delete()
            
            # 8. Finally delete the user
            db.session.delete(user)
            db.session.commit()
            
            return jsonify({
                'message': f'User {email} and all related data have been permanently deleted',
                'mode': 'hard',
                'deletedRelatedData': related_data
            }), 200
            
        except Exception as delete_error:
            db.session.rollback()
            print(f"Hard delete failed for user {user.id}: {delete_error}")
            
            # Provide helpful error message
            return jsonify({
                'error': 'Failed to delete user',
                'details': str(delete_error),
                'suggestion': 'Try using soft delete (?mode=soft) instead, or contact system administrator.',
                'relatedData': related_data
            }), 500


# ==========================================
# 🔥 NEW: Get available roles for current admin
# ==========================================
@admin_bp.route('/available-roles', methods=['GET'])
@login_required
@admin_required
def get_available_roles():
    """
    Return list of roles the current admin can assign
    
    - super_admin: Can assign all roles
    - admin: Can only assign 'user' role
    """
    current_admin_role = UserRole.normalize(current_user.role)
    
    if current_admin_role == UserRole.SUPER_ADMIN:
        available_roles = [
            {'value': UserRole.USER, 'label': 'User', 'description': 'Regular user'},
            {'value': UserRole.ADMIN, 'label': 'Admin', 'description': 'Can manage users'},
            {'value': UserRole.SUPER_ADMIN, 'label': 'Super Admin', 'description': 'Full access'}
        ]
    else:
        available_roles = [
            {'value': UserRole.USER, 'label': 'User', 'description': 'Regular user'}
        ]
    
    return jsonify({
        'currentRole': current_admin_role,
        'availableRoles': available_roles,
        'canManageAdmins': current_admin_role == UserRole.SUPER_ADMIN
    }), 200


# ==========================================
# 🔥 NEW: Get user related data before delete
# ==========================================
@admin_bp.route('/users/<int:user_id>/related-data', methods=['GET'])
@login_required
@admin_required
def get_user_related_data(user_id):
    """Get summary of user's related data (useful before deletion)"""
    try:
        user = User.query.get_or_404(user_id)
        related_data = get_user_related_data_summary(user)
        
        return jsonify({
            'userId': user_id,
            'email': user.email,
            'relatedData': related_data,
            'totalRelatedRecords': sum(related_data.values()),
            'hasRelatedData': sum(related_data.values()) > 0
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==========================================
# 🔥 Suspend user
# ==========================================
@admin_bp.route('/users/<int:user_id>/suspend', methods=['POST'])
@login_required
@admin_required
def suspend_user(user_id):
    """Suspend a user account"""
    try:
        user = User.query.get_or_404(user_id)
        current_admin_role = UserRole.normalize(current_user.role)
        target_user_role = UserRole.normalize(user.role)
        
        # Permission check
        if current_admin_role == UserRole.ADMIN:
            if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({'error': 'Permission denied: Cannot suspend admin users'}), 403
        
        if user.id == current_user.id:
            return jsonify({'error': 'Cannot suspend your own account'}), 400
        
        user.status = 'suspended'
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': f'User {user.email} has been suspended',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# 🔥 Reactivate user
# ==========================================
@admin_bp.route('/users/<int:user_id>/reactivate', methods=['POST'])
@login_required
@admin_required
def reactivate_user(user_id):
    """Reactivate a suspended or soft-deleted user"""
    try:
        user = User.query.get_or_404(user_id)
        current_admin_role = UserRole.normalize(current_user.role)
        target_user_role = UserRole.normalize(user.role)
        
        # Permission check
        if current_admin_role == UserRole.ADMIN:
            if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({'error': 'Permission denied: Cannot reactivate admin users'}), 403
        
        if user.status == 'active':
            return jsonify({'error': 'User is already active'}), 400
        
        # Reactivate based on verification status
        if user.is_email_verified:
            user.status = 'active'
        else:
            user.status = 'pending_verification'
        
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': f'User {user.email} has been reactivated',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# Create user with role restrictions
# ==========================================
@admin_bp.route('/users', methods=['POST'])
@login_required
@admin_required
def create_user():
    """Create a new user with role restrictions"""
    try:
        data = request.get_json()
        current_admin_role = UserRole.normalize(current_user.role)
        
        email = data.get('email')
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Check if email already exists
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already exists'}), 400
        
        # Normalize and validate role
        requested_role = data.get('role', 'User')
        
        # Legacy role handling
        ALLOWED_ROLES = ['User', 'Admin', 'user', 'admin', 'super_admin']
        if requested_role not in ALLOWED_ROLES:
            requested_role = 'user'
        
        # Normalize the role
        requested_role = UserRole.normalize(requested_role)
        
        # 🔥 ROLE ASSIGNMENT RESTRICTIONS
        if current_admin_role == UserRole.ADMIN:
            # Regular admin can only create normal users
            if requested_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({
                    'error': 'Permission denied: Only super_admin can create admin users'
                }), 403
            requested_role = UserRole.USER
        
        # Only super_admin can create super_admin
        if requested_role == UserRole.SUPER_ADMIN:
            if current_admin_role != UserRole.SUPER_ADMIN:
                return jsonify({
                    'error': 'Permission denied: Only super_admin can create super_admin users'
                }), 403
        
        status = data.get('status', 'active')
        
        # Generate temporary password
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        
        new_user = User(
            email=email,
            full_name=email.split('@')[0],
            role=requested_role,
            status=status,
            password_hash=generate_password_hash(temp_password),
            is_email_verified=True,
            created_at=datetime.utcnow()
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        # Send temp password email
        email_sent = False
        try:
            email_sent = send_temp_password_email(email, temp_password)
        except Exception as e:
            print(f"Failed to send temp password email: {e}")
        
        response_dict = new_user.to_dict()
        response_dict['role'] = requested_role
        response_dict['message'] = 'User created successfully'
        response_dict['email_sent'] = email_sent
        
        return jsonify(response_dict), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# Update user status
# ==========================================
@admin_bp.route('/users/<int:user_id>/status', methods=['PUT'])
@login_required
@admin_required
def update_user_status(user_id):
    """Update user status"""
    try:
        user = User.query.get_or_404(user_id)
        current_admin_role = UserRole.normalize(current_user.role)
        target_user_role = UserRole.normalize(user.role)
        
        # Permission check
        if current_admin_role == UserRole.ADMIN:
            if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({'error': 'Permission denied: Cannot modify admin user status'}), 403
        
        data = request.get_json()
        
        new_status = data.get('status')
        if new_status not in ['active', 'suspended', 'pending_verification', 'deleted']:
            return jsonify({'error': 'Invalid status'}), 400
        
        user.status = new_status
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'User status updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# Resend verification email
# ==========================================
@admin_bp.route('/users/<int:user_id>/resend-verification', methods=['POST'])
@login_required
@admin_required
def resend_verification_email(user_id):
    """Resend verification email to user"""
    try:
        user = User.query.get_or_404(user_id)
        
        if user.status != 'pending_verification':
            return jsonify({'error': 'User is already verified'}), 400
        
        # Implementation would send verification email
        return jsonify({'message': f'Verification email sent to {user.email}'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==========================================
# 🏢 PLACES MANAGEMENT
# ==========================================

@admin_bp.route('/places', methods=['GET'])
@login_required
@admin_required
def get_places():
    search = request.args.get('search', '')
    query = Place.query

    if search:
        query = query.filter(
            Place.name.ilike(f'%{search}%') |
            Place.address.ilike(f'%{search}%')
        )
    
    places = query.order_by(Place.cached_at.desc()).limit(200).all()
    
    results = []
    for p in places:
        results.append({
            'id': p.id,
            'google_place_id': p.google_place_id,
            'name': p.name,
            'address': p.address,
            'rating': p.rating,
            'business_status': p.business_status,
            'phone': p.phone,
            'cached_at': p.cached_at.strftime("%Y-%m-%d %H:%M") if p.cached_at else None
        })
    
    return jsonify(results)


@admin_bp.route('/places/<int:place_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_place(place_id):
    place = Place.query.get_or_404(place_id)
    try:
        db.session.delete(place)
        db.session.commit()
        return jsonify({"message": "Place deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==========================================
# ✈️ TRIPS MANAGEMENT
# ==========================================

@admin_bp.route('/trips', methods=['GET'])
@login_required
@admin_required
def get_trips():
    search = request.args.get('search', '')
    query = Trip.query.join(User)

    if search:
        query = query.filter(
            Trip.title.ilike(f'%{search}%') | 
            User.email.ilike(f'%{search}%')
        )
    
    trips = query.order_by(Trip.created_at.desc()).all()
    
    results = []
    for t in trips:
        t_dict = t.to_dict()
        t_dict['user_email'] = t.user.email if t.user else "Unknown"
        t_dict['destination'] = t.destination
        t_dict['items_count'] = TripItem.query.filter_by(trip_id=t.id).count()
        results.append(t_dict)
    
    return jsonify(results)


@admin_bp.route('/trips/<int:trip_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    try:
        # Delete trip items first
        TripItem.query.filter_by(trip_id=trip_id).delete()
        # Delete expenses associated with trip
        Expense.query.filter_by(trip_id=trip_id).delete()
        # Delete the trip
        db.session.delete(trip)
        db.session.commit()
        return jsonify({"message": "Trip deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/trip_items', methods=['GET'])
def get_trip_items():
    trip_id = request.args.get('trip_id', '')
    
    query = TripItem.query
    if trip_id:
        query = query.filter_by(trip_id=trip_id)
    
    items = query.order_by(TripItem.id.desc()).limit(200).all()
    
    results = []
    for item in items:
        i_dict = item.to_dict()
        i_dict['place_name'] = item.place.name if item.place else "Unknown"
        i_dict['type'] = item.type
        i_dict['status'] = item.status
        results.append(i_dict)
        
    return jsonify(results)


@admin_bp.route('/trip_items/<int:item_id>', methods=['DELETE'])
def delete_trip_item(item_id):
    item = TripItem.query.get_or_404(item_id)
    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Trip item deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==========================================
# 💰 SUBSCRIPTIONS MANAGEMENT
# ==========================================

@admin_bp.route('/subscriptions', methods=['GET'])
@login_required
@admin_required
def get_subscriptions():
    """Get all subscriptions"""
    try:
        subscriptions = Subscription.query.order_by(Subscription.created_at.desc()).all()
        
        results = []
        for sub in subscriptions:
            sub_dict = sub.to_dict()
            user = User.query.get(sub.user_id)
            sub_dict['user_email'] = user.email if user else "Unknown"
            results.append(sub_dict)
        
        return jsonify(results), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/subscriptions/<int:sub_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_subscription(sub_id):
    """Delete a subscription"""
    try:
        subscription = Subscription.query.get_or_404(sub_id)
        
        # Update user's premium status if needed
        user = User.query.get(subscription.user_id)
        if user:
            # Check if user has other active subscriptions
            other_active = Subscription.query.filter(
                Subscription.user_id == user.id,
                Subscription.id != sub_id,
                Subscription.status == 'paid',
                Subscription.end_date > datetime.utcnow()
            ).first()
            
            if not other_active:
                user.is_premium = False
                user.subscription_end_date = None
        
        db.session.delete(subscription)
        db.session.commit()
        
        return jsonify({'message': 'Subscription deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# 📧 EMAIL VERIFICATIONS
# ==========================================

@admin_bp.route('/email_verifications', methods=['GET'])
@login_required
@admin_required
def get_email_verifications():
    """Get all email verifications"""
    try:
        verifications = EmailVerification.query.order_by(
            EmailVerification.created_at.desc()
        ).limit(100).all()
        
        verifications_data = []
        for v in verifications:
            # EmailVerification uses email as primary key, not user_id
            user = User.query.filter_by(email=v.email).first()
            
            verifications_data.append({
                'id': v.email,  # Using email as ID since it's the primary key
                'email': v.email,
                'user_email': v.email,
                'user_exists': user is not None,
                'user_status': user.status if user else None,
                'code': v.code,
                'expires_at': v.expires_at.strftime('%Y-%m-%d %H:%M') if v.expires_at else None,
                'created_at': v.created_at.strftime('%Y-%m-%d %H:%M') if v.created_at else None
            })
        
        return jsonify(verifications_data), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==========================================
# 📊 DASHBOARD STATS
# ==========================================

@admin_bp.route('/dashboard-stats', methods=['GET'])
@login_required
@admin_required
def get_dashboard_stats():
    """Get admin dashboard statistics"""
    try:
        # Get time range from query params
        time_range = request.args.get('range', 'Last 12 Months')

        current_admin_role = UserRole.normalize(current_user.role)

        # Base query - filter by permission
        if current_admin_role == UserRole.SUPER_ADMIN:
            user_query = User.query
        else:
            # Admin can only see stats for normal users
            user_query = User.query.filter(
                ~User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN, 'Administrator', 'Admin'])
            )
        
        # 1. Total users (excluding soft-deleted)
        total_users = user_query.filter(User.status != 'deleted').count()
        
        # 2. Verified users count
        verified_users = user_query.filter(
            User.is_email_verified == True,
            User.status != 'deleted'
        ).count()
        
        # 3. Total trips count
        total_trips = Trip.query.count()
        
        # 4. Published articles count
        total_articles = Article.query.filter_by(status='Published').count()
        
        # 5. Active subscriptions count (premium users)
        total_subscriptions = Subscription.query.filter(
            Subscription.status == 'active',
            Subscription.start_date <= datetime.utcnow(),
            (Subscription.end_date == None) | (Subscription.end_date > datetime.utcnow())
        ).count()
        
        # 6. Monthly revenue - same logic as Subscription Management page
        current_month = datetime.now().month
        current_year = datetime.now().year
        month_start = datetime(current_year, current_month, 1)

        # Use func.sum to calculate actual revenue from subscription amounts
        from sqlalchemy import func
        revenue_query = db.session.query(func.sum(Subscription.amount)).filter(
            Subscription.status == 'active',
            Subscription.payment_date >= month_start
        )
        revenue_this_month = revenue_query.scalar() or 0.0
        
        # 7. Calculate growth rate (compared to last month)
        last_month = datetime.now().replace(day=1) - timedelta(days=1)
        last_month_start = last_month.replace(day=1)
        this_month_start = datetime.now().replace(day=1)
        
        # User growth
        users_last_month = user_query.filter(
            User.created_at < this_month_start,
            User.status != 'deleted'
        ).count()
        user_growth = round(((total_users - users_last_month) / users_last_month * 100), 1) if users_last_month > 0 else 0
        
        # Verified users growth
        verified_last_month = user_query.filter(
            User.is_email_verified == True,
            User.created_at < this_month_start,
            User.status != 'deleted'
        ).count()
        verified_growth = round(((verified_users - verified_last_month) / verified_last_month * 100), 1) if verified_last_month > 0 else 0
        
        # Trip growth
        trips_last_month = Trip.query.filter(
            Trip.created_at < this_month_start
        ).count()
        trip_growth = round(((total_trips - trips_last_month) / trips_last_month * 100), 1) if trips_last_month > 0 else 0
        
        # 8. User growth chart data - based on time_range parameter
        chart_data = []
        now = datetime.now()

        if time_range == 'Last 7 Days':
            # Show data for last 7 days
            for i in range(7):
                day_start = (now - timedelta(days=6 - i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)

                users_in_day = user_query.filter(
                    User.created_at >= day_start,
                    User.created_at < day_end,
                    User.status != 'deleted'
                ).count()

                chart_data.append(users_in_day)

        elif time_range == 'Last 30 Days':
            # Show data for last 30 days
            for i in range(30):
                day_start = (now - timedelta(days=29 - i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)

                users_in_day = user_query.filter(
                    User.created_at >= day_start,
                    User.created_at < day_end,
                    User.status != 'deleted'
                ).count()

                chart_data.append(users_in_day)

        else:  # 'Last 12 Months' (default)
            # Show data for last 12 months
            for i in range(12):
                month_start = (now - timedelta(days=30 * (11 - i))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                month_end = (month_start + timedelta(days=32)).replace(day=1)

                users_in_month = user_query.filter(
                    User.created_at >= month_start,
                    User.created_at < month_end,
                    User.status != 'deleted'
                ).count()

                chart_data.append(users_in_month)
        
        return jsonify({
            'totalUsers': total_users,
            'verifiedUsers': verified_users,
            'totalTrips': total_trips,
            'totalArticles': total_articles,
            'totalSubscriptions': total_subscriptions,
            'revenueThisMonth': revenue_this_month,
            'userGrowth': user_growth,
            'verifiedGrowth': verified_growth,
            'tripGrowth': trip_growth,
            'chartData': chart_data,
            # Include permission info
            'currentAdminRole': current_admin_role,
            'viewScope': 'all_users' if current_admin_role == UserRole.SUPER_ADMIN else 'regular_users_only'
        })
        
    except Exception as e:
        print(f"Error fetching admin dashboard stats: {e}")
        return jsonify({'message': str(e)}), 500


# ==========================================
# 📝 NOTES & EXPENSES
# ==========================================

@admin_bp.route('/users/<int:user_id>/notes', methods=['GET'])
@login_required
@admin_required
def get_user_notes(user_id):
    """Get all notes for a specific user"""
    try:
        user = User.query.get_or_404(user_id)
        
        # Permission check
        current_admin_role = UserRole.normalize(current_user.role)
        target_user_role = UserRole.normalize(user.role)
        if current_admin_role == UserRole.ADMIN:
            if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({'error': 'Permission denied'}), 403
        
        notes = SchedulerItem.query.filter_by(user_id=user_id).order_by(
            SchedulerItem.created_at.desc()
        ).all()
        
        notes_by_category = {
            'note': [],
            'activity': [],
            'ai-suggestion': [],
            'other': []
        }
        
        for note in notes:
            category_key = note.category if note.category in notes_by_category else 'other'
            notes_by_category[category_key].append(note.to_dict())
        
        return jsonify({
            'user_id': user_id,
            'user_name': user.full_name or user.email,
            'total_notes': len(notes),
            'notes': [note.to_dict() for note in notes],
            'notes_by_category': notes_by_category
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<int:user_id>/expenses', methods=['GET'])
@login_required
@admin_required
def get_user_expenses(user_id):
    """Get all expenses for a specific user"""
    try:
        user = User.query.get_or_404(user_id)
        
        # Permission check
        current_admin_role = UserRole.normalize(current_user.role)
        target_user_role = UserRole.normalize(user.role)
        if current_admin_role == UserRole.ADMIN:
            if target_user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                return jsonify({'error': 'Permission denied'}), 403
        
        expenses = Expense.query.filter_by(user_id=user_id).order_by(
            Expense.created_at.desc()
        ).all()
        
        total_amount = sum(exp.amount for exp in expenses)
        
        return jsonify({
            'user_id': user_id,
            'user_name': user.full_name or user.email,
            'total_expenses': len(expenses),
            'total_amount': total_amount,
            'expenses': [exp.to_dict() for exp in expenses]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/notes/<int:note_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user_note(note_id):
    """Delete a note"""
    try:
        note = SchedulerItem.query.get_or_404(note_id)
        db.session.delete(note)
        db.session.commit()
        
        return jsonify({'message': 'Note deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/expenses/<int:expense_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user_expense(expense_id):
    """Delete an expense"""
    try:
        expense = Expense.query.get_or_404(expense_id)
        db.session.delete(expense)
        db.session.commit()
        
        return jsonify({'message': 'Expense deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# 🔥 NEW: Admin user management (super_admin only)
# ==========================================
@admin_bp.route('/admins', methods=['GET'])
@login_required
@super_admin_required
def get_all_admins():
    """
    Get list of all admin users (super_admin only)
    """
    try:
        admins = User.query.filter(
            User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN, 'Administrator', 'Admin'])
        ).filter(
            User.status != 'deleted'
        ).order_by(User.created_at.desc()).all()
        
        admins_data = []
        for admin in admins:
            admin_dict = admin.to_dict()
            admin_dict['role'] = UserRole.normalize(admin.role)
            admins_data.append(admin_dict)
        
        return jsonify({'admins': admins_data}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500