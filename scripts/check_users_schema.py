import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.supabase_client import supabase

try:
    # Try to select timezone from users for a known user
    telegram_id = 8313501090
    response = supabase.table("users").select("timezone").eq("telegram_id", telegram_id).execute()
    print("Query successful.")
    print(f"Data: {response.data}")
except Exception as e:
    print(f"Error: {e}")
