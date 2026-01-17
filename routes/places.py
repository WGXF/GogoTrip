# routes/places.py

from flask import Blueprint, request, jsonify
from models import db, Place
from sqlalchemy import or_
import json
import re
import requests  # ✅ 新增：用于调用 Google API
import os
from datetime import datetime

# ✅ 修复：使用 url_prefix 为空，路由中包含完整路径
# 这样无论在 app.py 中如何注册，路由都是正确的
places_bp = Blueprint('places', __name__, url_prefix='/api/places')

# ============================================
# Google Places API 配置
# ============================================
GOOGLE_API_KEY = os.getenv('AIzaSyBtwosPLRjd7k1ztaAwTEVIIgIus3CMMvw', '')  # 从环境变量读取
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


# ============================================
# Google API 集成函数
# ============================================
def fetch_and_save_google_place(place_name: str) -> Place:
    """
    从 Google Places API 获取地点信息并保存到数据库
    
    Args:
        place_name: 地点名称
        
    Returns:
        Place: 保存后的 Place 对象
        None: 如果获取失败
    """
    if not GOOGLE_API_KEY:
        print("❌ [Google API] API Key 未配置")
        return None
    
    try:
        print(f"🌐 [Google API] 开始搜索: {place_name}")
        
        # ===============================================
        # 1. 使用 Text Search API 搜索地点
        # ===============================================
        search_params = {
            'query': place_name,
            'key': GOOGLE_API_KEY,
            'language': 'zh-CN',  # 中文优先
        }
        
        search_response = requests.get(GOOGLE_PLACES_TEXT_SEARCH_URL, params=search_params, timeout=10)
        search_data = search_response.json()
        
        if search_data.get('status') != 'OK' or not search_data.get('results'):
            print(f"⚠️ [Google API] 未找到结果: {search_data.get('status')}")
            return None
        
        # 取第一个结果
        place_data = search_data['results'][0]
        google_place_id = place_data.get('place_id')
        
        print(f"✅ [Google API] 找到地点: {place_data.get('name')} (ID: {google_place_id})")
        
        # ===============================================
        # 2. 使用 Place Details API 获取详细信息
        # ===============================================
        details_params = {
            'place_id': google_place_id,
            'key': GOOGLE_API_KEY,
            'language': 'zh-CN',
            'fields': 'place_id,name,formatted_address,rating,opening_hours,formatted_phone_number,website,price_level,geometry,photos,reviews,business_status'
        }
        
        details_response = requests.get(GOOGLE_PLACES_DETAILS_URL, params=details_params, timeout=10)
        details_data = details_response.json()
        
        if details_data.get('status') != 'OK':
            print(f"⚠️ [Google API] 获取详情失败: {details_data.get('status')}")
            # 即使详情失败，也尝试保存基本信息
            details_result = place_data
        else:
            details_result = details_data.get('result', {})
        
        # ===============================================
        # 3. 检查数据库中是否已存在
        # ===============================================
        existing_place = Place.query.filter_by(google_place_id=google_place_id).first()
        
        if existing_place:
            print(f"ℹ️ [Google API] 地点已存在于数据库，更新缓存")
            place = existing_place
        else:
            print(f"💾 [Google API] 创建新地点记录")
            place = Place(google_place_id=google_place_id)
            db.session.add(place)
        
        # ===============================================
        # 4. 填充/更新数据
        # ===============================================
        place.name = details_result.get('name')
        place.address = details_result.get('formatted_address')
        place.rating = details_result.get('rating')
        place.business_status = details_result.get('business_status', 'OPERATIONAL')
        
        # 营业时间
        opening_hours_data = details_result.get('opening_hours', {})
        place.is_open_now = opening_hours_data.get('open_now')
        place.opening_hours = json.dumps(opening_hours_data.get('weekday_text', []))
        
        # 联系方式
        place.phone = details_result.get('formatted_phone_number')
        place.website = details_result.get('website')
        
        # 价格等级
        price_level = details_result.get('price_level')
        if price_level is not None:
            place.price_level = '$' * price_level if price_level > 0 else 'Free'
        
        # 坐标
        geometry = details_result.get('geometry', {})
        location = geometry.get('location', {})
        if location:
            place.coordinates = json.dumps({
                'lat': location.get('lat'),
                'lng': location.get('lng')
            })
        
        # 照片（取第一张）
        photos = details_result.get('photos', [])
        if photos and len(photos) > 0:
            place.photo_reference = photos[0].get('photo_reference')
        
        # 评论（取前5条）
        reviews = details_result.get('reviews', [])
        if reviews:
            simplified_reviews = []
            for review in reviews[:5]:
                simplified_reviews.append({
                    'author': review.get('author_name'),
                    'rating': review.get('rating'),
                    'text': review.get('text', '')[:200],  # 只保存前200字
                    'time': review.get('relative_time_description')
                })
            place.review_list = json.dumps(simplified_reviews)
        
        # 更新缓存时间
        place.cached_at = datetime.utcnow()
        
        # ===============================================
        # 5. 保存到数据库
        # ===============================================
        db.session.commit()
        print(f"✅ [Google API] 地点已保存: {place.name} (DB ID: {place.id})")
        
        return place
        
    except requests.RequestException as e:
        print(f"❌ [Google API] 网络请求失败: {str(e)}")
        return None
    except Exception as e:
        print(f"❌ [Google API] 处理失败: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return None


@places_bp.route('/search', methods=['GET'])
def search_places():
    """
    智能搜索：解决"搜索词比数据库名字长"导致匹配失败的问题
    """
    try:
        raw_name = request.args.get('name', '').strip()
        limit = request.args.get('limit', 5, type=int)
        
        print(f"🔍 [Search Start] 原始输入: '{raw_name}'")
        
        if not raw_name:
            return jsonify({'error': '地点名称不能为空'}), 400

        # ===============================================
        # 1. 关键词清洗与生成策略
        # ===============================================
        search_candidates = []

        # 策略 A: 原始搜索 (最精确)
        search_candidates.append(raw_name)

        # 策略 B: 去除括号 (针对 AI 生成的 "Name (Description)" 格式)
        # 输入: "Dutch Square (Red Square) Melaka" -> 输出: "Dutch Square Melaka"
        clean_name = re.sub(r'\s*\(.*?\)', '', raw_name).strip()
        if clean_name != raw_name:
            search_candidates.append(clean_name)

        # 策略 C: 提取核心词 (解决 "xxx Melaka" 搜不到 "xxx" 的问题)
        # 输入: "Dutch Square Melaka" -> 提取前两个词 -> "Dutch Square"
        # 这一步至关重要！它能让长的搜索词匹配到短的数据库名
        words = clean_name.split()
        if len(words) >= 2:
            core_name = " ".join(words[:2]) # 取前两个词
            search_candidates.append(core_name)
        
        if len(words) >= 1:
            first_word = words[0] # 绝望模式：只搜第一个词 (如 "Dutch")
            search_candidates.append(first_word)

        # 去重并保持顺序
        search_candidates = list(dict.fromkeys(search_candidates))
        print(f"💡 [Search Strategy] 将尝试以下关键词: {search_candidates}")

        # ===============================================
        # 2. 循环尝试搜索
        # ===============================================
        places = []
        
        for term in search_candidates:
            # 防止搜索词太短导致匹配全库 (例如只搜 "A")
            if len(term) < 2: 
                continue

            print(f"   👉 正在尝试匹配: '{term}' ...")
            
            query = Place.query.filter(
                or_(
                    Place.name.ilike(f'%{term}%'),      # 名字包含关键词
                    Place.address.ilike(f'%{term}%')    # 地址包含关键词
                )
            ).limit(limit)
            
            found = query.all()
            
            if found:
                print(f"   ✅ 匹配成功! 找到 {len(found)} 个结果 (关键词: '{term}')")
                places = found
                break # 找到了就停止，不再尝试更模糊的词
        
        # ===============================================
        # 3. Google API Fallback (如果本地彻底没找到)
        # ===============================================
        if not places:
            print(f"⚠️ [Local Fail] 本地数据库未找到任何匹配，尝试 Google API...")
            
            # ✅ 调用 Google API 获取地点
            new_place = fetch_and_save_google_place(clean_name)
            
            if new_place: 
                places = [new_place]
                print(f"   ✅ [Google Success] 从 Google 抓取成功并保存")
            else:
                print(f"   ❌ [Google Fail] Google API 也未找到")

        # ===============================================
        # 4. 返回结果
        # ===============================================
        if not places:
            print(f"❌ [Final Fail] 彻底未找到: {raw_name}")
            return jsonify({'message': '未找到匹配的地点', 'results': []}), 404
        
        results = [_place_to_dict(place) for place in places]
        return jsonify(results), 200
    
    except Exception as e:
        print(f"❌ [System Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@places_bp.route('/<int:place_id>', methods=['GET'])
def get_place_by_id(place_id):
    """
    通过 ID 获取单个地点的详细信息
    
    完整路径: GET /api/places/<place_id>
    
    Path Parameters:
    - place_id: 地点的数据库 ID
    
    Returns:
    - JSON 对象，包含地点详细信息
    """
    try:
        print(f"🔍 [Places API] 获取地点 ID: {place_id}")
        
        place = Place.query.get(place_id)
        
        if not place:
            return jsonify({'error': '地点不存在'}), 404
        
        result = _place_to_dict(place)
        
        print(f"✅ [Places API] 成功返回地点: {place.name}")
        return jsonify(result), 200
    
    except Exception as e:
        print(f"❌ [Places API Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@places_bp.route('/batch', methods=['POST'])
def get_places_batch():
    """
    批量获取多个地点的详细信息
    
    完整路径: POST /api/places/batch
    
    Request Body:
    {
        "place_names": ["Petronas Twin Towers", "Batu Caves", ...]
    }
    
    Returns:
    - JSON 数组，包含所有找到的地点
    """
    try:
        data = request.json
        place_names = data.get('place_names', [])
        
        print(f"🔍 [Places API] 批量查询 {len(place_names)} 个地点")
        
        if not place_names or not isinstance(place_names, list):
            return jsonify({'error': '请提供地点名称数组'}), 400
        
        # 批量查询
        places = Place.query.filter(Place.name.in_(place_names)).all()
        
        print(f"✅ [Places API] 找到 {len(places)} 个匹配结果")
        
        if not places:
            return jsonify({'message': '未找到任何匹配的地点', 'results': []}), 404
        
        # 转换为 JSON
        results = [_place_to_dict(place) for place in places]
        
        return jsonify({
            'total': len(results),
            'results': results
        }), 200
    
    except Exception as e:
        print(f"❌ [Places API Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@places_bp.route('/nearby', methods=['GET'])
def get_nearby_places():
    """
    获取坐标附近的地点 (简化版，基于数据库现有数据)
    
    完整路径: GET /api/places/nearby?lat=xxx&lng=xxx
    
    Query Parameters:
    - lat: 纬度
    - lng: 经度
    - radius: 半径 (公里，默认 5)
    - limit: 返回数量 (默认 10)
    
    Note: 这是简化版本，真正的地理搜索需要 PostGIS 或类似扩展
    """
    try:
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        limit = request.args.get('limit', 10, type=int)
        
        print(f"🔍 [Places API] 查询附近地点: ({lat}, {lng})")
        
        if lat is None or lng is None:
            return jsonify({'error': '请提供 lat 和 lng 参数'}), 400
        
        # 简化版：返回最近缓存的地点 (实际应用中需要地理计算)
        places = Place.query.order_by(Place.cached_at.desc()).limit(limit).all()
        
        results = []
        for place in places:
            coordinates = place.coordinates
            if isinstance(coordinates, str):
                try:
                    coordinates = json.loads(coordinates)
                except:
                    coordinates = None
            
            results.append({
                'id': place.id,
                'name': place.name,
                'address': place.address,
                'rating': place.rating,
                'coordinates': coordinates,
                'photo_reference': place.photo_reference
            })
        
        return jsonify(results), 200
    
    except Exception as e:
        print(f"❌ [Places API Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


# ============================================
# 辅助函数：将 Place 模型转换为字典
# ============================================
def _place_to_dict(place):
    """安全地将 Place 对象转换为字典，处理 JSON 字段"""
    # 安全解析 coordinates
    coordinates = place.coordinates
    if isinstance(coordinates, str):
        try:
            coordinates = json.loads(coordinates)
        except:
            coordinates = None
    
    # 安全解析 opening_hours
    opening_hours = place.opening_hours
    if isinstance(opening_hours, str):
        try:
            opening_hours = json.loads(opening_hours)
        except:
            opening_hours = []
    
    # 安全解析 review_list
    review_list = place.review_list
    if isinstance(review_list, str):
        try:
            review_list = json.loads(review_list)
        except:
            review_list = []
    
    return {
        'id': place.id,
        'google_place_id': place.google_place_id,
        'name': place.name,
        'address': place.address,
        'rating': place.rating,
        'business_status': place.business_status,
        'is_open_now': place.is_open_now,
        'opening_hours': opening_hours,
        'phone': place.phone,
        'website': place.website,
        'price_level': place.price_level,
        'coordinates': coordinates,
        'photo_reference': place.photo_reference,
        'review_list': review_list,
        'cached_at': place.cached_at.isoformat() if place.cached_at else None
    }