# ai_agent.py
import json
import datetime
import google.generativeai as genai
import sys
import logging

# 从配置导入
import config
# 从外部工具导入 (保留所有非日历的工具)
from tools import get_ip_location_info, get_current_weather, search_nearby_places, get_coordinates_for_city
# from google_calendar import get_event_details_from_ai, execute_google_calendar_batch # 移除日历导入

# 配置日志记录到文件 'app.log'
logging.basicConfig(
    filename='app.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8' # 防止中文乱码
)

# [可选] 让 print() 语句也自动写入日志文件
class LoggerWriter:
    def __init__(self, level):
        self.level = level
    def write(self, message):
        if message.strip():
            self.level(message)
    def flush(self):
        pass

sys.stdout = LoggerWriter(logging.info)
sys.stderr = LoggerWriter(logging.error)

print("--- 日志系统已启动，正在写入 app.log ---")

# [修改] Gemini 的工具定义 (tools_definition) - 移除 create_calendar_events_from_prompt
tools_definition = [
    # 移除 create_calendar_events_from_prompt 工具定义
    # {
    #     "name": "create_calendar_events_from_prompt",
    #     "description": "当用户确认了推荐的地点并要求安排日程时...",
    #     "parameters": {
    #         "type": "OBJECT",  # [修复] 必须大写
    #         "properties": {
    #             "user_prompt": {
    #                 "type": "STRING",  # [修复] 必须大写
    #                 "description": "构造的自然语言日程请求..."
    #             }
    #         }, 
    #         "required": ["user_prompt"]
    #     }
    # },
    {
        "name": "search_nearby_places",
        "description": "当用户询问附近的地点推荐时调用...",
        "parameters": {
            "type": "OBJECT",  # [修复] 必须大写
            "properties": {
                "query": {
                    "type": "STRING",  # [修复] 必须大写
                    "description": "搜索的关键词，例如 '餐厅', '公园', '博物馆'"
                },
                "location": {
                    "type": "STRING",  # [修复] 必须大写
                    "description": "用户的位置，优先使用 '纬度,经度' 格式..."
                }
            },
            "required": ["query", "location"]
        }
    },
    {
        "name": "get_coordinates_for_city",
        "description": "当用户询问 *特定城市* ... *首先* 调用此工具。",
        "parameters": {
            "type": "OBJECT",  # [修复] 必须大写
            "properties": {
                "city_name": { 
                    "type": "STRING",  # [修复] 必须大写
                    "description": "要查询坐标的城市名称, 例如 '吉隆坡'" 
                }
            },
            "required": ["city_name"]
        }
    },
    {
        "name": "get_current_weather",
        "description": "当用户明确指定一个 *城市名称* 并询问天气时调用。",
        "parameters": {
            "type": "OBJECT",  # [修复] 必须大写
            "properties": {
                "city": {
                    "type": "STRING",  # [修复] 必须大写
                    "description": "城市名称"
                }
            }, 
            "required": ["city"]
        }
    },
    {
        "name": "get_weather_for_current_location",
        "description": "当用户询问'今天的天气如何'或任何 *没有* 指定城市的本地天气时调用。",
        "parameters": {
            "type": "OBJECT",  # [修复] 必须大写
            "properties": {}, 
            "required": []
        }
    }
]

# ai_agent.py

# ... (imports 和 tools_definition 已修改) ...

