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
# 🆕 新增：导出行程到 Google Calendar
# =========================================================
@trips_bp.route('/<int:trip_id>/export_calendar', methods=['POST', 'GET'])
@login_required
def export_to_calendar(trip_id):
    """
    将行程导出到 Google Calendar
    
    完整路径: POST /trips/<trip_id>/export_calendar
    
    Request Body (可选):
    {
        "start_date": "2024-01-15"  // 行程开始日期，默认为今天
    }
    
    Returns:
    {
        "status": "success",
        "message": "已导出 X 个日程",
        "events_exported": X
    }
    """
    # 检查 Google Calendar 授权
    if 'credentials' not in session:
        return jsonify({
            'error': '未授权 Google Calendar',
            'redirect': '/auth/authorize'
        }), 401
    
    user_id = current_user.id
    
    try:
        # 1. 获取行程信息
        trip = Trip.query.filter_by(id=trip_id, user_id=user_id).first()
        
        if not trip:
            return jsonify({'error': '行程不存在'}), 404
        
        # 2. 解析开始日期
        if request.is_json and request.json:
            start_date_str = request.json.get('start_date')
        else:
            start_date_str = request.args.get('start_date')
        
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
        else:
            start_date = trip.start_date or datetime.now().date()
        
        # 3. 获取行程中的所有项目
        trip_items = TripItem.query.filter_by(trip_id=trip_id).order_by(
            TripItem.day_number, TripItem.start_time
        ).all()
        
        if not trip_items:
            return jsonify({
                'status': 'success',
                'message': '行程中没有可导出的项目',
                'events_exported': 0
            }), 200
        
        # 4. 连接 Google Calendar
        credentials = Credentials(**session['credentials'])
        service = build('calendar', 'v3', credentials=credentials)
        
        events_created = 0
        
        # 5. 为每个行程项创建日历事件
        for item in trip_items:
            # 计算实际日期
            day_offset = (item.day_number or 1) - 1
            event_date = start_date + timedelta(days=day_offset)
            
            # 解析时间 - 确保是字符串格式 HH:MM
            if item.start_time:
                if hasattr(item.start_time, 'strftime'):
                    start_time_str = item.start_time.strftime("%H:%M")
                else:
                    start_time_str = str(item.start_time)[:5]  # 取前5字符 "09:00"
            else:
                start_time_str = "09:00"
            
            if item.end_time:
                if hasattr(item.end_time, 'strftime'):
                    end_time_str = item.end_time.strftime("%H:%M")
                else:
                    end_time_str = str(item.end_time)[:5]
            else:
                end_time_str = _calculate_end_time(start_time_str)
            
            # 获取地点名称
            place_name = ''
            if item.place_id:
                place = Place.query.get(item.place_id)
                if place:
                    place_name = place.name
            
            # 构建事件标题 - 优先使用 custom_title，然后 place_name，最后 custom_notes
            event_title = f"🗺️ {trip.title} - Day {item.day_number}"
            if hasattr(item, 'custom_title') and item.custom_title:
                event_title = f"📍 {item.custom_title}"
            elif place_name:
                event_title = f"📍 {place_name}"
            elif item.custom_notes:
                event_title = f"🗺️ {item.custom_notes[:50]}"
                        
            # 构建事件描述
            description_parts = [
                f"行程: {trip.title}",
                f"第 {item.day_number} 天",
            ]

            if hasattr(item, 'custom_title') and item.custom_title:
                description_parts.append(f"活动: {item.custom_title}")
            if place_name:
                description_parts.append(f"地点: {place_name}")
            if item.custom_notes:
                description_parts.append(f"备注: {item.custom_notes}")
            
            # 创建日历事件
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
            
            # 如果有地点坐标，添加位置信息
            if item.place_id:
                place = Place.query.get(item.place_id)
                if place and place.address:
                    event_body['location'] = place.address
            
            try:
                service.events().insert(calendarId='primary', body=event_body).execute()
                events_created += 1
                print(f"✅ [Calendar Export] 创建事件: {event_title}")
            except Exception as e:
                print(f"⚠️ [Calendar Export] 创建事件失败: {e}")
                continue
        
        # 6. 更新行程状态（可选）
        trip.status = 'active'
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': f'成功导出 {events_created} 个日程到 Google Calendar',
            'events_exported': events_created,
            'start_date': start_date.isoformat()
        }), 200
    
    except Exception as e:
        print(f"❌ [Calendar Export Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'导出失败: {str(e)}'}), 500


def _calculate_end_time(start_time: str, duration_hours: int = 2) -> str:
    """计算结束时间（默认活动时长2小时）"""
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
# 保存行程
# =========================================================
@trips_bp.route('/save', methods=['POST'])
@login_required
def save_trip():
    """
    保存行程到数据库
    """
    try:
        user_id = current_user.id
        
        data = request.json
        print(f"📥 [Trips API] 收到保存请求: {data.get('title', 'Unknown')} (User: {user_id})")
        
        # 判断保存的类型
        is_itinerary = 'itinerary' in data and isinstance(data['itinerary'], list)
        
        if is_itinerary:
            trip_data = save_full_itinerary(user_id, data)
        else:
            trip_data = save_single_place(user_id, data)
        
        return jsonify({
            'success': True,
            'message': '行程已保存',
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
    保存完整行程方案到数据库
    """
    # 1. 解析日期范围
    duration_str = data.get('duration', '3天')
    days_count = extract_days_from_duration(duration_str)

    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=days_count)
    
    # 2. 创建 Trip 记录
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
    
    print(f"✅ [Trips] 创建行程: {new_trip.title} (ID: {new_trip.id})")
    
    # 3. 遍历行程的每一天，创建 TripItem
    itinerary = data.get('itinerary', [])
    
    for day_plan in itinerary:
        day_number = day_plan.get('day', 1)
        items = day_plan.get('items', [])
        
        for item in items:

            raw_time = item.get('time', '09:00')
            start_time = datetime.strptime(raw_time, "%H:%M").time()

            activity_name = item.get('activity', '')
            
            # 查找或创建 Place 记录
            place = Place.query.filter_by(name=activity_name).first()
            place_id = place.id if place else None
            
            if not place:
                print(f"⚠️ [Warning] 地点 '{activity_name}' 不在数据库中，跳过 place_id")
            
            # 创建 TripItem
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
    print(f"✅ [Trips] 成功保存 {len(itinerary)} 天行程")
    
    return {
        'trip_id': new_trip.id,
        'type': 'full_itinerary'
    }


def save_single_place(user_id: int, data: dict):
    """
    保存单个地点到行程 (创建一个简单的行程)
    """
    # 1. 查找地点
    place_name = data.get('title', data.get('name', ''))
    place = Place.query.filter_by(name=place_name).first()
    
    if not place:
        print(f"⚠️ [Warning] 地点 '{place_name}' 不在数据库中")
        place = create_place_from_data(data)
    
    # 2. 创建一个简单的 Trip
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
    
    # 3. 创建 TripItem
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
    
    print(f"✅ [Trips] 成功保存单个地点: {place_name}")
    
    return {
        'trip_id': new_trip.id,
        'type': 'single_place'
    }


def create_place_from_data(data: dict):
    """
    从前端数据创建 Place 记录
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
    
    print(f"✅ [Places] 创建新地点: {new_place.name} (ID: {new_place.id})")
    
    return new_place


# =========================================================
# 工具函数
# =========================================================
def extract_days_from_duration(duration_str: str) -> int:
    """从 '3天2夜' 或 '5 Days' 中提取天数"""
    match = re.search(r'(\d+)', duration_str)
    return int(match.group(1)) if match else 3


def extract_destination_from_title(title: str) -> str:
    """从标题中提取目的地"""
    for suffix in ['游', '行程', '之旅', 'Trip', 'Tour']:
        title = title.replace(suffix, '')
    return title.strip()[:50]


def extract_budget_from_estimate(estimate_str: str) -> float:
    """从 'RM 1,500 - RM 2,500' 中提取预算上限"""
    numbers = re.findall(r'[\d,]+', estimate_str)
    if numbers:
        values = [float(n.replace(',', '')) for n in numbers]
        return max(values)
    return 0.0


# =========================================================
# 获取行程列表
# =========================================================
@trips_bp.route('/list', methods=['GET'])
@login_required
def list_trips():
    """
    获取用户的所有行程
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
# 获取单个行程详情
# =========================================================
@trips_bp.route('/<int:trip_id>', methods=['GET'])
@login_required
def get_trip_details(trip_id):
    """
    获取单个行程的详细信息（包括所有 TripItems）
    """
    try:
        user_id = current_user.id
        
        trip = Trip.query.filter_by(id=trip_id, user_id=user_id).first()
        
        if not trip:
            return jsonify({'error': '行程不存在'}), 404
        
        # 获取所有行程项
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
# 🆕 保存新格式的 Daily Plan (AI 生成的结构化行程)
# =========================================================
@trips_bp.route('/save_daily_plan', methods=['POST'])
@login_required
def save_daily_plan():
    """
    保存 AI 生成的结构化 Daily Plan 到数据库
    
    新格式包含:
    - type: "daily_plan"
    - days: 多天行程数组
    - 每天包含 top_locations 和 activities
    - 每个 activity 关联 place_id
    """
    try:
        user_id = current_user.id
        data = request.json
        
        if not data or data.get('type') != 'daily_plan':
            return jsonify({'error': '无效的行程格式'}), 400
        
        print(f"📥 [Trips API] 收到 Daily Plan 保存请求: {data.get('title', 'Unknown')} (User: {user_id})")
        
        # 1. 解析日期范围
        duration_str = data.get('duration', '3天')
        days_count = extract_days_from_duration(duration_str)
        
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=days_count)
        
        # 2. 创建 Trip 记录
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
        
        print(f"✅ [Trips] 创建 Daily Plan 行程: {new_trip.title} (ID: {new_trip.id})")
        
        # 3. 遍历每一天，创建 TripItems
        days = data.get('days', [])
        items_created = 0
        
        for day_data in days:
            day_number = day_data.get('day_number', 1)
            activities = day_data.get('activities', [])
            
            for activity in activities:
                # 解析时间
                start_time_str = activity.get('start_time', '09:00')
                end_time_str = activity.get('end_time', '10:00')
                
                try:
                    start_time = datetime.strptime(start_time_str, "%H:%M").time()
                    end_time = datetime.strptime(end_time_str, "%H:%M").time()
                except:
                    start_time = time(9, 0)
                    end_time = time(10, 0)
                
                # 获取 place_id (可能是 AI 给的，也可能需要查找)
                place_id = activity.get('place_id')
                place_name = activity.get('place_name', '')
                
                # 如果没有 place_id，尝试通过名称查找
                if not place_id and place_name:
                    place = Place.query.filter_by(name=place_name).first()
                    if place:
                        place_id = place.id
                
                # 创建 TripItem
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
        print(f"✅ [Trips] Daily Plan 保存完成: {len(days)} 天, {items_created} 个活动")
        
        return jsonify({
            'success': True,
            'message': f'行程已保存 ({items_created} 个活动)',
            'trip_id': new_trip.id
        }), 200
        
    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'error': f'保存失败: {str(e)}'}), 500


# =========================================================
# 删除行程
# =========================================================
@trips_bp.route('/<int:trip_id>', methods=['DELETE'])
@login_required
def delete_trip(trip_id):
    """
    删除行程
    """
    try:
        user_id = current_user.id
        
        trip = Trip.query.filter_by(id=trip_id, user_id=user_id).first()
        
        if not trip:
            return jsonify({'error': '行程不存在'}), 404
        
        db.session.delete(trip)
        db.session.commit()
        
        print(f"✅ [Trips] 删除行程: {trip.title} (ID: {trip_id})")
        
        return jsonify({'success': True, 'message': '行程已删除'}), 200
    
    except Exception as e:
        print(f"❌ [Trips API Error] {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500