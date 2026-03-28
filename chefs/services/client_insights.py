"""
Client insights service for Chef CRM Dashboard.

Provides aggregated statistics and analytics for:
- Dashboard summary (revenue, clients, orders)
- Per-client stats (orders, spend, preferences)
- Revenue breakdowns by period
- Upcoming orders compilation
"""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Sum, Count, Q, F, Avg
from django.db.models.functions import Coalesce
from django.utils import timezone

from chef_services.models import (
    ChefCustomerConnection,
    ChefServiceOrder,
    ChefServiceOffering,
)
from meals.models import ChefMealEvent, ChefMealOrder

logger = logging.getLogger(__name__)


def get_dashboard_summary(chef) -> dict[str, Any]:
    """
    Aggregate dashboard stats for a chef.
    
    Returns:
        {
            "revenue": {"today": Decimal, "this_week": Decimal, "this_month": Decimal},
            "clients": {"total": int, "active": int, "new_this_month": int},
            "orders": {"upcoming": int, "pending_confirmation": int, "completed_this_month": int},
            "top_services": [{"id": int, "name": str, "order_count": int}]
        }
    """
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    
    # Revenue calculations
    revenue = _calculate_revenue(chef, today_start, week_start, month_start)
    
    # Client stats
    clients = _calculate_client_stats(chef, month_start)
    
    # Order stats
    orders = _calculate_order_stats(chef, month_start, now)
    
    # Top services
    top_services = _get_top_services(chef, limit=5)
    
    return {
        "revenue": revenue,
        "clients": clients,
        "orders": orders,
        "top_services": top_services,
    }


def _calculate_revenue(chef, today_start, week_start, month_start) -> dict[str, Decimal]:
    """Calculate revenue from both ChefMealOrders and ChefServiceOrders."""
    
    def sum_meal_revenue(date_filter):
        result = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            status__in=['confirmed', 'completed'],
            **date_filter
        ).aggregate(
            total=Coalesce(Sum(F('price_paid') * F('quantity')), Decimal('0'))
        )
        return result['total'] or Decimal('0')

    def sum_service_revenue(date_filter):
        result = ChefServiceOrder.objects.filter(
            chef=chef,
            status__in=['confirmed', 'completed'],
            **date_filter
        ).aggregate(
            total=Coalesce(Sum('tier__desired_unit_amount_cents'), 0)
        )
        # Convert cents to dollars
        cents = result['total'] or 0
        return Decimal(cents) / 100
    
    return {
        "today": sum_meal_revenue({'created_at__gte': today_start}) + sum_service_revenue({'created_at__gte': today_start}),
        "this_week": sum_meal_revenue({'created_at__gte': week_start}) + sum_service_revenue({'created_at__gte': week_start}),
        "this_month": sum_meal_revenue({'created_at__gte': month_start}) + sum_service_revenue({'created_at__gte': month_start}),
    }


def _calculate_client_stats(chef, month_start) -> dict[str, int]:
    """Calculate client connection stats."""
    connections = ChefCustomerConnection.objects.filter(chef=chef)
    
    total = connections.count()
    active = connections.filter(status=ChefCustomerConnection.STATUS_ACCEPTED).count()
    new_this_month = connections.filter(
        status=ChefCustomerConnection.STATUS_ACCEPTED,
        responded_at__gte=month_start
    ).count()
    
    return {
        "total": total,
        "active": active,
        "new_this_month": new_this_month,
    }


def _calculate_order_stats(chef, month_start, now) -> dict[str, int]:
    """Calculate order stats from both order types."""
    
    # Upcoming meal events
    upcoming_meal_orders = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        meal_event__event_date__gte=now.date(),
        status__in=['placed', 'confirmed']
    ).count()
    
    # Upcoming service orders
    upcoming_service_orders = ChefServiceOrder.objects.filter(
        chef=chef,
        service_date__gte=now.date(),
        status__in=['draft', 'awaiting_payment', 'confirmed']
    ).count()
    
    # Pending confirmation (awaiting payment or placed)
    pending_meal = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        status='placed'
    ).count()
    pending_service = ChefServiceOrder.objects.filter(
        chef=chef,
        status='awaiting_payment'
    ).count()
    
    # Completed this month
    completed_meal = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        status='completed',
        updated_at__gte=month_start
    ).count()
    completed_service = ChefServiceOrder.objects.filter(
        chef=chef,
        status='completed',
        updated_at__gte=month_start
    ).count()
    
    return {
        "upcoming": upcoming_meal_orders + upcoming_service_orders,
        "pending_confirmation": pending_meal + pending_service,
        "completed_this_month": completed_meal + completed_service,
    }


