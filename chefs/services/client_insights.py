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
from chefs.models import ChefPaymentLink
from chefs.api.payment_links import ZERO_DECIMAL_CURRENCIES
from meals.models import ChefMealEvent, ChefMealOrder

logger = logging.getLogger(__name__)


def _sum_payment_links_by_currency(chef, date_filter):
    """Return {currency: Decimal amount} dict for paid payment links."""
    links = ChefPaymentLink.objects.filter(
        chef=chef, status=ChefPaymentLink.Status.PAID, **date_filter
    ).values_list('amount_cents', 'currency')
    by_currency = {}
    for amount_cents, currency in links:
        cur = (currency or 'usd').lower()
        amount = Decimal(amount_cents) if cur in ZERO_DECIMAL_CURRENCIES else Decimal(amount_cents) / 100
        by_currency[cur] = by_currency.get(cur, Decimal('0')) + amount
    return by_currency


def _merge_revenue(usd_amount, payment_link_by_currency):
    """Merge USD meal/service revenue with per-currency payment link revenue."""
    result = dict(payment_link_by_currency)
    result['usd'] = result.get('usd', Decimal('0')) + usd_amount
    # Remove zero entries
    return {k: v for k, v in result.items() if v}


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


def _calculate_revenue(chef, today_start, week_start, month_start) -> dict[str, dict[str, Decimal]]:
    """Calculate revenue grouped by currency from all order types."""

    def sum_usd_revenue(date_filter):
        """Sum meal + service revenue (always USD)."""
        meal = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            status__in=['confirmed', 'completed'],
            **date_filter
        ).aggregate(
            total=Coalesce(Sum(F('price_paid') * F('quantity')), Decimal('0'))
        )['total'] or Decimal('0')

        service_cents = ChefServiceOrder.objects.filter(
            chef=chef,
            status__in=['confirmed', 'completed'],
            **date_filter
        ).aggregate(
            total=Coalesce(Sum('tier__desired_unit_amount_cents'), 0)
        )['total'] or 0

        return meal + Decimal(service_cents) / 100

    def get_period_revenue(date_filter):
        usd = sum_usd_revenue(date_filter)
        # Payment links use paid_at, not created_at
        pl_filter = {k.replace('created_at', 'paid_at'): v for k, v in date_filter.items()}
        by_currency = _sum_payment_links_by_currency(chef, pl_filter)
        return _merge_revenue(usd, by_currency)

    return {
        "today": get_period_revenue({'created_at__gte': today_start}),
        "this_week": get_period_revenue({'created_at__gte': week_start}),
        "this_month": get_period_revenue({'created_at__gte': month_start}),
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

    # Payment link revenue (grouped by currency)
    payment_link_count = ChefPaymentLink.objects.filter(
        chef=chef,
        status=ChefPaymentLink.Status.PAID,
        paid_at__gte=start_date,
        paid_at__lte=end_date
    ).count()
    payment_link_by_currency = _sum_payment_links_by_currency(
        chef, {'paid_at__gte': start_date, 'paid_at__lte': end_date}
    )

    # USD totals (meal + service + USD payment links)
    usd_revenue = meal_revenue + service_revenue
    total_count = meal_count + service_count + payment_link_count

    # Revenue grouped by currency
    by_currency = _merge_revenue(usd_revenue, payment_link_by_currency)

    return {
        "period": period,
        "start_date": start_date.date() if hasattr(start_date, 'date') else start_date,
        "end_date": end_date.date() if hasattr(end_date, 'date') else end_date,
        "total_revenue": by_currency,
        "meal_revenue": meal_revenue,
        "service_revenue": service_revenue,
        "payment_link_revenue": payment_link_by_currency,
        "order_count": total_count,
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
    
    # Get payment link revenue by day (per-currency)
    payment_links = (
        ChefPaymentLink.objects
        .filter(
            chef=chef,
            status=ChefPaymentLink.Status.PAID,
            paid_at__gte=start_date,
            paid_at__lte=end_date
        )
        .annotate(day=TruncDate('paid_at'))
        .values_list('day', 'amount_cents', 'currency')
    )

    # Combine into dicts by date: {date: {currency: amount}}
    revenue_by_date = {}       # {date_str: {currency: float}}
    for item in meal_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            revenue_by_date.setdefault(date_str, {})
            revenue_by_date[date_str]['usd'] = revenue_by_date[date_str].get('usd', 0) + float(item['total'] or 0)

    for item in service_by_day:
        if item['day']:
            date_str = item['day'].strftime('%Y-%m-%d')
            revenue_by_date.setdefault(date_str, {})
            cents = item['total'] or 0
            revenue_by_date[date_str]['usd'] = revenue_by_date[date_str].get('usd', 0) + (cents / 100)

    for day, amount_cents, currency in payment_links:
        if day:
            date_str = day.strftime('%Y-%m-%d')
            cur = (currency or 'usd').lower()
            amount = float(amount_cents) if cur in ZERO_DECIMAL_CURRENCIES else float(amount_cents) / 100
            revenue_by_date.setdefault(date_str, {})
            revenue_by_date[date_str][cur] = revenue_by_date[date_str].get(cur, 0) + amount

    # Generate all days in range with by_currency data
    return _fill_date_range_by_currency(start_date, days, revenue_by_date)


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
    
    # Get payment link count by day
    from chefs.models import ChefPaymentLink
    payment_link_by_day = (
        ChefPaymentLink.objects
        .filter(
            chef=chef,
            status=ChefPaymentLink.Status.PAID,
            paid_at__gte=start_date,
            paid_at__lte=end_date
        )
        .annotate(day=TruncDate('paid_at'))
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

    for item in payment_link_by_day:
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


def _date_label(current_date, days):
    if days <= 7:
        return current_date.strftime('%a')
    return current_date.strftime('%b %d')


def _fill_date_range(start_date, days: int, data_by_date: dict) -> list[dict]:
    """Fill in all dates in range, using 0 for missing days."""
    results = []
    for i in range(days):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime('%Y-%m-%d')
        results.append({
            'date': date_str,
            'value': data_by_date.get(date_str, 0),
            'label': _date_label(current_date, days)
        })
    return results


def _fill_date_range_by_currency(start_date, days: int, data_by_date: dict) -> list[dict]:
    """Fill in all dates with per-currency revenue breakdown."""
    results = []
    for i in range(days):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime('%Y-%m-%d')
        by_currency = data_by_date.get(date_str, {})
        results.append({
            'date': date_str,
            'by_currency': by_currency,
            'label': _date_label(current_date, days)
        })
    return results