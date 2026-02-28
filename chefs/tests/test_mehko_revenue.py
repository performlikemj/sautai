"""Tests for MEHKO annual revenue cap (Phase 6)."""
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from chefs.models import Chef
from chef_services.models import ChefServiceOffering, ChefServicePriceTier, ChefServiceOrder
from chef_services.mehko_limits import get_annual_revenue, check_revenue_cap
from custom_auth.models import UserRole

User = get_user_model()


class AnnualRevenueTest(TestCase):
    """Test annual revenue calculation."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="revchef", email="revchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user, mehko_active=True)
        self.customer = User.objects.create_user(
            username="revcust", email="revcust@test.com", password="testpass123"
        )
        self.offering = ChefServiceOffering.objects.create(
            chef=self.chef, service_type="home_chef", title="Home Chef"
        )
        self.tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label="Standard",
            household_min=1,
            household_max=4,
            desired_unit_amount_cents=10000,  # $100
        )

    def _create_order(self, status='completed', date=None):
        return ChefServiceOrder.objects.create(
            chef=self.chef,
            customer=self.customer,
            offering=self.offering,
            tier=self.tier,
            household_size=2,
            service_date=date or timezone.now().date(),
            status=status,
        )

    def test_sums_completed_orders(self):
        self._create_order(status='completed')
        self._create_order(status='completed')
        self.assertEqual(get_annual_revenue(self.chef), Decimal('200.00'))

    def test_includes_confirmed(self):
        self._create_order(status='confirmed')
        self.assertEqual(get_annual_revenue(self.chef), Decimal('100.00'))

    def test_excludes_draft(self):
        self._create_order(status='draft')
        self.assertEqual(get_annual_revenue(self.chef), Decimal('0'))

    def test_excludes_old_orders(self):
        old_date = timezone.now().date() - timedelta(days=400)
        self._create_order(status='completed', date=old_date)
        self.assertEqual(get_annual_revenue(self.chef), Decimal('0'))

    def test_zero_when_no_orders(self):
        self.assertEqual(get_annual_revenue(self.chef), Decimal('0'))


class RevenueCapCheckTest(TestCase):
    """Test revenue cap enforcement logic."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="caprevchef", email="caprevchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user, mehko_active=True)
        self.customer = User.objects.create_user(
            username="caprevcust", email="caprevcust@test.com", password="testpass123"
        )
        self.offering = ChefServiceOffering.objects.create(
            chef=self.chef, service_type="home_chef", title="Home Chef"
        )

    def _create_tier_and_orders(self, amount_cents, count, status='completed'):
        tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label=f"Tier-{amount_cents}",
            household_min=1, household_max=4,
            desired_unit_amount_cents=amount_cents,
        )
        for _ in range(count):
            ChefServiceOrder.objects.create(
                chef=self.chef, customer=self.customer,
                offering=self.offering, tier=tier,
                household_size=2, service_date=timezone.now().date(),
                status=status,
            )
        return tier

    def test_under_cap(self):
        self._create_tier_and_orders(100_00, 10)  # $1000
        result = check_revenue_cap(self.chef)
        self.assertTrue(result['under_cap'])
        self.assertEqual(result['current_revenue'], Decimal('1000'))

    def test_at_cap(self):
        # 1000 orders × $100 = $100,000
        self._create_tier_and_orders(100_00, 1000)
        result = check_revenue_cap(self.chef, order_amount_cents=100_00)
        self.assertFalse(result['under_cap'])

    def test_ignores_non_mehko(self):
        self.chef.mehko_active = False
        self.chef.save()
        result = check_revenue_cap(self.chef)
        self.assertTrue(result['under_cap'])
        self.assertFalse(result['enforced'])

    def test_proposed_order_would_exceed(self):
        # $99,950 existing
        self._create_tier_and_orders(9995_00, 10)
        # Trying to add $100 more → $100,050 > cap
        result = check_revenue_cap(self.chef, order_amount_cents=100_00)
        self.assertFalse(result['under_cap'])

    def test_proposed_order_fits(self):
        self._create_tier_and_orders(9995_00, 10)  # $99,950
        result = check_revenue_cap(self.chef, order_amount_cents=50_00)  # +$50 = $100,000
        self.assertTrue(result['under_cap'])

    def test_percent_used(self):
        self._create_tier_and_orders(100_00, 500)  # $50,000
        result = check_revenue_cap(self.chef)
        self.assertEqual(result['percent_used'], 50.0)


class RevenueCapOrderGateTest(TestCase):
    """Test revenue cap enforcement in order creation."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="ordrevchef", email="ordrevchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user, mehko_active=True)
        self.customer = User.objects.create_user(
            username="ordrevcust", email="ordrevcust@test.com", password="testpass123"
        )
        # Accept disclosure so we get past that gate
        self.customer.mehko_disclosure_accepted_at = timezone.now()
        self.customer.save()
        UserRole.objects.create(user=self.customer)
        self.offering = ChefServiceOffering.objects.create(
            chef=self.chef, service_type="home_chef", title="Home Chef"
        )
        self.tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label="Expensive",
            household_min=1, household_max=4,
            desired_unit_amount_cents=100_00,  # $100
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.customer)

    def test_blocks_over_cap(self):
        # Fill up to cap
        big_tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label="Big",
            household_min=1, household_max=10,
            desired_unit_amount_cents=10000_00,  # $10,000
        )
        for _ in range(10):
            ChefServiceOrder.objects.create(
                chef=self.chef, customer=self.customer,
                offering=self.offering, tier=big_tier,
                household_size=2, service_date=timezone.now().date(),
                status='completed',
            )
        # Try to place another order
        today = timezone.now().date().isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': today,
            'service_start_time': '18:00',
            'delivery_method': 'self_delivery',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'mehko_revenue_cap')
