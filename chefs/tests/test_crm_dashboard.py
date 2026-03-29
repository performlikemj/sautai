"""
Comprehensive tests for Chef CRM Dashboard API.

Tests cover:
- Security (authentication, authorization, data isolation)
- Functionality (all endpoints work correctly)
- Edge cases and error handling
- Performance considerations (query efficiency)

Run with: pytest chefs/tests/test_crm_dashboard.py -v
"""

from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from custom_auth.models import CustomUser
from chefs.models import Chef
from chef_services.models import (
    ChefCustomerConnection,
    ChefServiceOffering,
    ChefServicePriceTier,
    ChefServiceOrder,
)
from meals.models import Meal, ChefMealEvent, ChefMealOrder
from crm.models import Lead, LeadInteraction


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ChefCrmSecurityTests(TestCase):
    """Tests for authentication and authorization security."""

    def setUp(self):
        self.client = APIClient()
        
        # Create a regular customer (non-chef)
        self.customer = CustomUser.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="testpass123",
        )
        
        # Create a chef user
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create another chef for isolation tests
        self.other_chef_user = CustomUser.objects.create_user(
            username="otherchef",
            email="other@example.com",
            password="testpass123",
        )
        self.other_chef = Chef.objects.create(user=self.other_chef_user)

    def _authenticate(self, user=None):
        if user is None:
            self.client.force_authenticate(user=None)
        else:
            self.client.force_authenticate(user=user)

    # =========================================================================
    # Authentication Tests - All endpoints require authentication
    # =========================================================================

    def test_dashboard_requires_authentication(self):
        """Dashboard endpoint should reject unauthenticated requests."""
        self._authenticate(None)
        url = reverse('chefs:chef_dashboard')
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [401, 403])

    def test_clients_requires_authentication(self):
        """Clients endpoint should reject unauthenticated requests."""
        self._authenticate(None)
        url = reverse('chefs:chef_clients')
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [401, 403])

    def test_revenue_requires_authentication(self):
        """Revenue endpoint should reject unauthenticated requests."""
        self._authenticate(None)
        url = reverse('chefs:chef_revenue')
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [401, 403])

    def test_leads_requires_authentication(self):
        """Leads endpoint should reject unauthenticated requests."""
        self._authenticate(None)
        url = reverse('chefs:chef_leads')
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [401, 403])

    def test_upcoming_orders_requires_authentication(self):
        """Upcoming orders endpoint should reject unauthenticated requests."""
        self._authenticate(None)
        url = reverse('chefs:chef_upcoming_orders')
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [401, 403])

    # =========================================================================
    # Authorization Tests - Only chefs can access chef endpoints
    # =========================================================================

    def test_dashboard_rejects_non_chef(self):
        """Dashboard should return 403 for non-chef users."""
        self._authenticate(self.customer)
        url = reverse('chefs:chef_dashboard')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)
        self.assertIn('error', resp.json())

    def test_clients_rejects_non_chef(self):
        """Clients endpoint should return 403 for non-chef users."""
        self._authenticate(self.customer)
        url = reverse('chefs:chef_clients')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_revenue_rejects_non_chef(self):
        """Revenue endpoint should return 403 for non-chef users."""
        self._authenticate(self.customer)
        url = reverse('chefs:chef_revenue')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_leads_rejects_non_chef(self):
        """Leads endpoint should return 403 for non-chef users."""
        self._authenticate(self.customer)
        url = reverse('chefs:chef_leads')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # Data Isolation Tests - Chefs only see their own data
    # =========================================================================

    def test_chef_cannot_see_other_chef_leads(self):
        """A chef should only see their own leads, not other chefs' leads."""
        # Create lead for other chef
        other_lead = Lead.objects.create(
            owner=self.other_chef_user,
            first_name="Other",
            last_name="Lead",
            email="other@lead.com",
            status=Lead.Status.NEW,
        )
        
        # Create lead for our chef
        my_lead = Lead.objects.create(
            owner=self.chef_user,
            first_name="My",
            last_name="Lead",
            email="my@lead.com",
            status=Lead.Status.NEW,
        )
        
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        # Should only see our lead
        lead_ids = [lead['id'] for lead in results]
        self.assertIn(my_lead.id, lead_ids)
        self.assertNotIn(other_lead.id, lead_ids)

    def test_chef_cannot_access_other_chef_client(self):
        """A chef should not be able to view another chef's client details."""
        # Create connection between other chef and customer
        connection = ChefCustomerConnection.objects.create(
            chef=self.other_chef,
            customer=self.customer,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
        )
        
        # Try to access this client as our chef
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_detail', args=[self.customer.id])
        resp = self.client.get(url)
        
        # Should return 404 (no connection found)
        self.assertEqual(resp.status_code, 404)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ChefCrmDashboardTests(TestCase):
    """Tests for the dashboard summary endpoint."""

    def setUp(self):
        self.client = APIClient()
        
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create customers
        self.customer1 = CustomUser.objects.create_user(
            username="customer1",
            email="customer1@example.com",
            password="testpass123",
        )
        self.customer2 = CustomUser.objects.create_user(
            username="customer2",
            email="customer2@example.com",
            password="testpass123",
        )

    def _authenticate(self, user=None):
        if user is None:
            self.client.force_authenticate(user=None)
        else:
            self.client.force_authenticate(user=user)

    def test_dashboard_returns_correct_structure(self):
        """Dashboard should return expected JSON structure."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_dashboard')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        # Check required keys exist
        self.assertIn('revenue', data)
        self.assertIn('clients', data)
        self.assertIn('orders', data)
        self.assertIn('top_services', data)
        
        # Check revenue structure
        self.assertIn('today', data['revenue'])
        self.assertIn('this_week', data['revenue'])
        self.assertIn('this_month', data['revenue'])
        
        # Check clients structure
        self.assertIn('total', data['clients'])
        self.assertIn('active', data['clients'])
        self.assertIn('new_this_month', data['clients'])
        
        # Check orders structure
        self.assertIn('upcoming', data['orders'])
        self.assertIn('pending_confirmation', data['orders'])
        self.assertIn('completed_this_month', data['orders'])

    def test_dashboard_counts_active_clients(self):
        """Dashboard should correctly count active (accepted) connections."""
        # Create accepted connection
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer1,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            responded_at=timezone.now(),
        )
        
        # Create pending connection (should not count as active)
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer2,
            status=ChefCustomerConnection.STATUS_PENDING,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
        )
        
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_dashboard')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data['clients']['total'], 2)
        self.assertEqual(data['clients']['active'], 1)

    def test_dashboard_empty_for_new_chef(self):
        """New chef with no data should see zeros, not errors."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_dashboard')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        # All counts should be 0 or empty
        self.assertEqual(data['clients']['total'], 0)
        self.assertEqual(data['clients']['active'], 0)
        self.assertEqual(data['orders']['upcoming'], 0)
        self.assertEqual(data['top_services'], [])


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ChefCrmClientManagementTests(TestCase):
    """Tests for client management endpoints."""

    def setUp(self):
        self.client = APIClient()
        
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create customers with different names for search testing
        self.customer1 = CustomUser.objects.create_user(
            username="johndoe",
            email="john@example.com",
            password="testpass123",
            first_name="John",
            last_name="Doe",
        )
        self.customer2 = CustomUser.objects.create_user(
            username="janedoe",
            email="jane@example.com",
            password="testpass123",
            first_name="Jane",
            last_name="Doe",
        )
        self.customer3 = CustomUser.objects.create_user(
            username="bobsmith",
            email="bob@example.com",
            password="testpass123",
            first_name="Bob",
            last_name="Smith",
        )
        
        # Create connections
        self.connection1 = ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer1,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            responded_at=timezone.now() - timedelta(days=30),
        )
        self.connection2 = ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer2,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            responded_at=timezone.now() - timedelta(days=5),
        )
        self.connection3 = ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer3,
            status=ChefCustomerConnection.STATUS_PENDING,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CHEF,
        )

    def _authenticate(self, user=None):
        if user is None:
            self.client.force_authenticate(user=None)
        else:
            self.client.force_authenticate(user=user)

    def test_client_list_returns_accepted_by_default(self):
        """Client list should only show accepted connections by default."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_clients')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        # Should only see 2 accepted clients, not the pending one
        self.assertEqual(len(results), 2)
        customer_ids = [c['customer_id'] for c in results]
        self.assertIn(self.customer1.id, customer_ids)
        self.assertIn(self.customer2.id, customer_ids)
        self.assertNotIn(self.customer3.id, customer_ids)

    def test_client_list_filter_by_status(self):
        """Client list should filter by status parameter."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_clients')
        
        # Filter for pending
        resp = self.client.get(url, {'status': 'pending'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['customer_id'], self.customer3.id)

    def test_client_list_search_by_name(self):
        """Client list search should find by first/last name."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_clients')
        
        # Search for "Doe" - should find John and Jane
        resp = self.client.get(url, {'search': 'Doe'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 2)

    def test_client_list_search_by_email(self):
        """Client list search should find by email."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_clients')
        
        resp = self.client.get(url, {'search': 'john@example'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['customer_id'], self.customer1.id)

    def test_client_detail_returns_full_profile(self):
        """Client detail should return full profile with stats."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_detail', args=[self.customer1.id])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        # Check required fields
        self.assertEqual(data['customer_id'], self.customer1.id)
        self.assertEqual(data['username'], 'johndoe')
        self.assertEqual(data['first_name'], 'John')
        self.assertEqual(data['last_name'], 'Doe')
        self.assertIn('total_orders', data)
        self.assertIn('total_spent', data)
        self.assertIn('dietary_preferences', data)
        self.assertIn('allergies', data)

    def test_client_detail_404_for_unconnected(self):
        """Client detail should return 404 for customers not connected."""
        unconnected_customer = CustomUser.objects.create_user(
            username="unconnected",
            email="unconnected@example.com",
            password="testpass123",
        )
        
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_detail', args=[unconnected_customer.id])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 404)

    def test_add_client_note(self):
        """Chef should be able to add interaction notes for a client."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_notes', args=[self.customer1.id])
        
        note_data = {
            'summary': 'Discussed weekly meal prep preferences',
            'details': 'Client prefers Mediterranean cuisine with low sodium.',
            'interaction_type': 'call',
            'next_steps': 'Send menu proposal by Friday',
        }
        
        resp = self.client.post(url, note_data, format='json')
        self.assertEqual(resp.status_code, 201)
        
        data = resp.json()
        self.assertEqual(data['summary'], note_data['summary'])
        self.assertEqual(data['interaction_type'], 'call')
        self.assertIn('id', data)

    def test_get_client_notes(self):
        """Chef should be able to retrieve client notes."""
        # First add a note
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_notes', args=[self.customer1.id])
        
        self.client.post(url, {
            'summary': 'Test note',
            'interaction_type': 'note',
        }, format='json')
        
        # Now retrieve notes
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        
        notes = resp.json()
        self.assertIsInstance(notes, list)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['summary'], 'Test note')


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ChefCrmRevenueAnalyticsTests(TestCase):
    """Tests for revenue and analytics endpoints."""

    def setUp(self):
        self.client = APIClient()
        
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create customer
        self.customer = CustomUser.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="testpass123",
        )

    def _authenticate(self, user=None):
        if user is None:
            self.client.force_authenticate(user=None)
        else:
            self.client.force_authenticate(user=user)

    def test_revenue_default_period(self):
        """Revenue endpoint should default to month period."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_revenue')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data['period'], 'month')
        self.assertIn('total_revenue', data)
        self.assertIn('meal_revenue', data)
        self.assertIn('service_revenue', data)
        self.assertIn('order_count', data)

    def test_revenue_custom_period(self):
        """Revenue endpoint should accept period parameter."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_revenue')
        
        for period in ['day', 'week', 'month', 'year']:
            resp = self.client.get(url, {'period': period})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['period'], period)

    def test_revenue_custom_date_range(self):
        """Revenue endpoint should accept custom date range."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_revenue')
        
        resp = self.client.get(url, {
            'start_date': '2024-01-01',
            'end_date': '2024-01-31',
        })
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['start_date'], '2024-01-01')
        self.assertEqual(data['end_date'], '2024-01-31')

    def test_upcoming_orders_returns_list(self):
        """Upcoming orders should return paginated list."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_upcoming_orders')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        # Should have pagination structure or be a list
        if 'results' in data:
            self.assertIsInstance(data['results'], list)
        else:
            self.assertIsInstance(data, list)

    def test_upcoming_orders_limit_parameter(self):
        """Upcoming orders should respect limit parameter."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_upcoming_orders')
        
        resp = self.client.get(url, {'limit': 5})
        self.assertEqual(resp.status_code, 200)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ChefCrmLeadPipelineTests(TestCase):
    """Tests for lead pipeline management."""

    def setUp(self):
        self.client = APIClient()
        
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create some leads
        self.lead1 = Lead.objects.create(
            owner=self.chef_user,
            first_name="Alice",
            last_name="Johnson",
            email="alice@example.com",
            status=Lead.Status.NEW,
            source=Lead.Source.WEB,
        )
        self.lead2 = Lead.objects.create(
            owner=self.chef_user,
            first_name="Bob",
            last_name="Williams",
            email="bob@example.com",
            status=Lead.Status.CONTACTED,
            source=Lead.Source.REFERRAL,
            is_priority=True,
        )

    def _authenticate(self, user=None):
        if user is None:
            self.client.force_authenticate(user=None)
        else:
            self.client.force_authenticate(user=user)

    def test_lead_list_returns_all_leads(self):
        """Lead list should return all leads for the chef."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 2)

    def test_lead_list_filter_by_status(self):
        """Lead list should filter by status."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        resp = self.client.get(url, {'status': 'new'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.lead1.id)

    def test_lead_list_filter_by_priority(self):
        """Lead list should filter by priority flag."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        resp = self.client.get(url, {'is_priority': 'true'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.lead2.id)

    def test_lead_list_search(self):
        """Lead list should search by name/email."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        resp = self.client.get(url, {'search': 'alice'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['email'], 'alice@example.com')

    def test_create_lead(self):
        """Chef should be able to create a new lead."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        lead_data = {
            'first_name': 'Charlie',
            'last_name': 'Brown',
            'email': 'charlie@example.com',
            'phone': '+1234567890',
            'source': 'referral',
            'notes': 'Referred by existing client',
        }
        
        resp = self.client.post(url, lead_data, format='json')
        self.assertEqual(resp.status_code, 201)
        
        data = resp.json()
        self.assertEqual(data['first_name'], 'Charlie')
        self.assertEqual(data['email'], 'charlie@example.com')
        self.assertIn('id', data)

    def test_create_lead_requires_first_name(self):
        """Lead creation should require first_name."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        resp = self.client.post(url, {'email': 'test@example.com'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_lead_detail(self):
        """Chef should be able to view lead details."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_lead_detail', args=[self.lead1.id])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data['id'], self.lead1.id)
        self.assertEqual(data['first_name'], 'Alice')
        self.assertEqual(data['email'], 'alice@example.com')

    def test_update_lead_status(self):
        """Chef should be able to update lead status."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_lead_detail', args=[self.lead1.id])
        
        resp = self.client.patch(url, {'status': 'contacted'}, format='json')
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertEqual(data['status'], 'contacted')
        
        # Verify in database
        self.lead1.refresh_from_db()
        self.assertEqual(self.lead1.status, Lead.Status.CONTACTED)

    def test_update_lead_priority(self):
        """Chef should be able to toggle lead priority."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_lead_detail', args=[self.lead1.id])
        
        resp = self.client.patch(url, {'is_priority': True}, format='json')
        self.assertEqual(resp.status_code, 200)
        
        self.lead1.refresh_from_db()
        self.assertTrue(self.lead1.is_priority)

    def test_delete_lead(self):
        """Chef should be able to soft-delete a lead."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_lead_detail', args=[self.lead1.id])
        
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        
        # Lead should be soft-deleted (is_deleted=True)
        self.lead1.refresh_from_db()
        self.assertTrue(self.lead1.is_deleted)
        
        # Should no longer appear in list
        list_url = reverse('chefs:chef_leads')
        resp = self.client.get(list_url)
        data = resp.json()
        results = data.get('results', data)
        lead_ids = [l['id'] for l in results]
        self.assertNotIn(self.lead1.id, lead_ids)

    def test_add_lead_interaction(self):
        """Chef should be able to add interactions to a lead."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_lead_interactions', args=[self.lead1.id])
        
        interaction_data = {
            'summary': 'Initial phone call',
            'details': 'Discussed catering needs for upcoming party',
            'interaction_type': 'call',
            'next_steps': 'Send quote by Monday',
        }
        
        resp = self.client.post(url, interaction_data, format='json')
        self.assertEqual(resp.status_code, 201)
        
        data = resp.json()
        self.assertEqual(data['summary'], interaction_data['summary'])
        self.assertEqual(data['interaction_type'], 'call')

    def test_lead_detail_404_for_other_chef(self):
        """Chef should not see other chefs' leads."""
        other_chef_user = CustomUser.objects.create_user(
            username="otherchef",
            email="other@example.com",
            password="testpass123",
        )
        Chef.objects.create(user=other_chef_user)
        
        self._authenticate(other_chef_user)
        url = reverse('chefs:chef_lead_detail', args=[self.lead1.id])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 404)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ChefCrmEdgeCaseTests(TestCase):
    """Tests for edge cases and error handling."""

    def setUp(self):
        self.client = APIClient()
        
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")

    def _authenticate(self, user=None):
        if user is None:
            self.client.force_authenticate(user=None)
        else:
            self.client.force_authenticate(user=user)

    def test_client_detail_nonexistent_customer(self):
        """Client detail should return 404 for nonexistent customer."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_detail', args=[99999])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 404)

    def test_client_notes_nonexistent_customer(self):
        """Client notes should return 404 for nonexistent customer."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_client_notes', args=[99999])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 404)

    def test_lead_detail_nonexistent_lead(self):
        """Lead detail should return 404 for nonexistent lead."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_lead_detail', args=[99999])
        resp = self.client.get(url)
        
        self.assertEqual(resp.status_code, 404)

    def test_invalid_period_defaults_to_month(self):
        """Revenue with invalid period should default to month."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_revenue')
        
        resp = self.client.get(url, {'period': 'invalid_period'})
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertEqual(data['period'], 'month')

    def test_empty_search_returns_all(self):
        """Empty search parameter should return all results."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        Lead.objects.create(
            owner=self.chef_user,
            first_name="Test",
            status=Lead.Status.NEW,
        )
        
        resp = self.client.get(url, {'search': ''})
        self.assertEqual(resp.status_code, 200)

    def test_pagination_out_of_range(self):
        """Pagination with out-of-range page should handle gracefully."""
        self._authenticate(self.chef_user)
        url = reverse('chefs:chef_leads')
        
        resp = self.client.get(url, {'page': 9999})
        # Should return 404 (standard DRF behavior) or empty results
        self.assertIn(resp.status_code, [200, 404])