# [修改] AI 代理 - 升级为 Gemini API 和“循环思考”模式
# 移除 credentials_dict 参数，因为不再需要 Google 凭据
def get_ai_chat_response(conversation_history, credentials_dict, coordinates=None, user_ip=None):
    """
    【AI 代理已激活 - 智能拦截版】
    如果检测到 search_nearby_places 返回了有效数据，直接透传给前端，防止 AI 生成错误 JSON。
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)

        today_date = (datetime.date.today()).isoformat()
        location_info_for_prompt = ""
        user_location_string = None
        
        if coordinates and coordinates.get('latitude'):
            user_location_string = f"{coordinates.get('latitude')},{coordinates.get('longitude')}"
            location_info_for_prompt = f"用户的 *当前* GPS 坐标是 {user_location_string}。"
        else:
            location_info_for_prompt = "用户的 *当前* GPS 坐标不可用。"

        system_prompt = (
            f"你是一个高效的助手。今天是 {today_date}。\n"
            f"**用户上下文:** {location_info_for_prompt}\n\n"
            "**[!!! 风格指南 (新) !!!]**\n"
            "1. **表情符号:** 在回复中适当使用表情符号 (emoji) 来使对话更友好、更生动。例如：📍 🍜 🏛️ 🌳 🌙。\n"
            "2. **格式化:** *不要* 使用 Markdown 的 `**` 来加粗文本。请使用直白的文本，或者使用 【标题】 这种方式来强调。\n\n"
            "当用户要求'规划行程'、'推荐方案'或'plan a trip'时，请遵循以下步骤：\n"
            "1. **普通搜索:** 用户问'附近好吃的' -> 调用 `search_nearby_places` 即可。\n"
            "2. **行程规划模式 (核心):**\n"
            "   - 当用户要求'规划行程'、'推荐方案'时，你必须：\n"
            "     a. 先调用 `search_nearby_places` 搜索真实地点（为了获取 photo_reference 和灵感）。\n"
            "     b. **不要**直接输出这些地点。你要基于这些地点，设计 3-5 个不同的**行程方案**。\n"
            "     c. **必须**以 JSON 数组格式输出这些方案，结构必须伪装成地点卡片格式，以便前端渲染：\n"
            "        [\n"
            "          {\n"
            "            \"name\": \"方案1：京都历史古韵5日游\",\n"
            "            \"address\": \"适合人群：历史迷 | 强度：中等\",\n"
            "            \"rating\": 5.0,\n"
            "            \"business_status\": \"PLAN\",\n"  # <--- 关键标签，告诉前端这是个 Plan
            "            \"price_level\": \"PRICE_LEVEL_MODERATE\",\n"
            "            \"photo_reference\": \"...\", (从搜索结果里借用一张好看的图)\n"
            "            \"review_list\": [\"第一天：清水寺...\\n第二天：金阁寺...\"] (把详细行程写在这里)\n"
            "          },\n"
            "          ... (更多方案)\n"
            "        ]\n"
            " - **只输出纯 JSON 文本**。绝对不要使用 Markdown 代码块（即不要使用 ```json 或 ``` 包裹），直接以 [ 开头，以 ] 结尾。\n"
            # "4. **确认规则:** 在推荐地点后，*等待* 用户确认，然后再调用 `Calendars_from_prompt`。 \n"
            "5. **日历规则:** **注意：此应用已禁用日历功能。** 即使用户要求安排日程，也应礼貌地告知用户此功能已被禁用。\n"
        )
        
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=system_prompt,
            tools=tools_definition,
            generation_config={"temperature": 0.1}
        )

        gemini_messages = [msg for msg in conversation_history]
        if gemini_messages and gemini_messages[0]['role'] == 'model':
            gemini_messages = gemini_messages[1:]

        print(f"--- [聊天日志] 正在调用 Gemini (2.5 Flash)... ---")

        max_turns = 15
        turn_count = 0
            
        while turn_count < max_turns:
            turn_count += 1
            print(f"--- [聊天日志] 正在调用 Gemini (Turn {turn_count})... ---")

            response = model.generate_content(
                gemini_messages,
                tool_config={"function_calling_config": {"mode": "auto"}}
            )
            
            if not response.candidates:
                print("--- [聊天错误] Gemini 未返回任何候选响应。 ---")
                return "抱歉，AI 未能生成响应。"

            response_content = response.candidates[0].content
            gemini_messages.append(response_content)

            if response_content.parts and response_content.parts[0].function_call:
                print(f"--- [聊天日志] AI 决定调用工具... ---")
                
                tool_call = response_content.parts[0].function_call
                function_name = tool_call.name
                function_args = {key: value for key, value in tool_call.args.items()}
                
                tool_result_content = ""

                # 6. 真正执行工具!
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
                            raise ValueError("未能确定搜索地点。")
                            
                        print(f"--- [工具执行] 最终搜索 Query: {query}, Location: {final_location_query} ---")
                        tool_result_content = search_nearby_places(query, final_location_query)

                        # ===============================================================
                        # [!!! 智能分流逻辑 !!!]
                        # ===============================================================
                        if tool_result_content and tool_result_content.strip().startswith("["):
                            
                            last_user_msg = ""
                            for m in reversed(conversation_history):
                                if m.get('role') == 'user':
                                    parts = m.get('parts', [])
                                    if isinstance(parts, list) and len(parts) > 0: last_user_msg = str(parts[0])
                                    elif isinstance(parts, str): last_user_msg = parts
                                    break
                            
                            # 关键词：如果包含这些，说明用户要的是“方案”，不是“地点清单”
                            plan_keywords = ["行程", "规划", "安排", "攻略", "玩几天", "日游", "plan", "itinerary", "schedule", "trip", "guide"]
                            is_planning = any(k in last_user_msg.lower() for k in plan_keywords)

                            if is_planning:
                                print(f"--- [智能判断] 用户做攻略 -> 放行给 AI 组装方案卡片 ---")
                                pass  # <--- 关键！放行！让 AI 去处理成方案 JSON
                            else:
                                print("--- [聊天日志] AI 决定普通回复 (循环结束)。 ---")
                                if response_content.parts and response_content.parts[0].text:
                                    ai_text = response_content.parts[0].text.strip()
                                    
                                    # 1. 无论如何，先强制清理 Markdown 标记
                                    clean_text = ai_text.replace("```json", "").replace("```", "").strip()

                                    # 2. 检查清理后的文本是否是 JSON 数组
                                    if clean_text.startswith("[") and clean_text.endswith("]"):
                                        print("--- [系统] 检测到 AI 生成了 JSON 方案，正在转换为卡片模式... ---")
                                        # 返回清理后的纯 JSON 给前端
                                        return f"POPUP_DATA::{clean_text}"
                                    
                                    # 如果不是 JSON，返回原始文本
                                    return ai_text
                                else:
                                    return "AI 决定回复，但未能生成文本。"
                        # ===============================================================

                    except Exception as e:
                        print(f"--- [工具执行错误] {e} ---")
                        tool_result_content = f"执行地点搜索时发生错误: {str(e)}"
                
                # 移除 create_calendar_events_from_prompt 的执行逻辑
                # elif function_name == "create_calendar_events_from_prompt":
                #     ... (移除) ...

                elif function_name == "get_current_weather":
                    try:
                        city_or_coords = function_args.get("city")
                        # 智能 GPS 替换逻辑
                        keywords_for_current_location = ["here", "my place", "current location", "me", "这", "这里", "我"]
                        if user_location_string and (not city_or_coords or any(k in str(city_or_coords).lower() for k in keywords_for_current_location)):
                             city_or_coords = user_location_string

                        print(f"--- [工具执行] 收到工具调用 (get_current_weather) 参数: {city_or_coords} ---")
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
                
                gemini_messages.append({
                    "role": "function",
                    "parts": [
                        {"function_response": {
                            "name": function_name,
                            "response": {"content": tool_result_content}
                        }}
                    ]
                })
                
                continue 
                
            else:
                print("--- [聊天日志] AI 决定普通回复 (循环结束)。 ---")
                if response_content.parts and response_content.parts[0].text:
                    ai_text = response_content.parts[0].text.strip()
                    
                    # [!!! 核心修改 !!!]
                    # 如果 AI 输出的是 JSON 数组（看起来像是方案卡片），
                    # 我们就给它加上魔法前缀，强制前端弹窗显示！
                    if ai_text.startswith("[") and ai_text.endswith("]"):
                        print("--- [系统] 检测到 AI 生成了 JSON 方案，正在转换为卡片模式... ---")
                        # 清理可能存在的 Markdown 标记
                        clean_json = ai_text.replace("```json", "").replace("```", "").strip()
                        return f"POPUP_DATA::{clean_json}"
                    
                    return ai_text
                else:
                    return "AI 决定回复，但未能生成文本。"        
        return "抱歉，AI 代理陷入了思考循环，请重试。"

    except Exception as e:
        print(f"--- [聊天错误] 在 get_ai_chat_response 中捕获到未知异常: {e} ---")
        import traceback
        traceback.print_exc()

        return f"抱歉，AI 代理在处理时遇到了一个错误。请检查服务器日志获取详细信息。错误: {str(e)}"