# lms/anki_sync.py
"""
Anki Sync Server Integration Module

Handles user creation/management for the official Anki sync server (Rust version).
Compatible with Anki Desktop 24.x and 25.x.

Key features:
- File locking to prevent race conditions during concurrent user creation
- Docker SDK integration for container restart after user changes
- SQLite read-only access for analytics collection
"""

import os
import os
import logging
from pathlib import Path
from django.conf import settings

try:
    import fcntl
except ImportError:
    fcntl = None

logger = logging.getLogger(__name__)

# Path constants - these can be overridden via Django settings
SYNC_USERS_ENV_FILE = Path(getattr(settings, 'ANKI_SYNC_USERS_FILE', '/app/sync_users.env'))
ANKI_DATA_PATH = Path(getattr(settings, 'ANKI_SYNC_DATA_PATH', '/anki_data'))
ANKI_CONTAINER_NAME = getattr(settings, 'ANKI_SYNC_CONTAINER_NAME', 'ankilms_anki')


def create_anki_user(email: str, password: str) -> bool:
    """
    Create Anki user by:
    1. Acquiring exclusive file lock (prevents race conditions)
    2. Writing to sync_users.env file
    3. Restarting Anki container to load new user
    
    Args:
        email: User's email (used as Anki username)
        password: Plain text password
        
    Returns:
        True if user was created successfully, False otherwise
    """
    try:
        # Ensure directory exists
        SYNC_USERS_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file if it doesn't exist
        if not SYNC_USERS_ENV_FILE.exists():
            SYNC_USERS_ENV_FILE.touch()
        
        # Open file for read+write with exclusive lock
        with open(SYNC_USERS_ENV_FILE, "r+") as f:
            # 1. Acquire exclusive lock (blocks until lock is available)
            fcntl.flock(f, fcntl.LOCK_EX)
            
            try:
                # 2. Read existing users
                f.seek(0)
                existing_users = {}
                for line in f:
                    line = line.strip()
                    if line and line.startswith("SYNC_USER") and '=' in line:
                        key, value = line.split("=", 1)
                        existing_users[key] = value
                
                # 3. Check if user already exists
                for value in existing_users.values():
                    if value.startswith(f"{email}:"):
                        logger.info(f"Anki user {email} already exists")
                        return True
                
                # 4. Find next available user number
                next_num = 1
                while f"SYNC_USER{next_num}" in existing_users:
                    next_num += 1
                
                # 5. Add new user
                existing_users[f"SYNC_USER{next_num}"] = f"{email}:{password}"
                
                # 6. Write back to file (overwrite with new content)
                f.seek(0)
                f.truncate()
                
                # Write header comments
                f.write("# Anki Sync Server Users\n")
                f.write("# Format: SYNC_USER{n}=email:password\n")
                f.write("# Auto-managed by LMS - DO NOT EDIT MANUALLY\n\n")
                
                # Write users sorted by number
                for key in sorted(existing_users.keys(), key=lambda x: int(x.replace('SYNC_USER', ''))):
                    f.write(f"{key}={existing_users[key]}\n")
                
            finally:
                # 7. Release lock (also released automatically when file closes)
                fcntl.flock(f, fcntl.LOCK_UN)
        
        # 8. Restart Anki container to load new user
        restart_success = _restart_anki_container()
        if not restart_success:
            logger.warning(f"Anki container restart failed, user {email} may not be available until manual restart")
        
        logger.info(f"Created Anki user: {email}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating Anki user {email}: {e}")
        return False


