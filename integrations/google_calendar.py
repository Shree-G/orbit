import logging
import datetime
import json
from typing import List, Optional, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from dateutil import parser

from config.settings import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI
)
from database.supabase_client import supabase
from utils.encryption import encrypt_text, decrypt_text

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']

class GoogleCalendarClient:
    def __init__(self, telegram_id: int):
        self.telegram_id = telegram_id
        self.service = self._authenticate()

    def _authenticate(self):
        """
        Authenticates the user using stored tokens.
        Handles token refresh if expired.
        """
        # Fetch user tokens from DB
        try:
            response = supabase.table("users").select("refresh_token, token_expiry").eq("telegram_id", self.telegram_id).execute()
            if not response.data:
                raise ValueError("User not found or not linked.")
            
            user_data = response.data[0]
            encrypted_refresh_token = user_data.get("refresh_token")
            
            if not encrypted_refresh_token:
                raise ValueError("No refresh token found. Please run /setup.")
                
            refresh_token = decrypt_text(encrypted_refresh_token)
            
        except Exception as e:
            logger.error(f"Auth Error for {self.telegram_id}: {e}")
            raise e

        # Create Credentials Object
        # Note: We don't store access_token reliably because it expires fast. 
        # We rely on refresh_token to get a new one.
        creds = Credentials(
            token=None, # we force refresh
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=SCOPES
        )

        # Refresh if needed (it will be needed since we passed token=None)
        if not creds.valid:
            if creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.error(f"Token Refresh Failed: {e}")
                    raise ValueError(f"Token refresh failed: {e}. Please run /setup again.")
            else:
                 raise ValueError("Invalid credentials (no refresh token). Please run /setup.")

        return build('calendar', 'v3', credentials=creds)

    def get_events(self, time_min: Optional[str] = None, time_max: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Lists events within a time range. 
        Strings should be ISO format or natural language parseable if we add that layer later.
        For now expecting ISO strings or defaulting to 'now' -> 'now + 7 days'.
        """
        now = datetime.datetime.utcnow()
        
        if not time_min:
            t_min = now.isoformat() + 'Z'
        else:
            t_min = parser.parse(time_min).isoformat()
            if not t_min.endswith('Z'): t_min += 'Z'

        if not time_max:
             # Default to 7 days ahead
             t_max = (now + datetime.timedelta(days=7)).isoformat() + 'Z'
        else:
             t_max = parser.parse(time_max).isoformat()
             if not t_max.endswith('Z'): t_max += 'Z'
             
        events_result = self.service.events().list(
            calendarId='primary', 
            timeMin=t_min,
            timeMax=t_max,
            maxResults=max_results, 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events_result.get('items', [])

    def get_primary_calendar_timezone(self) -> str:
        """
        Fetches the timezone of the primary calendar.
        """
        try:
            calendar = self.service.calendars().get(calendarId='primary').execute()
            return calendar.get('timeZone', 'UTC')
        except Exception as e:
            logger.error(f"Error fetching timezone: {e}")
            return 'UTC'

    def create_event(self, summary: str, start_time: str, duration_mins: int = 60, description: str = "", time_zone: str = "UTC") -> Dict[str, Any]:
        """
        Creates a new event.
        start_time: ISO string (e.g. 2023-10-27T10:00:00)
        time_zone: IANA timezone string (e.g. 'America/Los_Angeles')
        """
        try:
            start_dt = parser.parse(start_time)
            end_dt = start_dt + datetime.timedelta(minutes=duration_mins)
            
            event = {
                'summary': summary,
                'description': description,
                'start': {
                    'dateTime': start_dt.isoformat(),
                    'timeZone': time_zone, 
                },
                'end': {
                    'dateTime': end_dt.isoformat(),
                    'timeZone': time_zone,
                },
            }
            
            created_event = self.service.events().insert(calendarId='primary', body=event).execute()
            return created_event
            
        except Exception as e:
            logger.error(f"Create Event Error: {e}")
            raise e

    def search_events(self, query: str) -> List[Dict[str, Any]]:
        """
        Free text search for events.
        """
        # Google Calendar API 'q' parameter
        events_result = self.service.events().list(
            calendarId='primary',
            q=query,
            singleEvents=True,
            orderBy='startTime',
            maxResults=10
        ).execute()
        
        return events_result.get('items', [])

    def update_event(self, event_id: str, **kwargs) -> Dict[str, Any]:
        """
        Updates an event by ID.
        kwargs can be: summary, start_time, duration_mins, description
        """
        # First fetch existing to patch
        event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
        
        if 'summary' in kwargs:
            event['summary'] = kwargs['summary']
        if 'description' in kwargs:
            event['description'] = kwargs['description']
        
        # Time updates
        start_dt = None
        if 'start_time' in kwargs:
             start_dt = parser.parse(kwargs['start_time'])
             event['start']['dateTime'] = start_dt.isoformat()
        
        # If duration is changed, we need start time to calc end
        if 'duration_mins' in kwargs:
             if not start_dt:
                 # Parse existing start
                 start_v = event['start'].get('dateTime') or event['start'].get('date')
                 start_dt = parser.parse(start_v)
             
             end_dt = start_dt + datetime.timedelta(minutes=kwargs['duration_mins'])
             event['end']['dateTime'] = end_dt.isoformat()
             
        updated_event = self.service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
        return updated_event

    def delete_event(self, event_id: str) -> bool:
        """
        Deletes an event.
        Safe? : The agent layer should handle confirmation.
        """
        try:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return True
        except Exception as e:
            logger.error(f"Delete Error: {e}")
            return False
