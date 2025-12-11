from flask import Blueprint, request, jsonify
from models import db, Article

info_bp = Blueprint('info', __name__)

# 1. 获取文章列表 (公开接口，给 Info Website 用)
@info_bp.route('/articles/public', methods=['GET'])
def get_public_articles():
    # 只查已发布的
    articles = Article.query.filter_by(status='published').order_by(Article.created_at.desc()).all()
    return jsonify([a.to_dict() for a in articles])

# 2. 获取单篇文章详情 (公开接口)
@info_bp.route('/articles/<int:id>', methods=['GET'])
def get_article_detail(id):
    article = Article.query.get_or_404(id)
    # 增加阅读量
    article.views += 1
    db.session.commit()
    return jsonify(article.to_dict())

# 3. 创建文章 (仅限 Admin，这里简化了鉴权，建议加上 @login_required)
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