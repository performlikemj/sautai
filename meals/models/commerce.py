# meals/models/commerce.py
"""
Commerce models: Cart, Order, OrderMeal, StripeConnectAccount, PlatformFeeConfig, 
PaymentLog, MealPlanReceipt
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

import decimal
import logging

from custom_auth.models import CustomUser
# Use string reference 'chefs.Chef' in ForeignKey fields to avoid circular import

logger = logging.getLogger(__name__)


class Cart(models.Model):
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    meal = models.ManyToManyField('Meal')
    meal_plan = models.ForeignKey('MealPlan', null=True, blank=True, on_delete=models.SET_NULL)
    # Support for chef service orders in cart
    chef_service_orders = models.ManyToManyField('chef_services.ChefServiceOrder', blank=True, related_name='carts')

    def __str__(self):
        return f'Cart for {self.customer.username}'
    
    def get_all_chefs(self):
        """
        Get all unique chefs from cart items (meals and chef services).
        Returns a set of Chef objects.
        """
        chefs = set()
        
        # Get chefs from meals
        for meal in self.meal.all():
            if hasattr(meal, 'chef'):
                chefs.add(meal.chef)
        
        # Get chefs from chef service orders
        for service_order in self.chef_service_orders.filter(status='draft'):
            chefs.add(service_order.chef)
        
        return chefs
    
    def is_single_chef_cart(self):
        """
        Check if all cart items are from a single chef.
        Required for Stripe Connect checkout (can only transfer to one account).
        """
        chefs = self.get_all_chefs()
        return len(chefs) <= 1
    
    def get_cart_chef(self):
        """
        Get the chef for this cart if it's a single-chef cart.
        Returns None if cart is empty or has multiple chefs.
        """
        chefs = self.get_all_chefs()
        return list(chefs)[0] if len(chefs) == 1 else None
    

class Order(models.Model):
    # in your Order model
    ORDER_STATUS_CHOICES = [
        ('Placed', 'Placed'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled'),
        ('Refunded', 'Refunded'),
        ('Delayed', 'Delayed')
    ]

    DELIVERY_CHOICES = [
        ('Pickup', 'Pickup'),
        ('Delivery', 'Delivery'),
    ]

    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    address = models.ForeignKey('custom_auth.Address', null=True, on_delete=models.SET_NULL)
    meal = models.ManyToManyField('Meal', through='OrderMeal')
    order_date = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='Placed')
    delivery_method = models.CharField(max_length=10, choices=DELIVERY_CHOICES, default='Pickup')
    special_requests = models.TextField(blank=True)
    is_paid = models.BooleanField(default=False)
    meal_plan = models.ForeignKey('MealPlan', null=True, blank=True, on_delete=models.SET_NULL, related_name='related_orders')
    
    # Stripe payment tracking
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True, help_text="Stripe Checkout Session ID")

    def save(self, *args, **kwargs):
        if not self.order_date:  # only update if order_date is not already set
            self.order_date = timezone.now()
        self.updated_at = timezone.now()  # always update the last updated time
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Order {self.id} - {self.customer.username}'

    def total_price(self):
        """
        Calculate the total price of the order, using OrderMeal's get_price method
        to ensure consistent pricing.
        """
        total = decimal.Decimal('0.00')  # Use Decimal for currency
        # Fetch related objects efficiently
        order_meals = self.ordermeal_set.select_related('meal', 'chef_meal_event', 'meal_plan_meal').all()

        for order_meal in order_meals:
            # Skip meals that have already been paid for
            meal_plan_meal = order_meal.meal_plan_meal
            if hasattr(meal_plan_meal, 'already_paid') and meal_plan_meal.already_paid:
                # Skip this item in the total calculation
                continue
                
            # Get the price using the OrderMeal's get_price method for consistency
            item_price = order_meal.get_price()
            
            # Ensure quantity is valid (should be integer, but convert for safety)
            quantity = decimal.Decimal(order_meal.quantity) if order_meal.quantity is not None else decimal.Decimal('0')
            total += item_price * quantity

        return total


class OrderMeal(models.Model):
    meal = models.ForeignKey('Meal', on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    meal_plan_meal = models.ForeignKey('MealPlanMeal', on_delete=models.CASCADE)  # Existing field
    chef_meal_event = models.ForeignKey('ChefMealEvent', null=True, blank=True, on_delete=models.SET_NULL) 
    quantity = models.IntegerField()
    
    # Store the price at the time of order creation to avoid discrepancies
    price_at_order = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                         help_text="Price at the time of order creation")

    def __str__(self):
        return f'{self.meal} - {self.order} on {self.meal_plan_meal.day}'
        
    def save(self, *args, **kwargs):
        # If this is a new order meal, set the price_at_order
        if not self.pk:
            # For chef meal events, always use the current_price from the event
            if self.chef_meal_event and self.chef_meal_event.current_price is not None:
                self.price_at_order = self.chef_meal_event.current_price
            # Otherwise use the meal price
            elif self.meal and self.meal.price is not None:
                self.price_at_order = self.meal.price
                
        super().save(*args, **kwargs)
    
    def get_price(self):
        """
        Returns the price for this order meal, prioritizing:
        1. Stored price_at_order if available
        2. Current chef_meal_event price if linked
        3. Base meal price as fallback
        """
        if self.price_at_order is not None:
            return self.price_at_order
        elif self.chef_meal_event and self.chef_meal_event.current_price is not None:
            return self.chef_meal_event.current_price
        elif self.meal and self.meal.price is not None:
            return self.meal.price
        return decimal.Decimal('0.00')  # Default fallback


# StripeConnect model to store chef's Stripe connection information
class StripeConnectAccount(models.Model):
    chef = models.OneToOneField('chefs.Chef', on_delete=models.CASCADE, related_name='stripe_account')
    stripe_account_id = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Stripe account for {self.chef.user.username}"


# Add platform fee configuration
class PlatformFeeConfig(models.Model):
    """Configures the platform fee percentage for chef meal orders"""
    fee_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100)
        ],
        help_text="Platform fee percentage (0-100)"
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Platform Fee: {self.fee_percentage}%"
    
    def save(self, *args, **kwargs):
        # Ensure only one active config exists
        if self.active:
            PlatformFeeConfig.objects.filter(active=True).exclude(pk=self.pk).update(active=False)
        super().save(*args, **kwargs)
    
    @classmethod
    def get_active_fee(cls):
        """Get the currently active fee percentage"""
        try:
            return cls.objects.filter(active=True).first().fee_percentage
        except AttributeError:
            # Return a default value if no active fee config exists
            return 10  # 10% default


# Payment audit log
class PaymentLog(models.Model):
    """Logs all payment-related actions for auditing"""
    ACTION_CHOICES = [
        ('charge', 'Charge'),
        ('refund', 'Refund'),
        ('payout', 'Payout to Chef'),
        ('adjustment', 'Manual Adjustment'),
        ('dispute', 'Dispute/Chargeback'),
        ('transfer', 'Transfer to Chef'),
        ('transfer_reversal', 'Transfer Reversal'),
    ]
    
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name='payment_logs')
    chef_meal_order = models.ForeignKey('ChefMealOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='payment_logs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    chef = models.ForeignKey('chefs.Chef', null=True, blank=True, on_delete=models.SET_NULL)
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_id = models.CharField(max_length=255, blank=True)
    
    status = models.CharField(max_length=50)
    details = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        action_entity = f"Order #{self.order.id}" if self.order else f"ChefMealOrder #{self.chef_meal_order.id}" if self.chef_meal_order else "Unknown"
        return f"{self.action} - {action_entity} - {self.amount}"


# =============================================================================
# Purchase Receipt Models (for ingredient/shopping tracking)
# =============================================================================

class MealPlanReceipt(models.Model):
    """
    Receipt for purchases related to meal plans, prep plans, or general chef expenses.
    
    Chefs can upload receipts to track ingredient purchases, associate them with
    specific meal plans or customers, and maintain records for reimbursement or
    accounting purposes.
    """
    CATEGORY_CHOICES = [
        ('ingredients', 'Ingredients'),
        ('supplies', 'Cooking Supplies'),
        ('equipment', 'Equipment'),
        ('packaging', 'Packaging'),
        ('delivery', 'Delivery/Transport'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('reviewed', 'Reviewed'),
        ('reimbursed', 'Reimbursed'),
        ('rejected', 'Rejected'),
    ]
    
    # Ownership
    chef = models.ForeignKey(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='receipts',
        help_text="The chef who uploaded this receipt"
    )
    
    # Customer association (optional)
    customer = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chef_receipts',
        help_text="Customer this expense is associated with (for billing)"
    )
    
    # Meal plan associations (all optional - a receipt may be general)
    meal_plan = models.ForeignKey(
        'MealPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receipts',
        help_text="User-generated meal plan this receipt is for"
    )
    chef_meal_plan = models.ForeignKey(
        'ChefMealPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receipts',
        help_text="Chef-created meal plan this receipt is for"
    )
    prep_plan = models.ForeignKey(
        'chefs.ChefPrepPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receipts',
        help_text="Prep plan this receipt is associated with"
    )
    
    # Receipt details
    receipt_image = models.ImageField(
        upload_to='receipts/%Y/%m/',
        help_text="Photo/scan of the receipt"
    )
    receipt_thumbnail = models.ImageField(
        upload_to='receipts/thumbnails/%Y/%m/',
        blank=True,
        null=True,
        help_text="Auto-generated thumbnail"
    )
    
    # Financial info
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total amount on the receipt"
    )
    currency = models.CharField(max_length=3, default='USD')
    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Tax portion of the total"
    )
    
    # Metadata
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='ingredients'
    )
    merchant_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Store/vendor name"
    )
    purchase_date = models.DateField(
        help_text="Date of purchase"
    )
    description = models.TextField(
        blank=True,
        help_text="Description of items purchased"
    )
    
    # Itemized breakdown (optional, JSON for flexibility)
    items = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional itemized list: [{name, quantity, unit_price, total}]"
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='uploaded'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_receipts'
    )
    reviewer_notes = models.TextField(
        blank=True,
        help_text="Admin/reviewer notes"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-purchase_date', '-created_at']
        indexes = [
            models.Index(fields=['chef', '-purchase_date']),
            models.Index(fields=['chef', 'status']),
            models.Index(fields=['chef', 'customer', '-purchase_date']),
            models.Index(fields=['chef', 'category']),
        ]
    
    def __str__(self):
        merchant = self.merchant_name or "Receipt"
        return f"{merchant} - {self.currency} {self.amount} ({self.purchase_date})"
    
    def save(self, *args, **kwargs):
        """Extract image dimensions on save."""
        if self.receipt_image and hasattr(self.receipt_image, 'file'):
            try:
                from PIL import Image
                from io import BytesIO
                from django.core.files.uploadedfile import InMemoryUploadedFile
                
                # Generate thumbnail
                image = Image.open(self.receipt_image.file)
                image.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                thumb_io = BytesIO()
                thumb_format = 'JPEG' if image.mode == 'RGB' else 'PNG'
                image.save(thumb_io, format=thumb_format, quality=85)
                thumb_io.seek(0)
                
                # Only set thumbnail if not already set
                if not self.receipt_thumbnail:
                    ext = '.jpg' if thumb_format == 'JPEG' else '.png'
                    thumb_name = f"thumb_{self.receipt_image.name.split('/')[-1].rsplit('.', 1)[0]}{ext}"
                    self.receipt_thumbnail = InMemoryUploadedFile(
                        thumb_io, 'ImageField', thumb_name,
                        f'image/{thumb_format.lower()}', thumb_io.tell(), None
                    )
                
                self.receipt_image.file.seek(0)
            except Exception:
                pass  # Silently fail thumbnail generation
        
        super().save(*args, **kwargs)
    
    @property
    def subtotal(self):
        """Calculate subtotal (amount minus tax)."""
        if self.tax_amount:
            return self.amount - self.tax_amount
        return self.amount
