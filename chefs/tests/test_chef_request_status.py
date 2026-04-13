import tempfile

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from custom_auth.models import CustomUser, UserRole
from chefs.models import Chef, ChefRequest


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChefRequestStatusTests(TestCase):
    """Tests for enhanced check-chef-status and field-level validation on submit."""

    def setUp(self):
        self.client = APIClient()
        self.user = CustomUser.objects.create_user(
            username='statususer', email='status@test.com', password='testpass123'
        )
        UserRole.objects.create(user=self.user, current_role='customer')
        self.client.force_authenticate(user=self.user)

    # --- check_chef_status tests ---

    def test_check_status_no_request(self):
        """Returns basic status when no ChefRequest exists."""
        resp = self.client.get('/chefs/api/check-chef-status/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['is_chef'])
        self.assertFalse(data['has_pending_request'])

    def test_check_status_with_pending_request(self):
        """Returns enriched data when a pending ChefRequest exists."""
        cr = ChefRequest.objects.create(
            user=self.user, experience='10 years cooking', bio='I love food and sharing meals', is_approved=False
        )
        resp = self.client.get('/chefs/api/check-chef-status/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['is_chef'])
        self.assertTrue(data['has_pending_request'])
        self.assertIn('submitted_at', data)
        self.assertIn('experience_preview', data)

    def test_check_status_approved(self):
        """When user is a chef, returns is_chef=true."""
        chef = Chef.objects.create(user=self.user)
        resp = self.client.get('/chefs/api/check-chef-status/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['is_chef'])
        self.assertFalse(data['has_pending_request'])
        self.assertEqual(data.get('next_step'), '/chefs/dashboard')

    # --- submit_chef_request validation tests ---

    def test_submit_validates_bio_min_length(self):
        """Bio under 50 chars should return 400 with field_errors."""
        from custom_auth.models import Address
        Address.objects.create(user=self.user, city='LA', country='US')

        resp = self.client.post('/chefs/api/submit-chef-request/', {
            'experience': 'I have been cooking professionally for over ten years.',
            'bio': 'Short bio',
            'city': 'LA',
            'country': 'US',
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn('field_errors', data)
        self.assertIn('bio', data['field_errors'])

    def test_submit_validates_experience_min_length(self):
        """Experience under 20 chars should return 400 with field_errors."""
        from custom_auth.models import Address
        Address.objects.create(user=self.user, city='LA', country='US')

        resp = self.client.post('/chefs/api/submit-chef-request/', {
            'experience': 'Short',
            'bio': 'I am a passionate chef who loves creating farm-to-table experiences for my clients.',
            'city': 'LA',
            'country': 'US',
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn('field_errors', data)
        self.assertIn('experience', data['field_errors'])

    def test_submit_succeeds_with_valid_lengths(self):
        """Valid bio and experience should succeed."""
        from custom_auth.models import Address
        Address.objects.create(user=self.user, city='LA', country='US')

        resp = self.client.post('/chefs/api/submit-chef-request/', {
            'experience': 'I have been cooking professionally for over ten years.',
            'bio': 'I am a passionate chef who loves creating farm-to-table experiences for my clients.',
            'city': 'LA',
            'country': 'US',
        })
        self.assertIn(resp.status_code, [200, 201], resp.content)
