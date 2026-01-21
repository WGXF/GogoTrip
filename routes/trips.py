# routes/trips.py

from flask import Blueprint, request, session, jsonify
from models import db, Trip, TripItem, Place
from datetime import datetime, timedelta, time
from flask_login import login_required, current_user
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json
import re
import config

trips_bp = Blueprint('trips', __name__)



# =========================================================
# 🆕 New: Export trips to Google Calendar
# =========================================================
@trips_bp.route('/<int:trip_id>/export_calendar', methods=['POST', 'GET'])
@login_required
def export_to_calendar(trip_id):
    """
    Export trip to Google Calendar

    Complete path: POST /trips/<trip_id>/export_calendar

    Request Body (optional):
    {
        "start_date": "2024-01-15"  // Trip start date, defaults to today
    }

    Returns:
    {
        "status": "success",
        "message": "Successfully exported X events",
        "events_exported": X
    }
    """
    # Check Google Calendar authorization
    if 'credentials' not in session:
        return jsonify({
            'error': 'Google Calendar not authorized',
            'redirect': '/auth/authorize'
        }), 401
    
    user_id = current_user.id

    try:
        # 1. Get trip information
        trip = Trip.query.filter_by(id=trip_id, user_id=user_id).first()

        if not trip:
            return jsonify({'error': 'Trip does not exist'}), 404

        # 2. Parse start date
        if request.is_json and request.json:
            start_date_str = request.json.get('start_date')
        else:
            start_date_str = request.args.get('start_date')

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'Invalid date format, please use YYYY-MM-DD'}), 400
        else:
            start_date = trip.start_date or datetime.now().date()

        # 3. Get all items in trip
        trip_items = TripItem.query.filter_by(trip_id=trip_id).order_by(
            TripItem.day_number, TripItem.start_time
        ).all()

        if not trip_items:
            return jsonify({
                'status': 'success',
                'message': 'No items to export in trip',
                'events_exported': 0
            }), 200

        # 4. Connect to Google Calendar
        credentials = Credentials(**session['credentials'])
        service = build('calendar', 'v3', credentials=credentials)

        events_created = 0

        # 5. Create calendar event for each trip item
        for item in trip_items:
            # Calculate actual date
            day_offset = (item.day_number or 1) - 1
            event_date = start_date + timedelta(days=day_offset)

            # Parse time - ensure HH:MM string format
            if item.start_time:
                if hasattr(item.start_time, 'strftime'):
                    start_time_str = item.start_time.strftime("%H:%M")
                else:
                    start_time_str = str(item.start_time)[:5]  # Take first 5 chars "09:00"
            else:
                start_time_str = "09:00"

            if item.end_time:
                if hasattr(item.end_time, 'strftime'):
                    end_time_str = item.end_time.strftime("%H:%M")
                else:
                    end_time_str = str(item.end_time)[:5]
            else:
                end_time_str = _calculate_end_time(start_time_str)

            # Get place name
            place_name = ''
            if item.place_id:
                place = Place.query.get(item.place_id)
                if place:
                    place_name = place.name

            # Build event title - prioritize custom_title, then place_name, then custom_notes
            event_title = f"🗺️ {trip.title} - Day {item.day_number}"
            if hasattr(item, 'custom_title') and item.custom_title:
                event_title = f"📍 {item.custom_title}"
            elif place_name:
                event_title = f"📍 {place_name}"
            elif item.custom_notes:
                event_title = f"🗺️ {item.custom_notes[:50]}"

            # Build event description
            description_parts = [
                f"Trip: {trip.title}",
                f"Day {item.day_number}",
            ]

            if hasattr(item, 'custom_title') and item.custom_title:
                description_parts.append(f"Activity: {item.custom_title}")
            if place_name:
                description_parts.append(f"Place: {place_name}")
            if item.custom_notes:
                description_parts.append(f"Notes: {item.custom_notes}")
            
            # Create calendar event
            event_body = {
                'summary': event_title,
                'description': '\n'.join(description_parts),
                'start': {
                    'dateTime': f"{event_date}T{start_time_str}:00",
                    'timeZone': getattr(config, 'TIMEZONE', 'Asia/Kuala_Lumpur'),
                },
                'end': {
                    'dateTime': f"{event_date}T{end_time_str}:00",
                    'timeZone': getattr(config, 'TIMEZONE', 'Asia/Kuala_Lumpur'),
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 30},
                    ],
                },
            }

            # If there are place coordinates, add location information
            if item.place_id:
                place = Place.query.get(item.place_id)
                if place and place.address:
                    event_body['location'] = place.address

            try:
                service.events().insert(calendarId='primary', body=event_body).execute()
                events_created += 1
                print(f"✅ [Calendar Export] Event created: {event_title}")
            except Exception as e:
                print(f"⚠️ [Calendar Export] Failed to create event: {e}")
                continue

        # 6. Update trip status (optional)
        trip.status = 'active'
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': f'Successfully exported {events_created} events to Google Calendar',
            'events_exported': events_created,
            'start_date': start_date.isoformat()
        }), 200

    except Exception as e:
        print(f"❌ [Calendar Export Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'导出失败: {str(e)}'}), 500


def _calculate_end_time(start_time: str, duration_hours: int = 2) -> str:
    """Calculate end time (default activity duration 2 hours)"""
    try:
        parts = start_time.split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        
        end_hour = hour + duration_hours
        if end_hour >= 24:
            end_hour = 23
            minute = 59
        
        return f"{end_hour:02d}:{minute:02d}"
    except:
        return "11:00"


# =========================================================
# Save trip
# =========================================================
@trips_bp.route('/save', methods=['POST', 'DELETE'])
@login_required
def save_trip():
    """
    Save or delete trip from database
    """
    try:
        user_id = current_user.id
        data = request.json

        if request.method == 'DELETE':
            # Delete/unsave trip
            title = data.get('title')
            print(f"🗑️ [Trips API] Unsaving trip: {title} (User: {user_id})")

            # Find and delete the trip
            trip = Trip.query.filter_by(user_id=user_id, title=title).first()
            if trip:
                db.session.delete(trip)
                db.session.commit()
                return jsonify({'success': True, 'message': 'Trip unsaved'}), 200
            else:
                return jsonify({'success': False, 'message': 'Trip not found'}), 404

        else:  # POST - Save trip
            print(f"📥 [Trips API] Received save request: {data.get('title', 'Unknown')} (User: {user_id})")

            # Check if trip already exists
            existing_trip = Trip.query.filter_by(
                user_id=user_id,
                title=data.get('title')
            ).first()

            if existing_trip:
                print(f"⚠️ [Trips API] Trip already exists: {data.get('title')}")
                return jsonify({
                    'success': True,
                    'message': 'Trip already saved',
                    'trip_id': existing_trip.id
                }), 200

            # Determine the type of save
            is_itinerary = 'itinerary' in data and isinstance(data['itinerary'], list)

            if is_itinerary:
                trip_data = save_full_itinerary(user_id, data)
            else:
                trip_data = save_single_place(user_id, data)

            return jsonify({
                'success': True,
                'message': 'Trip saved',
                'trip_id': trip_data['trip_id']
            }), 200

    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'error': f'保存失败: {str(e)}'}), 500


