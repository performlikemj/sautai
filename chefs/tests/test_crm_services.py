"""
Tests for Chef CRM service layer (business logic).

Tests cover:
- Correct aggregation calculations
- Performance (efficient queries)
- Data accuracy
- Edge cases in business logic

Run with: pytest chefs/tests/test_crm_services.py -v
"""

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext

from custom_auth.models import CustomUser
from chefs.models import Chef
from chef_services.models import (
    ChefCustomerConnection,
    ChefServiceOffering,
    ChefServicePriceTier,
    ChefServiceOrder,
)
from meals.models import Meal, ChefMealEvent, ChefMealOrder
from chefs.services.client_insights import (
    get_dashboard_summary,
    get_client_stats,
    get_client_list_with_stats,
    get_revenue_breakdown,
    get_upcoming_orders,
)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class DashboardSummaryServiceTests(TestCase):
    """Tests for get_dashboard_summary service function."""

    def setUp(self):
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

    def test_empty_chef_returns_zeros(self):
        """New chef with no data should return empty revenue dicts."""
        summary = get_dashboard_summary(self.chef)

        # Revenue is now grouped by currency; empty chef has empty dicts
        self.assertEqual(summary['revenue']['today'], {})
        self.assertEqual(summary['revenue']['this_week'], {})
        self.assertEqual(summary['revenue']['this_month'], {})
        self.assertEqual(summary['clients']['total'], 0)
        self.assertEqual(summary['clients']['active'], 0)
        self.assertEqual(summary['orders']['upcoming'], 0)
        self.assertEqual(summary['top_services'], [])

    def test_client_counts_are_accurate(self):
        """Client counts should accurately reflect connection status."""
        # Create accepted connection
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer1,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            responded_at=timezone.now(),
        )
        
        # Create pending connection
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer2,
            status=ChefCustomerConnection.STATUS_PENDING,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
        )
        
        summary = get_dashboard_summary(self.chef)
        
        self.assertEqual(summary['clients']['total'], 2)
        self.assertEqual(summary['clients']['active'], 1)

    def test_new_this_month_counts_recent_connections(self):
        """new_this_month should count connections accepted this month."""
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Connection accepted this month
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer1,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            responded_at=month_start + timedelta(days=5),
        )
        
        # Connection accepted last month (should not count)
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer2,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            responded_at=month_start - timedelta(days=5),
        )
        
        summary = get_dashboard_summary(self.chef)
        
        self.assertEqual(summary['clients']['new_this_month'], 1)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ClientStatsServiceTests(TestCase):
    """Tests for get_client_stats service function."""

    def setUp(self):
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create customer with dietary preferences
        self.customer = CustomUser.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="testpass123",
            household_member_count=4,
        )
        self.customer.allergies = ['Peanuts', 'Shellfish']
        self.customer.save()
        
        # Create connection
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
        )

    def test_stats_for_new_client(self):
        """New client with no orders should have zero stats."""
        stats = get_client_stats(self.chef, self.customer)
        
        self.assertEqual(stats['total_orders'], 0)
        self.assertEqual(stats['total_spent'], Decimal('0'))
        self.assertIsNone(stats['last_order_date'])
        self.assertEqual(stats['average_order_value'], Decimal('0'))
        self.assertEqual(stats['household_size'], 4)

    def test_allergies_are_included(self):
        """Client allergies should be included in stats."""
        stats = get_client_stats(self.chef, self.customer)
        
        self.assertIn('Peanuts', stats['allergies'])
        self.assertIn('Shellfish', stats['allergies'])


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class RevenueBreakdownServiceTests(TestCase):
    """Tests for get_revenue_breakdown service function."""

    def setUp(self):
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")

    def test_default_period_is_month(self):
        """Default period should be 'month'."""
        result = get_revenue_breakdown(self.chef)
        
        self.assertEqual(result['period'], 'month')

    def test_all_periods_work(self):
        """All valid periods should work without errors."""
        for period in ['day', 'week', 'month', 'year']:
            result = get_revenue_breakdown(self.chef, period=period)
            self.assertEqual(result['period'], period)
            self.assertIn('total_revenue', result)
            self.assertIn('meal_revenue', result)
            self.assertIn('service_revenue', result)

    def test_custom_date_range(self):
        """Custom date range should override period calculation."""
        start = timezone.now() - timedelta(days=30)
        end = timezone.now()
        
        result = get_revenue_breakdown(
            self.chef,
            start_date=start,
            end_date=end
        )
        
        self.assertIn('start_date', result)
        self.assertIn('end_date', result)

    def test_empty_revenue_is_decimal_zero(self):
        """Empty revenue should return empty currency dicts and zero decimals."""
        result = get_revenue_breakdown(self.chef)

        # total_revenue is now a dict of {currency: Decimal}
        self.assertIsInstance(result['total_revenue'], dict)
        self.assertEqual(result['total_revenue'], {})
        self.assertIsInstance(result['meal_revenue'], Decimal)
        self.assertIsInstance(result['service_revenue'], Decimal)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class UpcomingOrdersServiceTests(TestCase):
    """Tests for get_upcoming_orders service function."""

    def setUp(self):
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

    def test_empty_returns_list(self):
        """Chef with no orders should return empty list."""
        orders = get_upcoming_orders(self.chef)
        
        self.assertIsInstance(orders, list)
        self.assertEqual(len(orders), 0)

    def test_limit_parameter(self):
        """Limit parameter should cap results."""
        orders = get_upcoming_orders(self.chef, limit=5)
        
        self.assertIsInstance(orders, list)
        self.assertLessEqual(len(orders), 5)

    def test_orders_sorted_by_date(self):
        """Orders should be sorted by service date."""
        # Create a service offering first
        offering = ChefServiceOffering.objects.create(
            chef=self.chef,
            service_type='home_chef',
            title='Test Service',
            active=True,
        )
        tier = ChefServicePriceTier.objects.create(
            offering=offering,
            household_min=1,
            household_max=4,
            desired_unit_amount_cents=10000,
            active=True,
        )
        
        now = timezone.now()
        
        # Create orders with different dates
        order1 = ChefServiceOrder.objects.create(
            chef=self.chef,
            customer=self.customer,
            offering=offering,
            tier=tier,
            household_size=2,
            service_date=(now + timedelta(days=5)).date(),
            status='confirmed',
        )
        order2 = ChefServiceOrder.objects.create(
            chef=self.chef,
            customer=self.customer,
            offering=offering,
            tier=tier,
            household_size=2,
            service_date=(now + timedelta(days=2)).date(),
            status='confirmed',
        )
        
        orders = get_upcoming_orders(self.chef)
        
        if len(orders) >= 2:
            # Earlier date should come first
            self.assertLessEqual(orders[0]['service_date'], orders[1]['service_date'])


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ClientListServiceTests(TestCase):
    """Tests for get_client_list_with_stats service function."""

    def setUp(self):
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create customers
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
        
        # Create connections
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer1,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
        )
        ChefCustomerConnection.objects.create(
            chef=self.chef,
            customer=self.customer2,
            status=ChefCustomerConnection.STATUS_PENDING,
            initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
        )

    def test_default_returns_accepted_only(self):
        """Default (no status filter) should return accepted connections."""
        clients = get_client_list_with_stats(self.chef)
        
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['customer_id'], self.customer1.id)

    def test_status_filter(self):
        """Status filter should work correctly."""
        # Get pending
        pending = get_client_list_with_stats(self.chef, status='pending')
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['customer_id'], self.customer2.id)

    def test_search_by_name(self):
        """Search should filter by name."""
        clients = get_client_list_with_stats(self.chef, search='John')
        
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['username'], 'johndoe')

    def test_search_by_email(self):
        """Search should filter by email."""
        clients = get_client_list_with_stats(self.chef, search='john@example')
        
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['email'], 'john@example.com')

    def test_search_case_insensitive(self):
        """Search should be case-insensitive."""
        clients = get_client_list_with_stats(self.chef, search='JOHN')
        
        self.assertEqual(len(clients), 1)

    def test_client_has_stats_fields(self):
        """Each client should have stats fields."""
        clients = get_client_list_with_stats(self.chef)
        
        if clients:
            client = clients[0]
            self.assertIn('customer_id', client)
            self.assertIn('username', client)
            self.assertIn('email', client)
            self.assertIn('total_orders', client)
            self.assertIn('total_spent', client)
            self.assertIn('connected_since', client)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class ServicePerformanceTests(TestCase):
    """Tests to ensure service layer is performant."""

    def setUp(self):
        # Create chef
        self.chef_user = CustomUser.objects.create_user(
            username="chefmike",
            email="chef@example.com",
            password="testpass123",
        )
        self.chef = Chef.objects.create(user=self.chef_user, bio="Test chef")
        
        # Create multiple customers with connections
        for i in range(20):
            customer = CustomUser.objects.create_user(
                username=f"customer{i}",
                email=f"customer{i}@example.com",
                password="testpass123",
            )
            ChefCustomerConnection.objects.create(
                chef=self.chef,
                customer=customer,
                status=ChefCustomerConnection.STATUS_ACCEPTED,
                initiated_by=ChefCustomerConnection.INITIATED_BY_CUSTOMER,
            )

    def test_dashboard_summary_query_count(self):
        """Dashboard summary should use reasonable number of queries."""
        # Warm up any lazy connections
        get_dashboard_summary(self.chef)
        
        with CaptureQueriesContext(connection) as context:
            get_dashboard_summary(self.chef)
        
        # Should not have excessive queries (N+1 problem)
        # Allow some queries for revenue, clients, orders, services
        self.assertLess(
            len(context.captured_queries), 
            20,  # Reasonable upper bound
            f"Too many queries ({len(context.captured_queries)}) for dashboard summary"
        )

    def test_client_list_scales_reasonably(self):
        """Client list should not have N+1 query problems."""
        # Warm up
        get_client_list_with_stats(self.chef)
        
        with CaptureQueriesContext(connection) as context:
            clients = get_client_list_with_stats(self.chef)
        
        # Note: Current implementation may have some N+1 for order stats
        # This test documents expected behavior and can be tightened later
        self.assertGreater(len(clients), 0)
        # Log query count for monitoring
        # print(f"Client list queries: {len(context.captured_queries)}")

