"""
LMS Anki Addon
Main entry point - registers hooks and adds menu items.

Features:
- AUTO-LOGIN: Automatically uses Anki sync credentials (SSO)
- Auto-download assigned decks when Anki syncs
- Cache reviews locally, batch upload to LMS
- Only track official LMS decks (anti-spam)
"""

from aqt import mw, gui_hooks
from aqt.qt import QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from aqt.utils import showInfo, showWarning, tooltip

from . import config
from .api_client import LMSClient, LMSClientError
from . import sync_hook
from . import progress_cache


# ============================================
# AUTO-LOGIN LOGIC
# ============================================

def ensure_logged_in() -> bool:
    """
    Ensure user is logged in. Tries auto-login first.
    Returns True if logged in, False otherwise.
    """
    print("LMS: Checking login status...")
    
    if config.is_logged_in():
        print("LMS: Already logged in")
        return True
    
    # Check if we can get Anki sync email
    sync_email = config.get_anki_sync_email()
    print(f"LMS: Detected Anki sync email: {sync_email}")
    
    if not sync_email:
        print("LMS: Cannot detect Anki sync email - manual login required")
        return False
    
    # Try auto-login using Anki sync credentials
    print("LMS: Attempting auto-login via token exchange...")
    client = LMSClient()
    user = client.auto_login()
    
    if user:
        print(f"LMS: Auto-login successful for {user.get('email', 'User')}")
        tooltip(f"LMS: Đã tự động đăng nhập - {user.get('email', 'User')}")
        return True
    
    print("LMS: Auto-login failed")
    return False


def debug_sync_info():
    """Debug function to show sync detection info."""
    from aqt.utils import showText
    
    info_lines = ["=== LMS Addon Debug Info ===\n"]
    
    # Check Anki sync email
    email = config.get_anki_sync_email()
    info_lines.append(f"Anki Sync Email: {email or 'NOT DETECTED'}")
    
    # Check LMS status
    info_lines.append(f"LMS URL: {config.get_lms_url()}")
    info_lines.append(f"LMS Logged In: {config.is_logged_in()}")
    info_lines.append(f"LMS User: {config.get_user_email() or 'None'}")
    
    # Check profile manager
    if mw.pm:
        info_lines.append(f"\n--- Anki Profile Manager ---")
        info_lines.append(f"Base path: {mw.pm.base}")
        
        # Try sync_auth
        try:
            auth = mw.pm.sync_auth()
            info_lines.append(f"sync_auth(): {auth}")
        except Exception as e:
            info_lines.append(f"sync_auth() error: {e}")
        
        # Check profile dict
        try:
            profile = mw.pm.profile
            info_lines.append(f"profile type: {type(profile)}")
            if profile:
                info_lines.append(f"profile keys: {list(profile.keys()) if isinstance(profile, dict) else 'N/A'}")
        except Exception as e:
            info_lines.append(f"profile error: {e}")
    
    showText("\n".join(info_lines), title="LMS Debug Info")


# ============================================
# LOGIN/SETTINGS DIALOGS
# ============================================

class LoginDialog(QDialog):
    """Manual login dialog for LMS integration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Đăng nhập LMS")
        self.setFixedWidth(350)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout()
        
        # LMS URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("LMS URL:"))
        self.url_input = QLineEdit()
        self.url_input.setText(config.get_lms_url())
        self.url_input.setPlaceholderText("https://lms-backend.example.com")
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)
        
        # Email
        email_layout = QHBoxLayout()
        email_layout.addWidget(QLabel("Email:"))
        self.email_input = QLineEdit()
        # Pre-fill with Anki sync email if available
        sync_email = config.get_anki_sync_email()
        if sync_email:
            self.email_input.setText(sync_email)
        self.email_input.setPlaceholderText("student@example.com")
        email_layout.addWidget(self.email_input)
        layout.addLayout(email_layout)
        
        # Password
        pwd_layout = QHBoxLayout()
        pwd_layout.addWidget(QLabel("Mật khẩu:"))
        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_layout.addWidget(self.pwd_input)
        layout.addLayout(pwd_layout)
        
        # Status label
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("Đăng nhập")
        self.login_btn.clicked.connect(self._on_login)
        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def _on_login(self):
        url = self.url_input.text().strip()
        email = self.email_input.text().strip()
        password = self.pwd_input.text()
        
        if not url or not email or not password:
            self.status_label.setText("Vui lòng điền đầy đủ thông tin.")
            return
        
        # Save URL
        config.set_lms_url(url)
        
        # Try login
        self.status_label.setText("Đang đăng nhập...")
        self.login_btn.setEnabled(False)
        
        try:
            client = LMSClient()
            user = client.login(email, password)
            
            showInfo(f"Đăng nhập thành công!\nXin chào {user.get('full_name', email)}")
            self.accept()
            
        except LMSClientError as e:
            self.status_label.setText(f"Lỗi: {e}")
        except Exception as e:
            self.status_label.setText(f"Lỗi kết nối: {e}")
        finally:
            self.login_btn.setEnabled(True)


class SettingsDialog(QDialog):
    """Settings dialog showing current status."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LMS Addon - Cài đặt")
        self.setFixedWidth(400)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout()
        
        # Anki sync email
        anki_email = config.get_anki_sync_email()
        if anki_email:
            layout.addWidget(QLabel(f"📧 Anki Sync: {anki_email}"))
        else:
            layout.addWidget(QLabel("⚠️ Chưa đăng nhập Anki Sync"))
        
        # LMS Status
        email = config.get_user_email()
        if email:
            status_text = f"✓ LMS: Đã đăng nhập ({email})"
        else:
            status_text = "✗ LMS: Chưa đăng nhập"
        
        layout.addWidget(QLabel(status_text))
        layout.addWidget(QLabel(f"🌐 URL: {config.get_lms_url()}"))
        
        # Cache stats
        stats = progress_cache.get_cache_stats()
        layout.addWidget(QLabel(f"\n📊 Reviews đang chờ: {stats['total_reviews']}"))
        
        # Tracked decks
        tracked = config.get_all_tracked_decks()
        layout.addWidget(QLabel(f"📚 Deck đang theo dõi: {len(tracked)}"))
        
        # Actions
        btn_layout = QHBoxLayout()
        
        if email:
            logout_btn = QPushButton("Đăng xuất")
            logout_btn.clicked.connect(self._on_logout)
            btn_layout.addWidget(logout_btn)
            
            sync_btn = QPushButton("Đồng bộ ngay")
            sync_btn.clicked.connect(self._on_sync)
            btn_layout.addWidget(sync_btn)
        else:
            login_btn = QPushButton("Đăng nhập thủ công")
            login_btn.clicked.connect(self._on_login)
            btn_layout.addWidget(login_btn)
        
        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def _on_logout(self):
        config.clear_tokens()
        showInfo("Đã đăng xuất.")
        self.close()
    
    def _on_login(self):
        self.close()
        show_login_dialog()
    
    def _on_sync(self):
        self.close()
        sync_hook.on_sync()


