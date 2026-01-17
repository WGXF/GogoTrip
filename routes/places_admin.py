# routes/places_admin.py

from flask import Blueprint, request, jsonify
from models import db, Place
import requests
import os
import json
import uuid
from datetime import datetime
from functools import wraps

# Blueprint 配置
places_admin_bp = Blueprint('places_admin', __name__, url_prefix='/api/admin/places')

# Google API 配置
GOOGLE_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'AIzaSyBtwosPLRjd7k1ztaAwTEVIIgIus3CMMvw')
GOOGLE_PLACES_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


# ============================================
# 辅助函数
# ============================================
def generate_manual_place_id():
    """
    为手动创建的地点生成唯一 ID
    格式: manual_<uuid> 以区分 Google 自动获取的地点
    """
    return f"manual_{uuid.uuid4().hex[:16]}"


def _place_to_admin_dict(place):
    """将 Place 对象转换为 Admin 视图的字典"""
    # 安全解析 JSON 字段
    def safe_json_parse(value, default=None):
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except:
            return default

    return {
        'id': place.id,
        'google_place_id': place.google_place_id,
        'name': place.name,
        'address': place.address,
        'rating': place.rating,
        'business_status': place.business_status,
        'is_open_now': place.is_open_now,
        'opening_hours': safe_json_parse(place.opening_hours, []),
        'phone': place.phone,
        'website': place.website,
        'price_level': place.price_level,
        'coordinates': safe_json_parse(place.coordinates),
        'photo_reference': place.photo_reference,
        'review_list': safe_json_parse(place.review_list, []),
        'cached_at': place.cached_at.isoformat() if place.cached_at else None,
        # Admin 专用字段
        'is_manual': bool(place.is_manual),  # 🔴 SINGLE SOURCE OF TRUTH - ensure boolean (handles None → False)
        'category': _infer_category(place)  # 推断分类用于前端显示
    }


def _infer_category(place):
    """根据地点信息推断分类（用于前端显示）"""
    name_lower = (place.name or '').lower()
    address_lower = (place.address or '').lower()
    
    # 简单的关键词匹配
    if any(kw in name_lower for kw in ['restaurant', 'cafe', 'coffee', 'food', 'bakery']):
        return 'Food & Drink'
    elif any(kw in name_lower for kw in ['hotel', 'resort', 'hostel', 'inn']):
        return 'Accommodation'
    elif any(kw in name_lower for kw in ['museum', 'gallery', 'temple', 'mosque', 'church']):
        return 'Culture'
    elif any(kw in name_lower for kw in ['park', 'beach', 'mountain', 'waterfall']):
        return 'Nature'
    elif any(kw in name_lower for kw in ['mall', 'market', 'shop', 'store']):
        return 'Shopping'
    elif any(kw in name_lower for kw in ['tower', 'landmark', 'monument', 'square']):
        return 'Landmark'
    else:
        return 'General'


# ============================================
# ⚠️ 重要：静态路由必须在动态路由之前定义！
# ============================================

# ============================================
# Google Places 搜索 API（给前端 Autocomplete 用）
# ============================================

