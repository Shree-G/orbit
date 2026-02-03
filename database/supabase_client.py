from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in the environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
