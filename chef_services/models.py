from datetime import datetime, timedelta
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class ChefServiceOffering(models.Model):
    SERVICE_TYPE_CHOICES = [
        ("home_chef", "Personal Home Chef"),
        ("weekly_prep", "Weekly Meal Prep"),
    ]

    chef = models.ForeignKey("chefs.Chef", on_delete=models.CASCADE, related_name="service_offerings")
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    default_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    max_travel_miles = models.PositiveIntegerField(null=True, blank=True, default=1)
    notes = models.TextField(null=True, blank=True)
    stripe_product_id = models.CharField(max_length=200, null=True, blank=True)
    target_customers = models.ManyToManyField(
        "custom_auth.CustomUser",
        blank=True,
        related_name="personalized_service_offerings",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["chef", "service_type", "active"]),
        ]
        ordering = ["-updated_at", "-id"]

    def clean(self):
        from chefs.validators import validate_no_catering
        super().clean()
        validate_no_catering(self.title, self.chef)
        validate_no_catering(self.description, self.chef)

    def __str__(self):
        return f"{self.get_service_type_display()} (chef={self.chef_id}, id={self.id})"


class ChefServicePriceTier(models.Model):
    """Represents a Stripe-backed price option for a service offering.

    Each tier covers a household size range, stores the amount billed in Stripe's
    smallest currency unit (cents for USD, whole units for JPY), and records 
    whether the booking recurs. The associated ``stripe_price_id`` links this 
    tier directly to the synced Stripe Price so updates can be propagated to 
    Checkout sessions.
    """
    RECURRENCE_CHOICES = [
        ("week", "Per Week"),
    ]
    
    # Stripe-supported currencies with their minimum amounts (in smallest unit)
    # https://stripe.com/docs/currencies#minimum-and-maximum-charge-amounts
    SUPPORTED_CURRENCIES = {
        'usd': {'min': 50, 'zero_decimal': False},      # $0.50 minimum
        'eur': {'min': 50, 'zero_decimal': False},      # €0.50 minimum
        'gbp': {'min': 30, 'zero_decimal': False},      # £0.30 minimum
        'jpy': {'min': 50, 'zero_decimal': True},       # ¥50 minimum
        'cad': {'min': 50, 'zero_decimal': False},      # C$0.50 minimum
        'aud': {'min': 50, 'zero_decimal': False},      # A$0.50 minimum
        'chf': {'min': 50, 'zero_decimal': False},      # CHF 0.50 minimum
        'hkd': {'min': 400, 'zero_decimal': False},     # HK$4.00 minimum
        'sgd': {'min': 50, 'zero_decimal': False},      # S$0.50 minimum
        'nzd': {'min': 50, 'zero_decimal': False},      # NZ$0.50 minimum
        'mxn': {'min': 1000, 'zero_decimal': False},    # MX$10.00 minimum
    }

    offering = models.ForeignKey(ChefServiceOffering, on_delete=models.CASCADE, related_name="tiers")
    household_min = models.PositiveIntegerField()
    household_max = models.PositiveIntegerField(null=True, blank=True, help_text="Null means no upper bound")

    currency = models.CharField(max_length=10, default="usd", help_text="ISO 4217 currency code (lowercase)")
    desired_unit_amount_cents = models.PositiveIntegerField(
        help_text="Amount in smallest currency unit (cents for USD, whole units for JPY)"
    )
    # ``stripe_price_id`` binds the tier to the live Stripe Price used for checkout
    stripe_price_id = models.CharField(max_length=200, blank=True, null=True, help_text="Linked Stripe Price ID")

    PRICE_SYNC_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("error", "Error"),
    ]
    price_sync_status = models.CharField(max_length=10, choices=PRICE_SYNC_STATUS_CHOICES, default="pending")
    last_price_sync_error = models.TextField(null=True, blank=True)
    price_synced_at = models.DateTimeField(null=True, blank=True)

    is_recurring = models.BooleanField(default=False)
    recurrence_interval = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, null=True, blank=True)

    active = models.BooleanField(default=True)
    display_label = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["household_min", "household_max", "id"]
        indexes = [
            models.Index(fields=["offering", "active"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(household_min__gte=1),
                name="tier_household_min_gte_1",
            ),
            models.CheckConstraint(
                check=(models.Q(household_max__isnull=True) | models.Q(household_max__gte=models.F('household_min'))),
                name="tier_household_max_gte_min_or_null",
            ),
            models.CheckConstraint(
                check=(models.Q(is_recurring=False, recurrence_interval__isnull=True) | models.Q(is_recurring=True, recurrence_interval__isnull=False)),
                name="tier_recurring_interval_consistency",
            ),
            models.CheckConstraint(
                check=models.Q(desired_unit_amount_cents__gte=50),
                name="tier_desired_amount_min_50",
            ),
        ]

    def __str__(self):
        label = self.display_label or f"{self.household_min}-{self.household_max or '∞'}"
        kind = "recurring" if self.is_recurring else "one-time"
        return f"Tier({label}, {kind}, offering={self.offering_id})"

    def clean(self):
        # Range validation
        if self.household_min == 0:
            raise ValidationError({"household_min": "Minimum household size must be at least 1."})
        if self.household_max is not None and self.household_max < self.household_min:
            raise ValidationError({"household_max": "Max must be greater than or equal to min."})

        # Recurrence validation
        if self.is_recurring and not self.recurrence_interval:
            raise ValidationError({"recurrence_interval": "Required when is_recurring is True."})
        if not self.is_recurring and self.recurrence_interval:
            raise ValidationError({"recurrence_interval": "Must be null for one-time tiers."})
        
        # Currency validation
        currency_lower = (self.currency or '').lower().strip()
        if currency_lower not in self.SUPPORTED_CURRENCIES:
            supported = ', '.join(sorted(self.SUPPORTED_CURRENCIES.keys()))
            raise ValidationError({
                "currency": f"Unsupported currency '{self.currency}'. Supported: {supported}"
            })
        self.currency = currency_lower  # Normalize to lowercase
        
        # Currency-specific minimum amount validation
        currency_info = self.SUPPORTED_CURRENCIES[currency_lower]
        min_amount = currency_info['min']
        if self.desired_unit_amount_cents < min_amount:
            if currency_info['zero_decimal']:
                raise ValidationError({
                    "desired_unit_amount_cents": f"Minimum amount for {currency_lower.upper()} is {min_amount} (e.g., ¥{min_amount})"
                })
            else:
                raise ValidationError({
                    "desired_unit_amount_cents": f"Minimum amount for {currency_lower.upper()} is {min_amount} cents (e.g., ${min_amount/100:.2f})"
                })

        # Overlap validation: prevent overlapping ranges within the same offering for ACTIVE tiers only
        # Allow overlapping drafts/inactive tiers to exist simultaneously
        if self.active:
            # Treat None (no upper bound) as infinity
            this_min = self.household_min
            this_max = self.household_max or 10**9
            qs = ChefServicePriceTier.objects.filter(offering=self.offering, active=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            for other in qs:
                other_min = other.household_min
                other_max = other.household_max or 10**9
                if not (this_max < other_min or other_max < this_min):
                    # Overlap
                    raise ValidationError("Overlapping household size ranges are not allowed for the same offering.")


class ChefCustomerConnection(models.Model):
    """Represents a mutually approved pairing between a chef and a customer.
    
    Activity tracking fields are used to order chefs by recent activity
    for customers with multiple chef connections.
    """

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_ENDED = "ended"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DECLINED, "Declined"),
        (STATUS_ENDED, "Ended"),
    ]

    INITIATED_BY_CHEF = "chef"
    INITIATED_BY_CUSTOMER = "customer"
    INITIATED_BY_CHOICES = [
        (INITIATED_BY_CHEF, "Chef"),
        (INITIATED_BY_CUSTOMER, "Customer"),
    ]

    chef = models.ForeignKey("chefs.Chef", on_delete=models.CASCADE, related_name="customer_connections")
    customer = models.ForeignKey(
        "custom_auth.CustomUser",
        on_delete=models.CASCADE,
        related_name="chef_connections",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    initiated_by = models.CharField(max_length=20, choices=INITIATED_BY_CHOICES)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    # Activity tracking for ordering chefs by recency (multi-chef support)
    last_order_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Last time customer placed an order with this chef"
    )
    last_message_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Last time there was a message exchange"
    )
    last_plan_update_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Last time a meal plan was created or updated"
    )

    class Meta:
        unique_together = ("chef", "customer")
        indexes = [
            models.Index(fields=["chef", "customer"]),
            models.Index(fields=["chef", "status"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["customer", "status", "-last_order_at"]),
        ]
        ordering = ["-requested_at", "-id"]

    def __str__(self):
        return f"Connection(chef={self.chef_id}, customer={self.customer_id}, status={self.status})"

    def clean(self):
        if self.chef and self.customer and self.chef.user_id == self.customer_id:
            raise ValidationError("Chefs cannot connect to themselves.")
    
    def update_activity(self, activity_type: str):
        """Update the appropriate activity timestamp.
        
        Args:
            activity_type: One of 'order', 'message', 'plan'
        """
        now = timezone.now()
        if activity_type == 'order':
            self.last_order_at = now
        elif activity_type == 'message':
            self.last_message_at = now
        elif activity_type == 'plan':
            self.last_plan_update_at = now
        self.save(update_fields=[f'last_{activity_type}_at' if activity_type != 'plan' else 'last_plan_update_at'])


class ChefServiceOrder(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("awaiting_payment", "Awaiting Payment"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
        ("refunded", "Refunded"),
        ("completed", "Completed"),
    ]

    DELIVERY_CHOICES = [
        ("self_delivery", "Chef/Household Delivery"),
        ("customer_pickup", "Customer Pickup"),
        ("third_party", "Third-Party Delivery"),
    ]

    customer = models.ForeignKey("custom_auth.CustomUser", on_delete=models.PROTECT, related_name="service_orders")
    chef = models.ForeignKey("chefs.Chef", on_delete=models.PROTECT, related_name="service_orders")
    offering = models.ForeignKey(ChefServiceOffering, on_delete=models.PROTECT, related_name="orders")
    tier = models.ForeignKey(ChefServicePriceTier, on_delete=models.PROTECT, related_name="orders")
    household_size = models.PositiveIntegerField()

    service_date = models.DateField(null=True, blank=True)
    service_start_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    address = models.ForeignKey("custom_auth.Address", on_delete=models.SET_NULL, null=True, blank=True)
    special_requests = models.TextField(blank=True)

    # Recurring preferences (e.g., preferred weekday/time) when subscription
    schedule_preferences = models.JSONField(null=True, blank=True)

    # Delivery method (MEHKO chefs restricted to self_delivery/customer_pickup)
    delivery_method = models.CharField(
        max_length=20,
        choices=DELIVERY_CHOICES,
        default="customer_pickup",
        blank=True,
    )

    # Denormalized price at order creation time (for revenue tracking).
    # Prevents retroactive recalculation when tier prices change.
    charged_amount_cents = models.PositiveIntegerField(
        default=0,
        help_text="Amount in smallest currency unit, captured at order creation time"
    )

    stripe_session_id = models.CharField(max_length=200, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=200, null=True, blank=True)
    is_subscription = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["chef", "status"]),
            models.Index(fields=["customer", "status"]),
            # MEHKO meal cap lookups: chef + service_date + status
            models.Index(fields=["chef", "service_date", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(household_size__gte=1),
                name="order_household_size_gte_1",
            ),
        ]

    def __str__(self):
        return f"ServiceOrder(id={self.id}, offering={self.offering_id}, tier={self.tier_id}, status={self.status})"

    def clean(self):
        errors = {}

        # Prevent chefs from ordering their own services (money laundering risk)
        if self.chef and self.customer and self.chef.user_id == self.customer_id:
            errors["customer"] = "Chefs cannot order from themselves."

        # Ensure tier belongs to offering and chef matches
        if self.tier and self.offering and self.tier.offering_id != self.offering_id:
            errors["tier"] = "Selected tier does not belong to the offering."
        if self.offering and self.chef and self.offering.chef_id != self.chef_id:
            errors["offering"] = "Offering does not belong to the selected chef."

        # Household size within tier range
        if self.tier and self.household_size:
            max_sz = self.tier.household_max or 10**9
            if not (self.tier.household_min <= self.household_size <= max_sz):
                errors["household_size"] = "Household size is not within the selected tier's bounds."

        # Schedule validation - only required when transitioning to payment or confirmed status
        # Allow draft orders without scheduling details so users can add to cart
        requires_schedule = self.status in ("awaiting_payment", "confirmed", "completed")
        
        if self.offering and requires_schedule:
            if self.offering.service_type == "home_chef":
                if not self.service_date or not self.service_start_time:
                    errors["service_date"] = "Service date and start time are required for home chef."
            elif self.offering.service_type == "weekly_prep":
                if self.tier and self.tier.is_recurring:
                    # For subscriptions, accept schedule_preferences or a date/time as a fallback
                    if not self.schedule_preferences and (not self.service_date or not self.service_start_time):
                        errors["schedule_preferences"] = "Provide schedule_preferences or a preferred date/time for recurring weekly prep."
                else:
                    # One-time weekly prep requires specific date/time
                    if not self.service_date or not self.service_start_time:
                        errors["service_date"] = "Service date and start time are required for one-time weekly prep."

        # Minimum notice validation (24 hours) - only when transitioning to payment/confirmed
        if requires_schedule and self.service_date and self.service_start_time:
            service_datetime = datetime.combine(self.service_date, self.service_start_time)
            # Make timezone-aware if needed
            if timezone.is_naive(service_datetime):
                service_datetime = timezone.make_aware(service_datetime)
            min_datetime = timezone.now() + timedelta(hours=24)
            if service_datetime < min_datetime:
                errors["service_date"] = "Service must be scheduled at least 24 hours in advance."

        # MEHKO delivery restriction (model-level, not just view-level)
        if (self.chef and getattr(self.chef, 'mehko_active', False)
                and self.delivery_method == 'third_party'):
            errors["delivery_method"] = (
                "MEHKO orders cannot use third-party delivery services "
                "per California Health & Safety Code §114367.5."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Derive is_subscription from tier if present
        if self.tier_id:
            try:
                tier = self.tier if isinstance(self.tier, ChefServicePriceTier) else None
                if tier is None:
                    tier = ChefServicePriceTier.objects.only("is_recurring").get(id=self.tier_id)
                self.is_subscription = bool(tier.is_recurring)
            except ChefServicePriceTier.DoesNotExist:
                pass
        super().save(*args, **kwargs)
