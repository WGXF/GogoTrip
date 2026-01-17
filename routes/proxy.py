# routes/proxy.py
"""
Centralized Image Proxy for GogoTrip

ALL image logic is handled here. Frontend should ONLY call this endpoint.

Priority Order:
1. Database photo_reference (by place_id or google_place_id)
2. Google Places API (if we have a valid reference)
3. Default placeholder image (NEVER return 404)

Usage:
- /proxy_image?place_id=123           - Lookup by our DB ID
- /proxy_image?google_place_id=ChIJ...  - Lookup by Google Place ID
- /proxy_image?ref=AWU...             - Direct photo reference
- /proxy_image?name=Restaurant+Name   - Fuzzy search by name
"""

from flask import Blueprint, request, Response, send_file
import requests
import io
import config
from models import db, Place

proxy_bp = Blueprint('proxy', __name__)

# ============ Default Placeholder Image (SVG) ============
DEFAULT_PLACEHOLDER_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#f1f5f9"/>
      <stop offset="100%" style="stop-color:#e2e8f0"/>
    </linearGradient>
  </defs>
  <rect fill="url(#grad)" width="400" height="300"/>
  <circle cx="200" cy="120" r="40" fill="#cbd5e1"/>
  <rect x="160" y="170" width="80" height="60" rx="8" fill="#cbd5e1"/>
  <text x="200" y="260" text-anchor="middle" fill="#94a3b8" font-family="system-ui" font-size="14">Image unavailable</text>
