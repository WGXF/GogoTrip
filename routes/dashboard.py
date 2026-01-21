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
    """Get admin dashboard statistics"""
    from flask import request

    # Check permissions
    if current_user.role not in ['Administrator', 'super_admin']:
        return jsonify({'message': 'Unauthorized'}), 403

    try:
        # Get time range from query params
        time_range = request.args.get('range', 'Last 12 Months')

        # 1. Total users
        total_users = User.query.count()

        # 2. Verified users
        verified_users = User.query.filter_by(is_email_verified=True).count()

        # 3. Total trips
        total_trips = Trip.query.count()

        # 4. Published articles
        total_articles = Article.query.filter_by(status='Published').count()

        # 5. Active subscriptions (premium users)
        total_subscriptions = User.query.filter_by(is_premium=True).count()

        # 6. Monthly revenue - Calculate from subscriptions paid this month
        # Include both 'active' and 'paid' status subscriptions
        current_month = datetime.now().month
        current_year = datetime.now().year

        # Get all subscriptions paid this month (using payment_date)
        monthly_subscriptions = Subscription.query.filter(
            Subscription.status.in_(['active', 'paid']),
            extract('month', Subscription.payment_date) == current_month,
            extract('year', Subscription.payment_date) == current_year
        ).all()

        # Calculate revenue from plan prices
        revenue_this_month = 0
        for sub in monthly_subscriptions:
            if sub.plan and sub.plan.price:
                revenue_this_month += float(sub.plan.price)
            else:
                # Fallback to default price if plan not found
                revenue_this_month += 19.90

        # 7. Calculate growth rate (compared to last month)
        last_month = datetime.now().replace(day=1) - timedelta(days=1)
        last_month_start = last_month.replace(day=1)
        this_month_start = datetime.now().replace(day=1)

        # User growth
        users_last_month = User.query.filter(
            User.created_at < this_month_start
        ).count()
        user_growth = round(((total_users - users_last_month) / users_last_month * 100), 1) if users_last_month > 0 else 0

        # Verified users growth
        verified_last_month = User.query.filter(
            User.is_email_verified == True,
            User.created_at < this_month_start
        ).count()
        verified_growth = round(((verified_users - verified_last_month) / verified_last_month * 100), 1) if verified_last_month > 0 else 0

        # Trip growth
        trips_last_month = Trip.query.filter(
            Trip.created_at < this_month_start
        ).count()
        trip_growth = round(((total_trips - trips_last_month) / trips_last_month * 100), 1) if trips_last_month > 0 else 0

        # 8. User growth chart data - FIX: Respect time_range parameter
        chart_data = []
        now = datetime.now()

        if time_range == 'Last 7 Days':
            # Show data for last 7 days
            for i in range(7):
                day_start = (now - timedelta(days=6 - i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)

                users_in_day = User.query.filter(
                    User.created_at >= day_start,
                    User.created_at < day_end
                ).count()

                chart_data.append(users_in_day)

        elif time_range == 'Last 30 Days':
            # Show data for last 30 days (grouped by day)
            for i in range(30):
                day_start = (now - timedelta(days=29 - i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)

                users_in_day = User.query.filter(
                    User.created_at >= day_start,
                    User.created_at < day_end
                ).count()

                chart_data.append(users_in_day)

        else:  # 'Last 12 Months' (default)
            # Show data for last 12 months
            for i in range(12):
                month_start = (now - timedelta(days=30 * (11 - i))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
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
        import traceback
        traceback.print_exc()
        return jsonify({'message': str(e)}), 500


# ==========================================
# USER DASHBOARD API
# ==========================================

@dashboard_bp.route('/user/dashboard', methods=['GET'])
@login_required
def get_user_dashboard():
    """Get user dashboard data"""

    try:
        # 1. Upcoming trips count
        upcoming_trips = Trip.query.filter(
            Trip.user_id == current_user.id,
            Trip.status.in_(['upcoming', 'planning']),
            Trip.start_date >= datetime.now().date()
        ).count()

        # 2. Countries visited count (count unique destinations from completed trips)
        # Simplified handling here, actual application may need more complex logic
        completed_trips = Trip.query.filter(
            Trip.user_id == current_user.id,
            Trip.status == 'completed'
        ).all()

        # Simple count: assuming destination field is country name
        countries = set()
        for trip in completed_trips:
            if trip.destination:
                countries.add(trip.destination)
        countries_visited = len(countries)

        # 3. Saved itineraries count (trips in all statuses)
        saved_itineraries = Trip.query.filter(
            Trip.user_id == current_user.id
        ).count()

        # 4. Next trip information
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

        # 5. Upcoming appointments/activities (from TripItem and CalendarEvent)
        upcoming_appointments = []

        # Get future events from CalendarEvent
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

        # 6. Saved drafts (can get trips with planning status from Trip table)
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