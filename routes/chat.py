# routes/chat.py
import json
from flask import Blueprint, request, session, jsonify
from flask_login import current_user, login_required
from ai_agent import get_ai_chat_response, edit_activities_with_ai, get_fast_food_recommendations
from models import db, User, Place
from chat_models import AIConversation, AIMessage, ConversationRepository

chat_bp = Blueprint('chat', __name__)


# =============================================================================
# Helper Functions
# =============================================================================

def enrich_food_with_place_ids(recommendations: list) -> list:
    """
    Enrich food recommendations with place_id from our database.
    Looks up each restaurant by name (fuzzy match) and adds place_id if found.
    
    This ensures images are fetched using place_id (which works) instead of name (which doesn't).
    """
    if not recommendations:
        return recommendations
    
    enriched = []
    for rec in recommendations:
        name = rec.get('name', '')
        if not name:
            enriched.append(rec)
            continue
        
        # Try to find place in database by name (case-insensitive fuzzy match)
        place = Place.query.filter(
            Place.name.ilike(f'%{name}%')
        ).first()
        
        if place:
            # Found in database - add place_id and other useful fields
            rec['place_id'] = place.id
            rec['google_place_id'] = place.google_place_id
            if place.photo_reference:
                rec['photo_reference'] = place.photo_reference
            if place.address and not rec.get('address'):
                rec['address'] = place.address
            if place.rating and not rec.get('rating'):
                rec['rating'] = place.rating
            print(f"--- [Food Enrichment] Found '{name}' -> place_id={place.id} ---")
        else:
            print(f"--- [Food Enrichment] '{name}' not found in database ---")
        
        enriched.append(rec)
    
    return enriched


# =============================================================================
# Conversation Management APIs
# =============================================================================

@chat_bp.route('/api/conversations', methods=['GET'])
@login_required
def list_conversations():
    """
    List all conversations for current user.
    
    GET /api/conversations
    Query params:
        - include_archived: bool (default: false)
        - limit: int (default: 50, max: 100)
    
    Returns:
        { conversations: [...], isPremium: bool }
    """
    # Premium check
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED',
            'message': 'Upgrade to Premium to access chat history'
        }), 403
    
    try:
        include_archived = request.args.get('include_archived', 'false').lower() == 'true'
        limit = min(request.args.get('limit', 50, type=int), 100)
        
        conversations = ConversationRepository.get_user_conversations(
            user_id=current_user.id,
            include_archived=include_archived,
            limit=limit
        )
        
        return jsonify({
            'conversations': [conv.to_list_item() for conv in conversations],
            'isPremium': True,
            'count': len(conversations)
        })
        
    except Exception as e:
        print(f"--- [Chat Error] GET /api/conversations: {e} ---")
        return jsonify({'error': 'Failed to fetch conversations'}), 500


@chat_bp.route('/api/conversations', methods=['POST'])
@login_required
def create_conversation():
    """
    Create a new conversation.
    
    POST /api/conversations
    Body: { title?: string }
    
    Returns:
        { conversation: {...} }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        data = request.json or {}
        title = data.get('title')
        
        conversation = ConversationRepository.create_conversation(
            user_id=current_user.id,
            title=title
        )
        
        return jsonify({
            'conversation': conversation.to_dict()
        }), 201
        
    except Exception as e:
        print(f"--- [Chat Error] POST /api/conversations: {e} ---")
        return jsonify({'error': 'Failed to create conversation'}), 500


@chat_bp.route('/api/conversations/<int:conversation_id>', methods=['GET'])
@login_required
def get_conversation(conversation_id):
    """
    Get a specific conversation with messages.
    
    GET /api/conversations/:id
    Query params:
        - include_messages: bool (default: true)
    
    Returns:
        { conversation: {..., messages: [...]} }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        conversation = ConversationRepository.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404
        
        include_messages = request.args.get('include_messages', 'true').lower() == 'true'
        
        return jsonify({
            'conversation': conversation.to_dict(include_messages=include_messages)
        })
        
    except Exception as e:
        print(f"--- [Chat Error] GET /api/conversations/{conversation_id}: {e} ---")
        return jsonify({'error': 'Failed to fetch conversation'}), 500


