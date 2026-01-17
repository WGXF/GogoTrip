# ================================================
# 📬 Public Inquiries Routes (FIXED - With assignedAdminName)
# ================================================
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Inquiry, SystemNotification, User

public_inquiries_bp = Blueprint('public_inquiries', __name__)


# ================================================
# 🔧 Helper Functions
# ================================================

def is_super_admin_role(role: str) -> bool:
    """Check if user has super_admin role."""
    if not role:
        return False
    role_lower = role.lower().strip()
    super_admin_roles = ['super_admin', 'administrator', 'superadmin']
    return role_lower in super_admin_roles


def validate_email(email):
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def create_admin_notification(inquiry):
    """Create a SystemNotification for all admins when a new inquiry arrives"""
    try:
        type_label = "Merchant Partnership" if inquiry.inquiry_type == 'merchant' else "Contact"
        title = f"New {type_label} Inquiry"
        content = f"""
New inquiry received from {inquiry.name} ({inquiry.email})
Type: {type_label}
{f"Business: {inquiry.business_name}" if inquiry.business_name else ""}
{f"Subject: {inquiry.subject}" if inquiry.subject else ""}

Message Preview:
{inquiry.message[:200]}{'...' if len(inquiry.message) > 200 else ''}
        """.strip()
        
        notification = SystemNotification(
            recipient_type='all_admins',
            recipient_id=None,
            title=title,
            content=content,
            notification_type='inquiry_new',
            related_type='inquiry',
            related_id=inquiry.id
        )
        db.session.add(notification)
        inquiry.admin_notified = True
        return notification
    except Exception as e:
        print(f"[Inquiry] Failed to create admin notification: {str(e)}")
        return None


def get_inquiry_with_admin_name(inquiry):
    """
    🔥 FIX: Convert inquiry to dict and include assignedAdminName
    This ensures the list view shows the assigned admin's name
    """
    # Get base preview dict
    data = inquiry.to_preview_dict()
    
    # 🔥 Manually add assignedAdminName if not present
    if 'assignedAdminName' not in data or data.get('assignedAdminName') is None:
        if inquiry.assigned_admin_id:
            admin = User.query.get(inquiry.assigned_admin_id)
            data['assignedAdminName'] = admin.full_name or admin.email if admin else None
        else:
            data['assignedAdminName'] = None
    
    return data


# ================================================
# 📬 Public Endpoints (No Auth Required)
# ================================================

