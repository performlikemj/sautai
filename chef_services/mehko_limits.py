"""MEHKO meal cap and revenue cap enforcement utilities."""
from datetime import timedelta
from django.utils import timezone

from chefs.constants import MEHKO_DAILY_MEAL_CAP, MEHKO_WEEKLY_MEAL_CAP


COUNTABLE_STATUSES = ('confirmed', 'completed')


def get_daily_order_count(chef, date=None):
    """Count orders for a chef on a given date."""
    from chef_services.models import ChefServiceOrder
    if date is None:
        date = timezone.now().date()
    return ChefServiceOrder.objects.filter(
        chef=chef,
        service_date=date,
        status__in=COUNTABLE_STATUSES,
    ).count()


def get_weekly_order_count(chef, date=None):
    """Count orders for a chef in the Mon-Sun week containing the given date."""
    from chef_services.models import ChefServiceOrder
    if date is None:
        date = timezone.now().date()
    # Monday of this week
    monday = date - timedelta(days=date.weekday())
    sunday = monday + timedelta(days=6)
    return ChefServiceOrder.objects.filter(
        chef=chef,
        service_date__gte=monday,
        service_date__lte=sunday,
        status__in=COUNTABLE_STATUSES,
    ).count()


def check_meal_cap(chef, date=None):
    """
    Check if a MEHKO chef can accept another order.
    Returns dict with allowed status and counts.
    Only enforced for mehko_active chefs.
    """
    if not getattr(chef, 'mehko_active', False):
        return {
            'allowed': True,
            'enforced': False,
            'daily_count': 0,
            'daily_remaining': None,
            'weekly_count': 0,
            'weekly_remaining': None,
        }

    daily = get_daily_order_count(chef, date)
    weekly = get_weekly_order_count(chef, date)

    daily_remaining = max(0, MEHKO_DAILY_MEAL_CAP - daily)
    weekly_remaining = max(0, MEHKO_WEEKLY_MEAL_CAP - weekly)
    allowed = daily_remaining > 0 and weekly_remaining > 0

    return {
        'allowed': allowed,
        'enforced': True,
        'daily_count': daily,
        'daily_remaining': daily_remaining,
        'weekly_count': weekly,
        'weekly_remaining': weekly_remaining,
    }
