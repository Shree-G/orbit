# Orbit - Master Technical PRD

**Version:** 3.0 (Production Grade) **Target:** 1,000 Monthly Active Users **Architecture Style:** Agentic RAG + Event-Driven Scheduler

## 1. Project Overview

**Orbit** is an AI executive function agent on Telegram. It manages Google Calendar not just by executing commands, but by **proactively** managing the user's time based on a **natural language profile** that evolves over time.

**Key Technical Differentiators:**

1. **Natural Language Persistence:** User preferences are stored as a prose document (TEXT), not JSON.
    
2. **Optimistic Locking:** Profile updates use version control to prevent race conditions.
    
3. **OAuth 2.0 with State Validation:** Securely links Telegram IDs to Google Accounts without service accounts.
    
4. **Persistent Agent State:** Uses LangGraph `PostgresSaver` to maintain conversation history across server restarts.
    
5. **Proactive Scheduling:** Uses `APScheduler` (via `python-telegram-bot` JobQueue) to trigger events without user input.
    

---

## 2. Architecture & Data Flow

### High-Level Flow

1. **User Input:** Telegram Webhook → `main.py`
    
2. **Auth Layer:** Checks for valid OAuth Token in `users` table.
    
3. **Context Loading:** Fetches `user_document` (Profile) + Conversation History (Postgres).
    
4. **Agent Execution:** LangGraph ReAct Agent (GPT-4o-mini) → Decides Tool.
    
5. **Tool Execution:**
    
    - **Calendar:** Decrypts Access Token → Calls Google API.
        
    - **Profile:** updates `user_document` with version check.
        
6. **Response:** Sends text/voice back to Telegram.
    

### Proactive Flow (Background)

1. **Scheduler:** Runs every 15 minutes.
    
2. **Check:** Queries Google Calendar for events starting in <15 mins with specific tags (e.g., "Deep Work").
    
3. **Action:** Triggers proactive message to user via Telegram Bot API.
    

---

## 3. Database Schema (Supabase/PostgreSQL)

**Instruction:** Execute these exact SQL statements to initialize the database.

### Core Tables

SQL

```
-- 1. USERS: Identity and OAuth Tokens
CREATE TABLE users (
    telegram_id BIGINT PRIMARY KEY,
    email VARCHAR(255),
    timezone VARCHAR(50) DEFAULT 'UTC',
    
    -- OAuth 2.0 Data (Encrypted at application level)
    refresh_token TEXT,             
    token_expiry TIMESTAMP,
    
    quiz_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. USER_PROFILES: The "Brain" (Natural Language)
CREATE TABLE user_profiles (
    telegram_id BIGINT PRIMARY KEY,
    
    -- The Master Document
    user_document TEXT DEFAULT 'New user. No preferences learned yet.',
    
    -- Concurrency Control (Optimistic Locking)
    version INT DEFAULT 1,
    
    updated_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- 3. PROFILE_HISTORY: Audit Trail
CREATE TABLE profile_history (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    previous_document TEXT,
    new_document TEXT,
    change_reason TEXT,    -- e.g., "User explicit preference", "Memory compression"
    changed_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- 4. QUIZ_SESSIONS: Temporary Onboarding State
CREATE TABLE quiz_sessions (
    telegram_id BIGINT PRIMARY KEY,
    current_question INT DEFAULT 0,
    responses JSONB DEFAULT '{}',
    followup_questions JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);
```

### LangGraph Persistence Tables

_Required for `PostgresSaver`._

SQL

```
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value JSONB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
```

---

## 4. Tech Stack & Dependencies

**Runtime:** Python 3.11+ **Hosting:** Railway (Dockerized) **Observability:** LangSmith

**`requirements.txt`:**

Plaintext

```
python-telegram-bot[job-queue]==20.7
langgraph==0.2.45
langchain-openai==0.2.9
openai==1.54.3
google-auth-oauthlib==1.2.1
google-api-python-client==2.149.0
supabase==2.0.0
python-dateutil==2.9.0
cryptography==42.0.0
psycopg2-binary==2.9.10
langsmith==0.1.0
apscheduler==3.10.4
```

---

## 5. Security Specifications

### 1. OAuth 2.0 Flow (No Service Accounts)

- **Library:** `google_auth_oauthlib.flow.Flow`
    
- **Scopes:** `https://www.googleapis.com/auth/calendar`
    
- **State Parameter (Crucial):**
    
    - When generating the Auth URL, you MUST create a `state` token.
        
    - `state = Encrypt(json.dumps({"telegram_id": 12345}))` using `cryptography.fernet`.
        
    - Pass this `state` to Google.
        
- **Callback Handling:**
    
    - Receive `code` and `state` from Google.
        
    - Decrypt `state` to recover `telegram_id`.
        
    - Exchange `code` for `access_token` and `refresh_token`.
        
    - **IF** `refresh_token` is missing (re-auth scenario), prompt user to revoke access and try again, OR assume existing refresh token is valid.
        

### 2. Token Encryption at Rest

- **Algorithm:** Fernet (Symmetric Encryption).
    
- **Key:** Stored in `ENCRYPTION_KEY` env var.
    
- **Field:** `users.refresh_token` is NEVER stored as plain text.
    

---

## 6. Logic & Feature Specifications

### F1: Onboarding Quiz (Hybrid)

**Class:** `QuizManager`

1. **Check:** If message received and `users.quiz_completed = FALSE`.
    
2. **Flow:**
    
    - Ask Question 1 (Name).
        
    - User Replies.
        
    - **LLM Call:** Generate conversational acknowledgment + Next Question.
        
    - Repeat for 7 predefined questions.
        
