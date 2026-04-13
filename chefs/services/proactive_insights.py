from __future__ import annotations

"""
Proactive insights generation service for Chef Hub.

Analyzes chef data to generate actionable insights like:
- Follow-up reminders for inactive families
- Batch cooking opportunities
- Seasonal ingredient suggestions
- Client wins (positive feedback)
- Scheduling tips for busy periods
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Count, Q, Sum, Avg, Max
from django.utils import timezone

from chef_services.models import ChefCustomerConnection, ChefServiceOrder
from meals.models import ChefMealEvent, ChefMealOrder, ChefMealReview

logger = logging.getLogger(__name__)


def generate_chef_insights(chef) -> list[dict[str, Any]]:
    """
    Generate all proactive insights for a chef.
    
    Returns a list of insight dicts ready to be saved as ChefProactiveInsight records.
    """
    insights = []
    
    insights.extend(_check_followup_needed(chef))
    insights.extend(_check_batch_opportunities(chef))
    insights.extend(_check_seasonal_suggestions(chef))
    insights.extend(_check_client_wins(chef))
    insights.extend(_check_scheduling_tips(chef))
    
    return insights


def _check_followup_needed(chef) -> list[dict[str, Any]]:
    """
    Find families who haven't ordered in 2+ weeks.
    
    Checks both ChefMealOrder and ChefServiceOrder for last activity.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insights = []
    today = date.today()
    now = timezone.now()
    two_weeks_ago = today - timedelta(days=14)
    
    # Get active connections
    connections = ChefCustomerConnection.objects.filter(
        chef=chef,
        status='accepted'
    ).select_related('customer')
    
    for connection in connections:
        customer = connection.customer
        
        # Find last order date from meal orders
        last_meal_order = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            customer=customer,
            status='confirmed'
        ).order_by('-created_at').first()
        
        # Find last order date from service orders
        last_service_order = ChefServiceOrder.objects.filter(
            chef=chef,
            customer=customer,
            status='completed'
        ).order_by('-created_at').first()
        
        # Determine the most recent order
        last_order_date = None
        if last_meal_order:
            last_order_date = last_meal_order.created_at.date()
        if last_service_order:
            service_date = last_service_order.created_at.date()
            if not last_order_date or service_date > last_order_date:
                last_order_date = service_date
        
        # Skip if no orders or recent activity
        if not last_order_date or last_order_date >= two_weeks_ago:
            continue
        
        # Check if insight already exists (not dismissed, not expired)
        existing = ChefProactiveInsight.objects.filter(
            chef=chef,
            customer=customer,
            insight_type='followup_needed',
            is_dismissed=False,
            expires_at__gt=now
        ).exists()
        
        if existing:
            continue
        
        days_since = (today - last_order_date).days
        customer_name = f"{customer.first_name} {customer.last_name}".strip() or customer.username
        
        insights.append({
            'chef': chef,
            'customer': customer,
            'insight_type': 'followup_needed',
            'title': f"Check in with {customer_name}",
            'content': (
                f"It's been {days_since} days since {customer_name}'s last order. "
                f"Consider reaching out to see if they need anything or to share what's new on your menu."
            ),
            'priority': 'high' if days_since >= 30 else 'medium',
            'expires_at': now + timedelta(days=7),
            'action_data': {
                'last_order_date': last_order_date.isoformat(),
                'days_since': days_since,
                'suggested_action': 'draft_message'
            }
        })
    
    return insights