def change_anki_password(email: str, new_password: str) -> bool:
    """
    Change Anki user password by updating env file and restarting container.
    Uses file locking to prevent race conditions.
    
    Args:
        email: User's email
        new_password: New plain text password
        
    Returns:
        True if password was changed successfully, False otherwise
    """
    try:
        if not SYNC_USERS_ENV_FILE.exists():
            # User doesn't exist, create them
            return create_anki_user(email, new_password)
        
        with open(SYNC_USERS_ENV_FILE, "r+") as f:
            # Acquire exclusive lock
            fcntl.flock(f, fcntl.LOCK_EX)
            
            try:
                # Read existing users
                f.seek(0)
                existing_users = {}
                for line in f:
                    line = line.strip()
                    if line and line.startswith("SYNC_USER") and '=' in line:
                        key, value = line.split("=", 1)
                        existing_users[key] = value
                
                # Find and update user
                found = False
                for key, value in existing_users.items():
                    if value.startswith(f"{email}:"):
                        existing_users[key] = f"{email}:{new_password}"
                        found = True
                        break
                
                if not found:
                    # Release lock and create new user
                    fcntl.flock(f, fcntl.LOCK_UN)
                    return create_anki_user(email, new_password)
                
                # Write back
                f.seek(0)
                f.truncate()
                
                # Write header
                f.write("# Anki Sync Server Users\n")
                f.write("# Format: SYNC_USER{n}=email:password\n")
                f.write("# Auto-managed by LMS - DO NOT EDIT MANUALLY\n\n")
                
                for key in sorted(existing_users.keys(), key=lambda x: int(x.replace('SYNC_USER', ''))):
                    f.write(f"{key}={existing_users[key]}\n")
                    
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        
        _restart_anki_container()
        logger.info(f"Changed Anki password for: {email}")
        return True
        
    except Exception as e:
        logger.error(f"Error changing Anki password for {email}: {e}")
        return False


