# routes/calendar.py
import datetime
import time
from flask import Blueprint, request, session, jsonify, redirect, url_for
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dateutil import parser # 确保安装了: pip install python-dateutil

import config
from models import db, CalendarEvent
# 引入你原本的 AI 处理函数
from google_calendar import get_event_details_from_ai, execute_google_calendar_batch

calendar_bp = Blueprint('calendar', __name__)

# =========================================================
# 辅助函数：执行同步 (Google -> 本地 DB)
# =========================================================
def perform_sync_logic(user_id, credentials_dict):
    """
    这是一个内部函数，用于从 Google 拉取数据并存入数据库。
    它可以被 /sync 接口调用，也可以被 /create_event (AI) 调用。
    """
    credentials = Credentials(**credentials_dict)
    service = build('calendar', 'v3', credentials=credentials)
    
    # 同步范围：过去3个月 ~ 未来 (根据需要调整)
    now = datetime.datetime.utcnow()
    time_min = (now - datetime.timedelta(days=90)).isoformat() + 'Z'
    
    print(f"--- [Sync] 正在为用户 {user_id} 执行同步... ---")
    
    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        maxResults=100,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    
    google_events = events_result.get('items', [])
    sync_count = 0
    
    for g_event in google_events:
        g_id = g_event.get('id')
        summary = g_event.get('summary', '无标题')
        
        # 处理时间 (兼容 dateTime 和 date)
        start_raw = g_event['start'].get('dateTime', g_event['start'].get('date'))
        end_raw = g_event['end'].get('dateTime', g_event['end'].get('date'))
        
        try:
            start_dt = parser.parse(start_raw)
            end_dt = parser.parse(end_raw)
            
            # 处理全天事件和时区
            if not isinstance(start_dt, datetime.datetime):
                start_dt = datetime.datetime.combine(start_dt, datetime.time.min)
            if not isinstance(end_dt, datetime.datetime):
                end_dt = datetime.datetime.combine(end_dt, datetime.time.min)
            
            start_dt = start_dt.replace(tzinfo=None)
            end_dt = end_dt.replace(tzinfo=None)
            
        except Exception as e:
            print(f"跳过时间解析错误: {e}")
            continue

        # 存入/更新数据库
        existing_event = CalendarEvent.query.filter_by(user_id=user_id, google_event_id=g_id).first()
        
        if existing_event:
            existing_event.title = summary
            existing_event.start_time = start_dt
            existing_event.end_time = end_dt
            existing_event.sync_status = 'synced'
        else:
            new_event = CalendarEvent(
                user_id=user_id,
                google_event_id=g_id,
                title=summary,
                start_time=start_dt,
                end_time=end_dt,
                sync_status='synced'
            )
            db.session.add(new_event)
        
        sync_count += 1

    db.session.commit()
    print(f"--- [Sync] 同步完成，更新了 {sync_count} 条数据 ---")
    return sync_count

