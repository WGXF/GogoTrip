# api_admin_routes.py
"""
Admin API routes for managing users, notes, and expenses
Provides organized, collapsible data structure for frontend
"""

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from models import db, User, SchedulerItem, Expense, Trip, Notification
from datetime import datetime

admin_bp = Blueprint('admin', __name__)

# ----------------------
# Admin Authorization Decorator
# ----------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'super_admin', 'Admin', 'super_admin', 'Administrator']:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


# ----------------------
# Get All Users (List View)
# ----------------------
@admin_bp.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def get_all_users():
    """
    Get list of all users with basic info
    No detailed notes/expenses included - those are loaded on-demand
    
    Query params:
    - page: int (default 1)
    - per_page: int (default 20)
    - search: string (optional - search by name or email)
    - status: string (optional - filter by status)
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '')
        status = request.args.get('status', '')
        
        # Build query
        query = User.query
        
        # Apply search filter
        if search:
            query = query.filter(
                (User.email.ilike(f'%{search}%')) |
                (User.full_name.ilike(f'%{search}%'))
            )
        
        # Apply status filter
        if status:
            query = query.filter_by(status=status)
        
        # Order by creation date (newest first)
        query = query.order_by(User.created_at.desc())
        
        # Paginate
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        users = pagination.items
        
        # Format user data with counts (not full data)
        users_data = []
        for user in users:
            user_dict = user.to_dict()
            
            # Add counts for notes and expenses
            notes_count = SchedulerItem.query.filter_by(user_id=user.id).count()
            expenses_count = Expense.query.filter(
                (Expense.user_id == user.id) | 
                (Expense.trip_id.in_(
                    db.session.query(Trip.id).filter_by(user_id=user.id)
                ))
            ).count()
            trips_count = Trip.query.filter_by(user_id=user.id).count()
            
            user_dict['notesCount'] = notes_count
            user_dict['expensesCount'] = expenses_count
            user_dict['tripsCount'] = trips_count
            
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
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ----------------------
# Get User Detail (Basic Info Only)
# ----------------------
@admin_bp.route('/admin/users/<int:user_id>', methods=['GET'])
@login_required
@admin_required
def get_user_detail(user_id):
    """
    Get basic user details without notes/expenses
    Notes and expenses are loaded separately via other endpoints
    """
    try:
        user = User.query.get_or_404(user_id)
        user_data = user.to_dict()
        
        # Add summary counts
        user_data['notesCount'] = SchedulerItem.query.filter_by(user_id=user.id).count()
        user_data['expensesCount'] = Expense.query.filter(
            (Expense.user_id == user.id) | 
            (Expense.trip_id.in_(
                db.session.query(Trip.id).filter_by(user_id=user.id)
            ))
        ).count()
        user_data['tripsCount'] = Trip.query.filter_by(user_id=user.id).count()
        
        return jsonify(user_data), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ----------------------
# 🔥 NEW: Get User Notes (Collapsible Section)
# ----------------------
@admin_bp.route('/admin/users/<int:user_id>/notes', methods=['GET'])
@login_required
@admin_required
def get_user_notes(user_id):
    """
    Get all notes (SchedulerItems) for a specific user
    This endpoint is called when admin expands the Notes section
    
    Query params:
    - category: string (optional - filter by category)
    - limit: int (optional - limit results, default all)
    """
    try:
        user = User.query.get_or_404(user_id)
        
        query = SchedulerItem.query.filter_by(user_id=user_id)
        
        # Apply category filter if provided
        category = request.args.get('category')
        if category:
            query = query.filter_by(category=category)
        
        # Apply limit if provided
        limit = request.args.get('limit', type=int)
        if limit:
            query = query.limit(limit)
        
        # Order by most recent first
        notes = query.order_by(SchedulerItem.created_at.desc()).all()
        
        # Group notes by category for better organization
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


# ----------------------
# 🔥 NEW: Get User Expenses (Collapsible Section)
# ----------------------
@admin_bp.route('/admin/users/<int:user_id>/expenses', methods=['GET'])
@login_required
@admin_required
def get_user_expenses(user_id):
    """
    Get all expenses for a specific user
    This endpoint is called when admin expands the Expenses section
    
    Query params:
    - include_relations: bool (default true) - include trip/item/place details
    - trip_id: int (optional) - filter by specific trip
    - category: string (optional) - filter by category
    - limit: int (optional - limit results, default all)
    """
    try:
        user = User.query.get_or_404(user_id)
        
        # Get all expenses for this user
        query = Expense.query.filter(
            (Expense.user_id == user_id) | 
            (Expense.trip_id.in_(
                db.session.query(Trip.id).filter_by(user_id=user_id)
            ))
        )
        
        # Apply filters
        trip_id = request.args.get('trip_id', type=int)
        if trip_id:
            query = query.filter_by(trip_id=trip_id)
        
        category = request.args.get('category')
        if category:
            query = query.filter_by(category=category)
        
        limit = request.args.get('limit', type=int)
        if limit:
            query = query.limit(limit)
        
        # Order by transaction date (most recent first)
        expenses = query.order_by(Expense.transaction_date.desc()).all()
        
        include_relations = request.args.get('include_relations', 'true').lower() == 'true'
        
        # Calculate statistics
        total_amount = sum(exp.amount for exp in expenses)
        custom_expenses = [exp for exp in expenses if exp.is_custom]
        trip_expenses = [exp for exp in expenses if not exp.is_custom]
        
        # Group by category
        by_category = {}
        for exp in expenses:
            cat = exp.category or 'other'
            if cat not in by_category:
                by_category[cat] = {
                    'count': 0,
                    'total': 0,
                    'expenses': []
                }
            by_category[cat]['count'] += 1
            by_category[cat]['total'] += exp.amount
            by_category[cat]['expenses'].append(exp.to_dict(include_relations=include_relations))
        
        # Group by trip
        by_trip = {}
        for exp in trip_expenses:
            if exp.trip_id:
                trip_id_key = str(exp.trip_id)
                if trip_id_key not in by_trip:
                    by_trip[trip_id_key] = {
                        'trip_id': exp.trip_id,
                        'trip_title': exp.trip.title if exp.trip else 'Unknown Trip',
                        'count': 0,
                        'total': 0,
                        'expenses': []
                    }
                by_trip[trip_id_key]['count'] += 1
                by_trip[trip_id_key]['total'] += exp.amount
                by_trip[trip_id_key]['expenses'].append(exp.to_dict(include_relations=include_relations))
        
        return jsonify({
            'user_id': user_id,
            'user_name': user.full_name or user.email,
            'total_expenses': len(expenses),
            'total_amount': total_amount,
            'custom_expenses_count': len(custom_expenses),
            'trip_expenses_count': len(trip_expenses),
            'expenses': [exp.to_dict(include_relations=include_relations) for exp in expenses],
            'by_category': by_category,
            'by_trip': by_trip,
            'custom_expenses': [exp.to_dict(include_relations=include_relations) for exp in custom_expenses]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ----------------------
# Get User Trips (for reference)
# ----------------------
@admin_bp.route('/admin/users/<int:user_id>/trips', methods=['GET'])
@login_required
@admin_required
def get_user_trips(user_id):
    """Get all trips for a specific user"""
    try:
        user = User.query.get_or_404(user_id)
        trips = Trip.query.filter_by(user_id=user_id).order_by(Trip.created_at.desc()).all()
        
        return jsonify({
            'user_id': user_id,
            'user_name': user.full_name or user.email,
            'total_trips': len(trips),
            'trips': [trip.to_dict() for trip in trips]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ----------------------
# Update User Status
# ----------------------
@admin_bp.route('/admin/users/<int:user_id>/status', methods=['PUT'])
@login_required
@admin_required
def update_user_status(user_id):
    """Update user status (Active/Suspended/Inactive)"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()
        
        new_status = data.get('status')
        if new_status not in ['Active', 'Suspended', 'Inactive']:
            return jsonify({'error': 'Invalid status'}), 400
        
        user.status = new_status
        db.session.commit()
        
        return jsonify({
            'message': 'User status updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ----------------------
# Delete User Note (Admin)
# ----------------------
@admin_bp.route('/admin/notes/<int:note_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user_note(note_id):
    """Delete a user's note (admin only)"""
    try:
        note = SchedulerItem.query.get_or_404(note_id)
        user_id = note.user_id
        
        db.session.delete(note)
        db.session.commit()
        
        return jsonify({
            'message': 'Note deleted successfully',
            'user_id': user_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ----------------------
# Delete User Expense (Admin)
# ----------------------
@admin_bp.route('/admin/expenses/<int:expense_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user_expense(expense_id):
    """Delete a user's expense (admin only)"""
    try:
        expense = Expense.query.get_or_404(expense_id)
        user_id = expense.user_id or (expense.trip.user_id if expense.trip else None)
        
        db.session.delete(expense)
        db.session.commit()
        
        return jsonify({
            'message': 'Expense deleted successfully',
            'user_id': user_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ----------------------
# Get Admin Dashboard Stats
# ----------------------
@admin_bp.route('/admin/dashboard-stats', methods=['GET'])
@login_required
@admin_required
def get_dashboard_stats():
    """Get overview statistics for admin dashboard"""
    try:
        total_users = User.query.count()
        active_users = User.query.filter_by(status='Active').count()
        total_trips = Trip.query.count()
        total_expenses = Expense.query.count()
        total_notes = SchedulerItem.query.count()
        
        # Recent activity
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        recent_expenses = Expense.query.order_by(Expense.created_at.desc()).limit(10).all()
        
        return jsonify({
            'total_users': total_users,
            'active_users': active_users,
            'total_trips': total_trips,
            'total_expenses': total_expenses,
            'total_notes': total_notes,
            'recent_users': [user.to_dict() for user in recent_users],
            'recent_expenses': [exp.to_dict(include_relations=True) for exp in recent_expenses]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500