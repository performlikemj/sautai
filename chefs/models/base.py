from django.conf import settings
from django.db import models
from local_chefs.models import PostalCode, ChefPostalCode
from pgvector.django import VectorField
from django.utils import timezone
from django_countries.fields import CountryField

class Chef(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    experience = models.CharField(max_length=500, blank=True)
    bio = models.TextField(blank=True)
    # Simple availability flag: when True, the chef is temporarily not accepting orders
    is_on_break = models.BooleanField(default=False, help_text="Temporarily not accepting orders")
    # Whether chef has completed setup and chosen to be visible in public directory
    is_live = models.BooleanField(default=False, help_text="Chef has completed setup and chosen to be visible in the public directory")
    # Default currency for payment links and stats
    default_currency = models.CharField(
        max_length=3,
        default='usd',
        help_text="Default currency for payment links and stats (ISO 4217 code)"
    )
    # Verification & compliance
    is_verified = models.BooleanField(default=False, help_text="Admin approval for platform listing")
    background_checked = models.BooleanField(default=False)
    insured = models.BooleanField(default=False)
    insurance_expiry = models.DateField(blank=True, null=True)
    food_handlers_cert = models.BooleanField(default=False)
    food_handlers_cert_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Food handler certificate number"
    )
    food_handlers_cert_expiry = models.DateField(
        blank=True,
        null=True,
        help_text="Food handler certificate expiration date"
    )
    food_handlers_cert_verified_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the food handler certificate was verified"
    )
    serving_postalcodes = models.ManyToManyField(
        PostalCode,
        through=ChefPostalCode,
        related_name='serving_chefs'
    )
    profile_pic = models.ImageField(upload_to='chefs/profile_pics/', blank=True)
    banner_image = models.ImageField(upload_to='chefs/banners/', blank=True, null=True)
    chef_request = models.BooleanField(default=False)
    chef_request_experience = models.TextField(blank=True, null=True)
    chef_request_bio = models.TextField(blank=True, null=True)
    chef_request_profile_pic = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    review_summary = models.TextField(blank=True, null=True)
    chef_embedding = VectorField(dimensions=1536, null=True, blank=True)  # Embedding field
    # Sous Chef assistant customization
    sous_chef_emoji = models.CharField(
        max_length=10,
        default='🧑‍🍳',
        blank=True,
        help_text="Emoji icon for the Sous Chef assistant widget"
    )
    # Sous Chef suggestion preferences
    sous_chef_suggestions_enabled = models.BooleanField(
        default=True,
        help_text="Enable contextual AI suggestions from Sous Chef"
    )
    sous_chef_suggestion_frequency = models.CharField(
        max_length=20,
        choices=[
            ('often', 'Often'),
            ('sometimes', 'Sometimes'),
            ('rarely', 'Rarely')
        ],
        default='sometimes',
        help_text="How often to show contextual suggestions"
    )
    dismissed_suggestion_types = models.JSONField(
        default=list,
        blank=True,
        help_text="List of suggestion types the chef has dismissed permanently"
    )
    # MEHKO / IFSI Compliance (California §114367.6)
    permit_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="MEHKO permit number issued by local enforcement agency"
    )
    permitting_agency = models.CharField(
        max_length=200,
        blank=True,
        help_text="Local enforcement agency that issued the MEHKO permit"
    )
    permit_expiry = models.DateField(
        blank=True,
        null=True,
        help_text="MEHKO permit expiration date"
    )
    county = models.CharField(
        max_length=100,
        blank=True,
        help_text="County or jurisdiction for MEHKO operations"
    )
    mehko_consent = models.BooleanField(
        default=False,
        help_text="Chef consented to CDPH disclosures and complaint reporting per §114367.6"
    )
    mehko_active = models.BooleanField(
        default=False,
        help_text="MEHKO compliance complete: permit + consent + food handler cert verified"
    )

    # Calendly booking link
    calendly_url = models.URLField(
        blank=True,
        null=True,
        max_length=500,
        help_text="Calendly booking URL for client consultations"
    )


    def __str__(self):
        return self.user.username if self.user else f"Chef #{self.pk}"
    
    @property
    def featured_dishes(self):
        return self.dishes.filter(featured=True)

    @property
    def reviews(self):
        return self.chef_reviews.all()

    class Meta:
        app_label = 'chefs'


