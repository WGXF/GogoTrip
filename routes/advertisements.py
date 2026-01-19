from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from models import db, User


advertisements_bp = Blueprint('advertisements', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 1. 获取广告列表 API
@advertisements_bp.route('/list', methods=['GET'])
@login_required
def get_advertisements():
    """获取所有广告（管理员用）"""
    from models import Advertisement
    
    # 检查权限
    if current_user.role not in ['admin', 'super_admin', 'Admin', 'super_admin', 'Administrator']:
        return jsonify({'message': 'Unauthorized'}), 403
    
    ads = Advertisement.query.order_by(Advertisement.created_at.desc()).all()
    return jsonify([ad.to_dict() for ad in ads])

# 2. 获取活跃广告 API (用户端)
@advertisements_bp.route('/active', methods=['GET'])
def get_active_advertisements():
    """获取所有活跃的广告（用户端）"""
    from models import Advertisement
    
    ads = Advertisement.query.filter_by(status='active').order_by(Advertisement.priority.asc()).all()
    return jsonify([ad.to_dict() for ad in ads])

# 3. 创建广告 API
@advertisements_bp.route('/create', methods=['POST'])
@login_required
def create_advertisement():
    """创建新广告"""
    from models import Advertisement
    
    # 检查权限
    if current_user.role not in ['admin', 'super_admin', 'Admin', 'super_admin', 'Administrator']:
        return jsonify({'message': 'Unauthorized'}), 403
    
    try:
        # 获取表单数据
        title = request.form.get('title')
        description = request.form.get('description')
        link = request.form.get('link')
        status = request.form.get('status', 'active')
        priority = request.form.get('priority', 1)

        # Localization fields
        title_zh = request.form.get('title_zh')
        description_zh = request.form.get('description_zh')
        title_ms = request.form.get('title_ms')
        description_ms = request.form.get('description_ms')

        try:
            priority = int(priority)
        except ValueError:
            priority = 1

        if priority < 1:
            priority = 1

        if not title or not link:
            return jsonify({'message': 'Title and link are required'}), 400

        image_url = None

        # 处理广告图片
        if 'image' in request.files:
            file = request.files['image']
            
            if file and allowed_file(file.filename):
                # 检查文件大小 (最大 5MB)
                file.seek(0, os.SEEK_END)
                if file.tell() > 5 * 1024 * 1024:
                    return jsonify({'message': 'File too large. Maximum size is 5MB'}), 400
                file.seek(0)

                filename = secure_filename(file.filename)
                timestamp = int(datetime.now().timestamp())
                unique_filename = f"ad_{timestamp}_{filename}"
                
                # 保存到 static/uploads/advertisements 文件夹
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'advertisements')
                os.makedirs(upload_folder, exist_ok=True)
                
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                
                image_url = f"/static/uploads/advertisements/{unique_filename}"

        # 创建新广告
        new_ad = Advertisement(
            title=title,
            description=description,
            # 🆕 Localization
            title_zh=title_zh,
            description_zh=description_zh,
            title_ms=title_ms,
            description_ms=description_ms,
            
            image_url=image_url,
            link=link,
            status=status,
            priority=int(priority),
            created_by=current_user.id
        )

        db.session.add(new_ad)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': 'Advertisement created successfully',
            'advertisement': new_ad.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error creating advertisement: {e}")
        return jsonify({'message': str(e)}), 500

# 4. 更新广告 API
@advertisements_bp.route('/<int:id>', methods=['PUT'])
@login_required
def update_advertisement(id):
    """更新广告信息"""
    from models import Advertisement
    
    # 检查权限
    if current_user.role not in ['Administrator', 'super_admin']:
        return jsonify({'message': 'Unauthorized'}), 403
    
    try:
        ad = Advertisement.query.get(id)
        if not ad:
            return jsonify({'message': 'Advertisement not found'}), 404

        # 更新文字字段
        ad.title = request.form.get('title', ad.title)
        ad.description = request.form.get('description', ad.description)
        
        # 🆕 Localization
        ad.title_zh = request.form.get('title_zh', ad.title_zh)
        ad.description_zh = request.form.get('description_zh', ad.description_zh)
        ad.title_ms = request.form.get('title_ms', ad.title_ms)
        ad.description_ms = request.form.get('description_ms', ad.description_ms)
        
        ad.link = request.form.get('link', ad.link)
        ad.status = request.form.get('status', ad.status)
        
        priority = request.form.get('priority')
        if priority is not None:
            try:
                priority = int(priority)
            except ValueError:
                priority = ad.priority

            if priority < 1:
                priority = 1

            ad.priority = priority
        # 更新图片（如果有上传新图片）
        if 'image' in request.files:
            file = request.files['image']
            
            if file and allowed_file(file.filename):
                # 检查文件大小
                file.seek(0, os.SEEK_END)
                if file.tell() > 5 * 1024 * 1024:
                    return jsonify({'message': 'File too large. Maximum size is 5MB'}), 400
                file.seek(0)

                filename = secure_filename(file.filename)
                timestamp = int(datetime.now().timestamp())
                unique_filename = f"ad_{timestamp}_{filename}"
                
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'advertisements')
                os.makedirs(upload_folder, exist_ok=True)
                
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                
                # 删除旧图片（可选）
                if ad.image_url:
                    try:
                        old_file_path = os.path.join(current_app.root_path, ad.image_url.lstrip('/'))
                        if os.path.exists(old_file_path):
                            os.remove(old_file_path)
                    except Exception as e:
                        print(f"Error deleting old image: {e}")
                
                ad.image_url = f"/static/uploads/advertisements/{unique_filename}"

        ad.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Advertisement updated successfully',
            'advertisement': ad.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error updating advertisement: {e}")
        return jsonify({'message': str(e)}), 500

# 5. 删除广告 API
@advertisements_bp.route('/<int:id>', methods=['DELETE'])
@login_required
def delete_advertisement(id):
    """删除广告"""
    from models import Advertisement
    
    # 检查权限
    if current_user.role not in ['Administrator', 'super_admin']:
        return jsonify({'message': 'Unauthorized'}), 403
    
    try:
        ad = Advertisement.query.get(id)
        if not ad:
            return jsonify({'message': 'Advertisement not found'}), 404
        
        # 删除关联的图片文件（可选）
        if ad.image_url:
            try:
                file_path = os.path.join(current_app.root_path, ad.image_url.lstrip('/'))
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error deleting image file: {e}")
        
        db.session.delete(ad)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Advertisement deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting advertisement: {e}")
        return jsonify({'message': str(e)}), 500

# 6. 记录广告点击 API
@advertisements_bp.route('/<int:id>/click', methods=['POST'])
def record_click(id):
    """记录广告点击"""
    from models import Advertisement
    
    try:
        ad = Advertisement.query.get(id)
        if not ad:
            return jsonify({'message': 'Advertisement not found'}), 404
        
        ad.clicks += 1
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Click recorded'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error recording click: {e}")
        return jsonify({'message': str(e)}), 500

# 7. 记录广告展示 API
@advertisements_bp.route('/<int:id>/view', methods=['POST'])
def record_view(id):
    """记录广告展示"""
    from models import Advertisement
    
    try:
        ad = Advertisement.query.get(id)
        if not ad:
            return jsonify({'message': 'Advertisement not found'}), 404
        
        ad.views += 1
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'View recorded'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error recording view: {e}")
        return jsonify({'message': str(e)}), 500