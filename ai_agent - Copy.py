# ai_agent.py
import json
import datetime
from groq import Groq

# 从配置导入
import config
# 从外部工具导入
from tools import get_ip_location_info, get_current_weather, search_nearby_places, get_coordinates_for_city
# 从日历逻辑导入
from google_calendar import get_event_details_from_ai, execute_google_calendar_batch

# 定义工具蓝图
tools_definition = [
    {
        "type": "function",
        "function": {
            "name": "create_calendar_events_from_prompt",
            "description": "当用户确认了推荐的地点并要求安排日程时，或用户直接给出完整日程信息时调用。你需要构造一个包含地点名称、地址、日期和时间的自然语言请求。",
            "parameters": {
                "type": "object", "properties": {"user_prompt": {"type": "string", "description": "构造的自然语言日程请求。例如：'安排明天下午2点去[地点名称]在[地址]，大约1小时'"}}, "required": ["user_prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_nearby_places", # <--- 新工具
            "description": "当用户询问附近的地点推荐时调用，例如'附近有什么好吃的'或'明天去哪玩'。你需要提供搜索关键词和用户的位置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索的关键词，例如 '餐厅', '公园', '博物馆'"
                    },
                    "location": {
                        "type": "string",
                        "description": "用户的位置，优先使用 '纬度,经度' 格式。如果 GPS 不可用，可以使用城市名。"
                    }
                },
                "required": ["query", "location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_coordinates_for_city",
            "description": "当用户询问 *特定城市* (例如 '吉隆坡' 或 'KL') 的信息，但你不知道该城市的 GPS 坐标时，*首先* 调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_name": { "type": "string", "description": "要查询坐标的城市名称, 例如 '吉隆坡'" }
                },
                "required": ["city_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "当用户明确指定一个 *城市名称* 并询问天气时调用。",
            "parameters": {
                "type": "object", "properties": {"city": {"type": "string", "description": "城市名称"}}, "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_for_current_location",
            "description": "当用户询问'今天的天气如何'或任何 *没有* 指定城市的本地天气时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]

# ai_agent.py

# ... (imports 和 tools_definition 保持不变) ...

# [修改] AI 代理 - 升级为“循环思考”模式
def get_ai_chat_response(conversation_history, credentials_dict, coordinates=None, user_ip=None):
    """
    【AI 代理已激活】
    调用 Groq API，使用一个循环来处理连续的工具调用 (Chain-of-Thought)。
    """
    try:
        client = Groq(api_key=config.GROQ_API_KEY)

        groq_messages = []
        for index, msg in enumerate(conversation_history):
            role = 'assistant' if msg['role'] == 'model' else 'user'
            if index == 0 and role == 'assistant': continue
            groq_messages.append({'role': role, 'content': msg['parts'][0]})

        # [修改] 关键更新：添加“失败重试规则”
        today_date = (datetime.date.today()).isoformat()
        
        location_info_for_prompt = ""
        user_location_string = None 
        
        if coordinates and coordinates.get('latitude'):
            user_location_string = f"{coordinates.get('latitude')},{coordinates.get('longitude')}"
            location_info_for_prompt = f"用户的 *当前* GPS 坐标是 {user_location_string}。"
        else:
            location_info_for_prompt = "用户的 *当前* GPS 坐标不可用。"

        # 2. 构建新的 System Prompt
        system_prompt = (
            f"你是一个高效的助手。今天是 {today_date}。\n"
            f"**用户上下文:** {location_info_for_prompt}\n\n"
            "**[!!! 关键工作流程 !!!]**\n"
            "1. **地点搜索 (两步流程):**\n"
            "   - **如果用户提供城市名 (例如 'KL', '吉隆坡'):** 你必须 *首先* 调用 `get_coordinates_for_city` 获取坐标。\n"
            "   - **然后 (或用户询问 '附近'):** 你必须调用 `search_nearby_places`。对于 `location` 参数，*必须* 使用 GPS 坐标 (例如 '{user_location_string}' 或你刚查到的坐标)。\n"
            "2. **地点翻译规则 (非常重要):**\n"
            "   - 当调用 `search_nearby_places` 时，`query` 参数 *必须* 是一个有效的地点类别。\n"
            "   - 如果用户说 '好吃' 或 '吃的'，*必须* 使用 `query='餐厅'` (Restaurant)。\n"
            "   - 如果用户说 '好玩' 或 '玩的'，*必须* 使用 `query='景点'` (Tourist Attraction)。\n"
            "   - **绝对不要** 使用 '明点' 或 '好吃的东西' 这种无效查询。\n" # <--- 强化规则
            "3. **[!!! 新增：失败重试规则 !!!]**\n" # <--- 新规则
            "   - 如果 `search_nearby_places` 工具返回 '未能找到' (ZERO_RESULTS) 的消息，这说明你的 `query` 参数可能是错的。\n"
            "   - 你 *不应该* 重复相同的失败查询。\n"
            "   - 你应该向用户道歉，说明你未能找到（例如）'景点'，并 *询问用户* 是否想尝试一个不同的词（例如 '公园' 或 '博物馆'）。\n"
            "4. **确认规则:** 在推荐地点后，*等待* 用户确认，然后再调用 `Calendars_from_prompt`。"
        )
        groq_messages.insert(0, {"role": "system", "content": system_prompt})
        # --- [修改结束] ---

        print(f"--- [聊天日志] 正在调用 Groq (Llama 3)... ---")

        max_turns = 5 
        turn_count = 0
            
        while turn_count < max_turns:
            turn_count += 1
            print(f"--- [聊天日志] 正在调用 Groq (Turn {turn_count})... ---")

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=groq_messages,
                tools=tools_definition,
                tool_choice="auto",
                temperature=0.1
            )
            response_message = response.choices[0].message
            
            groq_messages.append(response_message)

            if response_message.tool_calls:
                print(f"--- [聊天日志] AI 决定调用工具... ---")
                
                tool_call = response_message.tool_calls[0]
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                tool_result_content = ""

                # 5. 真正执行工具!
                if function_name == "get_coordinates_for_city":
                    try:
                        city_name = function_args.get("city_name")
                        print(f"--- [工具执行] 收到工具调用 (get_coordinates_for_city) ---")
                        tool_result_content = get_coordinates_for_city(city_name)
                    except Exception as e:
                        print(f"--- [工具执行错误] {e} ---")
                        tool_result_content = f"执行坐标查询时发生错误: {str(e)}"

                elif function_name == "search_nearby_places":
                     try:
                        query = function_args.get("query")
                        location_from_ai = function_args.get("location") 
                        print(f"--- [工具执行] 收到工具调用 (search_nearby_places) ---")
                        
                        final_location_query = None
                        if location_from_ai and ',' in location_from_ai:
                            final_location_query = location_from_ai
                        elif user_location_string: 
                            final_location_query = user_location_string
                        else:
                            raise ValueError("未能确定搜索地点（AI 未提供坐标，用户 GPS 也不可用）。")
                            
                        print(f"--- [工具执行] 最终搜索 Query: {query}, Location: {final_location_query} ---")
                        tool_result_content = search_nearby_places(query, final_location_query)
                     except Exception as e:
                        print(f"--- [工具执行错误] {e} ---")
                        tool_result_content = f"执行地点搜索时发生错误: {str(e)}"
                
                elif function_name == "create_calendar_events_from_prompt":
                    try:
                        user_prompt_for_tool = function_args.get("user_prompt")
                        print(f"--- [工具执行] 收到工具调用 (create_calendar_events_from_prompt) ---")
                        events_list = get_event_details_from_ai(user_prompt_for_tool)
                        if not events_list: raise ValueError("未能提取任何日程。")
                        tool_result_content = execute_google_calendar_batch(events_list, credentials_dict)
                    except Exception as e: tool_result_content = f"执行日历工具时发生错误: {str(e)}"

                elif function_name == "get_current_weather":
                     try:
                        city_or_coords = function_args.get("city") 
                        print(f"--- [工具执行] 收到工具调用 (get_current_weather) ---")
                        tool_result_content = get_current_weather(city_or_coords)
                     except Exception as e: tool_result_content = f"执行天气查询时发生错误: {str(e)}"

                elif function_name == "get_weather_for_current_location":
                    try:
                        print(f"--- [工具执行] 收到工具调用 (get_weather_for_current_location) ---")
                        query_string = None
                        if user_location_string:
                             query_string = user_location_string
                        else:
                             if user_ip == '127.0.0.1': user_ip = None
                             location_json = get_ip_location_info(ip_address=user_ip)
                             location_data = json.loads(location_json)
                             city = location_data.get('city')
                             if not city: raise ValueError("未能从 IP 检测到城市。")
                             query_string = city
                        print(f"--- [工具执行] 正在查询天气: '{query_string}'...")
                        tool_result_content = get_current_weather(query_string)
                    except Exception as e: tool_result_content = f"执行本地天气查询时发生错误: {str(e)}"

                else:
                    tool_result_content = f"错误：AI 试图调用一个未知的工具 '{function_name}'"

                print(f"--- [工具执行] 工具结果: {tool_result_content} ---")
                groq_messages.append(
                    {
                        "role": "tool",
                        "content": tool_result_content, 
                        "tool_call_id": tool_call.id,
                    }
                )
                
                continue 
                
            else:
                print("--- [聊天日志] AI 决定普通回复 (循环结束)。 ---")
                return response_message.content
        
        return "抱歉，AI 代理陷入了思考循环，请重试。"

    except Exception as e:
        print(f"--- [聊天错误] 在 get_ai_chat_response 中捕获到未知异常: {e} ---")
        import traceback
        traceback.print_exc() 
        return f"抱歉，AI 代理在处理时遇到了一个错误。请检查服务器日志获取详细信息。错误: {str(e)}"