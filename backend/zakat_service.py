import os
import time
import requests
import logging
from datetime import datetime, timedelta, timezone
from firebase_config import db

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# ISSUE 3: Extracted Hardcoded Fallback
FALLBACK_GOLD_PRICE = 380.00

def get_cached_price_data():
    """Safely attempts to read the cached price from Firestore."""
    try:
        system_ref = db.collection('system_config').document('gold_rate')
        doc = system_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get('gold_price'), data.get('updated_at')
    except Exception as db_error:
        logging.error(f"Firestore read error: {db_error}")
    
    return None, None

def update_cache(fresh_price, now):
    """Safely attempts to write the new price to Firestore."""
    try:
        system_ref = db.collection('system_config').document('gold_rate')
        # Store as ISO string for clean JSON serialization
        system_ref.set({
            "gold_price": fresh_price,
            "updated_at": now.isoformat() 
        })
        logging.info("💾 [DB UPDATED] Saved new API price to the database.")
    except Exception as db_error:
        logging.error(f"Firestore write error: {db_error}")

def fetch_external_gold_price():
    """Attempts to fetch the live price from the API with backoff retry logic."""
    if os.getenv("MOCK_MODE", "true").lower() == "true":
        logging.info("🛠️ [MOCK MODE] Simulating API response.")
        return 385.00

    api_url = "https://your-gold-api-url-here.com/latest" 
    
    for attempt in range(2):
        try:
            response = requests.get(api_url, timeout=3)
            response.raise_for_status() 
            data = response.json()
            
            return float(data.get("price") or data.get("rate") or FALLBACK_GOLD_PRICE)
            
        except Exception as e:
            logging.warning(f"⚠️ [API ERROR] Attempt {attempt + 1} failed: {e}")
            # ISSUE 1: Implement a simple 1-second backoff before retrying
            if attempt < 1:
                logging.info("⏳ Waiting 1 second before retrying...")
                time.sleep(1)
            
    return None

def get_current_gold_price():
    """Orchestrates caching, API fetching, and fallback logic."""
    now = datetime.now(timezone.utc)
    
    old_price, last_updated_raw = get_cached_price_data()
    
    if old_price is not None and last_updated_raw is not None:
        try:
            # ISSUE 2: Protect against Firestore returning strings OR datetime objects
            if isinstance(last_updated_raw, str):
                last_updated = datetime.fromisoformat(last_updated_raw)
            else:
                last_updated = last_updated_raw
            
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=timezone.utc)
            
            if (now - last_updated) < timedelta(hours=168):  # 7 days freshness threshold
                logging.info("⚡ [CACHE HIT] Price is fresh. Using database price.")
                return old_price
        except Exception as e:
            logging.error(f"Time parsing error: {e}")

    logging.info("🔄 [CACHE MISS/EXPIRED] Fetching latest price...")
    fresh_price = fetch_external_gold_price()
    
    if fresh_price is not None:
        update_cache(fresh_price, now)
        return fresh_price
    
    if old_price is not None:
        logging.warning("🛡️ [FALLBACK] API failed. Using the old database price.")
        return old_price
        
    logging.critical(f"🚨 [CRITICAL ERROR] API and DB failed. Using RM {FALLBACK_GOLD_PRICE}.")
    return FALLBACK_GOLD_PRICE

def get_current_nisab():
    """Calculates Nisab based on 85g of gold."""
    gold_price = get_current_gold_price()
    return gold_price * 85