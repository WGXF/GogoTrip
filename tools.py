# tools.py
import requests
import json
import time
from datetime import datetime, timedelta

# 从配置导入
import config

# --- IP Geolocation API Config ---
IP_API_URL = "http://ip-api.com/json/"

# --- 工具 1：IP 地理位置查询 (备用) ---
def get_ip_location_info(ip_address: str = None) -> str:
    # ... (函数体保持不变) ...
    if ip_address:
        print(f"--- TOOL CALLED: get_ip_location_info for {ip_address} ---")
        url = f"{IP_API_URL}{ip_address}?lang=zh-CN"
    else:
        print(f"--- TOOL CALLED: get_ip_location_info (auto-detecting location) ---")
        url = f"{IP_API_URL}?lang=zh-CN"
    try:
        # ... (其余部分不变) ...
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "fail": return f"IP 地址查询失败: {data.get('message', '未知')}"
        return json.dumps({ "ip": data.get('query', ip_address), "country": data.get('country'), "city": data.get('city'), "region": data.get('regionName') })
    except Exception as e: return f"调用 IP 查询 API 时出错: {e}"


# --- 工具 2：天气预报查询 (按城市或坐标) ---
def get_current_weather(city_or_coords: str) -> str:
    # ... (函数体保持不变) ...
    if not config.WEATHERSTACK_ACCESS_KEY or config.WEATHERSTACK_ACCESS_KEY == "YOUR_API_KEY_HERE": return "错误：天气 API 密钥未配置。"
    print(f"--- TOOL CALLED: get_current_weather for {city_or_coords} ---")
    try:
        url = f"{config.WEATHERSTACK_API_URL}current?access_key={config.WEATHERSTACK_ACCESS_KEY}&query={city_or_coords}&units=m"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if 'error' in data: return f"查询 '{city_or_coords}' 天气失败: {data['error']['info']}"
        return json.dumps({"city": data['location']['name'],"temperature": f"{data['current']['temperature']}°C","description": data['current']['weather_descriptions'][0],"humidity": f"{data['current']['humidity']}%"})
    except Exception as e: return f"调用 Weatherstack API 时出错: {e}"

def get_coordinates_for_city(city_name: str) -> str:
    """
    [新工具]
    将城市名称 (例如 "吉隆坡" 或 "Kuala Lumpur") 转换为精确的 GPS 坐标 (纬度,经度)。
    (请确保在 Google Cloud 中启用了 'Geocoding API')
    """
    if not config.GOOGLE_MAPS_API_KEY or config.GOOGLE_MAPS_API_KEY == "YOUR_GOOGLE_MAPS_API_KEY":
        return "错误：Google Maps API 密钥未在 config.py 中配置。"

    print(f"--- TOOL CALLED: get_coordinates_for_city for {city_name} ---")
    
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": city_name,
        "key": config.GOOGLE_MAPS_API_KEY,
        "language": "zh-CN"
    }

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "OK" or not data.get("results"):
            return f"未能找到城市 '{city_name}' 的坐标。状态: {data.get('status')}"

        # 提取第一个结果的坐标
        location = data["results"][0]["geometry"]["location"]
        lat = location["lat"]
        lng = location["lng"]
        
        result = {
            "city_name": city_name,
            "formatted_address": data["results"][0].get("formatted_address", city_name),
            "location": f"{lat},{lng}"
        }
        return json.dumps(result)

    except requests.exceptions.RequestException as e:
        return f"调用 Geocoding API 时发生网络错误: {e}"
    except Exception as e:
        return f"处理 Geocoding API 结果时发生未知错误: {e}"

# --- [新增] 工具 3：Google Places API 地点搜索 ---
# tools.py
# (请确保文件顶部有 import requests, json, config)

# tools.py
# (请确保文件顶部有 import requests, json, config)

