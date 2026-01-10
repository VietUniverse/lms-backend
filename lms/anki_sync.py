# lms/anki_sync.py
import subprocess
from django.conf import settings

ANKI_CONTAINER_NAME = getattr(settings, 'ANKI_SYNC_CONTAINER', 'anki-sync')

def run_command(cmd_list, input_text=None):
    """
    Run command inside docker container.
    """
    full_cmd = ['docker', 'exec', '-i', ANKI_CONTAINER_NAME] + cmd_list
    
    try:
        result = subprocess.run(
            full_cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stdout.strip() + result.stderr.strip()
    except Exception as e:
        return False, str(e)

def add_user(username, password):
    """
    Add user using ankisyncd-cli.
    Command: python3 -m ankisyncd_cli adduser <username>
    Input: password
    """
    # Try different command variations if one fails (path varies by image version)
    cmds = [
        ['python3', '-m', 'ankisyncd_cli', 'adduser', username], # Common
        ['./ankisyncctl.py', 'adduser', username],               # Older
    ]
    
    for cmd in cmds:
        success, output = run_command(cmd, input_text=f"{password}\n")
        if success: 
            return True, output
        if "already exists" in output:
            return True, "User exists"
            
    return False, "Failed to add user"

def change_password(username, password):
    """
    Change password.
    Command: python3 -m ankisyncd_cli passwd <username>
    """
    cmds = [
        ['python3', '-m', 'ankisyncd_cli', 'passwd', username],
        ['./ankisyncctl.py', 'passwd', username],
    ]
    
    for cmd in cmds:
        success, output = run_command(cmd, input_text=f"{password}\n")
        if success: return True, output
            
    return False, "Failed to change password"

def sync_user_from_lms(user, raw_password):
    """
    Sync LMS user to Anki Sync Server.
    Must be called with RAW password (e.g. during login/signup).
    """
    return add_user(user.email, raw_password)
