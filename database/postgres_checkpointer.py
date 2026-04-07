import logging
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from config.settings import SUPABASE_DB_URL

logger = logging.getLogger(__name__)

_pool = None

async def get_checkpointer() -> AsyncPostgresSaver:
    """
    Returns a connected AsyncPostgresSaver instance, 
    managing a global connection pool lazily.
    """
    global _pool
    if _pool is None:
        logger.info("Initializing Postgres checkpointer connection pool...")
        # prepare_threshold=0 is highly recommended for PgBouncer / Supabase serverless connections
        _pool = AsyncConnectionPool(
            conninfo=SUPABASE_DB_URL,
            max_size=20,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False
        )
        await _pool.open()
        
        # Ensure the required langgraph tables (checkpoints, checkpoint_writes, etc.) exist
        saver = AsyncPostgresSaver(_pool)
        await saver.setup()
        logger.info("Postgres checkpointer initialized and tables verified.")
        
    return AsyncPostgresSaver(_pool)

async def close_checkpointer():
    """
    Safely shuts down the global Postgres connection pool to prevent asyncio loop errors on exit.
    """
    global _pool
    if _pool is not None:
        logger.info("Closing global Postgres connection pool...")
        await _pool.close()
        _pool = None
