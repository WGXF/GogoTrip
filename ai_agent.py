# ai_agent.py
"""
GogoTrip AI Agent - Intelligent Itinerary Planning Assistant (MVP Optimized)

Optimization Focus:
- Speed First: Reduce AI reasoning depth
- Simplified Workflow: Reduce tool calls
- Allow place_id to be null: Generate itinerary first, link data later
"""

import json
import datetime
import google.generativeai as genai
import sys
import logging
import re

import config
from tools import (
    get_ip_location_info,
    get_current_weather,
    search_nearby_places,
    get_coordinates_for_city,
    query_places_from_db
)

logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

LANGUAGE_FULL_NAMES = {
    'en': 'English',
    'zh': 'Chinese (Simplified)',
    'ms': 'Bahasa Melayu (Malay)'
}

# ============ Safe JSON Parser ============

def safe_json_loads(text: str):
    """
    Safe JSON Parser - Handles common AI model JSON errors

    Common Errors:
    - Trailing commas
    - Missing commas between array items
    - Missing commas between object properties
    - Markdown code blocks
    - Extra data after JSON (AI explanations)
    """
    cleaned = text.strip()

    # Remove markdown
    cleaned = cleaned.replace("```json", "").replace("```", "")

    # Detect if array or object
    array_start = cleaned.find("[")
    obj_start = cleaned.find("{")

    # Prioritize array (Fast Mode mostly returns array)
    if array_start != -1 and (obj_start == -1 or array_start < obj_start):
        # Array format - extract first complete array
        start = array_start
        end = cleaned.find("]", start)

        if end == -1:
            raise ValueError("No valid JSON array found")

        cleaned = cleaned[start:end + 1]
    elif obj_start != -1:
        # Object format - extract first complete object
        # Need to count {} to find correct end position
        start = obj_start
        count = 0
        end = -1

        for i in range(start, len(cleaned)):
            if cleaned[i] == '{':
                count += 1
            elif cleaned[i] == '}':
                count -= 1
                if count == 0:
                    end = i
                    break

        if end == -1:
            raise ValueError("No valid JSON object found")

        cleaned = cleaned[start:end + 1]
    else:
        raise ValueError("No JSON found in text")

    # Prevent trailing commas
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    return json.loads(cleaned)


class LoggerWriter:
    def __init__(self, level):
        self.level = level
    def write(self, message):
        if message.strip():
            self.level(message)
    def flush(self):
        pass

sys.stdout = LoggerWriter(logging.info)
sys.stderr = LoggerWriter(logging.error)

print("--- App log enabled, now writing to app.log ---")


# ============================================================================
# JSON SCHEMA BUILDERS - Single Source of Truth
# ============================================================================
# These functions build final JSON from AI decisions
# This ensures JSON is ALWAYS valid and structure is centralized

def parse_budget_string(budget_str: str) -> float:
    """
    Parse budget string to float, handling various formats and currencies.

    Handles formats like:
    - "RM 50", "SGD 20", "USD 30", "JPY 1000"
    - "新市20" (Singapore Dollar in Chinese)
    - "$50", "¥100"
    - "50" (plain number)
    - "0 (Free)", "RM 0 (Free)", "Free"
    - "RM 20-30" (takes first number)
    - "20-30"

    Args:
        budget_str: Budget string from AI (can contain various currency symbols)

    Returns:
        Parsed float value (0.0 if parsing fails)
    """
    if not budget_str:
        return 0.0

    try:
        # Handle "Free" case
        if 'free' in budget_str.lower():
            return 0.0

        # Remove anything in parentheses (e.g., "(Free)")
        clean_str = budget_str
        if '(' in clean_str:
            clean_str = clean_str.split('(')[0].strip()

        # Remove common currency prefixes/symbols
        # Support: RM, SGD, USD, JPY, EUR, GBP, THB, PHP, IDR, CNY, HKD, TWD, etc.
        currency_patterns = [
            'RM', 'SGD', 'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'HKD', 'TWD',
            'THB', 'PHP', 'IDR', 'MYR', 'AUD', 'NZD', 'CAD', 'CHF',
            '新市',  # Singapore Dollar in Chinese
            '美元',  # US Dollar in Chinese
            '日元',  # Japanese Yen in Chinese
            '港币',  # Hong Kong Dollar in Chinese
            '$', '¥', '€', '£'  # Currency symbols
        ]

        for currency in currency_patterns:
            clean_str = clean_str.replace(currency, '')

        clean_str = clean_str.strip()

        # Handle ranges (e.g., "20-30" -> take first number)
        if '-' in clean_str and clean_str.count('-') == 1:
            # Check if it's a range, not a negative number
            parts = clean_str.split('-')
            if len(parts) == 2 and parts[0].strip():
                clean_str = parts[0].strip()

        # Remove any remaining non-numeric characters except decimal point
        # This handles cases like "20新市" or "20 "
        import re
        clean_str = re.sub(r'[^\d.]', '', clean_str)

        if not clean_str:
            return 0.0

        # Convert to float
        return float(clean_str)

    except (ValueError, AttributeError):
        return 0.0


def get_unsplash_image_url(query: str, width: int = 1200, fallback_id: str = None) -> str:
    """
    Generate Unsplash image URL from search query.

    Args:
        query: Search query (e.g., "Kuala Lumpur", "Petronas Towers")
        width: Image width (default 1200)
        fallback_id: Fallback photo ID if query is empty

    Returns:
        Unsplash image URL
    """
    if not query or query.strip() == '':
        # Use fallback ID or default
        photo_id = fallback_id or '1500000000000'
        return f'https://images.unsplash.com/photo-{photo_id}?w={width}&q=80'

    # Clean query for URL (remove special chars, spaces to hyphens)
    clean_query = query.strip().lower()
    clean_query = clean_query.replace(' ', '-').replace(',', '').replace('/', '-')

    # Use Unsplash Source API format (redirects to relevant image)
    return f'https://source.unsplash.com/{width}x{int(width * 0.6)}/?{clean_query}'


def get_destination_cover_image(destination: str, top_locations: list) -> str:
    """
    Derive cover image from destination and top locations.

    Strategy:
    1. Try to use first top location's name
    2. Fallback to destination name
    3. Fallback to preset images for common destinations

    Args:
        destination: Destination name from plan concept
        top_locations: List of top locations from day 1

    Returns:
        Cover image URL (Unsplash)
    """
    # Preset cover images for common destinations (high-quality photo IDs)
    DESTINATION_PRESETS = {
        'kuala lumpur': 'eCflE96eHdw',  # Petronas Towers
        'kl': 'eCflE96eHdw',
        'penang': 'WjU7tG0vjWE',  # Georgetown street art
        'langkawi': 'eO-RglrwKkQ',  # Beach and island
        'malacca': 'h-IrqGPjD1E',  # Historic building
        'melaka': 'h-IrqGPjD1E',
        'singapore': 'ZVprbBmT8QA',  # Marina Bay Sands
        'bangkok': 'sy3BLN2NZ0c',  # Temples
        'tokyo': 'URAq7qBiRfU',  # Shibuya crossing
        'osaka': 'ggYfR-kPbNU',  # Osaka castle
        'seoul': 'BuZj_K5eUPw',  # Seoul cityscape
        'taipei': 'Z6b2y31K12c',  # Taipei 101
        'hong kong': 'G7sE2S4Lab4',  # Hong Kong skyline
        'bali': 'VZ4zzGP2TIQ',  # Bali temple
        'phuket': 'eWkuEi26fyQ',  # Phuket beach
    }

    # Try to use first top location
    if top_locations and len(top_locations) > 0:
        first_location = top_locations[0].get('name', '')
        if first_location:
            # Check if location matches preset
            location_lower = first_location.lower()
            for key, photo_id in DESTINATION_PRESETS.items():
                if key in location_lower:
                    return f'https://images.unsplash.com/photo-{photo_id}?w=1200&q=80'

            # Use location name for search
            return get_unsplash_image_url(first_location, width=1200)

    # Fallback to destination
    if destination:
        destination_lower = destination.lower()

        # Check presets
        for key, photo_id in DESTINATION_PRESETS.items():
            if key in destination_lower:
                return f'https://images.unsplash.com/photo-{photo_id}?w=1200&q=80'

        # Use destination name for search
        return get_unsplash_image_url(destination, width=1200)

    # Ultimate fallback
    return 'https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1200&q=80'  # Generic travel


