import logging
import json
from typing import Optional, Dict, Any, List
from database.supabase_client import supabase
from config.settings import OPENAI_API_KEY
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger(__name__)

# Predefined Questions
QUESTIONS = [
    "Hi! I'm Orbit, your executive function agent. What should I call you?",
    "Nice to meet you. To help you best, I need to understand your primary goal. Is it productivity, work-life balance, health, or something else?",
    "Got it. What does your typical work schedule look like? (e.g., 9-5 M-F, irregular freelancing, etc.)",
    "Understood. Are there specific habits you want to track or build? (e.g., Gym, Reading, Meditation)",
    "Noted. How do you prefer I communicate? (e.g., Direct and concise, or warm and encouraging?)",
    "Okay. typically, when do you wake up and go to sleep?",
    "Finally, is there anything else specific you want me to help manage or remember for you?"
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

        # Generate Acknowledgment using LLM
        # We only generate acknowledgment, NOT the next question text (which is static), 
        # EXCEPT for the transitional phrase.
        
        system_prompt = "You are a helpful, empathetic executive assistant. Acknowledge the user's answer briefly (1 sentence) and bridge to the next topic."
        user_prompt = f"Question: {QUESTIONS[current_q_index]}\nAnswer: {user_text}\nNext Question: {QUESTIONS[current_q_index + 1] if current_q_index + 1 < len(QUESTIONS) else 'End of Quiz'}"
        
        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            acknowledgment = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            acknowledgment = "Got it."

        # Advance State
        next_q_index = current_q_index + 1
        QuizManager.create_or_update_state(telegram_id, next_q_index, responses)

        if next_q_index < len(QUESTIONS):
            return f"{acknowledgment}\n\n{QUESTIONS[next_q_index]}"
        else:
            # End of Quiz - Trigger Completion logic
            QuizManager.complete_quiz(telegram_id, responses)
            return f"{acknowledgment}\n\nThanks! I've set up your profile. You can now use /help to see what I can do."

    @staticmethod
    def complete_quiz(telegram_id: int, responses: Dict[str, Any]):
        """Synthesizes the profile and saves it to user_profiles."""
        # 1. Synthesize Profile
        prompt = f"""
        Analyze these quiz responses and create a comprehensive User Profile Document.
        The document should be written in third-person technical prose (e.g., "User is a night owl... Prone to procrastination...").
        
        Responses:
        {json.dumps(responses, indent=2)}
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
