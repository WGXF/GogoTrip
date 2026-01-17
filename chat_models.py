# models/chat_models.py

from datetime import datetime
from models import db


class AIConversation(db.Model):
    """
    Represents a chat conversation/session.
    
    Similar to ChatGPT's conversation concept:
    - Each conversation has its own context
    - Can be renamed by user
    - Contains multiple messages
    - Can be shared via unique token
    """
    __tablename__ = 'ai_conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Conversation metadata
    title = db.Column(db.String(255), nullable=True)  # Auto-generated or user-set
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    # Sharing functionality
    share_token = db.Column(db.String(64), unique=True, nullable=True, index=True)  # Unique token for sharing
    is_shared = db.Column(db.Boolean, default=False, nullable=False)  # Whether conversation is publicly shared
    shared_at = db.Column(db.DateTime, nullable=True)  # When sharing was enabled
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship to messages (conversation owns messages, NOT user)
    messages = db.relationship(
        'AIMessage',
        backref='conversation',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='AIMessage.created_at.asc()'
    )

    def to_dict(self, include_messages=False):
        """Convert to API response format"""
        result = {
            'id': self.id,
            'title': self.title or self._generate_default_title(),
            'isArchived': self.is_archived,
            'isShared': self.is_shared,
            'shareToken': self.share_token,
            'sharedAt': self.shared_at.isoformat() if self.shared_at else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'messageCount': self.messages.count()
        }
        
        if include_messages:
            result['messages'] = [msg.to_dict() for msg in self.messages.all()]
        
        return result
    
    def to_shared_dict(self):
        """Convert to API response format for shared view (no sensitive data)"""
        return {
            'id': self.id,
            'title': self.title or self._generate_default_title(),
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'messageCount': self.messages.count(),
            'messages': [msg.to_dict() for msg in self.messages.all()]
        }

    def to_list_item(self):
        """Lightweight format for conversation list sidebar"""
        return {
            'id': self.id,
            'title': self.title or self._generate_default_title(),
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'preview': self._get_preview()
        }

    def _generate_default_title(self):
        """Generate title from first user message"""
        first_msg = self.messages.filter_by(role='user').first()
        if first_msg:
            # Truncate to first 50 chars
            content = first_msg.content[:50]
            return content + '...' if len(first_msg.content) > 50 else content
        return 'New Conversation'

    def _get_preview(self):
        """Get last message preview for sidebar"""
        last_msg = self.messages.order_by(AIMessage.created_at.desc()).first()
        if last_msg:
            preview = last_msg.content[:80]
            return preview + '...' if len(last_msg.content) > 80 else preview
        return None

    def update_title_from_content(self):
        """Auto-generate title from first user message if not set"""
        if not self.title:
            self.title = self._generate_default_title()

    def __repr__(self):
        return f'<AIConversation {self.id} user={self.user_id}>'


class AIMessage(db.Model):
    """
    Represents a single message within a conversation.
    
    Belongs to Conversation, NOT directly to User.
    """
    __tablename__ = 'ai_messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, 
        db.ForeignKey('ai_conversations.id', ondelete='CASCADE'), 
        nullable=False, 
        index=True
    )
    
    # Message content
    role = db.Column(db.String(10), nullable=False)  # 'user' or 'ai'
    content = db.Column(db.Text, nullable=False)
    
    # Optional: Store suggestions/place data for AI responses
    suggestions_json = db.Column(db.Text, nullable=True)
    
    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        """Convert to API response format"""
        import json
        
        result = {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }
        
        # Parse suggestions if present
        if self.suggestions_json:
            try:
                result['suggestions'] = json.loads(self.suggestions_json)
            except (json.JSONDecodeError, TypeError):
                result['suggestions'] = None
        
        return result

    def __repr__(self):
        return f'<AIMessage {self.id} conv={self.conversation_id} role={self.role}>'


# =============================================================================
# Repository Pattern - Clean API Access (No ORM coupling to User)
# =============================================================================

