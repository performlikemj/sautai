"""
Community membership models for the Sautai chef cooperative.

This module implements a flat-rate membership system where all chefs
pay the same amount and receive equal access to platform features.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


# Stripe IDs loaded from environment via Django settings
MEMBERSHIP_PRODUCT_ID = settings.MEMBERSHIP_PRODUCT_ID
MEMBERSHIP_MONTHLY_PRICE_ID = settings.MEMBERSHIP_MONTHLY_PRICE_ID
MEMBERSHIP_ANNUAL_PRICE_ID = settings.MEMBERSHIP_ANNUAL_PRICE_ID


class ChefMembership(models.Model):
    """
    Tracks a chef's community membership status and Stripe subscription.
    
    All members have equal access to features - there are no tiers.
    The membership funds platform operations and community initiatives.
    """
    
    class Status(models.TextChoices):
        TRIAL = 'trial', 'Trial'
        ACTIVE = 'active', 'Active'
        PAST_DUE = 'past_due', 'Past Due'
        CANCELLED = 'cancelled', 'Cancelled'
        PAUSED = 'paused', 'Paused'
        FOUNDING = 'founding', 'Founding Member'  # Free access for early testers
    
    class BillingCycle(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly ($20/month)'
        ANNUAL = 'annual', 'Annual ($204/year)'
        FREE = 'free', 'Free (Founding Member)'
    
    chef = models.OneToOneField(
        'chefs.Chef',
        on_delete=models.CASCADE,
        related_name='membership'
    )
    
    # Founding member flag - bypasses payment requirements
    is_founding_member = models.BooleanField(
        default=False,
        help_text="Founding members get free access during the testing phase"
    )
    founding_member_notes = models.TextField(
        blank=True,
        help_text="Notes about why this chef is a founding member"
    )
    
    # Stripe integration
    stripe_customer_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Customer ID for this chef"
    )
    stripe_subscription_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Subscription ID for the membership"
    )
    
    # Billing configuration
    billing_cycle = models.CharField(
        max_length=10,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY
    )
    
    # Membership status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIAL
    )
    
    # Trial tracking
    trial_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the trial period began"
    )
    trial_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the trial period ends"
    )
    
    # Current billing period (synced from Stripe)
    current_period_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Start of current billing period"
    )
    current_period_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="End of current billing period"
    )
    
    # Lifecycle timestamps
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the membership was first created"
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the membership was cancelled"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Chef Membership'
        verbose_name_plural = 'Chef Memberships'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['stripe_customer_id']),
            models.Index(fields=['stripe_subscription_id']),
        ]
    
    def __str__(self):
        return f"Membership({self.chef.user.username}, {self.status})"
    
    @property
    def is_active_member(self):
        """Check if the chef has an active or trialing membership."""
        # Founding members always have access
        if self.is_founding_member:
            return True
        return self.status in [self.Status.ACTIVE, self.Status.TRIAL, self.Status.FOUNDING]
    
    @property
    def is_in_trial(self):
        """Check if the chef is currently in their trial period."""
        if self.status != self.Status.TRIAL:
            return False
        if not self.trial_ends_at:
            return False
        return timezone.now() < self.trial_ends_at
    
    @property
    def days_until_trial_ends(self):
        """Return days remaining in trial, or None if not in trial."""
        if not self.is_in_trial:
            return None
        delta = self.trial_ends_at - timezone.now()
        return max(0, delta.days)
    
    def start_trial(self, days=7):
        """Start a trial period for this membership."""
        now = timezone.now()
        self.status = self.Status.TRIAL
        self.trial_started_at = now
        self.trial_ends_at = now + timezone.timedelta(days=days)
        self.save(update_fields=[
            'status', 'trial_started_at', 'trial_ends_at', 'updated_at'
        ])
    
    def activate(self):
        """Activate the membership (called after successful payment)."""
        self.status = self.Status.ACTIVE
        self.save(update_fields=['status', 'updated_at'])
    
    def mark_past_due(self):
        """Mark membership as past due (payment failed)."""
        self.status = self.Status.PAST_DUE
        self.save(update_fields=['status', 'updated_at'])
    
    def cancel(self):
        """Cancel the membership."""
        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'cancelled_at', 'updated_at'])
    
    def pause(self):
        """Pause the membership (keeps data, suspends billing)."""
        self.status = self.Status.PAUSED
        self.save(update_fields=['status', 'updated_at'])
    
    def update_billing_period(self, period_start, period_end):
        """Update the current billing period from Stripe webhook data."""
        from datetime import datetime
        
        # Convert Unix timestamps to datetime if needed
        if isinstance(period_start, (int, float)):
            period_start = timezone.datetime.fromtimestamp(
                period_start, tz=timezone.utc
            )
        if isinstance(period_end, (int, float)):
            period_end = timezone.datetime.fromtimestamp(
                period_end, tz=timezone.utc
            )
        
        self.current_period_start = period_start
        self.current_period_end = period_end
        self.save(update_fields=[
            'current_period_start', 'current_period_end', 'updated_at'
        ])
    
    @classmethod
    def get_price_id_for_cycle(cls, billing_cycle):
        """Return the Stripe price ID for the given billing cycle."""
        if billing_cycle == cls.BillingCycle.ANNUAL:
            return MEMBERSHIP_ANNUAL_PRICE_ID
        return MEMBERSHIP_MONTHLY_PRICE_ID
    
    @classmethod
    def grant_founding_membership(cls, chef, notes=''):
        """
        Grant founding member status to a chef.
        
        Founding members get free access during the testing phase.
        This is useful for early testers and community builders.
        
        Args:
            chef: Chef instance
            notes: Optional notes about why they're a founding member
            
        Returns:
            ChefMembership instance
        """
        membership, created = cls.objects.update_or_create(
            chef=chef,
            defaults={
                'is_founding_member': True,
                'founding_member_notes': notes,
                'status': cls.Status.FOUNDING,
                'billing_cycle': cls.BillingCycle.FREE,
            }
        )
        return membership


class MembershipPaymentLog(models.Model):
    """
    Log of all membership payments for transparency and reporting.
    
    This enables the cooperative to show members exactly how much
    has been contributed and supports financial transparency.
    """
    
    membership = models.ForeignKey(
        ChefMembership,
        on_delete=models.CASCADE,
        related_name='payment_logs'
    )
    
    # Payment details
    amount_cents = models.PositiveIntegerField(
        help_text="Amount paid in cents"
    )
    currency = models.CharField(
        max_length=3,
        default='usd'
    )
    
    # Stripe references
    stripe_invoice_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Invoice ID"
    )
    stripe_payment_intent_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Payment Intent ID"
    )
    stripe_charge_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Stripe Charge ID"
    )
    
    # Period this payment covers
    period_start = models.DateTimeField(
        null=True,
        blank=True
    )
    period_end = models.DateTimeField(
        null=True,
        blank=True
    )
    
    # Timestamps
    paid_at = models.DateTimeField(
        help_text="When the payment was processed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Membership Payment Log'
        verbose_name_plural = 'Membership Payment Logs'
        ordering = ['-paid_at']
        indexes = [
            models.Index(fields=['membership', '-paid_at']),
            models.Index(fields=['stripe_invoice_id']),
        ]
    
    def __str__(self):
        return f"Payment(${self.amount_cents/100:.2f}, {self.paid_at.date()})"
    
    @property
    def amount_dollars(self):
        """Return the amount in dollars."""
        return self.amount_cents / 100
    
    @classmethod
    def log_payment(cls, membership, amount_cents, invoice_id=None, 
                    payment_intent_id=None, charge_id=None,
                    period_start=None, period_end=None, paid_at=None):
        """
        Create a payment log entry.
        
        Args:
            membership: ChefMembership instance
            amount_cents: Amount in cents
            invoice_id: Stripe invoice ID
            payment_intent_id: Stripe payment intent ID
            charge_id: Stripe charge ID
            period_start: Start of billing period
            period_end: End of billing period
            paid_at: When payment was made (defaults to now)
        
        Returns:
            MembershipPaymentLog instance
        """
        if paid_at is None:
            paid_at = timezone.now()
        
        return cls.objects.create(
            membership=membership,
            amount_cents=amount_cents,
            stripe_invoice_id=invoice_id,
            stripe_payment_intent_id=payment_intent_id,
            stripe_charge_id=charge_id,
            period_start=period_start,
            period_end=period_end,
            paid_at=paid_at,
        )










