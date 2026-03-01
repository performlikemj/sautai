"""Tests for MEHKO serializer validation (serializer consolidation)."""
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from chefs.models import Chef, MehkoComplaint, MehkoConfig
from chefs.serializers import ChefMehkoSerializer, MehkoComplaintSerializer, ChefPublicSerializer
from chef_services.models import ChefServiceOffering, ChefServicePriceTier
from chef_services.serializers import ChefServiceOfferingSerializer, ChefServiceOrderSerializer
from chef_services.mehko_limits import check_meal_cap, check_revenue_cap
from custom_auth.models import UserRole

User = get_user_model()


# --- M3: ChefServiceOfferingSerializer catering validation ---

class OfferingSerializerCateringTest(TestCase):
    """Test that DRF serializer catches catering words for MEHKO chefs."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="offchef", email="offchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user, mehko_active=True)

    def test_blocks_catering_title(self):
        data = {
            'service_type': 'home_chef',
            'title': 'My Catering Service',
            'description': 'Great food for events',
        }
        serializer = ChefServiceOfferingSerializer(
            data=data, context={'chef': self.chef}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('title', serializer.errors)

    def test_blocks_catering_description(self):
        data = {
            'service_type': 'home_chef',
            'title': 'Home Chef Service',
            'description': 'We cater to all your needs',
        }
        serializer = ChefServiceOfferingSerializer(
            data=data, context={'chef': self.chef}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('description', serializer.errors)

    def test_allows_non_mehko_catering(self):
        self.chef.mehko_active = False
        self.chef.save()
        data = {
            'service_type': 'home_chef',
            'title': 'My Catering Service',
            'description': 'Great catering for events',
        }
        serializer = ChefServiceOfferingSerializer(
            data=data, context={'chef': self.chef}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_api_create_blocks_catering(self):
        """End-to-end: creating offering via API blocks catering."""
        UserRole.objects.create(user=self.user, is_chef=True, current_role='chef')
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post('/services/offerings/', {
            'service_type': 'home_chef',
            'title': 'Event Catering',
            'description': 'Fine dining',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_blocks_cater_variation(self):
        data = {
            'service_type': 'home_chef',
            'title': 'Professional Caterer',
            'description': 'Great food',
        }
        serializer = ChefServiceOfferingSerializer(
            data=data, context={'chef': self.chef}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('title', serializer.errors)


# --- ChefServiceOrderSerializer delivery + charged_amount ---

class OrderSerializerTest(TestCase):
    """Test order serializer MEHKO fields."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="ordserchef", email="ordserchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user, mehko_active=True)
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

    def test_blocks_third_party_mehko(self):
        data = {
            'offering': self.offering.id,
            'offering_id': self.offering.id,
            'delivery_method': 'third_party',
        }
        serializer = ChefServiceOrderSerializer(data=data)
        # validate_delivery_method should fail
        self.assertFalse(serializer.is_valid())
        self.assertIn('delivery_method', serializer.errors)

    def test_allows_third_party_non_mehko(self):
        self.chef.mehko_active = False
        self.chef.save()
        data = {
            'offering': self.offering.id,
            'offering_id': self.offering.id,
            'delivery_method': 'third_party',
        }
        serializer = ChefServiceOrderSerializer(data=data)
        # delivery_method should pass (other fields may fail)
        serializer.is_valid()
        self.assertNotIn('delivery_method', serializer.errors)

    def test_charged_amount_read_only(self):
        """charged_amount_cents should not be settable via serializer."""
        self.assertIn('charged_amount_cents', ChefServiceOrderSerializer.Meta.read_only_fields)


# --- ChefMehkoSerializer ---

class MehkoSerializerFieldsTest(TestCase):
    """Test ChefMehkoSerializer field exposure."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="mehkoser", email="mehkoser@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.user, mehko_active=True,
            insured=True,
            insurance_expiry=timezone.now().date() + timedelta(days=365),
        )

    def test_includes_insurance_fields(self):
        serializer = ChefMehkoSerializer(self.chef)
        self.assertIn('insured', serializer.data)
        self.assertIn('insurance_expiry', serializer.data)
        self.assertTrue(serializer.data['insured'])

    def test_consent_at_read_only(self):
        self.assertIn('mehko_consent_at', ChefMehkoSerializer.Meta.read_only_fields)

    def test_missing_requirements_includes_insured(self):
        self.chef.insured = False
        self.chef.save()
        serializer = ChefMehkoSerializer(self.chef)
        self.assertIn('insured', serializer.data['missing_requirements'])

    def test_consent_revocation_blocked(self):
        self.chef.mehko_consent = True
        self.chef.save()
        serializer = ChefMehkoSerializer(
            self.chef, data={'mehko_consent': False}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('mehko_consent', serializer.errors)


# --- ChefPublicSerializer ---

class PublicSerializerMehkoTest(TestCase):
    """Test ChefPublicSerializer MEHKO field exposure."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="pubser", email="pubser@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.user, mehko_active=True,
            permit_number="PUB-001",
            permitting_agency="Alameda County DEH",
            county="Alameda",
            permit_expiry=timezone.now().date() + timedelta(days=365),
        )

    def test_includes_complaint_count(self):
        serializer = ChefPublicSerializer(self.chef)
        data = serializer.data
        self.assertIn('complaint_count', data)
        self.assertEqual(data['complaint_count'], 0)

    def test_includes_enforcement_agency(self):
        serializer = ChefPublicSerializer(self.chef)
        data = serializer.data
        self.assertIn('enforcement_agency', data)
        self.assertIn('name', data['enforcement_agency'])

    def test_non_mehko_excludes_fields(self):
        self.chef.mehko_active = False
        self.chef.save()
        serializer = ChefPublicSerializer(self.chef)
        data = serializer.data
        self.assertNotIn('complaint_count', data)
        self.assertNotIn('enforcement_agency', data)
        self.assertNotIn('home_kitchen_disclaimer', data)


