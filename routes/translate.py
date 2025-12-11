# routes/translate.py
from flask import Blueprint, request, jsonify
import google.generativeai as genai
import config

translate_bp = Blueprint('translate', __name__)

# 配置 Gemini
try:
    genai.configure(api_key=config.GEMINI_API_KEY)
except Exception as e:
    print(f"Gemini 配置警告: {e}")

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

@translate_bp.route('/translate', methods=['POST'])
def translate_api():
    try:
        data = request.json
        text = data.get('text', '')
        source_lang = data.get('source_lang', 'auto')
        target_lang = data.get('target_lang', 'en')

        if not text:
            return jsonify({'error': '没有提供文本'}), 400
        
        source_lang_name = LANG_NAME.get(source_lang, source_lang)
        target_lang_name = LANG_NAME.get(target_lang, target_lang)


        # 构建给 AI 的提示词
        prompt = f"""
            You are a native-level translator specialising in cultural localisation.

            Translate the following text from {source_lang_name} to {target_lang_name}.

            Requirements:
            - Keep the meaning accurate
            - Make the text sound natural, fluent, and local to native speakers
            - Adjust expressions to match cultural context and tone
            - If direct translation is awkward, rewrite it into a native-like phrasing

            Only output the translated text.

            Text:
            {text}
        """

        # 调用 Gemini 模型 (使用 Flash 模型速度较快)
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt)
        
        translated_text = response.text.strip()

        return jsonify({
            'status': 'success',
            'translation': translated_text
        })

    except Exception as e:
        print(f"Translation Error: {e}")
        return jsonify({'error': str(e)}), 500