def save_full_itinerary(user_id: int, data: dict):
    """
    Save full trip plan to database
    """
    # 1. Parse date range
    duration_str = data.get('duration', '3天')
    days_count = extract_days_from_duration(duration_str)

    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=days_count)

    # 2. Create Trip record
    new_trip = Trip(
        user_id=user_id,
        title=data.get('title', '未命名行程'),
        destination=extract_destination_from_title(data.get('title', '')),
        start_date=start_date,
        end_date=end_date,
        budget_limit=extract_budget_from_estimate(data.get('priceEstimate', 'N/A')),
        status='planning'
    )
    
    db.session.add(new_trip)
    db.session.flush()

    print(f"✅ [Trips] Trip created: {new_trip.title} (ID: {new_trip.id})")

    # 3. Iterate through each day of the trip, create TripItem
    itinerary = data.get('itinerary', [])
    
    for day_plan in itinerary:
        day_number = day_plan.get('day', 1)
        items = day_plan.get('items', [])
        
        for item in items:

            raw_time = item.get('time', '09:00')
            start_time = datetime.strptime(raw_time, "%H:%M").time()

            activity_name = item.get('activity', '')

            # Find or create Place record
            place = Place.query.filter_by(name=activity_name).first()
            place_id = place.id if place else None

            if not place:
                print(f"⚠️ [Warning] Place '{activity_name}' not in database, skipping place_id")

            # Create TripItem
            trip_item = TripItem(
                trip_id=new_trip.id,
                place_id=place_id,
                day_number=day_number,
                start_time=start_time,
                end_time=None,
                item_type='activity',
                custom_notes=item.get('description', '') or activity_name,
                status='confirmed'
            )
            
            db.session.add(trip_item)

    db.session.commit()
    print(f"✅ [Trips] Successfully saved {len(itinerary)}-day trip")

    return {
        'trip_id': new_trip.id,
        'type': 'full_itinerary'
    }


