# meals/models/chef_events.py
"""
Chef meal event models: ChefMealEvent, ChefMealOrder, ChefMealReview,
ChefMealPlan, ChefMealPlanDay, ChefMealPlanItem, MealPlanSuggestion, MealPlanGenerationJob
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import UniqueConstraint, Q
from zoneinfo import ZoneInfo
from datetime import timezone as py_tz

import dateutil.parser
import logging

from custom_auth.models import CustomUser

# Use string reference 'chefs.Chef' in ForeignKey fields to avoid circular import
# (chefs/models/ directory shadows chefs/models.py)

logger = logging.getLogger(__name__)

# Add status constants at the top of the file
# Shared statuses between ChefMealEvent and ChefMealOrder
STATUS_COMPLETED = 'completed'
STATUS_CANCELLED = 'cancelled'

# ChefMealEvent specific statuses
STATUS_SCHEDULED = 'scheduled'
STATUS_OPEN = 'open'
STATUS_CLOSED = 'closed'
STATUS_IN_PROGRESS = 'in_progress'

# ChefMealOrder specific statuses
STATUS_PLACED = 'placed'
STATUS_CONFIRMED = 'confirmed'
STATUS_REFUNDED = 'refunded'


class ChefMealEvent(models.Model):
    """
    Represents a Meal Share - a scheduled meal offering that multiple customers can order.
    
    This model allows chefs to schedule when they'll prepare a particular meal
    and make it available to multiple customers. For example, a chef might offer their
    signature lasagna on Friday evening from 6-8pm with orders needed by Thursday.
    
    The dynamic pricing encourages group orders - as more customers order the same meal,
    the price decreases for everyone, benefiting both the chef (more orders) and
    customers (lower prices).
    
    Note: The model is named ChefMealEvent for historical reasons, but the user-facing
    terminology is "Meal Share" to better convey the shared, group ordering concept.
    """
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_OPEN, 'Open for Orders'),
        (STATUS_CLOSED, 'Closed for Orders'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    
    chef = models.ForeignKey('chefs.Chef', on_delete=models.CASCADE, related_name='meal_events')
    meal = models.ForeignKey('Meal', on_delete=models.CASCADE, related_name='events')
    event_date = models.DateField(help_text="The date when the chef will prepare and serve this meal share")
    event_time = models.TimeField(help_text="The time when the meal will be available for pickup/delivery")
    order_cutoff_time = models.DateTimeField(help_text="Deadline for placing orders for this meal share")
    
    max_orders = models.PositiveIntegerField(help_text="Maximum number of orders the chef can fulfill for this meal share")
    min_orders = models.PositiveIntegerField(default=1, help_text="Minimum number of orders needed for the meal share to proceed")
    
    base_price = models.DecimalField(max_digits=6, decimal_places=2, 
                                   help_text="Starting price per order")
    current_price = models.DecimalField(max_digits=6, decimal_places=2, 
                                      help_text="Current price based on number of orders")
    min_price = models.DecimalField(max_digits=6, decimal_places=2, 
                                  help_text="Minimum price per order")
    
    orders_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    
    description = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['event_date', 'event_time']
        unique_together = ('chef', 'meal', 'event_date', 'event_time', 'status')
    
    def __str__(self):
        return f"{self.meal.name} by {self.chef.user.username} on {self.event_date} at {self.event_time}"
    
    def get_chef_timezone(self):
        """
        Get the chef's timezone. Defaults to UTC if not set.
        """
        return self.chef.user.timezone if hasattr(self.chef.user, 'timezone') else 'UTC'
    
    def get_chef_timezone_object(self):
        """
        Get the chef's timezone as a ZoneInfo timezone object.
        """
        timezone_str = self.get_chef_timezone()
        try:
            return ZoneInfo(timezone_str)
        except Exception:
            return ZoneInfo("UTC")
    
    def to_chef_timezone(self, dt):
        """
        Convert a datetime from UTC to the chef's timezone.
        """
        if not dt:
            return dt
            
        if not timezone.is_aware(dt):
            dt = timezone.make_aware(dt)
            
        return dt.astimezone(self.get_chef_timezone_object())
    
    def from_chef_timezone(self, dt):
        """
        Convert a datetime from the chef's timezone to UTC for storage.
        """
        if not dt:
            return dt
            
        # If the datetime is naive, assume it's in the chef's timezone and make it aware
        if not timezone.is_aware(dt):
            chef_tz = self.get_chef_timezone_object()
            dt = timezone.make_aware(dt, chef_tz)
            
        # Convert to UTC
        return dt.astimezone(py_tz.utc)
    
    def get_event_datetime(self):
        """
        Combine event_date and event_time into a timezone-aware datetime.
        """
        import datetime
        if not self.event_date or not self.event_time:
            return None
            
        # Combine date and time
        naive_dt = datetime.datetime.combine(self.event_date, self.event_time)
        
        # Make it timezone-aware in the chef's timezone
        chef_tz = self.get_chef_timezone_object()
        return timezone.make_aware(naive_dt, chef_tz)
    
    def get_cutoff_time_in_chef_timezone(self):
        """
        Get the order cutoff time in the chef's timezone.
        """
        if not self.order_cutoff_time:
            return None
            
        return self.to_chef_timezone(self.order_cutoff_time)
    
    def save(self, *args, **kwargs):
        # If this is a new event, set the current price to the base price
        if not self.pk:
            self.current_price = self.base_price
        else:
            # If this is an existing event with orders, prevent price changes
            try:
                original = ChefMealEvent.objects.get(pk=self.pk)
                if original.orders_count > 0:
                    # Prevent changes to any price fields once orders exist
                    self.base_price = original.base_price
                    self.min_price = original.min_price
                    # Allow current_price changes only through the update_price method
                    # (for automatic group discounts)
                    if not kwargs.get('update_fields') or 'current_price' not in kwargs.get('update_fields', []):
                        self.current_price = original.current_price
            except ChefMealEvent.DoesNotExist:
                pass
                
        super().save(*args, **kwargs)
    
    def update_price(self):
        """
        Update the price based on the number of orders.
        As more orders come in, the price decreases until it reaches min_price.
        
        The pricing algorithm works as follows:
        1. For each order after the first one, the price decreases by 5% of the difference 
           between base_price and min_price
        2. The price will never go below the min_price
        3. When price changes, all existing orders are updated to the new lower price
        
        This creates a win-win situation where:
        - It incentivizes customers to share/promote the meal to get more orders
        - Everyone benefits when more people join (price drops for all)
        - The chef benefits from higher volume
        - The minimum price protects the chef's profit margin
        """
        if self.orders_count <= 1:
            # No price discount for first order, but ensure price_paid is set
            from decimal import Decimal
            ChefMealOrder.objects.filter(
                meal_event=self,
                status__in=['placed', 'confirmed'],
                price_paid__isnull=True
            ).update(price_paid=self.current_price)
            return
        
        # Simple pricing algorithm:
        # For each order after the first one, reduce price by 5% of the difference 
        # between base_price and min_price, until min_price is reached
        price_range = float(self.base_price) - float(self.min_price)
        discount_per_order = price_range * 0.05  # 5% of the range
        
        # Calculate the discount based on number of orders
        total_discount = discount_per_order * (self.orders_count - 1)
        
        # Don't go below min_price
        new_price = max(float(self.base_price) - total_discount, float(self.min_price))
        
        # Save the new price
        self.current_price = new_price
        self.save(update_fields=['current_price'])
        
        # Update pricing for all existing orders
        from decimal import Decimal
        ChefMealOrder.objects.filter(meal_event=self, status__in=['placed', 'confirmed']).update(
            price_paid=Decimal(new_price)
        )
    
    def is_available_for_orders(self):
        """Check if the event is open for new orders"""
        # Get current time in UTC
        now_utc = timezone.now()
        
        # Get chef's timezone
        chef_tz = self.get_chef_timezone_object()
        
        # Convert current time to chef's timezone
        now = now_utc.astimezone(chef_tz)
        
        # Make sure order_cutoff_time is a datetime object
        cutoff_time = self.order_cutoff_time
        if isinstance(cutoff_time, str):
            # If it's a string, parse it and make it timezone-aware
            try:
                cutoff_time = dateutil.parser.parse(cutoff_time)
                if not timezone.is_aware(cutoff_time):
                    cutoff_time = timezone.make_aware(cutoff_time)
            except Exception:
                # If parsing fails, default to not available
                return False
        
        # Convert cutoff time to chef's timezone for comparison
        if cutoff_time:
            cutoff_time = cutoff_time.astimezone(chef_tz)
        
        # Explicitly check all conditions that would make the event unavailable
        if self.status in [STATUS_CLOSED, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELLED]:
            return False
            
        # Only SCHEDULED and OPEN statuses are valid for ordering
        if self.status not in [STATUS_SCHEDULED, STATUS_OPEN]:
            return False
            
        # Check time and capacity constraints
        if now >= cutoff_time:
            return False
            
        if self.orders_count >= self.max_orders:
            return False
            
        # If we passed all checks, the event is available
        return True
    
    def cancel(self):
        """Cancel the event and all associated orders"""
        self.status = STATUS_CANCELLED
        self.save()
        # Cancel all orders and initiate refunds
        self.orders.filter(status__in=[STATUS_PLACED, STATUS_CONFIRMED]).update(status=STATUS_CANCELLED)
        # Refund logic would be implemented separately


class ChefMealOrder(models.Model):
    """
    Represents a customer's order for a specific Meal Share (ChefMealEvent).
    Linked to the main Order model for unified order history.
    """
    STATUS_CHOICES = [
        (STATUS_PLACED, 'Placed'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_REFUNDED, 'Refunded'),
        (STATUS_COMPLETED, 'Completed')
    ]
    
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='chef_meal_orders')
    meal_event = models.ForeignKey(ChefMealEvent, on_delete=models.CASCADE, related_name='orders')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    # Add this link to tie the ChefMealOrder to the specific meal plan slot
    meal_plan_meal = models.ForeignKey(
        'MealPlanMeal', 
        on_delete=models.SET_NULL, # Or CASCADE if a deleted slot should remove the order item
        null=True, 
        blank=True, 
        related_name='chef_order_item' # Use a specific related_name
    ) 

    quantity = models.PositiveIntegerField(default=1)
    # price_paid should store the *total* price paid for the quantity at the time of purchase/confirmation
    unit_price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    price_paid = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True) # Allow null initially
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='placed')
    
    # Stripe payment details
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_refund_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Price adjustment tracking
    price_adjustment_processed = models.BooleanField(default=False, help_text="Whether price adjustment/refund has been processed")
    
    special_requests = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['customer', 'meal_event'],
                condition=Q(status__in=['placed', 'confirmed']),
                name='uniq_active_order_per_event'
            )
        ]
        ordering = ['-created_at']
    
    # Add property for backward compatibility with new service code
    @property
    def payment_intent_id(self):
        return self.stripe_payment_intent_id
    
    @payment_intent_id.setter
    def payment_intent_id(self, value):
        self.stripe_payment_intent_id = value
    
    def __str__(self):
        return f"Order #{self.id} - {self.meal_event.meal.name} by {self.customer.username}"
    
    def mark_as_paid(self):
        """
        Mark the order as paid and update the event's order count and pricing.
        This should ONLY be called when payment is confirmed.
        """
        if self.status == STATUS_PLACED:
            # Update status to confirmed
            self.status = STATUS_CONFIRMED
            self.save(update_fields=['status'])
            
            # Increment the orders count on the event
            # Ensure quantity is not None before using it
            quantity_to_add = self.quantity if self.quantity is not None else 1
            self.meal_event.orders_count += quantity_to_add
            self.meal_event.save() # Save the event after updating count
            
            # Update the price for all orders on the event
            self.meal_event.update_price()
            
            return True
        return False
    
    def cancel(self):
        """Cancel the order and update the event's orders count"""
        if self.status in [STATUS_PLACED, STATUS_CONFIRMED]:
            previous_status = self.status
            self.status = STATUS_CANCELLED
            self.save()
            
            # Only decrement the count if this was a confirmed (paid) order
            if previous_status == STATUS_CONFIRMED:
                # Decrement the orders count on the event
                # Ensure quantity is not None before using it
                quantity_to_remove = self.quantity if self.quantity is not None else 1
                self.meal_event.orders_count = max(0, self.meal_event.orders_count - quantity_to_remove) # Prevent negative count
                self.meal_event.save() # Save the event after updating count
                
                # Update pricing
                self.meal_event.update_price()
            
            # Refund logic would be implemented separately
            return True
        return False