# ============================================
# MENU ACTIONS
# ============================================

def show_login_dialog():
    """Show login dialog."""
    dialog = LoginDialog(mw)
    dialog.exec()


def show_settings():
    """Show settings dialog."""
    dialog = SettingsDialog(mw)
    dialog.exec()


def do_lms_sync():
    """Trigger LMS sync from menu."""
    print("[LMS] Menu sync triggered")
    
    try:
        if not ensure_logged_in():
            print("[LMS] Auto-login failed, showing login dialog")
            # Auto-login failed, show manual login
            show_login_dialog()
            if not config.is_logged_in():
                print("[LMS] Still not logged in after dialog")
                return
        
        print("[LMS] Calling sync_hook.on_sync()")
        sync_hook.on_sync()
        print("[LMS] Sync completed")
    except Exception as e:
        import traceback
        print(f"[LMS] Menu sync error: {traceback.format_exc()}")
        showWarning(f"Lỗi đồng bộ: {e}")


# ============================================
# HOOKS
# ============================================

def on_reviewer_did_answer_card(reviewer, card, ease):
    """Hook: Called when user answers a card."""
    sync_hook.on_review_card(reviewer, card, ease)


def on_sync_will_start():
    """
    Hook: Called before Anki sync starts.
    AUTO-LOGIN and sync LMS decks here!
    """
    # Try auto-login first
    if not ensure_logged_in():
        print("LMS: Auto-login không thành công, bỏ qua sync LMS")
        return
    
    try:
        client = LMSClient()
        
        # Download new decks
        tooltip("LMS: Đang kiểm tra deck mới...")
        sync_hook.on_sync()
        
    except Exception as e:
        print(f"LMS sync error: {e}")


def on_sync_did_finish():
    """Hook: Called after Anki sync finishes."""
    if not config.is_logged_in():
        return
    
    # Upload pending progress
    try:
        client = LMSClient()
        synced = sync_hook._upload_progress(client)
        if synced:
            tooltip(f"LMS: Đã đồng bộ {synced} reviews")
    except Exception as e:
        print(f"LMS progress sync error: {e}")


def on_profile_loaded():
    """Hook: Called when profile is loaded."""
    # Try auto-login when profile opens
    if ensure_logged_in():
        count = sync_hook.scan_and_register_decks()
        if count:
            print(f"LMS: Registered {count} decks")


# ============================================
# ADDON INITIALIZATION
# ============================================

def setup_menu():
    """Add menu items to Anki."""
    menu = mw.form.menuTools.addMenu("LMS")
    
    # Sync action (primary)
    sync_action = QAction("🔄 Đồng bộ LMS", mw)
    sync_action.triggered.connect(do_lms_sync)
    menu.addAction(sync_action)
    
    menu.addSeparator()
    
    # Login action
    login_action = QAction("Đăng nhập thủ công", mw)
    login_action.triggered.connect(show_login_dialog)
    menu.addAction(login_action)
    
    # Settings action
    settings_action = QAction("Cài đặt", mw)
    settings_action.triggered.connect(show_settings)
    menu.addAction(settings_action)
    
    menu.addSeparator()
    
    # Debug action
    debug_action = QAction("🐛 Debug Info", mw)
    debug_action.triggered.connect(debug_sync_info)
    menu.addAction(debug_action)


def register_hooks():
    """Register Anki hooks."""
    # Review hook - cache locally
    gui_hooks.reviewer_did_answer_card.append(on_reviewer_did_answer_card)
    
    # Sync hooks - auto-login and sync
    gui_hooks.sync_will_start.append(on_sync_will_start)
    gui_hooks.sync_did_finish.append(on_sync_did_finish)
    
    # Profile loaded hook
    gui_hooks.profile_did_open.append(on_profile_loaded)


# Initialize addon when Anki starts
setup_menu()
register_hooks()

print("LMS Addon loaded! Addon sẽ tự động đăng nhập khi bạn Sync.")
