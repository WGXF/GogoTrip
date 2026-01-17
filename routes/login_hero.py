# routes/login_hero.py
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import db, LoginHeroConfig, HeroImage, Place
from functools import wraps

login_hero_bp = Blueprint('login_hero', __name__)

# 权限检查装饰器
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'super_admin', 'Admin', 'super_admin', 'Administrator']:
            return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 公开接口：获取激活的 Hero 配置（供前端 LoginView 使用）
# ==========================================
@login_hero_bp.route('/api/login-hero/active', methods=['GET'])
def get_active_hero_config():
    """
    获取当前激活的 Hero 配置
    返回完整配置以及解析后的图片数据
    """
    try:
        config = LoginHeroConfig.query.filter_by(is_active=True).first()
        
        if not config:
            # 返回默认配置
            return jsonify({
                'status': 'success',
                'config': {
                    'displayMode': 'single',
                    'transitionInterval': 5,
                    'autoPlay': True,
                    'imageSource': 'url',
                    'enableGradient': True,
                    'images': [{
                        'url': 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&q=80&w=2000',
                        'alt': 'Travel'
                    }],
                    'title': 'Plan your next great adventure in seconds.',
                    'subtitle': None,
                    'description': 'Join thousands of travelers using AI to craft the perfect itinerary, track expenses, and explore the world.'
                }
            })
        
        # 根据 image_source 解析图片数据
        images = []
        
        if config.image_source == 'url':
            # 直接使用 URL
            images = config.images_config
            
        elif config.image_source == 'database':
            # 从 HeroImage 表获取（已由 to_dict() 处理好 URL）
            for img_config in config.images_config:
                image_id = img_config.get('image_id')
                hero_image = HeroImage.query.get(image_id)
                if hero_image and hero_image.is_active:
                    hero_dict = hero_image.to_dict()
                    images.append({
                        'url': hero_dict['imageUrl'],  # 已处理的 URL（包括 proxy）
                        'alt': hero_image.alt_text or hero_image.title
                    })
                    
        elif config.image_source == 'places':
            # 从 Place 表获取，使用 proxy URL
            for place_config in config.images_config:
                place_id = place_config.get('place_id')
                place = Place.query.get(place_id)
                if place and place.photo_reference:
                    # 🔥 使用 proxy_image API
                    images.append({
                        'url': f'/proxy_image?ref={place.photo_reference}',
                        'alt': place.name
                    })
        
        return jsonify({
            'status': 'success',
            'config': {
                'displayMode': config.display_mode,
                'transitionInterval': config.transition_interval,
                'autoPlay': config.auto_play,
                'imageSource': config.image_source,
                'enableGradient': config.enable_gradient,
                'images': images,
                'title': config.title,
                'subtitle': config.subtitle,
                'description': config.description
            }
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：获取所有配置
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/configs', methods=['GET'])
@admin_required
def get_all_configs():
    """获取所有 Hero 配置"""
    try:
        configs = LoginHeroConfig.query.order_by(LoginHeroConfig.updated_at.desc()).all()
        return jsonify({
            'status': 'success',
            'configs': [config.to_dict() for config in configs]
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：创建新配置
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/configs', methods=['POST'])
@admin_required
def create_config():
    """创建新的 Hero 配置"""
    try:
        data = request.get_json()
        
        # 如果设置为激活，先停用其他配置
        if data.get('isActive', False):
            LoginHeroConfig.query.update({'is_active': False})
        
        config = LoginHeroConfig(
            display_mode=data.get('displayMode', 'single'),
            transition_interval=data.get('transitionInterval', 5),
            auto_play=data.get('autoPlay', True),
            image_source=data.get('imageSource', 'url'),
            images_config=data.get('imagesConfig', []),
            title=data.get('title'),
            subtitle=data.get('subtitle'),
            description=data.get('description'),
            enable_gradient=data.get('enableGradient', True),
            is_active=data.get('isActive', False),
            created_by=current_user.id
        )
        
        db.session.add(config)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Configuration created successfully',
            'config': config.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：更新配置
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/configs/<int:config_id>', methods=['PUT'])
@admin_required
def update_config(config_id):
    """更新 Hero 配置"""
    try:
        config = LoginHeroConfig.query.get_or_404(config_id)
        data = request.get_json()
        
        # 如果设置为激活，先停用其他配置
        if data.get('isActive', False) and not config.is_active:
            LoginHeroConfig.query.filter(LoginHeroConfig.id != config_id).update({'is_active': False})
        
        # 更新字段
        config.display_mode = data.get('displayMode', config.display_mode)
        config.transition_interval = data.get('transitionInterval', config.transition_interval)
        config.auto_play = data.get('autoPlay', config.auto_play)
        config.image_source = data.get('imageSource', config.image_source)
        config.images_config = data.get('imagesConfig', config.images_config)
        config.title = data.get('title', config.title)
        config.subtitle = data.get('subtitle', config.subtitle)
        config.description = data.get('description', config.description)
        config.enable_gradient = data.get('enableGradient', config.enable_gradient)
        config.is_active = data.get('isActive', config.is_active)
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Configuration updated successfully',
            'config': config.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：删除配置
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/configs/<int:config_id>', methods=['DELETE'])
@admin_required
def delete_config(config_id):
    """删除 Hero 配置"""
    try:
        config = LoginHeroConfig.query.get_or_404(config_id)
        db.session.delete(config)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Configuration deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：激活配置
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/configs/<int:config_id>/activate', methods=['POST'])
@admin_required
def activate_config(config_id):
    """激活指定的 Hero 配置"""
    try:
        # 停用所有配置
        LoginHeroConfig.query.update({'is_active': False})
        
        # 激活指定配置
        config = LoginHeroConfig.query.get_or_404(config_id)
        config.is_active = True
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Configuration activated successfully',
            'config': config.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：获取所有 Hero 图片（数据库存储）
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/images', methods=['GET'])
@admin_required
def get_all_hero_images():
    """获取所有 Hero 图片"""
    try:
        images = HeroImage.query.order_by(HeroImage.sort_order, HeroImage.created_at.desc()).all()
        return jsonify({
            'status': 'success',
            'images': [img.to_dict() for img in images]
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：上传 Hero 图片
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/images/upload', methods=['POST'])
@admin_required
def upload_hero_image():
    """
    上传图片到服务器
    图片存储到 /static/hero-images/ 目录
    """
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({
                'status': 'error',
                'message': 'No file provided'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'status': 'error',
                'message': 'No file selected'
            }), 400
        
        # 验证文件类型
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_extensions:
            return jsonify({
                'status': 'error',
                'message': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'
            }), 400
        
        # 生成唯一文件名
        import os
        import uuid
        from datetime import datetime
        
        filename = f"{uuid.uuid4().hex}_{int(datetime.now().timestamp())}.{file_ext}"
        
        # 确保目录存在
        upload_dir = os.path.join('static', 'hero-images')
        os.makedirs(upload_dir, exist_ok=True)
        
        # 保存文件
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        # 生成访问 URL
        image_url = f'/static/hero-images/{filename}'
        
        # 获取表单数据
        title = request.form.get('title', 'Uploaded Image')
        description = request.form.get('description', '')
        alt_text = request.form.get('altText', title)
        
        # 创建数据库记录
        image = HeroImage(
            title=title,
            description=description,
            image_type='url',  # 上传的图片是直接 URL
            image_url=image_url,
            source='uploaded',
            alt_text=alt_text,
            sort_order=0,
            is_active=True,
            added_by=current_user.id
        )
        
        db.session.add(image)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Image uploaded successfully',
            'image': image.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：从 Places 添加图片到库
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/images/from-place', methods=['POST'])
@admin_required
def add_image_from_place():
    """
    从 Places 添加图片到 Hero 库
    """
    try:
        data = request.get_json()
        place_id = data.get('placeId')
        
        if not place_id:
            return jsonify({
                'status': 'error',
                'message': 'Place ID is required'
            }), 400
        
        place = Place.query.get_or_404(place_id)
        
        if not place.photo_reference:
            return jsonify({
                'status': 'error',
                'message': 'This place has no photo'
            }), 400
        
        # 创建 HeroImage 记录，type 为 proxy
        image = HeroImage(
            title=data.get('title') or place.name,
            description=data.get('description') or f'Image from {place.name}',
            image_type='proxy',  # 🔥 需要通过 proxy_image
            image_url=place.photo_reference,  # 存储 photo_reference
            source='places',
            source_place_id=place_id,
            alt_text=data.get('altText') or place.name,
            sort_order=data.get('sortOrder', 0),
            is_active=data.get('isActive', True),
            added_by=current_user.id
        )
        
        db.session.add(image)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Image added from place successfully',
            'image': image.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：更新 Hero 图片
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/images/<int:image_id>', methods=['PUT'])
@admin_required
def update_hero_image(image_id):
    """更新 Hero 图片"""
    try:
        image = HeroImage.query.get_or_404(image_id)
        data = request.get_json()
        
        # 更新基本字段
        image.title = data.get('title', image.title)
        image.description = data.get('description', image.description)
        image.alt_text = data.get('altText', image.alt_text)
        image.sort_order = data.get('sortOrder', image.sort_order)
        image.is_active = data.get('isActive', image.is_active)
        
        # 如果更新了 URL，需要判断类型
        if 'imageUrl' in data:
            new_url = data['imageUrl']
            # 判断是否是 proxy URL
            if 'places/' in new_url or 'photos/' in new_url:
                image.image_type = 'proxy'
            else:
                image.image_type = 'url'
            image.image_url = new_url
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Image updated successfully',
            'image': image.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：删除 Hero 图片
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/images/<int:image_id>', methods=['DELETE'])
@admin_required
def delete_hero_image(image_id):
    """删除 Hero 图片"""
    try:
        image = HeroImage.query.get_or_404(image_id)
        db.session.delete(image)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Image deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# Admin 接口：获取可用的 Places（用于选择）
# ==========================================
@login_hero_bp.route('/api/admin/login-hero/available-places', methods=['GET'])
@admin_required
def get_available_places():
    """获取可用于 Hero 的 Places"""
    try:
        # 只返回有图片的地点
        places = Place.query.filter(Place.photo_reference.isnot(None)).limit(100).all()
        return jsonify({
            'status': 'success',
            'places': [{
                'id': place.id,
                'name': place.name,
                'address': place.address,
                'photoUrl': place.photo_reference,
                'rating': place.rating
            } for place in places]
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500