import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.supabase_client import supabase

def verify_connection():
    try:
        print("Testing Supabase connection...")
        # Try to select from the users table (should be empty but succeed)
        response = supabase.table("users").select("*").limit(1).execute()
        print("Connection successful!")
        print(f"Data received: {response.data}")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    verify_connection()