class ChefRequest(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    experience = models.TextField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    requested_postalcodes = models.ManyToManyField(PostalCode, blank=True)
    profile_pic = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Chef Request for {self.user.username}"


class ChefPhoto(models.Model):
    """Gallery photo uploaded by an approved chef to showcase their food."""
    CATEGORY_CHOICES = [
        ('appetizer', 'Appetizer'),
        ('main', 'Main Course'),
        ('dessert', 'Dessert'),
        ('beverage', 'Beverage'),
        ('side', 'Side Dish'),
        ('other', 'Other'),
    ]
    
    chef = models.ForeignKey('Chef', on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='chefs/photos/')
    thumbnail = models.ImageField(upload_to='chefs/photos/thumbnails/', blank=True, null=True)
    
    # Text fields
    title = models.CharField(max_length=255, blank=True)
    caption = models.TextField(blank=True)
    description = models.TextField(blank=True)
    
    # Relationships
    dish = models.ForeignKey('meals.Dish', on_delete=models.SET_NULL, null=True, blank=True, related_name='photos')
    meal = models.ForeignKey('meals.Meal', on_delete=models.SET_NULL, null=True, blank=True, related_name='photos')
    
    # Organization
    tags = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, blank=True, null=True)
    
    # Metadata
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    file_size = models.IntegerField(blank=True, null=True)
    
    # Features
    is_featured = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', '-created_at']
        indexes = [
            models.Index(fields=['chef', '-created_at']),
            models.Index(fields=['chef', 'category']),
            models.Index(fields=['chef', 'is_public']),
        ]

    def __str__(self):
        base = self.title or 'Chef Photo'
        return f"{base} (chef_id={self.chef_id})"
    
    def save(self, *args, **kwargs):
        """Extract image dimensions and file size on save."""
        if self.image and hasattr(self.image, 'file'):
            try:
                from PIL import Image
                image = Image.open(self.image.file)
                self.width, self.height = image.size
                
                # Get file size
                self.image.file.seek(0, 2)  # Seek to end
                self.file_size = self.image.file.tell()
                self.image.file.seek(0)  # Reset to beginning
            except Exception:
                pass  # Silently fail if we can't extract metadata
        
        super().save(*args, **kwargs)


class ChefDefaultBanner(models.Model):
    """Site-wide default banner that applies when a Chef has no custom banner_image."""
    image = models.ImageField(upload_to='chefs/banners/defaults/')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return f"ChefDefaultBanner(id={self.id})"


