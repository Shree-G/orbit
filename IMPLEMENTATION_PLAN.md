# IMPLEMENATION PLAN - ORBIT

Based on the Master Technical PRD (Section 8).

## Day 1: Foundation & DB
- [x] Set up Supabase Project
- [x] Execute SQL Schema (from Section 3) to create tables:
    - [x] `users`
    - [x] `user_profiles`
    - [x] `profile_history`
    - [x] `quiz_sessions`
    - [x] `checkpoints` (LangGraph)
    - [x] `checkpoint_writes` (LangGraph)
- [x] Create `config/settings.py` for Environment Variables management
- [x] Create `database/supabase_client.py` for database connection
- [x] Verify database connection

## Day 2: Bot Infrastructure
- [x] Initialize `python-telegram-bot` Application in `main.py`
- [x] Create `onboarding/quiz_manager.py`
- [x] Implement State Machine for Quiz (Questions 1-7)
- [x] Implement support for user responses
- [x] Implement LLM call for conversational acknowledgment
- [x] Implement Dynamic Follow-up logic (After Q7)
- [x] Implement Profile Synthesis and Saving to `user_profiles`
- [x] Trigger `/setup` command upon completion

## Day 3: OAuth 2.0
- [x] Implement `auth/oauth_flow.py`
- [x] Implement URL generation with `access_type=offline` and `prompt=consent`
- [x] Implement `state` parameter encryption (binding `telegram_id`)
- [x] Create `utils/encryption.py` (if not created in Day 4 tasks, but needed here for state)
- [x] Create Callback Handling (likely a simple HTTP endpoint or redirect handler if using a web framework alongside the bot, or manual code paste if CLI)
    - *Note: PRD mentions "FastAPI... or use a simple redirect handler"*
- [x] Exchange code for `access_token` and `refresh_token`
- [x] Store encrypted secrets in `users` table
- [x] Verify `/setup` command successfully links Google Account

## Day 4: Calendar Integration
- [x] Implement `utils/encryption.py` (if not done in Day 3)
- [x] Implement `integrations/google_calendar.py` (Client Class)
- [x] Implement Token Refresh logic (Handle 401 errors)
- [x] Implement `get_events` tool
- [x] Implement `create_event` tool
- [x] Implement `search_events` tool
- [x] Implement `update_event` tool
- [x] Implement `delete_event` tool

## Day 5: Profile & Versioning
- [x] Implement `database/operations.py`
- [x] Implement `update_user_document` specific logic
- [x] Implement Optimistic Locking (check `version` column)
- [x] Implement `profile_history` insertion
- [x] Test concurrency handling (Parallel update test)

## Day 6: Agent Construction
- [ ] Setup LangGraph `MessageGraph`
- [ ] Bind all Tools (Calendar + Profile tools)
- [ ] Connect `PostgresSaver` for persistence
- [ ] Implement Context Injection (System Prompt with User Profile)
- [ ] Implement Memory Compression logic (F3)

## Day 7: Proactive Features
- [ ] Implement `APScheduler` in `main.py` or `jobs/scheduler.py`
- [ ] Implement `check_upcoming_events` job (15 min interval)
- [ ] Implement logic to query Google Calendar for upcoming events
- [ ] Implement logic to filter for keywords
- [ ] Implement Proactive Messaging via Telegram Bot API