def build_daily_plan_json(decisions: dict, preferences: dict) -> dict:
    """
    Build daily plan JSON from AI decisions.

    Args:
        decisions: AI decision object with plan_concept, daily_decisions, etc.
        preferences: User preferences dict

    Returns:
        Complete daily plan JSON matching frontend schema
    """
    plan_concept = decisions.get('plan_concept', {})
    daily_decisions = decisions.get('daily_decisions', [])

    # Calculate total budget and detect currency
    total_budget_min = 0
    total_budget_max = 0
    detected_currency = "RM"  # Default to RM

    # Extract currency from first budget entry
    for day in daily_decisions:
        for place in day.get('selected_places', []):
            budget_str = place.get('budget', 'RM 0')

            # Detect currency symbol/code from the budget string
            if not detected_currency or detected_currency == "RM":
                import re
                # Try to extract currency prefix (e.g., "SGD", "USD", "新市")
                currency_match = re.match(r'^([A-Z]{3}|[¥$€£]|新市|美元|日元|港币)\s*', budget_str)
                if currency_match:
                    detected_currency = currency_match.group(1)

            amount = parse_budget_string(budget_str)
            total_budget_min += amount * 0.8
            total_budget_max += amount * 1.2

    total_budget_estimate = f"{detected_currency} {int(total_budget_min)} - {detected_currency} {int(total_budget_max)}"

    # Extract tags
    tags = []
    if preferences.get('mood'):
        tags.append(preferences['mood'])
    if preferences.get('budget'):
        tags.append(preferences['budget'])
    tags.extend(plan_concept.get('key_attractions', [])[:2])

    # Build days array
    days = []
    today = datetime.date.today()

    for idx, day_decision in enumerate(daily_decisions):
        day_date = (today + datetime.timedelta(days=idx)).isoformat()

        # Build activities from selected places
        activities = []
        current_time = datetime.time(9, 0)  # Start at 9 AM

        for place in day_decision.get('selected_places', []):
            duration_hours = place.get('duration_hours', 2)
            end_time_delta = datetime.timedelta(hours=duration_hours)

            # Convert time to datetime for calculation
            current_datetime = datetime.datetime.combine(today, current_time)
            end_datetime = current_datetime + end_time_delta

            # Determine time_slot
            hour = current_time.hour
            if hour < 12:
                time_slot = 'morning'
            elif hour < 14:
                time_slot = 'lunch'
            elif hour < 18:
                time_slot = 'afternoon'
            elif hour < 21:
                time_slot = 'evening'
            else:
                time_slot = 'night'

            activity = {
                'time_slot': time_slot,
                'start_time': current_time.strftime('%H:%M'),
                'end_time': end_datetime.time().strftime('%H:%M'),
                'place_id': None,  # Will be linked later
                'place_name': place.get('name', ''),
                'place_address': place.get('address', 'Address not specified'),
                'activity_type': place.get('activity_type', 'attraction'),
                'description': place.get('reason', ''),
                'budget_estimate': place.get('budget', 'RM 50'),
                'tips': place.get('tips', ''),
                'dietary_info': place.get('dietary_info', '')
            }
            activities.append(activity)

            # Move to next time slot
            current_time = (end_datetime + datetime.timedelta(minutes=30)).time()

        # Calculate day summary and detect currency for this day
        day_budget = sum(
            parse_budget_string(place.get('budget', 'RM 0'))
            for place in day_decision.get('selected_places', [])
        )

        # Detect currency from first budget in this day
        day_currency = "RM"  # Default
        for place in day_decision.get('selected_places', []):
            budget_str = place.get('budget', 'RM 0')
            import re
            currency_match = re.match(r'^([A-Z]{3}|[¥$€£]|新市|美元|日元|港币)\s*', budget_str)
            if currency_match:
                day_currency = currency_match.group(1)
                break

        # Build top_locations with derived images
        top_locations = []
        for place in day_decision.get('selected_places', [])[:3]:
            place_name = place.get('name', '')
            top_locations.append({
                'place_id': None,
                'name': place_name,
                'image_url': get_unsplash_image_url(place_name, width=800),
                'highlight_reason': place.get('reason', '')
            })

        day = {
            'day_number': idx + 1,
            'date': day_date,
            'theme': day_decision.get('theme', f'Day {idx + 1}'),
            'top_locations': top_locations,
            'activities': activities,
            'day_summary': {
                'total_activities': len(activities),
                'total_budget': f'{day_currency} {int(day_budget)}',
                'transport_notes': day_decision.get('transport_notes', 'Use public transport or Grab')
            }
        }
        days.append(day)

    # Derive cover image from destination and top locations
    destination = plan_concept.get('title', 'Travel Itinerary')
    first_day_top_locations = days[0]['top_locations'] if days else []
    cover_image = get_destination_cover_image(destination, first_day_top_locations)

    # Build final JSON
    return {
        'type': 'daily_plan',
        'title': destination,
        'description': plan_concept.get('theme', 'Exciting travel adventure'),
        'duration': f"{len(daily_decisions)}D{len(daily_decisions)-1}N" if len(daily_decisions) > 1 else '1D',
        'total_budget_estimate': total_budget_estimate,
        'tags': tags[:5],
        'cover_image': cover_image,
        'user_preferences_applied': {
            'mood': preferences.get('mood', 'relaxed'),
            'budget': preferences.get('budget', 'medium'),
            'transport': preferences.get('transport', 'public'),
            'dietary': preferences.get('dietary', [])
        },
        'days': days,
        'practical_info': {
            'best_transport': decisions.get('transport_recommendation', 'Public transport recommended'),
            'weather_advisory': decisions.get('weather_advisory', 'Check weather before departure'),
            'booking_recommendations': decisions.get('practical_tips', [])
        }
    }


def build_food_recommendations_json(decisions: dict, preferences: dict) -> dict:
    """
    Build food recommendations JSON from AI decisions.

    Args:
        decisions: AI decision object with recommendations list
        preferences: User preferences dict

    Returns:
        Complete food recommendations JSON matching frontend schema
    """
    recommendations = []

    for rec in decisions.get('recommendations', []):
        # Map price estimate to price level
        price_str = rec.get('price_estimate', 'RM 20')
        price = parse_budget_string(price_str)
        if price < 15:
            price_level = 1
        elif price < 40:
            price_level = 2
        elif price < 80:
            price_level = 3
        else:
            price_level = 4

        # Extract dietary tags
        dietary_tags = []
        if preferences.get('dietary'):
            dietary_tags = preferences['dietary']

        recommendation = {
            'name': rec.get('name', 'Restaurant'),
            'cuisine_type': rec.get('cuisine_type', 'Various'),
            'address': rec.get('address', 'Address not available'),
            'rating': rec.get('rating', 4.0),
            'price_level': price_level,
            'description': rec.get('reason_to_visit', ''),
            'dietary_tags': dietary_tags,
            'is_open_now': rec.get('is_open_now', True),
            'signature_dishes': rec.get('signature_dishes', [rec.get('signature_dish_suggestion', 'Special dish')]),
            'tips': rec.get('tips', ''),
            'distance': rec.get('distance', '1km')
        }
        recommendations.append(recommendation)

    return {
        'success': True,
        'recommendations': recommendations,
        'preferences_applied': {
            'cuisine': preferences.get('cuisine', []),
            'mood': preferences.get('mood', 'casual'),
            'budget': preferences.get('budget', 'medium'),
            'dietary': preferences.get('dietary', []),
            'meal_type': preferences.get('mealType', 'lunch')
        },
        'general_tips': decisions.get('general_tips', [])
    }


def build_activity_edit_json(decisions: dict) -> dict:
    """
    Build activity edit JSON from AI decisions.

    Args:
        decisions: AI decision object with updated_activities list

    Returns:
        Activity edit JSON matching frontend schema
    """
    if decisions.get('success') == False:
        return {
            'success': False,
            'error': decisions.get('error', 'Unknown error')
        }

    updated_activities = []
    for activity_decision in decisions.get('updated_activities', []):
        activity = {
            'day_index': activity_decision.get('day_index', 0),
            'activity_index': activity_decision.get('activity_index', 0),
            'activity': activity_decision.get('activity', {})
        }
        updated_activities.append(activity)

    return {
        'success': True,
        'updated_activities': updated_activities
    }


# ============================================================================
# NEW DECISION-BASED AI FUNCTIONS
# ============================================================================
# AI makes decisions only, backend builds JSON

