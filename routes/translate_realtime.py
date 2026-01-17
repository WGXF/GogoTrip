# routes/translate_realtime.py

from flask import request
from flask_socketio import emit, disconnect
from flask_login import current_user
import google.generativeai as genai
from google.cloud import texttospeech_v1 as tts
import base64
import asyncio
import threading
from queue import Queue
import config

# Store active sessions
active_sessions = {}

# Language configurations
LANG_NAME = {
    "en": "English", "ja": "Japanese", "es": "Spanish",
    "fr": "French", "ko": "Korean", "zh": "Chinese",
    "it": "Italian", "de": "German", "my": "Malay"
}

TTS_VOICE_MAP = {
    "en": {"language_code": "en-US", "name": "en-US-Neural2-J"},
    "ja": {"language_code": "ja-JP", "name": "ja-JP-Neural2-B"},
    "es": {"language_code": "es-ES", "name": "es-ES-Neural2-A"},
    "fr": {"language_code": "fr-FR", "name": "fr-FR-Neural2-A"},
    "ko": {"language_code": "ko-KR", "name": "ko-KR-Neural2-A"},
    "zh": {"language_code": "cmn-CN", "name": "cmn-CN-Wavenet-A"},
    "it": {"language_code": "it-IT", "name": "it-IT-Neural2-A"},
    "de": {"language_code": "de-DE", "name": "de-DE-Neural2-A"},
    "my": {"language_code": "ms-MY", "name": "ms-MY-Standard-A"}
}


class RealtimeTranslationSession:
    """Manages a real-time translation session for a user"""
    
    def __init__(self, user_id, source_lang, target_lang, socket_id):
        self.user_id = user_id
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.socket_id = socket_id
        self.is_active = True
        self.audio_queue = Queue()
        self.accumulated_text = ""
        
        # Initialize TTS client
        self.tts_client = tts.TextToSpeechClient()
        
        # Initialize Gemini model
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
    def process_audio(self, audio_data):
        """Process incoming audio chunk"""
        if not self.is_active:
            return
        self.audio_queue.put(audio_data)
    
    def translate_text(self, text):
        """Translate text using Gemini"""
        try:
            source_name = LANG_NAME.get(self.source_lang, self.source_lang)
            target_name = LANG_NAME.get(self.target_lang, self.target_lang)
            
            prompt = f"""Translate this from {source_name} to {target_name}. 
            Output only the translation, nothing else:
            {text}"""
            
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Translation error: {e}")
            return None
    
    def generate_speech(self, text):
        """Generate TTS audio for translated text"""
        try:
            voice_config = TTS_VOICE_MAP.get(self.target_lang, TTS_VOICE_MAP['en'])
            
            synthesis_input = tts.SynthesisInput(text=text)
            voice = tts.VoiceSelectionParams(
                language_code=voice_config['language_code'],
                name=voice_config['name']
            )
            audio_config = tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.MP3,
                speaking_rate=1.0
            )
            
            response = self.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            return base64.b64encode(response.audio_content).decode('utf-8')
        except Exception as e:
            print(f"TTS error: {e}")
            return None
    
    def stop(self):
        """Stop the session"""
        self.is_active = False


