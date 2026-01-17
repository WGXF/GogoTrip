"""
Blog Routes - User Blog System with Social Features
Endpoints for blog CRUD, likes, comments, subscriptions, and reports
"""

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
import os

from models import db, Blog, BlogLike, BlogComment, BlogSubscription, BlogReport, User, Notification
from routes.realtime import notify_user

blogs_bp = Blueprint('blogs', __name__, url_prefix='/api/blogs')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@blogs_bp.route('/upload-image', methods=['POST'])
@login_required
def upload_image():
    """Generic image upload for blogs (cover images, content images)"""
    try:
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image file provided'}), 400
            
        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No selected file'}), 400
            
        if file and allowed_file(file.filename):
            # Size limit (5MB)
            file.seek(0, os.SEEK_END)
            if file.tell() > 5 * 1024 * 1024:
                return jsonify({'success': False, 'error': 'File too large (max 5MB)'}), 400
            file.seek(0)
            
            filename = secure_filename(file.filename)
            timestamp = int(datetime.now().timestamp())
            unique_filename = f"blog_img_{current_user.id}_{timestamp}_{filename}"
            
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs')
            os.makedirs(upload_folder, exist_ok=True)
            
            file_path = os.path.join(upload_folder, unique_filename)
            file.save(file_path)
            
            # Return relative URL
            url = f"/static/uploads/blogs/{unique_filename}"
            
            return jsonify({
                'success': True, 
                'url': url
            })
            
        return jsonify({'success': False, 'error': 'Invalid file type'}), 400
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 📝 Blog CRUD Operations
# =============================================================================

