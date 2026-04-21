"""
Test suite for Stripe settlement/balance transaction integration.

Tests cover:
- Settlement fields on ChefPaymentLink model
- Webhook fetching balance transaction data from Stripe
- Backfill management command for existing paid links
- Analytics using settled USD amounts for unified charting
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch, call

import pytest
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from chefs.models import Chef, ChefPaymentLink
from crm.models import Lead
from custom_auth.models import CustomUser


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class SettlementFieldsModelTest(TestCase):
    """Test the new settlement fields on ChefPaymentLink."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='settlement_chef', email='s_chef@test.com', password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user, first_name='Test', last_name='Client',
            email='client@test.com', status='new'
        )
        self.payment_link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=500000,  # ¥5,000 in JPY (zero-decimal)
            currency='jpy',
            description='Japanese cooking class',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_id='plink_test',
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_settlement_fields_default_to_null(self):
        """New settlement fields should default to null/None."""
        self.assertIsNone(self.payment_link.settled_amount_cents)
        self.assertIsNone(self.payment_link.settled_currency)
        self.assertIsNone(self.payment_link.exchange_rate)

    def test_settlement_fields_can_be_set(self):
        """Settlement fields can be populated and persisted."""
        self.payment_link.settled_amount_cents = 3350  # $33.50 USD
        self.payment_link.settled_currency = 'usd'
        self.payment_link.exchange_rate = 0.0067
        self.payment_link.save(update_fields=[
            'settled_amount_cents', 'settled_currency', 'exchange_rate',
        ])

        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.settled_amount_cents, 3350)
        self.assertEqual(self.payment_link.settled_currency, 'usd')
        self.assertAlmostEqual(float(self.payment_link.exchange_rate), 0.0067)

    def test_usd_payment_no_exchange_rate(self):
        """USD payments have no exchange rate (null)."""
        usd_link = ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead,
            amount_cents=5000, currency='usd',
            description='USD service',
            status=ChefPaymentLink.Status.PAID,
            stripe_payment_link_id='plink_usd',
            expires_at=timezone.now() + timedelta(days=30),
            settled_amount_cents=5000,
            settled_currency='usd',
            exchange_rate=None,
        )
        usd_link.refresh_from_db()
        self.assertEqual(usd_link.settled_amount_cents, 5000)
        self.assertIsNone(usd_link.exchange_rate)

    def test_mark_as_paid_with_settlement(self):
        """mark_as_paid should accept and store settlement data."""
        self.payment_link.mark_as_paid(
            payment_intent_id='pi_test',
            amount_cents=500000,
            settled_amount_cents=3350,
            settled_currency='usd',
            exchange_rate=0.0067,
        )

        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)
        self.assertEqual(self.payment_link.settled_amount_cents, 3350)
        self.assertEqual(self.payment_link.settled_currency, 'usd')
        self.assertAlmostEqual(float(self.payment_link.exchange_rate), 0.0067)

    def test_mark_as_paid_without_settlement_still_works(self):
        """mark_as_paid without settlement args should still work (backward compat)."""
        self.payment_link.mark_as_paid(
            payment_intent_id='pi_test',
            amount_cents=500000,
        )

        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)
        self.assertIsNone(self.payment_link.settled_amount_cents)


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------

