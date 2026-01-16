"""
LMS Addon Configuration Module
Handles JWT storage, LMS URL settings, and local deck version tracking.
Now includes auto-detection of Anki sync credentials for SSO.
"""

import json
import os
import time
import hmac
import hashlib
from typing import Optional, Dict, Any

# Try to import Anki modules
try:
    from aqt import mw
    ANKI_AVAILABLE = True
except ImportError:
    mw = None
    ANKI_AVAILABLE = False

# Default LMS Backend URL - Should match your deployment
DEFAULT_LMS_URL = "https://lms.ankivn.com"

# Shared secret for token exchange - MUST match server's ANKI_ADDON_SECRET
# In production, this should be configured securely
ADDON_SECRET = "f1d76aa60054747a400f8a7018579d1dbfde10980c44c8b71b3a891f9e0f8ac2"


def get_addon_dir() -> str:
    """Get addon directory path."""
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path() -> str:
    """Get path to addon config file."""
    return os.path.join(get_addon_dir(), "addon_config.json")


def load_config() -> Dict[str, Any]:
    """Load config from addon_config.json."""
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "lms_url": DEFAULT_LMS_URL,
        "access_token": None,
        "refresh_token": None,
        "user_email": None,
        "deck_versions": {},  # {lms_deck_id: local_version}
        "deck_mappings": {},  # {anki_deck_name: lms_deck_id}
    }


def save_config(config: Dict[str, Any]) -> None:
    """Save config to addon_config.json."""
    config_path = get_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ============================================
# ANKI SYNC CREDENTIALS AUTO-DETECTION
# ============================================

