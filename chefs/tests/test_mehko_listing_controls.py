"""Tests for MEHKO listing controls (Phase 3)."""
from datetime import timedelta
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from chefs.models import Chef
from chefs.validators import validate_no_catering
from chef_services.models import ChefServiceOffering, ChefServicePriceTier, ChefServiceOrder
from chef_services.mehko_limits import check_meal_cap, get_daily_order_count, get_weekly_order_count
from custom_auth.models import UserRole

User = get_user_model()


class CateringWordValidatorTest(TestCase):
    """Test the catering word filter."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="catchef", email="cat@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user, mehko_active=True)

    def test_blocks_mehko_offering_title(self):
        with self.assertRaises(ValidationError):
            validate_no_catering("Event Catering Service", self.chef)

    def test_blocks_mehko_offering_description(self):
        with self.assertRaises(ValidationError):
            validate_no_catering("We provide catering for all events", self.chef)

    def test_allows_non_mehko_chef(self):
        self.chef.mehko_active = False
        self.chef.save()
        # Should not raise
        validate_no_catering("Event Catering Service", self.chef)

    def test_allows_none_chef(self):
        # Should not raise
        validate_no_catering("Event Catering Service", None)

    def test_case_insensitive(self):
        with self.assertRaises(ValidationError):
            validate_no_catering("CATERING services", self.chef)

    def test_allows_clean_text(self):
        # Should not raise
        validate_no_catering("Personal Home Chef Service", self.chef)

    def test_offering_clean_method(self):
        """ChefServiceOffering.clean() should call the catering validator."""
        offering = ChefServiceOffering(
            chef=self.chef,
            service_type="home_chef",
            title="My Catering Service",
            description="Great food",
        )
        with self.assertRaises(ValidationError):
            offering.full_clean()


class MealCapTest(TestCase):
    """Test meal cap enforcement."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="capchef", email="cap@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.chef_user, mehko_active=True
        )
        self.customer = User.objects.create_user(
            username="capcust", email="capcust@test.com", password="testpass123"
        )
        self.offering = ChefServiceOffering.objects.create(
            chef=self.chef, service_type="home_chef", title="Home Chef"
        )
        self.tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label="Standard",
            household_min=1,
            household_max=4,
            desired_unit_amount_cents=5000,
            
        )

    def _create_order(self, date=None, status='confirmed'):
        return ChefServiceOrder.objects.create(
            chef=self.chef,
            customer=self.customer,
            offering=self.offering,
            tier=self.tier,
            household_size=2,
            service_date=date or timezone.now().date(),
            status=status,
        )

    def test_daily_cap_at_30(self):
        today = timezone.now().date()
        for _ in range(30):
            self._create_order(date=today)
        result = check_meal_cap(self.chef, today)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['daily_remaining'], 0)

    def test_daily_cap_allows_under_30(self):
        today = timezone.now().date()
        for _ in range(29):
            self._create_order(date=today)
        result = check_meal_cap(self.chef, today)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['daily_remaining'], 1)

    def test_weekly_cap_at_90(self):
        today = timezone.now().date()
        monday = today - timedelta(days=today.weekday())
        for i in range(90):
            day = monday + timedelta(days=i % 7)
            self._create_order(date=day)
        result = check_meal_cap(self.chef, today)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['weekly_remaining'], 0)

    def test_cap_only_counts_confirmed_completed(self):
        today = timezone.now().date()
        for _ in range(30):
            self._create_order(date=today, status='draft')
        result = check_meal_cap(self.chef, today)
        self.assertTrue(result['allowed'])  # Drafts don't count

    def test_cap_ignores_non_mehko_chef(self):
        self.chef.mehko_active = False
        self.chef.save()
        result = check_meal_cap(self.chef)
        self.assertTrue(result['allowed'])
        self.assertFalse(result['enforced'])