class ChefMealReview(models.Model):
    """Reviews for chef meals with ratings and comments"""
    chef_meal_order = models.OneToOneField(ChefMealOrder, on_delete=models.CASCADE, related_name='review')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    chef = models.ForeignKey('chefs.Chef', on_delete=models.CASCADE, related_name='meal_reviews')
    meal_event = models.ForeignKey(ChefMealEvent, on_delete=models.CASCADE, related_name='reviews')
    
    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5)
        ]
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('customer', 'meal_event')
    
    def __str__(self):
        return f"Review by {self.customer.username} for {self.meal_event.meal.name}"


# =============================================================================
# Collaborative Meal Planning Models (Chef-Customer)
# =============================================================================

class ChefMealPlan(models.Model):
    """Chef-created meal plan for a specific customer.
    
    Unlike user-generated MealPlan, this is created by the chef (with AI Sous Chef assistance)
    and can be collaboratively edited through customer suggestions.
    
    The date range is flexible - not forced to be weekly. Chefs can create plans
    for any date range based on their arrangement with the customer.
    """
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'
    
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED, 'Archived'),
    ]
    
    chef = models.ForeignKey(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='created_meal_plans'
    )
    customer = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chef_meal_plans',
        help_text="For platform users"
    )
    lead = models.ForeignKey(
        'crm.Lead',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chef_meal_plans',
        help_text="For off-platform clients (manual contacts)"
    )
    
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional title for the plan (e.g., 'Holiday Week', 'Back to School')"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Chef's notes for the customer about this plan"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-start_date', '-created_at']
        indexes = [
            models.Index(fields=['chef', 'customer', 'status']),
            models.Index(fields=['customer', 'status', '-start_date']),
            models.Index(fields=['chef', 'lead', 'status']),
            models.Index(fields=['lead', 'status', '-start_date']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['chef', 'customer', 'start_date'],
                condition=models.Q(customer__isnull=False),
                name='unique_chef_customer_plan_start'
            ),
            models.UniqueConstraint(
                fields=['chef', 'lead', 'start_date'],
                condition=models.Q(lead__isnull=False),
                name='unique_chef_lead_plan_start'
            ),
        ]
    
    def __str__(self):
        title = self.title or f"Plan {self.start_date}"
        client_name = self.get_client_name()
        return f"{title} for {client_name} by Chef {self.chef.user.username}"

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}

        if self.start_date and self.end_date and self.start_date > self.end_date:
            errors['end_date'] = 'End date must be after start date.'

        # Must have either customer or lead, but not both
        if self.customer and self.lead:
            errors['lead'] = 'Cannot have both a customer and a lead for the same meal plan.'
        if not self.customer and not self.lead:
            errors['customer'] = 'Must specify either a customer (platform user) or a lead (manual contact).'

        if errors:
            raise ValidationError(errors)

    @property
    def is_lead_plan(self):
        """Return True if this plan is for an off-platform lead."""
        return self.lead_id is not None

    def get_client_name(self):
        """Return the display name of the client (customer or lead)."""
        if self.lead:
            return f"{self.lead.first_name} {self.lead.last_name}".strip() or "Unknown"
        if self.customer:
            return f"{self.customer.first_name} {self.customer.last_name}".strip() or self.customer.username
        return "Unknown"

    def get_client_id(self):
        """Return the unified client ID with appropriate prefix."""
        if self.lead:
            return f"contact_{self.lead_id}"
        if self.customer:
            return f"platform_{self.customer_id}"
        return None
    
    def publish(self):
        """Publish the plan to make it visible to the customer."""
        self.status = self.STATUS_PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=['status', 'published_at', 'updated_at'])

        # Update activity tracking on the connection (only for platform customers)
        if self.customer:
            from chef_services.models import ChefCustomerConnection
            ChefCustomerConnection.objects.filter(
                chef=self.chef,
                customer=self.customer,
                status=ChefCustomerConnection.STATUS_ACCEPTED
            ).update(last_plan_update_at=timezone.now())
    
    def archive(self):
        """Archive the plan (typically after the date range has passed)."""
        self.status = self.STATUS_ARCHIVED
        self.save(update_fields=['status', 'updated_at'])

    def unpublish(self):
        """Revert plan to draft status for editing."""
        self.status = self.STATUS_DRAFT
        self.save(update_fields=['status', 'updated_at'])

    @property
    def pending_suggestions_count(self):
        """Count of customer suggestions awaiting chef review."""
        return self.suggestions.filter(status=MealPlanSuggestion.STATUS_PENDING).count()