3. **Dynamic Follow-up:**
    
    - After Q7, send all Q&A to LLM.
        
    - LLM Output: `{"needs_followup": bool, "questions": []}`.
        
    - If yes, ask follow-ups.
        
4. **Completion:**
    
    - LLM synthesizes `user_document`.
        
    - Insert into `user_profiles`.
        
    - Set `quiz_completed = TRUE`.
        
    - Trigger `/setup` command.
        

### F2: Agent "Brain" (System Prompt)

**Context Injection:** Before every agent run, fetch `user_profiles.user_document` and inject it here:

Plaintext

```
You are Orbit, an executive function agent.
CURRENT USER PROFILE:
{user_document}

RULES:
1. READ the profile before scheduling. If profile says "Gym at 6pm", default to that.
2. UPDATE the profile if the user states a new preference or you detect a pattern.
   - Use 'update_user_document' tool.
   - Example: User says "I hate mornings", add that to profile.
3. SAFETY: NEVER delete an event without using 'search_events' first to get details, then asking for explicit confirmation.
4. TIME: Current time is {current_time}.
```

### F3: Memory Compression

**Logic:**

1. Track `message_count` in memory (or redis/db).
    
2. If `message_count % 20 == 0`:
    
    - **Hidden Step:** Agent receives a system message: _"SYSTEM: Compressing memory. Read the user_document, summarize older patterns, keep recent context, and save the new version."_
        
    - Agent calls `update_user_document` with `reason="Compression"`.
        

### F4: Proactive Scheduler

**File:** `jobs/scheduler.py`

1. **Job:** `check_upcoming_events` (Interval: 15 mins).
    
2. **Logic:**
    
    - Loop through all users with `refresh_token`.
        
    - Call Google Calendar API: `list_events(timeMin=now, timeMax=now+15m)`.
        
    - Filter: Search for keywords (e.g., "Deep Work", "Meeting").
        
    - **Action:** `bot.send_message(chat_id=uid, text="HEADS UP: [Event] starts in 10 mins.")`
        

---

## 7. Tool Definitions (Inputs/Outputs)

The Agent has access to these specific tools.

### Calendar Tools

1. **`get_events(time_min, time_max)`**
    
    - _Auth:_ Auto-decrypts token. Handles Refresh if expired.
        
2. **`create_event(summary, start_time, duration_mins)`**
    
    - _Logic:_ Parses natural language time first.
        
3. **`search_events(query)`**
    
    - _Returns:_ List of `{id, summary, start}`.
        
4. **`update_event(event_id, ...)`**
    
5. **`delete_event(event_id)`**
    
    - _Constraint:_ Returns error if user hasn't confirmed in chat history (agent logic).
        

### Profile Tools

6. **`get_user_document()`**
    
    - _Returns:_ TEXT string.
        
7. **`update_user_document(new_text, change_reason)`**
    
    - _Input:_ Full new text, reason string.
        
    - _Logic:_
        
        - Fetch `current_version` from DB.
            
        - `UPDATE user_profiles SET user_document=..., version=version+1 WHERE telegram_id=... AND version=current_version`.
            
        - If Rows Affected == 0: **Raise Error** (Concurrency failure). Agent must re-read and retry.
            
        - Insert into `profile_history`.
            

---

## 8. Implementation Plan (Day-by-Day)

**Day 1: Foundation & DB**

- Set up Supabase. Run SQL Schema (Section 3).
    
- Create `config/settings.py` (Env vars).
    
- Create `database/supabase_client.py`.
    

**Day 2: Bot Infrastructure**

- Initialize `python-telegram-bot` Application.
    
- Create `onboarding/quiz_manager.py`.
    
- Implement state machine for Quiz (Questions 1-7).
    
- **Deliverable:** User can start bot and finish quiz; Profile is saved to DB.
    

**Day 3: OAuth 2.0 (The Hard Part)**

- Implement `auth/oauth_flow.py`.
    
- **Task:** Generate URL with `access_type=offline`, `prompt=consent`.
    
- **Task:** Encrypt `telegram_id` into `state` param.
    
- **Task:** Create `/oauth/callback` endpoint (FastAPI or similar wrapper required if not using polling, OR use a simple redirect handler).
    
- **Deliverable:** `/setup` command links Google Calendar.
    

**Day 4: Calendar Integration**

- Implement `utils/encryption.py`.
    
- Implement `integrations/google_calendar.py` (Client class).
    
- Implement Token Refresh logic (Catch `401`, refresh, update DB, retry).
    

**Day 5: Profile & Versioning**

- Implement `database/operations.py` specifically for `update_user_document`.
    
- Test Optimistic Locking: Try to update profile twice in parallel; ensure one fails.
    

**Day 6: Agent Construction**

- Setup LangGraph `MessageGraph`.
    
- Bind all Tools.
    
- Connect `PostgresSaver`.
    
- **Deliverable:** User can chat with agent, agent remembers context after restart.
    

**Day 7: Proactive Features**

- Implement `APScheduler` in `main.py`.
    
- Create the "Upcoming Event" checker.
    
- **Deliverable:** Bot messages user 10 mins before a calendar event.
    

---

## 9. Environment Variables (.env)

Bash

```
# Telegram
TELEGRAM_BOT_TOKEN=

# OpenAI
OPENAI_API_KEY=

# Google Cloud (OAuth 2.0 Client ID)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/callback  # Change for Prod

# Supabase
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_DB_URL=postgresql://...  # Required for PostgresSaver

# Security (Fernet Key)
# Generate with: cryptography.fernet.Fernet.generate_key()
ENCRYPTION_KEY=

# LangSmith (Tracing)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=orbit-dev
```