class SameDayOrderTest(TestCase):
    """Test same-day ordering constraint for MEHKO chefs."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="sdchef", email="sd@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.chef_user, mehko_active=True
        )
        self.customer = User.objects.create_user(
            username="sdcust", email="sdcust@test.com", password="testpass123"
        )
        UserRole.objects.create(user=self.customer)
        self.offering = ChefServiceOffering.objects.create(
            chef=self.chef, service_type="home_chef", title="Home Chef"
        )
        self.tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label="Standard",
            household_min=1,
            household_max=4,
            desired_unit_amount_cents=5000,
            
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.customer)

    def test_blocks_future_date_for_mehko(self):
        future = (timezone.now().date() + timedelta(days=3)).isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': future,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'mehko_same_day')

    def test_allows_today_for_mehko(self):
        today = timezone.now().date().isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': today,
            'service_start_time': '18:00',
        }, format='json')
        # Should succeed (201) or at least not be blocked by MEHKO
        self.assertIn(resp.status_code, [201, 400])
        if resp.status_code == 400:
            self.assertNotEqual(resp.data.get('error'), 'mehko_same_day')

    def test_allows_future_for_non_mehko(self):
        self.chef.mehko_active = False
        self.chef.save()
        future = (timezone.now().date() + timedelta(days=3)).isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': future,
            'service_start_time': '18:00',
        }, format='json')
        # Should not be blocked by MEHKO same-day constraint
        if resp.status_code == 400:
            self.assertNotEqual(resp.data.get('error'), 'mehko_same_day')


class DeliveryModeTest(TestCase):
    """Test delivery mode enforcement for MEHKO chefs."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="delchef", email="del@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.chef_user, mehko_active=True
        )
        self.customer = User.objects.create_user(
            username="delcust", email="delcust@test.com", password="testpass123"
        )
        UserRole.objects.create(user=self.customer)
        self.offering = ChefServiceOffering.objects.create(
            chef=self.chef, service_type="home_chef", title="Home Chef"
        )
        self.tier = ChefServicePriceTier.objects.create(
            offering=self.offering,
            display_label="Standard",
            household_min=1,
            household_max=4,
            desired_unit_amount_cents=5000,
            
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.customer)

    def test_blocks_third_party_for_mehko(self):
        today = timezone.now().date().isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': today,
            'service_start_time': '18:00',
            'delivery_method': 'third_party',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'mehko_no_third_party')

    def test_allows_self_delivery_for_mehko(self):
        today = timezone.now().date().isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': today,
            'service_start_time': '18:00',
            'delivery_method': 'self_delivery',
        }, format='json')
        # Should not be blocked by delivery check
        if resp.status_code == 400:
            self.assertNotEqual(resp.data.get('error'), 'mehko_no_third_party')

    def test_allows_third_party_for_non_mehko(self):
        self.chef.mehko_active = False
        self.chef.save()
        future = (timezone.now().date() + timedelta(days=1)).isoformat()
        resp = self.client.post('/services/orders/', {
            'offering_id': self.offering.id,
            'tier_id': self.tier.id,
            'household_size': 2,
            'service_date': future,
            'service_start_time': '18:00',
            'delivery_method': 'third_party',
        }, format='json')
        if resp.status_code == 400:
            self.assertNotEqual(resp.data.get('error'), 'mehko_no_third_party')


class CountyGatingTest(TestCase):
    """Test county gating on public chef directory."""

    def setUp(self):
        # MEHKO chef in approved county
        self.approved_user = User.objects.create_user(
            username="approved", email="a@test.com", password="testpass123"
        )
        UserRole.objects.create(user=self.approved_user, is_chef=True, current_role='chef')
        self.approved_chef = Chef.objects.create(
            user=self.approved_user,
            is_verified=True,
            is_live=True,
            mehko_active=True,
            county="Alameda",
        )

        # MEHKO chef in non-approved county
        self.bad_user = User.objects.create_user(
            username="badcounty", email="b@test.com", password="testpass123"
        )
        UserRole.objects.create(user=self.bad_user, is_chef=True, current_role='chef')
        self.bad_chef = Chef.objects.create(
            user=self.bad_user,
            is_verified=True,
            is_live=True,
            mehko_active=True,
            county="Fake County",
        )

        # Non-MEHKO chef
        self.normal_user = User.objects.create_user(
            username="normalchef", email="n@test.com", password="testpass123"
        )
        UserRole.objects.create(user=self.normal_user, is_chef=True, current_role='chef')
        self.normal_chef = Chef.objects.create(
            user=self.normal_user,
            is_verified=True,
            is_live=True,
            mehko_active=False,
        )

        self.client = APIClient()

    def test_excludes_non_approved_mehko(self):
        resp = self.client.get('/chefs/api/public/')
        self.assertEqual(resp.status_code, 200)
        chef_ids = [c['id'] for c in resp.data.get('results', resp.data)]
        self.assertNotIn(self.bad_chef.id, chef_ids)

    def test_includes_approved_mehko(self):
        resp = self.client.get('/chefs/api/public/')
        self.assertEqual(resp.status_code, 200)
        chef_ids = [c['id'] for c in resp.data.get('results', resp.data)]
        self.assertIn(self.approved_chef.id, chef_ids)

    def test_includes_non_mehko(self):
        resp = self.client.get('/chefs/api/public/')
        self.assertEqual(resp.status_code, 200)
        chef_ids = [c['id'] for c in resp.data.get('results', resp.data)]
        self.assertIn(self.normal_chef.id, chef_ids)
