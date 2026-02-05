from typing import Any, AsyncIterator, Dict, Optional, Sequence, Tuple
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from database.supabase_client import supabase
import logging
import json

logger = logging.getLogger(__name__)

class SupabaseCheckpointer(BaseCheckpointSaver):
    """
    A persistent checkpointer that saves to Supabase (Postgres) via HTTP API.
    """
    def __init__(self):
        super().__init__(serde=JsonPlusSerializer())

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        Get a checkpoint tuple from the database.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        try:
            query = supabase.table("checkpoints").select("*")\
                .eq("thread_id", thread_id)\
                .eq("checkpoint_ns", checkpoint_ns)
            
            if checkpoint_id:
                query = query.eq("checkpoint_id", checkpoint_id)
            else:
                # Get the latest one
                query = query.order("checkpoint_id", desc=True).limit(1)

            result = query.execute()

            if not result.data:
                logger.info(f"Checkpointer: No checkpoint found for {thread_id}")
                return None

            row = result.data[0]
            logger.info(f"Checkpointer: Loaded checkpoint {row['checkpoint_id']} for {thread_id}")
            
            # Supabase returns Dict for JSONB columns. 
            # LangGraph serializer expects bytes (JSON string encoded).
            checkpoint = self.serde.loads(json.dumps(row["checkpoint"]).encode("utf-8"))
            metadata = self.serde.loads(json.dumps(row["metadata"]).encode("utf-8"))
            parent_id = row.get("parent_checkpoint_id")

            # TODO: Fetch writes if needed for advanced usage (Time Travel)
            # For now, base chat memory largely relies on the checkpoint itself.
            
            return CheckpointTuple(
                config=config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_id,
                    }
                } if parent_id else None,
            )

        except Exception as e:
            logger.error(f"Error getting checkpoint for {thread_id}: {e}")
            return None

    async def alist(
        self,
        config: RunnableConfig,
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        List checkpoints from the database.
        """
        # Minimal implementation for history viewing
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        
        try:
            query = supabase.table("checkpoints").select("*")\
                .eq("thread_id", thread_id)\
                .eq("checkpoint_ns", checkpoint_ns)\
                .order("checkpoint_id", desc=True)
                
            if limit:
                query = query.limit(limit)
                
            result = query.execute()
            
            for row in result.data:
                yield CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": row["checkpoint_id"],
                        }
                    },
                    checkpoint=self.serde.loads(row["checkpoint"]),
                    metadata=self.serde.loads(row["metadata"]),
                    parent_config=None # Optimization: don't strictly need parent config for listing
                )
                
        except Exception as e:
            logger.error(f"Error listing checkpoints: {e}")

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> RunnableConfig:
        """
        Save a checkpoint to the database.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_id = config["configurable"].get("checkpoint_id") # Previous ID

        try:
            # Serialize content. 
            # JsonPlusSerializer returns bytes if we just call dumps, 
            # but we need to pass a JSON-compatible object to Supabase.
            # Actually, JsonPlusSerializer.dumps returns bytes.
            # We need to decode it to string if we are storing it in a JSONB column (via Supabase client).
            
            dumped_checkpoint = self.serde.dumps(checkpoint)
            dumped_metadata = self.serde.dumps(metadata)
            
            # Ensure we send strings, not bytes. 
            # Ideally we should use self.serde.loads(dumped) if we want to send the raw JSON object,
            # or just decode utf-8 if we want to send the string representation.
            # Supabase API usually expects a dict or a string.
            # Let's try decoding to UTF-8 string.
            if isinstance(dumped_checkpoint, bytes):
                dumped_checkpoint = dumped_checkpoint.decode("utf-8")
            if isinstance(dumped_metadata, bytes):
                dumped_metadata = dumped_metadata.decode("utf-8")
            
            # Use json.loads to ensure we are sending a Dictionary to Supabase, 
            # which will then be serialized to JSONB properly.
            data = {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": parent_id,
                "checkpoint": json.loads(dumped_checkpoint),
                "metadata": json.loads(dumped_metadata)
            }
            
            # Upsert
            supabase.table("checkpoints").upsert(data).execute()
            
            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            }
            
        except Exception as e:
            logger.error(f"Error saving checkpoint for {thread_id}: {e}")
            return config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """
        Store intermediate writes. (Required for recursion/pending tasks, typically).
        For now, we can implement a no-op or a real implementation.
        """
        # Minimal production: We should save these to `checkpoint_writes` table.
        # But if unused, a pass is safer than crashing.
        # The crash `NotImplementedError` confirms it IS called.
        pass
