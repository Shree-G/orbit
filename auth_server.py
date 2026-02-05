import logging
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from auth.oauth_flow import get_oauth_flow
from utils.encryption import decrypt_text, encrypt_text
from database.supabase_client import supabase
from datetime import datetime, timedelta

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.get("/oauth/callback")
async def oauth_callback(request: Request):
    """
    Handles the Google OAuth 2.0 callback.
    1. Validates State (decrypts telegram_id).
    2. Exchanges 'code' for tokens.
    3. Encrypts Refresh Token.
    4. Updates Supabase 'users' table.
    """
    params = request.query_params
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")

    if error:
        return HTMLResponse(content=f"<h1>Error</h1><p>{error}</p>", status_code=400)
    
    if not code or not state:
        return HTMLResponse(content="<h1>Error</h1><p>Missing code or state.</p>", status_code=400)

    # 1. Validate State & Decrypt Telegram ID
    try:
        decrypted_state_json = decrypt_text(state)
        state_data = json.loads(decrypted_state_json)
        telegram_id = state_data.get("telegram_id")
        
        if not telegram_id:
             raise ValueError("No telegram_id in state")
             
    except Exception as e:
        logger.error(f"State validation failed: {e}")
        return HTMLResponse(content="<h1>Error</h1><p>Invalid or expired session. Please try again from Telegram.</p>", status_code=400)

    # 2. Exchange Code for Tokens
    try:
        flow = get_oauth_flow()
        # The fetch_token method will automatically parse 'code' from the authorization response if we pass the full URL?
        # Or we can manually pass code.
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        return HTMLResponse(content=f"<h1>Error</h1><p>Failed to retrieve tokens from Google. {e}</p>", status_code=500)

    # 3. Encrypt Refresh Token & Prepare Data
    if not credentials.refresh_token:
        # Warning: If user re-auths without revoking access, Google might NOT send a refresh token.
        # We should assume this is a re-auth and maybe keep the old one?
        # For now, let's log it.
        logger.warning(f"No refresh_token returned for user {telegram_id}. Using existing if valid.")
        encrypted_refresh_token = None
    else:
        encrypted_refresh_token = encrypt_text(credentials.refresh_token)

    # Calculate expiry
    # credentials.expiry is a datetime object usually
    token_expiry = credentials.expiry if credentials.expiry else datetime.utcnow() + timedelta(hours=1)

    # 4. Update Supabase
    try:
        update_data = {
            "token_expiry": token_expiry.isoformat() if token_expiry else None,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if encrypted_refresh_token:
            update_data["refresh_token"] = encrypted_refresh_token
            
        # We also might want to store email if we can fetch it?
        # flow.credentials doesn't always have email unless we requested 'email' scope and used 'id_token'.
        # For Orbit, we are just using Calendar scope.
        
        # Execute Update
        supabase.table("users").update(update_data).eq("telegram_id", telegram_id).execute()
        
        # 5. Fetch & Save Timezone (Onboarding)
        try:
            from googleapiclient.discovery import build
            from database.operations import update_user_timezone
            
            service = build('calendar', 'v3', credentials=credentials)
            calendar = service.calendars().get(calendarId='primary').execute()
            timezone = calendar.get('timeZone', 'UTC')
            
            update_user_timezone(telegram_id, timezone)
            logger.info(f"Onboarding: Set timezone for {telegram_id} to {timezone}")
            
        except Exception as e:
            logger.error(f"Onboarding Timezone Sync Failed: {e}")
            # Don't fail the whole auth flow for this
    
    except Exception as e:
        logger.error(f"Database update failed: {e}")
        return HTMLResponse(content="<h1>Error</h1><p>Database error.</p>", status_code=500)

    return HTMLResponse(content="<h1>Success!</h1><p>Orbit is now linked to your Google Calendar. You can close this window and return to Telegram.</p>")

if __name__ == "__main__":
    import uvicorn
    # Run on port 8000 as configured in Google Console
    uvicorn.run(app, host="0.0.0.0", port=8000)
