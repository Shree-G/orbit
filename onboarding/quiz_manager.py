import logging
import json
from typing import Optional, Dict, Any, List
from database.supabase_client import supabase
from config.settings import OPENAI_API_KEY
from auth.oauth_flow import get_authorization_url
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger(__name__)

# Predefined Questions
QUESTIONS = [
    "Hi! I'm Orbit, your executive function agent. What should I call you?",
    "Got it. Are there any strict non-negotiable blocks in your day that may not be on your calendar (e.g., 9-5 work Monday to Friday, 12-1 PM lunch, dropping off kids from 8:30-9 AM)? I won't plan tasks during these periods.",
    "When you don't want to do tasks, what reasoning should I give you to keep going? This will help me send you personalized notifications to keep you as accountable as possible.",
    "Lastly, is there anything else I should know before I help manage your time?",
]

class QuizManager:
    """Manages the persistent onboarding quiz state using Supabase."""

    @staticmethod
    def get_state(telegram_id: int) -> Optional[Dict[str, Any]]:
        """Fetches the current quiz state from Supabase."""
        try:
            response = supabase.table("quiz_sessions").select("*").eq("telegram_id", telegram_id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching quiz state for {telegram_id}: {e}")
            return None

    @staticmethod
    def create_or_update_state(telegram_id: int, current_question: int, responses: Dict[str, Any], followup_questions: List[str] = []) -> None:
        """Upserts the quiz state in Supabase."""
        data = {
            "telegram_id": telegram_id,
            "current_question": current_question,
            "responses": json.dumps(responses),  # Ensure JSON serialization
            "followup_questions": json.dumps(followup_questions)
        }
        try:
            # Upsert (insert or update)
            supabase.table("quiz_sessions").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error saving quiz state for {telegram_id}: {e}")
            raise e

    @staticmethod
    def start_quiz(telegram_id: int) -> str:
        """Initializes the quiz for a user."""
        # Check if already exists
        state = QuizManager.get_state(telegram_id)
        if state:
             # If exists, resume (or restart if user explicitly requested generic logic elsewhere, 
             # but here we just return current question)
             return QUESTIONS[state['current_question']]
        
        # Initialize
        QuizManager.create_or_update_state(telegram_id, 0, {})
        return QUESTIONS[0]

    @staticmethod
    def handle_response(telegram_id: int, user_text: str) -> str:
        """Processes the user's response to the current question."""
        state = QuizManager.get_state(telegram_id)
        if not state:
            return QuizManager.start_quiz(telegram_id)

        current_q_index = state['current_question']
        
        # If we are done with the main questions (index 7), handle dynamic follow-ups
        # Logic for simplicity: If 0 <= index < 7, it's a main question.
        
        if current_q_index >= len(QUESTIONS):
            return "Profile setup complete! You can using the bot now."

        # Save Response
        # We need to parse the existing responses which might be a string (JSON) or a dict depending on Supabase client return
        responses = state['responses']
        if isinstance(responses, str):
            responses = json.loads(responses)
        
        # Key the response by the question text or index. Let's use Index for stability.
        responses[str(current_q_index)] = user_text

        # Advance State
        next_q_index = current_q_index + 1
        QuizManager.create_or_update_state(telegram_id, next_q_index, responses)

        if next_q_index < len(QUESTIONS):
            return QUESTIONS[next_q_index]
        else:
            # End of Quiz - Trigger Completion logic
            QuizManager.complete_quiz(telegram_id, responses)
            
            # Generate OAuth link automatically
            auth_url = get_authorization_url(telegram_id)
            completion_msg = (
                "Thanks! I've set up your profile.\n\n"
                "🔗 *One Last Step: Google Calendar Integration*\n"
                "To actually manage your time, please click the link below to authorize Orbit to access your calendar.\n\n"
                f"[Authorize with Google]({auth_url})"
            )
            return completion_msg

    @staticmethod
    def complete_quiz(telegram_id: int, responses: Dict[str, Any]):
        """Synthesizes the profile and saves it to user_profiles."""
        # Pair questions and answers
        qa_pairs = []
        for q_idx_str, user_ans in responses.items():
            if q_idx_str.isdigit():
                q_idx = int(q_idx_str)
                if q_idx < len(QUESTIONS):
                    qa_pairs.append(f"Q: {QUESTIONS[q_idx]}\nA: {user_ans}")
        
        qa_text = "\n\n".join(qa_pairs)

        # 1. Synthesize Profile
        prompt = f"""
        Analyze these quiz responses and synthesize a "User Persona" document for an executive function agent.
        
        FORMAT INSTRUCTIONS:
        Use the following Markdown structure. Be concise. Use bullet points under each header. In the AGENT STRATEGY section, translate user preferences into actionable 'rules of engagement' for the AI assistant.
        
        ## IDENTITY
        - [Preferred Name]
        
        ## NON-NEGOTIABLE BLOCKS
        - [List specific times/activities mentioned]
        
        ## PSYCHOLOGICAL LEVERS
        - [Reasoning/Motivation that works for them]
        
        ## OBSERVED BEHAVIORS
        - [Leave blank for now. Will be populated by the agent over time based on actual calendar behavior]
        
        ## AGENT STRATEGY
        - [Inferences about their style based on the 'anything else' response]
        - [Other strategies for this assistant to help the user the most]
        
        RESPONSES:
        {qa_text}
        """
        
        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You are an expert profiler."}, {"role": "user", "content": prompt}]
            )
            profile_text = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM Error during synthesis: {e}")
            profile_text = "Error generating profile. Please update manually."

        # 2. Save to `user_profiles`
        # Using upsert
        try:
            # Check if user exists in `users` table first? 
            # Ideally `users` table row is created on /start. We should ensure that in main.py.
            
            data = {
                "telegram_id": telegram_id,
                "user_document": profile_text,
                "version": 1
            }
            supabase.table("user_profiles").upsert(data).execute()
            
            # 3. Mark quiz_completed in `users`
            supabase.table("users").update({"quiz_completed": True}).eq("telegram_id", telegram_id).execute()
            
            # 4. Cleanup quiz session? Optional. We might keep it for now.
             
        except Exception as e:
            logger.error(f"Error saving profile for {telegram_id}: {e}")