@chat_bp.route('/api/conversations/<int:conversation_id>', methods=['PATCH'])
@login_required
def update_conversation(conversation_id):
    """
    Update conversation (rename, archive).
    
    PATCH /api/conversations/:id
    Body: { title?: string, isArchived?: bool }
    
    Returns:
        { conversation: {...} }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        data = request.json or {}
        
        conversation = ConversationRepository.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Update fields
        if 'title' in data:
            conversation.title = data['title']
        if 'isArchived' in data:
            conversation.is_archived = data['isArchived']
        
        db.session.commit()
        
        return jsonify({
            'conversation': conversation.to_dict()
        })
        
    except Exception as e:
        print(f"--- [Chat Error] PATCH /api/conversations/{conversation_id}: {e} ---")
        return jsonify({'error': 'Failed to update conversation'}), 500


@chat_bp.route('/api/conversations/<int:conversation_id>', methods=['DELETE'])
@login_required
def delete_conversation(conversation_id):
    """
    Delete a conversation and all its messages.
    
    DELETE /api/conversations/:id
    
    Returns:
        { success: true }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        success = ConversationRepository.delete_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not success:
            return jsonify({'error': 'Conversation not found'}), 404
        
        return jsonify({
            'success': True,
            'message': 'Conversation deleted'
        })
        
    except Exception as e:
        print(f"--- [Chat Error] DELETE /api/conversations/{conversation_id}: {e} ---")
        return jsonify({'error': 'Failed to delete conversation'}), 500


@chat_bp.route('/api/conversations/latest', methods=['GET'])
@login_required
def get_latest_conversation():
    """
    Get the most recent conversation for auto-loading.
    
    GET /api/conversations/latest
    
    Returns:
        { conversation: {..., messages: [...]} } or { conversation: null }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        conversation = ConversationRepository.get_latest_conversation(
            user_id=current_user.id
        )
        
        if not conversation:
            return jsonify({
                'conversation': None,
                'isPremium': True
            })
        
        return jsonify({
            'conversation': conversation.to_dict(include_messages=True),
            'isPremium': True
        })
        
    except Exception as e:
        print(f"--- [Chat Error] GET /api/conversations/latest: {e} ---")
        return jsonify({'error': 'Failed to fetch latest conversation'}), 500


@chat_bp.route('/api/conversations/clear', methods=['DELETE'])
@login_required
def clear_all_conversations():
    """
    Delete all conversations for current user.
    
    DELETE /api/conversations/clear
    
    Returns:
        { success: true, deletedCount: N }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        count = ConversationRepository.clear_user_conversations(
            user_id=current_user.id
        )
        
        return jsonify({
            'success': True,
            'deletedCount': count,
            'message': f'Deleted {count} conversations'
        })
        
    except Exception as e:
        print(f"--- [Chat Error] DELETE /api/conversations/clear: {e} ---")
        return jsonify({'error': 'Failed to clear conversations'}), 500


# =============================================================================
# Conversation Sharing APIs
# =============================================================================

