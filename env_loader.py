"""
Environment Loader — reads .env, validates API keys, checks kill switch.
"""
import os
import sys
from pathlib import Path


def load_env():
    """Load .env file and return validated config dict."""
    env_path = Path(__file__).parent / ".env"

    # Load .env manually (no dependency on python-dotenv required)
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    os.environ[key] = value
    else:
        print("\n  [FATAL] .env file not found!")
        print("  Copy .env.example to .env and add your Alpaca API keys.")
        sys.exit(1)

    api_key = os.getenv("APCA_API_KEY_ID", "")
    api_secret = os.getenv("APCA_API_SECRET_KEY", "")
    kill_switch = os.getenv("KILL_SWITCH", "false").lower() == "true"
    close_on_shutdown = os.getenv("CLOSE_ON_SHUTDOWN", "true").lower() == "true"
    trading_mode = os.getenv("TRADING_MODE", "paper").lower()  # "paper" or "live"

    # ── Validate API keys ──
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        print("\n  [FATAL] APCA_API_KEY_ID is not set in .env")
        sys.exit(1)
    if not api_secret or api_secret == "YOUR_API_SECRET_HERE":
        print("\n  [FATAL] APCA_API_SECRET_KEY is not set in .env")
        sys.exit(1)

    if trading_mode == "live":
        base_url = "https://api.alpaca.markets"
    else:
        base_url = "https://paper-api.alpaca.markets"

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "base_url": base_url,
        "trading_mode": trading_mode,
        "kill_switch": kill_switch,
        "close_on_shutdown": close_on_shutdown,
    }