class SettlementWebhookTest(TransactionTestCase):
    """Test that the webhook fetches balance transaction and stores settlement data."""
    reset_sequences = True

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='wh_settlement_chef', email='wh_s@test.com', password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user, first_name='Emiri', last_name='Test',
            email='emiri@test.com', status='new'
        )
        self.payment_link = ChefPaymentLink.objects.create(
            chef=self.chef,
            lead=self.lead,
            amount_cents=3900000,  # ¥39,000
            currency='jpy',
            description='Meal prep service',
            status=ChefPaymentLink.Status.PENDING,
            stripe_payment_link_id='plink_jpy_test',
            expires_at=timezone.now() + timedelta(days=30),
        )

    def _create_mock_session(self):
        session = MagicMock()
        session.id = 'cs_settlement_test'
        session.payment_intent = 'pi_settlement_test'
        session.amount_total = 3900000
        session.metadata = {
            'type': 'chef_payment_link',
            'payment_link_id': str(self.payment_link.id),
            'chef_id': str(self.chef.id),
        }
        return session

    def _create_mock_balance_transaction(self, amount=26000, currency='usd', exchange_rate=0.006667):
        """Create a mock Stripe balance transaction (amount in settlement currency cents)."""
        bt = MagicMock()
        bt.id = 'txn_test123'
        bt.amount = amount
        bt.currency = currency
        bt.exchange_rate = exchange_rate
        bt.fee = 780
        bt.net = amount - 780
        return bt

    @patch('chefs.webhooks._send_payment_confirmation')
    @patch('chefs.webhooks.stripe.PaymentIntent.retrieve')
    def test_webhook_stores_settlement_data_for_jpy(self, mock_pi_retrieve, mock_notify):
        """Webhook should fetch balance transaction and store USD settlement amount."""
        from chefs.webhooks import handle_payment_link_completed

        mock_charge = MagicMock()
        mock_charge.balance_transaction = self._create_mock_balance_transaction(
            amount=26000, currency='usd', exchange_rate=0.006667
        )

        mock_pi = MagicMock()
        mock_pi.latest_charge = mock_charge
        mock_pi_retrieve.return_value = mock_pi

        session = self._create_mock_session()
        handle_payment_link_completed(session)

        # Verify Stripe API was called with expand
        mock_pi_retrieve.assert_called_once_with(
            'pi_settlement_test',
            expand=['latest_charge.balance_transaction'],
        )

        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)
        self.assertEqual(self.payment_link.settled_amount_cents, 26000)
        self.assertEqual(self.payment_link.settled_currency, 'usd')
        self.assertAlmostEqual(float(self.payment_link.exchange_rate), 0.006667)

    @patch('chefs.webhooks._send_payment_confirmation')
    @patch('chefs.webhooks.stripe.PaymentIntent.retrieve')
    def test_webhook_usd_payment_no_exchange_rate(self, mock_pi_retrieve, mock_notify):
        """USD payments should store settlement with null exchange rate."""
        from chefs.webhooks import handle_payment_link_completed

        # Make it a USD payment link
        self.payment_link.currency = 'usd'
        self.payment_link.amount_cents = 5000
        self.payment_link.save()

        mock_charge = MagicMock()
        mock_charge.balance_transaction = self._create_mock_balance_transaction(
            amount=5000, currency='usd', exchange_rate=None
        )
        mock_pi = MagicMock()
        mock_pi.latest_charge = mock_charge
        mock_pi_retrieve.return_value = mock_pi

        session = self._create_mock_session()
        session.amount_total = 5000
        handle_payment_link_completed(session)

        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.settled_amount_cents, 5000)
        self.assertEqual(self.payment_link.settled_currency, 'usd')
        self.assertIsNone(self.payment_link.exchange_rate)

    @patch('chefs.webhooks._send_payment_confirmation')
    @patch('chefs.webhooks.stripe.PaymentIntent.retrieve')
    def test_webhook_stripe_api_failure_still_marks_paid(self, mock_pi_retrieve, mock_notify):
        """If balance transaction fetch fails, payment is still marked paid (settlement stays null)."""
        from chefs.webhooks import handle_payment_link_completed

        mock_pi_retrieve.side_effect = Exception("Stripe API down")

        session = self._create_mock_session()
        handle_payment_link_completed(session)

        self.payment_link.refresh_from_db()
        # Payment is still marked paid — settlement fetch is best-effort
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)
        self.assertIsNotNone(self.payment_link.paid_at)
        # Settlement fields remain null
        self.assertIsNone(self.payment_link.settled_amount_cents)

    @patch('chefs.webhooks._send_payment_confirmation')
    @patch('chefs.webhooks.stripe.PaymentIntent.retrieve')
    def test_webhook_no_payment_intent_skips_settlement(self, mock_pi_retrieve, mock_notify):
        """If session has no payment_intent, skip settlement fetch."""
        from chefs.webhooks import handle_payment_link_completed

        session = self._create_mock_session()
        session.payment_intent = None

        handle_payment_link_completed(session)

        mock_pi_retrieve.assert_not_called()

        self.payment_link.refresh_from_db()
        self.assertEqual(self.payment_link.status, ChefPaymentLink.Status.PAID)
        self.assertIsNone(self.payment_link.settled_amount_cents)


# ---------------------------------------------------------------------------
# Backfill management command tests
# ---------------------------------------------------------------------------