def get_itinerary_decisions(destination: str, duration: str, preferences: dict, language: str = 'en') -> dict:
    """
    Get AI decisions for itinerary (decisions only, NO JSON structure).

    Args:
        destination: Travel destination
        duration: Trip duration (e.g., "3D2N", "7D6N")
        preferences: User preferences dict
        language: User's preferred language

    Returns:
        Decision object with plan_concept, daily_decisions, tips
        OR error dict if duration exceeds limit
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)

        # Extract number of days from duration string (e.g., "14D13N" -> 14)
        import re
        duration_match = re.search(r'(\d+)D', duration)
        num_days = int(duration_match.group(1)) if duration_match else 3

        # Limit maximum trip duration to 7 days
        MAX_DAYS = 7
        if num_days > MAX_DAYS:
            return {
                'error': 'duration_too_long',
                'requested_days': num_days,
                'max_days': MAX_DAYS,
                'message': f'Trip duration ({num_days} days) exceeds maximum supported length ({MAX_DAYS} days). Please plan shorter trips or split into multiple segments.'
            }

        today_date = datetime.date.today().isoformat()

        # Extract preferences
        mood = preferences.get('mood', 'relaxed')
        budget = preferences.get('budget', 'medium')
        transport = preferences.get('transport', 'public')
        dietary = preferences.get('dietary', [])
        companions = preferences.get('companions', 'friends')

        # Determine activities per day based on mood
        activities_per_day = "3-4" if mood in ['relaxed', 'family'] else "5-6"

        decision_prompt = f"""{get_language_instruction(language)}

Generate travel planning decisions for a {duration} trip to {destination}.

USER PREFERENCES:
- Mood: {mood} ({activities_per_day} activities per day)
- Budget: {budget}
- Transport: {transport}
- Dietary: {', '.join(dietary) if dietary else 'No restrictions'}
- Traveling with: {companions}

YOUR ROLE: Make decisions about:
1. Which places to visit
2. Order and grouping of activities
3. Themes for each day
4. Budget estimates
5. Practical tips

*** IMPORTANT: DO NOT generate conversational introductions ***
Do NOT say things like "I've created a plan for you" or "Here's your itinerary".
ONLY return the decision JSON object. NO conversational text.

Return DECISION OBJECT (NOT final UI JSON):
{{
  "plan_concept": {{
    "title": "Trip title in user's language",
    "theme": "Overall theme/concept",
    "key_attractions": ["Main attraction 1", "Main attraction 2"]
  }},
  "daily_decisions": [
    {{
      "day": 1,
      "theme": "Day theme in user's language",
      "selected_places": [
        {{
          "name": "Place Name",
          "address": "Full address",
          "reason": "Why visit this place",
          "activity_type": "attraction|food|cafe|shopping",
          "time_suggestion": "morning|afternoon|evening",
          "duration_hours": 2.0,
          "budget": "RM 30",
          "tips": "Optional tips",
          "dietary_info": "If food-related"
        }}
      ],
      "transport_notes": "How to get around today"
    }}
  ],
  "transport_recommendation": "Best overall transport method",
  "weather_advisory": "Weather tips for this season",
  "practical_tips": ["Tip 1", "Tip 2"]
}}

CRITICAL JSON RULES:
- Use DOUBLE QUOTES only
- Do NOT include comments
- Do NOT use emojis in JSON values
- Every comma must be correctly placed
- No trailing commas before }} or ]
- Validate JSON before returning
"""

        # Adjust max_output_tokens based on trip length
        max_tokens = 4096 if num_days <= 3 else 6144 if num_days <= 5 else 8192

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash',
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": max_tokens
            }
        )

        response = model.generate_content(decision_prompt)

        if response.candidates and response.candidates[0].content.parts:
            ai_text = response.candidates[0].content.parts[0].text.strip()

            try:
                decisions = safe_json_loads(ai_text)
                print(f"--- [Itinerary Decisions] Success for {destination} ---")
                return decisions
            except Exception as e:
                # Retry once
                print(f"--- [Itinerary Decisions] JSON invalid, retrying... Error: {e} ---")
                try:
                    retry_response = model.generate_content(decision_prompt)
                    retry_text = retry_response.candidates[0].content.parts[0].text.strip()
                    decisions = safe_json_loads(retry_text)
                    print(f"--- [Itinerary Decisions] Retry success ---")
                    return decisions
                except Exception as retry_error:
                    print(f"--- [Itinerary Decisions] Retry failed: {retry_error} ---")
                    return None

        return None

    except Exception as e:
        print(f"--- [Itinerary Decisions Error] {e} ---")
        return None


def get_food_decisions(preferences: dict, location: str = None, language: str = 'en') -> dict:
    """
    Get AI decisions for food recommendations (decisions only, NO JSON structure).

    Args:
        preferences: User preferences dict
        location: User location
        language: User's preferred language

    Returns:
        Decision object with recommendations list
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)

        # Extract preferences
        cuisine = preferences.get('cuisine', [])
        mood = preferences.get('mood', 'casual')
        budget = preferences.get('budget', 'medium')
        dietary = preferences.get('dietary', [])
        meal_type = preferences.get('mealType', 'lunch')
        distance = preferences.get('distance', '5')

        # Map budget to price range
        budget_map = {
            'low': 'under RM 15 per person',
            'medium': 'RM 15-40 per person',
            'high': 'RM 40-80 per person',
            'luxury': 'RM 80+ per person (fine dining)'
        }
        budget_desc = budget_map.get(budget, 'RM 15-40 per person')

        # Map mood to dining style
        mood_map = {
            'quick': 'fast casual, quick service, takeaway-friendly',
            'casual': 'relaxed atmosphere, comfortable seating',
            'romantic': 'intimate setting, good ambiance, date-worthy',
            'group': 'spacious, good for groups, shareable dishes'
        }
        mood_desc = mood_map.get(mood, 'casual dining')

        location_context = f"near {location}" if location else "in Malaysia"
        cuisine_context = f"focusing on {', '.join(cuisine)} cuisine" if cuisine else "any cuisine type"
        dietary_context = f"MUST be {', '.join(dietary)}" if dietary else "no dietary restrictions"

        food_decision_prompt = f"""{get_language_instruction(language)}

You are a local food expert. Make decisions about which restaurants to recommend.

USER PREFERENCES:
- Meal: {meal_type}
- Vibe: {mood_desc}
- Budget: {budget_desc}
- Cuisine: {cuisine_context}
- Dietary: {dietary_context}
- Location: {location_context}
- Max distance: {distance}km

YOUR ROLE: Decide which 5-8 restaurants match the user's preferences and explain why.

*** IMPORTANT: DO NOT generate conversational introductions ***
Do NOT say things like "I found X restaurants for you" or "Here are my recommendations".
ONLY return the decision JSON object. NO conversational text.

Return DECISION OBJECT (NOT final UI JSON):
{{
  "recommendations": [
    {{
      "name": "Restaurant Name",
      "cuisine_type": "Chinese/Japanese/Malay/Western/etc",
      "address": "Full address",
      "rating": 4.5,
      "price_estimate": "RM 20-40",
      "reason_to_visit": "Why this matches user's preferences (2-3 sentences)",
      "is_open_now": true,
      "signature_dish_suggestion": "Best dish to order",
      "signature_dishes": ["Dish 1", "Dish 2"],
      "tips": "Best time to visit or ordering tips",
      "distance": "1.2km"
    }}
  ],
  "general_tips": ["Tip 1", "Tip 2"]
}}

RULES:
1. Use REAL restaurant names that exist in Malaysia/the specified location
2. Match the user's budget strictly
3. If dietary restrictions specified, ONLY include compliant restaurants
4. Sort by relevance to user's mood/preferences

CRITICAL JSON RULES:
- Use DOUBLE QUOTES only
- Do NOT include comments
- Do NOT use emojis in JSON values
- Every comma must be correctly placed
- No trailing commas
- Validate JSON before returning
"""

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash',
            generation_config={
                "temperature": 0.4,
                "max_output_tokens": 2048
            }
        )

        response = model.generate_content(food_decision_prompt)

        if response.candidates and response.candidates[0].content.parts:
            ai_text = response.candidates[0].content.parts[0].text.strip()

            try:
                decisions = safe_json_loads(ai_text)
                if isinstance(decisions.get('recommendations'), list):
                    print(f"--- [Food Decisions] Generated {len(decisions['recommendations'])} recommendations ---")
                    return decisions
            except Exception as e:
                # Retry once
                print(f"--- [Food Decisions] JSON invalid, retrying... Error: {e} ---")
                try:
                    retry_response = model.generate_content(food_decision_prompt)
                    retry_text = retry_response.candidates[0].content.parts[0].text.strip()
                    decisions = safe_json_loads(retry_text)
                    print(f"--- [Food Decisions] Retry success ---")
                    return decisions
                except Exception as retry_error:
                    print(f"--- [Food Decisions] Retry failed: {retry_error} ---")
                    return None

        return None

    except Exception as e:
        print(f"--- [Food Decisions Error] {e} ---")
        return None


