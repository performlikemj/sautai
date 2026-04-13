from django.test import TestCase
from rest_framework.test import APIClient

from custom_auth.models import CustomUser, Address


class RegistrationIntentTests(TestCase):
    """Tests for intent-aware registration (Phase 1: chef sign-up path)."""

    def setUp(self):
        self.client = APIClient()
        self.url = '/auth/api/register/'

    def _base_payload(self, **overrides):
        payload = {
            'user': {
                'username': 'testchef',
                'email': 'testchef@example.com',
                'password': 'securepass123',
                'timezone': 'America/New_York',
                'measurement_system': 'US',
                'preferred_language': 'en',
                'allergies': [],
                'dietary_preferences': [],
                'household_member_count': 1,
            }
        }
        payload.update(overrides)
        return payload

    def test_register_with_address_creates_address(self):
        """POST with address data should create a linked Address record."""
        payload = self._base_payload(
            address={'city': 'Los Angeles', 'country': 'US'}
        )
        resp = self.client.post(self.url, payload, format='json')
        self.assertIn(resp.status_code, [200, 201], resp.content)

        user = CustomUser.objects.get(username='testchef')
        self.assertTrue(hasattr(user, 'address'))
        self.assertEqual(user.address.city, 'Los Angeles')
        self.assertEqual(str(user.address.country), 'US')

    def test_register_without_address_still_works(self):
        """Existing registration flow without address should continue working."""
        payload = self._base_payload()
        resp = self.client.post(self.url, payload, format='json')
        self.assertIn(resp.status_code, [200, 201], resp.content)

        user = CustomUser.objects.get(username='testchef')
        self.assertIn('access', resp.json())
        self.assertIn('refresh', resp.json())

    def test_register_with_intent_echoes_intent(self):
        """When payload includes intent, it should be echoed in the response."""
        payload = self._base_payload(
            intent='chef',
            address={'city': 'San Diego', 'country': 'US'}
        )
        resp = self.client.post(self.url, payload, format='json')
        self.assertIn(resp.status_code, [200, 201], resp.content)
        self.assertEqual(resp.json().get('intent'), 'chef')

    def test_register_without_intent_has_no_intent_in_response(self):
        """When no intent is provided, response should not include intent field."""
        payload = self._base_payload()
        resp = self.client.post(self.url, payload, format='json')
        self.assertIn(resp.status_code, [200, 201], resp.content)
        self.assertNotIn('intent', resp.json())

    def test_register_address_city_country_only(self):
        """City + country without postal code should be accepted."""
        payload = self._base_payload(
            address={'city': 'Portland', 'country': 'US'}
        )
        resp = self.client.post(self.url, payload, format='json')
        self.assertIn(resp.status_code, [200, 201], resp.content)

        user = CustomUser.objects.get(username='testchef')
        self.assertEqual(user.address.city, 'Portland')
        # No postal code should be fine
        self.assertFalse(user.address.normalized_postalcode)
