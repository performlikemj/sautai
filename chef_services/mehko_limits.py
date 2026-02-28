"""MEHKO meal cap and revenue cap enforcement utilities."""
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum


def _get_caps():
    """Get current MEHKO caps from config model (falls back to statutory defaults)."""
    from chefs.models import MehkoConfig
    config = MehkoConfig.get_current()
    return config.daily_meal_cap, config.weekly_meal_cap, config.annual_revenue_cap


# For meal caps: count all non-cancelled orders (including draft/awaiting_payment)
# to prevent race conditions where concurrent requests both pass the check.
# The statute limits meals "prepared", so we count from creation, not payment.
COUNTABLE_STATUSES_MEAL_CAP = ('draft', 'awaiting_payment', 'confirmed', 'completed')

# For revenue: only count actual completed sales ("gross sales" per statute)
COUNTABLE_STATUSES_REVENUE = ('completed',)


def get_daily_order_count(chef, date=None):
    """Count orders for a chef on a given date."""
    from chef_services.models import ChefServiceOrder
    if date is None:
        date = timezone.now().date()
    return ChefServiceOrder.objects.filter(
        chef=chef,
        service_date=date,
        status__in=COUNTABLE_STATUSES_MEAL_CAP,
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
        status__in=COUNTABLE_STATUSES_MEAL_CAP,
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

    daily_cap, weekly_cap, _ = _get_caps()
    daily = get_daily_order_count(chef, date)
    weekly = get_weekly_order_count(chef, date)

    daily_remaining = max(0, daily_cap - daily)
    weekly_remaining = max(0, weekly_cap - weekly)
    allowed = daily_remaining > 0 and weekly_remaining > 0

    return {
        'allowed': allowed,
        'enforced': True,
        'daily_count': daily,
        'daily_remaining': daily_remaining,
        'weekly_count': weekly,
        'weekly_remaining': weekly_remaining,
    }


def get_annual_revenue(chef):
    """
    Sum completed order revenue for a MEHKO chef in rolling 12 months.
    Uses tier's desired_unit_amount_cents from confirmed/completed orders.
    Returns Decimal in dollars.
    """
    from chef_services.models import ChefServiceOrder
    from dateutil.relativedelta import relativedelta

    cutoff = timezone.now().date() - relativedelta(months=12)
    result = ChefServiceOrder.objects.filter(
        chef=chef,
        status__in=COUNTABLE_STATUSES_REVENUE,
        service_date__gte=cutoff,
    ).aggregate(
        total=Sum('charged_amount_cents')
    )
    total_cents = result['total'] or 0
    return Decimal(total_cents) / Decimal(100)


def check_revenue_cap(chef, order_amount_cents=0):
    """
    Check if a MEHKO chef is under the annual revenue cap ($100k).
    order_amount_cents: the proposed order amount to check against.
    Only enforced for mehko_active chefs.
    """
    _, _, annual_cap = _get_caps()

    if not getattr(chef, 'mehko_active', False):
        return {
            'under_cap': True,
            'enforced': False,
            'current_revenue': Decimal(0),
            'remaining': None,
            'cap': annual_cap,
            'percent_used': 0.0,
        }
    current = get_annual_revenue(chef)
    cap = Decimal(annual_cap)
    remaining = max(Decimal(0), cap - current)
    order_dollars = Decimal(order_amount_cents) / Decimal(100)
    would_exceed = (current + order_dollars) > cap
    percent_used = float(current / cap * 100) if cap else 0.0

    return {
        'under_cap': not would_exceed,
        'enforced': True,
        'current_revenue': current,
        'remaining': remaining,
        'cap': annual_cap,
        'percent_used': round(percent_used, 1),
    }