</svg>'''

def serve_default_image():
    """Return default placeholder image - NEVER fails"""
    return Response(
        DEFAULT_PLACEHOLDER_SVG,
        mimetype='image/svg+xml',
        headers={'Cache-Control': 'public, max-age=86400'}  # Cache for 24h
    )


def fetch_from_google(photo_reference: str) -> Response:
    """
    Fetch image from Google Places API
    Returns the image response or None on failure
    """
    if not photo_reference:
        return None
    
    # Clean the reference if it contains full path
    if "photos/" in photo_reference:
        photo_reference = photo_reference.split("photos/")[-1]
    
    # Also handle "places/..." format
    if photo_reference.startswith("places/"):
        parts = photo_reference.split("/")
        if "photos" in parts:
            idx = parts.index("photos")
            if idx + 1 < len(parts):
                photo_reference = parts[idx + 1]
    
    google_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_reference}&key={config.GOOGLE_MAPS_API_KEY}"
    
    try:
        r = requests.get(google_url, stream=True, timeout=10)
        
        if r.status_code == 200:
            # Filter hop-by-hop headers
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            headers = [(name, value) for (name, value) in r.raw.headers.items()
                       if name.lower() not in excluded_headers]
            headers.append(('Cache-Control', 'public, max-age=604800'))  # Cache for 7 days
            
            return Response(
                r.iter_content(chunk_size=4096),
                status=200,
                headers=headers
            )
        else:
            print(f"--- [Proxy] Google API returned {r.status_code} for ref={photo_reference[:50]}... ---")
            return None
            
    except Exception as e:
        print(f"--- [Proxy] Google fetch error: {e} ---")
        return None


def search_google_places_for_photo(name: str) -> Response:
    """
    Search Google Places API by name and return the first photo found.
    Also caches the result in our database for future lookups.
    """
    if not name or not config.GOOGLE_MAPS_API_KEY:
        return None
    
    try:
        # Search for the place by name
        search_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            'input': name,
            'inputtype': 'textquery',
            'fields': 'place_id,name,photos,formatted_address,rating',
            'key': config.GOOGLE_MAPS_API_KEY
        }
        
        r = requests.get(search_url, params=params, timeout=10)
        if r.status_code != 200:
            print(f"--- [Proxy] Google Places search failed: {r.status_code} ---")
            return None
        
        data = r.json()
        candidates = data.get('candidates', [])
        
        if not candidates:
            print(f"--- [Proxy] No Google Places results for '{name}' ---")
            return None
        
        place_data = candidates[0]
        photos = place_data.get('photos', [])
        
        if not photos:
            print(f"--- [Proxy] Google Place found but no photos for '{name}' ---")
            return None
        
        photo_reference = photos[0].get('photo_reference')
        if not photo_reference:
            return None
        
        print(f"--- [Proxy] Found photo via Google search for '{name}' ---")
        
        # Cache this place in our database for future lookups
        try:
            google_place_id = place_data.get('place_id')
            if google_place_id:
                existing = Place.query.filter_by(google_place_id=google_place_id).first()
                if not existing:
                    new_place = Place(
                        google_place_id=google_place_id,
                        name=place_data.get('name', name),
                        address=place_data.get('formatted_address', ''),
                        rating=place_data.get('rating'),
                        photo_reference=photo_reference
                    )
                    db.session.add(new_place)
                    db.session.commit()
                    print(f"--- [Proxy] Cached new place: {name} (id={new_place.id}) ---")
        except Exception as cache_error:
            print(f"--- [Proxy] Failed to cache place: {cache_error} ---")
            db.session.rollback()
        
        # Fetch and return the photo
        return fetch_from_google(photo_reference)
        
    except Exception as e:
        print(f"--- [Proxy] Google Places search error: {e} ---")
        return None


def lookup_place_by_id(place_id: int) -> Place:
    """Lookup place by our internal DB ID"""
    try:
        return Place.query.get(place_id)
    except Exception as e:
        print(f"--- [Proxy] DB lookup error (place_id={place_id}): {e} ---")
        return None


def lookup_place_by_google_id(google_place_id: str) -> Place:
    """Lookup place by Google Place ID"""
    try:
        return Place.query.filter_by(google_place_id=google_place_id).first()
    except Exception as e:
        print(f"--- [Proxy] DB lookup error (google_place_id={google_place_id}): {e} ---")
        return None


def lookup_place_by_name(name: str) -> Place:
    """Fuzzy search place by name"""
    try:
        # Exact match first
        place = Place.query.filter(Place.name.ilike(name)).first()
        if place:
            return place
        
        # Partial match
        place = Place.query.filter(Place.name.ilike(f"%{name}%")).first()
        return place
    except Exception as e:
        print(f"--- [Proxy] DB lookup error (name={name}): {e} ---")
        return None


@proxy_bp.route('/proxy_image')
def proxy_image():
    """
    Unified image proxy endpoint
    
    Query Parameters:
    - place_id: Our internal database ID (highest priority for DB lookup)
    - google_place_id: Google's place ID (secondary DB lookup)
    - name: Place name for fuzzy search (tertiary DB lookup)
    - ref: Direct photo reference (bypasses DB, goes straight to Google API)
    
    Returns:
    - Image data (JPEG/PNG from Google, or SVG placeholder)
    - NEVER returns 404 or error status - always returns an image
    """
    place_id = request.args.get('place_id')
    google_place_id = request.args.get('google_place_id')
    name = request.args.get('name')
    ref = request.args.get('ref')
    
    photo_reference = None
    place = None
    
    # ============ Step 1: Try to get photo_reference from database ============
    
    # Priority 1: Lookup by our DB place_id
    if place_id:
        try:
            place = lookup_place_by_id(int(place_id))
            if place and place.photo_reference:
                photo_reference = place.photo_reference
                print(f"--- [Proxy] Found photo_reference from place_id={place_id} ---")
        except ValueError:
            pass
    
    # Priority 2: Lookup by Google Place ID
    if not photo_reference and google_place_id:
        place = lookup_place_by_google_id(google_place_id)
        if place and place.photo_reference:
            photo_reference = place.photo_reference
            print(f"--- [Proxy] Found photo_reference from google_place_id={google_place_id} ---")
    
    # Priority 3: Lookup by name (fuzzy)
    if not photo_reference and name:
        place = lookup_place_by_name(name)
        if place and place.photo_reference:
            photo_reference = place.photo_reference
            print(f"--- [Proxy] Found photo_reference from name={name} ---")
    
    # Priority 4: Direct ref parameter
    if not photo_reference and ref:
        photo_reference = ref
        print(f"--- [Proxy] Using direct ref parameter ---")
    
    # ============ Step 2: Try to fetch from Google API ============
    
    if photo_reference:
        google_response = fetch_from_google(photo_reference)
        if google_response:
            return google_response
        else:
            print(f"--- [Proxy] Google fetch failed, trying Places search ---")
    
    # ============ Step 3: Search Google Places API by name ============
    # If no photo_reference found in DB, try searching Google Places API
    
    if name:
        search_result = search_google_places_for_photo(name)
        if search_result:
            return search_result
    
    # ============ Step 4: Return default placeholder ============
    
    print(f"--- [Proxy] No image found, returning placeholder (place_id={place_id}, google_id={google_place_id}, name={name}) ---")
    return serve_default_image()


@proxy_bp.route('/proxy_image/default')
def get_default_image():
    """
    Endpoint to get the default placeholder image directly
    Useful for frontend fallback without complex logic
    """
    return serve_default_image()
