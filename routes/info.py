from flask import Blueprint, request, jsonify, make_response
from models import db, Article
from sqlalchemy.sql import func

info_bp = Blueprint('info', __name__)

# 1. 获取文章详情并增加阅读量
@info_bp.route('/articles/<int:id>', methods=['GET'])
def get_article_detail(id):
    try:
        article = Article.query \
            .filter(
                Article.id == id,
                func.lower(Article.status) == 'published'
            ) \
            .first()

        if not article:
            return jsonify({"message": "Article not found"}), 404

        # 核心修复：使用 SQLAlchemy 表达式进行原子增加，防止并发问题或会话未感知
        article.views = Article.views + 1
        db.session.commit()
        
        # 重新获取最新数据以返回（因为用了表达式更新）
        db.session.refresh(article)

        # 构建响应
        response = make_response(jsonify(article.to_dict()))
        
        # 核心修复：添加防缓存 Header，强制浏览器每次都向服务器请求
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

        return response

    except Exception as e:
        print(f"Error viewing article: {e}")
        db.session.rollback()
        return jsonify({"message": "Server error"}), 500

# 2. 创建文章 (保留你的原有代码)
@info_bp.route('/articles', methods=['POST'])
def create_article():
    data = request.json
    new_article = Article(
        title=data.get('title'),
        category=data.get('category'),
        content=data.get('content'),
        status=data.get('status', 'draft'),
        cover_image=data.get('cover_image')
    )
    db.session.add(new_article)
    db.session.commit()
    return jsonify({"status": "success", "article": new_article.to_dict()})