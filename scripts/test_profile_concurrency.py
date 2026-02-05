import asyncio
import logging
import sys
import os
import random

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.operations import get_user_profile, update_user_document
from database.supabase_client import supabase

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def simulate_update(telegram_id: int, agent_name: str, delay: float):
    """
    Simulates an agent trying to update the profile.
    1. Reads profile (gets version V).
    2. Waits (simulating "thinking").
    3. Tries to update with version V.
    """
    logger.info(f"[{agent_name}] Reading profile...")
    doc, version = await asyncio.to_thread(get_user_profile, telegram_id)
    logger.info(f"[{agent_name}] Read version: {version}")
    
    # Simulate thinking time
    await asyncio.sleep(delay)
    
    new_doc = f"Updated by {agent_name} at version {version + 1}"
    logger.info(f"[{agent_name}] Attempting update to version {version + 1}...")
    
    success = await asyncio.to_thread(
        update_user_document, 
        telegram_id, 
        new_doc, 
        version, 
        f"Test update by {agent_name}"
    )
    
    if success:
        logger.info(f"[{agent_name}] ✅ Update SUCCESS!")
    else:
        logger.warning(f"[{agent_name}] ❌ Update FAILED (Optimistic Lock)!")

async def main():
    print("=== Orbit Profile Concurrency Test ===")
    telegram_id_input = input("Enter your Telegram ID: ")
    try:
        telegram_id = int(telegram_id_input)
    except:
        return

    # 1. Ensure Profile Exists
    # If not exists, insert dummy
    res = supabase.table("user_profiles").select("*").eq("telegram_id", telegram_id).execute()
    if not res.data:
        print("Creating initial profile...")
        supabase.table("user_profiles").insert({
            "telegram_id": telegram_id,
            "user_document": "Initial Doc",
            "version": 1
        }).execute()
        
    print("\n--- Starting Race Condition Test ---")
    # Spawn two agents:
    # Agent A: Fast (Thinking 1s)
    # Agent B: Slow (Thinking 2s)
    # Both read at T=0.
    # Agent A writes at T=1. Should succeed.
    # Agent B writes at T=2. Should fail because version changed.
    
    task1 = asyncio.create_task(simulate_update(telegram_id, "Agent A (Fast)", 1.0))
    task2 = asyncio.create_task(simulate_update(telegram_id, "Agent B (Slow)", 3.0))
    
    await asyncio.gather(task1, task2)
    
    print("\n--- Verifying Final State ---")
    doc, version = get_user_profile(telegram_id)
    print(f"Final Document: {doc}")
    print(f"Final Version: {version}")
    
    # Check history
    hist = supabase.table("profile_history").select("*").eq("telegram_id", telegram_id).order("id", desc=True).limit(5).execute()
    print(f"History Entries: {len(hist.data)}")
    for h in hist.data:
        print(f" - [{h['id']}] {h['change_reason']}")

if __name__ == "__main__":
    asyncio.run(main())
