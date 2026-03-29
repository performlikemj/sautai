"""
Chef Analytics and Revenue API endpoints.

Provides endpoints for revenue tracking, analytics, and upcoming orders.
"""

import logging
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from chefs.models import Chef
from chefs.services import get_revenue_breakdown, get_upcoming_orders
from chefs.services.client_insights import get_analytics_time_series
from .serializers import RevenueBreakdownSerializer, UpcomingOrderSerializer

logger = logging.getLogger(__name__)


def _get_chef_or_403(request):
    """
    Get the Chef instance for the authenticated user.
    Returns (chef, None) on success, (None, Response) on failure.
    """
    try:
        chef = Chef.objects.get(user=request.user)
        return chef, None
    except Chef.DoesNotExist:
        return None, Response(
            {"error": "Not a chef. Only chefs can access analytics."},
            status=403
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def revenue_breakdown(request):
    """
    GET /api/chefs/me/revenue/
    
    Returns revenue breakdown for a specified period.
    
    Query Parameters:
    - period: 'day', 'week', 'month', 'year' (default: 'month')
    - start_date: ISO date string (optional, overrides period)
    - end_date: ISO date string (optional, defaults to today)
    
    Response:
    ```json
    {
        "period": "month",
        "start_date": "2024-03-01",
        "end_date": "2024-03-15",
        "total_revenue": 3200.00,
        "meal_revenue": 2100.00,
        "service_revenue": 1100.00,
        "order_count": 45,
        "average_order_value": 71.11
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        # Parse query params
        period = request.query_params.get('period', 'month')
        if period not in ['day', 'week', 'month', 'year']:
            period = 'month'
        
        start_date = None
        end_date = None
        
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        if start_date_str:
            start_date = parse_date(start_date_str)
            if start_date:
                # Convert to datetime at start of day
                start_date = timezone.make_aware(
                    datetime.combine(start_date, datetime.min.time())
                )
        
        if end_date_str:
            end_date = parse_date(end_date_str)
            if end_date:
                # Convert to datetime at end of day
                end_date = timezone.make_aware(
                    datetime.combine(end_date, datetime.max.time())
                )
        
        # Get revenue breakdown
        data = get_revenue_breakdown(
            chef,
            period=period,
            start_date=start_date,
            end_date=end_date
        )
        
        serializer = RevenueBreakdownSerializer(data)
        return Response(serializer.data)
        
    except Exception as e:
        logger.exception(f"Error fetching revenue breakdown for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to fetch revenue data. Please try again."},
            status=500
        )


class UpcomingOrdersPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def upcoming_orders(request):
    """
    GET /api/chefs/me/orders/upcoming/
    
    Returns upcoming orders (both meal events and service orders) sorted by date.
    
    Query Parameters:
    - page: Page number
    - page_size: Items per page (default: 20, max: 100)
    - limit: Max results (default: 50, for non-paginated use)
    
    Response:
    ```json
    {
        "count": 12,
        "next": null,
        "previous": null,
        "results": [
            {
                "order_type": "meal_event",
                "order_id": 123,
                "customer_id": 42,
                "customer_username": "johndoe",
                "customer_name": "John Doe",
                "service_date": "2024-03-20",
                "service_time": "18:00:00",
                "service_name": "Italian Dinner Event",
                "status": "confirmed",
                "quantity": 2,
                "price": 45.00
            },
            {
                "order_type": "service",
                "order_id": 456,
                "customer_id": 55,
                "customer_username": "janedoe",
                "customer_name": "Jane Doe",
                "service_date": "2024-03-22",
                "service_time": "10:00:00",
                "service_name": "Weekly Meal Prep",
                "status": "confirmed",
                "quantity": 1,
                "price": 150.00
            }
        ]
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        # Get limit from query params
        limit = int(request.query_params.get('limit', 50))
        limit = min(limit, 100)  # Cap at 100
        
        # Get upcoming orders
        orders = get_upcoming_orders(chef, limit=limit)
        
        # Paginate
        paginator = UpcomingOrdersPagination()
        page = paginator.paginate_queryset(orders, request)
        
        if page is not None:
            serializer = UpcomingOrderSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = UpcomingOrderSerializer(orders, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.exception(f"Error fetching upcoming orders for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to fetch upcoming orders. Please try again."},
            status=500
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def time_series(request):
    """
    GET /api/chefs/analytics/time-series/
    
    Returns time-series data for analytics charts.
    
    Query params:
    - metric: 'revenue' | 'orders' | 'clients' (required)
    - range: '7d' | '30d' | '90d' | '1y' (default: '30d')
    
    Response:
    ```json
    {
        "metric": "revenue",
        "range": "30d",
        "data": [
            {"date": "2025-12-01", "value": 150.00, "label": "Dec 1"},
            {"date": "2025-12-02", "value": 200.00, "label": "Dec 2"},
            ...
        ],
        "total": 3500.00
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    # Parse query params
    metric = request.query_params.get('metric', 'revenue')
    if metric not in ('revenue', 'orders', 'clients'):
        return Response(
            {"error": f"Invalid metric '{metric}'. Must be 'revenue', 'orders', or 'clients'."},
            status=400
        )
    
    range_param = request.query_params.get('range', '30d')
    range_to_days = {
        '7d': 7,
        '30d': 30,
        '90d': 90,
        '1y': 365,
    }
    days = range_to_days.get(range_param, 30)
    
    try:
        data = get_analytics_time_series(chef, metric=metric, days=days)

        # Revenue returns by_currency dicts; other metrics return value
        if metric == 'revenue':
            # Compute total per currency across all data points
            total_by_currency = {}
            for point in data:
                for cur, amt in point.get('by_currency', {}).items():
                    total_by_currency[cur] = total_by_currency.get(cur, 0) + amt
            total = total_by_currency
        else:
            total = sum(point.get('value', 0) for point in data)

        return Response({
            "metric": metric,
            "range": range_param,
            "data": data,
            "total": total
        })
    except Exception as e:
        logger.exception(f"Error fetching analytics time series for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to fetch analytics data. Please try again."},
            status=500
        )