class ConversationRepository:
    """
    Clean API for conversation operations.
    Avoids ORM complexity - all access through explicit queries.
    """
    
    @staticmethod
    def get_user_conversations(user_id: int, include_archived: bool = False, limit: int = 50):
        """
        Get all conversations for a user.
        
        Args:
            user_id: Owner's user ID
            include_archived: Whether to include archived conversations
            limit: Max conversations to return
        
        Returns:
            List of AIConversation objects
        """
        query = AIConversation.query.filter_by(user_id=user_id)
        
        if not include_archived:
            query = query.filter_by(is_archived=False)
        
        return query.order_by(AIConversation.updated_at.desc()).limit(limit).all()

    @staticmethod
    def get_conversation(conversation_id: int, user_id: int):
        """
        Get a specific conversation (with ownership check).
        
        Args:
            conversation_id: Conversation ID
            user_id: User ID for ownership verification
        
        Returns:
            AIConversation or None if not found/not owned
        """
        return AIConversation.query.filter_by(
            id=conversation_id, 
            user_id=user_id
        ).first()

    @staticmethod
    def create_conversation(user_id: int, title: str = None):
        """
        Create a new conversation.
        
        Args:
            user_id: Owner's user ID
            title: Optional title (auto-generated if not provided)
        
        Returns:
            New AIConversation object
        """
        conversation = AIConversation(
            user_id=user_id,
            title=title
        )
        db.session.add(conversation)
        db.session.commit()
        return conversation

    @staticmethod
    def add_message(conversation_id: int, role: str, content: str, suggestions_json: str = None):
        """
        Add a message to a conversation.
        
        Args:
            conversation_id: Target conversation
            role: 'user' or 'ai'
            content: Message content
            suggestions_json: Optional JSON string
        
        Returns:
            New AIMessage object
        """
        message = AIMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            suggestions_json=suggestions_json
        )
        db.session.add(message)
        
        # Update conversation's updated_at
        conversation = AIConversation.query.get(conversation_id)
        if conversation:
            conversation.updated_at = datetime.utcnow()
            # Auto-generate title from first user message
            if role == 'user' and not conversation.title:
                conversation.update_title_from_content()
        
        db.session.commit()
        return message

    @staticmethod
    def rename_conversation(conversation_id: int, user_id: int, new_title: str):
        """
        Rename a conversation.
        
        Returns:
            Updated AIConversation or None if not found
        """
        conversation = ConversationRepository.get_conversation(conversation_id, user_id)
        if conversation:
            conversation.title = new_title
            conversation.updated_at = datetime.utcnow()
            db.session.commit()
        return conversation

    @staticmethod
    def archive_conversation(conversation_id: int, user_id: int):
        """
        Archive a conversation (soft delete).
        
        Returns:
            True if successful, False if not found
        """
        conversation = ConversationRepository.get_conversation(conversation_id, user_id)
        if conversation:
            conversation.is_archived = True
            db.session.commit()
            return True
        return False

    @staticmethod
    def delete_conversation(conversation_id: int, user_id: int):
        """
        Permanently delete a conversation and all its messages.
        
        Returns:
            True if successful, False if not found
        """
        conversation = ConversationRepository.get_conversation(conversation_id, user_id)
        if conversation:
            db.session.delete(conversation)
            db.session.commit()
            return True
        return False

    @staticmethod
    def get_conversation_messages(conversation_id: int, user_id: int, limit: int = 100):
        """
        Get messages for a conversation (with ownership check).
        
        Returns:
            List of AIMessage objects or None if conversation not found/not owned
        """
        conversation = ConversationRepository.get_conversation(conversation_id, user_id)
        if not conversation:
            return None
        
        return conversation.messages.order_by(AIMessage.created_at.asc()).limit(limit).all()

    @staticmethod
    def get_latest_conversation(user_id: int):
        """
        Get the most recently updated conversation for a user.
        
        Returns:
            AIConversation or None
        """
        return AIConversation.query.filter_by(
            user_id=user_id,
            is_archived=False
        ).order_by(AIConversation.updated_at.desc()).first()

    @staticmethod
    def clear_user_conversations(user_id: int):
        """
        Delete all conversations for a user.
        
        Returns:
            Number of conversations deleted
        """
        count = AIConversation.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        return count

    @staticmethod
    def generate_share_token(conversation_id: int, user_id: int):
        """
        Generate a unique share token for a conversation.
        
        Args:
            conversation_id: Conversation ID
            user_id: User ID for ownership verification
        
        Returns:
            Share token string or None if not found/not owned
        """
        import secrets
        
        conversation = ConversationRepository.get_conversation(conversation_id, user_id)
        if not conversation:
            return None
        
        # Generate a unique token if not already shared
        if not conversation.share_token:
            conversation.share_token = secrets.token_urlsafe(32)
        
        conversation.is_shared = True
        conversation.shared_at = datetime.utcnow()
        db.session.commit()
        
        return conversation.share_token

    @staticmethod
    def disable_sharing(conversation_id: int, user_id: int):
        """
        Disable sharing for a conversation (revoke share link).
        
        Returns:
            True if successful, False if not found
        """
        conversation = ConversationRepository.get_conversation(conversation_id, user_id)
        if not conversation:
            return False
        
        conversation.is_shared = False
        # Keep the token so re-enabling uses same URL
        db.session.commit()
        return True

    @staticmethod
    def get_shared_conversation(share_token: str):
        """
        Get a conversation by its share token (public access, no auth required).
        
        Args:
            share_token: The unique share token
        
        Returns:
            AIConversation or None if not found or not shared
        """
        return AIConversation.query.filter_by(
            share_token=share_token,
            is_shared=True
        ).first()