class ChefVerificationDocument(models.Model):
    """Documents uploaded by chef for verification: insurance, background, certifications."""
    DOC_TYPES = [
        ('insurance', 'Insurance'),
        ('background', 'Background Check'),
        ('food_handlers', 'Food Handler Certificate'),
        ('permit', 'MEHKO Permit'),
        ('other', 'Other'),
    ]
    chef = models.ForeignKey('Chef', on_delete=models.CASCADE, related_name='verification_docs')
    doc_type = models.CharField(max_length=32, choices=DOC_TYPES)
    file = models.FileField(upload_to='chefs/verification_docs/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_approved = models.BooleanField(default=False)
    rejected_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"VerificationDoc(type={self.doc_type}, chef_id={self.chef_id}, approved={self.is_approved})"

class MehkoComplaint(models.Model):
    """
    Tracks consumer complaints against MEHKO-registered chefs.
    Per §114367.6: 3+ unrelated complaints in 12 months requires
    reporting permit number to local enforcement agency.
    """
    chef = models.ForeignKey(
        'Chef',
        on_delete=models.CASCADE,
        related_name='mehko_complaints'
    )
    complainant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='filed_mehko_complaints',
        help_text="User who filed the complaint (null for anonymous)"
    )
    complaint_text = models.TextField(
        help_text="Description of the complaint"
    )
    is_significant = models.BooleanField(
        default=False,
        help_text="Significant food safety complaint requiring same-day buyer list"
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reported_to_agency = models.BooleanField(
        default=False,
        help_text="Whether this complaint has been reported to local enforcement"
    )
    reported_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this complaint was reported to local enforcement"
    )
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this complaint was resolved"
    )
    admin_notes = models.TextField(
        blank=True,
        help_text="Internal notes about complaint handling"
    )

    class Meta:
        app_label = 'chefs'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['chef', '-submitted_at']),
            models.Index(fields=['chef', 'reported_to_agency']),
        ]

    def __str__(self):
        return f"MehkoComplaint(chef={self.chef_id}, submitted={self.submitted_at:%Y-%m-%d})"

    @classmethod
    def complaints_in_window(cls, chef, months=12):
        """Count complaints for a chef in the last N months."""
        from dateutil.relativedelta import relativedelta
        cutoff = timezone.now() - relativedelta(months=months)
        return cls.objects.filter(
            chef=chef,
            submitted_at__gte=cutoff,
        ).count()

    @classmethod
    def threshold_reached(cls, chef, threshold=3, months=12):
        """Check if a chef has hit the complaint reporting threshold."""
        return cls.complaints_in_window(chef, months) >= threshold


# Waitlist feature models
class ChefWaitlistConfig(models.Model):
    """Global toggle and config for chef waitlist notifications."""
    enabled = models.BooleanField(default=False, help_text="Enable chef waitlist feature globally")
    cooldown_hours = models.PositiveIntegerField(default=24, help_text="Minimum hours a chef must be inactive before a new activation triggers notifications")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Chef Waitlist Config'
        verbose_name_plural = 'Chef Waitlist Config'

    def __str__(self):
        return f"Waitlist {'ENABLED' if self.enabled else 'DISABLED'} (cooldown={self.cooldown_hours}h)"

    @classmethod
    def get_config(cls):
        return cls.objects.order_by('-updated_at', '-id').first()

    @classmethod
    def get_enabled(cls) -> bool:
        cfg = cls.get_config()
        return bool(getattr(cfg, 'enabled', False))

    @classmethod
    def get_cooldown_hours(cls) -> int:
        cfg = cls.get_config()
        return int(getattr(cfg, 'cooldown_hours', 24) or 24)


class ChefAvailabilityState(models.Model):
    """Tracks a chef's availability state for orderable events and notification epochs."""
    chef = models.OneToOneField('Chef', on_delete=models.CASCADE, related_name='availability')
    is_active = models.BooleanField(default=False)
    activation_epoch = models.PositiveIntegerField(default=0, help_text="Increments each time the chef becomes active after a cooldown")
    last_activated_at = models.DateTimeField(null=True, blank=True)
    last_deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Chef Availability State'
        verbose_name_plural = 'Chef Availability States'

    def __str__(self):
        return f"ChefAvailability(chef_id={self.chef_id}, active={self.is_active}, epoch={self.activation_epoch})"


