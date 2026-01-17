# routes/main.py
from flask import Blueprint, jsonify

main_bp = Blueprint('main', __name__)

# Root route '/' is now handled by SPA fallback in main_app.py
# This blueprint only handles API-specific routes

@main_bp.route('/api/health')
def health_check():
    """
    Health check endpoint for monitoring
    GET /api/health
    """
    return jsonify({
        "status": "online",
        "message": "GogoTrip Backend API is running"
    })