@chat_bp.route('/api/conversations/<int:conversation_id>/share', methods=['POST'])
@login_required
def share_conversation(conversation_id):
    """
    Enable sharing for a conversation and generate share link.
    
    POST /api/conversations/:id/share
    
    Returns:
        { 
            success: true, 
            shareToken: "abc123...", 
            shareUrl: "https://gogotrip.com/shared/abc123..."
        }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        share_token = ConversationRepository.generate_share_token(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not share_token:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Build share URL (frontend route)
        share_url = f"/shared/{share_token}"
        
        return jsonify({
            'success': True,
            'shareToken': share_token,
            'shareUrl': share_url
        })
        
    except Exception as e:
        print(f"--- [Chat Error] POST /api/conversations/{conversation_id}/share: {e} ---")
        return jsonify({'error': 'Failed to share conversation'}), 500


@chat_bp.route('/api/conversations/<int:conversation_id>/share', methods=['DELETE'])
@login_required
def unshare_conversation(conversation_id):
    """
    Disable sharing for a conversation (revoke share link).
    
    DELETE /api/conversations/:id/share
    
    Returns:
        { success: true }
    """
    if not current_user.is_premium_active:
        return jsonify({
            'error': 'Premium subscription required',
            'errorCode': 'PREMIUM_REQUIRED'
        }), 403
    
    try:
        success = ConversationRepository.disable_sharing(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not success:
            return jsonify({'error': 'Conversation not found'}), 404
        
        return jsonify({
            'success': True,
            'message': 'Sharing disabled'
        })
        
    except Exception as e:
        print(f"--- [Chat Error] DELETE /api/conversations/{conversation_id}/share: {e} ---")
        return jsonify({'error': 'Failed to disable sharing'}), 500


@chat_bp.route('/api/shared/<share_token>', methods=['GET'])
def get_shared_conversation(share_token):
    """
    Get a shared conversation by token (public access, no auth required).
    
    GET /api/shared/:token
    
    Returns:
        { conversation: {..., messages: [...]} }
    """
    try:
        conversation = ConversationRepository.get_shared_conversation(share_token)
        
        if not conversation:
            return jsonify({'error': 'Conversation not found or not shared'}), 404
        
        return jsonify({
            'conversation': conversation.to_shared_dict()
        })
        
    except Exception as e:
        print(f"--- [Chat Error] GET /api/shared/{share_token}: {e} ---")
        return jsonify({'error': 'Failed to load shared conversation'}), 500


# =============================================================================
# Chat Message API (Updated for Conversation-Centric Design)
# =============================================================================

@chat_bp.route('/chat_message', methods=['POST'])
def chat_message():
    """
    Send a chat message and get AI response.
    
    POST /chat_message
    Body: {
        message: string,
        conversationId?: int,  // Optional - creates new if not provided
        history?: array,       // For context (used by AI)
        coordinates?: object
    }
    
    For Premium users:
        - Creates conversation if conversationId not provided
        - Saves both user message and AI response
        - Returns conversationId for frontend state
    
    For Free users:
        - No persistence
        - Works as before
    """
    # Get credentials for AI function
    user_credentials = session.get('credentials')
    
    # Check auth status
    # NEW: Save history for ALL authenticated users (not just Premium)
    # Viewing history is still Premium-only (checked in GET endpoints)
    user = None
    is_premium = False
    
    if current_user.is_authenticated:
        user = current_user
        is_premium = user.is_premium_active

    try:
        data = request.json
        user_message = data.get('message', '').strip()
        conversation_id = data.get('conversationId')
        history = data.get('history', [])
        coordinates = data.get('coordinates')
        user_ip = request.remote_addr
        
        # 🆕 Language preference for AI response (i18n support)
        # Priority: request param > user profile > 'en' (default)
        user_language = data.get('language')
        if not user_language and user and hasattr(user, 'preferred_language'):
            user_language = user.preferred_language
        if not user_language:
            user_language = 'en'

        if not user_message:
            return jsonify({'error': '消息内容为空'}), 400

        # Save history for ALL authenticated users (Premium viewing only)
        if user:
            try:
                # Get or create conversation
                if conversation_id:
                    conversation = ConversationRepository.get_conversation(
                        conversation_id=conversation_id,
                        user_id=user.id
                    )
                    if not conversation:
                        # Invalid conversation ID, create new
                        conversation = ConversationRepository.create_conversation(user_id=user.id)
                else:
                    # Create new conversation
                    conversation = ConversationRepository.create_conversation(user_id=user.id)
                
                conversation_id = conversation.id
                
                # Save user message
                ConversationRepository.add_message(
                    conversation_id=conversation_id,
                    role='user',
                    content=user_message
                )
                
            except Exception as save_error:
                print(f"--- [Chat] Failed to save user message: {save_error} ---")
                # Continue anyway - don't fail the request

        # Build history for AI
        history.append({'role': 'user', 'parts': [user_message]})

        # Call AI (with language preference for i18n)
        ai_response_text = get_ai_chat_response(
            history,
            user_credentials,
            coordinates=coordinates,
            user_ip=user_ip,
            language=user_language  # 🆕 Pass user's preferred language
        )

        history.append({'role': 'model', 'parts': [ai_response_text]})

        # Save AI response for ALL authenticated users
        if user and conversation_id:
            try:
                # Extract suggestions/plans JSON if present
                suggestions_json = None
                
                # Handle POPUP_DATA:: format (place recommendations)
                if ai_response_text.startswith('POPUP_DATA::'):
                    json_string = ai_response_text[len('POPUP_DATA::'):]
                    try:
                        json.loads(json_string)  # Validate
                        suggestions_json = json_string
                    except json.JSONDecodeError:
                        pass
                
                # Handle DAILY_PLAN:: format (itineraries)
                elif ai_response_text.startswith('DAILY_PLAN::'):
                    json_string = ai_response_text[len('DAILY_PLAN::'):]
                    try:
                        json.loads(json_string)  # Validate
                        suggestions_json = json_string
                    except json.JSONDecodeError:
                        pass
                
                # Save AI response
                ConversationRepository.add_message(
                    conversation_id=conversation_id,
                    role='ai',
                    content=ai_response_text,
                    suggestions_json=suggestions_json
                )
                
                print(f"--- [Chat] Saved messages for conversation {conversation_id} (user_id={user.id}) ---")
                
            except Exception as save_error:
                print(f"--- [Chat] Failed to save AI response: {save_error} ---")

        # Build response
        response_data = {
            'reply': ai_response_text,
            'history': history
        }
        
        # Include conversation ID for authenticated users (viewing requires Premium)
        if user and conversation_id:
            response_data['conversationId'] = conversation_id
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"--- [Chat Error] /chat_message: {e} ---")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# AI Edit Activities Endpoint
# =============================================================================

@chat_bp.route('/api/ai/edit-activities', methods=['POST'])
def edit_activities():
    """
    AI-assisted batch editing of itinerary activities.
    
    POST /api/ai/edit-activities
    Body: {
        activities: [{ day_index, activity_index, activity }],
        instructions: string,
        plan_context?: { title, destination, preferences }
    }
    
    Returns:
        { success: true, updated_activities: [...] }
    """
    try:
        data = request.json
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        activities = data.get('activities', [])
        instructions = data.get('instructions', '').strip()
        plan_context = data.get('plan_context')
        
        if not activities:
            return jsonify({'success': False, 'error': 'No activities provided'}), 400
        
        if not instructions:
            return jsonify({'success': False, 'error': 'No instructions provided'}), 400
        
        print(f"--- [AI Edit] Processing {len(activities)} activities ---")
        print(f"--- [AI Edit] Instructions: {instructions[:100]}... ---")
        
        # Call AI edit function
        result = edit_activities_with_ai(
            activities=activities,
            instructions=instructions,
            plan_context=plan_context
        )
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'updated_activities': result.get('updated_activities', [])
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 500
            
    except Exception as e:
        print(f"--- [AI Edit Error] /api/ai/edit-activities: {e} ---")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# Food Recommendations API (Food Wizard)
# =============================================================================

@chat_bp.route('/api/food/recommendations', methods=['POST'])
def get_food_recommendations():
    """
    Get fast food recommendations based on user preferences.
    
    POST /api/food/recommendations
    Body: {
        preferences: {
            cuisine: string[],
            mood: string,
            budget: 'low' | 'medium' | 'high' | 'luxury',
            dietary: string[],
            mealType: string,
            distance: string
        },
        location?: string,
        conversationId?: int  // Optional - to save in existing conversation
    }
    
    Returns:
        {
            success: true,
            recommendations: [...],
            preferences_applied: {...},
            conversationId: int  // For authenticated users
        }
        
    History Saving:
    - Food recommendations are saved for ALL authenticated users
    - Uses FOOD_DATA:: prefix for parsing when loading history
    - Viewing history is Premium-only (checked in GET endpoints)
    """
    try:
        data = request.json
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        preferences = data.get('preferences', {})
        location = data.get('location')
        conversation_id = data.get('conversationId')
        
        # Get coordinates from request if available
        coordinates = data.get('coordinates')
        if coordinates and coordinates.get('latitude'):
            location = f"{coordinates.get('latitude')},{coordinates.get('longitude')}"
        
        print(f"--- [Food Wizard] Processing request ---")
        print(f"--- [Food Wizard] Preferences: {preferences} ---")
        print(f"--- [Food Wizard] Location: {location} ---")
        
        # Call the fast food recommendations function
        result = get_fast_food_recommendations(
            preferences=preferences,
            location=location
        )
        
        if result.get('success'):
            recommendations = result.get('recommendations', [])
            preferences_applied = result.get('preferences_applied', {})
            
            # Enrich recommendations with place_id from database
            # This ensures images load properly via /proxy_image?place_id=X
            recommendations = enrich_food_with_place_ids(recommendations)
            
            # Save to history for ALL authenticated users
            if current_user.is_authenticated:
                try:
                    user = current_user
                    
                    # Get or create conversation
                    if conversation_id:
                        conversation = ConversationRepository.get_conversation(
                            conversation_id=conversation_id,
                            user_id=user.id
                        )
                        if not conversation:
                            conversation = ConversationRepository.create_conversation(user_id=user.id)
                    else:
                        conversation = ConversationRepository.create_conversation(user_id=user.id)
                    
                    conversation_id = conversation.id
                    
                    # Build user message (what they searched for)
                    meal_type = preferences.get('mealType', 'food')
                    mood = preferences.get('mood', '')
                    budget = preferences.get('budget', '')
                    user_msg = f"🍽️ Food search: {meal_type}"
                    if mood:
                        user_msg += f" ({mood})"
                    if budget:
                        user_msg += f", Budget: {budget}"
                    
                    # Save user message
                    ConversationRepository.add_message(
                        conversation_id=conversation_id,
                        role='user',
                        content=user_msg
                    )
                    
                    # Build AI response with FOOD_DATA:: prefix for parsing
                    food_data = {
                        'type': 'food_recommendations',
                        'recommendations': recommendations,
                        'preferences_applied': preferences_applied
                    }
                    ai_response = f"FOOD_DATA::{json.dumps(food_data, ensure_ascii=False)}"
                    
                    # Save AI response
                    ConversationRepository.add_message(
                        conversation_id=conversation_id,
                        role='ai',
                        content=ai_response,
                        suggestions_json=json.dumps(recommendations, ensure_ascii=False)
                    )
                    
                    print(f"--- [Food Wizard] Saved to history, conversation_id={conversation_id} ---")
                    
                except Exception as save_error:
                    print(f"--- [Food Wizard] Failed to save history: {save_error} ---")
                    # Don't fail the request, just log
            
            response_data = {
                'success': True,
                'recommendations': recommendations,
                'preferences_applied': preferences_applied
            }
            
            # Include conversation ID for authenticated users
            if current_user.is_authenticated and conversation_id:
                response_data['conversationId'] = conversation_id
            
            return jsonify(response_data)
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to get recommendations')
            }), 500
            
    except Exception as e:
        print(f"--- [Food Wizard Error] /api/food/recommendations: {e} ---")
        return jsonify({'success': False, 'error': str(e)}), 500
