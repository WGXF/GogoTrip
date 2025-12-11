# routes/proxy.py
from flask import Blueprint, request, Response
import requests
import config

proxy_bp = Blueprint('proxy', __name__)

@proxy_bp.route('/proxy_image')
def proxy_image():
    # 1. 获取参数
    ref = request.args.get('ref')
    if not ref:
        return "Missing photo reference", 400

    # 2. [关键修复] 清理 photo_reference
    # 之前的错误是因为传入了类似 "places/ChIJ.../photos/AWn..." 的完整路径
    # 但我们需要的只是最后那串 ID (AWn...)
    if "photos/" in ref:
        ref = ref.split("photos/")[-1]

    # 3. [关键修复] 切换为 Google Maps "Legacy" API
    # 旧版 API (maps.googleapis.com) 对各种 ID 的兼容性最好
    # 参数名：maxwidth (小写), photo_reference
    google_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={ref}&key={config.GOOGLE_MAPS_API_KEY}"

    try:
        # 4. 发起请求
        # stream=True 是为了不把整个图片读进内存，而是直接转发
        r = requests.get(google_url, stream=True, timeout=15)

        # 5. 检查 Google 是否返回错误
        if r.status_code != 200:
            # 只有出错时才去读 text，否则会破坏图片流
            print(f"--- [Proxy Error] Google returned {r.status_code}: {r.text[:200]} ---")
            return "Failed to fetch image from Google", 502

        # 6. 处理响应头 (Header Proxy)
        # 我们不能直接把 Google 的所有 Header 都扔给前端，需要过滤掉一些 hop-by-hop headers
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in r.raw.headers.items()
                   if name.lower() not in excluded_headers]

        # 7. 返回图片流
        return Response(
            r.iter_content(chunk_size=4096),
            status=r.status_code,
            headers=headers
        )
    
    except Exception as e:
        print(f"Proxy Exception: {e}")
        return str(e), 500