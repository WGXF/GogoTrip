# routes/translate.py
"""
Translation Module - Full Implementation
========================================
Provides two translation modes:
1. Real-time Streaming Translation (Premium Only) - WebSocket with Gemini Live API
2. Batch Audio Translation (All Users) - STT → Translate → TTS pipeline

API Endpoints:
- POST /translate - Text translation (existing)
- POST /translate/audio - Batch audio translation (all users)
- WebSocket /translate/live - Real-time streaming (premium only)
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from functools import wraps
import google.generativeai as genai
from google.cloud import speech_v1 as speech
from google.cloud import texttospeech_v1 as tts
from google.cloud import translate_v2 as translate
import os
import io
import base64
import tempfile
import config

translate_bp = Blueprint('translate', __name__)

# ============================================
# Configuration
# ============================================
try:
    genai.configure(api_key=config.GEMINI_API_KEY)
except Exception as e:
    print(f"Gemini configuration warning: {e}")

# Initialize Google Cloud clients (lazy loading)
_speech_client = None
_tts_client = None
_translate_client = None

def get_speech_client():
    global _speech_client
    if _speech_client is None:
        _speech_client = speech.SpeechClient()
    return _speech_client

def get_tts_client():
    global _tts_client
    if _tts_client is None:
        _tts_client = tts.TextToSpeechClient()
    return _tts_client

def get_translate_client():
    global _translate_client
    if _translate_client is None:
        _translate_client = translate.Client()
    return _translate_client

# ============================================
# Language Mappings
# ============================================
LANG_NAME = {
    "en": "English",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "ko": "Korean",
    "zh": "Chinese",
    "it": "Italian",
    "de": "German",
    "my": "Malay"
}

# BCP-47 language codes for Speech-to-Text
LANG_BCP47 = {
    "en": "en-US",
    "ja": "ja-JP",
    "es": "es-ES",
    "fr": "fr-FR",
    "ko": "ko-KR",
    "zh": "zh-CN",
    "it": "it-IT",
    "de": "de-DE",
    "my": "ms-MY"
}

# Google Cloud TTS voice mapping
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

# Google Cloud Translation API language codes
# Maps our internal codes to Google Translation API codes
LANG_CODE_MAP = {
    "en": "en",
    "ja": "ja",
    "es": "es",
    "fr": "fr",
    "ko": "ko",
    "zh": "zh-CN",  # Simplified Chinese
    "it": "it",
    "de": "de",
    "my": "ms",     # Malay
    "th": "th",
    "vi": "vi",
    "id": "id",
    "pt": "pt",
    "ru": "ru",
    "ar": "ar"
}

# ============================================
# Decorators
# ============================================
def premium_required(f):
    """Decorator to check if user has premium subscription"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({
                'error': 'AuthenticationRequired',
                'message': 'Please login to access this feature'
            }), 401
        
        if not current_user.is_premium_active:
            return jsonify({
                'error': 'PremiumFeatureRequired',
                'message': 'Please upgrade to Premium to use real-time voice translation',
                'upgrade_url': '/billing'
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# Text Translation API (Google Cloud Translation)
# ============================================
@translate_bp.route('/translate', methods=['POST'])
def translate_api():
    """
    Text-to-text translation
    Available to all users
    
    Default: Google Cloud Translation API (fast, stable, low cost)
    Optional: Gemini AI Translation (Premium only, more natural/contextual)
    
    Request body:
        - text: string (required)
        - source_lang: string (default: 'auto')
        - target_lang: string (default: 'en')
        - use_ai: boolean (optional, Premium only) - Use Gemini for natural translation
    """
    try:
        data = request.json
        text = data.get('text', '')
        source_lang = data.get('source_lang', 'auto')
        target_lang = data.get('target_lang', 'en')
        use_ai = data.get('use_ai', False)  # Optional AI mode

        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        # Check if AI mode requested
        if use_ai:
            # Premium check for AI translation
            if not current_user.is_authenticated:
                return jsonify({
                    'error': 'AuthenticationRequired',
                    'message': 'Please login to use AI translation'
                }), 401
            
            if not current_user.is_premium_active:
                return jsonify({
                    'error': 'PremiumFeatureRequired',
                    'message': 'AI translation is a Premium feature',
                    'upgrade_url': '/billing'
                }), 403
            
            # Use Gemini AI for natural translation
            translated_text = translate_with_gemini(text, source_lang, target_lang)
            translation_mode = 'ai'
        else:
            # Default: Google Cloud Translation API
            translated_text, detected_source = translate_with_google(text, source_lang, target_lang)
            if source_lang == 'auto':
                source_lang = detected_source
            translation_mode = 'standard'

        return jsonify({
            'status': 'success',
            'translation': translated_text,
            'source_lang': source_lang,
            'target_lang': target_lang,
            'mode': translation_mode
        })

    except Exception as e:
        print(f"Translation Error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================
# Translation Helper Functions
# ============================================
def translate_with_google(text: str, source_lang: str, target_lang: str) -> tuple:
    """
    Translate using Google Cloud Translation API
    Returns: (translated_text, detected_source_lang)
    """
    translate_client = get_translate_client()
    target_language = LANG_CODE_MAP.get(target_lang, target_lang)
    
    if source_lang == 'auto':
        result = translate_client.translate(text, target_language=target_language)
    else:
        source_language = LANG_CODE_MAP.get(source_lang, source_lang)
        result = translate_client.translate(
            text,
            source_language=source_language,
            target_language=target_language
        )
    
    detected = result.get('detectedSourceLanguage', source_lang)
    return result['translatedText'], detected


def translate_with_gemini(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translate using Gemini AI for more natural/contextual results
    Premium feature only
    """
    source_lang_name = LANG_NAME.get(source_lang, "the source language")
    target_lang_name = LANG_NAME.get(target_lang, target_lang)
    
    prompt = f"""You are a native-level translator specializing in cultural localization.

Translate the following text from {source_lang_name} to {target_lang_name}.

Requirements:
- Keep the meaning accurate
- Make it sound natural and fluent to native speakers
- Adjust expressions to match cultural context and tone
- If direct translation is awkward, rewrite into native-like phrasing

Only output the translated text, nothing else.

Text:
{text}"""
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content(prompt)
    return response.text.strip()


# ============================================
# Batch Audio Translation API (All Users)
# ============================================
@translate_bp.route('/translate/audio', methods=['POST'])
def translate_audio_api():
    """
    Batch audio translation: Audio → STT → Translate → TTS
    Available to all users
    
    Default: Google Cloud Translation API (fast, stable)
    Optional: Gemini AI Translation (Premium only, more natural)
    
    Request: multipart/form-data
        - file: audio file (WAV, FLAC, MP3, OGG, WebM)
        - source_lang: source language code (default: 'auto')
        - target_lang: target language code (required)
        - use_ai: '1' or 'true' (optional, Premium only)
    
    Response:
        {
            "status": "success",
            "original_text": "...",
            "translated_text": "...",
            "audio_base64": "base64_encoded_audio",
            "audio_format": "mp3",
            "mode": "standard" | "ai"
        }
    """
    try:
        # Validate request
        if 'file' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['file']
        source_lang = request.form.get('source_lang', 'auto')
        target_lang = request.form.get('target_lang', 'en')
        use_ai = request.form.get('use_ai', '').lower() in ['1', 'true', 'yes']
        
        # Check premium for AI mode
        if use_ai:
            if not current_user.is_authenticated:
                return jsonify({
                    'error': 'AuthenticationRequired',
                    'message': 'Please login to use AI translation'
                }), 401
            
            if not current_user.is_premium_active:
                return jsonify({
                    'error': 'PremiumFeatureRequired',
                    'message': 'AI translation is a Premium feature',
                    'upgrade_url': '/billing'
                }), 403
        
        if not audio_file.filename:
            return jsonify({'error': 'Empty filename'}), 400
        
        # Read audio content
        audio_content = audio_file.read()
        
        # Detect audio format
        filename = audio_file.filename.lower()
        if filename.endswith('.wav'):
            encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
        elif filename.endswith('.flac'):
            encoding = speech.RecognitionConfig.AudioEncoding.FLAC
        elif filename.endswith('.mp3'):
            encoding = speech.RecognitionConfig.AudioEncoding.MP3
        elif filename.endswith('.ogg') or filename.endswith('.webm'):
            encoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
        else:
            # Default to WEBM_OPUS for browser recordings
            encoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
        
        # Step 1: Speech-to-Text
        speech_client = get_speech_client()
        
        # Determine language for STT
        if source_lang == 'auto':
            # Use language detection or default to English
            stt_lang = 'en-US'
        else:
            stt_lang = LANG_BCP47.get(source_lang, 'en-US')
        
        recognition_config = speech.RecognitionConfig(
            encoding=encoding,
            language_code=stt_lang,
            enable_automatic_punctuation=True,
            model='latest_long'
        )
        
        audio = speech.RecognitionAudio(content=audio_content)
        
        stt_response = speech_client.recognize(config=recognition_config, audio=audio)
        
        # Extract transcription
        original_text = ''
        for result in stt_response.results:
            original_text += result.alternatives[0].transcript + ' '
        original_text = original_text.strip()
        
        if not original_text:
            return jsonify({
                'error': 'Could not transcribe audio. Please speak clearly and try again.',
                'status': 'stt_failed'
            }), 400
        
        # Step 2: Translate text
        if use_ai:
            # Use Gemini AI for natural translation (Premium)
            translated_text = translate_with_gemini(original_text, source_lang, target_lang)
            translation_mode = 'ai'
        else:
            # Use Google Cloud Translation API (default)
            translated_text, _ = translate_with_google(original_text, source_lang, target_lang)
            translation_mode = 'standard'
        
        # Step 3: Text-to-Speech
        tts_client = get_tts_client()
        
        voice_config = TTS_VOICE_MAP.get(target_lang, TTS_VOICE_MAP['en'])
        
        synthesis_input = tts.SynthesisInput(text=translated_text)
        voice = tts.VoiceSelectionParams(
            language_code=voice_config['language_code'],
            name=voice_config['name']
        )
        audio_config = tts.AudioConfig(
            audio_encoding=tts.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0
        )
        
        tts_response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # Encode audio to base64
        audio_base64 = base64.b64encode(tts_response.audio_content).decode('utf-8')
        
        return jsonify({
            'status': 'success',
            'original_text': original_text,
            'translated_text': translated_text,
            'audio_base64': audio_base64,
            'audio_format': 'mp3',
            'source_lang': source_lang,
            'target_lang': target_lang,
            'mode': translation_mode
        })
        
    except Exception as e:
        print(f"Audio Translation Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================
# Real-time Translation Status Check
# ============================================
@translate_bp.route('/translate/live/check', methods=['GET'])
@login_required
def check_realtime_access():
    """
    Check if user has access to real-time translation
    Returns premium status and WebSocket endpoint info
    """
    # FIXED: Use is_premium_active (dynamic check for subscriptions)
    has_access = current_user.is_premium_active
    
    return jsonify({
        'has_access': has_access,
        'user_id': current_user.id,
        'websocket_endpoint': '/socket.io/' if has_access else None,
        'message': 'Premium access granted' if has_access else 'Upgrade to Premium for real-time translation'
    })


# ============================================
# Language List API
# ============================================
@translate_bp.route('/translate/languages', methods=['GET'])
def get_languages():
    """Get list of supported languages"""
    languages = [
        {'code': code, 'name': name}
        for code, name in LANG_NAME.items()
    ]
    return jsonify({
        'status': 'success',
        'languages': languages
    })