import logging
import asyncio
from typing import Literal, Annotated
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from config.settings import OPENAI_API_KEY, SUPABASE_DB_URL
from agent.prompts import ORBIT_SYSTEM_PROMPT
from database.operations import get_user_profile, update_user_document, get_user_timezone, update_user_timezone
from database.supabase_checkpointer import SupabaseCheckpointer
from integrations.google_calendar import GoogleCalendarClient

# Logging
logger = logging.getLogger(__name__)

# Postgres Pool removed for now to fix Async Error


class OrbitAgent:
    def __init__(self, telegram_id: int):
        self.telegram_id = telegram_id
        
        # 1. Tools
        # We need to bind the client instance tools to the model
        self.calendar_client = GoogleCalendarClient(telegram_id)
        self.tools = self._bind_tools()
        
        # 2. Model
        self.model = ChatOpenAI(
            model="gpt-4o-mini", 
            api_key=OPENAI_API_KEY
        ).bind_tools(self.tools)
        
        # 3. Graph
        self.graph = self._build_graph()

    def _bind_tools(self):
        """
        Wraps client methods as LangChain tools.
        """
        # We define them as standalone functions that call the instance method
        # This is a bit verbose but safest for tool binding with instance state.
        
        @tool
        def get_events(time_min: str = None, time_max: str = None, max_results: int = 10):
            """Lists events from the calendar."""
            return self.calendar_client.get_events(time_min, time_max, max_results)

        @tool
        def create_event(summary: str, start_time: str, duration_mins: int = 60, description: str = "", time_zone: str = "UTC"):
            """Creates a new event on the calendar."""
            return self.calendar_client.create_event(summary, start_time, duration_mins, description, time_zone)
            
        @tool
        def search_events(query: str):
            """Searches for events matching the query."""
            return self.calendar_client.search_events(query)
            
        @tool
        def update_event(event_id: str, summary: str = None, start_time: str = None, duration_mins: int = None, description: str = None):
            """Updates an existing event."""
            kwargs = {k: v for k, v in locals().items() if k != 'event_id' and v is not None}
            return self.calendar_client.update_event(event_id, **kwargs)

        @tool
        def delete_event(event_id: str):
            """Deletes an event."""
            return self.calendar_client.delete_event(event_id)

        @tool
        def update_profile(fact: str):
            """
            Saves a permanent fact/preference about the user (e.g. 'Likes green apples', 'Vegetarian').
            Use this ONLY when the user explicitly asks to remember something or states a clear preference.
            """
            from database.operations import get_user_profile, update_user_document
            import asyncio
            import time

            # Retry Loop for Concurrency
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # 1. Fetch current (to get version)
                    current_doc, version = get_user_profile(self.telegram_id)
                    
                    # 2. Append new fact
                    new_doc = f"{current_doc}\n- {fact}"
                    
                    # 3. Update
                    success = update_user_document(self.telegram_id, new_doc, version, change_reason="Agent Tool Update")
                    
                    if success:
                        return "Successfully updated user profile."
                    
                    # If failed (Optimistic Lock), wait and retry
                    logger.warning(f"Update profile failed (conflict), retrying {attempt+1}/{max_retries}...")
                    time.sleep(0.5) # Short backoff
                    
                except Exception as e:
                    logger.error(f"Error updating profile: {e}")
                    return f"Error: {str(e)}"

            return "Failed to update profile after multiple attempts due to high traffic. Please try again later."

        return [get_events, create_event, search_events, update_event, delete_event, update_profile]

    def _get_system_message(self):
        """
        Fetches dynamic system message with user profile.
        """
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        
        doc, version = get_user_profile(self.telegram_id)
        
        # 1. Determine Timezone
        user_timezone = get_user_timezone(self.telegram_id)
        
        # 2. Format Current Time in User's Timezone
        try:
            tz = ZoneInfo(user_timezone)
            # utcnow is naive, we want aware UTC then convert
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(tz)
            current_time_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as e:
            logger.error(f"Timezone conversion error: {e}")
            current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        return SystemMessage(content=ORBIT_SYSTEM_PROMPT.format(user_document=doc, current_time=current_time_str))

    def _should_continue(self, state: MessagesState):
        """
        Determines if we should loop (use tool) or end.
        """
        last_message = state["messages"][-1]
        
        # If there are tool calls, go to 'tools'
        if last_message.tool_calls:
            return "tools"
        return END

    def _call_model(self, state: MessagesState):
        """
        Invokes the model.
        Injects system prompt at the beginning if not present?
        Actually simpler: Just invoke model with messages.
        BUT we need the Dynamic System Prompt.
        """
        messages = state["messages"]
        
        # Fetch fresh system message
        sys_msg = self._get_system_message()
        
        # If the first message is NOT system, prepend it.
        # If it IS system, we might want to replace it to get latest profile?
        # For simplicity in this graph: Prepend effective prompt to the list passed to model
        # but don't necessarily mutate the state history unless we want to persist it?
        # LangGraph state is persistent. Repeatedly adding SystemMessages is bad.
        # Strategy: Pass it as a separate argument to invoke? 
        # Or filter out old SystemMessages?
        
        filtered_messages = [m for m in messages if not isinstance(m, SystemMessage)]
        final_messages = [sys_msg] + filtered_messages
        
        response = self.model.invoke(final_messages)
        return {"messages": [response]}

    async def _summarize_conversation(self, state: MessagesState):
        """
        Compresses memory by extracting insights and removing old messages.
        """
        messages = state["messages"]
        
        # 1. Identify messages to summarize
        # We prune a larger chunk to avoid frequent summarization loops.
        # Pruning 30 messages leaves us with ~45, giving a good buffer.
        PRUNE_COUNT = 30
        early_messages = messages[:PRUNE_COUNT]
        recent_messages = messages[PRUNE_COUNT:]
        
        # 2. Convert messages to string for LLM
        history_text = "\n".join([f"{m.type}: {m.content}" for m in early_messages])
        
        # 3. Get Current Profile
        from database.operations import get_user_profile, update_user_document
        current_profile, version = get_user_profile(self.telegram_id)
        
        # 4. Invoke LLM for Consolidation
        from agent.prompts import MEMORY_CONSOLIDATION_PROMPT
        
        # We need a fresh model instance for this (or use self.model without tools)
        # Using self.model might try to call tools, which we don't want here.
        # So we create a raw ChatOpenAI instance.
        consolidation_model = ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY)
        
        prompt = MEMORY_CONSOLIDATION_PROMPT.format(
            user_profile=current_profile,
            chat_history=history_text
        )
        
        response = await consolidation_model.ainvoke([HumanMessage(content=prompt)])
        new_profile_content = response.content.strip()
        
        # 5. Update Profile if Needed
        if "NO_UPDATE" not in new_profile_content:
            # We Replace the entire profile with the consolidated version
            update_user_document(self.telegram_id, new_profile_content, version, change_reason="Memory Consolidation (Rewrite)")
            logger.info(f"Consolidated memory for {self.telegram_id}")
            
        # 6. Delete summarized messages
        # In LangGraph, returning a RemoveMessage with an ID deletes it.
        from langchain_core.messages import RemoveMessage
        delete_ops = [RemoveMessage(id=m.id) for m in early_messages if m.id]
        
        # Return side effects: Checkpoint will capture deletions
        return {"messages": delete_ops}

    def _check_memory_pressure(self, state: MessagesState):
        """
        Conditional edge to determine if summarization is needed.
        """
        messages = state["messages"]
        logger.info(f"Checking memory pressure: {len(messages)} messages")
        if len(messages) > 75:
             logger.info("Memory pressure high. Triggering summarization.")
             return "summarize"
        return END

    def _check_memory_pressure_node(self, state: MessagesState):
        """
        Passthrough node to allow conditional edge routing.
        Requires returning a valid state update (empty list of messages).
        """
        return {"messages": []}

    def _build_graph(self):
        workflow = StateGraph(MessagesState)

        # Nodes
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", ToolNode(self.tools))
        workflow.add_node("summarize", self._summarize_conversation)
        workflow.add_node("check_memory", self._check_memory_pressure_node)
        
        # Edges
        workflow.set_entry_point("agent")
        
        # Agent -> Tools OR Summarize OR End
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                END: "check_memory" # Instead of END, we go to memory check
            }
        )
        
        workflow.add_edge("tools", "agent")
        
        # Memory Check -> Summarize OR End
        workflow.add_conditional_edges(
            "check_memory",
            self._check_memory_pressure,
            {
                "summarize": "summarize",
                END: END
            }
        )
        
        # Summarize -> End
        workflow.add_edge("summarize", END)

        # Checkpointer using Supabase (Persistent)
        checkpointer = SupabaseCheckpointer()
        
        # Compile
        return workflow.compile(checkpointer=checkpointer)

    async def run(self, input_text: str):
        """
        Runs the agent with the given input.
        """
        # Config for persistence
        # We use the telegram_id as the unique thread_id for this user
        config = {"configurable": {"thread_id": str(self.telegram_id)}}
        
        # Format input
        inputs = {"messages": [HumanMessage(content=input_text)]}
        
        # Async invocation
        result = await self.graph.ainvoke(inputs, config=config)
        
        # Extract last message
        last_msg = result["messages"][-1]
        return last_msg.content