def delete_anki_user(email: str) -> bool:
    """
    Delete Anki user from sync server.
    Note: This does NOT delete user's collection data from disk.
    
    Args:
        email: User's email to delete
        
    Returns:
        True if user was deleted, False otherwise
    """
    try:
        if not SYNC_USERS_ENV_FILE.exists():
            return True
        
        with open(SYNC_USERS_ENV_FILE, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            
            try:
                f.seek(0)
                existing_users = {}
                for line in f:
                    line = line.strip()
                    if line and line.startswith("SYNC_USER") and '=' in line:
                        key, value = line.split("=", 1)
                        existing_users[key] = value
                
                # Find and remove user
                key_to_delete = None
                for key, value in existing_users.items():
                    if value.startswith(f"{email}:"):
                        key_to_delete = key
                        break
                
                if key_to_delete:
                    del existing_users[key_to_delete]
                    
                    # Renumber remaining users
                    new_users = {}
                    for i, (_, value) in enumerate(sorted(
                        existing_users.items(), 
                        key=lambda x: int(x[0].replace('SYNC_USER', ''))
                    ), 1):
                        new_users[f"SYNC_USER{i}"] = value
                    
                    # Write back
                    f.seek(0)
                    f.truncate()
                    f.write("# Anki Sync Server Users\n")
                    f.write("# Format: SYNC_USER{n}=email:password\n")
                    f.write("# Auto-managed by LMS - DO NOT EDIT MANUALLY\n\n")
                    
                    for key in sorted(new_users.keys(), key=lambda x: int(x.replace('SYNC_USER', ''))):
                        f.write(f"{key}={new_users[key]}\n")
                    
                    logger.info(f"Deleted Anki user: {email}")
                    
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        
        _restart_anki_container()
        return True
        
    except Exception as e:
        logger.error(f"Error deleting Anki user {email}: {e}")
        return False


def _restart_anki_container() -> bool:
    """
    Restart Anki sync container to reload environment variables.
    
    Prioritizes Docker SDK since docker CLI may not be available in container.
    Falls back to subprocess commands if SDK fails.
    
    Returns:
        True if container was restarted successfully, False otherwise
    """
    import os
    
    container_name = os.environ.get('ANKI_SYNC_CONTAINER_NAME', ANKI_CONTAINER_NAME)
    env_file_path = os.environ.get('ANKI_SYNC_USERS_FILE', str(SYNC_USERS_ENV_FILE))
    
    # Method 1: Try Docker SDK (preferred - works inside container)
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_name)
        
        # Read current env file
        env_vars = {'SYNC_BASE': '/data'}
        try:
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key] = value
        except Exception as e:
            logger.warning(f"Could not read env file: {e}")
        
        # Get container config
        image = container.image.tags[0] if container.image.tags else container.image.id
        
        # Get volumes from existing container
        mounts = container.attrs.get('Mounts', [])
        volumes = {}
        for mount in mounts:
            if mount['Type'] == 'volume':
                volumes[mount['Name']] = {'bind': mount['Destination'], 'mode': 'rw'}
            elif mount['Type'] == 'bind':
                volumes[mount['Source']] = {'bind': mount['Destination'], 'mode': mount.get('Mode', 'rw')}
        
        # Get ports
        ports = container.attrs.get('HostConfig', {}).get('PortBindings', {})
        
        # Stop and remove old container
        container.stop(timeout=10)
        container.remove()
        
        # Recreate with new environment
        new_container = client.containers.run(
            image,
            name=container_name,
            detach=True,
            restart_policy={'Name': 'always'},
            environment=env_vars,
            volumes=volumes if volumes else {'/var/lib/docker/volumes/lms-backend_anki_data/_data': {'bind': '/data', 'mode': 'rw'}},
            ports={'8080/tcp': 8080},
        )
        
        logger.info(f"Recreated container {container_name} via Docker SDK with {len(env_vars)} env vars")
        return True
        
    except ImportError:
        logger.warning("Docker SDK not installed")
    except Exception as docker_err:
        logger.warning(f"Docker SDK method failed: {docker_err}")
    
    # Method 2: Try subprocess docker compose (for systems with docker CLI)
    try:
        import subprocess
        
        compose_dir = os.environ.get('COMPOSE_PROJECT_DIR', None)
        if not compose_dir:
            for possible_dir in ['/var/www/lms-backend', '/opt/lms-backend', '/app']:
                if os.path.exists(f'{possible_dir}/docker-compose.prod.yml'):
                    compose_dir = possible_dir
                    break
        
        if compose_dir and os.path.exists(f'{compose_dir}/docker-compose.prod.yml'):
            result = subprocess.run(
                ['docker', 'compose', '-f', 'docker-compose.prod.yml', 'up', '-d', '--force-recreate', 'anki-sync'],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                logger.info(f"Restarted Anki container via docker compose from {compose_dir}")
                return True
            else:
                logger.warning(f"docker compose restart failed: {result.stderr}")
        
        # Try simple docker restart
        result = subprocess.run(
            ['docker', 'restart', container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            logger.info(f"Restarted container {container_name} via docker CLI")
            return True
        else:
            logger.error(f"Docker CLI restart failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Container restart timed out")
        return False
    except Exception as e:
        logger.error(f"Error restarting Anki container: {e}")
        return False


def get_user_collection_path(email: str) -> Path:
    """
    Get path to user's Anki collection database.
    
    Args:
        email: User's email (used as folder name by Anki sync server)
        
    Returns:
        Path to collection.anki2 file
    """
    return ANKI_DATA_PATH / email / "collection.anki2"


def user_has_synced(email: str) -> bool:
    """
    Check if user has synced at least once (collection exists).
    
    Args:
        email: User's email
        
    Returns:
        True if user has a collection file
    """
    collection_path = get_user_collection_path(email)
    return collection_path.exists()


# Legacy function aliases for backward compatibility
def add_user(username: str, password: str) -> tuple:
    """Legacy wrapper for create_anki_user."""
    success = create_anki_user(username, password)
    return (success, "User created" if success else "Failed to create user")


def change_password(username: str, password: str) -> tuple:
    """Legacy wrapper for change_anki_password."""
    success = change_anki_password(username, password)
    return (success, "Password changed" if success else "Failed to change password")


def delete_user(username: str) -> tuple:
    """Legacy wrapper for delete_anki_user."""
    success = delete_anki_user(username)
    return (success, "User deleted" if success else "Failed to delete user")
