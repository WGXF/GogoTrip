# ai_agent.py
import json
import datetime
# [修改] 移除 Groq，导入 Gemini
# from groq import Groq 
import google.generativeai as genai
import sys
import logging

# 从配置导入
import config
# 从外部工具导入
from tools import get_ip_location_info, get_current_weather, search_nearby_places, get_coordinates_for_city
# 从日历逻辑导入
from google_calendar import get_event_details_from_ai, execute_google_calendar_batch

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

# [修改] Gemini 的工具定义 (tools_definition)
# Gemini 期望的格式是一个简单的字典列表，不带 "type": "function" 包装
# ai_agent.py

# [已完全修复] Gemini 的工具定义 (tools_definition)
# 移除了所有 parameters 字典中的顶层 "type": "object"
tools_definition = [
    {
        "name": "create_calendar_events_from_prompt",
        "description": "当用户确认了推荐的地点并要求安排日程时...",
        "parameters": {
            "type": "OBJECT",  # [修复] 必须大写
            "properties": {
                "user_prompt": {
                    "type": "STRING",  # [修复] 必须大写
                    "description": "构造的自然语言日程请求..."
                }
            }, 
            "required": ["user_prompt"]
        }
    },
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
def get_ai_chat_response(conversation_history, credentials_dict, coordinates=None, user_ip=None):
    """
    【AI 代理已激活】
    调用 Google Gemini API，使用一个循环来处理连续的工具调用 (Chain-of-Thought)。
    """
    try:
        # [修改] 1. 配置 Gemini API 密钥
        # 确保您的 config.py 文件中有 GEMINI_API_KEY
        genai.configure(api_key=config.GEMINI_API_KEY)

        # [修改] 2. 格式化 System Prompt
        # (这部分逻辑与 Groq 相同)
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
            "2. **格式化:** *不要* 使用 Markdown 的 `**` 来加粗文本。使用普通的文本进行回复。\n\n"
            "**[!!! 关键工作流程 !!!]**\n"
            "1. **地点搜索 (两步流程):**\n"
            "   - **如果用户提供城市名 (例如 'KL', '吉隆坡'):** 你必须 *首先* 调用 `get_coordinates_for_city` 获取坐标。\n"
            "   - **然后 (或用户询问 '附近'):** 你必须调用 `search_nearby_places`。对于 `location` 参数，*必须* 使用 GPS 坐标 (例如 '{user_location_string}' 或你刚查到的坐标)。\n"
            
            # [!!! 修复：修改了规则 2 !!!]
            "2. **地点翻译规则 (非常重要):**\n"
            "   - 当调用 `search_nearby_places` 时，`query` 参数 *必须* 是一个有效的地点类别。\n"
            "   - 如果用户说 '好吃' 或 '吃的'，*必须* 使用 `query='餐厅'` (Restaurant)。\n"
            "   - **[修复]** 如果用户说 '好玩' 或 '玩的'，*必须* 使用 `query='景点'` (tourist attraction)。\n"
            "   - **绝对不要** 使用 '明点'、'好吃的东西' 或 '景点' 这种查询。\n"
            
            "3. **[!!! 新增：失败重试规则 !!!]**\n" 
            "   - 如果 `search_nearby_places` 工具返回 '未能找到' (ZERO_RESULTS) 的消息，这说明你的 `query` 参数可能是错的。\n"
            "   - 你 *不应该* 重复相同的失败查询。\n"
            "   - 你应该向用户道歉，说明你未能找到（例如）'tourist attraction'，并 *询问用户* 是否想尝试一个不同的词（例如 '公园' (Park) 或 '博物馆' (Museum)）。\n"
            
            "4. **确认规则:** 在推荐地点后，*等待* 用户确认，然后再调用 `Calendars_from_prompt`。 \n"
            
            "5. **[!!! POPUP 规则 (非常重要) !!!]**\n"
            "   - `search_nearby_places` 工具会返回一个 JSON 列表字符串。\n"
            "   - 当你收到这个 JSON 结果时 (例如 `[{'name': ...}]`)，你 *必须* 停止总结。\n"
            "   - 你的 *唯一* 且 *完整* 的回复 *必须* 是 `POPUP_DATA::` 紧接着那个 *未被修改* 的 JSON 字符串。\n"
            "   - **绝对不要** 添加任何其他文本、表情符号或总结。\n"
            "   - **正确示例 (必须这样做):** POPUP_DATA::[{\"name\": \"地点1\"...}, {\"name\": \"地点2\"...}]"
        )
        
        # [修改] 3. 初始化 Gemini 模型
        model = genai.GenerativeModel(
            # 推荐使用 gemini-1.5-pro-latest 来替代 llama-3.3-70b
            model_name='gemini-2.5-flash',
            system_instruction=system_prompt,
            tools=tools_definition,
            generation_config={"temperature": 0.1} # 在这里设置 temperature
        )

        # [修改] 4. 转换历史记录
        # Groq 使用 'assistant', 'user' 和 'content'
        # Gemini 使用 'model', 'user' 和 'parts'
        # 您的 conversation_history 格式 [{'role': 'model', 'parts': [...]}] 
        # 已经*是* Gemini 的格式了！我们只需要清理一下。
        gemini_messages = [msg for msg in conversation_history]
        # 移除开头的空 'model' 消息 (如果有的话)
        if gemini_messages and gemini_messages[0]['role'] == 'model':
            gemini_messages = gemini_messages[1:]

        print(f"--- [聊天日志] 正在调用 Gemini (1.5 Pro)... ---")

        max_turns = 5
        turn_count = 0
            
        while turn_count < max_turns:
            turn_count += 1
            print(f"--- [聊天日志] 正在调用 Gemini (Turn {turn_count})... ---")

            # [!!! 关键 Gemini 变更 !!!]
            # 1. API 调用方式改变
            #    - Groq: client.chat.completions.create(messages=...)
            #    - Gemini: model.generate_content(history=...)
            # 2. tool_choice="auto" 变为 tool_config={"mode": "auto"}
            response = model.generate_content(
                gemini_messages,
                # [修复] tool_config 需要一个 'function_calling_config' 嵌套
                tool_config={"function_calling_config": {"mode": "auto"}}
            )
            
            # 检查是否有有效的响应
            if not response.candidates:
                print("--- [聊天错误] Gemini 未返回任何候选响应。 ---")
                return "抱歉，AI 未能生成响应。"

            # [!!! 关键 Gemini 变更 !!!]
            # 3. 响应结构改变
            #    - Groq: response.choices[0].message
            #    - Gemini: response.candidates[0].content
            response_content = response.candidates[0].content
            
            # 将 Gemini 的回复添加到历史记录中，以便在循环中继续使用
            gemini_messages.append(response_content)

            # [!!! 关键 Gemini 变更 !!!]
            # 4. 工具调用检查和解析
            #    - Groq: if response_message.tool_calls:
            #    - Gemini: if response_content.parts[0].function_call:
            
            # Gemini 目前每次只会返回一个 function_call
            if response_content.parts and response_content.parts[0].function_call:
                print(f"--- [聊天日志] AI 决定调用工具... ---")
                
                tool_call = response_content.parts[0].function_call
                
                # [!!! 关键 Gemini 变更 !!!]
                # 5. 工具参数解析
                #    - Groq: json.loads(tool_call.function.arguments)
                #    - Gemini: 直接从 .args 属性 (一个类字典对象) 中提取
                function_name = tool_call.name
                function_args = {key: value for key, value in tool_call.args.items()}
                
                tool_result_content = ""

                # 6. 真正执行工具! (这部分逻辑与您的原始代码 99% 相同)
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
                        print(f"--- [工具执行] 收到工具调用 (get_current_weather) 参数: {city_or_coords} ---")
                        
                        # === [新增] 智能 GPS 替换逻辑 ===
                        # 如果 AI 传来的参数看起来像是在说“这里”，或者参数为空但我们要查天气
                        # 且我们手头有 GPS 坐标，那就强行使用 GPS。
                        keywords_for_current_location = ["here", "my place", "current location", "me", "这", "这里", "我"]
                        
                        # 检查条件: 
                        # 1. 如果参数完全包含在关键词里 (比如 AI 说 city="here")
                        # 2. 或者我们有 GPS，但 AI 传了个空值
                        if user_location_string and (not city_or_coords or any(k in str(city_or_coords).lower() for k in keywords_for_current_location)):
                             print(f"--- [工具优化] 检测到用户是在问本地天气，自动替换为 GPS: {user_location_string} ---")
                             city_or_coords = user_location_string
                        # ================================

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
                
                # [!!! 关键 Gemini 变更 !!!]
                # 7. 提交工具结果
                #    - Groq: {"role": "tool", "content": ..., "tool_call_id": ...}
                #    - Gemini: {"role": "function", "parts": [{"function_response": {"name": ..., "response": {"content": ...}}}]}
                #    Gemini 不需要 tool_call_id
                gemini_messages.append({
                    "role": "function",
                    "parts": [
                        {"function_response": {
                            "name": function_name,
                            "response": {"content": tool_result_content}
                        }}
                    ]
                })
                
                continue # 继续循环，让 AI 根据工具结果进行下一步
                
            else:
                # [!!! 关键 Gemini 变更 !!!]
                # 8. 提取最终文本回复
                #    - Groq: return response_message.content
                #    - Gemini: return response_content.parts[0].text
                print("--- [聊天日志] AI 决定普通回复 (循环结束)。 ---")
                if response_content.parts and response_content.parts[0].text:
                    return response_content.parts[0].text
                else:
                    return "AI 决定回复，但未能生成文本。"
        
        return "抱歉，AI 代理陷入了思考循环，请重试。"

    except Exception as e:
        print(f"--- [聊天错误] 在 get_ai_chat_response 中捕获到未知异常: {e} ---")
        import traceback
        traceback.print_exc()

        return f"抱歉，AI 代理在处理时遇到了一个错误。请检查服务器日志获取详细信息。错误: {str(e)}"