class BackfillSettlementCommandTest(TransactionTestCase):
    """Test the backfill_settlement_amounts management command."""
    reset_sequences = True

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='backfill_chef', email='bf@test.com', password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user, first_name='BF', last_name='Lead',
            email='bf_lead@test.com', status='new'
        )

    def _create_paid_link(self, currency='jpy', amount_cents=3900000, pi_id='pi_bf1',
                          settled_amount_cents=None):
        return ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead,
            amount_cents=amount_cents, currency=currency,
            description=f'Backfill test {pi_id}',
            status=ChefPaymentLink.Status.PAID,
            stripe_payment_link_id=f'plink_{pi_id}',
            stripe_payment_intent_id=pi_id,
            paid_at=timezone.now() - timedelta(days=5),
            paid_amount_cents=amount_cents,
            settled_amount_cents=settled_amount_cents,
            expires_at=timezone.now() + timedelta(days=30),
        )

    @patch('chefs.management.commands.backfill_settlement_amounts.stripe.PaymentIntent.retrieve')
    def test_backfills_missing_settlement_data(self, mock_pi_retrieve):
        """Command should fetch and store settlement for paid links missing it."""
        from django.core.management import call_command

        link = self._create_paid_link(pi_id='pi_backfill1')

        mock_bt = MagicMock()
        mock_bt.amount = 26000
        mock_bt.currency = 'usd'
        mock_bt.exchange_rate = 0.006667
        mock_charge = MagicMock()
        mock_charge.balance_transaction = mock_bt
        mock_pi = MagicMock()
        mock_pi.latest_charge = mock_charge
        mock_pi_retrieve.return_value = mock_pi

        out = StringIO()
        call_command('backfill_settlement_amounts', stdout=out)

        link.refresh_from_db()
        self.assertEqual(link.settled_amount_cents, 26000)
        self.assertEqual(link.settled_currency, 'usd')
        self.assertAlmostEqual(float(link.exchange_rate), 0.006667)

        output = out.getvalue()
        self.assertIn('1', output)  # processed count

    @patch('chefs.management.commands.backfill_settlement_amounts.stripe.PaymentIntent.retrieve')
    def test_skips_already_settled_links(self, mock_pi_retrieve):
        """Command should skip payment links that already have settlement data."""
        from django.core.management import call_command

        self._create_paid_link(pi_id='pi_already', settled_amount_cents=26000)

        out = StringIO()
        call_command('backfill_settlement_amounts', stdout=out)

        mock_pi_retrieve.assert_not_called()

    @patch('chefs.management.commands.backfill_settlement_amounts.stripe.PaymentIntent.retrieve')
    def test_skips_links_without_payment_intent(self, mock_pi_retrieve):
        """Command should skip links that have no stripe_payment_intent_id."""
        from django.core.management import call_command

        link = ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead,
            amount_cents=5000, currency='usd',
            description='No PI link',
            status=ChefPaymentLink.Status.PAID,
            stripe_payment_link_id='plink_nopi',
            stripe_payment_intent_id=None,  # No payment intent
            paid_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )

        out = StringIO()
        call_command('backfill_settlement_amounts', stdout=out)

        mock_pi_retrieve.assert_not_called()

    @patch('chefs.management.commands.backfill_settlement_amounts.stripe.PaymentIntent.retrieve')
    def test_handles_stripe_error_gracefully(self, mock_pi_retrieve):
        """Command should log errors and continue processing remaining links."""
        from django.core.management import call_command

        link_fail = self._create_paid_link(pi_id='pi_fail')
        link_ok = self._create_paid_link(pi_id='pi_ok')

        mock_bt = MagicMock()
        mock_bt.amount = 26000
        mock_bt.currency = 'usd'
        mock_bt.exchange_rate = 0.006667
        mock_charge = MagicMock()
        mock_charge.balance_transaction = mock_bt
        mock_pi_ok = MagicMock()
        mock_pi_ok.latest_charge = mock_charge

        def retrieve_side_effect(pi_id, **kwargs):
            if pi_id == 'pi_fail':
                raise Exception("Stripe error")
            return mock_pi_ok

        mock_pi_retrieve.side_effect = retrieve_side_effect

        out = StringIO()
        call_command('backfill_settlement_amounts', stdout=out)

        link_fail.refresh_from_db()
        link_ok.refresh_from_db()
        self.assertIsNone(link_fail.settled_amount_cents)  # Failed
        self.assertEqual(link_ok.settled_amount_cents, 26000)  # Succeeded

        output = out.getvalue()
        self.assertIn('error', output.lower())

    @patch('chefs.management.commands.backfill_settlement_amounts.stripe.PaymentIntent.retrieve')
    def test_dry_run_does_not_modify(self, mock_pi_retrieve):
        """--dry-run should report what would be updated without saving."""
        from django.core.management import call_command

        link = self._create_paid_link(pi_id='pi_dry')

        mock_bt = MagicMock()
        mock_bt.amount = 26000
        mock_bt.currency = 'usd'
        mock_bt.exchange_rate = 0.006667
        mock_charge = MagicMock()
        mock_charge.balance_transaction = mock_bt
        mock_pi = MagicMock()
        mock_pi.latest_charge = mock_charge
        mock_pi_retrieve.return_value = mock_pi

        out = StringIO()
        call_command('backfill_settlement_amounts', '--dry-run', stdout=out)

        link.refresh_from_db()
        self.assertIsNone(link.settled_amount_cents)  # Not modified

        output = out.getvalue()
        self.assertIn('dry run', output.lower())


# ---------------------------------------------------------------------------
# Analytics / client_insights tests
# ---------------------------------------------------------------------------

