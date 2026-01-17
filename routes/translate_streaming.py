# routes/translate_streaming.py

from flask import request
from flask_socketio import emit, disconnect, join_room, leave_room
from flask_login import current_user
import google.generativeai as genai
from google.cloud import texttospeech_v1 as tts
from google.cloud import translate_v2 as translate
import base64
import threading
import time
from typing import Optional, Dict
from dataclasses import dataclass, field
from enum import Enum
import config

# Import streaming ASR service
from services.streaming_asr import (
    StreamingASRManager,
    ConversationStreamManager,
    TranscriptionResult,
    StreamState
)


# ============================================
# Configuration
# ============================================

# Language configurations
LANG_NAME = {
    "en": "English", "ja": "Japanese", "es": "Spanish",
    "fr": "French", "ko": "Korean", "zh": "Chinese",
    "it": "Italian", "de": "German", "my": "Malay",
    "th": "Thai", "vi": "Vietnamese", "id": "Indonesian",
    "pt": "Portuguese", "ru": "Russian", "ar": "Arabic"
}

LANG_FLAG = {
    "en": "🇺🇸", "ja": "🇯🇵", "es": "🇪🇸", "fr": "🇫🇷",
    "ko": "🇰🇷", "zh": "🇨🇳", "it": "🇮🇹", "de": "🇩🇪",
    "my": "🇲🇾", "th": "🇹🇭", "vi": "🇻🇳", "id": "🇮🇩",
    "pt": "🇵🇹", "ru": "🇷🇺", "ar": "🇸🇦"
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
    "my": {"language_code": "ms-MY", "name": "ms-MY-Standard-A"},
    "th": {"language_code": "th-TH", "name": "th-TH-Neural2-C"},
    "vi": {"language_code": "vi-VN", "name": "vi-VN-Neural2-A"},
    "id": {"language_code": "id-ID", "name": "id-ID-Neural2-A"},
    "pt": {"language_code": "pt-BR", "name": "pt-BR-Neural2-A"},
    "ru": {"language_code": "ru-RU", "name": "ru-RU-Neural2-A"},
    "ar": {"language_code": "ar-XA", "name": "ar-XA-Neural2-A"}
}

# Translation API language codes
TRANSLATE_LANG_CODES = {
    "en": "en", "ja": "ja", "es": "es", "fr": "fr",
    "ko": "ko", "zh": "zh-CN", "it": "it", "de": "de",
    "my": "ms", "th": "th", "vi": "vi", "id": "id",
    "pt": "pt", "ru": "ru", "ar": "ar"
}


# ============================================
# Session Management
# ============================================

@dataclass
class StreamingSession:
    """Streaming session for a user"""
    user_id: int
    socket_id: str
    lang_a: str
    lang_b: str
    current_speaker: Optional[str] = None
    stream_manager: Optional[ConversationStreamManager] = None
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    
    # Clients
    tts_client: Optional[tts.TextToSpeechClient] = None
    translate_client: Optional[translate.Client] = None
    
    # Stats
    total_chunks: int = 0
    total_transcriptions: int = 0
    total_translations: int = 0
    
    def __post_init__(self):
        """Initialize clients and stream manager"""
        self.tts_client = tts.TextToSpeechClient()
        self.translate_client = translate.Client()


# Active sessions storage
active_streaming_sessions: Dict[str, StreamingSession] = {}


# ============================================
# Helper Functions
# ============================================

def get_target_language(session: StreamingSession, speaker: str) -> str:
    """Get the target language for translation based on speaker"""
    # Speaker A speaks lang_a, translates to lang_b
    # Speaker B speaks lang_b, translates to lang_a
    return session.lang_b if speaker == 'A' else session.lang_a


def translate_text(session: StreamingSession, text: str, source_lang: str, target_lang: str) -> Optional[str]:
    """Translate text using Google Cloud Translation API"""
    try:
        source_code = TRANSLATE_LANG_CODES.get(source_lang, source_lang)
        target_code = TRANSLATE_LANG_CODES.get(target_lang, target_lang)
        
        result = session.translate_client.translate(
            text,
            source_language=source_code,
            target_language=target_code
        )
        
        return result['translatedText']
    except Exception as e:
        print(f"[StreamingTranslate] Translation error: {e}")
        return None