# =========================================================
# 1. 接口：获取本地日程 (前端加载时调用)
# =========================================================
@calendar_bp.route('/calendar/events', methods=['GET'])
def get_local_events():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': '未登录'}), 401

    try:
        # 只查本地数据库，速度极快
        events_db = CalendarEvent.query.filter_by(user_id=user_id).all()
        events_list = []
        for ev in events_db:
            events_list.append({
                'id': str(ev.id),
                'google_event_id': ev.google_event_id,
                'title': ev.title,
                'startTime': ev.start_time.isoformat() if ev.start_time else None,
                'endTime': ev.end_time.isoformat() if ev.end_time else None,
                'type': 'activity', 
                'sync_status': ev.sync_status
            })
        return jsonify(events_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =========================================================
# 2. 接口：手动触发同步 (点击 Sync 按钮时调用)
# =========================================================
@calendar_bp.route('/calendar/sync', methods=['POST'])
def sync_events_endpoint():
    if 'credentials' not in session:
        return jsonify({'error': '未授权'}), 401
    user_id = session.get('user_id')
    
    try:
        count = perform_sync_logic(user_id, session['credentials'])
        return jsonify({'status': 'success', 'count': count})
    except Exception as e:
        print(f"同步失败: {e}")
        return jsonify({'error': str(e)}), 500

# =========================================================
# 3. 接口：AI Agent 创建日程 (支持自然语言)
# =========================================================
@calendar_bp.route('/create_event', methods=['POST'])
def create_event_ai():
    """
    这就是你原本的 AI 接口，经过修改以适配数据库架构。
    流程：
    1. 接收 user_prompt (例如 "明天下午3点开会")
    2. AI 解析 -> Google Calendar 创建 (使用你原本的逻辑)
    3. **自动执行一次同步** -> 把新日程存入本地数据库
    """
    if 'credentials' not in session:
        # 如果是 API 调用，最好返回 JSON 401，而不是 redirect
        return jsonify({'error': '未授权 Google Calendar'}), 401

    user_id = session.get('user_id')
    
    # 兼容 JSON 请求 (React) 和 Form 请求 (你的旧代码)
    if request.is_json:
        user_prompt = request.json.get('user_prompt')
    else:
        user_prompt = request.form.get('user_prompt')

    if not user_prompt:
        return jsonify({'error': '内容为空'}), 400

    print(f"\n--- [AI Calendar] 开始处理用户输入: '{user_prompt}' ---")

    try:
        # 1. 调用你的 AI 工具解析 (google_calendar.py)
        events_list = get_event_details_from_ai(user_prompt)
        
        # 2. 批量写入 Google Calendar (google_calendar.py)
        # 注意：这里我们只拿 message，实际上 execute_google_calendar_batch 会直接操作 Google API
        final_message = execute_google_calendar_batch(
            events_list,
            session['credentials']
        )
        
        # 3. [关键步骤] 写入成功后，立刻同步回本地数据库！
        # 这样前端刷新时，就能从数据库里读到刚刚 AI 创建的日程了
        perform_sync_logic(user_id, session['credentials'])

        return jsonify({
            'status': 'success', 
            'message': final_message,
            'ai_events': events_list # 返回给前端看一眼
        })

    except Exception as e:
        print(f"AI 创建日程失败: {e}")
        return jsonify({'error': f"AI 处理失败: {str(e)}"}), 500

# =========================================================
# 4. 接口：手动删除日程 (可选)
# =========================================================
@calendar_bp.route('/calendar/delete/<int:local_id>', methods=['DELETE'])
def delete_event(local_id):
    if 'credentials' not in session:
        return jsonify({'error': '未授权'}), 401
    user_id = session.get('user_id')
    
    try:
        # 1. 找本地记录
        event = CalendarEvent.query.filter_by(id=local_id, user_id=user_id).first()
        if not event:
            return jsonify({'error': '找不到该日程'}), 404
            
        # 2. 去 Google 删除
        if event.google_event_id:
            creds = Credentials(**session['credentials'])
            service = build('calendar', 'v3', credentials=creds)
            try:
                service.events().delete(calendarId='primary', eventId=event.google_event_id).execute()
            except Exception as e:
                print(f"Google 端删除警告: {e}") # 也许 Google 端已经被删了，忽略错误
        
        # 3. 删本地数据库
        db.session.delete(event)
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': '删除成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@calendar_bp.route('/calendar/add_manual', methods=['POST'])       
def add_event_manual():
    if 'credentials' not in session:
        return jsonify({'error': '未授权'}), 401
    
    user_id = session.get('user_id')
    data = request.json
    
    title = data.get('title')
    start_str = data.get('startTime') # ISO 格式: "2023-10-20T09:00:00"
    end_str = data.get('endTime')
    
    if not all([title, start_str, end_str]):
        return jsonify({'error': '缺少必要信息'}), 400

    try:
        credentials = Credentials(**session['credentials'])
        service = build('calendar', 'v3', credentials=credentials)
        
        # 1. Google Calendar API 要求的格式
        event_body = {
            'summary': title,
            'start': {
                'dateTime': start_str,
                'timeZone': config.TIMEZONE, 
            },
            'end': {
                'dateTime': end_str,
                'timeZone': config.TIMEZONE, 
            }
        }
        
        # 2. 调用 Google 创建
        g_event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        # 3. 解析时间存入数据库
        start_dt = parser.parse(start_str).replace(tzinfo=None)
        end_dt = parser.parse(end_str).replace(tzinfo=None)

        new_event = CalendarEvent(
            user_id=user_id,
            google_event_id=g_event.get('id'),
            title=title,
            start_time=start_dt,
            end_time=end_dt,
            sync_status='synced'
        )
        db.session.add(new_event)
        db.session.commit()
        
        return jsonify({'status': 'success', 'event': {
            'id': str(new_event.id),
            'title': new_event.title
        }})

    except Exception as e:
        print(f"手动创建日程失败: {e}")
        return jsonify({'error': str(e)}), 500