def _check_batch_opportunities(chef) -> list[dict[str, Any]]:
    """
    Find common ingredients across upcoming orders for batch cooking opportunities.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insights = []
    today = date.today()
    now = timezone.now()
    next_week = today + timedelta(days=7)
    
    # Get upcoming meal events with orders
    upcoming_events = ChefMealEvent.objects.filter(
        chef=chef,
        event_date__gte=today,
        event_date__lte=next_week,
        status__in=['scheduled', 'open'],
        orders_count__gt=0
    ).select_related('meal').prefetch_related('meal__dishes__ingredients')
    
    if upcoming_events.count() < 2:
        return insights
    
    # Count ingredient occurrences
    ingredient_counts = {}
    for event in upcoming_events:
        if not event.meal:
            continue
        for dish in event.meal.dishes.all():
            for ingredient in dish.ingredients.all():
                name = ingredient.name.lower()
                if name not in ingredient_counts:
                    ingredient_counts[name] = {'count': 0, 'meals': set()}
                ingredient_counts[name]['count'] += 1
                ingredient_counts[name]['meals'].add(event.meal.name)
    
    # Find ingredients in 2+ meals
    common_ingredients = [
        (name, data) for name, data in ingredient_counts.items()
        if data['count'] >= 2
    ]
    
    if len(common_ingredients) < 2:
        return insights
    
    # Check for existing insight
    existing = ChefProactiveInsight.objects.filter(
        chef=chef,
        insight_type='batch_opportunity',
        is_dismissed=False,
        expires_at__gt=now
    ).exists()
    
    if existing:
        return insights
    
    # Build insight
    top_ingredients = sorted(common_ingredients, key=lambda x: -x[1]['count'])[:5]
    ingredient_list = ", ".join([f"{name} ({data['count']} meals)" for name, data in top_ingredients])
    
    insights.append({
        'chef': chef,
        'insight_type': 'batch_opportunity',
        'title': "Batch cooking opportunity this week",
        'content': (
            f"You have {upcoming_events.count()} meal shares coming up with common ingredients. "
            f"Consider prepping these together: {ingredient_list}. This could save significant time."
        ),
        'priority': 'medium',
        'expires_at': now + timedelta(days=3),
        'action_data': {
            'common_ingredients': [name for name, _ in top_ingredients],
            'meal_count': upcoming_events.count(),
            'suggested_action': 'create_prep_plan'
        }
    })
    
    return insights


def _check_seasonal_suggestions(chef) -> list[dict[str, Any]]:
    """
    Generate monthly seasonal ingredient suggestions.
    Only creates insight in the first 5 days of each month.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insights = []
    today = date.today()
    now = timezone.now()
    
    # Only generate at the start of the month
    if today.day > 5:
        return insights
    
    # Check if we already have a seasonal suggestion this month
    existing = ChefProactiveInsight.objects.filter(
        chef=chef,
        insight_type='seasonal_suggestion',
        is_dismissed=False,
        created_at__month=today.month,
        created_at__year=today.year
    ).exists()
    
    if existing:
        return insights
    
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    
    seasonal_highlights = {
        1: ["citrus fruits", "root vegetables", "winter squash"],
        2: ["blood oranges", "Brussels sprouts", "cabbage"],
        3: ["asparagus", "artichokes", "spring greens"],
        4: ["peas", "ramps", "morels", "strawberries"],
        5: ["cherries", "fava beans", "new potatoes"],
        6: ["berries", "stone fruits", "corn", "tomatoes"],
        7: ["watermelon", "zucchini", "peppers", "eggplant"],
        8: ["peaches", "figs", "melons", "late summer vegetables"],
        9: ["apples", "grapes", "butternut squash", "late tomatoes"],
        10: ["pumpkin", "cranberries", "Brussels sprouts", "pears"],
        11: ["root vegetables", "winter squash", "citrus beginning"],
        12: ["citrus", "pomegranates", "root vegetables", "game"]
    }
    
    highlights = seasonal_highlights.get(today.month, [])
    month_name = month_names[today.month - 1]
    
    insights.append({
        'chef': chef,
        'insight_type': 'seasonal_suggestion',
        'title': f"{month_name} seasonal ingredients",
        'content': (
            f"It's a great time to feature: {', '.join(highlights)}. "
            f"Seasonal ingredients are fresher, more affordable, and your clients will love the variety."
        ),
        'priority': 'low',
        'expires_at': now + timedelta(days=14),
        'action_data': {
            'month': today.month,
            'month_name': month_name,
            'seasonal_ingredients': highlights,
            'suggested_action': 'create_menu'
        }
    })
    
    return insights