def get_activity_edit_decisions(activities: list, instructions: str, plan_context: dict = None, language: str = 'en') -> dict:
    """
    Get AI decisions for activity edits (decisions only, NO JSON structure).

    Args:
        activities: Activities to edit
        instructions: User's edit instructions
        plan_context: Plan context (optional)
        language: User's preferred language

    Returns:
        Decision object with updated_activities list
    """
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)

        # Build context string
        context_str = ""
        if plan_context:
            context_str = f"""
Trip Context:
- Title: {plan_context.get('title', 'N/A')}
- Destination: {plan_context.get('destination', 'N/A')}
- User Preferences: {json.dumps(plan_context.get('preferences', {}), ensure_ascii=False)}
"""

        # Format activities for the prompt
        activities_json = json.dumps(activities, ensure_ascii=False, indent=2)

        edit_decision_prompt = f"""{get_language_instruction(language)}

You are a travel itinerary editor. The user has selected activities and wants you to modify them according to their instructions.

{context_str}

## Selected Activities:
```json
{activities_json}
```

## User Instructions:
{instructions}

## YOUR TASK:
Modify these activities according to the user's instructions.

*** IMPORTANT: DO NOT generate conversational introductions ***
Do NOT say things like "I've updated the activities" or "Here are the changes".
ONLY return the decision JSON object. NO conversational text.

Return DECISION OBJECT (NOT final UI JSON):
{{
  "updated_activities": [
    {{
      "day_index": 0,
      "activity_index": 1,
      "activity": {{
        "time_slot": "morning",
        "start_time": "09:00",
        "end_time": "11:00",
        "place_id": null,
        "place_name": "Place Name",
        "place_address": "Address",
        "activity_type": "attraction",
        "description": "Description in user's language",
        "budget_estimate": "RM 50",
        "tips": "Tips in user's language",
        "dietary_info": "Dietary info if applicable"
      }}
    }}
  ]
}}

IMPORTANT RULES:
1. Keep JSON structure identical
2. Preserve day_index and activity_index fields
3. Only modify what user requested
4. Keep other fields unchanged unless explicitly requested
5. If time changes needed, use "HH:MM" format
6. If place changes needed, use real place names

CRITICAL JSON RULES:
- Use DOUBLE QUOTES only
- Do NOT include comments
- Do NOT use emojis in JSON values
- Every comma must be correctly placed
- No trailing commas
- Validate JSON before returning
"""

        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash',
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 4096
            }
        )

        response = model.generate_content(edit_decision_prompt)

        if response.candidates and response.candidates[0].content.parts:
            ai_text = response.candidates[0].content.parts[0].text.strip()

            try:
                decisions = safe_json_loads(ai_text)
                if isinstance(decisions.get('updated_activities'), list):
                    print(f"--- [Activity Edit Decisions] Modified {len(decisions['updated_activities'])} activities ---")
                    return {'success': True, 'updated_activities': decisions['updated_activities']}
            except Exception as e:
                # Retry once
                print(f"--- [Activity Edit Decisions] JSON invalid, retrying... Error: {e} ---")
                try:
                    retry_response = model.generate_content(edit_decision_prompt)
                    retry_text = retry_response.candidates[0].content.parts[0].text.strip()
                    decisions = safe_json_loads(retry_text)
                    print(f"--- [Activity Edit Decisions] Retry success ---")
                    return {'success': True, 'updated_activities': decisions['updated_activities']}
                except Exception as retry_error:
                    print(f"--- [Activity Edit Decisions] Retry failed: {retry_error} ---")
                    return {'success': False, 'error': 'AI failed to generate valid edits'}

        return {'success': False, 'error': 'No response from AI'}

    except Exception as e:
        print(f"--- [Activity Edit Decisions Error] {e} ---")
        return {'success': False, 'error': str(e)}


# ============ FAST MODE: Simplified itinerary generation ============
def get_fast_itinerary_response(destination: str, duration: str, preferences: dict, language: str = 'en'):
    """
    ✅ REFACTORED: Now uses decision-based architecture

    AI generates decisions → Backend builds JSON → Always valid

    Args:
        destination: Travel destination
        duration: Trip duration (e.g., "3D2N", "14D13N")
        preferences: User preferences dict
        language: User's preferred language

    Returns:
        DAILY_PLAN:: prefix + JSON string (for backwards compatibility)
        OR error message string if duration exceeds limit
    """
    try:
        # Get AI decisions
        decisions = get_itinerary_decisions(destination, duration, preferences, language)

        if not decisions:
            print("--- [Fast Mode] AI decisions failed ---")
            return None

        # Check if error was returned (duration too long)
        if decisions.get('error') == 'duration_too_long':
            error_messages = {
                'en': f"I can plan trips up to {decisions['max_days']} days. Your {decisions['requested_days']}-day trip is too long. Please try a shorter duration (e.g., '7-day trip to {destination}') or split it into multiple trips.",
                'zh': f"我最多可以规划{decisions['max_days']}天的行程。您请求的{decisions['requested_days']}天行程太长了。请尝试更短的时长（例如：'{destination} 7天之旅'）或分成多个行程。",
                'ms': f"Saya boleh merancang perjalanan sehingga {decisions['max_days']} hari. Perjalanan {decisions['requested_days']} hari anda terlalu panjang. Sila cuba tempoh yang lebih pendek (contoh: 'perjalanan 7 hari ke {destination}') atau bahagikan kepada beberapa perjalanan."
            }
            return error_messages.get(language, error_messages['en'])

        # Build final JSON from decisions
        final_json = build_daily_plan_json(decisions, preferences)

        print("--- [Fast Mode] Successfully generated itinerary with new architecture ---")
        return f"DAILY_PLAN::{json.dumps(final_json)}"

    except Exception as e:
        print(f"--- [Fast Mode Error] {e} ---")
        return None


# ============ Fast Food Recommendations ============

def get_fast_food_recommendations(preferences: dict, location: str = None, language: str = 'en'):
    """
    ✅ REFACTORED: Now uses decision-based architecture

    AI generates decisions → Backend builds JSON → Always valid

    Args:
        preferences: User preferences dict
        location: User location
        language: User's preferred language

    Returns:
        Food recommendations JSON (for backwards compatibility)
    """
    try:
        # Get AI decisions
        decisions = get_food_decisions(preferences, location, language)

        if not decisions:
            print("--- [Food Recommendations] AI decisions failed ---")
            return {
                "success": False,
                "error": "AI failed to generate recommendations"
            }

        # Build final JSON from decisions
        final_json = build_food_recommendations_json(decisions, preferences)

        print("--- [Food Recommendations] Successfully generated with new architecture ---")
        return final_json

    except Exception as e:
        print(f"--- [Food Recommendations Error] {e} ---")
        return {
            "success": False,
            "error": str(e)
        }


def edit_activities_with_ai(activities: list, instructions: str, plan_context: dict = None, language: str = 'en'):
    """
    ✅ REFACTORED: Now uses decision-based architecture

    AI generates decisions → Backend builds JSON → Always valid

    Args:
        activities: Activities to edit
        instructions: User's edit instructions
        plan_context: Plan context (optional)
        language: User's preferred language

    Returns:
        Activity edit JSON (for backwards compatibility)
    """
    try:
        # Get AI decisions
        decisions = get_activity_edit_decisions(activities, instructions, plan_context, language)

        # Build final JSON from decisions
        final_json = build_activity_edit_json(decisions)

        if final_json.get('success'):
            print(f"--- [Activity Edit] Successfully edited {len(final_json['updated_activities'])} activities with new architecture ---")
        else:
            print(f"--- [Activity Edit] Failed: {final_json.get('error')} ---")

        return final_json

    except Exception as e:
        print(f"--- [Activity Edit Error] {e} ---")
        return {
            'success': False,
            'error': str(e)
        }


