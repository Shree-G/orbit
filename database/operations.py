import logging
from typing import Tuple, Optional
from database.supabase_client import supabase

logger = logging.getLogger(__name__)

def get_user_profile(telegram_id: int) -> Tuple[dict, int]:
    """
    Fetches the user's profile document and current version.
    Returns: (user_document, version)
    """
    try:
        response = supabase.table("user_profiles").select("user_document, version").eq("telegram_id", telegram_id).execute()
        if not response.data:
            # If no profile exists, return default/empty and version 0 or 1?
            # Creating one might be better if it doesn't exist, but let's assume existence for now 
            # or handle it upstream.
            # PRD says default is 'New user...'
            # Let's return None to indicate missing/needs init, or defaults if that's safer.
            return ({"summary": "New user. No preferences learned yet."}, 0)
            
        data = response.data[0]
        # Strict string return as requested
        doc = data.get("user_document", "") or "New user. No preferences learned yet."
        return (str(doc), data.get("version", 0))
    except Exception as e:
        logger.error(f"Error fetching profile for {telegram_id}: {e}")
        raise e

def get_user_timezone(telegram_id: int) -> str:
    """
    Fetches the user's timezone from the users table.
    Returns: timezone string (e.g. 'UTC', 'America/Los_Angeles')
    """
    try:
        response = supabase.table("users").select("timezone").eq("telegram_id", telegram_id).execute()
        if not response.data:
            return "UTC"
        return response.data[0].get("timezone", "UTC")
    except Exception as e:
        logger.error(f"Error fetching timezone for {telegram_id}: {e}")
        return "UTC"

def update_user_timezone(telegram_id: int, timezone: str) -> bool:
    """
    Updates the user's timezone in the users table.
    """
    try:
        response = supabase.table("users").update({"timezone": timezone}).eq("telegram_id", telegram_id).execute()
        return bool(response.data)
    except Exception as e:
        logger.error(f"Error updating timezone for {telegram_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error fetching profile for {telegram_id}: {e}")
        raise e

def update_user_document(telegram_id: int, new_document: str, expected_version: int, change_reason: str) -> bool:
    """
    Optimistically updates the user profile.
    Checks if current version matches expected_version.
    If match: Updates document, increments version, logs history.
    If mismatch: Returns False (caller should retry).
    """
    try:
        # 1. Check Version & Update (Atomic-ish)
        next_version = expected_version + 1
        
        response = supabase.table("user_profiles").update({
            "user_document": new_document,
            "version": next_version,
            "updated_at": "now()"
        }).eq("telegram_id", telegram_id).eq("version", expected_version).execute()
        
        # Check if update happened
        if not response.data:
            logger.warning(f"Optimistic lock failed for user {telegram_id}. Expected v{expected_version}.")
            return False
            
        # 2. Log History
        try:
            supabase.table("profile_history").insert({
                "telegram_id": telegram_id,
                "previous_document": None,
                "new_document": new_document,
                "change_reason": change_reason
            }).execute()
        except Exception as e:
            logger.error(f"Failed to write history log: {e}")
            
        return True
        
    except Exception as e:
        logger.error(f"Error updating profile for {telegram_id}: {e}")
        raise e
