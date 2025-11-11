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
def search_nearby_places(query: str, location: str, rank_by: str = "prominence", radius: int = 5000) -> str:
    """
    [已更新至 Places API (New) - 使用 searchText]
    使用 Google Places API 搜索附近的地点。
    - query: 搜索关键词 (例如 "餐厅", "公园", "ATM")
    - location: 中心点，格式为 "纬度,经度" (例如 "3.1390,101.6869")
    - rank_by: 排序方式, 'prominence' (RELEVANCE) 或 'distance' (DISTANCE)
    - radius: 搜索半径 (米)
    """
    if not config.GOOGLE_MAPS_API_KEY or config.GOOGLE_MAPS_API_KEY == "YOUR_GOOGLE_MAPS_API_KEY":
        return "错误：Google Maps API 密钥未在 config.py 中配置。"

    print(f"--- TOOL CALLED: search_nearby_places (New API - searchText) ---")
    print(f"    Query: {query}")
    print(f"    Location: {location}")

    url = "https://places.googleapis.com/v1/places:searchText"
    
    field_mask = "places.displayName.text,places.formattedAddress,places.rating,places.types"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-Fieldmask": field_mask
    }

    try:
        lat, lon = map(float, location.split(','))
    except (ValueError, AttributeError):
        return f"错误：位置参数 '{location}' 格式不正确或不是有效字符串。必须是 '纬度,经度'。"

    # 4. [修复] 准备 searchText 的请求体 (Request Body)
    #    将 'locationRestriction' 更改为 'locationBias'
    payload = {
        "textQuery": query,
        "locationBias": { # <--- [关键修复] 使用 'locationBias' 而不是 'locationRestriction'
            "circle": {
                "center": {
                    "latitude": lat,
                    "longitude": lon
                },
                "radius": min(radius, 10000) 
            }
        },
        "languageCode": "zh-CN",
        "maxResultCount": 5 
    }

    # 5. [修复] 调整排序参数
    if rank_by == "distance":
         payload["rankPreference"] = "DISTANCE"
    else: # prominence
        payload["rankPreference"] = "RELEVANCE" 

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
        
        response.raise_for_status() 
        data = response.json()

        # 6. 解析响应
        if not data.get("places"):
            return json.dumps({"message": f"在您附近未能找到与 '{query}' 相关的地点。"})

        results = []
        for place in data.get("places", []):
            results.append({
                "name": place.get("displayName", {}).get("text", "未知名称"),
                "address": place.get("formattedAddress", "未知地址"),
                "rating": place.get("rating", "N/A"),
                "types": place.get("types", [])
            })
        
        return json.dumps(results)

    except requests.exceptions.HTTPError as http_err:
        try:
            error_details = http_err.response.json()
            error_info = error_details.get("error", {}).get("message", "无详细信息")
            return f"调用 Google Places API HTTP 失败: {http_err}。 详细信息: {error_info}"
        except json.JSONDecodeError:
            return f"调用 Google Places API HTTP 失败: {http_err}。 无法解析错误响应。"
    except requests.exceptions.RequestException as e:
        return f"调用 Google Places API 时发生网络错误: {e}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"处理 Google Places API 结果时发生未知错误: {e}"