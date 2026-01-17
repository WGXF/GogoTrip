# tools.py
import requests
import json
import logging
from datetime import datetime, timedelta
from flask import current_app
import config
from models import db, Place, SearchCache

# --- API Config ---
IP_API_URL = "http://ip-api.com/json/"

def get_ip_location_info(ip_address: str = None) -> str:
    url = f"{IP_API_URL}{ip_address}?lang=zh-CN" if ip_address else f"{IP_API_URL}?lang=zh-CN"
    try:
        resp = requests.get(url, timeout=5)
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return f"IP查询出错: {e}"

def get_current_weather(city: str) -> str:
    """Get weather for a city."""
    if not config.WEATHERSTACK_ACCESS_KEY: return "Err: No Weather Key"
    try:
        url = f"{config.WEATHERSTACK_API_URL}current?access_key={config.WEATHERSTACK_ACCESS_KEY}&query={city}&units=m"
        data = requests.get(url, timeout=5).json()
        if 'error' in data: return f"天气查询失败: {data['error']['info']}"
        return json.dumps({
            "city": data['location']['name'],
            "temp": f"{data['current']['temperature']}C",
            "desc": data['current']['weather_descriptions'][0]
        }, ensure_ascii=False)
    except Exception as e: return f"天气API出错: {e}"

def get_coordinates_for_city(city: str) -> str:
    """Get lat/lng coordinates for a city name."""
    if not config.GOOGLE_MAPS_API_KEY: return "Err: No Google Key"
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        data = requests.get(url, params={"address": city, "key": config.GOOGLE_MAPS_API_KEY}, timeout=5).json()
        if not data.get("results"): return "未找到该城市坐标"
        loc = data["results"][0]["geometry"]["location"]
        return json.dumps({"location": f"{loc['lat']},{loc['lng']}"})
    except Exception as e: return f"Geocode出错: {e}"

def normalize_key(text: str):
    """标准化字符串，用于缓存 Key 对比"""
    return text.strip().lower() if text else ""

def save_places_to_db(places_data_list):
    """
    【数据入库核心】
    将 API 返回的原始数据清洗后，强制同步到数据库 Place 表。
    返回插入/更新的 place_id 列表
    """
    if not current_app:
        print("!!! [DB Error] No Flask App Context")
        return []

    print(f"--- [DB Sync] 正在同步 {len(places_data_list)} 个地点到数据库... ---")
    saved_ids = []

    try:
        for p in places_data_list:
            pid = p.get('google_place_id')
            if not pid: continue

            existing_place = Place.query.filter_by(google_place_id=pid).first()
            coords_str = json.dumps(p.get('coordinates')) if isinstance(p.get('coordinates'), dict) else p.get('coordinates')
            
            if not existing_place:
                new_place = Place(
                    google_place_id=pid,
                    name=p.get('name'),
                    address=p.get('address'),
                    rating=p.get('rating'),
                    business_status=p.get('business_status'),
                    is_open_now=p.get('is_open_now'),
                    opening_hours=p.get('opening_hours_weekday'),
                    phone=p.get('phone'),
                    website=p.get('website'),
                    price_level=p.get('price_level'),
                    coordinates=coords_str,
                    photo_reference=p.get('photo_reference'),
                    review_list=p.get('review_list'),
                    cached_at=datetime.utcnow()
                )
                db.session.add(new_place)
                db.session.flush()  # 获取 ID
                saved_ids.append(new_place.id)
            else:
                existing_place.cached_at = datetime.utcnow()
                # 更新可能变化的字段
                existing_place.rating = p.get('rating')
                existing_place.is_open_now = p.get('is_open_now')
                saved_ids.append(existing_place.id)
        
        db.session.commit()
        print(f"✅ [DB Sync] 完成: 保存 {len(saved_ids)} 个地点。")
        return saved_ids
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ [DB Error] 入库失败: {str(e)}")
        return []

