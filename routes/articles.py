from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.sql import func
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from models import db, Article  # 确保导入了 Article 模型

articles_bp = Blueprint('articles', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 1. 获取文章列表 API
@articles_bp.route('/list', methods=['GET'])
def get_articles():
    # 获取所有文章，按时间倒序排列
    articles = Article.query.order_by(Article.created_at.desc()).all()
    return jsonify([article.to_dict() for article in articles])

# 2. 创建文章 (带图片上传) API
@articles_bp.route('/create', methods=['POST'])
@login_required
def create_article():
    try:
        # A. 获取文字数据 (使用 request.form)
        title = request.form.get('title')
        category = request.form.get('category')
        content = request.form.get('content')
        status = request.form.get('status', 'draft')

        if not title:
            return jsonify({'message': 'Title is required'}), 400

        image_url = None # 默认为空

        # B. 处理封面图片 (和你的头像上传逻辑几乎一样)
        if 'coverImage' in request.files:
            file = request.files['coverImage']
            
            if file and allowed_file(file.filename):
                # 大小限制 (例如 2MB)
                file.seek(0, os.SEEK_END)
                if file.tell() > 2 * 1024 * 1024: 
                    return jsonify({'message': 'File too large'}), 400
                file.seek(0)

                filename = secure_filename(file.filename)
                timestamp = int(datetime.now().timestamp())
                # 这里的命名加了 article 前缀
                unique_filename = f"article_{timestamp}_{filename}"
                
                # 存到 static/uploads/articles 文件夹 (记得新建这个文件夹)
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'articles')
                os.makedirs(upload_folder, exist_ok=True)
                
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                
                # 保存到数据库的路径
                image_url = f"/static/uploads/articles/{unique_filename}"

        # C. 存入数据库
        new_article = Article(
            author_id=current_user.id,
            title=title,
            category=category,
            content=content,
            cover_image=image_url, # 存路径
            status=status
        )

        db.session.add(new_article)
        db.session.commit()

        return jsonify({
            'status': 'success', 
            'message': 'Article created successfully',
            'article': new_article.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 500
    
@articles_bp.route('/public', methods=['GET'])
def get_public_articles():
    try:
        # 只查询 status 为 'Published' 的文章，并按时间倒序排列
        articles = Article.query \
        .filter(func.lower(Article.status) == 'published') \
        .order_by(Article.created_at.desc()) \
        .all()
        return jsonify([article.to_dict() for article in articles])
    except Exception as e:
        print(f"Error fetching public articles: {e}")
        return jsonify([]), 500
    
@articles_bp.route('/<int:id>', methods=['DELETE'])
@login_required
def delete_article(id):
    try:
        article = Article.query.get(id)
        if not article:
            return jsonify({'message': 'Article not found'}), 404
            
        # 可选：如果你想删除对应的图片文件，可以在这里写 os.remove 逻辑
        
        db.session.delete(article)
        db.session.commit()
        return jsonify({'message': 'Article deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 500

# 4. 更新文章 API
@articles_bp.route('/<int:id>', methods=['PUT'])
@login_required
def update_article(id):
    try:
        article = Article.query.get(id)
        if not article:
            return jsonify({'message': 'Article not found'}), 404

        # 更新文字字段
        article.title = request.form.get('title')
        article.category = request.form.get('category')
        article.content = request.form.get('content')
        article.status = request.form.get('status')

        # 更新图片 (如果有上传新图片)
        if 'coverImage' in request.files:
            file = request.files['coverImage']
            # 这里复用你之前的 allowed_file 和保存逻辑
            if file and allowed_file(file.filename):
                # ... (这里省略重复的保存代码，逻辑和 create 一样) ...
                # 记得重新生成 unique_filename 并保存文件
                # 假设你已经把保存逻辑封装好了，或者直接复制粘贴 create 里的逻辑
                
                # 简单示例 (请确保引入了 secure_filename, os, datetime 等):
                filename = secure_filename(file.filename)
                timestamp = int(datetime.now().timestamp())
                unique_filename = f"article_{timestamp}_{filename}"
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'articles')
                os.makedirs(upload_folder, exist_ok=True)
                file.save(os.path.join(upload_folder, unique_filename))
                
                article.cover_image = f"/static/uploads/articles/{unique_filename}"

        db.session.commit()
        return jsonify({'message': 'Article updated successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 500