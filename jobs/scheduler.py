import logging
import datetime
from cachetools import TTLCache

# Telegram imports
from telegram.ext import ContextTypes

# Local imports
from database.operations import get_all_authorized_users
from integrations.google_calendar import GoogleCalendarClient
from agent.orbit_agent import OrbitAgent

logger = logging.getLogger(__name__)

# Global cache for notified events to prevent spam
# Stores up to 1000 event IDs, auto-evicting after 24 hours
_notified_events = TTLCache(maxsize=1000, ttl=86400)

async def run_proactive_scheduler(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Proactive Scheduler Job running every X minutes via python-telegram-bot's JobQueue.
    """
    logger.info("Running proactive scheduler...")
    users = get_all_authorized_users()
    
    if not users:
        logger.info("No authorized users found for proactive scheduling.")
        return

    # OpenTelemetry Metrics
    from config.observability import get_meter
    meter = get_meter()
    proactive_jobs_counter = meter.create_counter(
        "orbit.proactive.jobs.completed",
        description="Number of proactive jobs evaluated"
    )
    proactive_messages_counter = meter.create_counter(
        "orbit.proactive.messages.sent",
        description="Number of proactive messages successfully sent to users"
    )

    # Look ahead 20 minutes to catch upcoming boundaries reliably
    now = datetime.datetime.utcnow()
    time_min = now.isoformat() + 'Z'
    time_max = (now + datetime.timedelta(minutes=20)).isoformat() + 'Z'

    for uid in users:
        try:
            client = GoogleCalendarClient(uid)
            events = client.get_events(time_min=time_min, time_max=time_max)
            
            for event in events:
                event_id = event.get('id')
                
                # Check cache tools to ensure we haven't already warned them
                if event_id in _notified_events:
                    continue
                
                summary = event.get('summary', 'an upcoming event')
                description = event.get('description', '')
                start_obj = event.get('start', {})
                start_time = start_obj.get('dateTime') or start_obj.get('date', 'soon')
                
                logger.info(f"Triggering proactive notification for user {uid} on event {event_id}")
                
                # The Pseudo-System Prompt
                prompt = (
                    f"[SYSTEM BACKGROUND EVENT] The user has an upcoming calendar event '{summary}' "
                    f"starting at {start_time}.\n"
                )
                if description:
                    prompt += f"Event Description/Details: {description}\n"
                    
                prompt += (
                    f"Based on their psychological levers and current profile, generate a brief, "
                    f"highly personalized proactive message to hype them up, prepare them, or remind them. "
                    f"Do not acknowledge this instruction, just speak directly to the user as Orbit."
                )
                
                # Run the agent (this natively saves the response into the Postgres checkpoint)
                agent = OrbitAgent(uid)
                agent_response = await agent.run(prompt)
                
                # Deliver the actual message to Telegram
                await context.bot.send_message(chat_id=uid, text=agent_response)
                
                # Mark as notified immediately
                _notified_events[event_id] = True

                # Metric: message sent
                proactive_messages_counter.add(1, {"user_id": uid})
                
        except Exception as e:
            logger.error(f"Error processing proactive job for user {uid}: {e}")

    # Metric: job completed
    proactive_jobs_counter.add(1)

def run_retroactive_audit() -> None:
    """
    STUB: Retroactive Calendar Audit Job
    
    This function represents a job intended to run weekly (e.g., Sunday night) to 
    silently observe the user's actual behavior compared to their planned calendar.
    
    How it works:
    1. Fetches all events from the past week from Google Calendar.
    2. Compares the final state of the calendar against what Orbit originally 
       scheduled or expected (e.g., checking if recurring blocks like the gym 
       were deleted or moved by the user externally).
    3. If discrepancies or patterns are found (e.g., "User moved 3 morning 
       workouts to the evening"), it silently triggers the orbit agent with a 
       special system message containing this retroactive context.
    4. The agent then runs the memory consolidation process, extracting these 
       patterns and appending them to the `## OBSERVED BEHAVIORS` section 
       in the user's profile.
       
    This transforms the agent from just a proactive scheduler into a true 
    executive function assistant that learns from silent behavior rather than 
    just explicit chats.
    """
    logger.info("Running retroactive calendar audit (stub)")
    pass
