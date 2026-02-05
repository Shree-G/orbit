import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.operations import update_user_timezone

telegram_id = 8313501090
timezone = "America/Los_Angeles"

success = update_user_timezone(telegram_id, timezone)
if success:
    print(f"Successfully updated timezone for {telegram_id} to {timezone}")
else:
    print("Failed to update timezone.")