class SettlementAnalyticsTest(TestCase):
    """Test that analytics uses settled USD amounts for unified charting."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='analytics_chef', email='a_chef@test.com', password='testpass123'
        )
        self.chef = Chef.objects.create(user=self.user)
        self.lead = Lead.objects.create(
            owner=self.user, first_name='Analytics', last_name='Lead',
            email='a_lead@test.com', status='new'
        )

    def _create_paid_link(self, currency='jpy', amount_cents=3900000,
                          settled_amount_cents=None, settled_currency=None,
                          paid_at=None):
        return ChefPaymentLink.objects.create(
            chef=self.chef, lead=self.lead,
            amount_cents=amount_cents, currency=currency,
            description='Analytics test',
            status=ChefPaymentLink.Status.PAID,
            stripe_payment_link_id=f'plink_a_{ChefPaymentLink.objects.count()}',
            paid_at=paid_at or timezone.now(),
            paid_amount_cents=amount_cents,
            settled_amount_cents=settled_amount_cents,
            settled_currency=settled_currency,
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_revenue_uses_settled_usd_when_available(self):
        """When settled_amount_cents is set, revenue should use it as USD."""
        from chefs.services.client_insights import _sum_payment_links_by_currency

        self._create_paid_link(
            currency='jpy', amount_cents=3900000,
            settled_amount_cents=26000, settled_currency='usd',
            paid_at=timezone.now(),
        )

        result = _sum_payment_links_by_currency(self.chef, {'paid_at__gte': timezone.now() - timedelta(days=1)})

        # Should report as USD (from settlement), not JPY
        self.assertIn('usd', result)
        self.assertNotIn('jpy', result)
        self.assertEqual(result['usd'], Decimal('260'))  # 26000 cents = $260.00

    def test_revenue_falls_back_to_original_currency_when_no_settlement(self):
        """When no settlement data, fall back to original amount/currency."""
        from chefs.services.client_insights import _sum_payment_links_by_currency

        self._create_paid_link(
            currency='jpy', amount_cents=3900000,
            settled_amount_cents=None,
            paid_at=timezone.now(),
        )

        result = _sum_payment_links_by_currency(self.chef, {'paid_at__gte': timezone.now() - timedelta(days=1)})

        # Falls back to JPY since no settlement data
        self.assertIn('jpy', result)
        self.assertEqual(result['jpy'], Decimal('3900000'))  # JPY is zero-decimal

    def test_mixed_settled_and_unsettled_links(self):
        """Mix of settled and unsettled links should both contribute correctly."""
        from chefs.services.client_insights import _sum_payment_links_by_currency

        # Settled JPY link → shows as USD
        self._create_paid_link(
            currency='jpy', amount_cents=3900000,
            settled_amount_cents=26000, settled_currency='usd',
            paid_at=timezone.now(),
        )
        # Native USD link (no settlement needed)
        self._create_paid_link(
            currency='usd', amount_cents=5000,
            settled_amount_cents=5000, settled_currency='usd',
            paid_at=timezone.now(),
        )

        result = _sum_payment_links_by_currency(self.chef, {'paid_at__gte': timezone.now() - timedelta(days=1)})

        # Both should be in USD
        self.assertIn('usd', result)
        self.assertNotIn('jpy', result)
        # $260.00 + $50.00 = $310.00
        self.assertEqual(result['usd'], Decimal('310'))

    def test_time_series_uses_settled_amounts(self):
        """Revenue time series should use settled USD amounts for chart data."""
        from chefs.services.client_insights import get_analytics_time_series

        self._create_paid_link(
            currency='jpy', amount_cents=3900000,
            settled_amount_cents=26000, settled_currency='usd',
            paid_at=timezone.now(),
        )

        data = get_analytics_time_series(self.chef, metric='revenue', days=7)

        # Find today's data point
        today_str = timezone.now().strftime('%Y-%m-%d')
        today_point = next((p for p in data if p['date'] == today_str), None)
        self.assertIsNotNone(today_point)

        # Should show USD amount, not JPY
        by_currency = today_point.get('by_currency', {})
        self.assertIn('usd', by_currency)
        self.assertNotIn('jpy', by_currency)
        self.assertAlmostEqual(by_currency['usd'], 260.0)  # $260.00

    def test_dashboard_revenue_uses_settled_amounts(self):
        """Dashboard summary revenue should use settled amounts."""
        from chefs.services.client_insights import get_dashboard_summary

        self._create_paid_link(
            currency='jpy', amount_cents=3900000,
            settled_amount_cents=26000, settled_currency='usd',
            paid_at=timezone.now(),
        )

        summary = get_dashboard_summary(self.chef)
        today_revenue = summary['revenue']['today']

        self.assertIn('usd', today_revenue)
        self.assertNotIn('jpy', today_revenue)
        self.assertEqual(today_revenue['usd'], Decimal('260'))