class ChefWaitlistSubscription(models.Model):
    """Per-user subscription to be notified when a chef becomes active again."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chef_waitlist_subscriptions')
    chef = models.ForeignKey('Chef', on_delete=models.CASCADE, related_name='waitlist_subscriptions')
    active = models.BooleanField(default=True)
    last_notified_epoch = models.PositiveIntegerField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'chefs'
        unique_together = (('user', 'chef', 'active'),)
        indexes = [
            models.Index(fields=['chef', 'active']),
            models.Index(fields=['user', 'active']),
        ]

    def __str__(self):
        status = 'active' if self.active else 'inactive'
        return f"Waitlist({self.user_id} -> chef {self.chef_id}, {status}, last_epoch={self.last_notified_epoch})"


class AreaWaitlist(models.Model):
    """Users waiting for ANY chef to become available in their area.
    
    This is distinct from ChefWaitlistSubscription which tracks users waiting
    for a specific chef. AreaWaitlist is for users in areas with no chef coverage
    who want to be notified when any chef starts serving their postal code.
    
    Uses a ForeignKey to PostalCode for referential integrity and easier joins.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='area_waitlist_entries'
    )
    location = models.ForeignKey(
        'local_chefs.PostalCode',
        on_delete=models.CASCADE,
        related_name='area_waitlist_entries',
        help_text="The postal code location the user is waiting for"
    )
    notified = models.BooleanField(default=False, help_text="Whether user has been notified of chef availability")
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'chefs'
        unique_together = ('user', 'location')
        indexes = [
            models.Index(fields=['location', 'notified']),
            models.Index(fields=['user', 'notified']),
        ]
        verbose_name = 'Area Waitlist Entry'
        verbose_name_plural = 'Area Waitlist Entries'

    def __str__(self):
        status = 'notified' if self.notified else 'waiting'
        return f"AreaWaitlist({self.user_id} in {self.location}, {status})"
    
    # Backwards compatibility properties
    @property
    def postal_code(self) -> str:
        """Backwards compatibility: returns normalized postal code string."""
        return self.location.code if self.location else None
    
    @property
    def country(self) -> str:
        """Backwards compatibility: returns country code string."""
        return str(self.location.country) if self.location else None

    @classmethod
    def get_waiting_users_for_area(cls, postal_code: str, country: str):
        """Get all users waiting for chefs in a specific area who haven't been notified."""
        from shared.services.location_service import LocationService
        
        normalized = LocationService.normalize(postal_code)
        if not normalized:
            return cls.objects.none()
        
        return cls.objects.filter(
            location__code=normalized,
            location__country=country,
            notified=False
        ).select_related('user', 'location')

    @classmethod
    def get_position(cls, user, postal_code: str, country: str) -> int:
        """Get user's position in the waitlist for their area (1-indexed)."""
        from shared.services.location_service import LocationService
        
        normalized = LocationService.normalize(postal_code)
        if not normalized:
            return 0
        
        try:
            entry = cls.objects.get(
                user=user,
                location__code=normalized,
                location__country=country
            )
            # Count entries created before this one in the same location
            position = cls.objects.filter(
                location=entry.location,
                created_at__lt=entry.created_at
            ).count() + 1
            return position
        except cls.DoesNotExist:
            return 0

    @classmethod
    def get_total_waiting(cls, postal_code: str, country: str) -> int:
        """Get total count of users waiting in an area."""
        from shared.services.location_service import LocationService
        
        normalized = LocationService.normalize(postal_code)
        if not normalized:
            return 0
        
        return cls.objects.filter(
            location__code=normalized,
            location__country=country,
            notified=False
        ).count()
    
    @classmethod
    def join_waitlist(cls, user, postal_code: str, country: str):
        """
        Add a user to the waitlist for a specific area.
        
        Args:
            user: The user to add
            postal_code: The postal code (will be normalized)
            country: The country code
            
        Returns:
            tuple: (entry, created) - The waitlist entry and whether it was created
        """
        from shared.services.location_service import LocationService
        
        # Get or create the PostalCode record
        location = LocationService.get_or_create_postal_code(postal_code, country)
        if not location:
            return None, False
        
        entry, created = cls.objects.get_or_create(
            user=user,
            location=location,
            defaults={'notified': False}
        )
        
        # If existing entry was notified (user rejoining), reset it
        if not created and entry.notified:
            entry.notified = False
            entry.notified_at = None
            entry.save(update_fields=['notified', 'notified_at'])
        
        return entry, created