def save_single_place(user_id: int, data: dict):
    """
    Save single place to trip (create a simple trip)
    """
    # 1. Find place
    place_name = data.get('title', data.get('name', ''))
    place = Place.query.filter_by(name=place_name).first()

    if not place:
        print(f"⚠️ [Warning] Place '{place_name}' not in database")
        place = create_place_from_data(data)

    # 2. Create a simple Trip
    new_trip = Trip(
        user_id=user_id,
        title=f"{place_name} 行程",
        destination=data.get('address', ''),
        start_date=datetime.now().date(),
        end_date=datetime.now().date(),
        status='planning'
    )
    
    db.session.add(new_trip)
    db.session.flush()

    # 3. Create TripItem
    trip_item = TripItem(
        trip_id=new_trip.id,
        place_id=place.id if place else None,
        day_number=1,
        start_time=time(9, 0),
        item_type='activity',
        custom_notes=data.get('description', ''),
        status='confirmed'
    )
    
    db.session.add(trip_item)
    db.session.commit()

    print(f"✅ [Trips] Successfully saved single place: {place_name}")

    return {
        'trip_id': new_trip.id,
        'type': 'single_place'
    }


def create_place_from_data(data: dict):
    """
    Create Place record from frontend data
    """
    coords = data.get('coordinates', {})
    if isinstance(coords, dict):
        coords_str = json.dumps(coords)
    else:
        coords_str = coords

    new_place = Place(
        google_place_id=data.get('google_place_id', f"manual-{datetime.now().timestamp()}"),
        name=data.get('title', data.get('name', '')),
        address=data.get('address', data.get('fullAddress', '')),
        rating=data.get('rating'),
        business_status='OPERATIONAL',
        is_open_now=data.get('is_open_now'),
        coordinates=coords_str,
        photo_reference=data.get('photo_reference'),
        review_list=json.dumps(data.get('reviews', [])),
        cached_at=datetime.utcnow()
    )

    db.session.add(new_place)
    db.session.flush()

    print(f"✅ [Places] New place created: {new_place.name} (ID: {new_place.id})")

    return new_place


# =========================================================
# Utility functions
# =========================================================
def extract_days_from_duration(duration_str: str) -> int:
    """Extract days from '3天2夜' or '5 Days'"""
    match = re.search(r'(\d+)', duration_str)
    return int(match.group(1)) if match else 3


def extract_destination_from_title(title: str) -> str:
    """从标题中提取目的地"""
    for suffix in ['游', '行程', '之旅', 'Trip', 'Tour']:
        title = title.replace(suffix, '')
    return title.strip()[:50]


def extract_budget_from_estimate(estimate_str: str) -> float:
    """Extract budget limit from 'RM 1,500 - RM 2,500'"""
    numbers = re.findall(r'[\d,]+', estimate_str)
    if numbers:
        values = [float(n.replace(',', '')) for n in numbers]
        return max(values)
    return 0.0


# =========================================================
# Get trip list
# =========================================================
@trips_bp.route('/list', methods=['GET'])
@login_required
def list_trips():
    """
    Get all trips for user
    """
    try:
        user_id = current_user.id

        trips = Trip.query.filter_by(user_id=user_id).order_by(Trip.created_at.desc()).all()
        
        results = []
        for trip in trips:
            results.append({
                'id': trip.id,
                'title': trip.title,
                'destination': trip.destination,
                'start_date': trip.start_date.isoformat() if trip.start_date else None,
                'end_date': trip.end_date.isoformat() if trip.end_date else None,
                'status': trip.status,
                'created_at': trip.created_at.isoformat() if trip.created_at else None
            })
        
        return jsonify(results), 200
    
    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        return jsonify({'error': str(e)}), 500


# =========================================================
# Get single trip details
# =========================================================
@trips_bp.route('/<int:trip_id>', methods=['GET'])
@login_required
def get_trip_details(trip_id):
    """
    Get detailed information for single trip (including all TripItems)
    """
    try:
        user_id = current_user.id

        trip = Trip.query.filter_by(id=trip_id, user_id=user_id).first()

        if not trip:
            return jsonify({'error': 'Trip does not exist'}), 404

        # Get all trip items
        items = []
        for trip_item in trip.items:
            place_data = None
            if trip_item.place_id:
                place = Place.query.get(trip_item.place_id)
                if place:
                    place_data = {
                        'id': place.id,
                        'name': place.name,
                        'address': place.address,
                        'rating': place.rating
                    }
            
            items.append({
                'id': trip_item.id,
                'day_number': trip_item.day_number,
                'start_time': trip_item.start_time.isoformat() if trip_item.start_time else None,
                'end_time': trip_item.end_time.isoformat() if trip_item.end_time else None,
                'item_type': trip_item.item_type,
                'notes': trip_item.custom_notes,
                'status': trip_item.status,
                'place': place_data
            })

        result = {
            'id': trip.id,
            'title': trip.title,
            'destination': trip.destination,
            'start_date': trip.start_date.isoformat() if trip.start_date else None,
            'end_date': trip.end_date.isoformat() if trip.end_date else None,
            'budget_limit': trip.budget_limit,
            'status': trip.status,
            'items': items,
            'created_at': trip.created_at.isoformat() if trip.created_at else None
        }
        
        return jsonify(result), 200
    
    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        return jsonify({'error': str(e)}), 500


