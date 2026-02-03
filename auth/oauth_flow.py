import json
import logging
import google_auth_oauthlib.flow
from config.settings import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI
)
from utils.encryption import encrypt_text

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_oauth_flow():
    """Initializes the Google OAuth 2.0 Flow."""
    # Ensure config is present
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET")

    # Creating flow from client config dictionary for simplicity (or file if we had client_secret.json)
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES
    )
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

def get_authorization_url(telegram_id: int) -> str:
    """
    Generates the Google OAuth 2.0 authorization URL.
    Encrypts the telegram_id into the 'state' parameter for security.
    """
    flow = get_oauth_flow()
    
    # Create State: JSON -> String -> Encrypt
    state_data = json.dumps({"telegram_id": telegram_id})
    encrypted_state = encrypt_text(state_data)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent', # Force consent to ensure we get a refresh token
        state=encrypted_state,
        include_granted_scopes='true'
    )
    
    return authorization_url