class ChefMealPlanDay(models.Model):
    """Individual day in a chef-created meal plan.
    
    Days can be skipped for holidays, vacations, or other reasons.
    This gives flexibility for real-world meal planning scenarios.
    """
    plan = models.ForeignKey(
        ChefMealPlan,
        on_delete=models.CASCADE,
        related_name='days'
    )
    date = models.DateField()
    is_skipped = models.BooleanField(
        default=False,
        help_text="Whether this day is skipped (holiday, vacation, etc.)"
    )
    skip_reason = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reason for skipping (e.g., 'Thanksgiving', 'Family vacation')"
    )
    notes = models.TextField(
        blank=True,
        help_text="Chef's notes for this specific day"
    )
    
    class Meta:
        ordering = ['date']
        unique_together = ('plan', 'date')
        indexes = [
            models.Index(fields=['plan', 'date']),
        ]
    
    def __str__(self):
        if self.is_skipped:
            return f"{self.date} (skipped: {self.skip_reason or 'no reason'})"
        return f"{self.date}"


class ChefMealPlanItem(models.Model):
    """Individual meal within a day of a chef meal plan.
    
    This represents a specific meal (breakfast, lunch, dinner, snack)
    that the chef has planned for the customer on a given day.
    """
    MEAL_TYPE_CHOICES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('snack', 'Snack'),
    ]
    
    day = models.ForeignKey(
        ChefMealPlanDay,
        on_delete=models.CASCADE,
        related_name='items'
    )
    meal_type = models.CharField(
        max_length=20,
        choices=MEAL_TYPE_CHOICES
    )
    
    # Can link to an existing Meal or describe a custom meal
    meal = models.ForeignKey(
        'Meal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chef_plan_items',
        help_text="Link to an existing meal from the chef's menu"
    )
    custom_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Custom meal name if not using an existing meal"
    )
    custom_description = models.TextField(
        blank=True,
        help_text="Description for custom meals not in the database"
    )
    
    servings = models.PositiveIntegerField(
        default=1,
        help_text="Number of servings planned"
    )
    notes = models.TextField(
        blank=True,
        help_text="Chef's notes for this specific meal"
    )
    
    class Meta:
        ordering = ['meal_type']
        indexes = [
            models.Index(fields=['day', 'meal_type']),
        ]
    
    def __str__(self):
        name = self.meal.name if self.meal else self.custom_name or "Unnamed"
        return f"{self.get_meal_type_display()}: {name}"
    
    @property
    def display_name(self):
        """Return the meal name for display."""
        if self.meal:
            return self.meal.name
        return self.custom_name or "Unnamed Meal"
    
    @property
    def display_description(self):
        """Return the meal description for display."""
        if self.meal:
            return self.meal.description
        return self.custom_description


