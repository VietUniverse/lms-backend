"""
LMS API Client Module
HTTP client with JWT authentication for communicating with LMS backend.
Supports auto-login via token exchange (SSO with Anki sync).
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple
from . import config


class LMSClientError(Exception):
    """Custom exception for LMS API errors."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class LMSClient:
    """HTTP client for LMS API with JWT authentication."""
    
    def __init__(self):
        self.base_url = config.get_lms_url()
    
    def _make_request(
        self, 
        endpoint: str, 
        method: str = "GET", 
        data: Optional[Dict] = None,
        auth: bool = True,
        raw_response: bool = False
    ) -> Any:
        """Make HTTP request to LMS API."""
        url = f"{self.base_url}{endpoint}"
        
        # Use different headers for binary file download vs JSON API
        if raw_response:
            headers = {
                "Accept": "application/octet-stream",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        
        if auth:
            token = config.get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        
        body = None
        if data:
            body = json.dumps(data).encode("utf-8")
        
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if raw_response:
                    # Return raw bytes (for file download)
                    return response.read(), dict(response.headers)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_json = json.loads(error_body)
                msg = error_json.get("detail") or error_json.get("error") or str(error_json)
            except json.JSONDecodeError:
                msg = error_body
            
            # Handle 401 - try refresh token
            if e.code == 401 and auth:
                if self._refresh_token():
                    # Retry with new token
                    return self._make_request(endpoint, method, data, auth, raw_response)
            
            raise LMSClientError(msg, e.code)
        except urllib.error.URLError as e:
            raise LMSClientError(f"Lỗi kết nối: {str(e.reason)}")
    
    def _refresh_token(self) -> bool:
        """Try to refresh the access token."""
        refresh = config.get_refresh_token()
        if not refresh:
            return False
        
        try:
            result = self._make_request(
                "/api/accounts/token/refresh/",
                method="POST",
                data={"refresh": refresh},
                auth=False
            )
            if "access" in result:
                cfg = config.load_config()
                cfg["access_token"] = result["access"]
                config.save_config(cfg)
                return True
        except LMSClientError:
            pass
        
        return False
    
    def auto_login(self) -> Optional[Dict[str, Any]]:
        """
        Automatically login using Anki sync credentials.
        Uses token exchange with HMAC signature for security.
        
        Returns user info on success, None if auto-login not possible.
        """
        # Get email from Anki sync
        email = config.get_anki_sync_email()
        if not email:
            return None
        
        # Create signature
        timestamp = int(time.time())
        signature = config.create_token_signature(email, timestamp)
        
        try:
            result = self._make_request(
                "/api/anki/token-exchange/",
                method="POST",
                data={
                    "email": email,
                    "timestamp": str(timestamp),
                    "signature": signature
                },
                auth=False
            )
            
            # Store tokens
            config.set_tokens(
                access=result.get("access", ""),
                refresh=result.get("refresh", ""),
                email=email
            )
            
            return result.get("user", {})
            
        except LMSClientError as e:
            print(f"Auto-login failed: {e}")
            return None
    
    def login(self, email: str, password: str) -> Dict[str, Any]:
        """
        Login to LMS with email/password.
        Returns user info on success.
        """
        result = self._make_request(
            "/api/accounts/login/",
            method="POST",
            data={"email": email, "password": password},
            auth=False
        )
        
        # Store tokens
        tokens = result.get("tokens", {})
        config.set_tokens(
            access=tokens.get("access", ""),
            refresh=tokens.get("refresh", ""),
            email=email
        )
        
        return result.get("user", {})
    
    def logout(self) -> None:
        """Clear stored tokens."""
        config.clear_tokens()
    
    def get_my_decks(self) -> List[Dict[str, Any]]:
        """
        Get list of assigned decks for current student.
        Returns: [{ lms_deck_id, title, version, updated_at }]
        """
        return self._make_request("/api/anki/my-decks/")
    
    def download_deck(self, deck_id: int) -> Tuple[bytes, int, str]:
        """
        Download .apkg file for a deck.
        Returns: (file_bytes, lms_deck_id, version)
        """
        content, headers = self._make_request(
            f"/api/anki/deck/{deck_id}/download/",
            raw_response=True
        )
        
        lms_deck_id = int(headers.get("X-LMS-Deck-ID", deck_id))
        version = int(headers.get("X-LMS-Deck-Version", 1))
        
        # Log file size for debugging
        content_length = headers.get("Content-Length", "unknown")
        print(f"[LMS] Downloaded deck {deck_id}: {len(content)} bytes (server reported: {content_length})")
        
        # Verify we got binary data, not JSON error
        if len(content) < 100:
            try:
                error_text = content.decode('utf-8')
                print(f"[LMS] Warning: Received small response, might be error: {error_text[:200]}")
            except:
                pass
        
        return content, lms_deck_id, version
    
    def submit_progress(self, lms_deck_id: int, reviews: List[Dict]) -> Dict[str, Any]:
        """
        Submit batch of reviews for a deck.
        Returns: { status, synced_count, session_id }
        """
        return self._make_request(
            "/api/anki/progress/",
            method="POST",
            data={
                "lms_deck_id": lms_deck_id,
                "reviews": reviews
            }
        )
    
    def test_connection(self) -> bool:
        """Test if LMS backend is reachable."""
        try:
            self._make_request("/api/", auth=False)
            return True
        except LMSClientError:
            return False
