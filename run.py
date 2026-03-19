import subprocess
import sys
import time

def main():
    print("🚀 Starting Orbit System...")
    
    # 1. Start Auth Server (FastAPI)
    print("   -> Launching Auth Server (Port 8000)...")
    auth_process = subprocess.Popen([sys.executable, "-m", "auth.auth_server"])
    
    # Wait a moment for server to spin up
    time.sleep(2)
    
    # 2. Start Telegram Bot
    print("   -> Launching Telegram Bot...")
    bot_process = subprocess.Popen([sys.executable, "main.py"])
    
    print("✅ System Online. Press Ctrl+C to stop.")
    
    try:
        # Keep main script alive
        bot_process.wait()
        auth_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        bot_process.terminate()
        auth_process.terminate()
        print("Goodbye.")

if __name__ == "__main__":
    main()
