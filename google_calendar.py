# google_calendar.py
import datetime
import json
import re
import time

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.generativeai as genai

# 从配置导入
import config
# 从工具导入
from utils import is_valid_email

def get_event_details_from_ai(user_input):
    """
    【可重用函数】
    [已修改] 调用 Google Gemini API 来将自然语言 *解析为 JSON*。
    """
    try:
        # [修改] 1. 配置 Gemini 客户端
        genai.configure(api_key=config.GEMINI_API_KEY)
        
        # [修改] 2. 初始化 Gemini 模型
        # 我们将告诉 Gemini 它必须返回 JSON
        model = genai.GenerativeModel(
            'gemini-2.5-flash',
            generation_config={"response_mime_type": "application/json"} # 关键：强制 JSON 输出
        )
        # 启动一个聊天会话，因为我们需要一个系统提示
        chat = model.start_chat()

    except Exception as e:
        print(f"--- [错误] Gemini 客户端初始化失败: {e} ---")
        raise ConnectionError("Gemini API 密钥或客户端配置错误。") from e

    tomorrow_date = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    system_prompt = f"""
    你是一个日程安排助手。从用户输入中提取所有日程，并输出一个JSON对象。
    - 根元素必须是一个JSON对象，包含一个键 "events"，其值是一个JSON数组。
    - 每个数组元素(日程)是一个JSON对象，包含: "summary", "description", "start_time", "end_time"。
    - (可选) 如果用户提到了参与者，请添加 "attendees" 键，值为一个包含邮箱字符串的数组。
    - **关键指令**: 'summary' 应该是简短标题。'description' 是补充说明。
    - "start_time" 和 "end_time" 必须是 ISO 8601 格式。
    - **重要规则**: 如果用户输入中没有明确指定日期，请默认所有日程都发生在明天 ({tomorrow_date})。
    - 你的回答只能是JSON对象。
    """
    
    # [修改] 3. 构建发送给 Gemini 的消息
    # Gemini 的 JSON 模式在使用 system_instruction 时效果不佳，
    # 我们使用一个包含系统和用户角色的完整提示。
    full_prompt = f"{system_prompt}\n\n**用户输入:**\n{user_input}"

    print(f"--- [日志] 正在连接 Gemini API (JSON 模式)... ---")

    try:
        # [修改] 4. 调用 Gemini API
        response = model.generate_content(full_prompt)

        # [修改] 5. 解析响应
        ai_response_str = response.text
        print(f"--- [日志] AI 模型返回的原始JSON: {ai_response_str} ---")

        parsed_data = json.loads(ai_response_str)
        events_list = parsed_data.get('events')

        if isinstance(events_list, list):
            print(f"--- [日志] 成功解析出 JSON，包含 {len(events_list)} 个日程 ---")
            return events_list
        else:
            raise ValueError("AI返回的JSON中没有找到 'events' 列表。")

    except Exception as e:
        print(f"--- [错误] 调用或解析 AI (JSON 模式) 时发生错误: {e} ---")
        raise

def execute_google_calendar_batch(events_list, credentials_dict):
    """
    【可重用函数】
    接收一个日程列表和凭据字典，执行 Google API 批量创建。
    返回一个包含成功/失败信息的字符串。
    """
    if not isinstance(events_list, list) or not events_list:
        return "错误：没有提供有效的日程列表。"

    print(f"--- [工具执行] === 开始执行 Google 日历批量创建... === ---")
    success_messages = []
    error_messages = []

    try:
        credentials = Credentials(**credentials_dict)
        service = build('calendar', 'v3', credentials=credentials)

        def batch_callback(request_id, response, exception):
            if exception:
                print(f"--- [错误] 批量请求失败 (ID: {request_id}): {exception} ---")
                error_messages.append(f"<li>失败: '{request_id}' - 错误: {exception}</li>")
            else:
                event_link = response.get('htmlLink')
                print(f"--- [日志] 批量请求成功 (ID: {request_id}) ---")
                success_messages.append(f"<li>成功: '{request_id}' <a href='{event_link}' target='_blank'>查看</a></li>")

        batch = service.new_batch_http_request(callback=batch_callback)

        for index, event_data in enumerate(events_list):
            summary_original = event_data.get('summary', '未知标题')
            try:
                summary = event_data.get('summary')
                description = event_data.get('description')
                if not summary and description:
                    generated_summary = re.split(r'[。；，,.!！?？\n]', description)[0]
                    summary = (generated_summary[:47] + '...') if len(generated_summary) > 50 else generated_summary
                    event_data['summary'] = summary
                if not all(event_data.get(key) for key in ['summary', 'start_time', 'end_time']):
                    raise ValueError("日程缺少'summary', 'start_time', 或 'end_time'等关键信息。")

                attendee_emails = set()
                ai_attendees = event_data.get('attendees', [])
                if isinstance(ai_attendees, list):
                    for email in ai_attendees:
                        if is_valid_email(email):
                            attendee_emails.add(email)
                valid_attendees_list = [{'email': email} for email in attendee_emails]

                event_body = {
                    'summary': event_data['summary'],
                    'location': event_data.get('location', ''),
                    'description': event_data.get('description', ''),
                    'start': {'dateTime': event_data['start_time'], 'timeZone': config.TIMEZONE},
                    'end': {'dateTime': event_data['end_time'], 'timeZone': config.TIMEZONE},
                    'attendees': valid_attendees_list,
                    'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 10}]},
                }
                batch.add(
                    service.events().insert(calendarId='primary', body=event_body, sendNotifications=True),
                    request_id=summary
                )
            except Exception as e:
                error_messages.append(f"<li>失败: '{summary_original}' - 错误 (准备阶段): {e}</li>")
                print(f"--- [错误] 准备单个日程时出错: {e} ---")

        if len(events_list) > 0:
            print(f"--- [日志] === 正在执行批量请求... === ---")
            batch.execute()
            print("--- [日志] === 批量请求执行完毕 === ---")
        else:
            print("--- [日志] 没有有效的日程可供批量处理 ---")

    except Exception as e:
        print(f"--- [工具执行错误] {e} ---")
        return f"创建日程失败 (在执行批量操作时): {str(e)}"

    num_success = len(success_messages)
    num_errors = len(error_messages)
    if num_errors == 0 and num_success > 0:
        final_message = f'您的 {num_success} 个日程已全部成功创建！'
    else:
        final_message = "<h3>日程创建结果:</h3>"
        if success_messages:
            final_message += f"<h4>成功 ({num_success}):</h4><ul>" + "".join(success_messages) + "</ul>"
        if error_messages:
            final_message += f"<h4>失败 ({num_errors}):</h4><ul>" + "".join(error_messages) + "</ul>"
    return final_message