def _get_top_services(chef, limit: int = 5) -> list[dict[str, Any]]:
    """Get top services by order count."""
    top = (
        ChefServiceOffering.objects
        .filter(chef=chef, active=True)
        .annotate(order_count=Count('orders', filter=Q(orders__status='confirmed')))
        .order_by('-order_count')[:limit]
    )
    return [
        {"id": s.id, "name": s.title, "service_type": s.service_type, "order_count": s.order_count}
        for s in top
    ]


def get_client_stats(chef, customer) -> dict[str, Any]:
    """
    Aggregate stats for a single client.
    
    Returns:
        {
            "total_orders": int,
            "total_spent": Decimal,
            "last_order_date": datetime | None,
            "average_order_value": Decimal,
            "favorite_services": [{"id": int, "name": str, "order_count": int}],
            "dietary_preferences": [str],
            "allergies": [str],
            "household_size": int,
        }
    """
    # Meal orders from this customer to this chef
    meal_orders = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        customer=customer,
        status__in=['confirmed', 'completed']
    )
    
    # Service orders from this customer to this chef
    service_orders = ChefServiceOrder.objects.filter(
        chef=chef,
        customer=customer,
        status__in=['confirmed', 'completed']
    )
    
    # Total orders
    total_orders = meal_orders.count() + service_orders.count()
    
    # Total spent
    meal_spent = meal_orders.aggregate(
        total=Coalesce(Sum(F('price_paid') * F('quantity')), Decimal('0'))
    )['total'] or Decimal('0')
    
    service_spent_cents = service_orders.aggregate(
        total=Coalesce(Sum('tier__desired_unit_amount_cents'), 0)
    )['total'] or 0
    service_spent = Decimal(service_spent_cents) / 100
    
    total_spent = meal_spent + service_spent
    
    # Last order date
    last_meal = meal_orders.order_by('-created_at').values_list('created_at', flat=True).first()
    last_service = service_orders.order_by('-created_at').values_list('created_at', flat=True).first()
    
    last_order_date = None
    if last_meal and last_service:
        last_order_date = max(last_meal, last_service)
    elif last_meal:
        last_order_date = last_meal
    elif last_service:
        last_order_date = last_service
    
    # Average order value
    average_order_value = total_spent / total_orders if total_orders > 0 else Decimal('0')
    
    # Favorite services
    favorite_services = (
        ChefServiceOffering.objects
        .filter(chef=chef, orders__customer=customer, orders__status__in=['confirmed', 'completed'])
        .annotate(order_count=Count('orders'))
        .order_by('-order_count')[:3]
    )
    favorite_services_list = [
        {"id": s.id, "name": s.title, "order_count": s.order_count}
        for s in favorite_services
    ]
    
    # Customer preferences
    dietary_preferences = list(customer.dietary_preferences.values_list('name', flat=True))
    allergies = customer.allergies if hasattr(customer, 'allergies') else []
    household_size = getattr(customer, 'household_member_count', 1)
    
    return {
        "total_orders": total_orders,
        "total_spent": total_spent,
        "last_order_date": last_order_date,
        "average_order_value": average_order_value,
        "favorite_services": favorite_services_list,
        "dietary_preferences": dietary_preferences,
        "allergies": allergies if isinstance(allergies, list) else [],
        "household_size": household_size,
    }


