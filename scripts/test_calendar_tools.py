import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from integrations.google_calendar import GoogleCalendarClient
from database.supabase_client import supabase

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=== Orbit Google Calendar Tool Test ===")
    
    # 1. Get Telegram ID
    telegram_id_input = input("Enter your Telegram ID (numeric): ")
    try:
        telegram_id = int(telegram_id_input)
    except ValueError:
        print("Invalid ID. Please enter a number.")
        return

    # 2. Initialize Client
    try:
        client = GoogleCalendarClient(telegram_id=telegram_id)
        print("✅ Client initialized successfully.")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        print("Make sure you have run /start and /setup in the bot.")
        return

    # 3. Create Event
    print("\n--- Testing create_event ---")
    summary = "Orbit Test Event"
    start_time = "2024-01-01T10:00:00" # Using a past/future date? Let's use tomorrow.
    
    from datetime import datetime, timedelta
    tomorrow = datetime.utcnow() + timedelta(days=1)
    start_time = tomorrow.strftime("%Y-%m-%dT10:00:00")
    
    try:
        event = client.create_event(summary=summary, start_time=start_time, duration_mins=30)
        event_id = event['id']
        print(f"✅ Event created: {event.get('htmlLink')}")
        print(f"ID: {event_id}")
    except Exception as e:
        print(f"❌ create_event failed: {e}")
        return

    # 4. Get Events
    print("\n--- Testing get_events ---")
    try:
        events = client.get_events()
        found = any(e['id'] == event_id for e in events)
        if found:
            print("✅ Created event found in list.")
        else:
            print("⚠️ Created event NOT found in list (might be due to time filtering).")
        print(f"Retrieved {len(events)} events.")
    except Exception as e:
        print(f"❌ get_events failed: {e}")

    # 5. Search Events
    print("\n--- Testing search_events ---")
    try:
        results = client.search_events(query="Orbit Test")
        found = any(e['id'] == event_id for e in results)
        if found:
            print("✅ Search found the test event.")
        else:
            print("❌ Search did NOT find the test event.")
    except Exception as e:
        print(f"❌ search_events failed: {e}")

    # 6. Update Event
    print("\n--- Testing update_event ---")
    try:
        updated = client.update_event(event_id, summary="Orbit Test Event (Updated)")
        if updated['summary'] == "Orbit Test Event (Updated)":
            print("✅ Event summary updated successfully.")
        else:
            print("❌ Event update mismatch.")
    except Exception as e:
        print(f"❌ update_event failed: {e}")

    # 7. Delete Event
    print("\n--- Testing delete_event ---")
    confirm = input(f"Delete testing event {event_id}? (y/n): ")
    if confirm.lower() == 'y':
        try:
            success = client.delete_event(event_id)
            if success:
                print("✅ Event deleted successfully.")
            else:
                print("❌ Event deletion failed.")
        except Exception as e:
            print(f"❌ delete_event failed: {e}")
    else:
        print("Skipping deletion.")

    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()
