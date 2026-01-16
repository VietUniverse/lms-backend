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
    This is the email user used to log into the Anki sync server.
    """
    if not ANKI_AVAILABLE or not mw:
        return None
    
    try:
        # Anki stores sync auth in the profile
        # For Anki 2.1.x, the sync auth is stored differently
        
        # Method 1: Try to get from sync media
        if hasattr(mw, 'pm') and mw.pm:
            # Profile manager has sync info
            profile = mw.pm.profile
            if profile:
                # Check for hkey (sync key) and username
                sync_user = profile.get('syncUser')
                if sync_user:
                    return sync_user
        
        # Method 2: Try to get from sync_auth 
        if hasattr(mw, 'col') and mw.col:
            # Check collection's sync settings
            conf = mw.col.get_config("sync", {})
            if isinstance(conf, dict):
                email = conf.get("username") or conf.get("email")
                if email:
                    return email
        
        # Method 3: Read from Anki's meta file
        if hasattr(mw, 'pm') and mw.pm:
            profile_folder = mw.pm.profileFolder()
            meta_path = os.path.join(profile_folder, "prefs21.db")
            if os.path.exists(meta_path):
                import sqlite3
                conn = sqlite3.connect(meta_path)
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT cast(data as text) FROM profiles WHERE name = 'meta'")
                    row = cursor.fetchone()
                    if row:
                        meta = json.loads(row[0])
                        email = meta.get("syncUser") or meta.get("email")
                        if email:
                            return email
                except Exception:
                    pass
                finally:
                    conn.close()
        
        return None
        
    except Exception as e:
        print(f"Error getting Anki sync email: {e}")
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