def fetch_places_from_api(query: str, location: str, radius: int = 5000):
    """
    【纯粹的 API 调用】
    从 Google Places API 获取数据，不做任何缓存判断
    返回: 清洗后的地点数据列表
    """
    print(f"--- [External API] 正在调用 Google Places API... ---")
    
    if not config.GOOGLE_MAPS_API_KEY:
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-Fieldmask": "places.id,places.displayName,places.formattedAddress,places.rating,places.priceLevel,places.location,places.businessStatus,places.regularOpeningHours,places.nationalPhoneNumber,places.websiteUri,places.photos,places.reviews"
    }
    
    payload = {"textQuery": query, "languageCode": "zh-CN", "maxResultCount": 10}
    if "," in location:
        try:
            lat, lng = map(float, location.split(','))
            payload["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}}
        except: pass

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        data = resp.json()
        places_raw = data.get("places", [])

        if not places_raw:
            return []

        # 清洗数据
        cleaned_list = []
        for p in places_raw:
            photo = p.get("photos")[0].get("name") if p.get("photos") else None
            reviews = [r.get("text", {}).get("text", "") for r in p.get("reviews", [])[:3]]
            
            place_obj = {
                "google_place_id": p.get("id"),
                "name": p.get("displayName", {}).get("text"),
                "address": p.get("formattedAddress"),
                "rating": p.get("rating"),
                "business_status": p.get("businessStatus"),
                "is_open_now": p.get("regularOpeningHours", {}).get("openNow"),
                "opening_hours_weekday": p.get("regularOpeningHours", {}).get("weekdayDescriptions"),
                "phone": p.get("nationalPhoneNumber"),
                "website": p.get("websiteUri"),
                "price_level": p.get("priceLevel"),
                "coordinates": p.get("location"),
                "photo_reference": photo,
                "review_list": reviews
            }
            cleaned_list.append(place_obj)

        return cleaned_list

    except Exception as e:
        print(f"❌ [API Error] {str(e)}")
        return []

def query_places_from_db(place_ids: list = None, query_hint: str = None, location: str = None) -> str:
    """
    【新增】从数据库查询地点
    - 如果有 place_ids，直接按 ID 查询
    - 如果有 query_hint 和 location，进行模糊匹配
    返回: JSON 字符串，供 AI 筛选
    """
    try:
        if place_ids:
            places = Place.query.filter(Place.id.in_(place_ids)).all()
        elif query_hint:
            # 模糊搜索 (简单版，可以优化为全文搜索)
            places = Place.query.filter(
                db.or_(
                    Place.name.ilike(f"%{query_hint}%"),
                    Place.address.ilike(f"%{query_hint}%")
                )
            ).limit(20).all()
        else:
            return json.dumps({"message": "需要提供 place_ids 或 query_hint"})

        if not places:
            return json.dumps({"message": "数据库中未找到匹配的地点"})

        # 转换为 JSON
        result = []
        for place in places:
            result.append({
                "id": place.id,
                "google_place_id": place.google_place_id,
                "name": place.name,
                "address": place.address,
                "rating": place.rating,
                "business_status": place.business_status,
                "is_open_now": place.is_open_now,
                "opening_hours_weekday": place.opening_hours,
                "phone": place.phone,
                "website": place.website,
                "price_level": place.price_level,
                "coordinates": place.coordinates,
                "photo_reference": place.photo_reference,
                "review_list": place.review_list,
                "cached_at": place.cached_at.isoformat() if place.cached_at else None
            })

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"数据库查询失败: {str(e)}"})

def search_nearby_places(query: str, location: str, radius: int = 5000) -> str:
    """
    【新逻辑 - 分阶段处理】
    阶段 1: 调用 API 获取数据
    阶段 2: 存入数据库
    阶段 3: 返回 "数据已存储" 信号 + place_ids
    (AI 会接收到这个信号，然后调用 query_places_from_db 进行筛选)
    """
    clean_query = normalize_key(query)
    clean_location = normalize_key(location)
    
    if "," in clean_location:
        try:
            lat, lng = map(float, clean_location.split(','))
            clean_location = f"{round(lat, 2)},{round(lng, 2)}"
        except: pass

    print(f"--- [Tool: Search] 请求: Q='{clean_query}', Loc='{clean_location}' ---")

    # 阶段 1: 获取 API 数据
    places_data = fetch_places_from_api(query, location, radius)
    
    if not places_data:
        return json.dumps({"message": "未找到任何地点，请尝试不同的关键词"})

    # 阶段 2: 存入数据库
    saved_ids = save_places_to_db(places_data)

    if not saved_ids:
        return json.dumps({"error": "数据存储失败"})

    # 阶段 3: 返回信号给 AI，让它调用 query_places_from_db
    return json.dumps({
        "status": "data_stored",
        "message": f"已找到 {len(saved_ids)} 个地点并存入数据库",
        "place_ids": saved_ids,
        "hint": "请使用 query_places_from_db 工具从数据库获取详细信息并筛选最符合用户需求的地点"
    }, ensure_ascii=False)