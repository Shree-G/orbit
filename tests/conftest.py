import pytest
import os
import asyncio
from database.supabase_client import supabase

# A deterministic fake ID that will never collide with a real Telegram ID
TEST_USER_ID = 999999999

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Session-scoped fixture.
    1. Ensures environment variables are loaded.
    2. Clears out any lingering test user artifacts before tests run.
    """
    # Teardown any past aborted tests
    supabase.table("users").delete().eq("telegram_id", TEST_USER_ID).execute()
    yield
    # Teardown cleanly after all tests finish
    supabase.table("users").delete().eq("telegram_id", TEST_USER_ID).execute()

@pytest.fixture
def fake_user_id():
    """
    Function-scoped fixture that provides the TEST_USER_ID
    and guarantees the user row exists for the duration of the test.
    """
    # Create the user strictly for this test
    data = {"telegram_id": TEST_USER_ID, "timezone": "America/New_York"}
    try:
        supabase.table("users").insert(data).execute()
    except Exception:
        pass # Might exist from parallel test run
        
    yield TEST_USER_ID 

@pytest.fixture
def real_user_id():
    """
    Provides the developer's REAL telegram ID for hitting Google live APIs.
    """
    return 8313501090