@public_inquiries_bp.route('/api/public/inquiry', methods=['POST'])
def submit_inquiry():
    """Submit a new inquiry (Merchant or Contact)"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        inquiry_type = data.get('type', '').strip().lower()
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        message = data.get('message', '').strip()
        
        if inquiry_type not in ['merchant', 'contact']:
            return jsonify({'success': False, 'error': 'Invalid inquiry type'}), 400
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        
        if not email or not validate_email(email):
            return jsonify({'success': False, 'error': 'Valid email is required'}), 400
        
        if not message:
            return jsonify({'success': False, 'error': 'Message is required'}), 400
        
        business_name = None
        subject = None
        
        if inquiry_type == 'merchant':
            business_name = data.get('businessName', '').strip()
            if not business_name:
                return jsonify({'success': False, 'error': 'Business name is required'}), 400
        
        if inquiry_type == 'contact':
            subject = data.get('subject', '').strip()
        
        inquiry = Inquiry(
            inquiry_type=inquiry_type,
            name=name,
            email=email,
            business_name=business_name,
            subject=subject,
            message=message,
            status='pending',
            priority='normal'
        )
        
        db.session.add(inquiry)
        db.session.flush()
        create_admin_notification(inquiry)
        db.session.commit()
        
        print(f"[Inquiry] New {inquiry_type} inquiry #{inquiry.id} from {name}")
        
        return jsonify({
            'success': True,
            'message': 'Inquiry submitted successfully.',
            'inquiryId': inquiry.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"[Inquiry] Error: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to submit inquiry'}), 500


# ================================================
# 🔒 Admin Endpoints (Auth Required)
# ================================================

@public_inquiries_bp.route('/api/admin/inquiries', methods=['GET'])
def get_all_inquiries():
    """Get all inquiries (Admin only)"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if current_user.role not in ['Administrator', 'super_admin', 'Admin', 'admin']:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        inquiry_type = request.args.get('type', 'all')
        status = request.args.get('status', 'all')
        assigned_to = request.args.get('assigned_to', type=int)
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        query = Inquiry.query
        
        if inquiry_type != 'all':
            query = query.filter(Inquiry.inquiry_type == inquiry_type)
        
        if status != 'all':
            query = query.filter(Inquiry.status == status)
        
        if assigned_to:
            query = query.filter(Inquiry.assigned_admin_id == assigned_to)
        
        query = query.order_by(Inquiry.created_at.desc())
        
        total = query.count()
        inquiries = query.offset((page - 1) * limit).limit(limit).all()
        
        # 🔥 FIX: Use helper function to include assignedAdminName
        inquiries_data = [get_inquiry_with_admin_name(i) for i in inquiries]
        
        return jsonify({
            'success': True,
            'data': inquiries_data,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
        
    except Exception as e:
        print(f"[Inquiry] Error fetching: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to fetch inquiries'}), 500


@public_inquiries_bp.route('/api/admin/inquiries/stats', methods=['GET'])
def get_inquiry_stats():
    """Get inquiry statistics (Admin only)"""
    from flask_login import current_user
    from sqlalchemy import func
    
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if current_user.role not in ['Administrator', 'super_admin', 'Admin', 'admin']:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        status_counts = db.session.query(
            Inquiry.status, func.count(Inquiry.id)
        ).group_by(Inquiry.status).all()
        
        type_counts = db.session.query(
            Inquiry.inquiry_type, func.count(Inquiry.id)
        ).group_by(Inquiry.inquiry_type).all()
        
        total = Inquiry.query.count()
        pending = Inquiry.query.filter(Inquiry.status == 'pending').count()
        
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'pending': pending,
                'byStatus': {s: c for s, c in status_counts},
                'byType': {t: c for t, c in type_counts}
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': 'Failed to fetch stats'}), 500


@public_inquiries_bp.route('/api/admin/inquiries/<int:inquiry_id>', methods=['GET'])
def get_inquiry_detail(inquiry_id):
    """Get inquiry detail (Admin only)"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if current_user.role not in ['Administrator', 'super_admin', 'Admin', 'admin']:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    inquiry = Inquiry.query.get(inquiry_id)
    if not inquiry:
        return jsonify({'success': False, 'error': 'Inquiry not found'}), 404
    
    # 🔥 FIX: Ensure detail also has assignedAdminName
    data = inquiry.to_dict()
    if 'assignedAdminName' not in data or data.get('assignedAdminName') is None:
        if inquiry.assigned_admin_id:
            admin = User.query.get(inquiry.assigned_admin_id)
            data['assignedAdminName'] = admin.full_name or admin.email if admin else None
        else:
            data['assignedAdminName'] = None
    
    return jsonify({'success': True, 'data': data})


@public_inquiries_bp.route('/api/admin/inquiries/<int:inquiry_id>', methods=['PATCH'])
def update_inquiry(inquiry_id):
    """Update inquiry (Admin only) - with role-based permissions"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if current_user.role not in ['Administrator', 'super_admin', 'Admin', 'admin']:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    inquiry = Inquiry.query.get(inquiry_id)
    if not inquiry:
        return jsonify({'success': False, 'error': 'Inquiry not found'}), 404
    
    user_is_super_admin = is_super_admin_role(current_user.role)
    
    # Regular admin can only edit inquiries assigned to them
    if not user_is_super_admin:
        if inquiry.assigned_admin_id is not None and inquiry.assigned_admin_id != current_user.id:
            return jsonify({
                'success': False, 
                'error': 'You can only modify inquiries assigned to you'
            }), 403
    
    try:
        data = request.get_json()
        
        if 'status' in data:
            valid_statuses = ['pending', 'in_progress', 'resolved', 'closed']
            if data['status'] in valid_statuses:
                old_status = inquiry.status
                inquiry.status = data['status']
                
                if data['status'] in ['resolved', 'closed'] and old_status not in ['resolved', 'closed']:
                    inquiry.resolved_at = datetime.utcnow()
                elif data['status'] in ['pending', 'in_progress'] and old_status in ['resolved', 'closed']:
                    inquiry.resolved_at = None
        
        if 'priority' in data:
            valid_priorities = ['low', 'normal', 'high']
            if data['priority'] in valid_priorities:
                inquiry.priority = data['priority']
        
        if 'adminNotes' in data:
            inquiry.admin_notes = data['adminNotes']
        
        # 🔐 Only super_admin can change assignment
        if 'assignedAdminId' in data:
            if not user_is_super_admin:
                return jsonify({
                    'success': False, 
                    'error': 'Only Super Admin can assign/reassign inquiries'
                }), 403
            
            new_admin_id = data['assignedAdminId']
            if new_admin_id:
                admin = User.query.get(new_admin_id)
                if admin and admin.role in ['Administrator', 'super_admin', 'Admin', 'admin']:
                    inquiry.assigned_admin_id = new_admin_id
                else:
                    return jsonify({'success': False, 'error': 'Invalid admin ID'}), 400
            else:
                inquiry.assigned_admin_id = None
        
        db.session.commit()
        
        # 🔥 FIX: Include assignedAdminName in response
        response_data = inquiry.to_dict()
        if inquiry.assigned_admin_id:
            admin = User.query.get(inquiry.assigned_admin_id)
            response_data['assignedAdminName'] = admin.full_name or admin.email if admin else None
        else:
            response_data['assignedAdminName'] = None
        
        return jsonify({
            'success': True,
            'message': 'Inquiry updated successfully',
            'data': response_data
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[Inquiry] Error updating: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to update inquiry'}), 500


@public_inquiries_bp.route('/api/admin/inquiries/<int:inquiry_id>', methods=['DELETE'])
def delete_inquiry(inquiry_id):
    """Delete inquiry (Admin only)"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if current_user.role not in ['Administrator', 'super_admin', 'Admin', 'admin']:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    inquiry = Inquiry.query.get(inquiry_id)
    if not inquiry:
        return jsonify({'success': False, 'error': 'Inquiry not found'}), 404
    
    try:
        db.session.delete(inquiry)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Inquiry deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to delete inquiry'}), 500


# ================================================
# 📧 Admin List Endpoint (for assignment dropdown)
# ================================================

@public_inquiries_bp.route('/api/admin/users/admins', methods=['GET'])
def get_admin_list():
    """Get list of admin users for assignment dropdown"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if current_user.role not in ['Administrator', 'super_admin', 'Admin', 'admin']:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        admins = User.query.filter(
            User.role.in_(['Administrator', 'super_admin', 'Admin', 'admin']),
            User.status == 'active'
        ).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': a.id,
                'name': a.full_name or a.email,
                'email': a.email,
                'role': a.role
            } for a in admins]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': 'Failed to fetch admins'}), 500