# =========================================================
# 🆕 Save new format Daily Plan (AI-generated structured trip)
# =========================================================
@trips_bp.route('/save_daily_plan', methods=['POST', 'DELETE'])
@login_required
def save_daily_plan():
    """
    Save or delete AI-generated structured Daily Plan from database

    New format includes:
    - type: "daily_plan"
    - days: multi-day trip array
    - Each day contains top_locations and activities
    - Each activity linked to place_id
    """
    try:
        user_id = current_user.id
        data = request.json

        if request.method == 'DELETE':
            # Delete/unsave daily plan
            title = data.get('title')
            print(f"🗑️ [Trips API] Unsaving daily plan: {title} (User: {user_id})")

            # Find and delete the trip
            trip = Trip.query.filter_by(user_id=user_id, title=title).first()
            if trip:
                db.session.delete(trip)
                db.session.commit()
                return jsonify({'success': True, 'message': 'Plan unsaved'}), 200
            else:
                return jsonify({'success': False, 'message': 'Plan not found'}), 404

        # POST - Save daily plan
        if not data or data.get('type') != 'daily_plan':
            return jsonify({'error': 'Invalid trip format'}), 400

        print(f"📥 [Trips API] Received Daily Plan save request: {data.get('title', 'Unknown')} (User: {user_id})")

        # Check if daily plan already exists
        existing_trip = Trip.query.filter_by(
            user_id=user_id,
            title=data.get('title', '未命名行程')
        ).first()

        if existing_trip:
            print(f"⚠️ [Trips API] Daily plan already exists: {data.get('title')}")
            return jsonify({
                'success': True,
                'message': 'Plan already saved',
                'trip_id': existing_trip.id
            }), 200

        # 1. Parse date range
        duration_str = data.get('duration', '3天')
        days_count = extract_days_from_duration(duration_str)

        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=days_count)

        # 2. Create Trip record
        new_trip = Trip(
            user_id=user_id,
            title=data.get('title', '未命名行程'),
            destination=extract_destination_from_title(data.get('title', '')),
            start_date=start_date,
            end_date=end_date,
            budget_limit=extract_budget_from_estimate(data.get('total_budget_estimate', 'N/A')),
            status='planning'
        )
        
        db.session.add(new_trip)
        db.session.flush()

        print(f"✅ [Trips] Daily Plan trip created: {new_trip.title} (ID: {new_trip.id})")

        # 3. Iterate through each day, create TripItems
        days = data.get('days', [])
        items_created = 0

        for day_data in days:
            day_number = day_data.get('day_number', 1)
            activities = day_data.get('activities', [])

            for activity in activities:
                # Parse time
                start_time_str = activity.get('start_time', '09:00')
                end_time_str = activity.get('end_time', '10:00')

                try:
                    start_time = datetime.strptime(start_time_str, "%H:%M").time()
                    end_time = datetime.strptime(end_time_str, "%H:%M").time()
                except:
                    start_time = time(9, 0)
                    end_time = time(10, 0)

                # Get place_id (may be given by AI or need to look up)
                place_id = activity.get('place_id')
                place_name = activity.get('place_name', '')

                # If no place_id, try to find by name
                if not place_id and place_name:
                    place = Place.query.filter_by(name=place_name).first()
                    if place:
                        place_id = place.id

                # Create TripItem
                trip_item = TripItem(
                    trip_id=new_trip.id,
                    place_id=place_id,
                    day_number=day_number,
                    start_time=start_time,
                    end_time=end_time,
                    item_type=activity.get('activity_type', 'activity'),
                    custom_title=place_name,
                    custom_notes=activity.get('description', ''),
                    status='confirmed'
                )
                
                db.session.add(trip_item)
                items_created += 1

        db.session.commit()
        print(f"✅ [Trips] Daily Plan save complete: {len(days)} days, {items_created} activities")

        return jsonify({
            'success': True,
            'message': f'Trip saved ({items_created} activities)',
            'trip_id': new_trip.id
        }), 200

    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'error': f'保存失败: {str(e)}'}), 500


# =========================================================
# Delete trip
# =========================================================
@trips_bp.route('/<int:trip_id>', methods=['DELETE'])
@login_required
def delete_trip(trip_id):
    """
    Delete trip
    """
    try:
        user_id = current_user.id

        trip = Trip.query.filter_by(id=trip_id, user_id=user_id).first()

        if not trip:
            return jsonify({'error': 'Trip does not exist'}), 404

        db.session.delete(trip)
        db.session.commit()

        print(f"✅ [Trips] Trip deleted: {trip.title} (ID: {trip_id})")
        
        return jsonify({'success': True, 'message': '行程已删除'}), 200
    
    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500