@blogs_bp.route('/feed', methods=['GET'])
def get_blog_feed():
    """
    Get published blogs for the public feed
    Supports pagination, filtering by category, and search
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        category = request.args.get('category')
        search = request.args.get('search')
        author_id = request.args.get('author_id', type=int)
        
        # Get current user ID for like status
        current_user_id = current_user.id if current_user.is_authenticated else None
        
        # Base query - only published blogs
        query = Blog.query.filter_by(status='published')
        
        # Apply filters
        if category and category != 'all':
            query = query.filter_by(category=category)
        
        if search:
            query = query.filter(
                db.or_(
                    Blog.title.ilike(f'%{search}%'),
                    Blog.content.ilike(f'%{search}%')
                )
            )
        
        if author_id:
            query = query.filter_by(author_id=author_id)
        
        # Order by published date (newest first)
        query = query.order_by(Blog.published_at.desc())
        
        # Paginate
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        blogs = [blog.to_preview_dict(current_user_id) for blog in pagination.items]
        
        return jsonify({
            'success': True,
            'blogs': blogs,
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            }
        })
        
    except Exception as e:
        print(f"Error getting blog feed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/<int:blog_id>', methods=['GET'])
def get_blog(blog_id):
    """Get a single blog with full details"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        # Only allow viewing published blogs or own drafts
        current_user_id = current_user.id if current_user.is_authenticated else None
        
        if blog.status != 'published':
            if not current_user.is_authenticated or blog.author_id != current_user.id:
                # Allow admins to view
                if not current_user.is_authenticated or current_user.role not in ['Admin', 'super_admin', 'Administrator']:
                    return jsonify({'success': False, 'error': 'Blog not found'}), 404
        
        # Increment view count
        blog.views += 1
        db.session.commit()
        
        return jsonify({
            'success': True,
            'blog': blog.to_dict(current_user_id)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/my', methods=['GET'])
@login_required
def get_my_blogs():
    """Get current user's blogs (all statuses)"""
    try:
        status = request.args.get('status')
        
        query = Blog.query.filter_by(author_id=current_user.id)
        
        if status and status != 'all':
            query = query.filter_by(status=status)
        
        query = query.order_by(Blog.created_at.desc())
        blogs = [blog.to_preview_dict(current_user.id) for blog in query.all()]
        
        return jsonify({
            'success': True,
            'blogs': blogs
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/create', methods=['POST'])
@login_required
def create_blog():
    """Create a new blog post"""
    try:
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            title = data.get('title')
            content = data.get('content')
            excerpt = data.get('excerpt')
            category = data.get('category', 'general')
            tags = data.get('tags', [])
            status = data.get('status', 'draft')
            cover_image = data.get('coverImage')
        else:
            title = request.form.get('title')
            content = request.form.get('content')
            excerpt = request.form.get('excerpt')
            category = request.form.get('category', 'general')
            tags = request.form.getlist('tags')
            status = request.form.get('status', 'draft')
            cover_image = None
            
            # Handle cover image upload
            if 'coverImage' in request.files:
                file = request.files['coverImage']
                if file and allowed_file(file.filename):
                    # Size limit (5MB)
                    file.seek(0, os.SEEK_END)
                    if file.tell() > 5 * 1024 * 1024:
                        return jsonify({'success': False, 'error': 'File too large (max 5MB)'}), 400
                    file.seek(0)
                    
                    filename = secure_filename(file.filename)
                    timestamp = int(datetime.now().timestamp())
                    unique_filename = f"blog_{current_user.id}_{timestamp}_{filename}"
                    
                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs')
                    os.makedirs(upload_folder, exist_ok=True)
                    
                    file_path = os.path.join(upload_folder, unique_filename)
                    file.save(file_path)
                    
                    cover_image = f"/static/uploads/blogs/{unique_filename}"
        
        if not title or not content:
            return jsonify({'success': False, 'error': 'Title and content are required'}), 400
        
        # Status validation - users can only create draft or pending
        if status not in ['draft', 'pending']:
            status = 'draft'
        
        new_blog = Blog(
            author_id=current_user.id,
            title=title,
            content=content,
            excerpt=excerpt,
            cover_image=cover_image,
            category=category,
            tags=tags if isinstance(tags, list) else [],
            status=status
        )
        
        db.session.add(new_blog)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog created successfully',
            'blog': new_blog.to_dict(current_user.id)
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating blog: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/<int:blog_id>', methods=['PUT'])
@login_required
def update_blog(blog_id):
    """Update a blog post (only author can update)"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        # Only author can update
        if blog.author_id != current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
            
            # Handle cover image upload
            if 'coverImage' in request.files:
                file = request.files['coverImage']
                if file and allowed_file(file.filename):
                    file.seek(0, os.SEEK_END)
                    if file.tell() > 5 * 1024 * 1024:
                        return jsonify({'success': False, 'error': 'File too large (max 5MB)'}), 400
                    file.seek(0)
                    
                    filename = secure_filename(file.filename)
                    timestamp = int(datetime.now().timestamp())
                    unique_filename = f"blog_{current_user.id}_{timestamp}_{filename}"
                    
                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'blogs')
                    os.makedirs(upload_folder, exist_ok=True)
                    
                    file_path = os.path.join(upload_folder, unique_filename)
                    file.save(file_path)
                    
                    data['coverImage'] = f"/static/uploads/blogs/{unique_filename}"
        
        # Update fields
        if 'title' in data:
            blog.title = data['title']
        if 'content' in data:
            blog.content = data['content']
        if 'excerpt' in data:
            blog.excerpt = data['excerpt']
        if 'coverImage' in data:
            blog.cover_image = data['coverImage']
        if 'category' in data:
            blog.category = data['category']
        if 'tags' in data:
            blog.tags = data['tags'] if isinstance(data['tags'], list) else []
        
        # Status change (users can only set to draft or pending)
        if 'status' in data:
            new_status = data['status']
            if new_status in ['draft', 'pending']:
                # If published, don't allow changing back to draft
                if blog.status != 'published':
                    blog.status = new_status
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog updated successfully',
            'blog': blog.to_dict(current_user.id)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/<int:blog_id>', methods=['DELETE'])
@login_required
def delete_blog(blog_id):
    """Delete a blog post (only author or admin can delete)"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        # Only author or admin can delete
        is_admin = current_user.role in ['Admin', 'super_admin', 'Administrator']
        if blog.author_id != current_user.id and not is_admin:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        db.session.delete(blog)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/<int:blog_id>/submit', methods=['POST'])
@login_required
def submit_blog_for_review(blog_id):
    """Submit a draft blog for admin review"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        if blog.author_id != current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        if blog.status != 'draft':
            return jsonify({'success': False, 'error': 'Only draft blogs can be submitted'}), 400
        
        blog.status = 'pending'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog submitted for review'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# ❤️ Like Operations
# =============================================================================

@blogs_bp.route('/<int:blog_id>/like', methods=['POST'])
@login_required
def toggle_like(blog_id):
    """Toggle like on a blog post"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        if blog.status != 'published':
            return jsonify({'success': False, 'error': 'Cannot like unpublished blog'}), 400
        
        existing_like = BlogLike.query.filter_by(
            blog_id=blog_id,
            user_id=current_user.id
        ).first()
        
        if existing_like:
            # Unlike
            db.session.delete(existing_like)
            db.session.commit()
            return jsonify({
                'success': True,
                'liked': False,
                'likesCount': blog.get_likes_count()
            })
        else:
            # Like
            new_like = BlogLike(blog_id=blog_id, user_id=current_user.id)
            db.session.add(new_like)
            db.session.commit()
            return jsonify({
                'success': True,
                'liked': True,
                'likesCount': blog.get_likes_count()
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 💬 Comment Operations
# =============================================================================

@blogs_bp.route('/<int:blog_id>/comments', methods=['GET'])
def get_comments(blog_id):
    """Get comments for a blog post"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        # Get top-level comments (no parent)
        comments = BlogComment.query.filter_by(
            blog_id=blog_id,
            parent_id=None,
            status='visible'
        ).order_by(BlogComment.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'comments': [c.to_dict() for c in comments]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/<int:blog_id>/comments', methods=['POST'])
@login_required
def create_comment(blog_id):
    """Create a comment on a blog post"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        if blog.status != 'published':
            return jsonify({'success': False, 'error': 'Cannot comment on unpublished blog'}), 400
        
        data = request.get_json()
        content = data.get('content')
        parent_id = data.get('parentId')
        
        if not content:
            return jsonify({'success': False, 'error': 'Content is required'}), 400
        
        # Validate parent comment if provided
        if parent_id:
            parent = BlogComment.query.get(parent_id)
            if not parent or parent.blog_id != blog_id:
                return jsonify({'success': False, 'error': 'Invalid parent comment'}), 400
        
        new_comment = BlogComment(
            blog_id=blog_id,
            user_id=current_user.id,
            content=content,
            parent_id=parent_id
        )
        
        db.session.add(new_comment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Comment added',
            'comment': new_comment.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Delete a comment (only author or admin)"""
    try:
        comment = BlogComment.query.get_or_404(comment_id)
        
        is_admin = current_user.role in ['Admin', 'super_admin', 'Administrator']
        if comment.user_id != current_user.id and not is_admin:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Soft delete
        comment.status = 'deleted'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Comment deleted'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 👥 Subscription (Follow) Operations
# =============================================================================

@blogs_bp.route('/authors/<int:author_id>/subscribe', methods=['POST'])
@login_required
def toggle_subscription(author_id):
    """Toggle subscription to a blog author"""
    try:
        if author_id == current_user.id:
            return jsonify({'success': False, 'error': 'Cannot subscribe to yourself'}), 400
        
        author = User.query.get_or_404(author_id)
        
        existing_sub = BlogSubscription.query.filter_by(
            subscriber_id=current_user.id,
            author_id=author_id
        ).first()
        
        if existing_sub:
            # Unsubscribe
            db.session.delete(existing_sub)
            db.session.commit()
            return jsonify({
                'success': True,
                'subscribed': False,
                'message': f'Unsubscribed from {author.full_name}'
            })
        else:
            # Subscribe
            new_sub = BlogSubscription(
                subscriber_id=current_user.id,
                author_id=author_id
            )
            db.session.add(new_sub)
            db.session.commit()
            return jsonify({
                'success': True,
                'subscribed': True,
                'message': f'Subscribed to {author.full_name}'
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/authors/<int:author_id>/subscription-status', methods=['GET'])
@login_required
def check_subscription_status(author_id):
    """Check if current user is subscribed to an author"""
    try:
        existing_sub = BlogSubscription.query.filter_by(
            subscriber_id=current_user.id,
            author_id=author_id
        ).first()
        
        return jsonify({
            'success': True,
            'subscribed': existing_sub is not None
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/subscriptions', methods=['GET'])
@login_required
def get_my_subscriptions():
    """Get list of authors the current user is subscribed to"""
    try:
        subscriptions = BlogSubscription.query.filter_by(
            subscriber_id=current_user.id
        ).order_by(BlogSubscription.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'subscriptions': [s.to_dict() for s in subscriptions]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/subscribed-feed', methods=['GET'])
@login_required
def get_subscribed_feed():
    """Get blogs from authors the user is subscribed to"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Get subscribed author IDs
        subscribed_ids = db.session.query(BlogSubscription.author_id).filter_by(
            subscriber_id=current_user.id
        ).subquery()
        
        # Get blogs from those authors
        query = Blog.query.filter(
            Blog.author_id.in_(subscribed_ids),
            Blog.status == 'published'
        ).order_by(Blog.published_at.desc())
        
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        blogs = [blog.to_preview_dict(current_user.id) for blog in pagination.items]
        
        return jsonify({
            'success': True,
            'blogs': blogs,
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 🚨 Report Operations
# =============================================================================

@blogs_bp.route('/<int:blog_id>/report', methods=['POST'])
@login_required
def report_blog(blog_id):
    """Report a blog post"""
    try:
        blog = Blog.query.get_or_404(blog_id)
        
        if blog.status != 'published':
            return jsonify({'success': False, 'error': 'Cannot report unpublished blog'}), 400
        
        if blog.author_id == current_user.id:
            return jsonify({'success': False, 'error': 'Cannot report your own blog'}), 400
        
        # Check for existing report
        existing_report = BlogReport.query.filter_by(
            blog_id=blog_id,
            reporter_id=current_user.id
        ).first()
        
        if existing_report:
            return jsonify({'success': False, 'error': 'You have already reported this blog'}), 400
        
        data = request.get_json()
        reason = data.get('reason')
        description = data.get('description')
        
        if not reason:
            return jsonify({'success': False, 'error': 'Reason is required'}), 400
        
        valid_reasons = ['spam', 'inappropriate', 'harassment', 'misinformation', 'other']
        if reason not in valid_reasons:
            return jsonify({'success': False, 'error': 'Invalid reason'}), 400
        
        new_report = BlogReport(
            blog_id=blog_id,
            reporter_id=current_user.id,
            reason=reason,
            description=description
        )
        
        db.session.add(new_report)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Report submitted. Our team will review it shortly.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 👨‍💼 Admin Operations
# =============================================================================

@blogs_bp.route('/admin/all', methods=['GET'])
@login_required
def admin_get_all_blogs():
    """Admin: Get all blogs (all statuses)"""
    try:
        if current_user.role not in ['Admin', 'super_admin', 'Administrator']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        search = request.args.get('search')
        
        query = Blog.query
        
        if status and status != 'all':
            query = query.filter_by(status=status)
        
        if search:
            query = query.filter(
                db.or_(
                    Blog.title.ilike(f'%{search}%'),
                    Blog.content.ilike(f'%{search}%')
                )
            )
        
        query = query.order_by(Blog.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        blogs = [blog.to_dict() for blog in pagination.items]
        
        # Get stats
        stats = {
            'total': Blog.query.count(),
            'published': Blog.query.filter_by(status='published').count(),
            'pending': Blog.query.filter_by(status='pending').count(),
            'draft': Blog.query.filter_by(status='draft').count(),
            'rejected': Blog.query.filter_by(status='rejected').count()
        }
        
        return jsonify({
            'success': True,
            'blogs': blogs,
            'stats': stats,
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/admin/<int:blog_id>/approve', methods=['POST'])
@login_required
def admin_approve_blog(blog_id):
    """Admin: Approve a pending blog"""
    try:
        if current_user.role not in ['Admin', 'super_admin', 'Administrator']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        blog = Blog.query.get_or_404(blog_id)
        
        if blog.status not in ['pending', 'draft']:
            return jsonify({'success': False, 'error': 'Only pending or draft blogs can be approved'}), 400
        
        blog.status = 'published'
        blog.published_at = datetime.utcnow()
        blog.rejection_reason = None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog approved and published'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/admin/<int:blog_id>/reject', methods=['POST'])
@login_required
def admin_reject_blog(blog_id):
    """Admin: Reject a pending blog"""
    try:
        if current_user.role not in ['Admin', 'super_admin', 'Administrator']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        blog = Blog.query.get_or_404(blog_id)
        
        data = request.get_json()
        reason = data.get('reason', 'Content does not meet community guidelines')
        
        blog.status = 'rejected'
        blog.rejection_reason = reason
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog rejected'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/admin/<int:blog_id>/hide', methods=['POST'])
@login_required
def admin_hide_blog(blog_id):
    """Admin: Hide a published blog"""
    try:
        if current_user.role not in ['Admin', 'super_admin', 'Administrator']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        blog = Blog.query.get_or_404(blog_id)
        
        data = request.get_json()
        reason = data.get('reason', 'Hidden by admin')
        
        blog.status = 'hidden'
        blog.rejection_reason = reason
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Blog hidden'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 🚨 Admin Report Management
# =============================================================================

@blogs_bp.route('/admin/reports', methods=['GET'])
@login_required
def admin_get_reports():
    """Admin: Get all blog reports"""
    try:
        if current_user.role not in ['Admin', 'super_admin', 'Administrator']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = BlogReport.query
        
        if status and status != 'all':
            query = query.filter_by(status=status)
        
        query = query.order_by(BlogReport.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        reports = [report.to_dict() for report in pagination.items]
        
        # Get stats
        stats = {
            'total': BlogReport.query.count(),
            'pending': BlogReport.query.filter_by(status='pending').count(),
            'reviewed': BlogReport.query.filter_by(status='reviewed').count(),
            'resolved': BlogReport.query.filter_by(status='resolved').count(),
            'dismissed': BlogReport.query.filter_by(status='dismissed').count()
        }
        
        return jsonify({
            'success': True,
            'reports': reports,
            'stats': stats,
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@blogs_bp.route('/admin/reports/<int:report_id>/review', methods=['POST'])
@login_required
def admin_review_report(report_id):
    """Admin: Review a report and take action"""
    try:
        if current_user.role not in ['Admin', 'super_admin', 'Administrator']:
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        report = BlogReport.query.get_or_404(report_id)
        
        data = request.get_json()
        action = data.get('action')  # none / warning / hidden / deleted
        admin_notes = data.get('adminNotes')
        new_status = data.get('status', 'reviewed')  # reviewed / resolved / dismissed
        
        valid_actions = ['none', 'warning', 'hidden', 'deleted']
        if action and action not in valid_actions:
            return jsonify({'success': False, 'error': 'Invalid action'}), 400
        
        report.status = new_status
        report.reviewed_by = current_user.id
        report.reviewed_at = datetime.utcnow()
        report.admin_notes = admin_notes
        report.action_taken = action
        
        # Apply action to blog & Notify User
        notif_data = None
        
        if action == 'warning':
            notif_data = {
                'title': 'Content Warning',
                'text': f"Warning for '{report.blog.title}': {admin_notes or 'Guideline violation'}",
                'type': 'warning',
                'icon': 'alert-triangle'
            }
        elif action == 'hidden' and report.blog:
            report.blog.status = 'hidden'
            report.blog.rejection_reason = f'Hidden due to report: {report.reason}'
            notif_data = {
                'title': 'Content Hidden',
                'text': f"Your story '{report.blog.title}' has been hidden. Reason: {admin_notes or report.reason}",
                'type': 'alert',
                'icon': 'eye-off'
            }
        elif action == 'deleted' and report.blog:
            notif_data = {
                'title': 'Content Removed',
                'text': f"Your story '{report.blog.title}' was removed. Reason: {admin_notes or report.reason}",
                'type': 'alert',
                'icon': 'trash-2'
            }
            db.session.delete(report.blog)
            
        # Create Notification if applicable
        if notif_data and report.blog and report.blog.author_id:
            notification = Notification(
                user_id=report.blog.author_id,
                title=notif_data['title'],
                text=notif_data['text'],
                type=notif_data['type'],
                icon=notif_data['icon'],
                sent_by=current_user.id
            )
            db.session.add(notification)
            # Flush to get ID for socket
            db.session.flush()
            
            # Real-time notification (if socket enabled)
            try:
                # frontend expects specific event or polling? 
                # Currently frontend polls, but we can try generic event
                notify_user(report.blog.author_id, 'new_notification', notification.to_dict())
            except Exception as e:
                print(f"Socket error: {e}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Report {new_status}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# 📊 Statistics & Categories
# =============================================================================

@blogs_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get blog categories with counts"""
    try:
        categories = db.session.query(
            Blog.category,
            db.func.count(Blog.id).label('count')
        ).filter_by(status='published').group_by(Blog.category).all()
        
        return jsonify({
            'success': True,
            'categories': [
                {'name': cat, 'count': count}
                for cat, count in categories
            ]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
