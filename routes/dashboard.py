from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from models import db, User, Trip, Article, Subscription, CalendarEvent, TripItem
from datetime import datetime, timedelta
from sqlalchemy import func, extract

dashboard_bp = Blueprint('dashboard', __name__)

# ==========================================
# ADMIN DASHBOARD API
# ==========================================

@dashboard_bp.route('/admin/dashboard-stats', methods=['GET'])
@login_required
def get_admin_dashboard_stats():
    """获取管理员仪表板统计数据"""
    
    # 检查权限
    if current_user.role not in ['Administrator', 'super_admin']:
        return jsonify({'message': 'Unauthorized'}), 403
    
    try:
        # 1. 总用户数
        total_users = User.query.count()
        
        # 2. 已验证用户数
        verified_users = User.query.filter_by(is_email_verified=True).count()
        
        # 3. 总行程数
        total_trips = Trip.query.count()
        
        # 4. 已发布文章数
        total_articles = Article.query.filter_by(status='Published').count()
        
        # 5. 活跃订阅数（premium用户）
        total_subscriptions = User.query.filter_by(is_premium=True).count()
        
        # 6. 本月收入（假设premium月费为RM 19.90）
        # 在实际应用中，这应该从 Subscription 表计算
        current_month = datetime.now().month
        current_year = datetime.now().year
        monthly_subscriptions = Subscription.query.filter(
            Subscription.status == 'paid',
            extract('month', Subscription.payment_date) == current_month,
            extract('year', Subscription.payment_date) == current_year
        ).count()
        revenue_this_month = monthly_subscriptions * 19.90  # 假设每个订阅 RM 19.90
        
        # 7. 计算增长率（与上月相比）
        last_month = datetime.now().replace(day=1) - timedelta(days=1)
        last_month_start = last_month.replace(day=1)
        this_month_start = datetime.now().replace(day=1)
        
        # 用户增长
        users_last_month = User.query.filter(
            User.created_at < this_month_start
        ).count()
        user_growth = round(((total_users - users_last_month) / users_last_month * 100), 1) if users_last_month > 0 else 0
        
        # 验证用户增长
        verified_last_month = User.query.filter(
            User.is_email_verified == True,
            User.created_at < this_month_start
        ).count()
        verified_growth = round(((verified_users - verified_last_month) / verified_last_month * 100), 1) if verified_last_month > 0 else 0
        
        # 行程增长
        trips_last_month = Trip.query.filter(
            Trip.created_at < this_month_start
        ).count()
        trip_growth = round(((total_trips - trips_last_month) / trips_last_month * 100), 1) if trips_last_month > 0 else 0
        
        # 8. 过去12个月的用户增长图表数据
        chart_data = []
        for i in range(12):
            month_start = (datetime.now() - timedelta(days=30 * (11 - i))).replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1)
            
            users_in_month = User.query.filter(
                User.created_at >= month_start,
                User.created_at < month_end
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
            'chartData': chart_data
        })
        
    except Exception as e:
        print(f"Error fetching admin dashboard stats: {e}")
        return jsonify({'message': str(e)}), 500


# ==========================================
# USER DASHBOARD API
# ==========================================

@dashboard_bp.route('/user/dashboard', methods=['GET'])
@login_required
def get_user_dashboard():
    """获取用户仪表板数据"""
    
    try:
        # 1. 即将到来的行程数
        upcoming_trips = Trip.query.filter(
            Trip.user_id == current_user.id,
            Trip.status.in_(['upcoming', 'planning']),
            Trip.start_date >= datetime.now().date()
        ).count()
        
        # 2. 已访问国家数（从已完成的行程中统计唯一目的地）
        # 这里简化处理，实际应用中可能需要更复杂的逻辑
        completed_trips = Trip.query.filter(
            Trip.user_id == current_user.id,
            Trip.status == 'completed'
        ).all()
        
        # 简单统计：假设 destination 字段就是国家名
        countries = set()
        for trip in completed_trips:
            if trip.destination:
                countries.add(trip.destination)
        countries_visited = len(countries)
        
        # 3. 保存的行程数（所有状态的行程）
        saved_itineraries = Trip.query.filter(
            Trip.user_id == current_user.id
        ).count()
        
        # 4. 下一个行程信息
        next_trip_query = Trip.query.filter(
            Trip.user_id == current_user.id,
            Trip.status.in_(['upcoming', 'planning']),
            Trip.start_date >= datetime.now().date()
        ).order_by(Trip.start_date.asc()).first()
        
        next_trip = None
        if next_trip_query:
            days_until = (next_trip_query.start_date - datetime.now().date()).days
            next_trip = {
                'destination': next_trip_query.destination or 'Unknown',
                'daysUntil': days_until
            }
        
        # 5. 即将到来的预约/活动（从 TripItem 和 CalendarEvent 获取）
        upcoming_appointments = []
        
        # 从 CalendarEvent 获取未来的事件
        calendar_events = CalendarEvent.query.filter(
            CalendarEvent.user_id == current_user.id,
            CalendarEvent.start_time >= datetime.now()
        ).order_by(CalendarEvent.start_time.asc()).limit(5).all()
        
        for event in calendar_events:
            upcoming_appointments.append({
                'id': str(event.id),
                'title': event.title or 'Event',
                'date': event.start_time.isoformat(),
                'durationMinutes': int((event.end_time - event.start_time).total_seconds() / 60) if event.end_time else 60,
                'location': '',
                'type': 'activity',
                'status': 'confirmed',
                'color': '#3B82F6'
            })
        
        # 6. 保存的草稿（这里可以从 Trip 表中获取 planning 状态的行程）
        draft_trips = Trip.query.filter(
            Trip.user_id == current_user.id,
            Trip.status == 'planning'
        ).order_by(Trip.created_at.desc()).limit(3).all()
        
        saved_drafts = []
        for trip in draft_trips:
            duration_days = 0
            if trip.start_date and trip.end_date:
                duration_days = (trip.end_date - trip.start_date).days
            
            saved_drafts.append({
                'id': trip.id,
                'title': trip.title or trip.destination or 'Untitled Trip',
                'details': f"{duration_days} days • {trip.destination or 'Planning'}"
            })
        
        return jsonify({
            'upcomingTrips': upcoming_trips,
            'countriesVisited': countries_visited,
            'savedItineraries': saved_itineraries,
            'nextTrip': next_trip,
            'upcomingAppointments': upcoming_appointments,
            'savedDrafts': saved_drafts
        })
        
    except Exception as e:
        print(f"Error fetching user dashboard: {e}")
        return jsonify({'message': str(e)}), 500