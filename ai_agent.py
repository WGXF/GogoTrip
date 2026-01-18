# ai_agent.py
"""
GogoTrip AI Agent - 智能日程规划助手 (MVP Optimized)

优化重点:
- 速度优先：减少 AI 推理深度
- 简化流程：减少工具调用次数
- 允许 place_id 为 null：先生成行程，后续再关联数据库
"""

import json
import datetime
import google.generativeai as genai
import sys
import logging

import config
from tools import (
    get_ip_location_info, 
    get_current_weather, 
    search_nearby_places, 
    get_coordinates_for_city,
    query_places_from_db
)

logging.basicConfig(
    filename='app.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)


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

print("--- App log enabled, now writing to app.log ---")

# ============ FAST MODE: Simplified itinerary generation ============
def get_fast_itinerary_response(destination: str, duration: str, preferences: dict, language: str = 'en'):
    """
    快速生成行程 - 不使用工具调用，直接让 AI 生成结构化 JSON
    用于 MVP 阶段，优先速度而非精确的 place_id 关联
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        
        today_date = datetime.date.today().isoformat()
        
        # Extract preferences
        mood = preferences.get('mood', 'relaxed')
        budget = preferences.get('budget', 'medium')
        transport = preferences.get('transport', 'public')
        dietary = preferences.get('dietary', [])
        companions = preferences.get('companions', 'friends')
        
        # Determine activities per day based on mood
        activities_per_day = "3-4" if mood in ['relaxed', 'family'] else "5-6"
        
        # 🆕 Get full language name
        response_language = LANGUAGE_FULL_NAMES.get(language, 'English')
        
        fast_prompt = f"""Generate a {duration} travel itinerary for {destination}.

USER PREFERENCES:
- Mood: {mood} ({activities_per_day} activities per day)
- Budget: {budget}
- Transport: {transport}
- Dietary: {', '.join(dietary) if dietary else 'No restrictions'}
- Traveling with: {companions}

*** CRITICAL: RESPONSE LANGUAGE ***
You MUST respond in {response_language}. All title, description, and content MUST be written in {response_language}.
- If "Chinese (Simplified)", use 简体中文.
- If "Bahasa Melayu (Malay)", use Bahasa Melayu.

OUTPUT: Return ONLY valid JSON (no markdown, no explanation). Start with {{

JSON SCHEMA:
{{
  "type": "daily_plan",
  "title": "Trip title in user's language",
  "description": "Brief description",
  "duration": "{duration}",
  "total_budget_estimate": "RM X - RM Y",
  "tags": ["tag1", "tag2", "tag3"],
  "cover_image": "https://images.unsplash.com/photo-RELEVANT_DESTINATION_PHOTO",
  "user_preferences_applied": {{
    "mood": "{mood}",
    "budget": "{budget}",
    "transport": "{transport}",
    "dietary": {json.dumps(dietary)}
  }},
  "days": [
    {{
      "day_number": 1,
      "date": "{today_date}",
      "theme": "Day theme",
      "top_locations": [
        {{"place_id": null, "name": "Place Name", "image_url": "https://...", "highlight_reason": "Why visit"}}
      ],
      "activities": [
        {{
          "time_slot": "morning|lunch|afternoon|evening|night",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "place_id": null,
          "place_name": "Place Name",
          "place_address": "Address",
          "activity_type": "attraction|food|cafe|hotel|shopping|transport",
          "description": "What to do",
          "budget_estimate": "RM X",
          "tips": "Optional tip",
          "dietary_info": "If food, note dietary compliance"
        }}
      ],
      "day_summary": {{
        "total_activities": N,
        "total_budget": "RM X",
        "transport_notes": "How to get around"
      }}
    }}
  ],
  "practical_info": {{
    "best_transport": "Recommended transport",
    "weather_advisory": "Weather tips",
    "booking_recommendations": ["Tip 1", "Tip 2"]
  }}
}}

RULES:
1. Use REAL place names and addresses for {destination}
2. place_id can be null (will be linked later)
3. Be concise - focus on key information
4. Match language to {response_language} strictly
5. Respect dietary restrictions strictly for food activities
6. **IMPORTANT**: Ensure valid JSON. Escape all double quotes within strings (e.g. \\"). Do not include trailing commas.
"""

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash',  # Faster model
            generation_config={
                "temperature": 0.3,  # Lower = faster, more deterministic
                "max_output_tokens": 4096
            }
        )
        
        response = model.generate_content(fast_prompt)
        
        if response.candidates and response.candidates[0].content.parts:
            ai_text = response.candidates[0].content.parts[0].text.strip()
            
            # Clean markdown if present
            clean_text = ai_text.replace("```json", "").replace("```", "").strip()
            
            # Extract JSON
            obj_start = clean_text.find('{')
            obj_end = clean_text.rfind('}')
            
            if obj_start != -1 and obj_end != -1:
                json_str = clean_text[obj_start:obj_end + 1]
                
                # Basic cleanup for common JSON errors
                # 1. Remove trailing commas before closing braces/brackets
                json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                
                try:
                    parsed = json.loads(json_str)
                    
                    if parsed.get("type") == "daily_plan":
                        print("--- [Fast Mode] 成功生成行程 ---")
                        return f"DAILY_PLAN::{json.dumps(parsed)}" # Re-dump to ensure valid JSON string
                except json.JSONDecodeError as je:
                     print(f"--- [Fast Mode JSON Error] {je} ---")
                     # Fallback: Try to fix truncated JSON if needed, or just fail gracefully
                     return None
        
        return None
        
    except Exception as e:
        print(f"--- [Fast Mode Error] {e} ---")
        return None


# ============ Fast Food Recommendations ============

def get_fast_food_recommendations(preferences: dict, location: str = None):
    """
    快速生成美食推荐 - 专门用于 Food Wizard
    比完整行程规划更快更简单
    
    参数:
    - preferences: 用户偏好 (cuisine, mood, budget, dietary, mealType, distance)
    - location: 用户位置 (可选, 格式: "lat,lng" 或城市名)
    
    返回:
    - FOOD_RECOMMENDATIONS:: 前缀的 JSON 字符串
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        
        # Extract preferences
        cuisine = preferences.get('cuisine', [])
        mood = preferences.get('mood', 'casual')
        budget = preferences.get('budget', 'medium')
        dietary = preferences.get('dietary', [])
        meal_type = preferences.get('mealType', 'lunch')
        distance = preferences.get('distance', '5')
        
        # Map budget to price range
        budget_map = {
            'low': 'under RM 15 per person',
            'medium': 'RM 15-40 per person',
            'high': 'RM 40-80 per person',
            'luxury': 'RM 80+ per person (fine dining)'
        }
        budget_desc = budget_map.get(budget, 'RM 15-40 per person')
        
        # Map mood to dining style
        mood_map = {
            'quick': 'fast casual, quick service, takeaway-friendly',
            'casual': 'relaxed atmosphere, comfortable seating',
            'romantic': 'intimate setting, good ambiance, date-worthy',
            'group': 'spacious, good for groups, shareable dishes'
        }
        mood_desc = mood_map.get(mood, 'casual dining')
        
        location_context = f"near {location}" if location else "in the area"
        cuisine_context = f"focusing on {', '.join(cuisine)} cuisine" if cuisine else "any cuisine type"
        dietary_context = f"MUST be {', '.join(dietary)}" if dietary else "no dietary restrictions"
        
        food_prompt = f"""You are a local food expert. Recommend 5-8 restaurants/food places based on these preferences.

USER PREFERENCES:
- Meal: {meal_type}
- Vibe: {mood_desc}
- Budget: {budget_desc}
- Cuisine: {cuisine_context}
- Dietary: {dietary_context}
- Location: {location_context}
- Max distance: {distance}km

OUTPUT: Return ONLY valid JSON array (no markdown, no explanation). Start with [

Each restaurant object must have:
{{
  "name": "Restaurant Name",
  "cuisine_type": "Chinese/Japanese/Malay/Western/etc",
  "address": "Full address",
  "rating": 4.5,
  "price_level": 2,
  "description": "Why this place is great for the user's mood/occasion (1-2 sentences)",
  "dietary_tags": ["Halal", "Vegetarian"],
  "is_open_now": true,
  "signature_dishes": ["Dish 1", "Dish 2"],
  "tips": "Best time to visit or ordering tips",
  "distance": "1.2km"
}}

RULES:
1. Use REAL restaurant names that exist in Malaysia/the specified location
2. Match the user's budget strictly (price_level: 1=$, 2=$$, 3=$$$, 4=$$$$)
3. If dietary restrictions specified, ONLY include compliant restaurants
4. Sort by relevance to user's mood/preferences
5. Provide actionable tips (what to order, when to go)
6. Be concise but helpful
7. **IMPORTANT**: Ensure valid JSON. Escape quotes. No trailing commas.
"""

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash',
            generation_config={
                "temperature": 0.4,
                "max_output_tokens": 2048
            }
        )
        
        response = model.generate_content(food_prompt)
        
        if response.candidates and response.candidates[0].content.parts:
            ai_text = response.candidates[0].content.parts[0].text.strip()
            
            # Clean markdown if present
            clean_text = ai_text.replace("```json", "").replace("```", "").strip()
            
            # Extract JSON array
            arr_start = clean_text.find('[')
            arr_end = clean_text.rfind(']')
            
            if arr_start != -1 and arr_end != -1:
                json_str = clean_text[arr_start:arr_end + 1]
                
                # Basic cleanup
                json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                
                try:
                    parsed = json.loads(json_str)
                    
                    if isinstance(parsed, list) and len(parsed) > 0:
                        print(f"--- [Food Recommendations] Generated {len(parsed)} recommendations ---")
                        return {
                            "success": True,
                            "recommendations": parsed,
                            "preferences_applied": {
                                "cuisine": cuisine,
                                "mood": mood,
                                "budget": budget,
                                "dietary": dietary,
                                "meal_type": meal_type
                            }
                        }
                except json.JSONDecodeError as je:
                    print(f"--- [Food Recommendations JSON Error] {je} ---")
                    return {
                        "success": False,
                        "error": "AI returned invalid JSON"
                    }
        
        return {
            "success": False,
            "error": "AI did not return valid recommendations"
        }
        
    except Exception as e:
        print(f"--- [Food Recommendations Error] {e} ---")
        return {
            "success": False,
            "error": str(e)
        }


# ============ AI Edit Activities Function ============

def edit_activities_with_ai(activities: list, instructions: str, plan_context: dict = None):
    """
    使用 AI 批量编辑活动
    
    参数:
    - activities: 要编辑的活动列表 [{day_index, activity_index, activity}, ...]
    - instructions: 用户的编辑指令
    - plan_context: 行程上下文信息 (可选)
    
    返回:
    - 编辑后的活动列表 [{day_index, activity_index, activity}, ...]
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        
        # Build context string
        context_str = ""
        if plan_context:
            context_str = f"""
行程背景:
- 标题: {plan_context.get('title', 'N/A')}
- 目的地: {plan_context.get('destination', 'N/A')}
- 用户偏好: {json.dumps(plan_context.get('preferences', {}), ensure_ascii=False)}
"""
        
        # Format activities for the prompt
        activities_json = json.dumps(activities, ensure_ascii=False, indent=2)
        
        edit_prompt = f"""你是一个旅行行程编辑助手。用户选择了以下活动，希望你按照指令修改它们。

{context_str}

## 选中的活动:
```json
{activities_json}
```

## 用户指令:
{instructions}

## 任务:
根据用户指令修改这些活动，并返回修改后的完整活动列表。

## 重要规则:
1. 保持 JSON 结构完全相同
2. 保留 day_index 和 activity_index 字段（用于前端更新）
3. 只修改用户要求修改的内容
4. 保持其他字段不变（除非用户明确要求修改）
5. 如果涉及时间修改，确保时间格式为 "HH:MM"
6. 如果涉及餐厅/地点更换，使用真实存在的地点名称

## 输出格式:
直接返回 JSON 数组（不要 markdown 标记），格式如下：
[
  {{
    "day_index": 0,
    "activity_index": 1,
    "activity": {{
      "time_slot": "morning",
      "start_time": "09:00",
      "end_time": "11:00",
      "place_id": null,
      "place_name": "地点名称",
      "place_address": "地址",
      "activity_type": "attraction",
      "description": "描述",
      "budget_estimate": "RM 50",
      "tips": "小贴士",
      "dietary_info": "饮食信息"
    }}
  }}
]
"""

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash',
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 4096
            }
        )
        
        response = model.generate_content(edit_prompt)
        
        if response.candidates and response.candidates[0].content.parts:
            ai_text = response.candidates[0].content.parts[0].text.strip()
            
            # Clean markdown if present
            clean_text = ai_text.replace("```json", "").replace("```", "").strip()
            
            # Extract JSON array
            arr_start = clean_text.find('[')
            arr_end = clean_text.rfind(']')
            
            if arr_start != -1 and arr_end != -1:
                json_str = clean_text[arr_start:arr_end + 1]
                parsed = json.loads(json_str)
                
                if isinstance(parsed, list):
                    print(f"--- [AI Edit] 成功修改 {len(parsed)} 个活动 ---")
                    return {
                        "success": True,
                        "updated_activities": parsed
                    }
        
        return {
            "success": False,
            "error": "AI 未能生成有效的修改结果"
        }
        
    except Exception as e:
        print(f"--- [AI Edit Error] {e} ---")
        return {
            "success": False,
            "error": str(e)
        }


# ============ Helper functions for Fast Mode ============
import re

# 🆕 Language code to full name mapping (for AI prompts)
LANGUAGE_FULL_NAMES = {
    'en': 'English',
    'zh': 'Chinese (Simplified)',
    'ms': 'Bahasa Melayu (Malay)'
}

def extract_destination_from_message(message: str) -> str:
    """从消息中提取目的地 - 简单启发式"""
    # 常见马来西亚/东南亚城市
    cities = [
        'kuala lumpur', 'kl', '吉隆坡', 'penang', '槟城', 'langkawi', '兰卡威',
        'malacca', 'melaka', '马六甲', 'johor bahru', 'jb', '新山',
        'ipoh', '怡保', 'cameron highlands', '金马伦', 'genting', '云顶',
        'singapore', '新加坡', 'bangkok', '曼谷', 'bali', '巴厘岛',
        'tokyo', '东京', 'osaka', '大阪', 'seoul', '首尔', 'taipei', '台北',
        'hong kong', '香港', 'macau', '澳门', 'vietnam', '越南', 'hanoi', '河内',
        'ho chi minh', '胡志明', 'phuket', '普吉岛', 'krabi', '甲米'
    ]
    
    msg_lower = message.lower()
    
    for city in cities:
        if city in msg_lower:
            # Return proper case
            city_map = {
                'kuala lumpur': 'Kuala Lumpur', 'kl': 'Kuala Lumpur', '吉隆坡': 'Kuala Lumpur',
                'penang': 'Penang', '槟城': 'Penang',
                'langkawi': 'Langkawi', '兰卡威': 'Langkawi',
                'malacca': 'Melaka', 'melaka': 'Melaka', '马六甲': 'Melaka',
                'johor bahru': 'Johor Bahru', 'jb': 'Johor Bahru', '新山': 'Johor Bahru',
                'ipoh': 'Ipoh', '怡保': 'Ipoh',
                'cameron highlands': 'Cameron Highlands', '金马伦': 'Cameron Highlands',
                'genting': 'Genting Highlands', '云顶': 'Genting Highlands',
                'singapore': 'Singapore', '新加坡': 'Singapore',
                'bangkok': 'Bangkok', '曼谷': 'Bangkok',
                'bali': 'Bali', '巴厘岛': 'Bali',
                'tokyo': 'Tokyo', '东京': 'Tokyo',
                'osaka': 'Osaka', '大阪': 'Osaka',
                'seoul': 'Seoul', '首尔': 'Seoul',
                'taipei': 'Taipei', '台北': 'Taipei',
                'hong kong': 'Hong Kong', '香港': 'Hong Kong',
                'macau': 'Macau', '澳门': 'Macau',
                'vietnam': 'Vietnam', '越南': 'Vietnam',
                'hanoi': 'Hanoi', '河内': 'Hanoi',
                'ho chi minh': 'Ho Chi Minh City', '胡志明': 'Ho Chi Minh City',
                'phuket': 'Phuket', '普吉岛': 'Phuket',
                'krabi': 'Krabi', '甲米': 'Krabi'
            }
            return city_map.get(city, city.title())
    
    # If no known city found, return empty (will fall back to standard mode)
    return ""


def extract_duration_from_message(message: str) -> str:
    """从消息中提取行程天数"""
    msg_lower = message.lower()
    
    # Match patterns like "3天", "3 days", "3天2夜"
    patterns = [
        r'(\d+)\s*天',  # 3天
        r'(\d+)\s*days?',  # 3 days
        r'(\d+)\s*晚',  # 3晚
        r'(\d+)\s*nights?',  # 3 nights
    ]
    
    for pattern in patterns:
        match = re.search(pattern, msg_lower)
        if match:
            num = int(match.group(1))
            return f"{num}天{num-1}夜" if num > 1 else "1天"
    
    # Default
    return "3天2夜"


def extract_preferences_from_message(message: str) -> dict:
    """从消息中提取用户偏好"""
    msg_lower = message.lower()
    prefs = {
        'mood': 'relaxed',
        'budget': 'medium',
        'transport': 'public',
        'dietary': [],
        'companions': 'friends'
    }
    
    # Mood
    if any(w in msg_lower for w in ['relax', '轻松', '悠闲', '慢节奏', 'santai', 'tenang']):
        prefs['mood'] = 'relaxed'
    elif any(w in msg_lower for w in ['energetic', '紧凑', '充实', '活力', 'bertenaga', 'aktif']):
        prefs['mood'] = 'energetic'
    elif any(w in msg_lower for w in ['romantic', '浪漫', '情侣', 'couple', 'romantik']):
        prefs['mood'] = 'romantic'
    elif any(w in msg_lower for w in ['family', '家庭', '亲子', '孩子', 'kids', 'keluarga']):
        prefs['mood'] = 'family'
    
    # Budget
    if any(w in msg_lower for w in ['budget', '省钱', '便宜', 'cheap', 'low budget', 'murah', 'bajet']):
        prefs['budget'] = 'low'
    elif any(w in msg_lower for w in ['luxury', '奢华', '高端', 'premium', 'expensive', 'mewah']):
        prefs['budget'] = 'luxury'
    elif any(w in msg_lower for w in ['high', '高预算', 'mahal']):
        prefs['budget'] = 'high'
    
    # Transport
    if any(w in msg_lower for w in ['walk', '步行', '走路', 'jalan kaki', 'berjalan']):
        prefs['transport'] = 'walk'
    elif any(w in msg_lower for w in ['car', '自驾', '开车', 'drive', 'kereta', 'memandu']):
        prefs['transport'] = 'car'
    
    # Dietary
    if any(w in msg_lower for w in ['halal', '清真']):
        prefs['dietary'].append('Halal')
    if any(w in msg_lower for w in ['vegetarian', '素食', '吃素']):
        prefs['dietary'].append('Vegetarian')
    if any(w in msg_lower for w in ['vegan', '纯素']):
        prefs['dietary'].append('Vegan')
    if any(w in msg_lower for w in ['no pork', '不吃猪肉', '无猪', 'tiada babi']):
        prefs['dietary'].append('No Pork')
    if any(w in msg_lower for w in ['no beef', '不吃牛肉', '无牛', 'tiada daging lembu']):
        prefs['dietary'].append('No Beef')
    
    # Companions
    if any(w in msg_lower for w in ['solo', '一个人', '独自', 'alone', 'sendiri', 'bersendirian']):
        prefs['companions'] = 'solo'
    elif any(w in msg_lower for w in ['couple', '情侣', '两个人', '约会', 'pasangan']):
        prefs['companions'] = 'couple'
    elif any(w in msg_lower for w in ['family', '家庭', '全家', '亲子', 'keluarga']):
        prefs['companions'] = 'family'
    elif any(w in msg_lower for w in ['friend', '朋友', '同事', 'kawan', 'rakan']):
        prefs['companions'] = 'friends'
    
    return prefs


# [修改] Gemini 工具定义 - 添加新的数据库查询工具
tools_definition = [
    {
        "name": "search_nearby_places",
        "description": """
        当用户询问附近的地点推荐时调用。
        此工具会将找到的地点存入数据库，并返回 place_ids。
        你需要接着调用 query_places_from_db 来获取详细信息。
        """,
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "搜索的关键词，例如 '餐厅', '公园', '博物馆'"
                },
                "location": {
                    "type": "STRING",
                    "description": "用户的位置，优先使用 '纬度,经度' 格式"
                }
            },
            "required": ["query", "location"]
        }
    },
    {
        "name": "query_places_from_db",
        "description": """
        从数据库查询地点详细信息。
        用法 1: 传入 place_ids (来自 search_nearby_places 的返回值)
        用法 2: 传入 query_hint 进行模糊搜索
        你需要分析这些地点，筛选出最符合用户需求的推荐。
        如果没有符合的，告诉用户原因，然后用不同的关键词再次调用 search_nearby_places。
        """,
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "place_ids": {
                    "type": "ARRAY",
                    "description": "地点 ID 列表 (来自 search_nearby_places)",
                    "items": {"type": "INTEGER"}
                },
                "query_hint": {
                    "type": "STRING",
                    "description": "模糊搜索关键词 (可选)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_coordinates_for_city",
        "description": "当用户询问特定城市时，首先调用此工具获取坐标。",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city_name": { 
                    "type": "STRING",
                    "description": "要查询坐标的城市名称, 例如 '吉隆坡'" 
                }
            },
            "required": ["city_name"]
        }
    },
    {
        "name": "get_current_weather",
        "description": "当用户明确指定一个城市名称并询问天气时调用。",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {
                    "type": "STRING",
                    "description": "城市名称"
                }
            }, 
            "required": ["city"]
        }
    },
    {
        "name": "get_weather_for_current_location",
        "description": "当用户询问本地天气（没有指定城市）时调用。",
        "parameters": {
            "type": "OBJECT",
            "properties": {}, 
            "required": []
        }
    }
]

def get_ai_chat_response(conversation_history, credentials_dict, coordinates=None, user_ip=None, language='en'):
    """
    【AI 代理 - 优化版】
    
    优化策略:
    1. 检测是否是行程规划请求 -> 使用 Fast Mode (无工具调用)
    2. 其他请求 -> 使用标准模式 (带工具调用)
    
    参数:
    - language: 用户首选语言 (en, zh, ms)，AI 将使用此语言回复
    """
    try:
        # 获取最后一条用户消息
        last_user_message = ""
        for msg in reversed(conversation_history):
            if msg.get('role') == 'user':
                last_user_message = msg.get('parts', [''])[0] if msg.get('parts') else ''
                break
        
        last_msg_lower = last_user_message.lower()
        
        # ============ FAST MODE: 行程规划请求 ============
        # 检测关键词：规划、行程、N天、plan、itinerary、trip 等
        itinerary_keywords = [
            '规划', '行程', '天游', '日游', '旅行计划', '安排',
            'plan', 'itinerary', 'trip', 'days', 'schedule', 'travel plan',
            'day 1', 'day 2', 'day 3', '第一天', '第二天',
            'rancang', 'perjalanan', 'cuti', 'lawatan', 'hari'  # Malay keywords
        ]
        
        is_itinerary_request = any(kw in last_msg_lower for kw in itinerary_keywords)
        
        if is_itinerary_request:
            print("--- [检测] 行程规划请求，使用 Fast Mode ---")
            
            # 尝试从消息中提取目的地和偏好
            # 简单启发式：查找常见城市名或在消息中的地点
            destination = extract_destination_from_message(last_user_message)
            duration = extract_duration_from_message(last_user_message)
            preferences = extract_preferences_from_message(last_user_message)
            
            if destination:
                fast_result = get_fast_itinerary_response(destination, duration, preferences, language=language)
                if fast_result:
                    return fast_result
            
            # 如果 Fast Mode 失败或无法提取目的地，继续使用标准模式
            print("--- [Fast Mode] 回退到标准模式 ---")
        
        # ============ STANDARD MODE: 其他请求 ============
        genai.configure(api_key=config.GEMINI_API_KEY)

        today_date = datetime.date.today().isoformat()
        location_info_for_prompt = ""
        user_location_string = None
        
        if coordinates and coordinates.get('latitude'):
            user_location_string = f"{coordinates.get('latitude')},{coordinates.get('longitude')}"
            location_info_for_prompt = f"用户的当前 GPS 坐标是 {user_location_string}。"
        else:
            location_info_for_prompt = "用户的当前 GPS 坐标不可用。"

        # 🆕 Get full language name for AI prompt
        response_language = LANGUAGE_FULL_NAMES.get(language, 'English')
        
        system_prompt = f"""
You are GogoTrip AI, a professional intelligent travel planning assistant. 
Current Date: {today_date}
User Context: {location_info_for_prompt}

*** CRITICAL: RESPONSE LANGUAGE ***
You MUST respond in {response_language}. All your responses, recommendations, descriptions, and JSON content MUST be written in {response_language}.
- If the language is "English", respond in English.
- If the language is "Chinese (Simplified)", respond in 简体中文.
- If the language is "Bahasa Melayu (Malay)", respond in Bahasa Melayu.
This is NON-NEGOTIABLE. The user has selected {response_language} as their preferred language.
DO NOT use English if the user selected Chinese or Malay, unless it is a proper noun (like a place name).

*** PREFERENCE ANALYSIS ***
The user may provide structured preferences (e.g., "Mood: Relaxed", "Budget: Medium", "Dietary: Halal").
You MUST STRICTLY adhere to these constraints:
- **Mood**: Adjust the pace. "Relaxed" = fewer spots, more time. "Energetic" = packed itinerary.
- **Budget**: 
  - "Low": Prioritize free attractions, hawker centers, affordable transit.
  - "Medium": Balanced mix of paid/free.
  - "High/Luxury": Fine dining, premium experiences, private transport.
- **Transport**:
  - "Public": Ensure locations are near train/bus stations.
  - "Walk": Cluster activities close together.
- **Dietary**: STRICTLY filter food choices (e.g., NO Pork for Halal).

*** CRITICAL WORKFLOW - 数据库优先筛选模式 ***

当用户询问地点推荐时，你必须遵循以下流程:

**步骤 1: 搜索并存储**
- 调用 search_nearby_places(query, location)
- 这会将找到的地点存入数据库，并返回 place_ids

**步骤 2: 查询数据库**
- 调用 query_places_from_db(place_ids=[...])
- 获取所有地点的详细信息

**步骤 3: 智能筛选**
- 分析用户的真实需求 (例如: "浪漫约会" vs "家庭聚餐" vs "快速午餐")
- 从数据库结果中筛选出最符合的 3-5 个地点
- 考虑因素: 评分、营业状态、价格、用户评论、位置等

**步骤 4: 判断是否需要重新搜索**
- 如果数据库中的地点都不符合用户需求 (例如: 用户要"米其林餐厅"，但只找到快餐店)
- 明确告诉用户为什么不符合
- 用更精确的关键词重新调用 search_nearby_places (例如: "fine dining" 或 "高档餐厅")

**步骤 5: 返回结果**
- 如果找到符合的地点，以 [POPUP_DATA::[...]] 格式返回
- 如果多次搜索仍未找到，诚实告知用户并建议替代方案

*** LANGUAGE REMINDER ***
You MUST respond in {response_language}. This has been set by the user in their preferences.
Do NOT auto-detect or switch languages based on user input - always use {response_language}.
Even if the user asks in English, reply in {response_language}.

*** RESPONSE FORMAT ***

**MODE A: 地点推荐 (Simple Search - Food/Places)**
当用户只是想找餐厅或某个地点时使用。
返回格式: POPUP_DATA::[{{"name": "...", "address": "...", "rating": 4.5, ...}}]

**MODE B: 智能日程规划 (Daily Planning)**
触发条件: 用户说 "规划行程"、"安排旅行"、"N天游"、"plan my day"、"daily plan" 等

这是本系统的核心功能。你需要生成一个结构化的多天行程，每天包含:
1. 该天的 top_locations (用于展示精选图片, 最多2-3个)
2. 该天的完整活动列表 (按时间排序)
3. 每个活动必须关联数据库中的真实地点 (place_id)

严格遵循以下 JSON Schema (NO MARKDOWN, start directly with {{):

{{
  "type": "daily_plan",
  "title": "行程总标题 (例如: 吉隆坡3日文化美食之旅)",
  "description": "行程总体描述",
  "duration": "3天2夜",
  "total_budget_estimate": "RM 1,500 - RM 2,500",
  "tags": ["文化", "美食", "适合情侣"],
  "cover_image": "https://images.unsplash.com/photo-... (目的地代表性图片)",
  "user_preferences_applied": {{
    "mood": "relaxed",
    "budget": "medium", 
    "transport": "public",
    "dietary": ["halal"]
  }},
  "days": [
    {{
      "day_number": 1,
      "date": "2024-01-15",
      "theme": "抵达与城市探索",
      "top_locations": [
        {{
          "place_id": 123,
          "name": "Petronas Twin Towers",
          "image_url": "https://...",
          "highlight_reason": "地标性建筑，必打卡"
        }},
        {{
          "place_id": 456,
          "name": "Jalan Alor",
          "image_url": "https://...",
          "highlight_reason": "最佳夜市美食街"
        }}
      ],
      "activities": [
        {{
          "time_slot": "morning",
          "start_time": "09:00",
          "end_time": "11:30",
          "place_id": 123,
          "place_name": "Petronas Twin Towers",
          "place_address": "Kuala Lumpur City Centre",
          "activity_type": "attraction",
          "description": "参观双子塔，建议早上人少时前往观景台",
          "budget_estimate": "RM 80",
          "tips": "建议网上提前购票"
        }},
        {{
          "time_slot": "lunch",
          "start_time": "12:00",
          "end_time": "13:30",
          "place_id": 789,
          "place_name": "Madam Kwan's",
          "place_address": "KLCC Suria Mall",
          "activity_type": "food",
          "description": "品尝正宗马来西亚菜，推荐 Nasi Lemak",
          "budget_estimate": "RM 35",
          "dietary_info": "Halal certified"
        }},
        {{
          "time_slot": "afternoon",
          "start_time": "14:30",
          "end_time": "17:00",
          "place_id": 101,
          "place_name": "Islamic Arts Museum",
          "place_address": "Jalan Lembah Perdana",
          "activity_type": "attraction",
          "description": "探索伊斯兰艺术与建筑之美",
          "budget_estimate": "RM 20",
          "tips": "适合下午避暑"
        }},
        {{
          "time_slot": "evening",
          "start_time": "19:00",
          "end_time": "21:00",
          "place_id": 456,
          "place_name": "Jalan Alor",
          "place_address": "Jalan Alor, Bukit Bintang",
          "activity_type": "food",
          "description": "夜市美食街，体验当地小吃文化",
          "budget_estimate": "RM 50",
          "dietary_info": "多种选择，部分摊位非 Halal"
        }}
      ],
      "day_summary": {{
        "total_activities": 4,
        "total_budget": "RM 185",
        "transport_notes": "全程可使用 LRT/MRT，步行距离合理"
      }}
    }},
    {{
      "day_number": 2,
      "date": "2024-01-16",
      "theme": "历史文化探索",
      "top_locations": [...],
      "activities": [...],
      "day_summary": {{...}}
    }}
  ],
  "practical_info": {{
    "best_transport": "LRT + Grab",
    "weather_advisory": "热带气候，建议携带雨具",
    "booking_recommendations": ["双子塔门票提前网上预订", "热门餐厅建议预约"]
  }}
}}

**CRITICAL RULES FOR DAILY PLANNING:**
1. ⚠️ **PLACE_ID 是必须的**: 每个 activity 必须包含真实的 place_id (来自数据库)
2. **先搜索，后规划**: 
   - 首先调用 search_nearby_places 搜索: 餐厅、景点、咖啡馆等
   - 然后调用 query_places_from_db 获取详情
   - 建立 "地点池"，然后从中挑选
3. **时间逻辑**: 活动时间应该合理，考虑交通时间
4. **预算逻辑**: 根据用户的 budget 偏好筛选地点 (price_level)
5. **交通逻辑**: 
   - "public" = 优先选择地铁/公交站附近的地点
   - "walk" = 活动点要聚集在一起
6. **饮食逻辑**: 
   - 如果用户选择 "Halal"，食物类活动必须是 Halal 认证餐厅
   - 在 dietary_info 中标注
7. **心情逻辑**:
   - "relaxed" = 每天 3-4 个活动，留出休息时间
   - "energetic" = 每天 5-6 个活动，紧凑行程
8. **top_locations**: 每天选择 2-3 个最具代表性的地点用于图片展示
9. **NO MARKDOWN**: 直接以 {{ 开始，不要 ```json

*** NEVER HALLUCINATE ***
- 只使用工具返回的真实数据
- place_id 必须是数据库中真实存在的
- 不要编造地点名称或地址
"""
        
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=system_prompt,
            tools=tools_definition,
            generation_config={"temperature": 0.1}
        )

        gemini_messages = [msg for msg in conversation_history]
        if gemini_messages and gemini_messages[0]['role'] == 'model':
            gemini_messages = gemini_messages[1:]

        max_turns = 20  # 增加循环次数以支持多次搜索
        turn_count = 0
        
        # 用于追踪搜索历史，防止重复搜索
        search_history = []
            
        while turn_count < max_turns:
            turn_count += 1
            print(f"--- [聊天日志] Gemini Turn {turn_count} ---")

            response = model.generate_content(
                gemini_messages,
                tool_config={"function_calling_config": {"mode": "auto"}}
            )
            
            if not response.candidates:
                print("--- [聊天错误] Gemini 未返回任何候选响应。 ---")
                return "抱歉，AI 未能生成响应。"

            response_content = response.candidates[0].content
            gemini_messages.append(response_content)

            # 检查是否调用工具
            if response_content.parts and response_content.parts[0].function_call:
                print(f"--- [Tool Call] AI 正在调用工具... ---")
                
                tool_call = response_content.parts[0].function_call
                function_name = tool_call.name
                function_args = {key: value for key, value in tool_call.args.items()}
                
                tool_result_content = ""

                # 执行工具
                if function_name == "get_coordinates_for_city":
                    try:
                        city_name = function_args.get("city_name")
                        print(f"--- [Tool] get_coordinates_for_city: {city_name} ---")
                        tool_result_content = get_coordinates_for_city(city_name)
                    except Exception as e:
                        tool_result_content = f"执行坐标查询时发生错误: {str(e)}"

                elif function_name == "search_nearby_places":
                    try:
                        query = function_args.get("query")
                        location_from_ai = function_args.get("location")
                        print(f"--- [Tool] search_nearby_places: {query} @ {location_from_ai} ---")
                        
                        # 记录搜索历史，防止死循环
                        search_key = f"{query}|{location_from_ai}"
                        if search_key in search_history:
                            tool_result_content = json.dumps({
                                "error": "已经搜索过此关键词，请尝试不同的搜索词"
                            })
                        else:
                            search_history.append(search_key)
                            
                            final_location_query = None
                            if location_from_ai and ',' in location_from_ai:
                                final_location_query = location_from_ai
                            elif user_location_string:
                                final_location_query = user_location_string
                            else:
                                raise ValueError("未能确定搜索地点。")
                            
                            tool_result_content = search_nearby_places(query, final_location_query)
                            
                    except Exception as e:
                        tool_result_content = f"执行地点搜索时发生错误: {str(e)}"

                elif function_name == "query_places_from_db":
                    try:
                        place_ids = function_args.get("place_ids")
                        query_hint = function_args.get("query_hint")
                        print(f"--- [Tool] query_places_from_db: IDs={place_ids}, Hint={query_hint} ---")
                        
                        tool_result_content = query_places_from_db(
                            place_ids=place_ids,
                            query_hint=query_hint,
                            location=user_location_string
                        )
                    except Exception as e:
                        tool_result_content = f"执行数据库查询时发生错误: {str(e)}"

                elif function_name == "get_current_weather":
                    try:
                        city_or_coords = function_args.get("city")
                        keywords_for_current_location = ["here", "my place", "current location", "me", "这", "这里", "我"]
                        if user_location_string and (not city_or_coords or any(k in str(city_or_coords).lower() for k in keywords_for_current_location)):
                            city_or_coords = user_location_string
                        print(f"--- [Tool] get_current_weather: {city_or_coords} ---")
                        tool_result_content = get_current_weather(city_or_coords)
                    except Exception as e:
                        tool_result_content = f"执行天气查询时发生错误: {str(e)}"
                        
                elif function_name == "get_weather_for_current_location":
                    try:
                        print(f"--- [Tool] get_weather_for_current_location ---")
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
                        tool_result_content = get_current_weather(query_string)
                    except Exception as e:
                        tool_result_content = f"执行本地天气查询时发生错误: {str(e)}"

                else:
                    tool_result_content = f"错误：AI 试图调用一个未知的工具 '{function_name}'"

                print(f"--- [Tool Result] {tool_result_content[:200]}... ---")
                
                # 将工具结果返回给 AI
                gemini_messages.append({
                    "role": "function",
                    "parts": [
                        {"function_response": {
                            "name": function_name,
                            "response": {"content": tool_result_content}
                        }}
                    ]
                })
                
                continue  # 继续循环，让 AI 处理工具结果
                
            else:
                # AI 决定不再调用工具，返回最终响应
                print("--- [聊天日志] AI 生成最终回复 ---")
                if response_content.parts and response_content.parts[0].text:
                    ai_text = response_content.parts[0].text.strip()
                    
                    # 清理 Markdown 标记
                    clean_text = ai_text.replace("```json", "").replace("```", "").strip()

                    # 智能提取 JSON - 支持两种格式: 数组 [] 或对象 {}
                    try:
                        # 首先尝试提取 daily_plan 对象格式 (新格式)
                        obj_start = clean_text.find('{')
                        obj_end = clean_text.rfind('}')
                        
                        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
                            potential_json = clean_text[obj_start : obj_end + 1]
                            parsed = json.loads(potential_json)
                            
                            # 检查是否是 daily_plan 格式
                            if isinstance(parsed, dict) and parsed.get("type") == "daily_plan":
                                print("--- [系统] 检测到 Daily Plan JSON，转换为行程模式 ---")
                                return f"DAILY_PLAN::{potential_json}"
                        
                        # 然后尝试提取数组格式 (旧格式 - 地点推荐)
                        arr_start = clean_text.find('[')
                        arr_end = clean_text.rfind(']')

                        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
                            potential_json = clean_text[arr_start : arr_end + 1]
                            json.loads(potential_json)  # 验证 JSON
                            
                            print("--- [系统] 检测到 JSON 数组，转换为卡片模式 ---")
                            return f"POPUP_DATA::{potential_json}"
                    
                    except json.JSONDecodeError:
                        pass

                    return ai_text
                else:
                    return "AI 决定回复，但未能生成文本。"
                    
        return "抱歉，AI 代理陷入了思考循环，请重试。"

    except Exception as e:
        print(f"--- [聊天错误] {e} ---")
        import traceback
        traceback.print_exc()
        return f"抱歉，AI 代理在处理时遇到了一个错误: {str(e)}"