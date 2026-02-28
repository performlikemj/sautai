# chefs/models/proactive.py
"""
Sous Chef Proactive Engine Models.

This module provides:
- ChefProactiveSettings: Notification preferences and feature toggles
- ChefOnboardingState: Onboarding journey tracking and milestones
- ChefNotification: Queued notifications for the proactive engine

Design principles:
- Master switch OFF by default (chefs must opt-in)
- Per-feature granular control
- Progressive onboarding with milestone tracking
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


# ═══════════════════════════════════════════════════════════════════════════════
# PROACTIVE SETTINGS (Notification Preferences)
# ═══════════════════════════════════════════════════════════════════════════════

class ChefProactiveSettings(models.Model):
    """
    Chef's proactive notification preferences.

    Master switch is OFF by default - chefs must explicitly opt-in
    to receive proactive reminders.
    """
    chef = models.OneToOneField(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='proactive_settings'
    )

    # Master switch - OFF by default
    enabled = models.BooleanField(
        default=False,
        help_text="Master switch to enable/disable all proactive features"
    )

    # Feature toggles (what to notify about)
    notify_birthdays = models.BooleanField(
        default=True,
        help_text="Notify about upcoming client birthdays"
    )
    notify_anniversaries = models.BooleanField(
        default=True,
        help_text="Notify about anniversaries and special dates"
    )
    notify_followups = models.BooleanField(
        default=True,
        help_text="Remind to follow up with inactive clients"
    )
    notify_todos = models.BooleanField(
        default=True,
        help_text="Remind about to-do items"
    )
    notify_seasonal = models.BooleanField(
        default=True,
        help_text="Suggest seasonal ingredients and menus"
    )
    notify_milestones = models.BooleanField(
        default=True,
        help_text="Celebrate client milestones (e.g., 10th order)"
    )
    notify_cert_expiry = models.BooleanField(
        default=True,
        help_text="Notify about expiring certifications (food handler, insurance)"
    )

    # Lead days for birthday/anniversary notifications
    birthday_lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="Days before birthday to notify"
    )
    anniversary_lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="Days before anniversary to notify"
    )

    # Followup threshold (days since last interaction)
    followup_threshold_days = models.PositiveSmallIntegerField(
        default=30,
        help_text="Days of inactivity before suggesting follow-up"
    )

    # Frequency settings
    FREQUENCY_REALTIME = 'realtime'
    FREQUENCY_DAILY = 'daily'
    FREQUENCY_WEEKLY = 'weekly'

    FREQUENCY_CHOICES = [
        (FREQUENCY_REALTIME, 'Real-time'),
        (FREQUENCY_DAILY, 'Daily digest'),
        (FREQUENCY_WEEKLY, 'Weekly digest'),
    ]

    notification_frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default=FREQUENCY_DAILY,
        help_text="How often to receive notifications"
    )

    # Channel preferences
    channel_in_app = models.BooleanField(
        default=True,
        help_text="Show notifications in the app"
    )
    channel_email = models.BooleanField(
        default=False,
        help_text="Send notification emails"
    )
    channel_push = models.BooleanField(
        default=False,
        help_text="Send push notifications (future)"
    )

    # Quiet hours
    quiet_hours_enabled = models.BooleanField(
        default=False,
        help_text="Enable quiet hours"
    )
    quiet_hours_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Start of quiet hours (e.g., 22:00)"
    )
    quiet_hours_end = models.TimeField(
        null=True,
        blank=True,
        help_text="End of quiet hours (e.g., 08:00)"
    )
    quiet_hours_timezone = models.CharField(
        max_length=50,
        default='UTC',
        help_text="Timezone for quiet hours"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Chef Proactive Settings'
        verbose_name_plural = 'Chef Proactive Settings'

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"Proactive settings for Chef #{self.chef_id} ({status})"

    @classmethod
    def get_or_create_for_chef(cls, chef) -> 'ChefProactiveSettings':
        """Get or create settings with sensible defaults (master switch OFF)."""
        settings_obj, _ = cls.objects.get_or_create(chef=chef)
        return settings_obj

    def is_within_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        if not self.quiet_hours_enabled or not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        import pytz
        try:
            tz = pytz.timezone(self.quiet_hours_timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            tz = pytz.UTC

        now = timezone.now().astimezone(tz).time()
        start = self.quiet_hours_start
        end = self.quiet_hours_end

        # Handle overnight quiet hours (e.g., 22:00 - 08:00)
        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end


# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING STATE (Journey Tracking)
# ═══════════════════════════════════════════════════════════════════════════════

class ChefOnboardingState(models.Model):
    """
    Tracks a chef's onboarding journey through the Sous Chef assistant.

    Follows progressive disclosure pattern - show features as chef
    demonstrates readiness.
    """
    chef = models.OneToOneField(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='onboarding_state'
    )

    # Welcome & Setup Flow
    welcomed = models.BooleanField(
        default=False,
        help_text="Has seen welcome modal"
    )
    welcomed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When chef saw welcome modal"
    )

    setup_started = models.BooleanField(
        default=False,
        help_text="Has started the setup wizard"
    )
    setup_started_at = models.DateTimeField(
        null=True,
        blank=True
    )

    setup_completed = models.BooleanField(
        default=False,
        help_text="Has completed the setup wizard"
    )
    setup_completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    setup_skipped = models.BooleanField(
        default=False,
        help_text="Skipped the setup wizard"
    )
    setup_skipped_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # Personality Setup (from wizard step 2)
    personality_set = models.BooleanField(
        default=False,
        help_text="Has set communication style"
    )
    personality_choice = models.CharField(
        max_length=50,
        blank=True,
        help_text="Selected personality: professional, friendly, efficient"
    )

    # First Actions (milestones)
    first_dish_added = models.BooleanField(
        default=False,
        help_text="Has added their first dish"
    )
    first_dish_added_at = models.DateTimeField(
        null=True,
        blank=True
    )

    first_client_added = models.BooleanField(
        default=False,
        help_text="Has added their first client (platform or lead)"
    )
    first_client_added_at = models.DateTimeField(
        null=True,
        blank=True
    )

    first_conversation = models.BooleanField(
        default=False,
        help_text="Has had their first Sous Chef conversation"
    )
    first_conversation_at = models.DateTimeField(
        null=True,
        blank=True
    )

    first_memory_saved = models.BooleanField(
        default=False,
        help_text="Has saved their first memory"
    )
    first_memory_saved_at = models.DateTimeField(
        null=True,
        blank=True
    )

    first_order_completed = models.BooleanField(
        default=False,
        help_text="Has completed their first order"
    )
    first_order_completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    proactive_enabled = models.BooleanField(
        default=False,
        help_text="Has enabled proactive features"
    )
    proactive_enabled_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # Tips tracking (JSON stores list of shown tip IDs)
    tips_shown = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tip IDs that have been shown"
    )
    tips_dismissed = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tip IDs that have been permanently dismissed"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Chef Onboarding State'
        verbose_name_plural = 'Chef Onboarding States'

    def __str__(self):
        status = "completed" if self.setup_completed else "in progress"
        return f"Onboarding for Chef #{self.chef_id} ({status})"

    @classmethod
    def get_or_create_for_chef(cls, chef) -> 'ChefOnboardingState':
        """Get or create onboarding state."""
        state, _ = cls.objects.get_or_create(chef=chef)
        return state

    def mark_welcomed(self):
        """Mark that chef has seen the welcome modal."""
        if not self.welcomed:
            self.welcomed = True
            self.welcomed_at = timezone.now()
            self.save(update_fields=['welcomed', 'welcomed_at', 'updated_at'])

    def mark_setup_started(self):
        """Mark that chef has started the setup wizard."""
        if not self.setup_started:
            self.setup_started = True
            self.setup_started_at = timezone.now()
            self.save(update_fields=['setup_started', 'setup_started_at', 'updated_at'])

    def mark_setup_completed(self):
        """Mark that chef has completed the setup wizard."""
        if not self.setup_completed:
            self.setup_completed = True
            self.setup_completed_at = timezone.now()
            self.setup_skipped = False  # Clear skipped if they completed
            self.save(update_fields=['setup_completed', 'setup_completed_at', 'setup_skipped', 'updated_at'])

    def mark_setup_skipped(self):
        """Mark that chef has skipped the setup wizard."""
        if not self.setup_skipped and not self.setup_completed:
            self.setup_skipped = True
            self.setup_skipped_at = timezone.now()
            self.save(update_fields=['setup_skipped', 'setup_skipped_at', 'updated_at'])

    def record_milestone(self, milestone_name: str):
        """
        Record a milestone achievement.

        Valid milestones:
        - first_dish, first_client, first_conversation,
        - first_memory, first_order, proactive_enabled
        """
        field_map = {
            'first_dish': ('first_dish_added', 'first_dish_added_at'),
            'first_client': ('first_client_added', 'first_client_added_at'),
            'first_conversation': ('first_conversation', 'first_conversation_at'),
            'first_memory': ('first_memory_saved', 'first_memory_saved_at'),
            'first_order': ('first_order_completed', 'first_order_completed_at'),
            'proactive_enabled': ('proactive_enabled', 'proactive_enabled_at'),
        }

        if milestone_name not in field_map:
            return False

        bool_field, time_field = field_map[milestone_name]

        if not getattr(self, bool_field):
            setattr(self, bool_field, True)
            setattr(self, time_field, timezone.now())
            self.save(update_fields=[bool_field, time_field, 'updated_at'])
            return True

        return False

    def show_tip(self, tip_id: str):
        """Record that a tip was shown."""
        if tip_id not in self.tips_shown:
            self.tips_shown = self.tips_shown + [tip_id]
            self.save(update_fields=['tips_shown', 'updated_at'])

    def dismiss_tip(self, tip_id: str):
        """Permanently dismiss a tip."""
        if tip_id not in self.tips_dismissed:
            self.tips_dismissed = self.tips_dismissed + [tip_id]
            self.save(update_fields=['tips_dismissed', 'updated_at'])

    def should_show_tip(self, tip_id: str) -> bool:
        """Check if a tip should be shown (not dismissed)."""
        return tip_id not in self.tips_dismissed


# ═══════════════════════════════════════════════════════════════════════════════
# CHEF NOTIFICATION (Proactive Engine Queue)
# ═══════════════════════════════════════════════════════════════════════════════

class ChefNotification(models.Model):
    """
    Queued notifications for the proactive engine.

    Notifications are created by the proactive check task and consumed
    by the frontend notification system.
    """
    chef = models.ForeignKey(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    # Notification types
    TYPE_WELCOME = 'welcome'
    TYPE_BIRTHDAY = 'birthday'
    TYPE_ANNIVERSARY = 'anniversary'
    TYPE_FOLLOWUP = 'followup'
    TYPE_TODO = 'todo'
    TYPE_SEASONAL = 'seasonal'
    TYPE_MILESTONE = 'milestone'
    TYPE_TIP = 'tip'
    TYPE_SYSTEM = 'system'
    TYPE_CERT_EXPIRY = 'cert_expiry'
    TYPE_PERMIT_EXPIRY = 'permit_expiry'

    NOTIFICATION_TYPES = [
        (TYPE_WELCOME, 'Welcome'),
        (TYPE_BIRTHDAY, 'Birthday reminder'),
        (TYPE_ANNIVERSARY, 'Anniversary reminder'),
        (TYPE_FOLLOWUP, 'Follow-up suggestion'),
        (TYPE_TODO, 'To-do reminder'),
        (TYPE_SEASONAL, 'Seasonal suggestion'),
        (TYPE_MILESTONE, 'Client milestone'),
        (TYPE_TIP, 'Contextual tip'),
        (TYPE_SYSTEM, 'System notification'),
        (TYPE_CERT_EXPIRY, 'Certification expiry'),
        (TYPE_PERMIT_EXPIRY, 'MEHKO permit expiry'),
    ]

    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        default=TYPE_SYSTEM
    )

    # Status
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_READ = 'read'
    STATUS_DISMISSED = 'dismissed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_READ, 'Read'),
        (STATUS_DISMISSED, 'Dismissed'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )

    # Content
    title = models.CharField(max_length=200)
    message = models.TextField()

    # Optional client reference (for birthday/followup etc)
    related_client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='chef_notifications'
    )
    related_lead = models.ForeignKey(
        'crm.Lead',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='chef_notifications'
    )

    # Action context (for navigation, pre-filling forms, etc)
    action_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Context for actions: prePrompt, navigation target, etc."
    )

    # Channels (where this notification was/should be delivered)
    sent_in_app = models.BooleanField(default=False)
    sent_email = models.BooleanField(default=False)
    sent_push = models.BooleanField(default=False)

    # Scheduling
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When to send (for digest mode)"
    )

    # Deduplication key (e.g., "birthday_client_123_2026-03-15")
    dedup_key = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Key for deduplication"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Chef Notification'
        verbose_name_plural = 'Chef Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['chef', 'status', '-created_at']),
            models.Index(fields=['chef', 'notification_type']),
            models.Index(fields=['dedup_key']),
        ]

    def __str__(self):
        return f"{self.notification_type}: {self.title} (chef_id={self.chef_id})"

    def mark_sent(self, channel: str = 'in_app'):
        """Mark notification as sent."""
        self.status = self.STATUS_SENT
        self.sent_at = timezone.now()

        if channel == 'in_app':
            self.sent_in_app = True
        elif channel == 'email':
            self.sent_email = True
        elif channel == 'push':
            self.sent_push = True

        self.save()

    def mark_read(self):
        """Mark notification as read."""
        if self.status != self.STATUS_DISMISSED:
            self.status = self.STATUS_READ
            self.read_at = timezone.now()
            self.save(update_fields=['status', 'read_at'])

    def mark_dismissed(self):
        """Dismiss the notification."""
        self.status = self.STATUS_DISMISSED
        self.dismissed_at = timezone.now()
        self.save(update_fields=['status', 'dismissed_at'])

    @classmethod
    def create_notification(
        cls,
        chef,
        notification_type: str,
        title: str,
        message: str,
        related_client=None,
        related_lead=None,
        action_context: dict = None,
        dedup_key: str = None,
        scheduled_for=None,
    ) -> 'ChefNotification':
        """
        Create a notification, respecting deduplication.

        Returns existing notification if dedup_key matches a recent one.
        """
        if dedup_key:
            # Check for existing notification with same dedup key in last 7 days
            cutoff = timezone.now() - timezone.timedelta(days=7)
            existing = cls.objects.filter(
                chef=chef,
                dedup_key=dedup_key,
                created_at__gte=cutoff
            ).first()

            if existing:
                return existing

        return cls.objects.create(
            chef=chef,
            notification_type=notification_type,
            title=title,
            message=message,
            related_client=related_client,
            related_lead=related_lead,
            action_context=action_context or {},
            dedup_key=dedup_key or '',
            scheduled_for=scheduled_for,
        )

    @classmethod
    def get_unread_count(cls, chef) -> int:
        """Get count of unread notifications for a chef."""
        return cls.objects.filter(
            chef=chef,
            status__in=[cls.STATUS_PENDING, cls.STATUS_SENT]
        ).count()

    @classmethod
    def get_pending_for_chef(cls, chef, limit: int = 50):
        """Get pending/sent notifications for a chef."""
        return cls.objects.filter(
            chef=chef,
            status__in=[cls.STATUS_PENDING, cls.STATUS_SENT]
        ).order_by('-created_at')[:limit]
