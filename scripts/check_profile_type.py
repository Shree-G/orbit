import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.supabase_client import supabase
import json

telegram_id = 8313501090

response = supabase.table("user_profiles").select("user_document, version").eq("telegram_id", telegram_id).execute()

if response.data:
    row = response.data[0]
    doc = row.get("user_document")
    print(f"Type: {type(doc)}")
    print(f"Value: {doc}")
else:
    print("No profile found.")
