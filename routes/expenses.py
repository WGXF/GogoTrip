# expenses.py - CORRECTED FOR budget_limit
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, Expense, Trip
from datetime import datetime
from sqlalchemy import func

expenses_bp = Blueprint('expenses', __name__)


@expenses_bp.route('/active-trips', methods=['GET'])
@login_required
def get_active_trips():
    """获取当前用户所有 status='active' 的 Trip"""
    try:
        active_trips = Trip.query.filter_by(
            user_id=current_user.id,
            status='active'
        ).order_by(Trip.start_date.desc()).all()
        
        if not active_trips:
            return jsonify({
                'trips': [],
                'hasActiveTrips': False,
                'message': 'No active trips found. Please create a trip in Travel page.'
            }), 200
        
        trips_data = []
        for trip in active_trips:
            total_spent = db.session.query(
                func.sum(Expense.amount)
            ).filter(
                Expense.trip_id == trip.id
            ).scalar() or 0
            
            expense_count = Expense.query.filter_by(trip_id=trip.id).count()
            
            trip_dict = trip.to_dict()
            trip_dict['total_spent'] = float(total_spent)
            trip_dict['expense_count'] = expense_count
            # 🔥 修改：使用 budget_limit 而不是 budget
            trip_dict['budget'] = float(trip.budget_limit) if trip.budget_limit else 0
            
            trips_data.append(trip_dict)
        
        return jsonify({
            'trips': trips_data,
            'hasActiveTrips': True,
            'defaultTripId': trips_data[0]['id'] if trips_data else None
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_active_trips: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/trips/<int:trip_id>/stats', methods=['GET'])
@login_required
def get_trip_expense_stats(trip_id):
    """获取指定 Trip 的详细统计信息"""
    try:
        trip = Trip.query.filter_by(
            id=trip_id,
            user_id=current_user.id
        ).first_or_404()
        
        expenses = Expense.query.filter_by(trip_id=trip_id).all()
        total_spent = sum(exp.amount for exp in expenses)
        
        by_category = {}
        for exp in expenses:
            category = exp.category or 'other'
            by_category[category] = by_category.get(category, 0) + exp.amount
        
        # 🔥 修改：使用 budget_limit
        budget = float(trip.budget_limit) if trip.budget_limit else 0
        budget_percentage = (total_spent / budget * 100) if budget > 0 else 0
        
        return jsonify({
            'trip_id': trip.id,
            'trip_title': trip.title,
            'trip_destination': trip.destination,
            'trip_status': trip.status,
            'budget': budget,
            'total_spent': total_spent,
            'remaining': budget - total_spent,
            'budget_percentage': min(budget_percentage, 100),
            'expense_count': len(expenses),
            'by_category': by_category,
            'is_over_budget': total_spent > budget
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_trip_expense_stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/trips/<int:trip_id>', methods=['GET'])
@login_required
def get_trip_expenses(trip_id):
    """获取指定 Trip 的所有费用明细"""
    try:
        trip = Trip.query.filter_by(
            id=trip_id,
            user_id=current_user.id
        ).first_or_404()
        
        expenses = Expense.query.filter_by(
            trip_id=trip_id
        ).order_by(
            Expense.date.desc()
        ).all()
        
        return jsonify({
            'trip_id': trip.id,
            'trip_title': trip.title,
            'expenses': [exp.to_dict() for exp in expenses],
            'total': len(expenses)
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_trip_expenses: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/', methods=['POST'])
@login_required
def create_expense():
    """创建新费用"""
    data = request.get_json()
    
    if not data.get('title') or not data.get('amount'):
        return jsonify({'error': 'Title and amount are required'}), 400
    
    if not data.get('trip_id'):
        return jsonify({'error': 'trip_id is required. All expenses must be linked to a trip.'}), 400
    
    try:
        trip_id = data.get('trip_id')
        
        trip = Trip.query.filter_by(
            id=trip_id,
            user_id=current_user.id
        ).first()
        
        if not trip:
            return jsonify({'error': 'Invalid trip_id or trip does not belong to you'}), 400
        
        if trip.status != 'active':
            return jsonify({
                'error': f'Cannot add expense to non-active trip. Trip status: {trip.status}'
            }), 400
        
        expense = Expense(
            user_id=current_user.id,
            trip_id=trip_id,
            title=data.get('title'),
            amount=float(data.get('amount')),
            category=data.get('category', 'other')
        )
        
        # Set the date field
        if data.get('transaction_date'):
            try:
                expense.date = datetime.strptime(
                    data.get('transaction_date'), '%Y-%m-%d'
                ).date()
            except ValueError:
                expense.date = datetime.utcnow().date()
        else:
            expense.date = datetime.utcnow().date()
        
        db.session.add(expense)
        db.session.commit()
        
        return jsonify({
            'message': 'Expense created successfully',
            'expense': expense.to_dict()
        }), 201
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': 'Invalid amount value'}), 400
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error in create_expense: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/<int:expense_id>', methods=['PUT'])
@login_required
def update_expense(expense_id):
    """更新费用"""
    try:
        expense = Expense.query.get_or_404(expense_id)
        
        if expense.user_id != current_user.id:
            if not expense.trip or expense.trip.user_id != current_user.id:
                return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json()
        
        if 'title' in data:
            expense.title = data['title']
        if 'amount' in data:
            expense.amount = float(data['amount'])
        if 'category' in data:
            expense.category = data['category']
        if 'transaction_date' in data:
            try:
                expense.date = datetime.strptime(
                    data['transaction_date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                pass
        
        db.session.commit()
        
        return jsonify({
            'message': 'Expense updated successfully',
            'expense': expense.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error in update_expense: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/<int:expense_id>', methods=['DELETE'])
@login_required
def delete_expense(expense_id):
    """删除费用"""
    try:
        expense = Expense.query.get_or_404(expense_id)
        
        if expense.user_id != current_user.id:
            if not expense.trip or expense.trip.user_id != current_user.id:
                return jsonify({'error': 'Unauthorized'}), 403
        
        db.session.delete(expense)
        db.session.commit()
        
        return jsonify({'message': 'Expense deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error in delete_expense: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/trips/<int:trip_id>/budget', methods=['PUT'])
@login_required
def update_trip_budget(trip_id):
    """更新 Trip 的预算"""
    try:
        trip = Trip.query.filter_by(
            id=trip_id,
            user_id=current_user.id
        ).first_or_404()
        
        data = request.get_json()
        
        if 'budget' not in data:
            return jsonify({'error': 'budget field is required'}), 400
        
        try:
            budget = float(data['budget'])
            if budget < 0:
                return jsonify({'error': 'Budget cannot be negative'}), 400
            
            # 🔥 修改：使用 budget_limit
            trip.budget_limit = budget
            db.session.commit()
            
            return jsonify({
                'message': 'Budget updated successfully',
                'trip_id': trip.id,
                'budget': budget
            }), 200
            
        except ValueError:
            return jsonify({'error': 'Invalid budget value'}), 400
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error in update_trip_budget: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/summary', methods=['GET'])
@login_required
def get_all_active_trips_summary():
    """获取当前用户所有 active trips 的总览统计"""
    try:
        active_trips = Trip.query.filter_by(
            user_id=current_user.id,
            status='active'
        ).all()
        
        # 🔥 修改：使用 budget_limit
        total_budget = sum(float(trip.budget_limit or 0) for trip in active_trips)
        
        total_spent = 0
        for trip in active_trips:
            trip_spent = db.session.query(
                func.sum(Expense.amount)
            ).filter(
                Expense.trip_id == trip.id
            ).scalar() or 0
            total_spent += trip_spent
        
        return jsonify({
            'active_trips_count': len(active_trips),
            'total_budget': total_budget,
            'total_spent': total_spent,
            'total_remaining': total_budget - total_spent
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_all_active_trips_summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500