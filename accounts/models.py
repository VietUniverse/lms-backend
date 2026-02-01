from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = (
        ("teacher", "Teacher"),
        ("student", "Student"),
    )

    # giữ username để tương thích admin, nhưng login bằng email
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="student")

    # ============================================
    # GAMIFICATION FIELDS (Phase 1)
    # ============================================
    xp = models.IntegerField(default=0, help_text="Experience points")
    level = models.IntegerField(default=1, help_text="Current level")
    coin_balance = models.IntegerField(default=0, help_text="Coin balance")
    shield_count = models.IntegerField(default=1, help_text="Streak shields (1 free at start)")

    # ============================================
    # PROFILE & SETTINGS FIELDS
    # ============================================
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    
    # JSON fields for settings
    notification_settings = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"daily_reminder": true, "streak_warning": true, "achievements": true, "marketing": false}'
    )
    preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"dark_mode": false, "sound_effects": true, "language": "vi", "cards_per_day": 20}'
    )
    
    # Soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]


    def __str__(self):
        return self.email

    # ============================================
    # GAMIFICATION METHODS
    # ============================================
    def add_xp(self, amount: int) -> bool:
        """Add XP and check for level up. Returns True if leveled up."""
        self.xp += amount
        leveled_up = False
        
        # Level formula: XP needed = level² × 100
        while self.xp >= self.xp_for_next_level():
            self.level += 1
            leveled_up = True
        
        self.save(update_fields=['xp', 'level'])
        return leveled_up

    def xp_for_next_level(self) -> int:
        """Calculate XP needed for next level."""
        return self.level ** 2 * 100

    def xp_progress(self) -> dict:
        """Get XP progress to next level."""
        current_level_xp = (self.level - 1) ** 2 * 100 if self.level > 1 else 0
        next_level_xp = self.xp_for_next_level()
        progress_xp = self.xp - current_level_xp
        needed_xp = next_level_xp - current_level_xp
        return {
            "current_xp": self.xp,
            "level": self.level,
            "progress_xp": progress_xp,
            "needed_xp": needed_xp,
            "percentage": round(progress_xp / needed_xp * 100, 1) if needed_xp > 0 else 100
        }

    def add_coins(self, amount: int, reason: str = "") -> None:
        """Add coins to balance."""
        from lms.models import CoinTransaction
        self.coin_balance += amount
        self.save(update_fields=['coin_balance'])
        CoinTransaction.objects.create(
            user=self,
            amount=amount,
            transaction_type='EARN',
            reason=reason
        )

    def spend_coins(self, amount: int, reason: str = "") -> bool:
        """Spend coins. Returns True if successful, False if insufficient balance."""
        if self.coin_balance < amount:
            return False
        from lms.models import CoinTransaction
        self.coin_balance -= amount
        self.save(update_fields=['coin_balance'])
        CoinTransaction.objects.create(
            user=self,
            amount=-amount,
            transaction_type='SPEND',
            reason=reason
        )
        return True

    def use_shield(self) -> bool:
        """Use a shield to protect streak. Returns True if shield used."""
        if self.shield_count > 0:
            self.shield_count -= 1
            self.save(update_fields=['shield_count'])
            return True
        return False

    def buy_shield(self, price: int = 25) -> bool:
        """Buy a shield with coins. Returns True if successful."""
        if self.spend_coins(price, "Mua Khiên Bảo Vệ"):
            self.shield_count += 1
            self.save(update_fields=['shield_count'])
            return True
        return False