def register_realtime_handlers(socketio):
    """Register all WebSocket event handlers"""
    
    @socketio.on('connect', namespace='/translate')
    def handle_connect():
        """Handle new WebSocket connection"""
        print(f"[Translate WS] Connection attempt from {request.sid}")
        
        # Check authentication
        if not current_user.is_authenticated:
            emit('error', {
                'code': 'AUTH_REQUIRED',
                'message': 'Please login to use real-time translation'
            })
            disconnect()
            return
        
        # Check premium status
        if not current_user.is_premium_active:
            emit('error', {
                'code': 'PREMIUM_REQUIRED',
                'message': 'Please upgrade to Premium to use real-time voice translation',
                'upgrade_url': '/pricing'
            })
            disconnect()
            return
        
        emit('connected', {
            'status': 'success',
            'message': 'Connected to real-time translation service',
            'user_id': current_user.id
        })
        print(f"[Translate WS] User {current_user.id} connected")
    
    
    @socketio.on('disconnect', namespace='/translate')
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        session_id = request.sid
        
        # Clean up session
        if session_id in active_sessions:
            active_sessions[session_id].stop()
            del active_sessions[session_id]
        
        print(f"[Translate WS] Disconnected: {session_id}")
    
    
    @socketio.on('start_session', namespace='/translate')
    def handle_start_session(data):
        """
        Start a new translation session
        
        data: {
            source_lang: 'en',
            target_lang: 'ja'
        }
        """
        if not current_user.is_authenticated or not current_user.is_premium_active:
            emit('error', {'code': 'UNAUTHORIZED', 'message': 'Not authorized'})
            return
        
        source_lang = data.get('source_lang', 'en')
        target_lang = data.get('target_lang', 'ja')
        session_id = request.sid
        
        # Create new session
        session = RealtimeTranslationSession(
            user_id=current_user.id,
            source_lang=source_lang,
            target_lang=target_lang,
            socket_id=session_id
        )
        active_sessions[session_id] = session
        
        emit('session_started', {
            'status': 'success',
            'session_id': session_id,
            'source_lang': source_lang,
            'target_lang': target_lang,
            'message': f'Ready to translate from {LANG_NAME.get(source_lang, source_lang)} to {LANG_NAME.get(target_lang, target_lang)}'
        })
        
        print(f"[Translate WS] Session started for user {current_user.id}: {source_lang} -> {target_lang}")
    
    
    @socketio.on('audio_chunk', namespace='/translate')
    def handle_audio_chunk(data):
        """
        Receive audio chunk from client
        
        data: {
            audio: base64_encoded_audio,
            is_final: bool (optional, marks end of utterance)
        }
        """
        session_id = request.sid
        
        if session_id not in active_sessions:
            emit('error', {'code': 'NO_SESSION', 'message': 'No active session'})
            return
        
        session = active_sessions[session_id]
        
        try:
            audio_data = data.get('audio', '')
            is_final = data.get('is_final', False)
            
            # For demonstration, we'll process the audio when is_final is True
            # In a production system, you'd use Gemini Live API's streaming
            if is_final and audio_data:
                # Decode audio
                audio_bytes = base64.b64decode(audio_data)
                
                # Use Gemini to transcribe and translate
                # Note: In production, use Gemini Live API for real streaming
                transcription = transcribe_audio_with_gemini(audio_bytes, session.source_lang)
                
                if transcription:
                    # Emit transcription
                    emit('transcription', {
                        'text': transcription,
                        'is_final': True
                    })
                    
                    # Translate
                    translation = session.translate_text(transcription)
                    
                    if translation:
                        # Emit translation
                        emit('translation', {
                            'original': transcription,
                            'translated': translation,
                            'source_lang': session.source_lang,
                            'target_lang': session.target_lang
                        })
                        
                        # Generate and emit TTS
                        audio_base64 = session.generate_speech(translation)
                        if audio_base64:
                            emit('audio_response', {
                                'audio': audio_base64,
                                'format': 'mp3',
                                'text': translation
                            })
                else:
                    emit('error', {
                        'code': 'TRANSCRIPTION_FAILED',
                        'message': 'Could not transcribe audio'
                    })
                    
        except Exception as e:
            print(f"[Translate WS] Audio processing error: {e}")
            emit('error', {
                'code': 'PROCESSING_ERROR',
                'message': str(e)
            })
    
    
    @socketio.on('text_input', namespace='/translate')
    def handle_text_input(data):
        """
        Handle direct text input for translation (alternative to voice)
        
        data: {
            text: 'Hello world'
        }
        """
        session_id = request.sid
        
        if session_id not in active_sessions:
            emit('error', {'code': 'NO_SESSION', 'message': 'No active session'})
            return
        
        session = active_sessions[session_id]
        text = data.get('text', '').strip()
        
        if not text:
            return
        
        try:
            # Translate
            translation = session.translate_text(text)
            
            if translation:
                emit('translation', {
                    'original': text,
                    'translated': translation,
                    'source_lang': session.source_lang,
                    'target_lang': session.target_lang
                })
                
                # Generate TTS
                audio_base64 = session.generate_speech(translation)
                if audio_base64:
                    emit('audio_response', {
                        'audio': audio_base64,
                        'format': 'mp3',
                        'text': translation
                    })
        except Exception as e:
            emit('error', {'code': 'TRANSLATION_ERROR', 'message': str(e)})
    
    
    @socketio.on('stop_session', namespace='/translate')
    def handle_stop_session():
        """Stop the current translation session"""
        session_id = request.sid
        
        if session_id in active_sessions:
            active_sessions[session_id].stop()
            del active_sessions[session_id]
        
        emit('session_ended', {
            'status': 'success',
            'message': 'Translation session ended'
        })
        print(f"[Translate WS] Session stopped: {session_id}")
    
    
    @socketio.on('change_languages', namespace='/translate')
    def handle_change_languages(data):
        """
        Change languages mid-session
        
        data: {
            source_lang: 'ja',
            target_lang: 'en'
        }
        """
        session_id = request.sid
        
        if session_id not in active_sessions:
            emit('error', {'code': 'NO_SESSION', 'message': 'No active session'})
            return
        
        session = active_sessions[session_id]
        session.source_lang = data.get('source_lang', session.source_lang)
        session.target_lang = data.get('target_lang', session.target_lang)
        
        emit('languages_changed', {
            'source_lang': session.source_lang,
            'target_lang': session.target_lang,
            'message': f'Now translating from {LANG_NAME.get(session.source_lang)} to {LANG_NAME.get(session.target_lang)}'
        })


def transcribe_audio_with_gemini(audio_bytes, language):
    try:
        lang_name = LANG_NAME.get(language, language)

        model = genai.GenerativeModel("gemini-2.5-flash")

        response = model.generate_content([
            {
                "mime_type": "audio/webm",
                "data": audio_bytes
            },
            f"Transcribe this audio. The speaker is talking in {lang_name}. "
            "Output only the transcription, nothing else."
        ])

        return response.text.strip()

    except Exception as e:
        print(f"Gemini transcription error: {e}")
        return None


def init_realtime_translation(socketio):
    """Initialize real-time translation WebSocket handlers"""
    register_realtime_handlers(socketio)
    print("[Translate WS] Real-time translation handlers registered")