def get_anki_sync_email() -> Optional[str]:
    """
    Get the email/username from Anki's sync configuration.
    Works with Anki 24.x and 25.x (self-hosted sync servers).
    """
    if not ANKI_AVAILABLE or not mw:
        print("LMS: Anki not available")
        return None
    
    try:
        # Method 1: Anki 24+ - Use sync_auth() from profile manager
        if hasattr(mw, 'pm') and mw.pm:
            # sync_auth returns (hkey, username) or None
            try:
                auth = mw.pm.sync_auth()
                if auth:
                    # auth is a NamedTuple with hkey and username
                    if hasattr(auth, 'username') and auth.username:
                        print(f"LMS: Found sync email via sync_auth: {auth.username}")
                        return auth.username
                    # Fallback for older format
                    if isinstance(auth, tuple) and len(auth) >= 2:
                        print(f"LMS: Found sync email via tuple: {auth[1]}")
                        return auth[1]
            except Exception as e:
                print(f"LMS: sync_auth error: {e}")
        
        # Method 2: Check profile directly
        if hasattr(mw, 'pm') and mw.pm:
            try:
                profile = mw.pm.profile
                if profile and isinstance(profile, dict):
                    # Try different keys
                    for key in ['syncUser', 'syncUsername', 'sync_user', 'username']:
                        if key in profile and profile[key]:
                            print(f"LMS: Found sync email in profile[{key}]: {profile[key]}")
                            return profile[key]
            except Exception as e:
                print(f"LMS: profile check error: {e}")
        
        # Method 3: Read from prefs21.db (Anki's profile database)
        if hasattr(mw, 'pm') and mw.pm:
            try:
                base = mw.pm.base
                prefs_path = os.path.join(base, "prefs21.db")
                if os.path.exists(prefs_path):
                    import sqlite3
                    conn = sqlite3.connect(prefs_path, timeout=1)
                    cursor = conn.cursor()
                    try:
                        cursor.execute("SELECT data FROM profiles")
                        for row in cursor.fetchall():
                            try:
                                data = json.loads(row[0])
                                for key in ['syncUser', 'syncUsername', 'username']:
                                    if key in data and data[key]:
                                        print(f"LMS: Found in prefs21.db: {data[key]}")
                                        return data[key]
                            except (json.JSONDecodeError, TypeError):
                                continue
                    finally:
                        conn.close()
            except Exception as e:
                print(f"LMS: prefs21.db error: {e}")
        
        # Method 4: Check sync endpoint config 
        if hasattr(mw, 'pm') and mw.pm:
            try:
                # Get custom sync URL
                sync_endpoint = getattr(mw.pm, 'sync_endpoint', None)
                if sync_endpoint:
                    print(f"LMS: Custom sync endpoint detected: {sync_endpoint}")
            except Exception:
                pass
        
        print("LMS: Could not detect Anki sync email")
        return None
        
    except Exception as e:
        print(f"LMS: Error in get_anki_sync_email: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_token_signature(email: str, timestamp: int) -> str:
    """
    Create HMAC signature for token exchange.
    Must match the server-side verification.
    """
    message = f"{email}:{timestamp}"
    signature = hmac.new(
        ADDON_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


def get_addon_secret() -> str:
    """Get the shared secret for token exchange."""
    return ADDON_SECRET


def set_addon_secret(secret: str) -> None:
    """Set the shared secret (stored in config)."""
    global ADDON_SECRET
    ADDON_SECRET = secret
    config = load_config()
    config["addon_secret"] = secret
    save_config(config)


# ============================================
# JWT TOKEN MANAGEMENT
# ============================================

def get_access_token() -> Optional[str]:
    """Get stored access token."""
    config = load_config()
    return config.get("access_token")


def set_tokens(access: str, refresh: str, email: str) -> None:
    """Store JWT tokens and user email."""
    config = load_config()
    config["access_token"] = access
    config["refresh_token"] = refresh
    config["user_email"] = email
    save_config(config)


def clear_tokens() -> None:
    """Clear stored tokens (logout)."""
    config = load_config()
    config["access_token"] = None
    config["refresh_token"] = None
    config["user_email"] = None
    save_config(config)


def get_refresh_token() -> Optional[str]:
    """Get stored refresh token."""
    config = load_config()
    return config.get("refresh_token")


def get_lms_url() -> str:
    """Get LMS backend URL."""
    config = load_config()
    return config.get("lms_url", DEFAULT_LMS_URL)


def set_lms_url(url: str) -> None:
    """Set LMS backend URL."""
    config = load_config()
    config["lms_url"] = url.rstrip("/")
    save_config(config)


def get_user_email() -> Optional[str]:
    """Get logged in user email."""
    config = load_config()
    return config.get("user_email")


def is_logged_in() -> bool:
    """Check if user is logged in."""
    return get_access_token() is not None


# ============================================
# DECK VERSION MANAGEMENT
# ============================================

def get_deck_version(lms_deck_id: int) -> int:
    """Get local version of a deck."""
    config = load_config()
    return config.get("deck_versions", {}).get(str(lms_deck_id), 0)


def set_deck_version(lms_deck_id: int, version: int) -> None:
    """Set local version of a deck after download."""
    config = load_config()
    if "deck_versions" not in config:
        config["deck_versions"] = {}
    config["deck_versions"][str(lms_deck_id)] = version
    save_config(config)


# ============================================
# DECK MAPPING MANAGEMENT
# ============================================

def get_deck_mapping(anki_deck_name: str) -> Optional[int]:
    """Get LMS deck ID for an Anki deck."""
    config = load_config()
    return config.get("deck_mappings", {}).get(anki_deck_name)


def set_deck_mapping(anki_deck_name: str, lms_deck_id: int) -> None:
    """Map Anki deck name to LMS deck ID."""
    config = load_config()
    if "deck_mappings" not in config:
        config["deck_mappings"] = {}
    config["deck_mappings"][anki_deck_name] = lms_deck_id
    save_config(config)


def get_all_tracked_decks() -> Dict[str, int]:
    """Get all tracked deck mappings."""
    config = load_config()
    return config.get("deck_mappings", {})