def search_nearby_places(query: str, location: str, rank_by: str = "prominence", radius: int = 5000) -> str:
    """
    [最终修复版 - v1.6]
    修复了 'formattedPhoneNumber' 字段错误。
    Google Places API v1 的正确字段名是 'nationalPhoneNumber'。
    """
    import json
    import requests
    import config

    if not config.GOOGLE_MAPS_API_KEY or config.GOOGLE_MAPS_API_KEY == "YOUR_GOOGLE_MAPS_API_KEY":
        return "错误：Google Maps API 密钥未在 config.py 中配置。"

    print(f"--- TOOL CALLED: search_nearby_places (v1.6 Fix) ---")

    # ==========================================
    # Step 1: searchText (获取 ID)
    # ==========================================
    search_url = "https://places.googleapis.com/v1/places:searchText"
    search_headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-Fieldmask": "places.id"
    }

    try:
        lat, lon = map(float, location.split(','))
    except (ValueError, AttributeError):
        return f"错误：位置参数 '{location}' 格式不正确或不是有效字符串。必须是 '纬度,经度'。"

    search_payload = {
        "textQuery": query,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": min(radius, 10000) 
            }
        },
        "languageCode": "zh-CN",
        "maxResultCount": 3,
        "rankPreference": "RELEVANCE" if rank_by != "distance" else "DISTANCE"
    }

    place_ids = []
    try:
        print("--- [Step 1] 正在搜索地点 ID... ---")
        response = requests.post(search_url, headers=search_headers, data=json.dumps(search_payload), timeout=10)
        response.raise_for_status() 
        data = response.json()
        
        places_found = data.get("places", [])
        if not places_found:
            return json.dumps({"message": f"在您附近未能找到与 '{query}' 相关的地点。"}, ensure_ascii=False)
            
        for p in places_found:
            if p.get("id"):
                place_ids.append(p.get("id"))
        
        print(f"--- [Step 1 完成] 获取到 {len(place_ids)} 个 ID ---")

    except Exception as e:
        return f"Step 1 (搜索) 失败: {e}"

    
    # ==========================================
    # Step 2: Place Details (获取详情)
    # ==========================================
    print(f"--- [Step 2] 正在获取详情... ---")

    # [!!! 修复 !!!] 
    # 1. regularOpeningHours (之前已修)
    # 2. nationalPhoneNumber (现在修复，替代 formattedPhoneNumber)
    safe_fields = (
        "id,displayName,formattedAddress,rating,priceLevel,location,"
        "businessStatus,regularOpeningHours,nationalPhoneNumber,websiteUri,"
        "reviews"
    )
    
    details_headers = {
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY
    }

    results = []
    
    for place_id in place_ids:
        details_url = f"https://places.googleapis.com/v1/places/{place_id}"
        params = {
            "fields": safe_fields,
            "languageCode": "zh-CN"
        }

        try:
            response = requests.get(details_url, headers=details_headers, params=params, timeout=10)
            
            if response.status_code != 200:
                print(f"    [错误] 获取 ID {place_id} 失败: {response.status_code} - {response.text}")
                continue

            place = response.json()

            # 解析数据
            open_hours_data = place.get("regularOpeningHours", {})
            
            # 提取评论
            review_list = []
            if place.get("reviews"):
                for review in place.get("reviews", [])[:3]:
                    txt = review.get("text", {}).get("text", "")
                    if txt:
                        review_list.append(txt)
            if not review_list:
                review_list = ["暂无评论"]

            clean_details = {
                "name": place.get("displayName", {}).get("text", "未知名称"),
                "address": place.get("formattedAddress", "未知地址"),
                "rating": place.get("rating", "N/A"),
                "business_status": place.get("businessStatus", "N/A"),
                "is_open_now": open_hours_data.get("openNow", "未知"),
                "opening_hours_weekday": open_hours_data.get("weekdayDescriptions", []),
                
                # [!!! 修复 !!!] 使用 nationalPhoneNumber
                "phone": place.get("nationalPhoneNumber", "N/A"),
                
                "website": place.get("websiteUri", "N/A"),
                "price_level": place.get("priceLevel", "N/A"),
                "coordinates": place.get("location", {}),
                
                # 默认值
                "accessibility": {"wheelchair_accessible": "未知"},
                "service_attributes": {
                    "delivery": "未知",
                    "dine_in": "未知",
                    "serves_vegetarian_food": "未知"
                },
                
                "review_list": review_list
            }
            results.append(clean_details)
        
        except Exception as e:
            print(f"    [异常] 处理 ID {place_id} 时出错: {e}")
            continue

    if not results:
        return json.dumps({"message": "成功获取ID，但获取详情全部失败。"}, ensure_ascii=False)

    return json.dumps(results, ensure_ascii=False)