def get_language_instruction(language: str) -> str:
    """
    Returns standardized language instruction for ALL AI prompts.
    Ensures consistent language enforcement across all AI functions.

    Args:
        language: Language code ('en', 'zh', 'ms')

    Returns:
        Language instruction string to prepend to AI prompts
    """
    response_language = LANGUAGE_FULL_NAMES.get(language, 'English')

    return f"""*** CRITICAL: RESPONSE LANGUAGE ***
You MUST respond in {response_language}. ALL text content MUST be written in {response_language}.
- If "English": respond in English
- If "Chinese (Simplified)": respond in 简体中文
- If "Bahasa Melayu (Malay)": respond in Bahasa Melayu

This is NON-NEGOTIABLE. The user has selected {response_language} as their preferred language.
Do NOT auto-detect or switch languages based on user input - always use {response_language}.
Even if the user asks in a different language, reply in {response_language}."""


def get_system_message(message_type: str, language: str = 'en', **kwargs) -> str:
    """
    Returns standardized system messages in the correct language.

    Args:
        message_type: Type of system message (itineraryGenerated, foodRecommendations, etc.)
        language: Language code ('en', 'zh', 'ms')
        **kwargs: Parameters to interpolate (e.g., destination, duration, count)

    Returns:
        Translated system message string
    """
    SYSTEM_MESSAGES = {
        'en': {
            'itineraryGenerated': "I've created a {duration} itinerary for {destination}. Check out the detailed plan below!",
            'foodRecommendations': "I found {count} great {mealType} options for you. Take a look below!",
            'placeRecommendations': "I found {count} places that match your request. Check them out below!",
            'activityEdited': "Successfully updated {count} activities based on your instructions.",
            'generalResponse': "Here's what I found for you:"
        },
        'zh': {
            'itineraryGenerated': "我已经为您创建了{destination}的{duration}行程。请查看下面的详细计划！",
            'foodRecommendations': "我为您找到了{count}个很棒的{mealType}选择。快来看看吧！",
            'placeRecommendations': "我找到了{count}个符合您要求的地点。请查看下面的内容！",
            'activityEdited': "已根据您的指示成功更新{count}个活动。",
            'generalResponse': "这是我为您找到的内容："
        },
        'ms': {
            'itineraryGenerated': "Saya telah membuat jadual {duration} untuk {destination}. Lihat pelan terperinci di bawah!",
            'foodRecommendations': "Saya jumpa {count} pilihan {mealType} yang hebat untuk anda. Lihat di bawah!",
            'placeRecommendations': "Saya jumpa {count} tempat yang sesuai dengan permintaan anda. Semak di bawah!",
            'activityEdited': "Berjaya mengemas kini {count} aktiviti berdasarkan arahan anda.",
            'generalResponse': "Inilah yang saya jumpa untuk anda:"
        }
    }

    # Get the message template for the language
    messages = SYSTEM_MESSAGES.get(language, SYSTEM_MESSAGES['en'])
    template = messages.get(message_type, messages.get('generalResponse', ''))

    # Interpolate parameters
    try:
        return template.format(**kwargs)
    except KeyError:
        # If interpolation fails, return template as-is
        return template

def extract_destination_from_message(message: str) -> str:
    """Extract destination from message - simple heuristic"""
    # Common Malaysia/Southeast Asia cities
    cities = [
        'kuala lumpur', 'kl', '吉隆坡', 'penang', '槟城', 'langkawi', '兰卡威',
        'malacca', 'melaka', '马六甲', 'johor bahru', 'jb', '新山',
        'ipoh', '怡保', 'cameron highlands', '金马伦', 'genting', '云顶',
        'singapore', '新加坡', 'bangkok', '曼谷', 'bali', '巴厘岛',
        'tokyo', '东京', 'osaka', '大阪', 'seoul', '首尔', 'taipei', '台北',
        'hong kong', '香港', 'macau', '澳门', 'vietnam', '越南', 'hanoi', '河内',
        'ho chi minh', '胡志明', 'phuket', '普吉岛', 'krabi', '甲米'
    ]
    
    msg_lower = message.lower()
    
    for city in cities:
        if city in msg_lower:
            # Return proper case
            city_map = {
                'kuala lumpur': 'Kuala Lumpur', 'kl': 'Kuala Lumpur', '吉隆坡': 'Kuala Lumpur',
                'penang': 'Penang', '槟城': 'Penang',
                'langkawi': 'Langkawi', '兰卡威': 'Langkawi',
                'malacca': 'Melaka', 'melaka': 'Melaka', '马六甲': 'Melaka',
                'johor bahru': 'Johor Bahru', 'jb': 'Johor Bahru', '新山': 'Johor Bahru',
                'ipoh': 'Ipoh', '怡保': 'Ipoh',
                'cameron highlands': 'Cameron Highlands', '金马伦': 'Cameron Highlands',
                'genting': 'Genting Highlands', '云顶': 'Genting Highlands',
                'singapore': 'Singapore', '新加坡': 'Singapore',
                'bangkok': 'Bangkok', '曼谷': 'Bangkok',
                'bali': 'Bali', '巴厘岛': 'Bali',
                'tokyo': 'Tokyo', '东京': 'Tokyo',
                'osaka': 'Osaka', '大阪': 'Osaka',
                'seoul': 'Seoul', '首尔': 'Seoul',
                'taipei': 'Taipei', '台北': 'Taipei',
                'hong kong': 'Hong Kong', '香港': 'Hong Kong',
                'macau': 'Macau', '澳门': 'Macau',
                'vietnam': 'Vietnam', '越南': 'Vietnam',
                'hanoi': 'Hanoi', '河内': 'Hanoi',
                'ho chi minh': 'Ho Chi Minh City', '胡志明': 'Ho Chi Minh City',
                'phuket': 'Phuket', '普吉岛': 'Phuket',
                'krabi': 'Krabi', '甲米': 'Krabi'
            }
            return city_map.get(city, city.title())
    
    # If no known city found, return empty (will fall back to standard mode)
    return ""


def extract_duration_from_message(message: str) -> str:
    """Extract trip duration from message"""
    msg_lower = message.lower()

    # Match week patterns first (1 week = 7 days, 2 weeks = 14 days)
    week_patterns = [
        r'(\d+)\s*weeks?',  # "1 week", "2 weeks"
        r'(\d+)\s*星期',    # Chinese: "1 星期"
        r'(\d+)\s*周',      # Chinese: "1 周"
        r'(\d+)\s*minggu',  # Malay: "1 minggu"
    ]

    for pattern in week_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            weeks = int(match.group(1))
            days = weeks * 7
            nights = days - 1
            return f"{days}D{nights}N"

    # Match day patterns like "3天", "3 days", "3天2夜"
    day_patterns = [
        r'(\d+)\s*天',  # 3 days (Chinese)
        r'(\d+)\s*days?',  # 3 days
        r'(\d+)\s*晚',  # 3 nights (Chinese)
        r'(\d+)\s*nights?',  # 3 nights
        r'(\d+)\s*hari',  # Malay: days
        r'(\d+)\s*malam',  # Malay: nights
    ]

    for pattern in day_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            num = int(match.group(1))
            return f"{num}D{num-1}N" if num > 1 else "1D"

    # Default
    return "3D2N"  # 3 days 2 nights