def generate_speech(session: StreamingSession, text: str, language: str) -> Optional[str]:
    """Generate TTS audio and return as base64"""
    try:
        voice_config = TTS_VOICE_MAP.get(language, TTS_VOICE_MAP['en'])
        
        synthesis_input = tts.SynthesisInput(text=text)
        voice = tts.VoiceSelectionParams(
            language_code=voice_config['language_code'],
            name=voice_config['name']
        )
        audio_config = tts.AudioConfig(
            audio_encoding=tts.AudioEncoding.MP3,
            speaking_rate=1.0
        )
        
        response = session.tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        return base64.b64encode(response.audio_content).decode('utf-8')
    except Exception as e:
        print(f"[StreamingTranslate] TTS error: {e}")
        return None


# ============================================
# WebSocket Handlers
# ============================================

def register_streaming_handlers(socketio):
    """Register streaming WebSocket event handlers"""
    
    @socketio.on('connect', namespace='/translate-stream')
    def handle_connect():
        """Handle new WebSocket connection"""
        print(f"[StreamingTranslate] Connection attempt: {request.sid}")
        
        # Authentication check
        if not current_user.is_authenticated:
            emit('error', {
                'code': 'AUTH_REQUIRED',
                'message': 'Please login to use streaming translation'
            })
            disconnect()
            return
        
        # Premium check
        if not current_user.is_premium_active:
            emit('error', {
                'code': 'PREMIUM_REQUIRED',
                'message': 'Streaming translation is a Premium feature',
                'upgrade_url': '/pricing'
            })
            disconnect()
            return
        
        # Join user room for targeted emits
        join_room(request.sid)
        
        emit('connected', {
            'status': 'success',
            'message': 'Connected to streaming translation service',
            'user_id': current_user.id,
            'capabilities': {
                'streaming': True,
                'partial_results': True,
                'max_duration_seconds': 300
            }
        })
        
        print(f"[StreamingTranslate] User {current_user.id} connected")
    
    
    @socketio.on('disconnect', namespace='/translate-stream')
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        session_id = request.sid
        
        # Clean up session
        if session_id in active_streaming_sessions:
            session = active_streaming_sessions[session_id]
            if session.stream_manager:
                session.stream_manager.stop_all()
            del active_streaming_sessions[session_id]
        
        leave_room(session_id)
        print(f"[StreamingTranslate] Disconnected: {session_id}")
    
    
    @socketio.on('start_streaming', namespace='/translate-stream')
    def handle_start_streaming(data):
        """
        Start streaming session for a speaker.
        
        data: {
            lang_a: 'en',        # Speaker A's language
            lang_b: 'ja',        # Speaker B's language  
            speaker: 'A'         # Current speaker starting
        }
        """
        if not current_user.is_authenticated or not current_user.is_premium_active:
            emit('error', {'code': 'UNAUTHORIZED', 'message': 'Not authorized'})
            return
        
        session_id = request.sid
        lang_a = data.get('lang_a', 'en')
        lang_b = data.get('lang_b', 'ja')
        speaker = data.get('speaker', 'A')
        
        if speaker not in ['A', 'B']:
            emit('error', {'code': 'INVALID_SPEAKER', 'message': 'Speaker must be A or B'})
            return
        
        # Create or update session
        if session_id not in active_streaming_sessions:
            session = StreamingSession(
                user_id=current_user.id,
                socket_id=session_id,
                lang_a=lang_a,
                lang_b=lang_b
            )
            active_streaming_sessions[session_id] = session
        else:
            session = active_streaming_sessions[session_id]
            session.lang_a = lang_a
            session.lang_b = lang_b
        
        # Track last stable partial to avoid duplicate translations
        last_stable_partial = {'A': '', 'B': ''}
        
        # Create stream manager with callbacks
        def on_partial(spk: str, result: TranscriptionResult):
            """Handle partial transcription - show live subtitles"""
            socketio.emit('partial_transcription', {
                'speaker': spk,
                'text': result.text,
                'language': result.language,
                'language_name': LANG_NAME.get(result.language, result.language),
                'flag': LANG_FLAG.get(result.language, '🌐'),
                'stability': result.stability,
                'is_stable': result.stability > 0.8
            }, room=session_id, namespace='/translate-stream')
            
            # For highly stable partials (>0.85), emit early partial translation
            # This gives faster feedback while user is still speaking
            if result.stability > 0.85 and len(result.text) > 10:
                # Avoid translating the same stable text repeatedly
                if result.text != last_stable_partial[spk]:
                    last_stable_partial[spk] = result.text
                    
                    # Get translation direction
                    source_lang = session.lang_a if spk == 'A' else session.lang_b
                    target_lang = session.lang_b if spk == 'A' else session.lang_a
                    
                    # Quick translation for stable partial (no TTS yet)
                    translated = translate_text(session, result.text, source_lang, target_lang)
                    if translated:
                        socketio.emit('partial_translation', {
                            'speaker': spk,
                            'original_text': result.text,
                            'translated_text': translated,
                            'target_lang': target_lang,
                            'target_lang_name': LANG_NAME.get(target_lang, target_lang),
                            'target_flag': LANG_FLAG.get(target_lang, '🌐'),
                            'is_partial': True
                        }, room=session_id, namespace='/translate-stream')
        
        def on_final(spk: str, result: TranscriptionResult):
            """Handle final transcription → translate → TTS (with parallelization)"""
            session.total_transcriptions += 1
            
            # Clear the stable partial tracker
            last_stable_partial[spk] = ''
            
            # Emit final transcription
            socketio.emit('final_transcription', {
                'speaker': spk,
                'text': result.text,
                'language': result.language,
                'language_name': LANG_NAME.get(result.language, result.language),
                'flag': LANG_FLAG.get(result.language, '🌐'),
                'confidence': result.confidence
            }, room=session_id, namespace='/translate-stream')
            
            # Get translation direction
            source_lang = session.lang_a if spk == 'A' else session.lang_b
            target_lang = session.lang_b if spk == 'A' else session.lang_a
            
            # Translate
            translated = translate_text(session, result.text, source_lang, target_lang)
            
            if translated:
                session.total_translations += 1
                
                # Emit translation IMMEDIATELY (don't wait for TTS)
                socketio.emit('translation', {
                    'speaker': spk,
                    'original_text': result.text,
                    'translated_text': translated,
                    'source_lang': source_lang,
                    'source_lang_name': LANG_NAME.get(source_lang, source_lang),
                    'source_flag': LANG_FLAG.get(source_lang, '🌐'),
                    'target_lang': target_lang,
                    'target_lang_name': LANG_NAME.get(target_lang, target_lang),
                    'target_flag': LANG_FLAG.get(target_lang, '🌐')
                }, room=session_id, namespace='/translate-stream')
                
                # Generate TTS in parallel thread for faster response
                def generate_and_emit_tts():
                    try:
                        audio_base64 = generate_speech(session, translated, target_lang)
                        if audio_base64:
                            for_speaker = 'B' if spk == 'A' else 'A'
                            socketio.emit('audio_response', {
                                'speaker': spk,
                                'audio': audio_base64,
                                'format': 'mp3',
                                'text': translated,
                                'language': target_lang,
                                'for_speaker': for_speaker,
                                'auto_play': True
                            }, room=session_id, namespace='/translate-stream')
                    except Exception as e:
                        print(f"[StreamingTranslate] TTS Generation Error: {e}")
                
                # Run TTS generation in background thread
                tts_thread = threading.Thread(target=generate_and_emit_tts, daemon=True)
                tts_thread.start()
        
        def on_error(spk: str, error: Exception):
            """Handle streaming error"""
            socketio.emit('error', {
                'code': 'STREAMING_ERROR',
                'message': str(error),
                'speaker': spk
            }, room=session_id, namespace='/translate-stream')
        
        # Create conversation stream manager
        session.stream_manager = ConversationStreamManager(
            lang_a=lang_a,
            lang_b=lang_b,
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error
        )
        
        # Start streaming for the speaker
        if session.stream_manager.start_speaker(speaker):
            session.current_speaker = speaker
            
            emit('streaming_started', {
                'speaker': speaker,
                'language': lang_a if speaker == 'A' else lang_b,
                'language_name': LANG_NAME.get(lang_a if speaker == 'A' else lang_b),
                'flag': LANG_FLAG.get(lang_a if speaker == 'A' else lang_b, '🌐'),
                'session_info': {
                    'lang_a': lang_a,
                    'lang_b': lang_b,
                    'lang_a_name': LANG_NAME.get(lang_a, lang_a),
                    'lang_b_name': LANG_NAME.get(lang_b, lang_b),
                    'lang_a_flag': LANG_FLAG.get(lang_a, '🌐'),
                    'lang_b_flag': LANG_FLAG.get(lang_b, '🌐')
                }
            })
            
            print(f"[StreamingTranslate] Streaming started: User {current_user.id}, Speaker {speaker}, Lang {lang_a if speaker == 'A' else lang_b}")
        else:
            emit('error', {
                'code': 'STREAM_START_FAILED',
                'message': 'Failed to start streaming'
            })
    
    
    @socketio.on('audio_chunk', namespace='/translate-stream')
    def handle_audio_chunk(data):
        """
        Receive audio chunk from client.
        
        data: {
            audio: base64_encoded_audio,
            speaker: 'A' | 'B',
            seq: chunk_sequence_number (optional)
        }
        """
        session_id = request.sid
        
        if session_id not in active_streaming_sessions:
            emit('error', {'code': 'NO_SESSION', 'message': 'No active session'})
            return
        
        session = active_streaming_sessions[session_id]
        
        if not session.stream_manager:
            emit('error', {'code': 'NO_STREAM', 'message': 'Streaming not started'})
            return
        
        try:
            audio_base64 = data.get('audio', '')
            speaker = data.get('speaker', session.current_speaker or 'A')
            
            if not audio_base64:
                return
            
            # Decode audio
            audio_bytes = base64.b64decode(audio_base64)
            
            # Add to stream
            if session.stream_manager.add_audio(speaker, audio_bytes):
                session.total_chunks += 1
            else:
                # Stream not active for this speaker, start it
                if session.stream_manager.start_speaker(speaker):
                    session.current_speaker = speaker
                    session.stream_manager.add_audio(speaker, audio_bytes)
                    session.total_chunks += 1
                    
        except Exception as e:
            print(f"[StreamingTranslate] Audio chunk error: {e}")
            emit('error', {
                'code': 'AUDIO_ERROR',
                'message': str(e)
            })
    
    
    @socketio.on('stop_streaming', namespace='/translate-stream')
    def handle_stop_streaming(data):
        """
        Stop streaming for current speaker.
        
        data: {
            speaker: 'A' | 'B' (optional, defaults to current)
        }
        """
        session_id = request.sid
        
        if session_id not in active_streaming_sessions:
            return
        
        session = active_streaming_sessions[session_id]
        speaker = data.get('speaker', session.current_speaker)
        
        if session.stream_manager and speaker:
            session.stream_manager.stop_speaker(speaker)
            
            # Determine next speaker
            next_speaker = 'B' if speaker == 'A' else 'A'
            
            emit('streaming_ended', {
                'speaker': speaker,
                'next_speaker': next_speaker,
                'stats': {
                    'chunks_processed': session.total_chunks,
                    'transcriptions': session.total_transcriptions,
                    'translations': session.total_translations
                }
            })
            
            session.current_speaker = None
            print(f"[StreamingTranslate] Streaming ended for speaker {speaker}")
    
    
    @socketio.on('switch_speaker', namespace='/translate-stream')
    def handle_switch_speaker(data):
        """
        Switch to different speaker.
        
        data: {
            speaker: 'A' | 'B'
        }
        """
        session_id = request.sid
        
        if session_id not in active_streaming_sessions:
            emit('error', {'code': 'NO_SESSION', 'message': 'No active session'})
            return
        
        session = active_streaming_sessions[session_id]
        new_speaker = data.get('speaker')
        
        if new_speaker not in ['A', 'B']:
            emit('error', {'code': 'INVALID_SPEAKER', 'message': 'Speaker must be A or B'})
            return
        
        # Stop current speaker
        if session.current_speaker and session.stream_manager:
            session.stream_manager.stop_speaker(session.current_speaker)
        
        # Start new speaker
        if session.stream_manager and session.stream_manager.start_speaker(new_speaker):
            session.current_speaker = new_speaker
            
            emit('speaker_switched', {
                'speaker': new_speaker,
                'language': session.lang_a if new_speaker == 'A' else session.lang_b,
                'language_name': LANG_NAME.get(session.lang_a if new_speaker == 'A' else session.lang_b),
                'flag': LANG_FLAG.get(session.lang_a if new_speaker == 'A' else session.lang_b, '🌐')
            })
    
    
    @socketio.on('swap_languages', namespace='/translate-stream')
    def handle_swap_languages():
        """Swap languages between speakers"""
        session_id = request.sid
        
        if session_id not in active_streaming_sessions:
            return
        
        session = active_streaming_sessions[session_id]
        
        # Swap
        session.lang_a, session.lang_b = session.lang_b, session.lang_a
        
        if session.stream_manager:
            session.stream_manager.swap_languages()
        
        emit('languages_swapped', {
            'lang_a': session.lang_a,
            'lang_b': session.lang_b,
            'lang_a_name': LANG_NAME.get(session.lang_a, session.lang_a),
            'lang_b_name': LANG_NAME.get(session.lang_b, session.lang_b),
            'lang_a_flag': LANG_FLAG.get(session.lang_a, '🌐'),
            'lang_b_flag': LANG_FLAG.get(session.lang_b, '🌐')
        })
    
    
    @socketio.on('end_session', namespace='/translate-stream')
    def handle_end_session():
        """End the entire streaming session"""
        session_id = request.sid
        
        if session_id in active_streaming_sessions:
            session = active_streaming_sessions[session_id]
            
            if session.stream_manager:
                session.stream_manager.stop_all()
            
            emit('session_ended', {
                'status': 'success',
                'stats': {
                    'total_chunks': session.total_chunks,
                    'total_transcriptions': session.total_transcriptions,
                    'total_translations': session.total_translations,
                    'duration_seconds': round(time.time() - session.created_at, 2)
                }
            })
            
            del active_streaming_sessions[session_id]
            
        print(f"[StreamingTranslate] Session ended: {session_id}")
    
    
    @socketio.on('get_stats', namespace='/translate-stream')
    def handle_get_stats():
        """Get current session statistics"""
        session_id = request.sid
        
        if session_id not in active_streaming_sessions:
            emit('stats', {'error': 'No active session'})
            return
        
        session = active_streaming_sessions[session_id]
        
        stats = {
            'session': {
                'lang_a': session.lang_a,
                'lang_b': session.lang_b,
                'current_speaker': session.current_speaker,
                'total_chunks': session.total_chunks,
                'total_transcriptions': session.total_transcriptions,
                'total_translations': session.total_translations,
                'duration_seconds': round(time.time() - session.created_at, 2)
            }
        }
        
        if session.stream_manager:
            stats['streams'] = session.stream_manager.get_stats()
        
        emit('stats', stats)


def init_streaming_translation(socketio):
    """Initialize streaming translation WebSocket handlers"""
    register_streaming_handlers(socketio)
    print("[StreamingTranslate] Streaming translation handlers registered on /translate-stream")
