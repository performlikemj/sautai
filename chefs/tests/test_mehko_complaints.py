"""Tests for MEHKO complaint pipeline (Phase 5)."""
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from chefs.models import Chef, MehkoComplaint
from chefs.models.proactive import ChefNotification
from custom_auth.models import UserRole

User = get_user_model()


class ComplaintSubmissionTest(TestCase):
    """Test complaint submission endpoint."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="compchef", email="compchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.chef_user, mehko_active=True,
            permit_number="TEST-001", permitting_agency="Test Agency",
            county="Alameda",
        )
        self.complainant = User.objects.create_user(
            username="complainant", email="comp@test.com", password="testpass123"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.complainant)

    def test_submit_success(self):
        resp = self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'Food was not prepared safely and was cold upon delivery.',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(MehkoComplaint.objects.count(), 1)

    def test_requires_auth(self):
        client = APIClient()
        resp = client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'Food was not prepared safely and was cold.',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_min_length(self):
        resp = self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'Too short',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('complaint_text', resp.data)

    def test_only_mehko_chef(self):
        self.chef.mehko_active = False
        self.chef.save()
        resp = self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'This should be rejected since chef is not MEHKO.',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('chef_id', resp.data)

    def test_rate_limited(self):
        self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'First complaint about food safety concern here.',
        }, format='json')
        resp = self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'Second complaint within 24 hours should fail.',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('complaint_text', resp.data)

    def test_chef_not_found(self):
        resp = self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': 99999,
            'complaint_text': 'Complaint against nonexistent chef for testing.',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('chef_id', resp.data)


class ThresholdNotificationTest(TestCase):
    """Test complaint threshold monitoring."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="thrchef", email="thrchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.chef_user, mehko_active=True,
            permit_number="THR-001", permitting_agency="Test Agency",
            county="Los Angeles",
        )
        self.client = APIClient()

    def _file_complaint(self, user_suffix):
        user = User.objects.create_user(
            username=f"comp_{user_suffix}", email=f"comp_{user_suffix}@test.com",
            password="testpass123"
        )
        self.client.force_authenticate(user=user)
        return self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': f'Food safety complaint number {user_suffix} filed here.',
        }, format='json')

    def test_threshold_triggers_notification(self):
        for i in range(3):
            resp = self._file_complaint(f"thr{i}")
            self.assertEqual(resp.status_code, 201)

        notifications = ChefNotification.objects.filter(
            chef=self.chef,
            notification_type=ChefNotification.TYPE_COMPLAINT_THRESHOLD,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn("3 complaints", notifications.first().message)

    def test_threshold_dedup(self):
        """Notifications dedup by count bracket — same distinct count doesn't re-notify."""
        # File 3 complaints from 3 distinct users → triggers notification at n=3
        for i in range(3):
            self._file_complaint(f"dup{i}")

        notifications = ChefNotification.objects.filter(
            chef=self.chef,
            notification_type=ChefNotification.TYPE_COMPLAINT_THRESHOLD,
        )
        self.assertEqual(notifications.count(), 1)

        # File a 4th from same user as #0 (not a new distinct complainant)
        user = User.objects.get(username="comp_dup0")
        # Need to clear rate limit by adjusting submitted_at
        from chefs.models import MehkoComplaint
        MehkoComplaint.objects.filter(complainant=user).update(
            submitted_at=timezone.now() - timedelta(days=2)
        )
        self.client.force_authenticate(user=user)
        self.client.post('/chefs/api/mehko/complaints/', {
            'chef_id': self.chef.id,
            'complaint_text': 'Follow up complaint from same person as before.',
        }, format='json')
        # Still 3 distinct complainants → still 1 notification (deduped)
        self.assertEqual(notifications.count(), 1)


class ComplaintCountEndpointTest(TestCase):
    """Test public complaint count endpoint."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="cntchef", email="cntchef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user, mehko_active=True)
        self.client = APIClient()

    def test_returns_count(self):
        user = User.objects.create_user(
            username="cntcomp", email="cntcomp@test.com", password="testpass123"
        )
        MehkoComplaint.objects.create(
            chef=self.chef, complainant=user,
            complaint_text="Test complaint for count endpoint testing."
        )
        resp = self.client.get(f'/chefs/api/mehko/complaints/chef/{self.chef.id}/count/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)

    def test_not_found(self):
        resp = self.client.get('/chefs/api/mehko/complaints/chef/99999/count/')
        self.assertEqual(resp.status_code, 404)

    def test_threshold_reached_in_count(self):
        for i in range(3):
            user = User.objects.create_user(
                username=f"cntc{i}", email=f"cntc{i}@test.com", password="testpass123"
            )
            MehkoComplaint.objects.create(
                chef=self.chef, complainant=user,
                complaint_text=f"Complaint {i} for threshold count test here."
            )
        resp = self.client.get(f'/chefs/api/mehko/complaints/chef/{self.chef.id}/count/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 3)