# --- MehkoComplaintSerializer ---

class ComplaintSerializerTest(TestCase):
    """Test MehkoComplaintSerializer validation."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="compserchef", email="compserchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user, mehko_active=True)
        self.complainant = User.objects.create_user(
            username="compseruser", email="compseruser@test.com", password="testpass123"
        )

    def test_validates_min_length(self):
        s = MehkoComplaintSerializer(data={
            'chef_id': self.chef.id, 'complaint_text': 'Too short'
        })
        self.assertFalse(s.is_valid())
        self.assertIn('complaint_text', s.errors)

    def test_validates_max_length(self):
        s = MehkoComplaintSerializer(data={
            'chef_id': self.chef.id, 'complaint_text': 'x' * 5001
        })
        self.assertFalse(s.is_valid())
        self.assertIn('complaint_text', s.errors)

    def test_validates_chef_exists(self):
        s = MehkoComplaintSerializer(data={
            'chef_id': 99999, 'complaint_text': 'Valid complaint text for testing.'
        })
        self.assertFalse(s.is_valid())
        self.assertIn('chef_id', s.errors)

    def test_validates_mehko_active(self):
        self.chef.mehko_active = False
        self.chef.save()
        s = MehkoComplaintSerializer(data={
            'chef_id': self.chef.id,
            'complaint_text': 'Valid complaint text for testing.'
        })
        self.assertFalse(s.is_valid())
        self.assertIn('chef_id', s.errors)

    def test_validates_valid_data(self):
        s = MehkoComplaintSerializer(data={
            'chef_id': self.chef.id,
            'complaint_text': 'Valid complaint about food safety here.',
        })
        self.assertTrue(s.is_valid(), s.errors)


# --- MehkoConfig ---

class MehkoConfigTest(TestCase):
    """Test MehkoConfig dynamic caps."""

    def test_returns_fallback_when_no_config(self):
        config = MehkoConfig.get_current()
        self.assertEqual(config.daily_meal_cap, 30)
        self.assertEqual(config.weekly_meal_cap, 90)
        self.assertEqual(config.annual_revenue_cap, 100_000)

    def test_returns_latest_effective(self):
        MehkoConfig.objects.create(
            daily_meal_cap=30, weekly_meal_cap=90,
            annual_revenue_cap=100_000,
            effective_date=timezone.now().date() - timedelta(days=365),
        )
        MehkoConfig.objects.create(
            daily_meal_cap=35, weekly_meal_cap=100,
            annual_revenue_cap=105_000,
            effective_date=timezone.now().date() - timedelta(days=1),
            notes="CPI adjustment 2026",
        )
        config = MehkoConfig.get_current()
        self.assertEqual(config.daily_meal_cap, 35)
        self.assertEqual(config.weekly_meal_cap, 100)
        self.assertEqual(config.annual_revenue_cap, 105_000)

    def test_ignores_future_config(self):
        MehkoConfig.objects.create(
            daily_meal_cap=30, weekly_meal_cap=90,
            annual_revenue_cap=100_000,
            effective_date=timezone.now().date() - timedelta(days=30),
        )
        MehkoConfig.objects.create(
            daily_meal_cap=40, weekly_meal_cap=120,
            annual_revenue_cap=120_000,
            effective_date=timezone.now().date() + timedelta(days=365),
        )
        config = MehkoConfig.get_current()
        self.assertEqual(config.daily_meal_cap, 30)

    def test_meal_cap_uses_config(self):
        """Integration: check_meal_cap reads from MehkoConfig."""
        MehkoConfig.objects.create(
            daily_meal_cap=5, weekly_meal_cap=10,
            annual_revenue_cap=100_000,
            effective_date=timezone.now().date() - timedelta(days=1),
        )
        user = User.objects.create_user(
            username="capcfg", email="capcfg@test.com", password="testpass123"
        )
        chef = Chef.objects.create(user=user, mehko_active=True)
        result = check_meal_cap(chef)
        self.assertTrue(result['enforced'])
        self.assertEqual(result['daily_remaining'], 5)

    def test_revenue_cap_uses_config(self):
        """Integration: check_revenue_cap reads from MehkoConfig."""
        MehkoConfig.objects.create(
            daily_meal_cap=30, weekly_meal_cap=90,
            annual_revenue_cap=50_000,
            effective_date=timezone.now().date() - timedelta(days=1),
        )
        user = User.objects.create_user(
            username="revcfg", email="revcfg@test.com", password="testpass123"
        )
        chef = Chef.objects.create(user=user, mehko_active=True)
        result = check_revenue_cap(chef)
        self.assertEqual(result['cap'], 50_000)
