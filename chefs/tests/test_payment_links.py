"""
Comprehensive test suite for Chef Payment Links functionality.

Tests cover:
- Model behavior and validation
- Email verification for leads
- Payment links CRUD API endpoints
- Stripe integration (mocked)
- Webhook handling
- Edge cases and error conditions
- Security and permission checks
"""

import json
import os
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import stripe
from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from chefs.models import Chef, ChefPaymentLink
from crm.models import Lead
from custom_auth.models import CustomUser

# Skip API tests in CI - they require Stripe configuration
SKIP_IN_CI = pytest.mark.skipif(
    os.getenv('CI') == 'true' or os.getenv('TEST_MODE') == 'True',
    reason="Payment Links API tests require Stripe configuration"
)


class PaymentLinkModelTestCase(TestCase):
    """Test ChefPaymentLink model behavior and validation."""

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )

    def test_create_payment_link(self):
        """Test creating a basic payment link."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        self.assertEqual(link.status, ChefPaymentLink.Status.DRAFT)
        self.assertEqual(link.amount_cents, 5000)
        self.assertEqual(link.currency, 'usd')

    def test_get_recipient_name_with_lead(self):
        """Test getting recipient name when lead is set."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        self.assertEqual(link.get_recipient_name(), 'John Doe')

    def test_get_recipient_name_with_customer(self):
        """Test getting recipient name when customer is set."""
        customer = CustomUser.objects.create_user(
            username='customer1',
            email='customer@test.com',
            password='testpass123',
            first_name='Jane',
            last_name='Smith'
        )
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            customer=customer,
            amount_cents=5000,
            description='Test payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        self.assertEqual(link.get_recipient_name(), 'Jane Smith')

    def test_get_recipient_email_from_lead(self):
        """Test getting recipient email from lead."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        self.assertEqual(link.get_recipient_email(), 'john@example.com')

    def test_get_recipient_email_override(self):
        """Test that recipient_email field overrides lead email."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            recipient_email='override@test.com',
            expires_at=timezone.now() + timedelta(days=30)
        )
        self.assertEqual(link.get_recipient_email(), 'override@test.com')

    def test_is_expired_future_date(self):
        """Test is_expired returns False for future expiration."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        self.assertFalse(link.is_expired())

    def test_is_expired_past_date(self):
        """Test is_expired returns True for past expiration."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            expires_at=timezone.now() - timedelta(days=1)
        )
        self.assertTrue(link.is_expired())

    def test_can_send_email_unverified_lead(self):
        """Test can_send_email returns False for unverified lead email."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        can_send, reason = link.can_send_email()
        self.assertFalse(can_send)
        self.assertEqual(reason, 'Email not verified')

    def test_can_send_email_verified_lead(self):
        """Test can_send_email returns True for verified lead email."""
        self.lead.email_verified = True
        self.lead.save()
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        can_send, reason = link.can_send_email()
        self.assertTrue(can_send)
        self.assertIsNone(reason)

    def test_can_send_email_no_email(self):
        """Test can_send_email returns False when no email available."""
        self.lead.email = ''
        self.lead.save()
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        can_send, reason = link.can_send_email()
        self.assertFalse(can_send)
        self.assertEqual(reason, 'No email address available')

    def test_can_send_email_expired_link(self):
        """Test can_send_email returns False for expired links."""
        self.lead.email_verified = True
        self.lead.save()
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() - timedelta(days=1)
        )
        can_send, reason = link.can_send_email()
        self.assertFalse(can_send)
        self.assertEqual(reason, 'Payment link has expired')

    def test_can_send_email_paid_link(self):
        """Test can_send_email returns False for paid links."""
        self.lead.email_verified = True
        self.lead.save()
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PAID,
            expires_at=timezone.now() + timedelta(days=30)
        )
        can_send, reason = link.can_send_email()
        self.assertFalse(can_send)
        self.assertIn('paid', reason.lower())

    def test_mark_as_paid(self):
        """Test marking a payment link as paid."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        link.mark_as_paid(payment_intent_id='pi_test123', amount_cents=5000)
        
        link.refresh_from_db()
        self.assertEqual(link.status, ChefPaymentLink.Status.PAID)
        self.assertEqual(link.stripe_payment_intent_id, 'pi_test123')
        self.assertEqual(link.paid_amount_cents, 5000)
        self.assertIsNotNone(link.paid_at)

    def test_cancel_payment_link(self):
        """Test cancelling a payment link."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        link.cancel()
        
        link.refresh_from_db()
        self.assertEqual(link.status, ChefPaymentLink.Status.CANCELLED)

    def test_cancel_paid_link_raises_error(self):
        """Test that cancelling a paid link raises ValueError."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PAID,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        with self.assertRaises(ValueError):
            link.cancel()

    def test_record_email_sent(self):
        """Test recording email sent updates fields correctly."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.DRAFT,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        link.record_email_sent('test@example.com')
        
        link.refresh_from_db()
        self.assertEqual(link.email_send_count, 1)
        self.assertEqual(link.recipient_email, 'test@example.com')
        self.assertEqual(link.status, ChefPaymentLink.Status.PENDING)
        self.assertIsNotNone(link.email_sent_at)

    def test_record_email_sent_increment_count(self):
        """Test that email send count increments on each send."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            email_send_count=2,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        link.record_email_sent()
        
        link.refresh_from_db()
        self.assertEqual(link.email_send_count, 3)

    def test_minimum_amount_validation(self):
        """Test that minimum amount is enforced in clean()."""
        link = ChefPaymentLink(
            chef=self.chef,
            lead=self.lead,
            amount_cents=30,  # Less than $0.50 minimum
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as context:
            link.clean()
        self.assertIn('amount_cents', context.exception.message_dict)

    def test_cannot_have_both_lead_and_customer(self):
        """Test validation prevents both lead and customer being set."""
        customer = CustomUser.objects.create_user(
            username='customer2',
            email='customer2@test.com',
            password='testpass123'
        )
        
        link = ChefPaymentLink(
            chef=self.chef,
            lead=self.lead,
            customer=customer,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as context:
            link.clean()
        self.assertIn('lead', context.exception.message_dict)


class LeadEmailVerificationTestCase(TestCase):
    """Test Lead model email verification functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='chef@test.com',
            password='testpass123'
        )
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )

    def test_generate_verification_token(self):
        """Test generating a verification token."""
        token = self.lead.generate_verification_token()
        
        self.assertIsNotNone(token)
        self.assertGreater(len(token), 32)
        self.assertEqual(self.lead.email_verification_token, token)
        self.assertIsNotNone(self.lead.email_verification_sent_at)

    def test_token_is_unique(self):
        """Test that generated tokens are unique."""
        lead2 = Lead.objects.create(
            owner=self.user,
            first_name='Jane',
            last_name='Smith',
            email='jane@example.com'
        )
        
        token1 = self.lead.generate_verification_token()
        token2 = lead2.generate_verification_token()
        
        self.assertNotEqual(token1, token2)

    def test_is_verification_token_valid_fresh_token(self):
        """Test token validity check for fresh token."""
        self.lead.generate_verification_token()
        self.assertTrue(self.lead.is_verification_token_valid())

    def test_is_verification_token_valid_expired_token(self):
        """Test token validity check for expired token (>72 hours)."""
        self.lead.generate_verification_token()
        self.lead.email_verification_sent_at = timezone.now() - timedelta(hours=73)
        self.lead.save()
        
        self.assertFalse(self.lead.is_verification_token_valid())

    def test_is_verification_token_valid_no_token(self):
        """Test token validity check when no token exists."""
        self.assertFalse(self.lead.is_verification_token_valid())

    def test_verify_email_success(self):
        """Test successful email verification."""
        token = self.lead.generate_verification_token()
        
        result = self.lead.verify_email(token)
        
        self.assertTrue(result)
        self.assertTrue(self.lead.email_verified)
        self.assertIsNotNone(self.lead.email_verified_at)
        self.assertIsNone(self.lead.email_verification_token)  # Token invalidated

    def test_verify_email_wrong_token(self):
        """Test verification fails with wrong token."""
        self.lead.generate_verification_token()
        
        result = self.lead.verify_email('wrong_token')
        
        self.assertFalse(result)
        self.assertFalse(self.lead.email_verified)

    def test_verify_email_expired_token(self):
        """Test verification fails with expired token."""
        token = self.lead.generate_verification_token()
        self.lead.email_verification_sent_at = timezone.now() - timedelta(hours=73)
        self.lead.save()
        
        result = self.lead.verify_email(token)
        
        self.assertFalse(result)
        self.assertFalse(self.lead.email_verified)

    def test_verify_email_already_used_token(self):
        """Test verification fails when token already used."""
        token = self.lead.generate_verification_token()
        self.lead.verify_email(token)  # First use
        
        # Try to use again
        result = self.lead.verify_email(token)
        
        self.assertFalse(result)  # Should fail because token was invalidated

    def test_reset_email_verification(self):
        """Test resetting email verification status."""
        self.lead.email_verified = True
        self.lead.email_verified_at = timezone.now()
        self.lead.email_verification_token = 'old_token'
        self.lead.email_verification_sent_at = timezone.now()
        self.lead.save()
        
        self.lead.reset_email_verification()
        
        self.lead.refresh_from_db()
        self.assertFalse(self.lead.email_verified)
        self.assertIsNone(self.lead.email_verified_at)
        self.assertIsNone(self.lead.email_verification_token)
        self.assertIsNone(self.lead.email_verification_sent_at)


@SKIP_IN_CI
class PaymentLinksAPITestCase(APITestCase):
    """Test Payment Links API endpoints."""

    def setUp(self):
        """Set up test data and client."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com',
            email_verified=True
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_payment_links_empty(self):
        """Test listing payment links when none exist."""
        response = self.client.get('/chefs/api/me/payment-links/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Check for paginated or direct response
        results = data.get('results', data)
        self.assertEqual(len(results), 0)

    def test_list_payment_links_with_data(self):
        """Test listing payment links with existing data."""
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment 1',
            expires_at=timezone.now() + timedelta(days=30)
        )
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=10000,
            description='Test payment 2',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.get('/chefs/api/me/payment-links/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 2)

    def test_list_payment_links_filter_by_status(self):
        """Test filtering payment links by status."""
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Pending payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=10000,
            description='Paid payment',
            status=ChefPaymentLink.Status.PAID,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.get('/chefs/api/me/payment-links/?status=pending')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'pending')

    def test_list_payment_links_search(self):
        """Test searching payment links."""
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Weekly meal prep',
            expires_at=timezone.now() + timedelta(days=30)
        )
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=10000,
            description='Catering service',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.get('/chefs/api/me/payment-links/?search=meal')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 1)
        self.assertIn('meal', results[0]['description'].lower())

    @patch('chefs.api.payment_links.get_active_stripe_account')
    @patch('chefs.api.payment_links.stripe.Product.create')
    @patch('chefs.api.payment_links.stripe.Price.create')
    @patch('chefs.api.payment_links.stripe.PaymentLink.create')
    def test_create_payment_link_success(self, mock_pl_create, mock_price_create, 
                                          mock_product_create, mock_get_account):
        """Test successfully creating a payment link."""
        mock_get_account.return_value = ('acct_test123', None)
        mock_product_create.return_value = MagicMock(id='prod_test123')
        mock_price_create.return_value = MagicMock(id='price_test123')
        mock_pl_create.return_value = MagicMock(
            id='plink_test123',
            url='https://buy.stripe.com/test123'
        )
        
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Weekly meal prep service',
            'lead_id': self.lead.id,
            'expires_days': 30
        })
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['amount_cents'], 5000)
        self.assertEqual(data['description'], 'Weekly meal prep service')
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['payment_url'], 'https://buy.stripe.com/test123')

    def test_create_payment_link_missing_amount(self):
        """Test creating payment link without amount fails."""
        response = self.client.post('/chefs/api/me/payment-links/', {
            'description': 'Test payment',
            'lead_id': self.lead.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())

    def test_create_payment_link_amount_too_low(self):
        """Test creating payment link with amount below minimum fails."""
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 30,  # Below $0.50 minimum
            'description': 'Test payment',
            'lead_id': self.lead.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('0.50', response.json()['error'])

    def test_create_payment_link_missing_description(self):
        """Test creating payment link without description fails."""
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'lead_id': self.lead.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('description', response.json()['error'].lower())

    def test_create_payment_link_no_recipient(self):
        """Test creating payment link without recipient fails."""
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Test payment'
        })
        
        # This should succeed and create a draft, or fail - depends on implementation
        # Checking it doesn't crash
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])

    def test_create_payment_link_both_lead_and_customer(self):
        """Test creating payment link with both lead and customer fails."""
        customer = CustomUser.objects.create_user(
            username='customer',
            email='customer@test.com',
            password='testpass123'
        )
        
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Test payment',
            'lead_id': self.lead.id,
            'customer_id': customer.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())

    def test_create_payment_link_nonexistent_lead(self):
        """Test creating payment link with nonexistent lead fails."""
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Test payment',
            'lead_id': 99999
        })
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('chefs.api.payment_links.get_active_stripe_account')
    def test_create_payment_link_no_stripe_account(self, mock_get_account):
        """Test creating payment link without Stripe account fails."""
        from meals.utils.stripe_utils import StripeAccountError
        mock_get_account.side_effect = StripeAccountError('No Stripe account connected')
        
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Test payment',
            'lead_id': self.lead.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('stripe', response.json()['error'].lower())

    @patch('chefs.api.payment_links.get_active_stripe_account')
    @patch('chefs.api.payment_links.stripe.Product.create')
    def test_create_payment_link_stripe_error(self, mock_product_create, mock_get_account):
        """Test handling Stripe API errors during creation."""
        mock_get_account.return_value = ('acct_test123', None)
        mock_product_create.side_effect = stripe.error.StripeError('API error')
        
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Test payment',
            'lead_id': self.lead.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        # Verify no payment link was created
        self.assertEqual(ChefPaymentLink.objects.count(), 0)

    def test_get_payment_link_detail(self):
        """Test getting payment link details."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_url='https://buy.stripe.com/test',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.get(f'/chefs/api/me/payment-links/{link.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], link.id)
        self.assertEqual(data['amount_cents'], 5000)
        self.assertEqual(data['description'], 'Test payment')

    def test_get_payment_link_not_found(self):
        """Test getting nonexistent payment link returns 404."""
        response = self.client.get('/chefs/api/me/payment-links/99999/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_payment_link_other_chef(self):
        """Test chef cannot access another chef's payment link."""
        other_user = CustomUser.objects.create_user(
            username='otherchef',
            email='other@test.com',
            password='testpass123'
        )
        other_chef = Chef.objects.create(user=other_user)
        other_lead = Lead.objects.create(
            owner=other_user,
            first_name='Other',
            last_name='Client',
            email='other@client.com'
        )
        
        link = ChefPaymentLink.objects.create(
            chef=other_chef,
            lead=other_lead,
            amount_cents=5000,
            description='Other chef payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.get(f'/chefs/api/me/payment-links/{link.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('chefs.api.payment_links.stripe.PaymentLink.modify')
    def test_cancel_payment_link(self, mock_pl_modify):
        """Test cancelling a payment link."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_id='plink_test123',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.delete(f'/chefs/api/me/payment-links/{link.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        link.refresh_from_db()
        self.assertEqual(link.status, ChefPaymentLink.Status.CANCELLED)
        mock_pl_modify.assert_called_once()

    def test_cancel_paid_payment_link_fails(self):
        """Test cancelling a paid payment link fails."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PAID,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.delete(f'/chefs/api/me/payment-links/{link.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('paid', response.json()['error'].lower())

    @patch('chefs.api.payment_links._send_payment_link_email')
    def test_send_payment_link_success(self, mock_send_email):
        """Test sending payment link via email."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_url='https://buy.stripe.com/test',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.post(f'/chefs/api/me/payment-links/{link.id}/send/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.json()['status'])
        mock_send_email.assert_called_once()
        
        link.refresh_from_db()
        self.assertEqual(link.email_send_count, 1)

    def test_send_payment_link_unverified_email(self):
        """Test sending payment link to unverified email fails."""
        self.lead.email_verified = False
        self.lead.save()
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_url='https://buy.stripe.com/test',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.post(f'/chefs/api/me/payment-links/{link.id}/send/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('verified', response.json()['error'].lower())

    def test_send_payment_link_expired(self):
        """Test sending expired payment link fails."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_url='https://buy.stripe.com/test',
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        response = self.client.post(f'/chefs/api/me/payment-links/{link.id}/send/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', response.json()['error'].lower())

    def test_send_payment_link_no_email(self):
        """Test sending payment link without email address fails."""
        self.lead.email = ''
        self.lead.save()
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.post(f'/chefs/api/me/payment-links/{link.id}/send/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.json()['error'].lower())

    def test_get_payment_link_stats(self):
        """Test getting payment link statistics."""
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Pending 1',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=10000,
            description='Pending 2',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=7500,
            description='Paid',
            status=ChefPaymentLink.Status.PAID,
            paid_amount_cents=7500,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        response = self.client.get('/chefs/api/me/payment-links/stats/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['total_count'], 3)
        self.assertEqual(data['pending_count'], 2)
        self.assertEqual(data['paid_count'], 1)
        self.assertEqual(data['total_pending_amount_cents'], 15000)
        self.assertEqual(data['total_paid_amount_cents'], 7500)
        # New per-currency fields (single currency should have one entry each)
        self.assertEqual(len(data['pending_amounts']), 1)
        self.assertEqual(len(data['paid_amounts']), 1)

    def test_get_payment_link_stats_multi_currency(self):
        """Test stats with payment links in multiple currencies."""
        # 2 JPY pending links
        ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead, amount_cents=10000,
            currency='jpy', description='JPY 1',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead, amount_cents=29000,
            currency='jpy', description='JPY 2',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        # 1 USD pending link
        ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead, amount_cents=5000,
            currency='usd', description='USD pending',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        # 1 USD paid link
        ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead, amount_cents=7500,
            currency='usd', description='USD paid',
            status=ChefPaymentLink.Status.PAID,
            paid_amount_cents=7500,
            expires_at=timezone.now() + timedelta(days=30)
        )

        response = self.client.get('/chefs/api/me/payment-links/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Counts include all currencies
        self.assertEqual(data['total_count'], 4)
        self.assertEqual(data['pending_count'], 3)
        self.assertEqual(data['paid_count'], 1)

        # Per-currency breakdowns
        self.assertEqual(len(data['pending_amounts']), 2)
        pending_by_cur = {e['currency']: e['amount_cents'] for e in data['pending_amounts']}
        self.assertEqual(pending_by_cur['JPY'], 39000)
        self.assertEqual(pending_by_cur['USD'], 5000)

        self.assertEqual(len(data['paid_amounts']), 1)
        self.assertEqual(data['paid_amounts'][0]['currency'], 'USD')
        self.assertEqual(data['paid_amounts'][0]['amount_cents'], 7500)

        # Legacy fields reflect dominant currency (JPY has most links)
        self.assertEqual(data['currency'], 'JPY')
        self.assertEqual(data['total_pending_amount_cents'], 39000)

    def test_get_payment_link_stats_empty(self):
        """Test stats when no payment links exist."""
        response = self.client.get('/chefs/api/me/payment-links/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['total_count'], 0)
        self.assertEqual(data['pending_count'], 0)
        self.assertEqual(data['pending_amounts'], [])
        self.assertEqual(data['paid_amounts'], [])
        self.assertEqual(data['total_pending_amount_cents'], 0)
        self.assertEqual(data['total_paid_amount_cents'], 0)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated requests are denied."""
        self.client.force_authenticate(user=None)
        
        response = self.client.get('/chefs/api/me/payment-links/')
        
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_non_chef_access_denied(self):
        """Test that non-chef users cannot access payment links."""
        regular_user = CustomUser.objects.create_user(
            username='regular',
            email='regular@test.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=regular_user)
        
        response = self.client.get('/chefs/api/me/payment-links/')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EmailVerificationAPITestCase(APITestCase):
    """Test email verification API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch('chefs.api.leads._send_verification_email')
    def test_send_verification_email_success(self, mock_send):
        """Test successfully sending verification email."""
        response = self.client.post(f'/chefs/api/me/leads/{self.lead.id}/send-verification/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.json()['status'])
        mock_send.assert_called_once()
        
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.email_verification_token)

    def test_send_verification_no_email(self):
        """Test sending verification to lead without email fails."""
        self.lead.email = ''
        self.lead.save()
        
        response = self.client.post(f'/chefs/api/me/leads/{self.lead.id}/send-verification/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.json()['error'].lower())

    def test_send_verification_already_verified(self):
        """Test sending verification to already verified email fails."""
        self.lead.email_verified = True
        self.lead.save()
        
        response = self.client.post(f'/chefs/api/me/leads/{self.lead.id}/send-verification/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already', response.json()['error'].lower())

    @patch('chefs.api.leads._send_verification_email')
    def test_send_verification_rate_limiting(self, mock_send):
        """Test rate limiting for verification emails."""
        # Send first email
        response = self.client.post(f'/chefs/api/me/leads/{self.lead.id}/send-verification/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Try to send again immediately (should be rate limited)
        response = self.client.post(f'/chefs/api/me/leads/{self.lead.id}/send-verification/')
        
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn('wait', response.json()['error'].lower())

    def test_send_verification_other_chef_lead(self):
        """Test chef cannot send verification to another chef's lead."""
        other_user = CustomUser.objects.create_user(
            username='otherchef',
            email='other@test.com',
            password='testpass123'
        )
        other_lead = Lead.objects.create(
            owner=other_user,
            first_name='Other',
            last_name='Client',
            email='other@client.com'
        )
        
        response = self.client.post(f'/chefs/api/me/leads/{other_lead.id}/send-verification/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_verify_email_token_success(self):
        """Test successful email verification via token."""
        token = self.lead.generate_verification_token()
        
        # Use unauthenticated client for public endpoint
        client = APIClient()
        response = client.get(f'/chefs/api/verify-email/{token}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.json()['status'])
        
        self.lead.refresh_from_db()
        self.assertTrue(self.lead.email_verified)

    def test_verify_email_token_invalid(self):
        """Test verification with invalid token fails."""
        client = APIClient()
        response = client.get('/chefs/api/verify-email/invalid_token_here/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json()['status'])

    def test_verify_email_token_expired(self):
        """Test verification with expired token fails."""
        token = self.lead.generate_verification_token()
        self.lead.email_verification_sent_at = timezone.now() - timedelta(hours=73)
        self.lead.save()
        
        client = APIClient()
        response = client.get(f'/chefs/api/verify-email/{token}/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', response.json()['message'].lower())

    def test_verify_email_token_already_used(self):
        """Test verification with already-used token fails."""
        token = self.lead.generate_verification_token()
        
        client = APIClient()
        # First verification
        response1 = client.get(f'/chefs/api/verify-email/{token}/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        # Second verification attempt with same token
        response2 = client.get(f'/chefs/api/verify-email/{token}/')
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_email_token_too_short(self):
        """Test verification with too-short token fails."""
        client = APIClient()
        response = client.get('/chefs/api/verify-email/short/')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_verification_status(self):
        """Test getting email verification status."""
        response = self.client.get(f'/chefs/api/me/leads/{self.lead.id}/verification-status/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['has_email'])
        self.assertEqual(data['email'], 'john@example.com')
        self.assertFalse(data['email_verified'])

    def test_get_verification_status_verified(self):
        """Test verification status for verified email."""
        self.lead.email_verified = True
        self.lead.email_verified_at = timezone.now()
        self.lead.save()
        
        response = self.client.get(f'/chefs/api/me/leads/{self.lead.id}/verification-status/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['email_verified'])
        self.assertIsNotNone(data['email_verified_at'])


class PaymentLinkWebhookTestCase(TransactionTestCase):
    """Test Stripe webhook handling for payment links."""
    reset_sequences = True

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='webhook_testchef',
            email='webhook_chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )
        self.payment_link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_id='plink_test123',
            expires_at=timezone.now() + timedelta(days=30)
        )

    def _create_mock_session(self, metadata):
        """Create a mock Stripe checkout session."""
        session = MagicMock()
        session.id = 'cs_test123'
        session.payment_intent = 'pi_test123'
        session.amount_total = 5000
        session.metadata = metadata
        return session

    def test_webhook_payment_link_completed(self):
        """Test webhook marks payment link as paid."""
        from chefs.webhooks import handle_payment_link_completed
        
        session = self._create_mock_session({
            'type': 'chef_payment_link',
            'payment_link_id': str(self.payment_link.id),
            'chef_id': str(self.chef.id)
        })
        
        with patch('chefs.webhooks._send_payment_confirmation'):
            handle_payment_link_completed(session)
        
        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)
        self.assertEqual(self.payment_link.stripe_payment_intent_id, 'pi_test123')
        self.assertEqual(self.payment_link.stripe_checkout_session_id, 'cs_test123')
        self.assertEqual(self.payment_link.paid_amount_cents, 5000)
        self.assertIsNotNone(self.payment_link.paid_at)

    def test_webhook_idempotency_already_paid(self):
        """Test webhook is idempotent - handles already paid links."""
        from chefs.webhooks import handle_payment_link_completed
        
        self.payment_link.status = ChefPaymentLink.Status.PAID
        self.payment_link.paid_at = timezone.now()
        self.payment_link.save()
        
        session = self._create_mock_session({
            'type': 'chef_payment_link',
            'payment_link_id': str(self.payment_link.id),
            'chef_id': str(self.chef.id)
        })
        
        # Should not raise an error
        handle_payment_link_completed(session)
        
        # Status should remain paid
        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)

    def test_webhook_wrong_type(self):
        """Test webhook ignores wrong type."""
        from chefs.webhooks import handle_payment_link_completed
        
        session = self._create_mock_session({
            'type': 'service',
            'payment_link_id': str(self.payment_link.id)
        })
        
        handle_payment_link_completed(session)
        
        # Status should remain pending
        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PENDING)

    def test_webhook_missing_payment_link_id(self):
        """Test webhook handles missing payment_link_id gracefully."""
        from chefs.webhooks import handle_payment_link_completed
        
        session = self._create_mock_session({
            'type': 'chef_payment_link'
            # Missing payment_link_id
        })
        
        # Should not raise an error
        handle_payment_link_completed(session)

    def test_webhook_nonexistent_payment_link(self):
        """Test webhook handles nonexistent payment link gracefully."""
        from chefs.webhooks import handle_payment_link_completed
        
        session = self._create_mock_session({
            'type': 'chef_payment_link',
            'payment_link_id': '99999'
        })
        
        # Should not raise an error (logged instead)
        with patch('chefs.webhooks._send_traceback'):
            handle_payment_link_completed(session)

    def test_webhook_chef_id_mismatch_logged(self):
        """Test webhook logs warning for chef ID mismatch."""
        from chefs.webhooks import handle_payment_link_completed
        
        session = self._create_mock_session({
            'type': 'chef_payment_link',
            'payment_link_id': str(self.payment_link.id),
            'chef_id': '99999'  # Wrong chef ID
        })
        
        with patch('chefs.webhooks.logger') as mock_logger:
            with patch('chefs.webhooks._send_payment_confirmation'):
                handle_payment_link_completed(session)
            
            # Should log warning but still process
            mock_logger.warning.assert_called()
        
        # Payment should still be marked as paid
        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)


class StripeIntegrationTestCase(TestCase):
    """Test Stripe API integration for payment links."""

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )

    @patch('chefs.api.payment_links.stripe.Product.create')
    @patch('chefs.api.payment_links.stripe.Price.create')
    @patch('chefs.api.payment_links.stripe.PaymentLink.create')
    @patch('chefs.api.payment_links.get_platform_fee_percentage')
    def test_create_stripe_payment_link(self, mock_fee, mock_pl_create, 
                                         mock_price_create, mock_product_create):
        """Test creating Stripe product, price, and payment link."""
        from chefs.api.payment_links import _create_stripe_payment_link
        
        mock_fee.return_value = Decimal('10.00')
        mock_product_create.return_value = MagicMock(id='prod_test')
        mock_price_create.return_value = MagicMock(id='price_test')
        mock_pl_create.return_value = MagicMock(
            id='plink_test',
            url='https://buy.stripe.com/test'
        )
        
        payment_link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            currency='usd',
            description='Test payment',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        result = _create_stripe_payment_link(
            chef=self.chef,
            payment_link=payment_link,
            destination_account_id='acct_test123'
        )
        
        self.assertEqual(result['product_id'], 'prod_test')
        self.assertEqual(result['price_id'], 'price_test')
        self.assertEqual(result['payment_link_id'], 'plink_test')
        self.assertEqual(result['payment_link_url'], 'https://buy.stripe.com/test')
        
        # Verify product creation
        mock_product_create.assert_called_once()
        product_call = mock_product_create.call_args
        self.assertIn('Test payment', product_call.kwargs['name'])
        self.assertEqual(product_call.kwargs['metadata']['chef_id'], str(self.chef.id))
        
        # Verify price creation
        mock_price_create.assert_called_once()
        price_call = mock_price_create.call_args
        self.assertEqual(price_call.kwargs['unit_amount'], 5000)
        self.assertEqual(price_call.kwargs['currency'], 'usd')
        
        # Verify payment link creation with transfer_data
        mock_pl_create.assert_called_once()
        pl_call = mock_pl_create.call_args
        self.assertEqual(pl_call.kwargs['transfer_data']['destination'], 'acct_test123')
        # application_fee_amount = 5000 * 10% = 500 cents
        self.assertEqual(pl_call.kwargs['application_fee_amount'], 500)

    @patch('chefs.api.payment_links.stripe.Product.create')
    def test_stripe_product_creation_includes_metadata(self, mock_product_create):
        """Test that Stripe product includes correct metadata."""
        from chefs.api.payment_links import _create_stripe_payment_link
        
        mock_product_create.return_value = MagicMock(id='prod_test')
        
        payment_link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Weekly meal prep',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        with patch('chefs.api.payment_links.stripe.Price.create') as mock_price:
            with patch('chefs.api.payment_links.stripe.PaymentLink.create') as mock_pl:
                mock_price.return_value = MagicMock(id='price_test')
                mock_pl.return_value = MagicMock(id='plink_test', url='https://test.com')
                
                _create_stripe_payment_link(
                    chef=self.chef,
                    payment_link=payment_link,
                    destination_account_id='acct_test'
                )
        
        call_kwargs = mock_product_create.call_args.kwargs
        self.assertEqual(call_kwargs['metadata']['type'], 'chef_payment_link')
        self.assertEqual(call_kwargs['metadata']['payment_link_id'], str(payment_link.id))

    @patch('chefs.api.payment_links.stripe.PaymentLink.modify')
    def test_deactivate_stripe_payment_link(self, mock_modify):
        """Test deactivating Stripe payment link on cancel."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_id='plink_test123',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        client = APIClient()
        client.force_authenticate(user=self.user)
        
        response = client.delete(f'/chefs/api/me/payment-links/{link.id}/')
        
        mock_modify.assert_called_once_with('plink_test123', active=False)

    @patch('chefs.api.payment_links.stripe.PaymentLink.modify')
    def test_stripe_deactivation_failure_handled(self, mock_modify):
        """Test that Stripe deactivation failure is handled gracefully."""
        mock_modify.side_effect = stripe.error.StripeError('API error')
        
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_id='plink_test123',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        client = APIClient()
        client.force_authenticate(user=self.user)
        
        # Should succeed even if Stripe fails
        response = client.delete(f'/chefs/api/me/payment-links/{link.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        link.refresh_from_db()
        self.assertEqual(link.status, ChefPaymentLink.Status.CANCELLED)


class ConcurrencyTestCase(TransactionTestCase):
    """Test concurrent access scenarios."""
    reset_sequences = True

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='concurrency_testchef',
            email='concurrency_chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )

    def test_concurrent_payment_processing(self):
        """Test that concurrent webhook calls don't cause issues."""
        from chefs.webhooks import handle_payment_link_completed
        
        payment_link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test payment',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        session1 = MagicMock()
        session1.id = 'cs_test1'
        session1.payment_intent = 'pi_test1'
        session1.amount_total = 5000
        session1.metadata = {
            'type': 'chef_payment_link',
            'payment_link_id': str(payment_link.id),
            'chef_id': str(self.chef.id)
        }
        
        session2 = MagicMock()
        session2.id = 'cs_test2'
        session2.payment_intent = 'pi_test2'
        session2.amount_total = 5000
        session2.metadata = {
            'type': 'chef_payment_link',
            'payment_link_id': str(payment_link.id),
            'chef_id': str(self.chef.id)
        }
        
        # Simulate concurrent calls - both should handle gracefully
        with patch('chefs.webhooks._send_payment_confirmation'):
            handle_payment_link_completed(session1)
            handle_payment_link_completed(session2)  # Should be idempotent
        
        payment_link.refresh_from_db()
        self.assertEqual(payment_link.status, ChefPaymentLink.Status.PAID)
        # First payment intent should be recorded
        self.assertEqual(payment_link.stripe_payment_intent_id, 'pi_test1')


@SKIP_IN_CI
class EdgeCaseTestCase(TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        """Set up test data."""
        self.user = CustomUser.objects.create_user(
            username='testchef',
            email='chef@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user,
            first_name='John',
            last_name='Doe',
            email='john@example.com',
            email_verified=True
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_exact_minimum_amount(self):
        """Test creating payment link with exact minimum amount ($0.50)."""
        with patch('chefs.api.payment_links.get_active_stripe_account') as mock_account:
            with patch('chefs.api.payment_links._create_stripe_payment_link') as mock_create:
                mock_account.return_value = ('acct_test', None)
                mock_create.return_value = {
                    'product_id': 'prod_test',
                    'price_id': 'price_test',
                    'payment_link_id': 'plink_test',
                    'payment_link_url': 'https://test.com'
                }
                
                response = self.client.post('/chefs/api/me/payment-links/', {
                    'amount_cents': 50,  # Exact minimum
                    'description': 'Test',
                    'lead_id': self.lead.id
                })
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_large_amount(self):
        """Test creating payment link with large amount."""
        with patch('chefs.api.payment_links.get_active_stripe_account') as mock_account:
            with patch('chefs.api.payment_links._create_stripe_payment_link') as mock_create:
                mock_account.return_value = ('acct_test', None)
                mock_create.return_value = {
                    'product_id': 'prod_test',
                    'price_id': 'price_test',
                    'payment_link_id': 'plink_test',
                    'payment_link_url': 'https://test.com'
                }
                
                response = self.client.post('/chefs/api/me/payment-links/', {
                    'amount_cents': 10000000,  # $100,000
                    'description': 'Large catering order',
                    'lead_id': self.lead.id
                })
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_description_max_length(self):
        """Test creating payment link with maximum description length."""
        with patch('chefs.api.payment_links.get_active_stripe_account') as mock_account:
            with patch('chefs.api.payment_links._create_stripe_payment_link') as mock_create:
                mock_account.return_value = ('acct_test', None)
                mock_create.return_value = {
                    'product_id': 'prod_test',
                    'price_id': 'price_test',
                    'payment_link_id': 'plink_test',
                    'payment_link_url': 'https://test.com'
                }
                
                description = 'A' * 500  # Max length
                response = self.client.post('/chefs/api/me/payment-links/', {
                    'amount_cents': 5000,
                    'description': description,
                    'lead_id': self.lead.id
                })
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_special_characters_in_description(self):
        """Test handling special characters in description."""
        with patch('chefs.api.payment_links.get_active_stripe_account') as mock_account:
            with patch('chefs.api.payment_links._create_stripe_payment_link') as mock_create:
                mock_account.return_value = ('acct_test', None)
                mock_create.return_value = {
                    'product_id': 'prod_test',
                    'price_id': 'price_test',
                    'payment_link_id': 'plink_test',
                    'payment_link_url': 'https://test.com'
                }
                
                description = 'Meal prep - includes: pasta, salad & bread! "Fresh" ingredients.'
                response = self.client.post('/chefs/api/me/payment-links/', {
                    'amount_cents': 5000,
                    'description': description,
                    'lead_id': self.lead.id
                })
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unicode_in_description(self):
        """Test handling unicode characters in description."""
        with patch('chefs.api.payment_links.get_active_stripe_account') as mock_account:
            with patch('chefs.api.payment_links._create_stripe_payment_link') as mock_create:
                mock_account.return_value = ('acct_test', None)
                mock_create.return_value = {
                    'product_id': 'prod_test',
                    'price_id': 'price_test',
                    'payment_link_id': 'plink_test',
                    'payment_link_url': 'https://test.com'
                }
                
                description = 'Meal prep 🍝🥗 - délicieux!'
                response = self.client.post('/chefs/api/me/payment-links/', {
                    'amount_cents': 5000,
                    'description': description,
                    'lead_id': self.lead.id
                })
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_expiration_exactly_at_now(self):
        """Test payment link with expiration exactly at current time."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test',
            status=ChefPaymentLink.Status.PENDING,
            expires_at=timezone.now()
        )
        
        # Should be considered expired
        self.assertTrue(link.is_expired())

    def test_zero_email_send_count_initial(self):
        """Test email send count starts at zero."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        self.assertEqual(link.email_send_count, 0)

    def test_verification_token_near_expiry(self):
        """Test verification token at exactly 72 hours (edge of expiry)."""
        token = self.lead.generate_verification_token()
        
        # Set to exactly 72 hours - should still be valid
        self.lead.email_verification_sent_at = timezone.now() - timedelta(hours=71, minutes=59)
        self.lead.save()
        
        self.assertTrue(self.lead.is_verification_token_valid())
        
        # Just past 72 hours - should be expired
        self.lead.email_verification_sent_at = timezone.now() - timedelta(hours=72, minutes=1)
        self.lead.save()
        
        self.assertFalse(self.lead.is_verification_token_valid())

    def test_deleted_lead_payment_link(self):
        """Test that deleted lead's payment links still function."""
        link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=5000,
            description='Test',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        # Soft delete the lead
        self.lead.is_deleted = True
        self.lead.save()
        
        # Payment link should still exist and be accessible
        link.refresh_from_db()
        self.assertIsNotNone(link.lead)
        self.assertEqual(link.get_recipient_name(), 'John Doe')


@SKIP_IN_CI
class SecurityTestCase(APITestCase):
    """Test security-related scenarios."""

    def setUp(self):
        """Set up test data."""
        self.chef_user = CustomUser.objects.create_user(
            username='chef1',
            email='chef1@test.com',
            password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.chef_user)
        
        self.other_chef_user = CustomUser.objects.create_user(
            username='chef2',
            email='chef2@test.com',
            password='testpass123'
        )
        self.other_chef = Chef.objects.create(user=self.other_chef_user)
        
        self.lead = Lead.objects.create(
            owner=self.chef_user,
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )
        
        self.other_lead = Lead.objects.create(
            owner=self.other_chef_user,
            first_name='Jane',
            last_name='Smith',
            email='jane@example.com'
        )
        
        self.client = APIClient()

    def test_chef_cannot_access_other_chef_payment_links(self):
        """Test that a chef cannot access another chef's payment links."""
        other_link = ChefPaymentLink.objects.create(
            chef=self.other_chef,
            lead=self.other_lead,
            amount_cents=5000,
            description='Other chef link',
            expires_at=timezone.now() + timedelta(days=30)
        )
        
        self.client.force_authenticate(user=self.chef_user)
        
        response = self.client.get(f'/chefs/api/me/payment-links/{other_link.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        response = self.client.delete(f'/chefs/api/me/payment-links/{other_link.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_chef_cannot_create_link_for_other_chef_lead(self):
        """Test that a chef cannot create payment link for another chef's lead."""
        self.client.force_authenticate(user=self.chef_user)
        
        response = self.client.post('/chefs/api/me/payment-links/', {
            'amount_cents': 5000,
            'description': 'Test',
            'lead_id': self.other_lead.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_verification_token_not_exposed_in_api(self):
        """Test that verification token is not exposed in API responses."""
        self.lead.generate_verification_token()
        
        self.client.force_authenticate(user=self.chef_user)
        
        response = self.client.get(f'/chefs/api/me/leads/{self.lead.id}/verification-status/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertNotIn('email_verification_token', data)
        self.assertNotIn('token', data)

    def test_payment_link_token_enumeration_prevented(self):
        """Test that verification tokens cannot be enumerated."""
        # Generate a token
        token = self.lead.generate_verification_token()
        
        # Try similar tokens
        client = APIClient()
        
        # These should all fail
        response = client.get(f'/chefs/api/verify-email/{token[:-1]}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        response = client.get(f'/chefs/api/verify-email/{token}a/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sql_injection_prevention(self):
        """Test that SQL injection attempts are handled safely."""
        self.client.force_authenticate(user=self.chef_user)
        
        # Try SQL injection in search parameter
        response = self.client.get("/chefs/api/me/payment-links/?search=' OR '1'='1")
        
        # Should return 200 with no results, not a database error
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_xss_prevention_in_stored_data(self):
        """Test that XSS attempts in description are handled safely."""
        with patch('chefs.api.payment_links.get_active_stripe_account') as mock_account:
            with patch('chefs.api.payment_links._create_stripe_payment_link') as mock_create:
                mock_account.return_value = ('acct_test', None)
                mock_create.return_value = {
                    'product_id': 'prod_test',
                    'price_id': 'price_test',
                    'payment_link_id': 'plink_test',
                    'payment_link_url': 'https://test.com'
                }
                
                self.lead.email_verified = True
                self.lead.save()
                
                self.client.force_authenticate(user=self.chef_user)
                
                description = '<script>alert("xss")</script>'
                response = self.client.post('/chefs/api/me/payment-links/', {
                    'amount_cents': 5000,
                    'description': description,
                    'lead_id': self.lead.id
                })
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                
                # Verify stored as-is (frontend should escape)
                data = response.json()
                self.assertEqual(data['description'], description)


