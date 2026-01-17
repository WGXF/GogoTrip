# ----------------------
# AI Chat History Table (NEW - Premium Feature)
# ----------------------
class AIChatHistory(db.Model):
    """
    Stores AI chat messages for Premium users.
    
    Premium users can:
    - Have their chat messages saved automatically
    - Access chat history across sessions
    - Load previous conversations on page refresh
    
    Free users:
    - No chat history saved
    - Chat clears on page refresh (current behavior)
    """
    __tablename__ = 'ai_chat_histories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)  # 'user' or 'ai'
    content = db.Column(db.Text, nullable=False)
    
    # Optional: Store suggestions/place data for AI responses with recommendations
    suggestions_json = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationship
    user = db.relationship('User', backref=db.backref('chat_histories', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        """Convert chat message to dictionary for API responses"""
        result = {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'timestamp': self.created_at.isoformat() if self.created_at else None
        }
        
        # Include suggestions if present
        if self.suggestions_json:
            try:
                import json
                result['suggestions'] = json.loads(self.suggestions_json)
            except:
                result['suggestions'] = None
        
        return result

    @staticmethod
    def save_message(user_id: int, role: str, content: str, suggestions_json: str = None):
        """
        Helper method to save a chat message.
        
        Args:
            user_id: The ID of the user
            role: 'user' or 'ai'
            content: The message content
            suggestions_json: Optional JSON string of suggestions/places
        
        Returns:
            AIChatHistory: The saved message object
        """
        message = AIChatHistory(
            user_id=user_id,
            role=role,
            content=content,
            suggestions_json=suggestions_json
        )
        db.session.add(message)
        db.session.commit()
        return message

    @staticmethod
    def get_user_history(user_id: int, limit: int = 100):
        """
        Get chat history for a user, ordered by creation time.
        
        Args:
            user_id: The ID of the user
            limit: Maximum number of messages to return (default 100)
        
        Returns:
            List of AIChatHistory objects
        """
        return AIChatHistory.query.filter_by(user_id=user_id)\
            .order_by(AIChatHistory.created_at.asc())\
            .limit(limit)\
            .all()

    @staticmethod
    def clear_user_history(user_id: int):
        """
        Clear all chat history for a user.
        
        Args:
            user_id: The ID of the user
        
        Returns:
            int: Number of messages deleted
        """
        count = AIChatHistory.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        return count

    def __repr__(self):
        return f'<AIChatHistory {self.id} user={self.user_id} role={self.role}>'


# ----------------------
# Update User model - Add relationship (if not using backref above)
# ----------------------
# Add this line to the User class relationships section:
# chat_histories = db.relationship('AIChatHistory', backref='user', lazy='dynamic', cascade="all, delete-orphan")
