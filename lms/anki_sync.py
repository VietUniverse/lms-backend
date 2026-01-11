# lms/anki_sync.py
import subprocess
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

ANKI_CONTAINER_NAME = getattr(settings, 'ANKI_SYNC_CONTAINER', 'anki-sync')

def run_ankisyncd_command(args):
    """
    Run command inside Anki container via Docker Socket.
    """
    # Lệnh đầy đủ: docker exec -i anki-sync ankisyncd <args>
    cmd = ['docker', 'exec', '-i', ANKI_CONTAINER_NAME, 'ankisyncd'] + args
    
    try:
        # timeout=5s là đủ, tránh treo server Django
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0:
            logger.error(f"Anki Sync Error: {result.stderr}")
            return False, result.stderr.strip()
            
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("Anki Sync Command Timed Out")
        return False, "Timeout"
    except FileNotFoundError:
        logger.error("Docker command not found. Is Docker CLI installed in backend container?")
        return False, "Docker CLI missing"
    except Exception as e:
        logger.error(f"Anki Sync Exception: {str(e)}")
        return False, str(e)

def add_user(username, password):
    """Add new user to Anki Sync Server."""
    return run_ankisyncd_command(['user', '--add', username, password])

def change_password(username, password):
    """Change user password."""
    return run_ankisyncd_command(['user', '--pass', username, password])

def delete_user(username):
    """Delete user from Anki Sync Server."""
    return run_ankisyncd_command(['user', '--del', username])

def sync_user_from_lms(user, raw_password):
    """
    Sync LMS user to Anki Sync Server.
    Must be called with RAW password (e.g. during login/signup).
    """
    return add_user(user.email, raw_password)
