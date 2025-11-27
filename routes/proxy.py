# routes/proxy.py
from flask import Blueprint, request, Response
import requests
import config

proxy_bp = Blueprint('proxy', __name__)

@proxy_bp.route('/proxy_image')
def proxy_image():
    photo_reference = request.args.get('ref')
    if not photo_reference:
        return "Missing photo reference", 400

    # 1. 构造 URL
    google_url = f"https://places.googleapis.com/v1/{photo_reference}/media?maxWidthPx=400&key={config.GOOGLE_MAPS_API_KEY}"

    # 2. 发起请求 (注意：这里一定要赋值给 r)
    # stream=True 是为了不把整个图片读进内存，而是直接转发
    try:
        r = requests.get(google_url, stream=True, timeout=10)

        # ✅ 调试日志
        print(f"--- [Proxy] Requesting: {google_url[:60]}... ---") # 只打印前60个字符避免泄露 Key
        print("Status:", r.status_code)
        print("Content-Type:", r.headers.get("Content-Type"))

        # 3. 检查 Google 是否返回错误
        if r.status_code != 200:
            # 只有出错时才去读 text，否则会破坏图片流
            print("Google image error:", r.text[:200])
            return "Failed to fetch image", 500

        # 4. 返回图片流
        return Response(
            r.iter_content(chunk_size=1024),
            content_type=r.headers.get("Content-Type", "image/jpeg")
        )
    
    except Exception as e:
        print(f"Proxy Exception: {e}")
        return "Internal Server Error", 500