def extract_preferences_from_message(message: str) -> dict:
    """Extract user preferences from message"""
    msg_lower = message.lower()
    prefs = {
        'mood': 'relaxed',
        'budget': 'medium',
        'transport': 'public',
        'dietary': [],
        'companions': 'friends'
    }

    # Mood
    if any(w in msg_lower for w in ['relax', 'relaxed', 'leisure', 'slow pace', 'santai', 'tenang']):
        prefs['mood'] = 'relaxed'
    elif any(w in msg_lower for w in ['energetic', 'packed', 'full', 'active', 'bertenaga', 'aktif']):
        prefs['mood'] = 'energetic'
    elif any(w in msg_lower for w in ['romantic', 'romantic', 'couple', 'date', 'romantik']):
        prefs['mood'] = 'romantic'
    elif any(w in msg_lower for w in ['family', 'kids', 'children', 'keluarga']):
        prefs['mood'] = 'family'

    # Budget
    if any(w in msg_lower for w in ['budget', 'save', 'cheap', 'low budget', 'murah', 'bajet']):
        prefs['budget'] = 'low'
    elif any(w in msg_lower for w in ['luxury', 'upscale', 'premium', 'expensive', 'mewah']):
        prefs['budget'] = 'luxury'
    elif any(w in msg_lower for w in ['high', 'high budget', 'mahal']):
        prefs['budget'] = 'high'

    # Transport
    if any(w in msg_lower for w in ['walk', 'walking', 'on foot', 'jalan kaki', 'berjalan']):
        prefs['transport'] = 'walk'
    elif any(w in msg_lower for w in ['car', 'drive', 'car rental', 'kereta', 'memandu']):
        prefs['transport'] = 'car'

    # Dietary
    if any(w in msg_lower for w in ['halal']):
        prefs['dietary'].append('Halal')
    if any(w in msg_lower for w in ['vegetarian', 'veg']):
        prefs['dietary'].append('Vegetarian')
    if any(w in msg_lower for w in ['vegan']):
        prefs['dietary'].append('Vegan')
    if any(w in msg_lower for w in ['no pork', 'pork-free', 'tiada babi']):
        prefs['dietary'].append('No Pork')
    if any(w in msg_lower for w in ['no beef', 'beef-free', 'tiada daging lembu']):
        prefs['dietary'].append('No Beef')

    # Companions
    if any(w in msg_lower for w in ['solo', 'alone', 'by myself', 'sendiri', 'bersendirian']):
        prefs['companions'] = 'solo'
    elif any(w in msg_lower for w in ['couple', 'partner', 'spouse', 'pasangan']):
        prefs['companions'] = 'couple'
    elif any(w in msg_lower for w in ['family', 'kids', 'children', 'keluarga']):
        prefs['companions'] = 'family'
    elif any(w in msg_lower for w in ['friend', 'friends', 'colleagues', 'kawan', 'rakan']):
        prefs['companions'] = 'friends'
    
    return prefs


# Modified: Gemini tool definitions - Added new database query tools
tools_definition = [
    {
        "name": "search_nearby_places",
        "description": """
        Call when user asks for nearby place recommendations.
        This tool stores found places in database and returns place_ids.
        Then call query_places_from_db to get detailed information.
        """,
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Search keywords, e.g. 'restaurants', 'parks', 'museums'"
                },
                "location": {
                    "type": "STRING",
                    "description": "User location, preferably in 'latitude,longitude' format"
                }
            },
            "required": ["query", "location"]
        }
    },
    {
        "name": "query_places_from_db",
        "description": """
        Query place details from database.
        Usage 1: Pass place_ids (from search_nearby_places return value)
        Usage 2: Pass query_hint for fuzzy search
        Analyze these places and filter the best matching recommendations.
        If none match, explain why and call search_nearby_places with different keywords.
        """,
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "place_ids": {
                    "type": "ARRAY",
                    "description": "List of place IDs (from search_nearby_places)",
                    "items": {"type": "INTEGER"}
                },
                "query_hint": {
                    "type": "STRING",
                    "description": "Fuzzy search keywords (optional)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_coordinates_for_city",
        "description": "Call when user asks about a specific city to get coordinates first.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city_name": {
                    "type": "STRING",
                    "description": "City name to query coordinates for, e.g. 'Kuala Lumpur'"
                }
            },
            "required": ["city_name"]
        }
    },
    {
        "name": "get_current_weather",
        "description": "Call when user specifies a city name and asks about weather.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {
                    "type": "STRING",
                    "description": "City name"
                }
            },
            "required": ["city"]
        }
    },
    {
        "name": "get_weather_for_current_location",
        "description": "Call when user asks about local weather (no specific city mentioned).",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    }
]