@places_admin_bp.route('/google/search', methods=['GET'])
def google_search():
    """
    Google Places 搜索（用于 Admin 添加地点时的实时搜索）
    
    Query Parameters:
    - q: 搜索关键词
    - region: 区域偏好 (如 'my' 表示 Malaysia)
    
    Returns:
    - 搜索结果列表（简化版，仅包含选择所需信息）
    """
    try:
        query = request.args.get('q', '').strip()
        region = request.args.get('region', 'my')  # 默认 Malaysia

        print(f"🔍 [Google Search] Query: '{query}', Region: {region}")

        if not query or len(query) < 2:
            return jsonify([]), 200

        if not GOOGLE_API_KEY:
            print("❌ [Google Search] API Key not configured!")
            return jsonify({'error': 'Google API Key not configured'}), 500

        # 使用 Text Search API（比 Autocomplete 返回更多信息）
        params = {
            'query': query,
            'key': GOOGLE_API_KEY,
            'language': 'en',
            'region': region
        }

        response = requests.get(GOOGLE_PLACES_TEXT_SEARCH_URL, params=params, timeout=10)
        data = response.json()

        if data.get('status') != 'OK':
            print(f"⚠️ [Google Search] Status: {data.get('status')}, Error: {data.get('error_message', 'N/A')}")
            return jsonify([]), 200

        # 简化结果
        results = []
        for place in data.get('results', [])[:8]:  # 最多返回 8 个
            results.append({
                'place_id': place.get('place_id'),
                'name': place.get('name'),
                'address': place.get('formatted_address'),
                'rating': place.get('rating'),
                'types': place.get('types', [])[:3],  # 只取前3个类型
                'photo_reference': place.get('photos', [{}])[0].get('photo_reference') if place.get('photos') else None
            })

        print(f"✅ [Google Search] Found {len(results)} results")
        return jsonify(results), 200

    except requests.RequestException as e:
        print(f"❌ [Google Search] Network error: {str(e)}")
        return jsonify({'error': 'Network error'}), 500
    except Exception as e:
        print(f"❌ [Google Search] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@places_admin_bp.route('/google/import', methods=['POST'])
def import_from_google():
    """
    从 Google Places 导入地点到数据库
    
    Request Body:
    {
        "place_id": "ChIJ..."  // Google Place ID
    }
    
    Returns:
    - 导入后的 Place 对象
    """
    try:
        data = request.json
        google_place_id = data.get('place_id')

        if not google_place_id:
            return jsonify({'error': 'place_id is required'}), 400

        if not GOOGLE_API_KEY:
            return jsonify({'error': 'Google API Key not configured'}), 500

        # 检查是否已存在
        existing = Place.query.filter_by(google_place_id=google_place_id).first()
        if existing:
            return jsonify({
                'success': True,
                'message': 'Place already exists',
                'place': _place_to_admin_dict(existing),
                'is_new': False
            }), 200

        # 获取详细信息
        params = {
            'place_id': google_place_id,
            'key': GOOGLE_API_KEY,
            'language': 'en',
            'fields': 'place_id,name,formatted_address,rating,opening_hours,formatted_phone_number,website,price_level,geometry,photos,reviews,business_status'
        }

        response = requests.get(GOOGLE_PLACES_DETAILS_URL, params=params, timeout=10)
        result = response.json()

        if result.get('status') != 'OK':
            return jsonify({'error': f"Google API error: {result.get('status')}"}), 400

        details = result.get('result', {})

        # 创建新地点
        place = Place(
            google_place_id=google_place_id,
            name=details.get('name'),
            address=details.get('formatted_address'),
            rating=details.get('rating'),
            business_status=details.get('business_status', 'OPERATIONAL'),
            phone=details.get('formatted_phone_number'),
            website=details.get('website'),
            is_manual=False,
            cached_at=datetime.utcnow(),
        )

        # 营业时间
        opening_hours = details.get('opening_hours', {})
        place.is_open_now = opening_hours.get('open_now')
        place.opening_hours = json.dumps(opening_hours.get('weekday_text', []))

        # 价格等级
        price_level = details.get('price_level')
        if price_level is not None:
            place.price_level = '$' * price_level if price_level > 0 else 'Free'

        # 坐标
        geometry = details.get('geometry', {})
        location = geometry.get('location', {})
        if location:
            place.coordinates = json.dumps({
                'lat': location.get('lat'),
                'lng': location.get('lng')
            })

        # 照片
        photos = details.get('photos', [])
        if photos:
            place.photo_reference = photos[0].get('photo_reference')

        # 评论
        reviews = details.get('reviews', [])
        if reviews:
            simplified_reviews = [{
                'author': r.get('author_name'),
                'rating': r.get('rating'),
                'text': r.get('text', '')[:200],
                'time': r.get('relative_time_description')
            } for r in reviews[:5]]
            place.review_list = json.dumps(simplified_reviews)

        db.session.add(place)
        db.session.commit()

        print(f"✅ [Admin Import] Place imported: {place.name} (ID: {place.id})")

        return jsonify({
            'success': True,
            'message': 'Place imported successfully',
            'place': _place_to_admin_dict(place),
            'is_new': True
        }), 201

    except requests.RequestException as e:
        print(f"❌ [Google Import] Network error: {str(e)}")
        return jsonify({'error': 'Network error'}), 500
    except Exception as e:
        db.session.rollback()
        print(f"❌ [Google Import] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================
# 手动创建地点 API
# ============================================

@places_admin_bp.route('/manual', methods=['POST'])
def create_manual_place():
    """
    手动创建地点（不使用 Google API）
    
    Request Body:
    {
        "name": "My Custom Place",        // 必填
        "address": "123 Main Street",     // 必填
        "rating": 4.5,                    // 可选
        "phone": "+60123456789",          // 可选
        "website": "https://...",         // 可选
        "price_level": "$$",              // 可选
        "coordinates": {                  // 可选
            "lat": 3.1234,
            "lng": 101.5678
        }
    }
    """
    try:
        data = request.json

        # 验证必填字段
        name = data.get('name', '').strip()
        address = data.get('address', '').strip()

        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if not address:
            return jsonify({'error': 'Address is required'}), 400

        # 生成唯一 ID
        manual_id = generate_manual_place_id()

        # 创建地点
        place = Place(
            google_place_id=manual_id,
            name=name,
            address=address,
            rating=data.get('rating'),
            phone=data.get('phone'),
            website=data.get('website'),
            price_level=data.get('price_level'),
            is_manual=True,
            business_status='OPERATIONAL',
            cached_at=datetime.utcnow()
        )

        # 坐标
        coords = data.get('coordinates')
        if coords and isinstance(coords, dict):
            place.coordinates = json.dumps(coords)

        db.session.add(place)
        db.session.commit()

        print(f"✅ [Admin Manual] Place created: {place.name} (ID: {place.id})")

        return jsonify({
            'success': True,
            'message': 'Place created successfully',
            'place': _place_to_admin_dict(place)
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"❌ [Manual Create] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================
# 统计 API
# ============================================

@places_admin_bp.route('/stats', methods=['GET'])
def get_stats():
    """获取地点统计信息"""
    try:
        total = Place.query.count()
        manual_count = Place.query.filter(Place.is_manual == True).count()
        google_count = total - manual_count

        # 按评分分布
        high_rated = Place.query.filter(Place.rating >= 4.0).count()
        
        return jsonify({
            'total': total,
            'google': google_count,
            'manual': manual_count,
            'high_rated': high_rated
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# Admin CRUD API（动态路由放在最后！）
# ============================================

@places_admin_bp.route('', methods=['GET'])
def list_places():
    """
    获取所有地点列表（Admin 视图）
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()
        source = request.args.get('source', 'all')

        query = Place.query

        # 🔍 搜索过滤
        if search:
            query = query.filter(
                db.or_(
                    Place.name.ilike(f'%{search}%'),
                    Place.address.ilike(f'%{search}%')
                )
            )

        # 🔥 来源筛选 —— 只看 is_manual
        if source == 'manual':
            query = query.filter(Place.is_manual == True)
        elif source == 'google':
            query = query.filter(Place.is_manual == False)

        # 排序
        query = query.order_by(Place.cached_at.desc())

        # 查询
        places = query.all()

        # ✅【关键】强制统一使用 Admin Dict
        places_data = [_place_to_admin_dict(p) for p in places]

        return jsonify({
            'success': True,
            'places': places_data
        }), 200

    except Exception as e:
        print(f"❌ [Admin List] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



@places_admin_bp.route('/<int:place_id>', methods=['GET'])
def get_place(place_id):
    """获取单个地点详情"""
    try:
        place = Place.query.get_or_404(place_id)
        return jsonify(_place_to_admin_dict(place)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@places_admin_bp.route('/<int:place_id>', methods=['DELETE'])
def delete_place(place_id):
    """删除地点"""
    try:
        place = Place.query.get_or_404(place_id)
        db.session.delete(place)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Place deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@places_admin_bp.route('/<int:place_id>', methods=['PUT'])
def update_place(place_id):
    """
    Update place info.
    
    ✅ SINGLE SOURCE OF TRUTH: is_manual field
    - is_manual is updated directly from request if provided
    - google_place_id is treated purely as an identifier (NOT used to infer source)
    - No prefix-based logic or inference
    """
    try:
        place = Place.query.get_or_404(place_id)
        data = request.json

        print(f"📝 [Update Request] ID: {place_id}, Data: {data}")

        # ✅ Handle is_manual field directly (SINGLE SOURCE OF TRUTH)
        # Only update if explicitly provided in request
        if 'is_manual' in data:
            place.is_manual = bool(data['is_manual'])
            print(f"🔄 [Source Update] Place {place.id} is_manual set to: {place.is_manual}")

        # Standard Field Updates
        updatable_fields = ['name', 'address', 'rating', 'phone', 'website', 
                           'price_level', 'business_status']
        
        for field in updatable_fields:
            if field in data:
                setattr(place, field, data[field])

        # Handle Coordinates
        if 'coordinates' in data:
            coords = data['coordinates']
            if isinstance(coords, dict):
                place.coordinates = json.dumps(coords)
            elif coords is not None: # Allow clearing coordinates if null
                place.coordinates = coords

        place.cached_at = datetime.utcnow()
        db.session.commit()

        print("✅ [Update Success] Database committed.")
        return jsonify(_place_to_admin_dict(place)), 200

    except Exception as e:
        db.session.rollback()
        print(f"❌ [Update Error]: {str(e)}")
        import traceback
        traceback.print_exc() # Print full error to console
        return jsonify({'error': str(e)}), 500