# routes/calendar.py
import time
import datetime
from flask import Blueprint, request, session, redirect, url_for
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config
from google_calendar import get_event_details_from_ai, execute_google_calendar_batch

calendar_bp = Blueprint('calendar', __name__)

@calendar_bp.route('/create_event', methods=['POST'])
def create_event():
    if 'credentials' not in session:
        return redirect(url_for('auth.authorize')) # 重定向到认证蓝图的 authorize

    start_time_total = time.time()
    user_prompt = request.form['user_prompt']

    print(f"\n\n--- [日志] === 开始批量创建新日程流程 (用户输入: '{user_prompt}') === ---")

    try:
        events_list = get_event_details_from_ai(user_prompt)
        final_message = execute_google_calendar_batch(
            events_list,
            session['credentials']
        )
    except Exception as e:
        session['message'] = f"创建日程失败: {str(e)}"
        print(f"--- [错误] 在 /create_event 流程中捕获到未知异常: {e} ---")
        return redirect(url_for('main.index'))

    end_time_total = time.time()
    total_duration = end_time_total - start_time_total
    final_message += f"<br><br><small style='color: #555;'>总执行时间: {total_duration:.2f} 秒</small>"
    print(f"--- [日志] 总执行时间: {total_duration:.2f} 秒 ---")

    session['message'] = final_message
    return redirect(url_for('main.index'))

@calendar_bp.route('/list_events')
def list_events():
    if 'credentials' not in session:
        return redirect(url_for('auth.authorize'))
    credentials = Credentials(**session['credentials'])
    try:
        service = build('calendar', 'v3', credentials=credentials)
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        if not events:
            return '<h1>您的日历中没有即将到来的事件。</h1><a href="/">返回首页</a>' # 可以链接回 main.index
        output_html = '<h1>您接下来的10个日程：</h1><ul>'
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            output_html += f'<li>{start} - {event["summary"]}</li>'
        output_html += '</ul><a href="/">返回首页</a>' # 可以链接回 main.index
        return output_html
    except Exception as e:
        print(f"调用 API 时发生错误: {e}")
        # 可以重定向回 auth.authorize 让用户重新授权
        return f"<h1>调用 API 时发生错误</h1><p>{e}</p><a href=\"{url_for('auth.authorize')}\">请尝试重新授权</a>"