class MealPlanSuggestion(models.Model):
    """Customer's suggested change to a chef-created meal plan.
    
    This enables collaborative planning where customers can propose changes
    and chefs can approve, reject, or modify the suggestions.
    """
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_MODIFIED = 'modified'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_MODIFIED, 'Approved with Modifications'),
    ]
    
    SUGGESTION_TYPE_SWAP = 'swap_meal'
    SUGGESTION_TYPE_SKIP = 'skip_day'
    SUGGESTION_TYPE_ADD = 'add_day'
    SUGGESTION_TYPE_DIETARY = 'dietary_note'
    SUGGESTION_TYPE_GENERAL = 'general'
    
    SUGGESTION_TYPE_CHOICES = [
        (SUGGESTION_TYPE_SWAP, 'Swap this meal for something else'),
        (SUGGESTION_TYPE_SKIP, 'Skip this day'),
        (SUGGESTION_TYPE_ADD, 'Add a day to the plan'),
        (SUGGESTION_TYPE_DIETARY, 'Dietary concern/note'),
        (SUGGESTION_TYPE_GENERAL, 'General feedback'),
    ]
    
    plan = models.ForeignKey(
        ChefMealPlan,
        on_delete=models.CASCADE,
        related_name='suggestions'
    )
    customer = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='meal_plan_suggestions'
    )
    
    # Target of the suggestion (optional - depends on type)
    target_item = models.ForeignKey(
        ChefMealPlanItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='suggestions',
        help_text="The specific meal item this suggestion is about"
    )
    target_day = models.ForeignKey(
        ChefMealPlanDay,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='suggestions',
        help_text="The specific day this suggestion is about"
    )
    
    suggestion_type = models.CharField(
        max_length=20,
        choices=SUGGESTION_TYPE_CHOICES
    )
    description = models.TextField(
        help_text="Customer's explanation of their suggestion"
    )
    
    # Chef's response
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )
    chef_response = models.TextField(
        blank=True,
        help_text="Chef's response to the suggestion"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['plan', 'status']),
            models.Index(fields=['customer', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_suggestion_type_display()} by {self.customer.username} ({self.status})"
    
    def approve(self, response: str = ''):
        """Approve the suggestion."""
        self.status = self.STATUS_APPROVED
        self.chef_response = response
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'chef_response', 'reviewed_at'])
    
    def reject(self, response: str):
        """Reject the suggestion with a reason."""
        self.status = self.STATUS_REJECTED
        self.chef_response = response
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'chef_response', 'reviewed_at'])
    
    def approve_with_modifications(self, response: str):
        """Approve the suggestion with modifications."""
        self.status = self.STATUS_MODIFIED
        self.chef_response = response
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'chef_response', 'reviewed_at'])


