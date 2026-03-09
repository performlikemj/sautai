"""
Tests for the community membership system.
"""

from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone

from chefs.models import Chef
from custom_auth.models import CustomUser
from .models import ChefMembership, MembershipPaymentLog


class ChefMembershipModelTests(TestCase):
    """Tests for the ChefMembership model."""
    
    def setUp(self):
        """Create a test user and chef."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='testchef@example.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(
            user=self.user,
            bio='Test chef bio'
        )
    
    def test_create_membership(self):
        """Test creating a basic membership."""
        membership = ChefMembership.objects.create(
            chef=self.chef,
            status=ChefMembership.Status.TRIAL,
            billing_cycle=ChefMembership.BillingCycle.MONTHLY,
        )
        
        self.assertEqual(membership.chef, self.chef)
        self.assertEqual(membership.status, ChefMembership.Status.TRIAL)
        self.assertTrue(membership.is_active_member)  # TRIAL status is considered active
    
    def test_trial_membership(self):
        """Test trial membership status."""
        membership = ChefMembership.objects.create(
            chef=self.chef,
            status=ChefMembership.Status.TRIAL,
        )
        
        # Start a 14-day trial
        membership.start_trial(days=14)
        
        self.assertTrue(membership.is_in_trial)
        self.assertEqual(membership.days_until_trial_ends, 13)  # ~14 days minus a few seconds
        self.assertTrue(membership.is_active_member)
    
    def test_activate_membership(self):
        """Test activating a membership."""
        membership = ChefMembership.objects.create(
            chef=self.chef,
            status=ChefMembership.Status.TRIAL,
        )
        
        membership.activate()
        membership.refresh_from_db()
        
        self.assertEqual(membership.status, ChefMembership.Status.ACTIVE)
        self.assertTrue(membership.is_active_member)
    
    def test_cancel_membership(self):
        """Test cancelling a membership."""
        membership = ChefMembership.objects.create(
            chef=self.chef,
            status=ChefMembership.Status.ACTIVE,
        )
        
        membership.cancel()
        membership.refresh_from_db()
        
        self.assertEqual(membership.status, ChefMembership.Status.CANCELLED)
        self.assertFalse(membership.is_active_member)
        self.assertIsNotNone(membership.cancelled_at)
    
    @override_settings(
        MEMBERSHIP_PRODUCT_ID='prod_test123',
        MEMBERSHIP_MONTHLY_PRICE_ID='price_monthly_test',
        MEMBERSHIP_ANNUAL_PRICE_ID='price_annual_test',
    )
    def test_get_price_id_for_cycle(self):
        """Test getting correct Stripe price ID for billing cycle."""
        # Reload module-level constants from overridden settings
        from django.conf import settings
        import memberships.models as mm
        mm.MEMBERSHIP_MONTHLY_PRICE_ID = settings.MEMBERSHIP_MONTHLY_PRICE_ID
        mm.MEMBERSHIP_ANNUAL_PRICE_ID = settings.MEMBERSHIP_ANNUAL_PRICE_ID

        monthly_id = ChefMembership.get_price_id_for_cycle(
            ChefMembership.BillingCycle.MONTHLY
        )
        annual_id = ChefMembership.get_price_id_for_cycle(
            ChefMembership.BillingCycle.ANNUAL
        )

        self.assertIn('price_', monthly_id)
        self.assertIn('price_', annual_id)
        self.assertNotEqual(monthly_id, annual_id)


class MembershipPaymentLogTests(TestCase):
    """Tests for payment logging."""
    
    def setUp(self):
        """Create test membership."""
        self.user = CustomUser.objects.create_user(
            username='testchef2',
            email='testchef2@example.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.membership = ChefMembership.objects.create(
            chef=self.chef,
            status=ChefMembership.Status.ACTIVE,
        )
    
    def test_log_payment(self):
        """Test logging a payment."""
        payment = MembershipPaymentLog.log_payment(
            membership=self.membership,
            amount_cents=2000,
            invoice_id='inv_test123',
        )
        
        self.assertEqual(payment.amount_cents, 2000)
        self.assertEqual(payment.amount_dollars, 20.0)
        self.assertEqual(payment.stripe_invoice_id, 'inv_test123')
        self.assertIsNotNone(payment.paid_at)
    
    def test_payment_with_period(self):
        """Test logging payment with billing period."""
        period_start = timezone.now()
        period_end = period_start + timedelta(days=30)
        
        payment = MembershipPaymentLog.log_payment(
            membership=self.membership,
            amount_cents=2000,
            period_start=period_start,
            period_end=period_end,
        )
        
        self.assertEqual(payment.period_start, period_start)
        self.assertEqual(payment.period_end, period_end)


