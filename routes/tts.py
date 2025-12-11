# routes/tts.py
from flask import Blueprint, request, Response, jsonify
from gtts import gTTS
import io

tts_bp = Blueprint('tts', __name__)

@tts_bp.route('/tts', methods=['POST'])
def tts_api():
    try:
        data = request.json
        text = data.get('text', '')
        lang = data.get('lang', 'en')

        if not text:
            return jsonify({'error': 'No text provided'}), 400

        # 语言代码映射：前端传来的代码 -> gTTS 需要的代码
        # gTTS 使用 'zh-cn' 代表中文，'ms' 代表马来语
        lang_map = {
            'zh': 'zh-cn',
            'my': 'ms',
            'en': 'en',
            'ja': 'ja',
            'ko': 'ko',
            'es': 'es',
            'fr': 'fr',
            'de': 'de',
            'it': 'it'
        }
        # 如果不在映射里，就默认用原值，如果报错则回退到英语
        target_lang = lang_map.get(lang, lang)

        # 调用 Google TTS
        tts = gTTS(text=text, lang=target_lang)

        # 将音频写入内存文件，而不是保存到硬盘
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)

        # 直接返回音频流 (MIME type: audio/mpeg)
        return Response(fp.read(), mimetype='audio/mpeg')

    except Exception as e:
        print(f"TTS Error: {e}")
        return jsonify({'error': str(e)}), 500