class MealPlanGenerationJob(models.Model):
    """Tracks async AI meal generation jobs.
    
    When a chef requests meal suggestions, a job is created and processed
    in the background via Celery. The chef can continue working and check
    back for results.
    """
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]
    
    MODE_FULL_WEEK = 'full_week'
    MODE_FILL_EMPTY = 'fill_empty'
    MODE_SINGLE_SLOT = 'single_slot'
    
    MODE_CHOICES = [
        (MODE_FULL_WEEK, 'Generate Full Week'),
        (MODE_FILL_EMPTY, 'Fill Empty Slots'),
        (MODE_SINGLE_SLOT, 'Single Slot'),
    ]
    
    plan = models.ForeignKey(
        ChefMealPlan,
        on_delete=models.CASCADE,
        related_name='generation_jobs'
    )
    chef = models.ForeignKey(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='meal_generation_jobs'
    )
    
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default=MODE_FILL_EMPTY
    )
    target_day = models.CharField(max_length=20, blank=True)
    target_meal_type = models.CharField(max_length=20, blank=True)
    custom_prompt = models.TextField(blank=True)
    week_offset = models.PositiveIntegerField(
        default=0,
        help_text="0-indexed week number to generate for (0 = first week, 1 = second, etc.)"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )
    
    # Results stored as JSON
    suggestions = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    
    # Metadata
    slots_requested = models.IntegerField(default=0)
    slots_generated = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['plan', 'status']),
            models.Index(fields=['chef', '-created_at']),
        ]
    
    def __str__(self):
        return f"Generation Job {self.id} for Plan {self.plan_id} ({self.status})"
    
    def mark_processing(self):
        """Mark job as started."""
        self.status = self.STATUS_PROCESSING
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def mark_completed(self, suggestions: list):
        """Mark job as completed with suggestions."""
        self.status = self.STATUS_COMPLETED
        self.suggestions = suggestions
        self.slots_generated = len(suggestions)
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'suggestions', 'slots_generated', 'completed_at'])
    
    def mark_failed(self, error: str):
        """Mark job as failed with error message."""
        self.status = self.STATUS_FAILED
        self.error_message = error
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'completed_at'])
