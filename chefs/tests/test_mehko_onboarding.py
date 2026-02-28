"""Tests for MEHKO/IFSI onboarding compliance (Phase 2)."""
from datetime import timedelta
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from chefs.models import Chef, ChefVerificationDocument
from chefs.constants import MEHKO_APPROVED_COUNTIES
from custom_auth.models import UserRole

User = get_user_model()


class MehkoEligibilityTest(TestCase):
    """Test Chef.check_mehko_eligibility()."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="eligchef", email="elig@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user)

    def _make_eligible(self):
        """Set all fields to make chef MEHKO eligible."""
        self.chef.permit_number = "MEHKO-2026-001"
        self.chef.permitting_agency = "Alameda County DEH"
        self.chef.permit_expiry = timezone.now().date() + timedelta(days=365)
        self.chef.county = "Alameda"
        self.chef.mehko_consent = True
        self.chef.food_handlers_cert = True
        self.chef.insured = True
        self.chef.insurance_expiry = timezone.now().date() + timedelta(days=365)
        self.chef.save()

    def test_all_requirements_met(self):
        self._make_eligible()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertTrue(eligible)
        self.assertEqual(missing, [])

    def test_missing_permit_number(self):
        self._make_eligible()
        self.chef.permit_number = ""
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("permit_number", missing)

    def test_missing_permitting_agency(self):
        self._make_eligible()
        self.chef.permitting_agency = ""
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("permitting_agency", missing)

    def test_expired_permit(self):
        self._make_eligible()
        self.chef.permit_expiry = timezone.now().date() - timedelta(days=1)
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("permit_expiry", missing)

    def test_null_permit_expiry(self):
        self._make_eligible()
        self.chef.permit_expiry = None
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("permit_expiry", missing)

    def test_bad_county(self):
        self._make_eligible()
        self.chef.county = "Fake County"
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("county", missing)

    def test_empty_county(self):
        self._make_eligible()
        self.chef.county = ""
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("county", missing)

    def test_missing_consent(self):
        self._make_eligible()
        self.chef.mehko_consent = False
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("mehko_consent", missing)

    def test_missing_food_cert(self):
        self._make_eligible()
        self.chef.food_handlers_cert = False
        self.chef.save()
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertIn("food_handlers_cert", missing)

    def test_multiple_missing(self):
        # Fresh chef — everything is missing
        eligible, missing = self.chef.check_mehko_eligibility()
        self.assertFalse(eligible)
        self.assertEqual(len(missing), 7)  # all 7 requirements


class MehkoAPITest(TestCase):
    """Test MEHKO PATCH/GET endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="apichef", email="api@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user)
        UserRole.objects.create(user=self.user, is_chef=True, current_role='chef')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_mehko_status(self):
        resp = self.client.get('/chefs/api/me/chef/mehko/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['mehko_active'])
        self.assertEqual(len(resp.data['missing_requirements']), 7)

    def test_patch_updates_fields(self):
        resp = self.client.patch('/chefs/api/me/chef/mehko/', {
            'permit_number': 'MEHKO-2026-001',
            'permitting_agency': 'Alameda County DEH',
            'county': 'Alameda',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.chef.refresh_from_db()
        self.assertEqual(self.chef.permit_number, 'MEHKO-2026-001')
        self.assertEqual(self.chef.county, 'Alameda')

    def test_patch_auto_activates(self):
        self.chef.food_handlers_cert = True
        self.chef.insured = True
        self.chef.insurance_expiry = timezone.now().date() + timedelta(days=365)
        self.chef.save()
        resp = self.client.patch('/chefs/api/me/chef/mehko/', {
            'permit_number': 'MEHKO-2026-001',
            'permitting_agency': 'Alameda County DEH',
            'permit_expiry': (timezone.now().date() + timedelta(days=365)).isoformat(),
            'county': 'Alameda',
            'mehko_consent': True,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['mehko_active'])
        self.assertEqual(resp.data['missing_requirements'], [])

    def test_patch_deactivates_when_incomplete(self):
        # First activate
        self.chef.food_handlers_cert = True
        self.chef.insured = True
        self.chef.insurance_expiry = timezone.now().date() + timedelta(days=365)
        self.chef.permit_number = 'MEHKO-2026-001'
        self.chef.permitting_agency = 'Alameda County DEH'
        self.chef.permit_expiry = timezone.now().date() + timedelta(days=365)
        self.chef.county = 'Alameda'
        self.chef.mehko_consent = True
        self.chef.mehko_active = True
        self.chef.save()

        # Remove consent
        resp = self.client.patch('/chefs/api/me/chef/mehko/', {
            'mehko_consent': False,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['mehko_active'])

    def test_patch_rejects_bad_county(self):
        resp = self.client.patch('/chefs/api/me/chef/mehko/', {
            'county': 'Narnia',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('county', resp.data)

    def test_patch_rejects_past_expiry(self):
        resp = self.client.patch('/chefs/api/me/chef/mehko/', {
            'permit_expiry': (timezone.now().date() - timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('permit_expiry', resp.data)

    def test_requires_auth(self):
        client = APIClient()  # not authenticated
        resp = client.get('/chefs/api/me/chef/mehko/')
        self.assertEqual(resp.status_code, 401)


class SetLiveMehkoGateTest(TestCase):
    """Test that me_set_live() gates MEHKO chefs on compliance."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="livechef", email="live@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user)
        UserRole.objects.create(user=self.user, is_chef=True, current_role='chef')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_non_mehko_chef_not_affected(self):
        """Chef without county set should not be subject to MEHKO checks."""
        # Note: This test will fail because Stripe is also required.
        # We're testing that the MEHKO check specifically doesn't block.
        self.chef.county = ""
        self.chef.save()
        resp = self.client.post('/chefs/api/me/chef/live/', {'is_live': True}, format='json')
        # Should fail on Stripe, not MEHKO
        if resp.status_code == 400:
            self.assertIn(resp.data.get('error', ''), ['stripe_not_connected', 'stripe_not_active'])

    def test_mehko_chef_blocked_without_compliance(self):
        """MEHKO chef (consent given) should be blocked if not eligible."""
        self.chef.mehko_consent = True
        self.chef.save()
        resp = self.client.post('/chefs/api/me/chef/live/', {'is_live': True}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'mehko_incomplete')
        self.assertIn('missing', resp.data)


class PermitDocUploadTest(TestCase):
    """Test that permit doc type is accepted for upload."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="docchef", email="doc@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user)

    def test_permit_doc_type_in_choices(self):
        """The 'permit' doc type should be in ChefVerificationDocument choices."""
        valid_types = [t[0] for t in ChefVerificationDocument.DOC_TYPES]
        self.assertIn('permit', valid_types)