class PlatformCalendlyConfig(models.Model):
    """
    Platform-wide Calendly configuration for chef verification meetings.
    Admin configures their Calendly link and meeting details here.
    Singleton pattern - only one active config should exist.
    """
    calendly_url = models.URLField(
        max_length=500,
        help_text="Admin's Calendly URL for chef verification meetings"
    )
    meeting_title = models.CharField(
        max_length=200,
        default="Chef Verification Call",
        help_text="Title shown to chefs when scheduling"
    )
    meeting_description = models.TextField(
        blank=True,
        help_text="Description of what to expect in the verification call"
    )
    is_required = models.BooleanField(
        default=True,
        help_text="Whether the meeting is required before chef can be fully activated"
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Enable/disable the Calendly meeting step globally"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Platform Calendly Config'
        verbose_name_plural = 'Platform Calendly Config'

    def __str__(self):
        status = 'ENABLED' if self.enabled else 'DISABLED'
        return f"Calendly Config ({status})"

    def save(self, *args, **kwargs):
        # Ensure only one config exists (singleton pattern)
        if not self.pk:
            PlatformCalendlyConfig.objects.all().delete()
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        """Get the active Calendly configuration."""
        return cls.objects.first()

    @classmethod
    def is_enabled(cls) -> bool:
        cfg = cls.get_config()
        return bool(getattr(cfg, 'enabled', False)) if cfg else False

    @classmethod
    def get_calendly_url(cls) -> str:
        cfg = cls.get_config()
        return getattr(cfg, 'calendly_url', '') if cfg else ''


class ChefVerificationMeeting(models.Model):
    """
    Tracks verification meeting status for each chef.
    Allows admin to mark meetings as scheduled/completed.
    """
    STATUS_CHOICES = [
        ('not_scheduled', 'Not Scheduled'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]

    chef = models.OneToOneField(
        'Chef',
        on_delete=models.CASCADE,
        related_name='verification_meeting'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='not_scheduled'
    )
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the meeting is/was scheduled for"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the meeting was completed"
    )
    admin_notes = models.TextField(
        blank=True,
        help_text="Admin notes from the verification meeting"
    )
    marked_complete_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_chef_meetings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'chefs'
        verbose_name = 'Chef Verification Meeting'
        verbose_name_plural = 'Chef Verification Meetings'

    def __str__(self):
        return f"Meeting for {self.chef.user.username}: {self.status}"

    def mark_as_scheduled(self, scheduled_time=None):
        self.status = 'scheduled'
        if scheduled_time:
            self.scheduled_at = scheduled_time
        self.save(update_fields=['status', 'scheduled_at', 'updated_at'])

    def mark_as_completed(self, admin_user=None, notes=''):
        self.status = 'completed'
        self.completed_at = timezone.now()
        if admin_user:
            self.marked_complete_by = admin_user
        if notes:
            self.admin_notes = notes
        self.save()


class ChefPaymentLink(models.Model):
    """
    Tracks payment links created by chefs for clients (both platform users and manual contacts).
    Uses Stripe Payment Links for secure, shareable payment URLs.
    """
    
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending Payment"
        PAID = "paid", "Paid"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
    
    chef = models.ForeignKey(
        'Chef',
        on_delete=models.CASCADE,
        related_name='payment_links'
    )
    
    # Recipient - either a platform user or a manual contact (Lead)
    lead = models.ForeignKey(
        'crm.Lead',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_links',
        help_text="For off-platform clients (manual contacts)"
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chef_payment_links',
        help_text="For platform users"
    )
    
    # Payment details
    amount_cents = models.PositiveIntegerField(
        help_text="Payment amount in cents (e.g., 5000 = $50.00)"
    )
    currency = models.CharField(max_length=3, default='usd')
    description = models.CharField(
        max_length=500,
        help_text="Description of what this payment is for"
    )
    
    # Stripe integration
    stripe_payment_link_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Payment Link ID"
    )
    stripe_payment_link_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Shareable Stripe Payment Link URL"
    )
    stripe_price_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Price ID created for this payment"
    )
    stripe_product_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Product ID created for this payment"
    )
    stripe_checkout_session_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Checkout Session ID when payment is initiated"
    )
    stripe_payment_intent_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Payment Intent ID after successful payment"
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    
    # Email tracking
    recipient_email = models.EmailField(
        blank=True,
        help_text="Email address the payment link was sent to"
    )
    email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the payment link email was last sent"
    )
    email_send_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times the payment link has been emailed"
    )
    
    # Payment completion tracking
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the payment was completed"
    )
    paid_amount_cents = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Actual amount paid (may differ due to fees)"
    )
    
    # Expiration
    expires_at = models.DateTimeField(
        help_text="When this payment link expires"
    )
    
    # Notes and metadata
    internal_notes = models.TextField(
        blank=True,
        help_text="Internal notes for the chef (not shown to client)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        app_label = 'chefs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['chef', 'status']),
            models.Index(fields=['chef', '-created_at']),
            models.Index(fields=['lead', 'status']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['stripe_payment_link_id']),
            models.Index(fields=['stripe_checkout_session_id']),
        ]
    
    def __str__(self):
        recipient = self.get_recipient_name()
        return f"PaymentLink(${self.amount_cents/100:.2f} to {recipient}, {self.status})"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        
        # Must have either lead or customer, but not both
        if self.lead and self.customer:
            errors['lead'] = "Cannot have both a lead and a customer for the same payment link."
        if not self.lead and not self.customer and self.status != self.Status.DRAFT:
            errors['lead'] = "Must specify either a lead (manual contact) or a customer (platform user)."
        
        # Validate amount
        if self.amount_cents and self.amount_cents < 50:
            errors['amount_cents'] = "Minimum amount is $0.50 (50 cents)."
        
        if errors:
            raise ValidationError(errors)
    
    def get_recipient_name(self):
        """Get the name of the payment recipient."""
        if self.lead:
            return f"{self.lead.first_name} {self.lead.last_name}".strip()
        if self.customer:
            return self.customer.get_full_name() or self.customer.username
        return "Unknown"
    
    def get_recipient_email(self):
        """Get the email of the payment recipient."""
        if self.recipient_email:
            return self.recipient_email
        if self.lead and self.lead.email:
            return self.lead.email
        if self.customer and self.customer.email:
            return self.customer.email
        return None
    
    def is_expired(self):
        """Check if the payment link has expired."""
        return timezone.now() > self.expires_at
    
    def can_send_email(self):
        """Check if the payment link can be sent via email."""
        email = self.get_recipient_email()
        if not email:
            return False, "No email address available"
        
        # For leads, require email verification
        if self.lead and not self.lead.email_verified:
            return False, "Email not verified"
        
        if self.status not in [self.Status.DRAFT, self.Status.PENDING]:
            return False, f"Cannot send email for {self.status} payment link"
        
        if self.is_expired():
            return False, "Payment link has expired"
        
        return True, None
    
    def mark_as_paid(self, payment_intent_id=None, amount_cents=None):
        """Mark the payment link as paid."""
        self.status = self.Status.PAID
        self.paid_at = timezone.now()
        if payment_intent_id:
            self.stripe_payment_intent_id = payment_intent_id
        if amount_cents:
            self.paid_amount_cents = amount_cents
        self.save(update_fields=[
            'status', 'paid_at', 'stripe_payment_intent_id', 
            'paid_amount_cents', 'updated_at'
        ])
    
    def cancel(self):
        """Cancel the payment link."""
        if self.status == self.Status.PAID:
            raise ValueError("Cannot cancel a paid payment link")
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status', 'updated_at'])
    
    def record_email_sent(self, email_address=None):
        """Record that an email was sent for this payment link."""
        self.email_sent_at = timezone.now()
        self.email_send_count += 1
        if email_address:
            self.recipient_email = email_address
        if self.status == self.Status.DRAFT:
            self.status = self.Status.PENDING
        self.save(update_fields=[
            'email_sent_at', 'email_send_count', 
            'recipient_email', 'status', 'updated_at'
        ])