def _check_client_wins(chef) -> list[dict[str, Any]]:
    """
    Find recent positive reviews (4-5 stars) to celebrate.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insights = []
    today = date.today()
    now = timezone.now()
    one_week_ago = today - timedelta(days=7)
    
    # Get recent positive reviews
    recent_reviews = ChefMealReview.objects.filter(
        chef=chef,
        rating__gte=4,
        created_at__date__gte=one_week_ago
    ).select_related('customer', 'meal_event__meal')
    
    for review in recent_reviews:
        # Check if we already created an insight for this review
        existing = ChefProactiveInsight.objects.filter(
            chef=chef,
            insight_type='client_win',
            action_data__review_id=review.id
        ).exists()
        
        if existing:
            continue
        
        customer_name = f"{review.customer.first_name}".strip() or review.customer.username
        meal_name = "your meal"
        if review.meal_event and review.meal_event.meal:
            meal_name = review.meal_event.meal.name
        
        content = f"{customer_name} gave {meal_name} a {review.rating}-star rating!"
        if review.comment:
            comment_preview = review.comment[:100] + "..." if len(review.comment) > 100 else review.comment
            content += f' They said: "{comment_preview}"'
        
        insights.append({
            'chef': chef,
            'customer': review.customer,
            'insight_type': 'client_win',
            'title': f"Great feedback from {customer_name}! 🎉",
            'content': content,
            'priority': 'low',
            'expires_at': now + timedelta(days=7),
            'action_data': {
                'review_id': review.id,
                'rating': review.rating,
                'meal_name': meal_name,
                'suggested_action': 'thank_client'
            }
        })
    
    return insights


def _check_scheduling_tips(chef) -> list[dict[str, Any]]:
    """
    Find busy days ahead (5+ orders) and suggest preparation.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insights = []
    today = date.today()
    now = timezone.now()
    next_3_days = today + timedelta(days=3)
    
    # Count orders per day
    daily_counts = {}
    
    # Count from meal events
    for event in ChefMealEvent.objects.filter(
        chef=chef,
        event_date__gte=today,
        event_date__lte=next_3_days,
        status__in=['scheduled', 'open', 'confirmed']
    ):
        day = event.event_date
        if day not in daily_counts:
            daily_counts[day] = 0
        daily_counts[day] += event.orders_count
    
    # Count from service orders
    for service in ChefServiceOrder.objects.filter(
        chef=chef,
        service_date__gte=today,
        service_date__lte=next_3_days,
        status='confirmed'
    ):
        day = service.service_date
        if day not in daily_counts:
            daily_counts[day] = 0
        daily_counts[day] += 1
    
    # Generate insights for busy days
    for day, count in daily_counts.items():
        if count < 5:
            continue
        
        # Check for existing insight
        existing = ChefProactiveInsight.objects.filter(
            chef=chef,
            insight_type='scheduling_tip',
            is_dismissed=False,
            action_data__date=day.isoformat()
        ).exists()
        
        if existing:
            continue
        
        day_name = day.strftime("%A, %B %d")
        
        insights.append({
            'chef': chef,
            'insight_type': 'scheduling_tip',
            'title': f"Busy day ahead: {day_name}",
            'content': (
                f"You have {count} orders scheduled for {day_name}. "
                f"Consider prepping ingredients today and reviewing your timeline to ensure smooth execution."
            ),
            'priority': 'high',
            'expires_at': timezone.make_aware(
                timezone.datetime.combine(day, timezone.datetime.max.time())
            ),
            'action_data': {
                'date': day.isoformat(),
                'order_count': count,
                'suggested_action': 'create_prep_plan'
            }
        })
    
    return insights


def save_insights(insights: list[dict[str, Any]]) -> int:
    """
    Save a list of insight dicts as ChefProactiveInsight records.
    
    Returns the number of insights created.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    created_count = 0
    for insight_data in insights:
        try:
            ChefProactiveInsight.objects.create(**insight_data)
            created_count += 1
        except Exception as e:
            logger.error(f"Failed to create insight: {e}")
    
    return created_count


def expire_old_insights(chef) -> int:
    """
    Mark expired insights as dismissed.
    
    Returns the number of insights expired.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    now = timezone.now()
    count = ChefProactiveInsight.objects.filter(
        chef=chef,
        expires_at__lt=now,
        is_dismissed=False
    ).update(is_dismissed=True)
    
    return count


def get_insights_for_chef(
    chef,
    *,
    include_read: bool = False,
    include_dismissed: bool = False,
    insight_types: list[str] | None = None,
    limit: int = 10
) -> list[dict[str, Any]]:
    """
    Get proactive insights for a chef with filtering options.
    
    Returns a list of insight dicts ready for API response.
    """
    from customer_dashboard.models import ChefProactiveInsight
    from django.db.models import Case, When, IntegerField
    
    now = timezone.now()
    
    queryset = ChefProactiveInsight.objects.filter(chef=chef)
    
    if not include_dismissed:
        queryset = queryset.filter(is_dismissed=False)
    
    if not include_read:
        queryset = queryset.filter(is_read=False)
    
    # Filter by expiration
    queryset = queryset.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    
    if insight_types:
        queryset = queryset.filter(insight_type__in=insight_types)
    
    # Order by priority, then recency
    priority_order = Case(
        When(priority='high', then=1),
        When(priority='medium', then=2),
        When(priority='low', then=3),
        output_field=IntegerField(),
    )
    
    insights = queryset.annotate(
        priority_rank=priority_order
    ).order_by('priority_rank', '-created_at').select_related('customer', 'lead')[:limit]
    
    results = []
    for insight in insights:
        family_name = None
        family_id = None
        family_type = None
        
        if insight.customer:
            family_name = f"{insight.customer.first_name} {insight.customer.last_name}".strip() or insight.customer.username
            family_id = insight.customer_id
            family_type = 'customer'
        elif insight.lead:
            family_name = f"{insight.lead.first_name} {insight.lead.last_name}".strip()
            family_id = insight.lead_id
            family_type = 'lead'
        
        results.append({
            'id': insight.id,
            'type': insight.insight_type,
            'type_display': insight.get_insight_type_display(),
            'title': insight.title,
            'content': insight.content,
            'priority': insight.priority,
            'family_name': family_name,
            'family_id': family_id,
            'family_type': family_type,
            'is_read': insight.is_read,
            'is_dismissed': insight.is_dismissed,
            'created_at': insight.created_at.isoformat(),
            'expires_at': insight.expires_at.isoformat() if insight.expires_at else None,
            'action_data': insight.action_data,
        })
    
    return results
