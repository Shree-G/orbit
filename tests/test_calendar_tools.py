import pytest
import datetime
from integrations.google_calendar import GoogleCalendarClient

def test_live_calendar_crud_flow(real_user_id):
    """
    Tests the Google Calendar API directly using the developer's
    actual authorization tokens to ensure Google payload scopes,
    refresh behaviors, and token decryptions correctly pass on the network layer.
    """
    # 1. Initialize Client (Tests decryption and refresh)
    client = GoogleCalendarClient(real_user_id)
    
    # 2. CREATE an event slightly in the future
    start_time = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).replace(microsecond=0).isoformat()
    test_title = "[ORBIT_TEST] Delete Me"
    
    created_event = client.create_event(
        summary=test_title,
        start_time=start_time,
        duration_mins=15,
        description="Automated pytest creation"
    )
    
    event_id = created_event.get("id")
    assert event_id is not None
    assert created_event.get("summary") == test_title

    # 3. SEARCH for the event
    # Give google api a microsecond to ingest it
    search_results = client.search_events(query="[ORBIT_TEST]")
    assert any(e.get("id") == event_id for e in search_results)

    # 4. UPDATE the event
    updated_title = "[ORBIT_TEST] Still Delete Me"
    updated_event = client.update_event(
        event_id=event_id,
        summary=updated_title,
        duration_mins=30
    )
    assert updated_event.get("summary") == updated_title

    # 5. DELETE the event
    delete_success = client.delete_event(event_id)
    assert delete_success is True

def test_calendar_auth_edge_cases(fake_user_id):
    """
    Edge Case: What happens if a user is not linked? Or invalid token?
    """
    with pytest.raises(ValueError) as excinfo:
        GoogleCalendarClient(fake_user_id) # Fake user has no token!
        
    assert "No refresh token found" in str(excinfo.value)