def get_ai_chat_response(conversation_history, credentials_dict, coordinates=None, user_ip=None, language='en'):
    """
    AI Chat Agent - Optimized Version

    Optimization Strategy:
    1. Detect if request is itinerary planning -> Use Fast Mode (no tool calls)
    2. Other requests -> Use standard mode (with tool calls)

    Parameters:
    - language: User's preferred language (en, zh, ms), AI will respond in this language
    """
    try:
        # Get last user message
        last_user_message = ""
        for msg in reversed(conversation_history):
            if msg.get('role') == 'user':
                last_user_message = msg.get('parts', [''])[0] if msg.get('parts') else ''
                break

        last_msg_lower = last_user_message.lower()

        # ============ FAST MODE: Itinerary Planning Request ============
        # Detect keywords: plan, itinerary, trip, days, schedule, etc.
        itinerary_keywords = [
            'plan', 'itinerary', 'trip', 'days', 'schedule', 'travel plan',
            'day 1', 'day 2', 'day 3', 'day trip',
            'rancang', 'perjalanan', 'cuti', 'lawatan', 'hari'  # Malay keywords
        ]

        is_itinerary_request = any(kw in last_msg_lower for kw in itinerary_keywords)

        if is_itinerary_request:
            print("--- [Detected] Itinerary planning request, using Fast Mode ---")

            # Try to extract destination and preferences from message
            # Simple heuristic: find common city names or locations in message
            destination = extract_destination_from_message(last_user_message)
            duration = extract_duration_from_message(last_user_message)
            preferences = extract_preferences_from_message(last_user_message)

            if destination:
                fast_result = get_fast_itinerary_response(destination, duration, preferences, language=language)
                if fast_result:
                    return fast_result
                else:
                    # Fast Mode returned None (error occurred)
                    print("--- [Fast Mode] Failed to generate itinerary ---")
                    error_messages = {
                        'en': f"Sorry, I couldn't generate an itinerary for {destination}. Please try again with a different destination or shorter duration.",
                        'zh': f"抱歉，我无法为{destination}生成行程。请尝试使用不同的目的地或更短的时长。",
                        'ms': f"Maaf, saya tidak dapat menjana jadual perjalanan untuk {destination}. Sila cuba lagi dengan destinasi yang berbeza atau tempoh yang lebih pendek."
                    }
                    return error_messages.get(language, error_messages['en'])
            else:
                # No valid destination detected - warn user early
                print("--- [Fast Mode] No valid destination detected in message ---")
                invalid_dest_messages = {
                    'en': "I couldn't identify a valid travel destination in your request. Please specify a city or place (e.g., 'Plan a 7-day trip to Tokyo').",
                    'zh': "我无法在您的请求中识别出有效的旅游目的地。请指定一个城市或地点（例如：'规划7天东京之旅'）。",
                    'ms': "Saya tidak dapat mengenal pasti destinasi pelancongan yang sah dalam permintaan anda. Sila nyatakan bandar atau tempat (contoh: 'Rancang perjalanan 7 hari ke Tokyo')."
                }
                return invalid_dest_messages.get(language, invalid_dest_messages['en'])

        # ============ STANDARD MODE: Other Requests ============
        genai.configure(api_key=config.GEMINI_API_KEY)

        today_date = datetime.date.today().isoformat()
        location_info_for_prompt = ""
        user_location_string = None

        if coordinates and coordinates.get('latitude'):
            user_location_string = f"{coordinates.get('latitude')},{coordinates.get('longitude')}"
            location_info_for_prompt = f"User's current GPS coordinates are {user_location_string}."
        else:
            location_info_for_prompt = "User's current GPS coordinates are not available."

        # Get full language name for AI prompt
        response_language = LANGUAGE_FULL_NAMES.get(language, 'English')
        
        system_prompt = f"""
You are GogoTrip AI, a professional intelligent travel planning assistant specialized in TRAVEL AND TOURISM ONLY.

Current Date: {today_date}
User Context: {location_info_for_prompt}

*** CRITICAL: SCOPE RESTRICTION ***
You MUST ONLY answer questions related to:
✅ Travel planning and itineraries
✅ Tourist destinations and attractions
✅ Restaurants and food recommendations
✅ Hotels and accommodations
✅ Transportation and directions
✅ Travel tips and weather
✅ Activities and experiences

❌ You MUST REFUSE to answer:
- Non-travel questions (math, coding, general knowledge, etc.)
- Invalid destinations (e.g., "seafood", "pizza", random words that aren't places)
- Medical advice, legal advice, financial advice
- Any topic unrelated to tourism

If the user asks something outside your scope or provides an invalid destination, politely respond in {response_language}:
"I'm sorry, but I can only help with travel planning and tourism-related questions. Please ask me about destinations, restaurants, activities, or trip planning."

*** CRITICAL: DESTINATION VALIDATION ***
Before planning ANY itinerary, validate that the destination is a REAL PLACE:
- ✅ Valid: "Kuala Lumpur", "Tokyo", "Paris", "Bali"
- ❌ Invalid: "seafood" (that's food, not a place), "pizza" (that's food), "happiness" (abstract concept)

If you detect an invalid destination, IMMEDIATELY respond with an error message in {response_language} and DO NOT call any tools.

*** CRITICAL: RESPONSE LANGUAGE ***
You MUST respond in {response_language}. All your responses, recommendations, descriptions, and JSON content MUST be written in {response_language}.
- If the language is "English", respond in English.
- If the language is "Chinese (Simplified)", respond in 简体中文.
- If the language is "Bahasa Melayu (Malay)", respond in Bahasa Melayu.
This is NON-NEGOTIABLE. The user has selected {response_language} as their preferred language.
DO NOT use English if the user selected Chinese or Malay, unless it is a proper noun (like a place name).

*** PREFERENCE ANALYSIS ***
The user may provide structured preferences (e.g., "Mood: Relaxed", "Budget: Medium", "Dietary: Halal").
You MUST STRICTLY adhere to these constraints:
- **Mood**: Adjust the pace. "Relaxed" = fewer spots, more time. "Energetic" = packed itinerary.
- **Budget**: 
  - "Low": Prioritize free attractions, hawker centers, affordable transit.
  - "Medium": Balanced mix of paid/free.
  - "High/Luxury": Fine dining, premium experiences, private transport.
- **Transport**:
  - "Public": Ensure locations are near train/bus stations.
  - "Walk": Cluster activities close together.
- **Dietary**: STRICTLY filter food choices (e.g., NO Pork for Halal).

*** CRITICAL WORKFLOW - Database-First Filtering Mode ***

When user asks for place recommendations, follow this workflow:

**Step 1: Search and Store**
- Call search_nearby_places(query, location)
- This stores found places in database and returns place_ids

**Step 2: Query Database**
- Call query_places_from_db(place_ids=[...])
- Get detailed information for all places

**Step 3: Smart Filtering**
- Analyze user's real needs (e.g.: "romantic date" vs "family gathering" vs "quick lunch")
- Filter 3-5 best matching places from database results
- Consider factors: ratings, open status, price, reviews, location

**Step 4: Decide if Re-search Needed**
- If database places don't match user requirements (e.g.: user wants "Michelin restaurant" but found fast food)
- Clearly explain why they don't match
- Re-call search_nearby_places with more precise keywords (e.g.: "fine dining" or similar)

**Step 5: Return Results**
- If matching places found, return in POPUP_DATA::[...] format
- If multiple searches still unsuccessful, honestly tell user and suggest alternatives

*** LANGUAGE REMINDER ***
You MUST respond in {response_language}. This has been set by the user in their preferences.
Do NOT auto-detect or switch languages based on user input - always use {response_language}.
Even if the user asks in English, reply in {response_language}.

*** RESPONSE FORMAT ***

**MODE A: Place Recommendations (Simple Search - Food/Places)**
Use when user just wants to find restaurants or a place.
Return format: POPUP_DATA::[{{"name": "...", "address": "...", "rating": 4.5, ...}}]

*** CRITICAL: NO CONVERSATIONAL TEXT ***
⚠️ DO NOT include ANY introductory text before POPUP_DATA::
⚠️ DO NOT say "I found X places for you" or similar phrases.
⚠️ Start your response DIRECTLY with POPUP_DATA::[...]
The system will add appropriate user-facing messages automatically.

**MODE B: Smart Daily Planning**
Trigger conditions: User says "plan itinerary", "arrange trip", "N day tour", "plan my day", "daily plan" etc.

This is the core function of this system. Generate a structured multi-day itinerary with each day containing:
1. That day's top_locations (for displaying featured images, 2-3 max)
2. That day's complete activity list (sorted by time)
3. Each activity MUST be linked to real place in database (place_id)

Strictly follow this JSON Schema (NO MARKDOWN, start directly with {{):

{{
  "type": "daily_plan",
  "title": "Itinerary title (e.g.: Kuala Lumpur 3-Day Cultural & Food Experience)",
  "description": "Overall itinerary description",
  "duration": "3D2N",
  "total_budget_estimate": "RM 1,500 - RM 2,500",
  "tags": ["culture", "food", "couple-friendly"],
  "cover_image": "https://images.unsplash.com/photo-... (destination representative image)",
  "user_preferences_applied": {{
    "mood": "relaxed",
    "budget": "medium", 
    "transport": "public",
    "dietary": ["halal"]
  }},
  "days": [
    {{
      "day_number": 1,
      "date": "2024-01-15",
      "theme": "Arrival & City Exploration",
      "top_locations": [
        {{
          "place_id": 123,
          "name": "Petronas Twin Towers",
          "image_url": "https://...",
          "highlight_reason": "Iconic landmark, must visit"
        }},
        {{
          "place_id": 456,
          "name": "Jalan Alor",
          "image_url": "https://...",
          "highlight_reason": "Best night market food street"
        }}
      ],
      "activities": [
        {{
          "time_slot": "morning",
          "start_time": "09:00",
          "end_time": "11:30",
          "place_id": 123,
          "place_name": "Petronas Twin Towers",
          "place_address": "Kuala Lumpur City Centre",
          "activity_type": "attraction",
          "description": "Visit the Twin Towers, recommend going to observation deck in morning when crowd is less",
          "budget_estimate": "RM 80",
          "tips": "Recommend buying tickets online in advance"
        }},
        {{
          "time_slot": "lunch",
          "start_time": "12:00",
          "end_time": "13:30",
          "place_id": 789,
          "place_name": "Madam Kwan's",
          "place_address": "KLCC Suria Mall",
          "activity_type": "food",
          "description": "Taste authentic Malaysian cuisine, recommend Nasi Lemak",
          "budget_estimate": "RM 35",
          "dietary_info": "Halal certified"
        }},
        {{
          "time_slot": "afternoon",
          "start_time": "14:30",
          "end_time": "17:00",
          "place_id": 101,
          "place_name": "Islamic Arts Museum",
          "place_address": "Jalan Lembah Perdana",
          "activity_type": "attraction",
          "description": "Explore the beauty of Islamic art and architecture",
          "budget_estimate": "RM 20",
          "tips": "Good for avoiding afternoon heat"
        }},
        {{
          "time_slot": "evening",
          "start_time": "19:00",
          "end_time": "21:00",
          "place_id": 456,
          "place_name": "Jalan Alor",
          "place_address": "Jalan Alor, Bukit Bintang",
          "activity_type": "food",
          "description": "Night market food street, experience local food culture",
          "budget_estimate": "RM 50",
          "dietary_info": "Various options, some stalls not Halal"
        }}
      ],
      "day_summary": {{
        "total_activities": 4,
        "total_budget": "RM 185",
        "transport_notes": "Can use LRT/MRT throughout, reasonable walking distances"
      }}
    }},
    {{
      "day_number": 2,
      "date": "2024-01-16",
      "theme": "Historical & Cultural Exploration",
      "top_locations": [...],
      "activities": [...],
      "day_summary": {{...}}
    }}
  ],
  "practical_info": {{
    "best_transport": "LRT + Grab",
    "weather_advisory": "Tropical climate, bring rain gear",
    "booking_recommendations": ["Book Twin Towers tickets online in advance", "Popular restaurants recommend reservation"]
  }}
}}

**CRITICAL RULES FOR DAILY PLANNING:**
1. ⚠️ **PLACE_ID is mandatory**: Each activity MUST contain real place_id (from database)
2. **Search first, plan second**:
   - First call search_nearby_places for: restaurants, attractions, cafes, etc.
   - Then call query_places_from_db to get details
   - Build a "place pool", then select from it
3. **Time Logic**: Activity times should be reasonable, consider travel time
4. **Budget Logic**: Filter places based on user's budget preference (price_level)
5. **Transport Logic**:
   - "public" = prioritize places near metro/bus stations
   - "walk" = cluster activities close together
6. **Dietary Logic**:
   - If user selects "Halal", food activities MUST be Halal certified
   - Note in dietary_info
7. **Mood Logic**:
   - "relaxed" = 3-4 activities per day, leave rest time
   - "energetic" = 5-6 activities per day, packed itinerary
8. **top_locations**: Select 2-3 most representative places per day for image display
9. **NO MARKDOWN**: Start directly with {{, not ```json

*** CRITICAL: NO CONVERSATIONAL TEXT ***
⚠️ DO NOT include ANY introductory, explanatory, or conversational text before the JSON.
⚠️ DO NOT say phrases like "I've created", "Here is your itinerary", "Check out the plan below", or similar.
⚠️ Start your response DIRECTLY with the JSON object ({{ ... }}).
The system will add appropriate user-facing messages automatically.

*** NEVER HALLUCINATE ***
- Only use real data returned by tools
- place_id MUST exist in database
- Don't make up place names or addresses
"""
        
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=system_prompt,
            tools=tools_definition,
            generation_config={
                "temperature": 0.1,
                "top_p": 0.95,
                "top_k": 40
            }
        )

        gemini_messages = [msg for msg in conversation_history]
        if gemini_messages and gemini_messages[0]['role'] == 'model':
            gemini_messages = gemini_messages[1:]

        max_turns = 10  # Reduced from 20 to prevent infinite loops
        turn_count = 0

        # Track search history to prevent duplicate searches
        search_history = []
        # Track consecutive tool calls to detect loops
        consecutive_tool_calls = 0
        max_consecutive_tool_calls = 6  # If AI calls tools 6 times in a row, force stop

        while turn_count < max_turns:
            turn_count += 1
            print(f"--- [Chat Log] Gemini Turn {turn_count} ---")

            response = model.generate_content(
                gemini_messages,
                tool_config={"function_calling_config": {"mode": "any"}}
            )
            
            if not response.candidates:
                print("--- [Chat Error] Gemini did not return any candidate response. ---")
                return "Sorry, AI failed to generate response."

            response_content = response.candidates[0].content
            gemini_messages.append(response_content)

            # Check if tool is being called
            if response_content.parts and response_content.parts[0].function_call:
                consecutive_tool_calls += 1
                print(f"--- [Tool Call] AI is calling tools... (consecutive: {consecutive_tool_calls}/{max_consecutive_tool_calls}) ---")

                # Prevent infinite tool calling loop
                if consecutive_tool_calls >= max_consecutive_tool_calls:
                    print(f"--- [Loop Prevention] AI called tools {consecutive_tool_calls} times consecutively, forcing stop ---")
                    error_message = {
                        'en': "Sorry, I'm having trouble processing your request. Could you please rephrase or provide a valid travel destination?",
                        'zh': "抱歉，我在处理您的请求时遇到了问题。您能否重新表述或提供一个有效的旅游目的地？",
                        'ms': "Maaf, saya menghadapi masalah memproses permintaan anda. Bolehkah anda nyatakan semula atau berikan destinasi pelancongan yang sah?"
                    }
                    return error_message.get(language, error_message['en'])

                tool_call = response_content.parts[0].function_call
                function_name = tool_call.name
                function_args = {key: value for key, value in tool_call.args.items()}
                
                tool_result_content = ""

                # Execute tools
                if function_name == "get_coordinates_for_city":
                    try:
                        city_name = function_args.get("city_name")
                        print(f"--- [Tool] get_coordinates_for_city: {city_name} ---")
                        tool_result_content = get_coordinates_for_city(city_name)
                    except Exception as e:
                        tool_result_content = f"Error executing coordinate query: {str(e)}"

                elif function_name == "search_nearby_places":
                    try:
                        query = function_args.get("query")
                        location_from_ai = function_args.get("location")
                        print(f"--- [Tool] search_nearby_places: {query} @ {location_from_ai} ---")

                        # Record search history to prevent infinite loops
                        search_key = f"{query}|{location_from_ai}"
                        if search_key in search_history:
                            tool_result_content = json.dumps({
                                "error": "Already searched with these keywords, try different search terms"
                            })
                        else:
                            search_history.append(search_key)

                            final_location_query = None
                            if location_from_ai and ',' in location_from_ai:
                                final_location_query = location_from_ai
                            elif user_location_string:
                                final_location_query = user_location_string
                            else:
                                raise ValueError("Failed to determine search location.")

                            tool_result_content = search_nearby_places(query, final_location_query)

                    except Exception as e:
                        tool_result_content = f"Error executing place search: {str(e)}"

                elif function_name == "query_places_from_db":
                    try:
                        place_ids = function_args.get("place_ids")
                        query_hint = function_args.get("query_hint")
                        print(f"--- [Tool] query_places_from_db: IDs={place_ids}, Hint={query_hint} ---")

                        tool_result_content = query_places_from_db(
                            place_ids=place_ids,
                            query_hint=query_hint,
                            location=user_location_string
                        )
                    except Exception as e:
                        tool_result_content = f"Error executing database query: {str(e)}"

                elif function_name == "get_current_weather":
                    try:
                        city_or_coords = function_args.get("city")
                        keywords_for_current_location = ["here", "my place", "current location", "me"]
                        if user_location_string and (not city_or_coords or any(k in str(city_or_coords).lower() for k in keywords_for_current_location)):
                            city_or_coords = user_location_string
                        print(f"--- [Tool] get_current_weather: {city_or_coords} ---")
                        tool_result_content = get_current_weather(city_or_coords)
                    except Exception as e:
                        tool_result_content = f"Error executing weather query: {str(e)}"

                elif function_name == "get_weather_for_current_location":
                    try:
                        print(f"--- [Tool] get_weather_for_current_location ---")
                        query_string = None
                        if user_location_string:
                            query_string = user_location_string
                        else:
                            if user_ip == '127.0.0.1': user_ip = None
                            location_json = get_ip_location_info(ip_address=user_ip)
                            location_data = json.loads(location_json)
                            city = location_data.get('city')
                            if not city: raise ValueError("Failed to detect city from IP.")
                            query_string = city
                        tool_result_content = get_current_weather(query_string)
                    except Exception as e:
                        tool_result_content = f"Error executing local weather query: {str(e)}"

                else:
                    tool_result_content = f"Error: AI tried to call unknown tool '{function_name}'"

                print(f"--- [Tool Result] {tool_result_content[:200]}... ---")

                # Return tool result to AI
                gemini_messages.append({
                    "role": "function",
                    "parts": [
                        {"function_response": {
                            "name": function_name,
                            "response": {"content": tool_result_content}
                        }}
                    ]
                })

                continue  # Continue loop to let AI process tool result
                
            else:
                # AI decided not to call tools, return final response
                consecutive_tool_calls = 0  # Reset counter when AI generates text response
                print("--- [Chat Log] AI generating final response ---")
                if response_content.parts and response_content.parts[0].text:
                    ai_text = response_content.parts[0].text.strip()

                    # Clean up markdown markers
                    clean_text = ai_text.replace("```json", "").replace("```", "").strip()

                    # Smart JSON extraction - supports two formats: array [] or object {}
                    try:
                        # First try to extract daily_plan object format (new format)
                        obj_start = clean_text.find('{')
                        obj_end = clean_text.rfind('}')

                        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
                            potential_json = clean_text[obj_start : obj_end + 1]
                            parsed = json.loads(potential_json)

                            # Check if it's daily_plan format
                            if isinstance(parsed, dict) and parsed.get("type") == "daily_plan":
                                print("--- [System] Detected Daily Plan JSON, converting to itinerary mode ---")
                                return f"DAILY_PLAN::{potential_json}"

                        # Then try to extract array format (old format - place recommendations)
                        arr_start = clean_text.find('[')
                        arr_end = clean_text.rfind(']')

                        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
                            potential_json = clean_text[arr_start : arr_end + 1]
                            json.loads(potential_json)  # Validate JSON

                            print("--- [System] Detected JSON array, converting to card mode ---")
                            return f"POPUP_DATA::{potential_json}"

                    except json.JSONDecodeError:
                        pass

                    return ai_text
                else:
                    return "AI decided to respond but failed to generate text."

        # If loop exits due to max_turns, return error message in user's language
        loop_error_messages = {
            'en': "Sorry, AI agent got stuck in a thinking loop. Please try rephrasing your request with a clear destination (e.g., 'Plan a 3-day trip to Tokyo').",
            'zh': "抱歉，AI代理陷入了思考循环。请尝试用明确的目的地重新表述您的请求（例如：'规划3天东京之旅'）。",
            'ms': "Maaf, agen AI terperangkap dalam gelung pemikiran. Sila cuba nyatakan semula permintaan anda dengan destinasi yang jelas (contoh: 'Rancang perjalanan 3 hari ke Tokyo')."
        }
        return loop_error_messages.get(language, loop_error_messages['en'])

    except Exception as e:
        print(f"--- [Chat Error] {e} ---")
        import traceback
        traceback.print_exc()
        return f"Sorry, AI agent encountered an error while processing: {str(e)}"