def get_client_list_with_stats(chef, search: Optional[str] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Get list of clients with aggregated stats for list view.
    
    Args:
        chef: Chef instance
        search: Optional search term for customer username/email
        status: Optional status filter ('accepted', 'pending', 'ended')
    
    Returns:
        List of client dicts with basic stats
    """
    connections = ChefCustomerConnection.objects.filter(chef=chef).select_related('customer')
    
    if status:
        connections = connections.filter(status=status)
    else:
        # Default: show accepted connections
        connections = connections.filter(status=ChefCustomerConnection.STATUS_ACCEPTED)
    
    if search:
        connections = connections.filter(
            Q(customer__username__icontains=search) |
            Q(customer__email__icontains=search) |
            Q(customer__first_name__icontains=search) |
            Q(customer__last_name__icontains=search)
        )
    
    results = []
    for conn in connections:
        customer = conn.customer
        
        # Quick stats (optimized - could be further optimized with annotate if needed)
        meal_count = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            customer=customer,
            status__in=['confirmed', 'completed']
        ).count()
        
        service_count = ChefServiceOrder.objects.filter(
            chef=chef,
            customer=customer,
            status__in=['confirmed', 'completed']
        ).count()
        
        # Total spent
        meal_spent = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            customer=customer,
            status__in=['confirmed', 'completed']
        ).aggregate(
            total=Coalesce(Sum(F('price_paid') * F('quantity')), Decimal('0'))
        )['total'] or Decimal('0')
        
        service_spent_cents = ChefServiceOrder.objects.filter(
            chef=chef,
            customer=customer,
            status__in=['confirmed', 'completed']
        ).aggregate(
            total=Coalesce(Sum('tier__desired_unit_amount_cents'), 0)
        )['total'] or 0
        
        total_spent = meal_spent + Decimal(service_spent_cents) / 100
        
        results.append({
            "customer_id": customer.id,
            "username": customer.username,
            "email": customer.email,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "connection_status": conn.status,
            "connected_since": conn.responded_at or conn.requested_at,
            "total_orders": meal_count + service_count,
            "total_spent": total_spent,
        })
    
    return results


def get_revenue_breakdown(
    chef,
    period: str = 'month',
    start_date=None,
    end_date=None
) -> dict[str, Any]:
    """
    Get revenue breakdown by period.
    
    Args:
        chef: Chef instance
        period: 'day', 'week', 'month', 'year'
        start_date: Optional start date
        end_date: Optional end date
    
    Returns:
        {
            "period": str,
            "start_date": date,
            "end_date": date,
            "total_revenue": Decimal,
            "meal_revenue": Decimal,
            "service_revenue": Decimal,
            "order_count": int,
            "average_order_value": Decimal,
        }
    """
    now = timezone.now()
    
    if not end_date:
        end_date = now
    
    if not start_date:
        if period == 'day':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = now - timedelta(days=now.weekday())
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == 'year':
            start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = now - timedelta(days=30)
    
    # Meal orders revenue
    meal_data = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        status__in=['confirmed', 'completed'],
        created_at__gte=start_date,
        created_at__lte=end_date
    ).aggregate(
        total=Coalesce(Sum(F('price_paid') * F('quantity')), Decimal('0')),
        count=Count('id')
    )
    meal_revenue = meal_data['total'] or Decimal('0')
    meal_count = meal_data['count'] or 0
    
    # Service orders revenue
    service_data = ChefServiceOrder.objects.filter(
        chef=chef,
        status__in=['confirmed', 'completed'],
        created_at__gte=start_date,
        created_at__lte=end_date
    ).aggregate(
        total=Coalesce(Sum('tier__desired_unit_amount_cents'), 0),
        count=Count('id')
    )
    service_revenue = Decimal(service_data['total'] or 0) / 100
    service_count = service_data['count'] or 0
    
    total_revenue = meal_revenue + service_revenue
    total_count = meal_count + service_count
    average_order_value = total_revenue / total_count if total_count > 0 else Decimal('0')
    
    return {
        "period": period,
        "start_date": start_date.date() if hasattr(start_date, 'date') else start_date,
        "end_date": end_date.date() if hasattr(end_date, 'date') else end_date,
        "total_revenue": total_revenue,
        "meal_revenue": meal_revenue,
        "service_revenue": service_revenue,
        "order_count": total_count,
        "average_order_value": average_order_value,
    }


def get_upcoming_orders(chef, limit: int = 20) -> list[dict[str, Any]]:
    """
    Get upcoming orders (both meal events and service orders).
    
    Returns list of orders sorted by date, with unified structure.
    """
    now = timezone.now()
    results = []
    
    # Upcoming meal orders
    meal_orders = (
        ChefMealOrder.objects
        .filter(
            meal_event__chef=chef,
            meal_event__event_date__gte=now.date(),
            status__in=['placed', 'confirmed']
        )
        .select_related('meal_event', 'meal_event__meal', 'customer')
        .order_by('meal_event__event_date', 'meal_event__event_time')[:limit]
    )
    
    for order in meal_orders:
        results.append({
            "order_type": "meal_event",
            "order_id": order.id,
            "customer_id": order.customer_id,
            "customer_username": order.customer.username,
            "customer_name": f"{order.customer.first_name} {order.customer.last_name}".strip() or order.customer.username,
            "service_date": order.meal_event.event_date,
            "service_time": order.meal_event.event_time,
            "service_name": order.meal_event.meal.name if order.meal_event.meal else "Meal Event",
            "status": order.status,
            "quantity": order.quantity,
            "price": order.price_paid,
        })
    
    # Upcoming service orders
    service_orders = (
        ChefServiceOrder.objects
        .filter(
            chef=chef,
            service_date__gte=now.date(),
            status__in=['draft', 'awaiting_payment', 'confirmed']
        )
        .select_related('offering', 'tier', 'customer')
        .order_by('service_date', 'service_start_time')[:limit]
    )
    
    for order in service_orders:
        results.append({
            "order_type": "service",
            "order_id": order.id,
            "customer_id": order.customer_id,
            "customer_username": order.customer.username,
            "customer_name": f"{order.customer.first_name} {order.customer.last_name}".strip() or order.customer.username,
            "service_date": order.service_date,
            "service_time": order.service_start_time,
            "service_name": order.offering.title if order.offering else "Service",
            "status": order.status,
            "quantity": 1,
            "price": Decimal(order.tier.desired_unit_amount_cents) / 100 if order.tier else Decimal('0'),
        })
    
    # Sort by date and time
    results.sort(key=lambda x: (x['service_date'] or now.date(), x['service_time'] or now.time()))
    
    return results[:limit]


def get_analytics_time_series(chef, metric: str, days: int = 30) -> list[dict[str, Any]]:
    """
    Generate time-series data for analytics charts.
    
    Args:
        chef: Chef instance
        metric: 'revenue', 'orders', or 'clients'
        days: Number of days to include (7, 30, 90, 365)
    
    Returns:
        List of daily data points:
        [{"date": "2025-12-01", "value": 150.00, "label": "Dec 1"}, ...]
    """
    now = timezone.now()
    end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_date = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    if metric == 'revenue':
        return _get_revenue_time_series(chef, start_date, end_date, days)
    elif metric == 'orders':
        return _get_orders_time_series(chef, start_date, end_date, days)
    elif metric == 'clients':
        return _get_clients_time_series(chef, start_date, end_date, days)
    else:
        logger.warning(f"Unknown analytics metric: {metric}")
        return []


def _get_revenue_time_series(chef, start_date, end_date, days: int) -> list[dict]:
    """Generate daily revenue data points."""
    from django.db.models.functions import TruncDate
    
    # Get meal order revenue by day
    meal_by_day = (
        ChefMealOrder.objects
        .filter(
            meal_event__chef=chef,
            status__in=['confirmed', 'completed'],
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum(F('price_paid') * F('quantity')))
        .order_by('day')
    )
    
    # Get service order revenue by day
    service_by_day = (
        ChefServiceOrder.objects
        .filter(
            chef=chef,
            status__in=['confirmed', 'completed'],
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('tier__desired_unit_amount_cents'))
        .order_by('day')
    )
    
    # Combine into a dict by date
    revenue_by_date = {}
    for item in meal_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            revenue_by_date[date_str] = float(item['total'] or 0)
    
    for item in service_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            cents = item['total'] or 0
            revenue_by_date[date_str] = revenue_by_date.get(date_str, 0) + (cents / 100)
    
    # Generate all days in range
    return _fill_date_range(start_date, days, revenue_by_date)


def _get_orders_time_series(chef, start_date, end_date, days: int) -> list[dict]:
    """Generate daily order count data points."""
    from django.db.models.functions import TruncDate
    
    # Get meal order count by day
    meal_by_day = (
        ChefMealOrder.objects
        .filter(
            meal_event__chef=chef,
            status__in=['confirmed', 'completed'],
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    
    # Get service order count by day
    service_by_day = (
        ChefServiceOrder.objects
        .filter(
            chef=chef,
            status__in=['confirmed', 'completed'],
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    
    # Combine into a dict by date
    orders_by_date = {}
    for item in meal_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            orders_by_date[date_str] = item['count'] or 0
    
    for item in service_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            orders_by_date[date_str] = orders_by_date.get(date_str, 0) + (item['count'] or 0)
    
    return _fill_date_range(start_date, days, orders_by_date)


def _get_clients_time_series(chef, start_date, end_date, days: int) -> list[dict]:
    """Generate daily new client count data points."""
    from django.db.models.functions import TruncDate
    
    # Get new accepted connections by day
    connections_by_day = (
        ChefCustomerConnection.objects
        .filter(
            chef=chef,
            status=ChefCustomerConnection.STATUS_ACCEPTED,
            responded_at__gte=start_date,
            responded_at__lte=end_date
        )
        .annotate(day=TruncDate('responded_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    
    clients_by_date = {}
    for item in connections_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            clients_by_date[date_str] = item['count'] or 0
    
    return _fill_date_range(start_date, days, clients_by_date)


def _fill_date_range(start_date, days: int, data_by_date: dict) -> list[dict]:
    """Fill in all dates in range, using 0 for missing days."""
    results = []
    
    for i in range(days):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Format label based on range
        if days <= 7:
            label = current_date.strftime('%a')  # Mon, Tue, etc.
        elif days <= 31:
            label = current_date.strftime('%b %d')  # Dec 19
        else:
            label = current_date.strftime('%b %d')  # Dec 19
        
        results.append({
            'date': date_str,
            'value': data_by_date.get(date_str, 0),
            'label': label
        })
    
    return results