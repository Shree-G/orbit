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
from integrations.google_calendar import GoogleCalendarClient

# Logging
logger = logging.getLogger(__name__)


class OrbitAgent:
    def __init__(self, telegram_id: int):
        self.telegram_id = telegram_id
        
        # 1. Tools
        # We need to bind the client instance tools to the model
        self.calendar_client = GoogleCalendarClient(telegram_id)
        self.tools = self._bind_tools()
        
        # 2. Model
        self.model = ChatOpenAI(
            model="gpt-4o", 
            api_key=OPENAI_API_KEY
        ).bind_tools(self.tools)
        
        # 3. Workflow
        self.workflow = self._build_workflow()

    def _bind_tools(self):
        """
        Wraps client methods as LangChain tools.
        """
        # We define them as standalone functions that call the instance method
        
        @tool
        def get_events(time_min: str = None, time_max: str = None):
            """
            Lists events from the calendar within an optional time range.
            Important: Ensure time strings are formatted as RFC3339 timestamps (e.g. '2023-10-27T00:00:00-07:00').
            CRITICAL: If the user asks for events "today" or "tomorrow" without specifying a time of day, you MUST set time_min to the start of the day (00:00:00) and time_max to the end of the day (23:59:59) to ensure you do not miss early morning or late night events.
            If neither are provided, defaults to showing events for the next 7 days.
            """
            return self.calendar_client.get_events(time_min, time_max)

        @tool
        def create_event(summary: str, start_time: str, duration_mins: int = 60, description: str = ""):
            """
            Creates a new event on the calendar.
            Important: start_time MUST be formatted as an RFC3339 timestamp with timezone offset included (e.g. '2023-10-27T10:00:00-07:00').
            Check the user's timezone from the system prompt to determine the correct offset if scheduling locally.
            """
            return self.calendar_client.create_event(summary, start_time, duration_mins, description)
            
        @tool
        def search_events(query: str):
            """Searches for events matching the query."""
            return self.calendar_client.search_events(query)
            
        @tool
        def update_event(event_id: str, summary: str = None, start_time: str = None, duration_mins: int = None, description: str = None):
            """Updates an existing event."""
            kwargs = {}
            if summary is not None: kwargs['summary'] = summary
            if start_time is not None: kwargs['start_time'] = start_time
            if duration_mins is not None: kwargs['duration_mins'] = duration_mins
            if description is not None: kwargs['description'] = description
            return self.calendar_client.update_event(event_id, **kwargs)

        @tool
        def delete_event(event_id: str):
            """Deletes an event."""
            return self.calendar_client.delete_event(event_id)

        @tool
        async def update_profile(fact: str, category: Literal["IDENTITY", "NON-NEGOTIABLE BLOCKS", "PSYCHOLOGICAL LEVERS", "OBSERVED BEHAVIORS", "AGENT STRATEGY"]):
            """
            Saves a permanent fact/preference about the user (e.g. 'User needs 8 hours of sleep', 'Do not schedule meetings before 10 AM', 'User is motivated by seeing progress streaks').
            Use this ONLY when the user explicitly asks to remember something or states a clear preference.
            You MUST specify which category (Markdown Header) this fact belongs to.
            """
            from database.operations import get_user_profile, update_user_document
            import asyncio
            import time

            # Retry Loop for Concurrency
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # 1. Fetch current (to get version)
                    current_doc, version = await asyncio.to_thread(get_user_profile, self.telegram_id)
                    
                    # 2. Append new fact to the correct category
                    # We will do a basic string replacement to insert the fact under the right header
                    header = f"## {category}"
                    if header in current_doc:
                        # Split the document at the header, insert the fact, and reassemble
                        parts = current_doc.split(header)
                        new_doc = f"{parts[0]}{header}\n- {fact}{parts[1]}"
                    else:
                        # Return an error to the agent so it knows to try again.
                        return f"Error: Category '{category}' not found in the user profile document. Cannot save fact."
                    
                    # 3. Update
                    success = await asyncio.to_thread(
                        update_user_document, 
                        self.telegram_id, 
                        new_doc, 
                        version, 
                        change_reason=f"Agent Tool Update: {category}", 
                        old_document=current_doc
                    )
                    
                    if success:
                        return f"Successfully updated user profile under {category}."
                    
                    # If failed (Optimistic Lock), wait and retry
                    logger.warning(f"Update profile failed (conflict), retrying {attempt+1}/{max_retries}...")
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error updating profile: {e}")
                    return f"Error: {str(e)}"

            return "Failed to update profile after multiple attempts due to high traffic. Please try again later."

        return [get_events, create_event, search_events, update_event, delete_event, update_profile]

    async def _get_system_message(self):
        """
        Fetches dynamic system message with user profile asynchronously.
        """
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        import asyncio
        
        doc, version = await asyncio.to_thread(get_user_profile, self.telegram_id)
        
        # 1. Determine Timezone
        try:
            user_timezone = await asyncio.to_thread(get_user_timezone, self.telegram_id)
        except (LookupError, ValueError, Exception) as e:
            logger.warning(f"Timezone not found for user {self.telegram_id}: {e}. Defaulting to UTC.")
            user_timezone = "UTC"
        
        # 2. Format Current Time in User's Timezone
        try:
            tz = ZoneInfo(user_timezone)
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

    async def _call_model(self, state: MessagesState):
        """
        Invokes the model.
        Instead of directly mutating the state array (which causes sequence errors in LangGraph), 
        we pass the dynamic system prompt directly to the model invocation alongside the state messages.
        """
        messages = state["messages"]
        
        # Fetch fresh system message asynchronously
        sys_msg = await self._get_system_message()
        
        # Filter out stray system messages that might have crept into the history
        filtered_messages = [m for m in messages if not isinstance(m, SystemMessage)]
        
        # Filter out "Dangling Tool Calls" where an AIMessage has tool_calls but no matching ToolMessage follows it.
        # This happens if a tool crashes mid-invocation and the user replies again natively.
        clean_messages = []
        for i, m in enumerate(filtered_messages):
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", []):
                # Check if the next message is a ToolMessage
                has_tool_response = False
                if i + 1 < len(filtered_messages) and isinstance(filtered_messages[i+1], ToolMessage):
                    has_tool_response = True
                
                if not has_tool_response:
                    # Strip the tool calls to prevent OpenAI 400 Bad Request
                    m = AIMessage(content=m.content or "Tool call aborted due to internal system error.", id=m.id)
            clean_messages.append(m)
        
        # Pass the system message directly to the model ON INVOCATION 
        final_messages = [sys_msg] + clean_messages
        
        response = await self.model.ainvoke(final_messages)
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
        
        # 2. Convert messages to string for LLM
        history_text = "\n".join([f"{m.type}: {m.content}" for m in early_messages])
        
        # 3. Get Current Profile without blocking
        from database.operations import get_user_profile, update_user_document
        current_profile, version = await asyncio.to_thread(get_user_profile, self.telegram_id)
        
        # 4. Invoke LLM for Consolidation
        from agent.prompts import MEMORY_CONSOLIDATION_PROMPT
        consolidation_model = ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY)
        
        prompt = MEMORY_CONSOLIDATION_PROMPT.format(
            user_profile=current_profile,
            chat_history=history_text
        )
        
        response = await consolidation_model.ainvoke([HumanMessage(content=prompt)])
        new_profile_content = response.content.strip()
        
        # 5. Update Profile if Needed without blocking
        if "NO_UPDATE" not in new_profile_content:
            # We Replace the entire profile with the consolidated version
            await asyncio.to_thread(
                update_user_document, 
                self.telegram_id, 
                new_profile_content, 
                version, 
                change_reason="Memory Consolidation (Rewrite)", 
                old_document=current_profile
            )
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

    def _build_workflow(self):
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

        return workflow

    async def run(self, input_text: str):
        """
        Runs the agent with the given input.
        """
        # Config for persistence
        # We use the telegram_id as the unique thread_id for this user
        config = {"configurable": {"thread_id": str(self.telegram_id)}}
        
        # Format input
        inputs = {"messages": [HumanMessage(content=input_text)]}
        
        # Load checkpointer lazily connected to the native pool
        from database.postgres_checkpointer import get_checkpointer
        checkpointer = await get_checkpointer()
        
        # Compile graph dynamically
        graph = self.workflow.compile(checkpointer=checkpointer)
        
        # Async invocation
        result = await graph.ainvoke(inputs, config=config)
        
        # Extract last message
        last_msg = result["messages"][-1]
        return last_msg.content

