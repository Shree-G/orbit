import pytest
from database.operations import (
    get_user_profile,
    update_user_document,
    get_user_timezone
)

def test_database_profile_creation_and_locking(fake_user_id):
    """
    Tests the full end-to-end optimistic locking loop for user profiles.
    """
    # Seed the initial row, which mimics what QuizManager does
    from database.supabase_client import supabase
    supabase.table("user_profiles").insert({"telegram_id": fake_user_id, "user_document": "No preferences learned yet.", "version": 0}).execute()

    # 1. Fetch initial state
    doc, version = get_user_profile(fake_user_id)
    assert version == 0
    assert "No preferences learned yet." in str(doc)

    # 2. Update the document successfully
    new_doc = "User hates morning meetings."
    success = update_user_document(
        telegram_id=fake_user_id,
        new_document=new_doc,
        expected_version=version,
        change_reason="pytest initialization"
    )
    assert success is True

    # 3. Fetch again to verify increment
    updated_doc, updated_version = get_user_profile(fake_user_id)
    assert updated_version == 1
    assert updated_doc == new_doc

    # 4. EDGE CASE: Test Optimistic Locking collision
    # Attempting to update with the OLD version (0) should fail
    collision_success = update_user_document(
        telegram_id=fake_user_id,
        new_document="Parallel hacker edit",
        expected_version=0,  # Intentional stale version
        change_reason="Malicious collision test"
    )
    assert collision_success is False

def test_timezone_lookup_edge_cases(fake_user_id):
    """
    Edge case: Timezone fetches.
    """
    # 1. Valid fetch
    tz = get_user_timezone(fake_user_id)
    assert tz == "America/New_York"
    
    # 2. Edge Case: Fetching for a user that doesn't exist
    with pytest.raises(LookupError) as excinfo:
        get_user_timezone(111111111)
    
    assert "does not exist" in str(excinfo.value)
