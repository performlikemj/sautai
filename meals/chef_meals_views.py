import logging
import os
import traceback
from django.shortcuts import get_object_or_404, render, redirect
from datetime import datetime, timedelta
import pytz
from .models import (
    Meal, Dish, Ingredient, ChefMealEvent, ChefMealOrder, 
    ChefPostalCode, StripeConnectAccount, PaymentLog, 
    DietaryPreference, CustomDietaryPreference,
    STATUS_CANCELLED, STATUS_PLACED, STATUS_CONFIRMED, STATUS_COMPLETED,
    STATUS_REFUNDED, STATUS_SCHEDULED, STATUS_OPEN, STATUS_CLOSED,
    STATUS_IN_PROGRESS
)
from .serializers import (
    MealSerializer, ChefMealEventSerializer, 
    ChefMealOrderSerializer, ChefMealOrderCreateSerializer, 
    DishSerializer, IngredientSerializer, ChefMealEventCreateSerializer,
    ChefMealReviewSerializer
)
from shared.utils import standardize_response, ChefMealEventPagination, create_meal
from custom_auth.models import CustomUser
from chefs.models import Chef
from django.conf import settings
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q, Sum, Count, Avg, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timezone as py_tz
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
import stripe
import django.db.utils
import dateutil.parser
import re
import json
import requests
from meals.order_service import ensure_chef_meal_order
from django.db import transaction
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import pytz
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stripe_return(request, account_id):
    """
    API endpoint for handling Stripe Connect account status updates
    """
    try:
        # Get the chef and their Stripe account
        chef = get_object_or_404(Chef, user=request.user)
        stripe_account = get_object_or_404(StripeConnectAccount, 
                                         stripe_account_id=account_id,
                                         chef=chef)
        
        # Update account status from Stripe
        stripe_account_info = stripe.Account.retrieve(account_id)
        stripe_account.charges_enabled = stripe_account_info.charges_enabled
        stripe_account.payouts_enabled = stripe_account_info.payouts_enabled
        stripe_account.details_submitted = stripe_account_info.details_submitted
        stripe_account.save()

        # Return JSON response
        return Response({
            'status': 'success',
            'message': 'Stripe account status updated successfully',
            'account_status': {
                'charges_enabled': stripe_account.charges_enabled,
                'payouts_enabled': stripe_account.payouts_enabled,
                'details_submitted': stripe_account.details_submitted
            }
        })
        
    except Exception as e:
        logger.error(f"Error in stripe_return for account {account_id}: {str(e)}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stripe_refresh(request, account_id):
    """
    API endpoint to handle refresh requests from Stripe onboarding flow.
    Returns new account link when session expires or retry is needed.
    """
    try:
        # Verify chef status
        chef = get_object_or_404(Chef, user=request.user)
        
        # Check if this account belongs to the chef
        stripe_account = get_object_or_404(StripeConnectAccount, 
                                         chef=chef, 
                                         stripe_account_id=account_id)

        # Create new account link
        dummy_url = f"{os.getenv('STREAMLIT_URL')}/"
        account_link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=dummy_url,
            return_url=dummy_url,
            type="account_onboarding",
        )
        
        return Response({
            'status': 'success',
            'message': 'New onboarding link generated',
            'url': account_link.url,
            'account_id': account_id
        })

    except Exception as e:
        logger.error(f"Error in stripe_refresh for account {account_id}: {str(e)}")
        return Response({
            'status': 'error',
            'message': str(e),
            'account_id': account_id
        }, status=500)

# Helper function (non-decorated) to get chef meal orders
def _get_chef_meal_orders(user, as_chef=False):
    """
    Helper function to get chef meal orders.
    This function is not decorated with @api_view so it can be called by other views.
    """
    # Chef viewing their received orders
    if as_chef:
        try:
            chef = Chef.objects.get(user=user)
            orders = ChefMealOrder.objects.filter(meal_event__chef=chef).order_by('-created_at')
        except Chef.DoesNotExist:
            orders = ChefMealOrder.objects.none()
    
    # Default: customer viewing their own orders
    else:
        orders = ChefMealOrder.objects.filter(customer=user).order_by('-created_at')
    
    return orders

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_chef_meal_orders(request):
    """
    Get chef meal orders - either for a chef or a customer based on query params.
    Use ?as_chef=true to get orders received as a chef.
    """
    as_chef = request.query_params.get('as_chef') == 'true'
    orders = _get_chef_meal_orders(request.user, as_chef)
    serializer = ChefMealOrderSerializer(orders, many=True)
    return Response(serializer.data)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_chef_meal_orders(request):
    """
    GET: Get chef meal orders
    POST: Create a new chef meal order
    """
    # Handle GET requests
    if request.method == 'GET':
        as_chef = request.query_params.get('as_chef') == 'true'
        orders = _get_chef_meal_orders(request.user, as_chef)
        serializer = ChefMealOrderSerializer(orders, many=True)
        return Response(serializer.data)
    
    # Handle POST requests
    elif request.method == 'POST':
        serializer = ChefMealOrderCreateSerializer(data=request.data, context={'request': request})
        try:
            if serializer.is_valid():
                # Allow multiple chef-created meal orders across different chefs and events
                # Uniqueness per event is enforced at the model level (active orders per event)
                order = serializer.save()
                # Return the created order with full details
                response_serializer = ChefMealOrderSerializer(order)
                # If the serializer exposed the idempotency key, echo it back in the header
                idem_key = serializer.context.get('idem_key')
                resp = Response(response_serializer.data, status=201)
                if idem_key:
                    resp["Idempotency-Key"] = idem_key
                return resp
        except Exception as e:
            # Special handling for DRF validation errors with specific error detail
            from rest_framework.exceptions import ValidationError
            # Use module-level Response import to avoid overshadowing
            from rest_framework import status
            import traceback
            import os
            import requests

            # Check for DRF ValidationError or error detail in the exception
            error_detail = getattr(e, 'detail', None)
            if error_detail:
                # If the error is about an active order already existing, return a specific message
                if isinstance(error_detail, dict):
                    # Check for a field or non_field_errors containing the message
                    for field, messages in error_detail.items():
                        if isinstance(messages, list):
                            for msg in messages:
                                if (
                                    hasattr(msg, 'code') and msg.code == 'invalid'
                                    and str(msg) == 'Active order already exists'
                                ):
                                    return Response(
                                        {"error": "Active order already exists for this event. Please update the existing order instead."},
                                        status=status.HTTP_400_BAD_REQUEST
                                    )
                elif isinstance(error_detail, list):
                    for msg in error_detail:
                        if (
                            hasattr(msg, 'code') and msg.code == 'invalid'
                            and str(msg) == 'Active order already exists'
                        ):
                            return Response(
                                {"error": "Active order already exists for this event. Please update the existing order instead."},
                                status=status.HTTP_400_BAD_REQUEST
                            )
            logger.error(f"Error creating ChefMealOrder: {str(e)}")
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_orders',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return Response({"error": str(e)}, status=400)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_chef_meal_order_detail(request, order_id):
    """
    Get, update or delete a specific order containing chef meals.
    This endpoint can be called with either a ChefMealOrder ID or a regular Order ID.
    """
    import logging
    import traceback
    logger = logging.getLogger(__name__)
    
    from meals.models import Order, ChefMealOrder, OrderMeal
    user = request.user
    as_chef = request.query_params.get('as_chef') == 'true'
    
    
    # First, try to get the order as a ChefMealOrder
    chef_meal_order = None
    order = None
    
    try:
        # Try to get a ChefMealOrder directly
        if as_chef:
            try:
                chef = Chef.objects.get(user=user)
                chef_meal_order = ChefMealOrder.objects.select_related('order', 'meal_event').get(
                    id=order_id,
                    meal_event__chef=chef
                )
            except Chef.DoesNotExist:
                logger.error(f"Chef profile not found for user_id={user.id}")
                return Response({"error": "Chef profile not found"}, status=404)
            except ChefMealOrder.DoesNotExist:
                # n8n traceback
                n8n_traceback = {
                    'error': f"ChefMealOrder not found with id={order_id} for chef_id={chef.id}",
                    'source': 'api_chef_meal_order_detail',
                    'traceback': traceback.format_exc()
                }
                requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                pass
        else:
            try:
                chef_meal_order = ChefMealOrder.objects.select_related('order').get(
                    id=order_id,
                    customer=user
                )
            except ChefMealOrder.DoesNotExist:
                # n8n traceback
                n8n_traceback = {
                    'error': f"ChefMealOrder not found with id={order_id} for user_id={user.id}",
                    'source': 'api_chef_meal_order_detail',
                    'traceback': traceback.format_exc()
                }
                requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
        
        # If we found a ChefMealOrder, get its parent Order
        if chef_meal_order:
            order = chef_meal_order.order
            
    except ChefMealOrder.DoesNotExist:
        # Already handled in the inner blocks
        pass
    except Exception as e:
        logger.error(f"Unexpected error looking for ChefMealOrder: {str(e)}")
        # n8n traceback
        n8n_traceback = {
            'error': str(e),
            'source': 'api_chef_meal_order_detail',
            'traceback': traceback.format_exc()
        }
        requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
    
    # If not found as ChefMealOrder, try as regular Order
    if not order:
        try:
            if as_chef:
                try:
                    chef = Chef.objects.get(user=user)
                    order = Order.objects.prefetch_related('chef_meal_orders').get(
                        id=order_id,
                        chef_meal_orders__meal_event__chef=chef
                    )
                except Chef.DoesNotExist:
                    logger.error(f"Chef profile not found for user_id={user.id}")
                    # n8n traceback
                    n8n_traceback = {
                        'error': f"Chef profile not found for user_id={user.id}",
                        'source': 'api_chef_meal_order_detail',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                    return Response({"error": "Chef profile not found"}, status=404)
                except Order.DoesNotExist:
                    # n8n traceback
                    n8n_traceback = {
                        'error': f"Order not found with id={order_id} for chef_id={chef.id}",
                        'source': 'api_chef_meal_order_detail',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            else:
                try:
                    # First check if the order exists at all
                    if Order.objects.filter(id=order_id).exists():
                        # Check if it belongs to this user
                        if Order.objects.filter(id=order_id, customer=user).exists():
                            # Finally, get it with prefetch_related
                            order = Order.objects.prefetch_related('chef_meal_orders').get(
                                id=order_id, 
                                customer=user
                            )
                        else:
                            user_of_order = Order.objects.get(id=order_id).customer
                            logger.warning(f"Order exists but belongs to user_id={user_of_order.id}, not requestor user_id={user.id}")
                            return Response({"error": "Order not found for this user"}, status=404)
                    else:
                        logger.warning(f"Order with id={order_id} does not exist in the database")
                        return Response({"error": "Order does not exist"}, status=404)
                except Order.DoesNotExist:
                    # n8n traceback
                    n8n_traceback = {
                        'error': f"Order not found with id={order_id} for user_id={user.id}",
                        'source': 'api_chef_meal_order_detail',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                except Exception as e:
                    logger.error(f"Unexpected error looking for Order: {str(e)}")
                    # n8n traceback
                    n8n_traceback = {
                        'error': str(e),
                        'source': 'api_chef_meal_order_detail',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                
            # Check if the order has any chef meal orders
            if order and not order.chef_meal_orders.exists():
                logger.warning(f"Order with id={order.id} exists but has no chef_meal_orders")
                
                # For debugging, try to find any ChefMealOrders that might reference this order
                direct_query_orders = ChefMealOrder.objects.filter(order_id=order.id)
                if direct_query_orders.exists():
                    logger.warning(f"Found {direct_query_orders.count()} ChefMealOrders directly using order_id={order.id}")
                    for cmo in direct_query_orders:
                        logger.warning(f"ChefMealOrder id={cmo.id}, customer_id={cmo.customer_id}")
                
                # Instead of returning a 404, continue with the empty chef_meal_orders
                # This allows the frontend to handle orders without chef meals
                # We'll just continue and let the serializer handle the empty chef_meal_orders
        
        except Order.DoesNotExist:
            logger.warning(f"Order with id={order_id} does not exist for user_id={user.id}")
            # n8n traceback
            n8n_traceback = {
                'error': f"Order not found with id={order_id} for user_id={user.id}",
                'source': 'api_chef_meal_order_detail',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return Response({"error": "Order not found"}, status=404)
        except Exception as e:
            logger.error(f"Unexpected error looking for Order: {str(e)}")
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_order_detail',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return Response({"error": f"Unexpected error: {str(e)}"}, status=500)
    
    # At this point, we should have an Order object
    if not order:
        logger.error(f"Failed to retrieve order with id={order_id} for user_id={user.id}")
        return Response({"error": "Order not found"}, status=404)
        
    # Handle GET request - retrieve order details
    if request.method == 'GET':
        try:
            # IMPORTANT: Explicitly fetch the chef meal orders
            chef_meal_orders = list(ChefMealOrder.objects.filter(order_id=order.id))
            
            # Serialize the order with its chef meal orders
            from meals.serializers import OrderWithChefMealsSerializer
            serializer = OrderWithChefMealsSerializer(order, context={'request': request})
            
            # Get the serialized data
            data = serializer.data
            
            # If the chef_meal_orders field is empty but we found them manually, append them
            if not data['chef_meal_orders'] and chef_meal_orders:
                logger.warning(f"Serializer didn't include chef_meal_orders, manually adding {len(chef_meal_orders)}")
                from meals.serializers import ChefMealOrderSerializer
                data['chef_meal_orders'] = ChefMealOrderSerializer(chef_meal_orders, many=True).data
            
            return Response(data)
        except Exception as e:
            logger.error(f"Error serializing Order with id={order.id}: {str(e)}")
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_order_detail',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return Response({"error": f"Error serializing order: {str(e)}"}, status=500)
    
    # Handle DELETE request - cancel the order
    elif request.method == 'DELETE':
        try:
            # Cancel all chef meal orders associated with this order
            for chef_meal_order in order.chef_meal_orders.all():
                if chef_meal_order.status not in ['cancelled', 'completed']:
                    chef_meal_order.cancel()
            
            # Update order status
            order.status = 'Cancelled'
            order.save()
            
            return Response({"status": "success", "message": "Order cancelled successfully"})
        except Exception as e:
            logger.error(f"Error cancelling Order with id={order.id}: {str(e)}")
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_order_detail',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return Response({"error": f"Error cancelling order: {str(e)}"}, status=500)
    
    # Handle PUT/PATCH request - update the order
    elif request.method in ['PUT', 'PATCH']:
        try:
            # Check if we have chef meal orders to update
            chef_meal_orders = order.chef_meal_orders.all()
            if not chef_meal_orders:
                logger.warning(f"No chef meal orders found for Order with id={order.id}")
                return Response({"error": "No chef meal orders found for this order"}, status=404)
            
            # Get the update fields from the request
            special_requests = request.data.get('special_requests')
            quantity = request.data.get('quantity')
            
            # Track if any updates were made
            updates_made = False
            
            # Update special requests if provided
            if special_requests is not None:
                # Update special requests for all chef meal orders in this order
                for chef_meal_order in chef_meal_orders:
                    chef_meal_order.special_requests = special_requests
                    chef_meal_order.save(update_fields=['special_requests'])
                
                # Also update the main order
                order.special_requests = special_requests
                order.save(update_fields=['special_requests'])
                
                updates_made = True
            
            # Update quantity if provided
            if quantity is not None:
                try:
                    quantity = int(quantity)
                    # Validate quantity
                    if quantity <= 0:
                        return Response({"error": "Quantity must be greater than zero"}, status=400)
                    
                    # For each chef meal order, update the quantity field but DO NOT update orders_count
                    # or recalculate pricing - that will happen when payment is confirmed
                    for chef_meal_order in chef_meal_orders:
                        # Check if the event has enough capacity
                        event = chef_meal_order.meal_event
                        available_slots = event.max_orders - event.orders_count
                        
                        # Add back this order's current quantity since we're replacing it
                        if chef_meal_order.status == STATUS_CONFIRMED:
                            available_slots += chef_meal_order.quantity
                            
                        # Check if there's enough capacity for the new quantity
                        if quantity > available_slots and chef_meal_order.status != STATUS_CONFIRMED:
                            return Response({
                                "error": f"Not enough available slots. Only {available_slots} slots available.",
                                "available_slots": available_slots
                            }, status=400)
                            
                        # Update the quantity without updating orders_count or pricing
                        chef_meal_order.quantity = quantity
                        chef_meal_order.save(update_fields=['quantity'])
                        
                        # Also update the quantity in the OrderMeal
                        try:
                            order_meal = OrderMeal.objects.get(
                                order=order,
                                meal_plan_meal=chef_meal_order.meal_plan_meal
                            )
                            order_meal.quantity = quantity
                            order_meal.save(update_fields=['quantity'])
                        except OrderMeal.DoesNotExist:
                            logger.warning(f"No OrderMeal found for ChefMealOrder id={chef_meal_order.id}")
                    
                    updates_made = True
                except ValueError:
                    return Response({"error": "Invalid quantity value"}, status=400)
                
            if updates_made:
                return Response({"status": "success", "message": "Order updated successfully"})
            else:
                logger.warning(f"No valid fields to update for Order with id={order.id}")
                return Response({"error": "No valid fields to update"}, status=400)
        except Exception as e:
            logger.error(f"Error updating Order with id={order.id}: {str(e)}")
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_order_detail',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return Response({"error": f"Error updating order: {str(e)}"}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_chef_meal_order_detail(request, order_id):
    """
    Get details of a specific order containing chef meals.
    For backwards compatibility, returns the same data as api_chef_meal_order_detail.
    """
    from meals.models import Order, ChefMealOrder
    # Delegate to the main implementation
    return api_chef_meal_order_detail(request, order_id)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_cancel_chef_meal_order(request, order_id):
    """Cancel a chef meal order"""
    try:
        order = ChefMealOrder.objects.get(id=order_id)
        
        # Check if the user is the owner of this order
        if order.customer != request.user:
            return Response(
                {"error": "You don't have permission to cancel this order"},
                status=403
            )
        
        # Check if the order can be cancelled
        if order.status not in [STATUS_PLACED, STATUS_CONFIRMED]:
            return Response(
                {"error": "This order cannot be cancelled in its current state"},
                status=400
            )
        
        # Check if we're past the deadline
        event = order.meal_event
        now = timezone.now()
        if now > event.order_cutoff_time:
            return Response(
                {"error": "The cancellation period has passed"},
                status=400
            )
        
        # Cancel the order
        try:
            order.cancel()
            return Response({"status": "Order cancelled successfully"})
        except Exception as e:
            return Response(
                {"error": f"Failed to cancel order: {str(e)}"},
                status=500
            )
            
    except ChefMealOrder.DoesNotExist:
        return Response(
            {"error": "Order not found"},
            status=404
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_confirm_chef_meal_order(request, order_id):
    """
    Confirm a chef meal order.
    This endpoint allows a chef to confirm an order with status 'placed'.
    Only chefs can confirm orders for their own meals.
    """
    from meals.models import OrderMeal, ChefMealEvent
    try:
        order_meal = OrderMeal.objects.get(id=order_id)
        chef_meal_order = ChefMealOrder.objects.get(id=order_meal.chef_meal_event_id)
        
        # Check if the user is the chef who created this meal event
        if not hasattr(request.user, 'chef') or chef_meal_order.meal_event.chef.user != request.user:
            return Response(
                {"error": "You don't have permission to confirm this order"},
                status=403
            )
        
        # Check if the order is in 'placed' status
        if chef_meal_order.status != STATUS_PLACED:
            return Response(
                {"error": f"This order cannot be confirmed because it is in '{chef_meal_order.status}' status"},
                status=400
            )
        
        # Confirm the order
        try:
            # Update status to confirmed
            chef_meal_order.status = STATUS_CONFIRMED
            chef_meal_order.save()
            
            # Create payment log if it doesn't exist and if there's a payment intent
            if order_meal.payment_intent_id and not PaymentLog.objects.filter(chef_meal_order=chef_meal_order, stripe_id=order_meal.payment_intent_id).exists():
                PaymentLog.objects.create(
                    chef_meal_order=chef_meal_order,
                    user=order_meal.customer,
                    chef=chef_meal_order.meal_event.chef,
                    action='charge',
                    amount=float(order_meal.price_paid) * order_meal.quantity,
                    stripe_id=order_meal.payment_intent_id or '',
                    status='succeeded',
                    details={'confirmed_by_chef': True}
                )
            
            # Return success
            return Response({
                "status": "success",
                "message": "Order confirmed successfully",
                "details": {
                    "order_id": order_meal.id,
                    "status": order_meal.status,
                    "customer": order_meal.customer.username
                }
            })
            
        except Exception as e:
            logger.error(f"Error confirming order {order_meal.id}: {str(e)}", exc_info=True)
            return Response(
                {"error": f"Failed to confirm order: {str(e)}"},
                status=500
            )
            
    except ChefMealOrder.DoesNotExist:
        return Response(
            {"error": "Order not found"},
            status=404
        )
    
# Helper function to cancel a chef meal order
def _cancel_chef_meal_order(user, order_id):
    """
    Helper function to cancel a chef meal order.
    This function is not decorated with @api_view so it can be called by other views.
    """
    try:
        order = ChefMealOrder.objects.get(id=order_id)
        
        # Check if the user is the owner of this order
        if order.customer != user:
            return None, {"error": "You don't have permission to cancel this order"}, 403
        
        # Check if the order can be cancelled
        if order.status not in [STATUS_PLACED, STATUS_CONFIRMED]:
            return None, {"error": "This order cannot be cancelled in its current state"}, 400
        
        # Check if we're past the deadline
        event = order.meal_event
        now = timezone.now()
        if now > event.order_cutoff_time:
            return None, {"error": "The cancellation period has passed"}, 400
        
        # Cancel the order
        try:
            order.cancel()
            return order, {"status": "Order cancelled successfully"}, 200
        except Exception as e:
            return None, {"error": f"Failed to cancel order: {str(e)}"}, 500
            
    except ChefMealOrder.DoesNotExist:
        return None, {"error": "Order not found"}, 404

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_cancel_chef_meal_order(request, order_id):
    """Cancel a chef meal order"""
    reason = request.data.get('reason', '')
    
    # Log the cancellation request
    _, response_data, status_code = _cancel_chef_meal_order(request.user, order_id)
    return Response(response_data, status=status_code)

@api_view(['POST'])
@permission_classes([])  # No authentication required for webhooks
def stripe_webhook(request):
    """
    Handle Stripe webhook events.
    This endpoint receives events from Stripe and updates the application state accordingly.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    from meals.email_service import send_payment_confirmation_email, send_refund_notification_email, send_order_cancellation_email
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid payload in Stripe webhook: {str(e)}")
        return Response({"error": "Invalid payload"}, status=400)
    except stripe.error.SignatureVerificationError as e:
        # In development, allow fallback parsing if signature header is missing and DEBUG is True
        if getattr(settings, 'DEBUG', False) and not sig_header:
            import json as _json
            try:
                event = stripe.Event.construct_from(_json.loads(payload), stripe.api_key)
            except Exception as _e:
                logger.error(f"Unable to parse webhook payload in DEBUG fallback: {_e}")
                return Response({"error": "Invalid signature"}, status=400)
        else:
            logger.error(f"Invalid signature in Stripe webhook: {str(e)}")
            return Response({"error": "Invalid signature"}, status=400)
    
    try:
        if event.type == 'checkout.session.completed':
            session = event.data.object
            metadata = getattr(session, 'metadata', {}) or {}

            if metadata.get('order_type') == 'service' and metadata.get('service_order_id'):
                try:
                    from chef_services.webhooks import handle_checkout_session_completed
                    handle_checkout_session_completed(session)
                    logger.info(
                        "Processed service order checkout via webhook",
                        extra={
                            "service_order_id": metadata.get('service_order_id'),
                            "session_id": getattr(session, 'id', None),
                        },
                    )
                    return Response({"status": "success"})
                except Exception as svc_err:
                    logger.error(
                        f"Service order webhook handling failed: {svc_err}",
                        exc_info=True,
                    )
                    return Response({"error": str(svc_err)}, status=400)

            # Handle chef payment link payments
            if metadata.get('type') == 'chef_payment_link' and metadata.get('payment_link_id'):
                try:
                    from chefs.webhooks import handle_payment_link_completed
                    handle_payment_link_completed(session)
                    logger.info(
                        "Processed chef payment link via webhook",
                        extra={
                            "payment_link_id": metadata.get('payment_link_id'),
                            "session_id": getattr(session, 'id', None),
                        },
                    )
                    return Response({"status": "success"})
                except Exception as pl_err:
                    logger.error(
                        f"Chef payment link webhook handling failed: {pl_err}",
                        exc_info=True,
                    )
                    return Response({"error": str(pl_err)}, status=400)

            # Handle chef meal payments via parent Order
            if metadata.get('order_type') == 'chef_meal':
                from meals.models import Order
                parent_order_id = metadata.get('order_id')
                logger.info(f"Processing payment confirmation for Order {parent_order_id}")
                try:
                    # Use transaction to make the order/payment update atomic
                    with transaction.atomic():
                        order = Order.objects.select_for_update().select_related('customer').get(id=parent_order_id)

                        # Ensure ChefMealOrder rows exist for all chef-linked OrderMeals
                        order_meals = order.ordermeal_set.filter(chef_meal_event__isnull=False).select_related('chef_meal_event')
                        for order_meal in order_meals:
                            ensure_chef_meal_order(
                                order=order,
                                event=order_meal.chef_meal_event,
                                customer=order.customer,
                                quantity=order_meal.quantity or 1,
                                unit_price=order_meal.chef_meal_event.current_price,
                            )

                        # Idempotency: acknowledge if already paid
                        if getattr(order, 'is_paid', False):
                            return Response({"received": True})

                        # Mark order paid and move to an active status
                        order.is_paid = True
                        order.status = 'In Progress'
                        order.save(update_fields=['is_paid', 'status'])

                        # Confirm associated chef items (locked for update)
                        chef_items = (
                            ChefMealOrder.objects.select_for_update()
                            .filter(order=order, status__in=['placed'])
                            .select_related('meal_event')
                        )
                        for item in chef_items:
                            item.payment_intent_id = session.payment_intent
                            try:
                                item.mark_as_paid()
                            except Exception:
                                item.status = 'confirmed'
                                item.save(update_fields=['status', 'stripe_payment_intent_id'])

                        # Order-level payment log (best-effort inside tx)
                        try:
                            total_amount = float(getattr(session, 'amount_total', 0) or 0) / 100.0
                            PaymentLog.objects.create(
                                order=order,
                                user=order.customer,
                                action='charge',
                                amount=total_amount,
                                stripe_id=session.payment_intent,
                                status='succeeded',
                                details={
                                    'session_id': session.id,
                                    'payment_intent_id': session.payment_intent,
                                    'checkout_completed_at': timezone.now().isoformat()
                                }
                            )
                        except Exception as _log_e:
                            logger.warning(f"Failed to log payment for Order {order.id}: {_log_e}")

                    logger.info(f"Successfully processed payment for Order {parent_order_id}")
                    return Response({"received": True})
                except Order.DoesNotExist:
                    logger.error(f"Could not find Order {parent_order_id} for completed Stripe session")
                    n8n_traceback = {
                        'error': f"Could not find Order {parent_order_id} for completed Stripe session",
                        'source': 'stripe_webhook',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                    return Response({"error": "Order not found"}, status=404)
                except Exception as e:
                    logger.error(f"Error processing chef meal payment: {str(e)}", exc_info=True)
                    n8n_traceback = {
                        'error': str(e),
                        'source': 'stripe_webhook',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                    return Response({"error": str(e)}, status=400)
            
            # Handle regular meal plan payments
            elif metadata.get('order_type') in ['meal_plan', 'standard', None]:  # Handle all order types
                order_id = metadata.get('order_id')
                logger.info(f"Processing payment confirmation for meal plan order {order_id}")
                try:
                    # Get the order
                    from meals.models import Order, PaymentLog
                    order = Order.objects.get(id=order_id)
                    
                    # Update order status
                    order.is_paid = True
                    order.status = 'Confirmed'
                    order.save()
                    
                    # Process any associated ChefMealOrders
                    chef_meal_orders = ChefMealOrder.objects.filter(order=order)
                    for chef_order in chef_meal_orders:
                        # Use mark_as_paid to properly update order counts and pricing
                        chef_order.mark_as_paid()
                        
                        # Update Stripe payment details
                        chef_order.payment_intent_id = session.payment_intent
                        chef_order.save(update_fields=['payment_intent_id'])
                        
                        logger.info(f"Updated ChefMealOrder {chef_order.id} to confirmed status and updated meal counts")
                    
                    # Create payment log
                    PaymentLog.objects.create(
                        order=order,
                        user=order.customer,
                        action='charge',
                        amount=float(session.amount_total) / 100,  # Convert cents to dollars
                        stripe_id=session.payment_intent,
                        status='succeeded',
                        details={
                            'session_id': session.id,
                            'payment_intent_id': session.payment_intent,
                            'checkout_completed_at': timezone.now().isoformat()
                        }
                    )
                    
                    # You could add email notification here
                    # send_payment_confirmation_email.delay(order_id)
                    
                    
                except Order.DoesNotExist:
                    logger.error(f"Could not find meal plan order {order_id} for completed Stripe session")
                    # n8n traceback
                    n8n_traceback = {
                        'error': f"Could not find meal plan order {order_id} for completed Stripe session",
                        'source': 'stripe_webhook',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                    return Response({"error": "Order not found"}, status=404)
                except Exception as e:
                    logger.error(f"Error processing meal plan payment: {str(e)}", exc_info=True)
                    # n8n traceback
                    n8n_traceback = {
                        'error': str(e),
                        'source': 'stripe_webhook',
                        'traceback': traceback.format_exc()
                    }
                    requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
                    return Response({"error": str(e)}, status=400)
        
        elif event.type == 'payment_intent.succeeded':
            # Handle direct payment intents (not through checkout)
            payment_intent = event.data.object
            
            # Check if we have any orders with this payment intent
            chef_meal_orders = ChefMealOrder.objects.filter(stripe_payment_intent_id=payment_intent.id)
            
            if chef_meal_orders.exists():
                for order in chef_meal_orders:
                    # Update status if not already confirmed
                    if order.status == STATUS_PLACED:
                        # Use mark_as_paid to properly update order counts and pricing
                        order.mark_as_paid()
                        
                        # Create payment log if it doesn't exist
                        if not PaymentLog.objects.filter(chef_meal_order=order, stripe_id=payment_intent.id).exists():
                            PaymentLog.objects.create(
                                chef_meal_order=order,
                                user=order.customer,
                                chef=order.meal_event.chef,
                                action='charge',
                                amount=float(order.price_paid * order.quantity),
                                stripe_id=payment_intent.id,
                                status='succeeded',
                                details={'payment_intent_id': payment_intent.id}
                            )
        
        # Handle membership subscription events
        elif event.type == 'customer.subscription.created':
            subscription = event.data.object
            try:
                from memberships.webhooks import handle_subscription_created
                handle_subscription_created(subscription)
                logger.info(f"Processed subscription.created for {subscription.id}")
            except Exception as sub_err:
                logger.error(f"Membership subscription.created handling failed: {sub_err}", exc_info=True)
        
        elif event.type == 'customer.subscription.updated':
            subscription = event.data.object
            try:
                from memberships.webhooks import handle_subscription_updated
                handle_subscription_updated(subscription)
                logger.info(f"Processed subscription.updated for {subscription.id}")
            except Exception as sub_err:
                logger.error(f"Membership subscription.updated handling failed: {sub_err}", exc_info=True)
        
        elif event.type == 'customer.subscription.deleted':
            subscription = event.data.object
            try:
                from memberships.webhooks import handle_subscription_deleted
                handle_subscription_deleted(subscription)
                logger.info(f"Processed subscription.deleted for {subscription.id}")
            except Exception as sub_err:
                logger.error(f"Membership subscription.deleted handling failed: {sub_err}", exc_info=True)
        
        elif event.type == 'invoice.paid':
            invoice = event.data.object
            try:
                from memberships.webhooks import handle_invoice_paid
                handle_invoice_paid(invoice)
                logger.info(f"Processed invoice.paid for {invoice.id}")
            except Exception as inv_err:
                logger.error(f"Membership invoice.paid handling failed: {inv_err}", exc_info=True)
        
        elif event.type == 'invoice.payment_failed':
            invoice = event.data.object
            try:
                from memberships.webhooks import handle_invoice_payment_failed
                handle_invoice_payment_failed(invoice)
                logger.warning(f"Processed invoice.payment_failed for {invoice.id}")
            except Exception as inv_err:
                logger.error(f"Membership invoice.payment_failed handling failed: {inv_err}", exc_info=True)

        # ---- Dispute / chargeback handling ----
        elif event.type == 'charge.dispute.created':
            dispute = event.data.object
            charge_id = dispute.charge
            payment_intent_id = dispute.payment_intent
            disputed_amount = dispute.amount  # in minor units (cents)
            logger.warning(
                f"Dispute created: {dispute.id} for charge {charge_id}, "
                f"amount={disputed_amount}, reason={dispute.reason}"
            )
            try:
                # Find the related order via payment intent
                from meals.models import Order
                order = None
                chef = None

                # Try to find via ChefMealOrder first
                chef_meal_order = ChefMealOrder.objects.filter(
                    stripe_payment_intent_id=payment_intent_id
                ).select_related('meal_event__chef', 'order').first()

                if chef_meal_order:
                    order = chef_meal_order.order
                    chef = chef_meal_order.meal_event.chef if chef_meal_order.meal_event else None

                if not order and payment_intent_id:
                    # Try to find via PaymentLog
                    log = PaymentLog.objects.filter(
                        stripe_id=payment_intent_id, action='charge'
                    ).select_related('order', 'chef').first()
                    if log:
                        order = log.order
                        chef = log.chef

                # Attempt to reverse the transfer to recover funds from chef
                if payment_intent_id and chef:
                    try:
                        # Get the charge to find the transfer
                        charge = stripe.Charge.retrieve(charge_id)
                        transfer_id = getattr(charge, 'transfer', None)
                        if transfer_id:
                            stripe.Transfer.create_reversal(
                                transfer_id,
                                amount=disputed_amount,
                                metadata={
                                    'dispute_id': dispute.id,
                                    'reason': 'dispute_recovery',
                                },
                            )
                            logger.info(
                                f"Reversed transfer {transfer_id} for dispute {dispute.id}"
                            )
                    except stripe.error.StripeError as rev_err:
                        logger.error(
                            f"Failed to reverse transfer for dispute {dispute.id}: {rev_err}"
                        )

                # Log the dispute
                PaymentLog.objects.create(
                    order=order,
                    chef=chef,
                    action='dispute',
                    amount=disputed_amount / 100.0,
                    stripe_id=dispute.id,
                    status='needs_response',
                    details={
                        'charge_id': charge_id,
                        'payment_intent_id': payment_intent_id,
                        'reason': dispute.reason,
                        'dispute_amount': disputed_amount,
                        'currency': dispute.currency,
                    },
                )
            except Exception as disp_err:
                logger.error(f"Dispute webhook handling failed: {disp_err}", exc_info=True)

        # ---- Refund event tracking ----
        elif event.type == 'charge.refunded':
            charge = event.data.object
            payment_intent_id = getattr(charge, 'payment_intent', None)
            refunded_amount = charge.amount_refunded  # cumulative refunded in minor units
            logger.info(
                f"Charge refunded: {charge.id}, refunded_amount={refunded_amount}"
            )
            try:
                order = None
                if payment_intent_id:
                    log = PaymentLog.objects.filter(
                        stripe_id=payment_intent_id, action='charge'
                    ).select_related('order').first()
                    if log:
                        order = log.order

                PaymentLog.objects.create(
                    order=order,
                    action='refund',
                    amount=refunded_amount / 100.0,
                    stripe_id=charge.id,
                    status='succeeded',
                    details={
                        'payment_intent_id': payment_intent_id,
                        'refund_event': True,
                    },
                )
            except Exception as ref_err:
                logger.error(f"charge.refunded webhook handling failed: {ref_err}", exc_info=True)

        # ---- Transfer tracking ----
        elif event.type == 'transfer.created':
            transfer = event.data.object
            logger.info(
                f"Transfer created: {transfer.id}, amount={transfer.amount} {transfer.currency}, "
                f"destination={transfer.destination}"
            )
            try:
                # Find the chef by connected account ID
                chef = None
                try:
                    stripe_acct = StripeConnectAccount.objects.select_related('chef').get(
                        stripe_account_id=transfer.destination
                    )
                    chef = stripe_acct.chef
                except StripeConnectAccount.DoesNotExist:
                    pass

                PaymentLog.objects.create(
                    chef=chef,
                    action='transfer',
                    amount=transfer.amount / 100.0,
                    stripe_id=transfer.id,
                    status='created',
                    details={
                        'destination': transfer.destination,
                        'currency': transfer.currency,
                        'source_transaction': getattr(transfer, 'source_transaction', None),
                    },
                )
            except Exception as xfer_err:
                logger.error(f"transfer.created webhook handling failed: {xfer_err}", exc_info=True)

        # ---- Payout tracking (chef payouts to their bank) ----
        elif event.type in ('payout.paid', 'payout.failed'):
            payout = event.data.object
            payout_status = 'paid' if event.type == 'payout.paid' else 'failed'
            logger.info(
                f"Payout {payout_status}: {payout.id}, amount={payout.amount} {payout.currency}"
            )
            try:
                # Payout events on connected accounts come with the account header
                connected_account_id = getattr(event, 'account', None)
                chef = None
                if connected_account_id:
                    try:
                        stripe_acct = StripeConnectAccount.objects.select_related('chef').get(
                            stripe_account_id=connected_account_id
                        )
                        chef = stripe_acct.chef
                    except StripeConnectAccount.DoesNotExist:
                        pass

                PaymentLog.objects.create(
                    chef=chef,
                    action='payout',
                    amount=payout.amount / 100.0,
                    stripe_id=payout.id,
                    status=payout_status,
                    details={
                        'currency': payout.currency,
                        'arrival_date': payout.arrival_date,
                        'failure_code': getattr(payout, 'failure_code', None),
                        'failure_message': getattr(payout, 'failure_message', None),
                        'connected_account': connected_account_id,
                    },
                )
            except Exception as po_err:
                logger.error(f"Payout webhook handling failed: {po_err}", exc_info=True)

        # ---- Connected account status changes ----
        elif event.type == 'account.updated':
            account = event.data.object
            account_id = account.id
            logger.info(f"Account updated: {account_id}")
            try:
                stripe_acct = StripeConnectAccount.objects.get(
                    stripe_account_id=account_id
                )
                # Sync active status based on Stripe's verification
                charges_enabled = getattr(account, 'charges_enabled', False)
                payouts_enabled = getattr(account, 'payouts_enabled', False)
                details_submitted = getattr(account, 'details_submitted', False)
                new_active = charges_enabled and payouts_enabled and details_submitted

                if stripe_acct.is_active != new_active:
                    stripe_acct.is_active = new_active
                    stripe_acct.save(update_fields=['is_active', 'updated_at'])
                    logger.info(
                        f"StripeConnectAccount {account_id} is_active changed to {new_active} "
                        f"(charges={charges_enabled}, payouts={payouts_enabled}, details={details_submitted})"
                    )
            except StripeConnectAccount.DoesNotExist:
                logger.debug(f"No local StripeConnectAccount for {account_id}, ignoring")
            except Exception as acct_err:
                logger.error(f"account.updated webhook handling failed: {acct_err}", exc_info=True)

        return Response({"status": "success"})
        
    except Exception as e:
        logger.error(f"Error processing Stripe webhook: {str(e)}", exc_info=True)
        # n8n traceback
        n8n_traceback = {
            'error': str(e),
            'source': 'stripe_webhook',
            'traceback': traceback.format_exc()
        }
        requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
        return Response({"error": str(e)}, status=400)

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def api_chef_meal_events(request):
    """
    GET: Get a list of chef meal events with optional filtering.
    
    Query parameters:
    - my_events: If 'true', returns only events created by the requesting chef
    - postal_code: If provided, filters events by postal code
    - page: For pagination
    - page_size: Number of items per page (default 12, max 100)
    
    POST: Create a new chef meal event. Only authenticated users who are chefs can access this endpoint.
    
    Required fields:
    - meal: Integer, ID of the meal to be served
    - event_date: Date, date of the event
    - event_time: Time, time of the event
    - order_cutoff_time: DateTime, deadline for placing orders
    - base_price: Decimal, base price per serving
    - min_price: Decimal, minimum price per serving as orders increase
    - max_orders: Integer, maximum number of orders available
    - min_orders: Integer, minimum number of orders required
    - description: String, description of the event
    
    Optional fields:
    - special_instructions: String, additional instructions for the event
    - status: String, status of the event (default: 'scheduled')
    """
    if request.method == 'GET':
        try:
            queryset = ChefMealEvent.objects.all()
            user = request.user
            my_events = request.query_params.get('my_events') == 'true'
            upcoming = request.query_params.get('upcoming') == 'true'
            chef_id = request.query_params.get('chef_id')
            chef_username = request.query_params.get('chef_username')

            # Ownership filter (requires auth)
            if my_events and user.is_authenticated:
                try:
                    chef = Chef.objects.get(user=user)
                    queryset = queryset.filter(chef=chef)
                except Chef.DoesNotExist:
                    queryset = ChefMealEvent.objects.none()
            # Public filters by chef
            elif chef_id:
                queryset = queryset.filter(chef_id=chef_id)
            elif chef_username:
                queryset = queryset.filter(chef__user__username__iexact=chef_username)


            # Filter by postal code if provided
            postal_code = request.query_params.get('postal_code')
            if postal_code:
                # Optional: filter events by chefs serving this postal code
                from shared.services.location_service import LocationService
                normalized = LocationService.normalize(postal_code)
                queryset = queryset.filter(chef__serving_postalcodes__code=normalized)

            if upcoming:
                # Consider events with future cutoff or future event datetime
                now = timezone.now()
                queryset = queryset.filter(order_cutoff_time__gte=now)
            
            # Order by date and time
            queryset = queryset.order_by('event_date', 'event_time')
            # Paginate the results
            paginator = ChefMealEventPagination()
            page = paginator.paginate_queryset(queryset, request)
            
            if page is not None:
                serializer = ChefMealEventSerializer(page, many=True)
                paginated_response = paginator.get_paginated_response(serializer.data)
                # Return standardized response with status code
                return standardize_response(
                    status="success",
                    message="Chef meal events retrieved successfully",
                    details=paginated_response.data,
                    status_code=200
                )
            
            serializer = ChefMealEventSerializer(queryset, many=True)
            # Return standardized response with status code
            return standardize_response(
                status="success",
                message="Chef meal events retrieved successfully",
                details=serializer.data,
                status_code=200
            )
        except Exception as e:
            logger.error(f"Error retrieving chef meal events: {str(e)}", exc_info=True)
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_events',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return standardize_response(
                status="error",
                message="Unable to retrieve meal events. Please try again later.",
                status_code=500
            )
    
    elif request.method == 'POST':
        # Verify the user is a chef
        try:
            chef = request.user.chef
        except Chef.DoesNotExist:
            # n8n traceback
            n8n_traceback = {
                'error': f"User {request.user.username} is not a chef",
                'source': 'api_chef_meal_events',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return standardize_response(
                status="error",
                message="You must be registered as a chef to create meal events.",
                status_code=403
            )
        
        # Verify chef has completed Stripe onboarding
        try:
            stripe_account = StripeConnectAccount.objects.get(chef=chef)
            if not stripe_account.stripe_account_id or not stripe_account.is_active:
                return standardize_response(
                    status="error",
                    message="You must complete payment setup before creating meal events.",
                    status_code=403
                )
        except StripeConnectAccount.DoesNotExist:
            # n8n traceback
            n8n_traceback = {
                'error': f"User {request.user.username} is not a chef",
                'source': 'api_chef_meal_events',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return standardize_response(
                status="error",
                message="You must complete payment setup before creating meal events.",
                status_code=403
            )
        
        data = request.data
        # List of required fields
        required_fields = ['meal', 'event_date', 'event_time', 'order_cutoff_time',
                          'base_price', 'min_price', 'max_orders', 'min_orders', 'description']
        
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            return standardize_response(
                status="error",
                message=f"Missing required fields: {', '.join(missing)}",
                status_code=400
            )
        
        # Validate meal belongs to chef
        try:
            meal = Meal.objects.get(id=data['meal'])
            if meal.chef.id != chef.id:
                return standardize_response(
                    status="error",
                    message="You can only create events for your own meals.",
                    status_code=403
                )
        except Meal.DoesNotExist:
            # n8n traceback
            n8n_traceback = {
                'error': f"Meal not found with id={data['meal']}",
                'source': 'api_chef_meal_events',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return standardize_response(
                status="error",
                message="Meal not found.",
                status_code=404
            )
        
        # Validate date is in the future
        try:
            event_date = datetime.strptime(data['event_date'], '%Y-%m-%d').date()
            event_time = datetime.strptime(data['event_time'], '%H:%M').time()
            
            # Get the chef's timezone
            chef_timezone = chef.user.timezone if hasattr(chef.user, 'timezone') else 'UTC'
            try:
                chef_zinfo = ZoneInfo(chef_timezone)
            except Exception:
                chef_zinfo = ZoneInfo("UTC")
            
            # Get current time in chef's timezone
            now = timezone.now().astimezone(chef_zinfo)
            
            # Create event datetime in chef's timezone
            event_datetime_naive = datetime.combine(event_date, event_time)
            event_datetime = timezone.make_aware(event_datetime_naive, chef_zinfo)
            
            # Compare with current time in chef's timezone
            if event_datetime <= now:
                return standardize_response(
                    status="error",
                    message=f"Event date and time must be in the future in your local timezone ({chef_timezone}).",
                    status_code=400
                )
                
            # Parse and validate order cutoff time in chef's timezone
            order_cutoff_time = dateutil.parser.parse(data['order_cutoff_time'])
            
            # If cutoff time is naive, assume it's in chef's timezone
            if not timezone.is_aware(order_cutoff_time):
                order_cutoff_time = timezone.make_aware(order_cutoff_time, chef_zinfo)
            
            # Compare with event time in chef's timezone
            if order_cutoff_time >= event_datetime:
                return standardize_response(
                    status="error",
                    message="Order cutoff time must be before the event time.",
                    status_code=400
                )
                
            # Also check cutoff time is in the future
            if order_cutoff_time <= now:
                return standardize_response(
                    status="error",
                    message=f"Order cutoff time must be in the future in your local timezone ({chef_timezone}).",
                    status_code=400
                )
                
            # Convert order_cutoff_time to UTC for storage
            order_cutoff_time = order_cutoff_time.astimezone(py_tz.utc)
            
        except ValueError:
            # n8n traceback
            n8n_traceback = {
                'error': f"Invalid date or time format. Please use YYYY-MM-DD for dates and HH:MM for times.",
                'source': 'api_chef_meal_events',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return standardize_response(
                status="error",
                message="Invalid date or time format. Please use YYYY-MM-DD for dates and HH:MM for times.",
                status_code=400
            )
        
        try:
            # Before creating a new event, check for an existing CANCELLED event
            try:
                meal_id = data.get('meal')
                event_date_str = data.get('event_date')
                event_time_str = data.get('event_time')
                
                # Parse the date and time using your existing logic
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date() if isinstance(event_date_str, str) else event_date_str
                event_time = datetime.strptime(event_time_str, '%H:%M').time() if isinstance(event_time_str, str) else event_time_str
                
                # Look for existing cancelled events with the same key parameters
                existing_cancelled_event = ChefMealEvent.objects.filter(
                    chef=chef,
                    meal_id=meal_id,
                    event_date=event_date,
                    event_time=event_time,
                    status=STATUS_CANCELLED
                ).first()
                
                if existing_cancelled_event:
                    # Update the existing cancelled event instead of creating a new one
                    # Your existing code for parsing the request data...
                    
                    # Update the event with new values
                    existing_cancelled_event.order_cutoff_time = order_cutoff_time  # Use your parsed value
                    existing_cancelled_event.base_price = data.get('base_price')
                    existing_cancelled_event.min_price = data.get('min_price')
                    existing_cancelled_event.max_orders = data.get('max_orders')
                    existing_cancelled_event.min_orders = data.get('min_orders')
                    existing_cancelled_event.description = data.get('description')
                    existing_cancelled_event.special_instructions = data.get('special_instructions', '')
                    existing_cancelled_event.status = STATUS_SCHEDULED
                    existing_cancelled_event.current_price = data.get('base_price')
                    existing_cancelled_event.orders_count = 0
                    existing_cancelled_event.cancellation_reason = None
                    existing_cancelled_event.cancellation_date = None
                    
                    existing_cancelled_event.save()
                    
                    return standardize_response(
                        status="success",
                        message="Chef meal event reactivated successfully",
                        details=ChefMealEventSerializer(existing_cancelled_event).data,
                        status_code=201
                    )
            except Exception as e:
                # If there's an error checking for cancelled events, log it but continue with normal creation
                logger.warning(f"Error checking for cancelled events: {str(e)}")
                # n8n traceback
                n8n_traceback = {
                    'error': str(e),
                    'source': 'api_chef_meal_events',
                    'traceback': traceback.format_exc()
                }
                requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            
            # Your existing code to create a new event if no cancelled event was found...
            
            # Create the Chef Meal Event
            event = ChefMealEvent(
                chef=chef,
                meal=meal,
                event_date=event_date,
                event_time=event_time,
                order_cutoff_time=order_cutoff_time,  # Use the UTC value for storage
                base_price=data['base_price'],
                min_price=data['min_price'],
                max_orders=data['max_orders'],
                min_orders=data['min_orders'],
                description=data['description'],
                special_instructions=data.get('special_instructions', ''),
                status=data.get('status', STATUS_SCHEDULED),
                current_price=data['base_price']  # Initialize current price to base price
            )
            
            event.save()

            
            serializer = ChefMealEventSerializer(event)
            return standardize_response(
                status="success",
                message="Chef meal event created successfully",
                details=serializer.data,
                status_code=201
            )
        
        except django.db.utils.IntegrityError as e:
            error_str = str(e)
            # Check if this is a violation of the unique_chef_meal_per_date constraint
            if "unique_chef_meal_per_date_and_type" in error_str:
                return standardize_response(
                    status="error",
                    message=f"You already have a {data['meal_type']} meal scheduled for {data['start_date']}. Please choose a different date or meal type.",
                    status_code=400
                )
            # Check if this is a violation of the unique_meal_per_creator constraint
            elif "unique_meal_per_creator" in error_str:
                return standardize_response(
                    status="error",
                    message=f"You already have a meal named '{data['name']}'. Please choose a different name.",
                    status_code=400
                )
            # Generic message for other integrity errors
            else:
                # Create a more user-friendly message without exposing database field names
                logger.warning(f"Database constraint violation: {error_str}")
                
                # You can customize this message based on the specific database fields
                if "chef_id" in error_str and "start_date" in error_str:
                    return standardize_response(
                        status="error",
                        message="You already have a meal scheduled for this date. Please choose a different date or meal type.",
                        status_code=400
                    )
                elif "name" in error_str and "creator_id" in error_str:
                    return standardize_response(
                        status="error",
                        message="You already have a meal with this name. Please choose a different name.",
                        status_code=400
                    )
                # Default generic message
                else:
                    return standardize_response(
                        status="error",
                        message="This meal cannot be created because it would create a duplicate. Please check your inputs and try again.",
                        status_code=400
                    )
                
        except Exception as e:
            logger.error(f"Error creating chef meal event: {str(e)}", exc_info=True)
            # n8n traceback
            n8n_traceback = {
                'error': str(e),
                'source': 'api_chef_meal_events',
                'traceback': traceback.format_exc()
            }
            requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
            return standardize_response(
                status="error",
                message="Unable to create meal event. Please try again later.",
                status_code=500
            )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_cancel_chef_meal_event(request, event_id):
    """
    Cancel a chef meal event. Only the chef who created the event can cancel it.
    
    Required fields:
    - reason: String, reason for cancellation
    """
    from meals.email_service import send_order_cancellation_email, send_refund_notification_email
    # Verify the user is a chef

    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        logger.error(f"User {request.user.username} is not a chef")
        # n8n traceback
        n8n_traceback = {
            'error': f"User {request.user.username} is not a chef",
            'source': 'api_cancel_chef_meal_event',
            'traceback': traceback.format_exc()
        }
        requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the event and verify ownership
    try:

        event = get_object_or_404(ChefMealEvent, id=event_id)

        
        if event.chef.id != chef.id:
            logger.error(f"Permission denied: Event chef ID {event.chef.id} does not match requesting chef ID {chef.id}")
            return standardize_response(
                status="error",
                message="You don't have permission to cancel this event.",
                status_code=403
            )
        
        # Check if the event is already canceled
        if event.status == STATUS_CANCELLED:
            logger.warning(f"Event {event_id} is already cancelled")
            return standardize_response(
                status="error",
                message="This event is already cancelled.",
                status_code=400
            )
        
        # Get cancellation reason
        reason = request.data.get('reason')
        if not reason:
            logger.warning(f"No cancellation reason provided for event {event_id}")
            return standardize_response(
                status="error",
                message="Cancellation reason is required.",
                status_code=400
            )
        
        with transaction.atomic():
            # Cancel any existing orders

            orders = ChefMealOrder.objects.filter(meal_event=event, status__in=[STATUS_PLACED, STATUS_CONFIRMED])

            
            for order in orders:

                # Update order status
                order.status = STATUS_CANCELLED
                order.cancellation_reason = 'Event cancelled by chef: ' + reason
                order.save()

                
                # Process refunds if payment was made
                if order.payment_intent_id:

                    try:
                        # Create a refund in Stripe
                        stripe.api_key = settings.STRIPE_SECRET_KEY
                        if order.payment_intent_id:

                            refund = stripe.Refund.create(
                                payment_intent=order.payment_intent_id
                            )
                            order.refund_id = refund.id
                            order.refund_status = 'processed'
                            order.save()

                            
                            # Send refund notification email
                            send_refund_notification_email(order.id)
                    except Exception as e:

                        logger.error(f"Error processing refund for order {order.id}: {str(e)}")
                        order.refund_status = 'failed'
                        order.save()
                
                # Send cancellation email
                send_order_cancellation_email(order.id)
            
            # Update event status

            event.status = STATUS_CANCELLED
            event.cancellation_reason = reason
            event.cancellation_date = timezone.now()
            event.save()
        

        logger.info(f"Cancelled chef meal event {event_id}")
        
        return standardize_response(
            status="success",
            message="Chef meal event cancelled successfully",
            status_code=200
        )
        
    except ChefMealEvent.DoesNotExist:

        logger.error(f"Event with ID {event_id} not found")
        return standardize_response(
            status="error",
            message="Event not found.",
            status_code=404
        )
    except Exception as e:

        logger.error(f"Error cancelling chef meal event: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error cancelling chef meal event: {str(e)}",
            status_code=500
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_duplicate_meal_share(request, event_id):
    """
    Duplicate an existing meal share (ChefMealEvent) with new date/time.
    
    This allows chefs to quickly recreate a previous meal share without re-entering
    all the details. The duplicated meal share will have:
    - Same meal, pricing, capacity settings
    - Reset orders_count to 0
    - Status set to 'scheduled'
    - current_price set to base_price
    - New date/time (provided in request body or defaults that chef must change)
    
    Request body (all optional - will copy from original if not provided):
    - event_date: New date for the meal share (YYYY-MM-DD)
    - event_time: New time for the meal share (HH:MM)
    - order_cutoff_date: New cutoff date
    - order_cutoff_time: New cutoff time
    - base_price: Override base price
    - min_price: Override min price
    - max_orders: Override max orders
    - min_orders: Override min orders
    - description: Override description
    - special_instructions: Override special instructions
    """
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        logger.error(f"User {request.user.username} is not a chef")
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    try:
        original = get_object_or_404(ChefMealEvent, id=event_id)
        
        # Verify ownership
        if original.chef.id != chef.id:
            logger.error(f"Permission denied: Event chef ID {original.chef.id} does not match requesting chef ID {chef.id}")
            return standardize_response(
                status="error",
                message="You don't have permission to duplicate this meal share.",
                status_code=403
            )
        
        # Get data from request or use original values
        data = request.data
        
        # Parse new date/time or use placeholder values that signal "needs to be updated"
        event_date = data.get('event_date')
        event_time = data.get('event_time', original.event_time.strftime('%H:%M') if original.event_time else '18:00')
        order_cutoff_date = data.get('order_cutoff_date')
        order_cutoff_time = data.get('order_cutoff_time', '12:00')
        
        # If no new date provided, use tomorrow as default
        if not event_date:
            tomorrow = timezone.now().date() + timedelta(days=1)
            event_date = tomorrow.strftime('%Y-%m-%d')
        
        if not order_cutoff_date:
            order_cutoff_date = event_date
        
        # Build cutoff datetime
        try:
            cutoff_datetime = datetime.strptime(f"{order_cutoff_date} {order_cutoff_time}", "%Y-%m-%d %H:%M")
            cutoff_datetime = timezone.make_aware(cutoff_datetime) if timezone.is_naive(cutoff_datetime) else cutoff_datetime
        except ValueError:
            cutoff_datetime = timezone.now() + timedelta(hours=24)
        
        # Create the new meal share
        new_event = ChefMealEvent.objects.create(
            chef=chef,
            meal=original.meal,
            event_date=event_date,
            event_time=event_time,
            order_cutoff_time=cutoff_datetime,
            max_orders=int(data.get('max_orders', original.max_orders)),
            min_orders=int(data.get('min_orders', original.min_orders)),
            base_price=Decimal(str(data.get('base_price', original.base_price))),
            current_price=Decimal(str(data.get('base_price', original.base_price))),  # Reset to base
            min_price=Decimal(str(data.get('min_price', original.min_price))),
            orders_count=0,
            status=STATUS_SCHEDULED,
            description=data.get('description', original.description or ''),
            special_instructions=data.get('special_instructions', original.special_instructions or '')
        )
        
        logger.info(f"Duplicated meal share {event_id} to new meal share {new_event.id}")
        
        serializer = ChefMealEventSerializer(new_event)
        return standardize_response(
            status="success",
            message="Meal share duplicated successfully",
            data=serializer.data,
            status_code=201
        )
        
    except ChefMealEvent.DoesNotExist:
        logger.error(f"Meal share with ID {event_id} not found")
        return standardize_response(
            status="error",
            message="Meal share not found.",
            status_code=404
        )
    except Exception as e:
        logger.error(f"Error duplicating meal share: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error duplicating meal share: {str(e)}",
            status_code=500
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_meals(request):
    """
    Get a list of meals with optional filtering.
    
    Default behavior:
    - Returns only meals created by the requesting chef
    
    Query parameters:
    - chef_meals: If 'true', returns only meals created by the requesting chef (this is now the default behavior)
    - all_meals: If 'true', returns all meals from all chefs (requires admin/staff permissions)
    """
    try:
        user = request.user
        # Default behavior: return chef's own meals
        try:
            chef = Chef.objects.get(user=user)
            queryset = Meal.objects.filter(chef=chef).order_by('-created_date')
        except Chef.DoesNotExist:
            # User is not a chef, return empty set
            queryset = Meal.objects.none()
            
        # Only administrators can request all meals by setting all_meals=true
        if request.query_params.get('all_meals') == 'true' and user.is_staff:
            queryset = Meal.objects.all().order_by('-created_date')
        
        serializer = MealSerializer(queryset, many=True)
        # Return standardized response with status code
        return standardize_response(
            status="success",
            message="Meals retrieved successfully",
            details=serializer.data,
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error retrieving meals: {str(e)}")
        # n8n traceback
        n8n_traceback = {
            'error': str(e),
            'source': 'api_get_meals',
            'traceback': traceback.format_exc()
        }
        requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
        return standardize_response(
            status="error",
            message=f"Error retrieving meals: {str(e)}",
            status_code=500
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_create_chef_meal(request):
    """
    Create a new chef meal. Only authenticated users who are chefs can access this endpoint.
    
    Required fields:
    - name: String, the name of the meal
    - description: String, detailed description of the meal
    - meal_type: String, one of 'Breakfast', 'Lunch', 'Dinner'
    - start_date: Date, the first day the meal is available
    - price: Decimal, the price of the meal
    - dishes: List, at least one dish must be provided
    
    Optional fields:
    - image: File, an image of the meal
    - dietary_preferences: List, dietary preferences related to the meal
    - custom_dietary_preferences: List, custom dietary preferences
    """
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        # n8n traceback
        n8n_traceback = {
            'error': f"User {request.user.username} is not a chef",
            'source': 'api_create_chef_meal',
            'traceback': traceback.format_exc()
        }
        requests.post(os.getenv('N8N_TRACEBACK_URL'), json=n8n_traceback)
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    data = request.data
    # List of required fields for chef-created meals
    required_fields = ['name', 'description', 'meal_type', 'start_date', 'price']
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        return standardize_response(
            status="error",
            message=f"Missing required fields: {', '.join(missing)}",
            status_code=400
        )
    
    # Pre-process many-to-many fields to ensure they're valid before creating the meal
    dishes = data.get('dishes')
    if not dishes:
        return standardize_response(
            status="error",
            message="At least one dish must be provided.",
            status_code=400
        )
    
    try:
        # Helper function to safely parse JSON or handle values that are already parsed
        def parse_json_field(field_value):
            if not field_value:
                return []
                
            # Handle case where the value is a list containing a JSON string (common in form data)
            if isinstance(field_value, list) and len(field_value) == 1:
                try:
                    return json.loads(field_value[0])
                except (json.JSONDecodeError, TypeError):
                    # If it's not valid JSON, return as is
                    return field_value
            
            # Try to parse as JSON if it's a string
            if isinstance(field_value, str):
                try:
                    return json.loads(field_value)
                except json.JSONDecodeError:
                    # If it's not valid JSON, return as is
                    return [field_value]
            
            # If it's already a list or other object, return as is
            return field_value
            
        # Parse the data fields
        dish_ids = parse_json_field(dishes)
        dietary_prefs = parse_json_field(data.get('dietary_preferences', []))
        custom_prefs = parse_json_field(data.get('custom_dietary_preferences', []))
        
        # Use the refactored create_meal utility function

        
        # Call create_meal with chef-specific parameters, but skip compatibility analysis for now
        result = create_meal(
            user_id=request.user.id,
            name=data['name'],
            description=data['description'],
            meal_type=data['meal_type'],
        )
        
        if result['status'] != 'success':
            return standardize_response(
                status="error",
                message=result['message'],
                status_code=400
            )
        
        # Get the created meal
        meal = Meal.objects.get(id=result['meal']['id'])
        meal.chef = chef
        meal.price = data['price']
        # Use a transaction to handle the many-to-many relationships
        with transaction.atomic():
            # Set many-to-many relationships
            if dish_ids:
                meal.dishes.set(dish_ids)
            if dietary_prefs:
                # Ensure dietary_prefs is always a list/iterable
                if isinstance(dietary_prefs, int):
                    meal.dietary_preferences.set([dietary_prefs])
                else:
                    meal.dietary_preferences.set(dietary_prefs)
            if custom_prefs:
                meal.custom_dietary_preferences.set(custom_prefs)
            
            # Attach image if provided
            if 'image' in request.FILES:
                meal.image = request.FILES['image']
        
        meal.save()
        
        # Generate and store meal embedding
        from meals.meal_embedding import prepare_meal_representation
        from shared.utils import get_embedding
        
        # Generate meal representation for embedding
        meal_representation = prepare_meal_representation(meal)
        
        # Get embedding from OpenAI
        try:
            embedding = get_embedding(meal_representation)
            if embedding:
                meal.meal_embedding = embedding
                meal.save(update_fields=['meal_embedding'])
                logger.info(f"Successfully generated embedding for chef meal {meal.id}")
            else:
                logger.warning(f"Could not generate embedding for chef meal {meal.id}")
                # Generate embedding
                from meals.meal_embedding import generate_meal_embedding
                generate_meal_embedding(meal.id)
        except Exception as e:
            logger.error(f"Error generating embedding for chef meal {meal.id}: {e}")
            # Try again
            from meals.meal_embedding import generate_meal_embedding
            generate_meal_embedding(meal.id)
        

        
        # Serialize and return the meal
        serializer = MealSerializer(meal)
        return standardize_response(
            status="success",
            message="Meal created successfully",
            details=serializer.data,
            status_code=201
        )
    
    except Exception as e:
        # Log the exception for debugging
        logger.error(f"Error creating meal: {str(e)}")
        traceback.print_exc()
        return standardize_response(
            status="error",
            message=f"Error creating meal. We will look into it and get back to you. Apologies for the inconvenience.",
            status_code=400
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_dishes(request):
    """
    Get a list of dishes with optional filtering.
    
    Default behavior:
    - Returns only dishes created by the requesting chef
    
    Query parameters:
    - chef_dishes: If 'true', returns only dishes created by the requesting chef (this is now the default behavior)
    - all_dishes: If 'true', returns all dishes from all chefs (requires admin/staff permissions)
    """
    try:
        user = request.user
        
        # Default behavior: return chef's own dishes
        try:
            chef = Chef.objects.get(user=user)
            queryset = Dish.objects.filter(chef=chef).order_by('name')
        except Chef.DoesNotExist:
            # User is not a chef, return empty set
            queryset = Dish.objects.none()
            
        # Only administrators can request all dishes by setting all_dishes=true
        if request.query_params.get('all_dishes') == 'true' and user.is_staff:
            queryset = Dish.objects.all().order_by('name')
            logger.info(f"Admin user {user.username} retrieved all dishes")
        
        serializer = DishSerializer(queryset, many=True)
        # Return standardized response with status code
        return standardize_response(
            status="success",
            message="Dishes retrieved successfully",
            details=serializer.data,
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error retrieving dishes: {str(e)}")
        return standardize_response(
            status="error",
            message=f"Error retrieving dishes: {str(e)}",
            status_code=500
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_create_chef_dish(request):
    """
    Create a new dish. Only authenticated users who are chefs can access this endpoint.
    
    Required fields:
    - name: String, the name of the dish
    
    Optional fields:
    - ingredients: List, IDs of ingredients to include in the dish
    - featured: Boolean, whether the dish is featured
    """
    # Verify the user is a chef
    logger.info(f"Dish create request: {request.data}")
    
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    data = request.data
    # Check for required fields
    if not data.get('name'):
        return standardize_response(
            status="error",
            message="Dish name is required.",
            status_code=400
        )
    
    # Check for existing dish with same name for this chef
    dish_name = data.get('name').strip()
    if Dish.objects.filter(chef=chef, name__iexact=dish_name).exists():
        return standardize_response(
            status="error",
            message=f"You already have a dish named '{dish_name}'.",
            status_code=400
        )
    
    try:
        # Create the dish instance
        dish = Dish(
            name=dish_name,
            chef=chef,
            featured=data.get('featured', False)
        )
        # Save the basic dish first
        dish.save()
        logger.info(f"Created basic dish: {dish.id} - {dish.name}")
        
        # Validate and add ingredients if provided
        ingredients_list = data.get('ingredients', [])
        valid_ingredients = []
        
        if ingredients_list:
            try:
                # Convert string IDs to integers if needed
                if isinstance(ingredients_list, str):
                    try:
                        # Handle case where it might be a JSON string
                        import json
                        ingredients_list = json.loads(ingredients_list)
                    except json.JSONDecodeError:
                        # Handle case where it might be comma-separated 
                        ingredients_list = [int(i.strip()) for i in ingredients_list.split(',') if i.strip()]
                
                # Ensure we have a list of integers
                if not isinstance(ingredients_list, list):
                    ingredients_list = [ingredients_list]
                
                # Validate ingredients
                for ingredient_id in ingredients_list:
                    try:
                        ingredient = Ingredient.objects.get(id=ingredient_id)
                        # Verify the ingredient belongs to this chef or is public
                        if ingredient.chef == chef:
                            valid_ingredients.append(ingredient_id)
                        else:
                            logger.warning(f"Ingredient {ingredient_id} doesn't belong to chef {chef.id}")
                    except Ingredient.DoesNotExist:
                        logger.warning(f"Ingredient {ingredient_id} doesn't exist")
                
                # Set valid ingredients
                if valid_ingredients:
                    dish.ingredients.set(valid_ingredients)
                    # The dish's nutritional information will be updated on save()
                    dish.save()
                    logger.info(f"Added {len(valid_ingredients)} ingredients to dish {dish.id}")
                
            except Exception as e:
                logger.error(f"Error processing ingredients: {str(e)}")
                # Continue with creation even if ingredients fail
        
        serializer = DishSerializer(dish)
        return standardize_response(
            status="success",
            message="Dish created successfully",
            details=serializer.data,
            status_code=201
        )
    
    except Exception as e:
        logger.error(f"Error creating dish: {str(e)}", exc_info=True)
        # If a dish was partially created, delete it to avoid orphaned records
        try:
            if 'dish' in locals() and dish.id:
                dish.delete()
                logger.info(f"Deleted partially created dish {dish.id} due to error")
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {str(cleanup_error)}")
            
        return standardize_response(
            status="error",
            message=f"Error creating dish: {str(e)}",
            status_code=500
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_dish_by_id(request, dish_id):
    """
    API endpoint to retrieve details for a specific dish.
    """
    try:
        dish = get_object_or_404(Dish, id=dish_id)
        
        # Check if the dish belongs to the requesting chef (if chef_dishes=true)
        if request.query_params.get('chef_dishes') == 'true':
            try:
                chef = Chef.objects.get(user=request.user)
                if dish.chef != chef:
                    return standardize_response(
                        status="error",
                        message="You don't have permission to view this dish.",
                        status_code=403
                    )
            except Chef.DoesNotExist:
                return standardize_response(
                    status="error",
                    message="User is not a chef.",
                    status_code=403
                )
        
        serializer = DishSerializer(dish)
        return standardize_response(
            status="success",
            message="Dish retrieved successfully",
            details=serializer.data,
            status_code=200
        )
    except Dish.DoesNotExist:
        return standardize_response(
            status="error", 
            message="Dish not found", 
            status_code=404
        )
    except Exception as e:
        return standardize_response(
            status="error",
            message=f"Error retrieving dish: {str(e)}",
            status_code=500
        )

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def api_update_chef_dish(request, dish_id):
    """
    Update an existing dish. Only authenticated users who are chefs can access this endpoint,
    and they can only update their own dishes.
    
    Fields that can be updated:
    - name: String, the name of the dish
    - ingredients: List, IDs of ingredients to include in the dish
    - featured: Boolean, whether the dish is featured
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Dish update request for dish_id {dish_id}: {request.data}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the dish and verify ownership
    try:
        dish = get_object_or_404(Dish, id=dish_id)
        if dish.chef.id != chef.id:
            return standardize_response(
                status="error",
                message="You don't have permission to edit this dish.",
                status_code=403
            )
    except Dish.DoesNotExist:
        return standardize_response(
            status="error",
            message="Dish not found.",
            status_code=404
        )
    
    data = request.data
    
    # Check for name changes and validate
    if 'name' in data and data['name']:
        new_name = data['name'].strip()
        
        # If name is changing, check for duplicates
        if new_name.lower() != dish.name.lower():
            if Dish.objects.filter(chef=chef, name__iexact=new_name).exists():
                return standardize_response(
                    status="error",
                    message=f"You already have a dish named '{new_name}'.",
                    status_code=400
                )
            dish.name = new_name
    
    # Update featured status if provided
    if 'featured' in data:
        dish.featured = data['featured']
    
    try:
        # Save basic dish data
        dish.save()
        
        # Update ingredients if provided
        if 'ingredients' in data:
            ingredients_list = data.get('ingredients', [])
            valid_ingredients = []
            
            try:
                # Convert string IDs to integers if needed
                if isinstance(ingredients_list, str):
                    try:
                        import json
                        ingredients_list = json.loads(ingredients_list)
                    except json.JSONDecodeError:
                        ingredients_list = [int(i.strip()) for i in ingredients_list.split(',') if i.strip()]
                
                # Ensure we have a list of integers
                if not isinstance(ingredients_list, list):
                    ingredients_list = [ingredients_list]
                
                # Validate ingredients
                for ingredient_id in ingredients_list:
                    try:
                        ingredient = Ingredient.objects.get(id=ingredient_id)
                        # Verify the ingredient belongs to this chef
                        if ingredient.chef == chef:
                            valid_ingredients.append(ingredient_id)
                        else:
                            logger.warning(f"Ingredient {ingredient_id} doesn't belong to chef {chef.id}")
                    except Ingredient.DoesNotExist:
                        logger.warning(f"Ingredient {ingredient_id} doesn't exist")
                
                # Set valid ingredients (this will replace existing ingredients)
                dish.ingredients.set(valid_ingredients)
                # Update nutritional information
                dish.save()
                logger.info(f"Updated dish {dish.id} with {len(valid_ingredients)} ingredients")
                
            except Exception as e:
                logger.error(f"Error updating ingredients: {str(e)}")
                # We can continue without failing the entire update
        
        serializer = DishSerializer(dish)
        return standardize_response(
            status="success",
            message="Dish updated successfully",
            details=serializer.data,
            status_code=200
        )
    
    except Exception as e:
        logger.error(f"Error updating dish: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error updating dish: {str(e)}",
            status_code=500
        )

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def api_delete_chef_dish(request, dish_id):
    """
    Delete a dish. Only authenticated users who are chefs can access this endpoint,
    and they can only delete their own dishes.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Dish delete request for dish_id {dish_id}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the dish and verify ownership
    try:
        dish = get_object_or_404(Dish, id=dish_id)
        if dish.chef.id != chef.id:
            return standardize_response(
                status="error",
                message="You don't have permission to delete this dish.",
                status_code=403
            )
        
        # Check if dish is used in any meals before deleting
        meals_using_dish = Meal.objects.filter(dishes=dish)
        if meals_using_dish.exists():
            meal_names = ", ".join([meal.name for meal in meals_using_dish[:5]])
            return standardize_response(
                status="error",
                message=f"Cannot delete dish because it is used in the following meals: {meal_names}" + 
                         (f"... and {meals_using_dish.count() - 5} more" if meals_using_dish.count() > 5 else ""),
                status_code=400
            )
        
        # Store the name for the response
        dish_name = dish.name
        
        # Delete the dish
        dish.delete()
        logger.info(f"Deleted dish {dish_id} - {dish_name}")
        
        return standardize_response(
            status="success",
            message=f"Dish '{dish_name}' was deleted successfully",
            status_code=200
        )
        
    except Dish.DoesNotExist:
        return standardize_response(
            status="error",
            message="Dish not found.",
            status_code=404
        )
    except Exception as e:
        logger.error(f"Error deleting dish: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error deleting dish: {str(e)}",
            status_code=500
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_ingredients(request):
    """
    Get a list of ingredients with optional filtering.
    
    Default behavior:
    - Returns only ingredients created by the requesting chef
    
    Query parameters:
    - chef_ingredients: If 'true', returns only ingredients created by the requesting chef (this is now the default behavior)
    - all_ingredients: If 'true', returns all ingredients from all chefs (requires admin/staff permissions)
    """
    try:
        user = request.user
        
        # Default behavior: return chef's own ingredients
        try:
            chef = Chef.objects.get(user=user)
            queryset = Ingredient.objects.filter(chef=chef).order_by('name')
        except Chef.DoesNotExist:
            # User is not a chef, return empty set
            queryset = Ingredient.objects.none()
            
        # Only administrators can request all ingredients by setting all_ingredients=true
        if request.query_params.get('all_ingredients') == 'true' and user.is_staff:
            queryset = Ingredient.objects.all().order_by('name')
            logger.info(f"Admin user {user.username} retrieved all ingredients")
        
        serializer = IngredientSerializer(queryset, many=True)
        return standardize_response(
            status="success",
            message="Ingredients retrieved successfully",
            details=serializer.data,
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error retrieving ingredients: {str(e)}")
        return standardize_response(
            status="error",
            message=f"Error retrieving ingredients: {str(e)}",
            status_code=500
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_create_chef_ingredient(request):
    """
    Create a new ingredient. Only authenticated users who are chefs can access this endpoint.
    
    Required fields:
    - name: String, the name of the ingredient
    
    Optional fields:
    - calories: Float, calories per standard serving
    - fat: Decimal, fat content in grams
    - carbohydrates: Decimal, carbohydrate content in grams
    - protein: Decimal, protein content in grams
    """
    logger.info(f"Ingredient create request: {request.data}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    data = request.data
    # Check for required fields
    if not data.get('name'):
        return standardize_response(
            status="error",
            message="Ingredient name is required.",
            status_code=400
        )
    
    # Check for existing ingredient with same name for this chef
    ingredient_name = data.get('name').strip()
    if Ingredient.objects.filter(chef=chef, name__iexact=ingredient_name).exists():

        return standardize_response(
            status="error",
            message=f"You already have an ingredient named '{ingredient_name}'.",
            status_code=400
        )
    
    try:
        # Create the ingredient instance
        ingredient = Ingredient(
            name=ingredient_name,
            chef=chef,
            calories=data.get('calories'),
            fat=data.get('fat'),
            carbohydrates=data.get('carbohydrates'),
            protein=data.get('protein')
        )
        
        # Save the ingredient
        ingredient.save()
        logger.info(f"Created ingredient: {ingredient.id} - {ingredient.name}")
        
        serializer = IngredientSerializer(ingredient)
        return standardize_response(
            status="success",
            message="Ingredient created successfully",
            details=serializer.data,
            status_code=201
        )
    
    except Exception as e:
        logger.error(f"Error creating ingredient: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error creating ingredient: {str(e)}",
            status_code=500
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_ingredient_by_id(request, ingredient_id):
    """
    API endpoint to retrieve details for a specific ingredient.
    """
    try:
        ingredient = get_object_or_404(Ingredient, id=ingredient_id)
        
        # Check if the ingredient belongs to the requesting chef (if chef_ingredients=true)
        if request.query_params.get('chef_ingredients') == 'true':
            try:
                chef = Chef.objects.get(user=request.user)
                if ingredient.chef != chef:
                    return standardize_response(
                        status="error",
                        message="You don't have permission to view this ingredient.",
                        status_code=403
                    )
            except Chef.DoesNotExist:
                return standardize_response(
                    status="error",
                    message="User is not a chef.",
                    status_code=403
                )
        
        serializer = IngredientSerializer(ingredient)
        return standardize_response(
            status="success",
            message="Ingredient retrieved successfully",
            details=serializer.data,
            status_code=200
        )
    except Ingredient.DoesNotExist:
        return standardize_response(
            status="error", 
            message="Ingredient not found", 
            status_code=404
        )
    except Exception as e:
        return standardize_response(
            status="error",
            message=f"Error retrieving ingredient: {str(e)}",
            status_code=500
        )

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def api_update_chef_ingredient(request, ingredient_id):
    """
    Update an existing ingredient. Only authenticated users who are chefs can access this endpoint,
    and they can only update their own ingredients.
    
    Fields that can be updated:
    - name: String, the name of the ingredient
    - calories: Float, calories per standard serving
    - fat: Decimal, fat content in grams
    - carbohydrates: Decimal, carbohydrate content in grams
    - protein: Decimal, protein content in grams
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Ingredient update request for ingredient_id {ingredient_id}: {request.data}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the ingredient and verify ownership
    try:
        ingredient = get_object_or_404(Ingredient, id=ingredient_id)
        if ingredient.chef.id != chef.id:
            return standardize_response(
                status="error",
                message="You don't have permission to edit this ingredient.",
                status_code=403
            )
    except Ingredient.DoesNotExist:
        return standardize_response(
            status="error",
            message="Ingredient not found.",
            status_code=404
        )
    
    data = request.data
    
    # Check for name changes and validate
    if 'name' in data and data['name']:
        new_name = data['name'].strip()
        
        # If name is changing, check for duplicates
        if new_name.lower() != ingredient.name.lower():
            if Ingredient.objects.filter(chef=chef, name__iexact=new_name).exists():
                return standardize_response(
                    status="error",
                    message=f"You already have an ingredient named '{new_name}'.",
                    status_code=400
                )
            ingredient.name = new_name
    
    # Update nutritional information if provided
    if 'calories' in data:
        ingredient.calories = data['calories']
    if 'fat' in data:
        ingredient.fat = data['fat']
    if 'carbohydrates' in data:
        ingredient.carbohydrates = data['carbohydrates']
    if 'protein' in data:
        ingredient.protein = data['protein']
    
    try:
        # Save the updated ingredient
        ingredient.save()
        logger.info(f"Updated ingredient {ingredient.id}")
        
        serializer = IngredientSerializer(ingredient)
        return standardize_response(
            status="success",
            message="Ingredient updated successfully",
            details=serializer.data,
            status_code=200
        )
    
    except Exception as e:
        logger.error(f"Error updating ingredient: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error updating ingredient: {str(e)}",
            status_code=500
        )

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def api_delete_chef_ingredient(request, ingredient_id):
    """
    Delete an ingredient. Only authenticated users who are chefs can access this endpoint,
    and they can only delete their own ingredients.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Ingredient delete request for ingredient_id {ingredient_id}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the ingredient and verify ownership
    try:
        ingredient = get_object_or_404(Ingredient, id=ingredient_id)
        if ingredient.chef.id != chef.id:
            return standardize_response(
                status="error",
                message="You don't have permission to delete this ingredient.",
                status_code=403
            )
        
        # Check if ingredient is used in any dishes before deleting
        dishes_using_ingredient = Dish.objects.filter(ingredients=ingredient)
        if dishes_using_ingredient.exists():
            dish_names = ", ".join([dish.name for dish in dishes_using_ingredient[:5]])
            return standardize_response(
                status="error",
                message=f"Cannot delete ingredient because it is used in the following dishes: {dish_names}" + 
                         (f"... and {dishes_using_ingredient.count() - 5} more" if dishes_using_ingredient.count() > 5 else ""),
                status_code=400
            )
        
        # Store the name for the response
        ingredient_name = ingredient.name
        
        # Delete the ingredient
        ingredient.delete()
        logger.info(f"Deleted ingredient {ingredient_id} - {ingredient_name}")
        
        return standardize_response(
            status="success",
            message=f"Ingredient '{ingredient_name}' was deleted successfully",
            status_code=200
        )
        
    except Ingredient.DoesNotExist:
        return standardize_response(
            status="error",
            message="Ingredient not found.",
            status_code=404
        )
    except Exception as e:
        logger.error(f"Error deleting ingredient: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error deleting ingredient: {str(e)}",
            status_code=500
        )

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_chef_meal_detail(request, meal_id):
    """
    Retrieve, update, or delete a chef meal.
    GET: Retrieve meal details.
    PUT/PATCH: Update meal details.
    DELETE: Delete the meal.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Meal detail request for meal_id {meal_id}, method: {request.method}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the meal and verify ownership
    try:
        meal = get_object_or_404(Meal, id=meal_id)
        
        # Verify that the requesting user is the owner of the meal
        if meal.chef != chef:
            return standardize_response(
                status="error",
                message="You don't have permission to access this meal.",
                status_code=403
            )
        
        if request.method == 'GET':
            serializer = MealSerializer(meal)
            return standardize_response(
                status="success",
                message="Meal retrieved successfully",
                details=serializer.data,
                status_code=200
            )
        
        elif request.method in ['PUT', 'PATCH']:
            data = request.data
            
            # Check for name changes and validate
            if 'name' in data and data['name']:
                new_name = data['name'].strip()
                
                # If name is changing, check for duplicates
                if new_name.lower() != meal.name.lower():
                    if Meal.objects.filter(chef=chef, name__iexact=new_name).exists():
                        return standardize_response(
                            status="error",
                            message=f"You already have a meal named '{new_name}'.",
                            status_code=400
                        )
                    meal.name = new_name
            
            # Update other simple fields
            if 'description' in data:
                meal.description = data.get('description', '')
            
            if 'price' in data:
                try:
                    meal.price = Decimal(str(data.get('price')))
                except (InvalidOperation, TypeError):
                    return standardize_response(
                        status="error",
                        message="Invalid price format.",
                        status_code=400
                    )
            
            if 'meal_type' in data:
                meal_type = data.get('meal_type')
                if meal_type in dict(Meal.MEAL_TYPE_CHOICES):
                    meal.meal_type = meal_type
                else:
                    return standardize_response(
                        status="error",
                        message=f"Invalid meal type. Must be one of: {', '.join(dict(Meal.MEAL_TYPE_CHOICES))}",
                        status_code=400
                    )
            
            try:
                # Save basic meal data
                meal.save()
                
                # Update dishes if provided
                if 'dish_ids' in data:
                    dish_ids = data.get('dish_ids', [])
                    valid_dishes = []
                    
                    try:
                        # Convert string IDs to integers if needed
                        if isinstance(dish_ids, str):
                            try:
                                import json
                                dish_ids = json.loads(dish_ids)
                            except json.JSONDecodeError:
                                dish_ids = [int(i.strip()) for i in dish_ids.split(',') if i.strip()]
                        
                        # Ensure we have a list of integers
                        if not isinstance(dish_ids, list):
                            dish_ids = [dish_ids]
                        
                        # Validate dishes
                        for dish_id in dish_ids:
                            try:
                                dish = Dish.objects.get(id=dish_id)
                                # Verify the dish belongs to this chef
                                if dish.chef == chef:
                                    valid_dishes.append(dish_id)
                                else:
                                    logger.warning(f"Dish {dish_id} doesn't belong to chef {chef.id}")
                            except Dish.DoesNotExist:
                                logger.warning(f"Dish {dish_id} doesn't exist")
                        
                        # Set valid dishes
                        meal.dishes.set(valid_dishes)
                        logger.info(f"Updated meal {meal.id} with {len(valid_dishes)} dishes")
                        
                    except Exception as e:
                        logger.error(f"Error updating dishes: {str(e)}")
                        # We can continue without failing the entire update
                
                # Update dietary preferences if provided
                if 'dietary_preferences' in data:
                    dietary_prefs = []
                    pref_ids = data.get('dietary_preferences', [])
                    
                    if isinstance(pref_ids, str):
                        try:
                            import json
                            pref_ids = json.loads(pref_ids)
                        except json.JSONDecodeError:
                            pref_ids = [int(i.strip()) for i in pref_ids.split(',') if i.strip()]
                    
                    if not isinstance(pref_ids, list):
                        pref_ids = [pref_ids]
                    
                    for pref_id in pref_ids:
                        try:
                            pref = DietaryPreference.objects.get(id=pref_id)
                            dietary_prefs.append(pref_id)
                        except DietaryPreference.DoesNotExist:
                            logger.warning(f"Dietary preference {pref_id} doesn't exist")
                    
                    meal.dietary_preferences.set(dietary_prefs)
                    logger.info(f"Updated meal {meal.id} with {len(dietary_prefs)} dietary preferences")
                
                # Update custom dietary preferences if provided
                if 'custom_dietary_preferences' in data:
                    custom_prefs = []
                    custom_pref_ids = data.get('custom_dietary_preferences', [])
                    
                    if isinstance(custom_pref_ids, str):
                        try:
                            import json
                            custom_pref_ids = json.loads(custom_pref_ids)
                        except json.JSONDecodeError:
                            custom_pref_ids = [int(i.strip()) for i in custom_pref_ids.split(',') if i.strip()]
                    
                    if not isinstance(custom_pref_ids, list):
                        custom_pref_ids = [custom_pref_ids]
                    
                    for pref_id in custom_pref_ids:
                        try:
                            pref = CustomDietaryPreference.objects.get(id=pref_id)
                            if pref.chef == chef:
                                custom_prefs.append(pref_id)
                            else:
                                logger.warning(f"Custom dietary preference {pref_id} doesn't belong to chef {chef.id}")
                        except CustomDietaryPreference.DoesNotExist:
                            logger.warning(f"Custom dietary preference {pref_id} doesn't exist")
                    
                    meal.custom_dietary_preferences.set(custom_prefs)
                    logger.info(f"Updated meal {meal.id} with {len(custom_prefs)} custom dietary preferences")
                
                serializer = MealSerializer(meal)
                return standardize_response(
                    status="success",
                    message="Meal updated successfully",
                    details=serializer.data,
                    status_code=200
                )
                
            except Exception as e:
                logger.error(f"Error updating meal: {str(e)}", exc_info=True)
                return standardize_response(
                    status="error",
                    message=f"Error updating meal: {str(e)}",
                    status_code=500
                )
        
        elif request.method == 'DELETE':
            # Check if meal is used in any events before deleting
            events_using_meal = ChefMealEvent.objects.filter(meal=meal)
            if events_using_meal.exists():
                event_dates = ", ".join([str(event.event_date) for event in events_using_meal[:5]])
                return standardize_response(
                    status="error",
                    message=f"Cannot delete meal because it is used in events on the following dates: {event_dates}" + 
                             (f"... and {events_using_meal.count() - 5} more" if events_using_meal.count() > 5 else ""),
                    status_code=400
                )
            
            # Store the name for the response
            meal_name = meal.name
            
            # Delete the meal
            meal.delete()
            logger.info(f"Deleted meal {meal_id} - {meal_name}")
            
            return standardize_response(
                status="success",
                message=f"Meal '{meal_name}' was deleted successfully",
                status_code=200
            )
    
    except Meal.DoesNotExist:
        return standardize_response(
            status="error",
            message="Meal not found.",
            status_code=404
        )
    except Exception as e:
        logger.error(f"Error processing meal request: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error processing meal request: {str(e)}",
            status_code=500
        )

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def api_update_chef_meal(request, meal_id):
    """
    Update an existing chef meal.
    Supports both PUT and PATCH methods.
    Handles multipart/form-data for image uploads.
    """
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Get the meal and verify ownership
    try:
        meal = Meal.objects.get(id=meal_id, chef=chef)
    except Meal.DoesNotExist:
        return standardize_response(
            status="error",
            message="Meal not found or you don't have permission to edit it.",
            status_code=404
        )
    
    data = request.data
    logger.info(f"Updating meal {meal_id} with data: {data}")
    
    try:
        # Helper function to safely parse JSON or handle values that are already parsed
        def parse_json_field(field_value):
            if not field_value:
                return []
                
            # Handle case where the value is a list containing a JSON string
            if isinstance(field_value, list) and len(field_value) == 1:
                try:
                    return json.loads(field_value[0])
                except (json.JSONDecodeError, TypeError):
                    return field_value
            
            # Try to parse as JSON if it's a string
            if isinstance(field_value, str):
                try:
                    return json.loads(field_value)
                except json.JSONDecodeError:
                    return [field_value]
            
            # If it's already a list or other object, return as is
            return field_value
        
        # Use a transaction for all updates
        with transaction.atomic():
            # Update basic fields if provided
            if 'name' in data:
                meal.name = data['name']
            if 'description' in data:
                meal.description = data['description']
            if 'meal_type' in data:
                meal.meal_type = data['meal_type']
            if 'start_date' in data:
                meal.start_date = data['start_date']
            if 'price' in data:
                meal.price = data['price']
            
            # Save basic field updates
            meal.save()
            
            # Update many-to-many relationships if provided
            dishes = data.get('dishes')
            if dishes:
                dish_ids = parse_json_field(dishes)
                meal.dishes.set(dish_ids)
            
            dietary_prefs = data.get('dietary_preferences')
            if dietary_prefs:
                pref_ids = parse_json_field(dietary_prefs)
                meal.dietary_preferences.set(pref_ids)
            
            custom_prefs = data.get('custom_dietary_preferences')
            if custom_prefs:
                custom_pref_ids = parse_json_field(custom_prefs)
                meal.custom_dietary_preferences.set(custom_pref_ids)
            
            # Update image if provided
            if 'image' in request.FILES:
                meal.image = request.FILES['image']
                meal.save()
        
        # Update meal embedding since the meal details have changed
        from meals.meal_embedding import prepare_meal_representation
        from shared.utils import get_embedding
        
        # Generate updated meal representation for embedding
        meal_representation = prepare_meal_representation(meal)
        
        # Get updated embedding from OpenAI
        try:
            embedding = get_embedding(meal_representation)
            if embedding:
                meal.meal_embedding = embedding
                meal.save(update_fields=['meal_embedding'])
                logger.info(f"Successfully updated embedding for chef meal {meal.id}")
            else:
                logger.warning(f"Could not update embedding for chef meal {meal.id}")
                # Try again
                from meals.meal_embedding import generate_meal_embedding
                generate_meal_embedding(meal.id)
        except Exception as e:
            logger.error(f"Error updating embedding for chef meal {meal.id}: {e}")
            # Try again
            from meals.meal_embedding import generate_meal_embedding
            generate_meal_embedding(meal.id)
        
        # Serialize and return the updated meal
        serializer = MealSerializer(meal)
        return standardize_response(
            status="success",
            message="Meal updated successfully",
            details=serializer.data,
            status_code=200  # Explicitly set status code for success
        )
    
    except Exception as e:
        logger.error(f"Error updating meal: {str(e)}")
        traceback.print_exc()
        return standardize_response(
            status="error",
            message=f"Error updating meal: {str(e)}",
            status_code=400
        )

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def api_update_chef_meal_event(request, event_id):
    """
    Update an existing chef meal event. Only authenticated users who are chefs can access this endpoint.
    
    Required fields: None (at least one field should be provided)
    
    Optional fields:
    - meal: Integer, ID of the meal to be served
    - event_date: Date, date of the event
    - event_time: Time, time of the event
    - order_cutoff_time: DateTime, deadline for placing orders
    - base_price: Decimal, base price per serving
    - min_price: Decimal, minimum price per serving as orders increase
    - max_orders: Integer, maximum number of orders available
    - min_orders: Integer, minimum number of orders required
    - description: String, description of the event
    - special_instructions: String, additional instructions for the event
    - status: String, status of the event
    """
    logger.info(f"Chef meal event update request for event_id {event_id}: {request.data}")
    
    # Verify the user is a chef
    try:
        chef = request.user.chef
    except Chef.DoesNotExist:
        return standardize_response(
            status="error",
            message="User is not a chef.",
            status_code=403
        )
    
    # Retrieve the event and verify ownership
    try:
        event = ChefMealEvent.objects.get(id=event_id)
        if event.chef.id != chef.id:
            return standardize_response(
                status="error",
                message="You don't have permission to edit this event.",
                status_code=403
            )
    except ChefMealEvent.DoesNotExist:
        return standardize_response(
            status="error",
            message="Event not found.",
            status_code=404
        )
    
    data = request.data
    
    # Check if orders already exist and prevent price changes
    if event.orders_count > 0:
        if 'base_price' in data or 'min_price' in data:
            return standardize_response(
                status="error",
                message="Cannot change pricing after orders have been placed.",
                status_code=400
            )
    
    try:
        # Track if the meal is being changed
        old_meal_id = event.meal.id
        new_meal_id = None
        meal_changed = False
        
        with transaction.atomic():
            # Update meal if provided
            if 'meal' in data:
                try:
                    meal = Meal.objects.get(id=data['meal'])
                    # Verify the meal belongs to this chef
                    if meal.chef.id != chef.id:
                        return standardize_response(
                            status="error",
                            message="You can only use your own meals for events.",
                            status_code=403
                        )
                    event.meal = meal
                    new_meal_id = meal.id
                    meal_changed = (old_meal_id != new_meal_id)
                except Meal.DoesNotExist:
                    return standardize_response(
                        status="error",
                        message="Meal not found.",
                        status_code=404
                    )
            
            # Update event fields if provided
            if 'event_date' in data:
                try:
                    event_date = datetime.strptime(data['event_date'], '%Y-%m-%d').date()
                    event.event_date = event_date
                except ValueError:
                    return standardize_response(
                        status="error",
                        message="Invalid date format. Please use YYYY-MM-DD.",
                        status_code=400
                    )
            
            if 'event_time' in data:
                try:
                    event_time = datetime.strptime(data['event_time'], '%H:%M').time()
                    event.event_time = event_time
                except ValueError:
                    return standardize_response(
                        status="error",
                        message="Invalid time format. Please use HH:MM.",
                        status_code=400
                    )
            
            if 'order_cutoff_time' in data:
                try:
                    # Get the chef's timezone
                    chef_timezone = event.chef.user.timezone if hasattr(event.chef.user, 'timezone') else 'UTC'
                    try:
                        chef_zinfo = ZoneInfo(chef_timezone)
                    except Exception:
                        chef_zinfo = ZoneInfo("UTC")
                    
                    # Parse the cutoff time
                    order_cutoff_time = dateutil.parser.parse(data['order_cutoff_time'])
                    
                    # If cutoff time is naive, assume it's in chef's timezone
                    if not timezone.is_aware(order_cutoff_time):
                        order_cutoff_time = timezone.make_aware(order_cutoff_time, chef_zinfo)
                    
                    # Get current time in chef's timezone    
                    now = timezone.now().astimezone(chef_zinfo)
                    
                    # Ensure the new cutoff time is still in the future
                    if order_cutoff_time <= now:
                        return standardize_response(
                            status="error",
                            message=f"Order cutoff time must be in the future in your local timezone ({chef_timezone}).",
                            status_code=400
                        )
                    
                    # Convert to UTC for storage
                    event.order_cutoff_time = order_cutoff_time.astimezone(py_tz.utc)
                except ValueError:
                    return standardize_response(
                        status="error",
                        message="Invalid datetime format for order_cutoff_time.",
                        status_code=400
                    )
            
            # Validate event time is after cutoff time
            # Construct event_datetime using potentially updated event_date/event_time
            current_event_date = event.event_date
            current_event_time = event.event_time
            
            # Get chef's timezone for validation
            chef_timezone = event.chef.user.timezone if hasattr(event.chef.user, 'timezone') else 'UTC'
            try:
                chef_zinfo = ZoneInfo(chef_timezone)
            except Exception:
                chef_zinfo = ZoneInfo("UTC")
            
            # Create event datetime in chef's timezone
            event_datetime_naive = datetime.combine(current_event_date, current_event_time)
            event_datetime = timezone.make_aware(event_datetime_naive, chef_zinfo)
            
            # Compare with cutoff time in chef's timezone
            cutoff_time = event.order_cutoff_time.astimezone(chef_zinfo)
            
            if cutoff_time >= event_datetime:
                return standardize_response(
                    status="error",
                    message="Order cutoff time must be before the event time.",
                    status_code=400
                )
            
            # Update price fields
            if 'base_price' in data:
                try:
                    # SECURITY CHECK: Prevent price increases if orders already exist
                    new_base_price = Decimal(str(data['base_price']))
                    
                    # If we have existing orders, enforce price protection
                    if event.orders_count > 0:
                        # Allow price decreases but not increases
                        if new_base_price > event.base_price:
                            return standardize_response(
                                status="error",
                                message="Cannot increase base price after orders have been placed. This protects customers from unexpected price changes.",
                                status_code=400
                            )
                    
                    event.base_price = new_base_price
                    # Also update current price if orders_count is 0
                    if event.orders_count == 0:
                        event.current_price = event.base_price
                except (InvalidOperation, TypeError):
                    return standardize_response(
                        status="error",
                        message="Invalid base price format.",
                        status_code=400
                    )
            
            if 'min_price' in data:
                try:
                    new_min_price = Decimal(str(data['min_price']))
                    
                    # SECURITY CHECK: Prevent min_price increases if orders already exist
                    if event.orders_count > 0:
                        if new_min_price > event.min_price:
                            return standardize_response(
                                status="error",
                                message="Cannot increase minimum price after orders have been placed. This protects customers from unexpected price changes.",
                                status_code=400
                            )
                    
                    event.min_price = new_min_price
                except (InvalidOperation, TypeError):
                    return standardize_response(
                        status="error",
                        message="Invalid minimum price format.",
                        status_code=400
                    )
            
            # Update order limits
            if 'max_orders' in data:
                try:
                    new_max_orders = int(data['max_orders'])
                    if new_max_orders < event.orders_count:
                        return standardize_response(
                            status="error",
                            message=f"Maximum orders cannot be less than current orders count ({event.orders_count}).",
                            status_code=400
                        )
                    event.max_orders = new_max_orders
                except ValueError:
                    return standardize_response(
                        status="error",
                        message="Invalid format for max_orders. Must be an integer.",
                        status_code=400
                    )
            
            if 'min_orders' in data:
                try:
                    event.min_orders = int(data['min_orders'])
                except ValueError:
                    return standardize_response(
                        status="error",
                        message="Invalid format for min_orders. Must be an integer.",
                        status_code=400
                    )
            
            # Update text fields
            if 'description' in data:
                event.description = data['description']
            
            if 'special_instructions' in data:
                event.special_instructions = data['special_instructions']
            
            # Update status if provided and valid
            if 'status' in data:
                new_status = data['status']
                valid_statuses = [s[0] for s in ChefMealEvent.STATUS_CHOICES]
                if new_status in valid_statuses:
                    event.status = new_status
                else:
                    return standardize_response(
                        status="error",
                        message=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                        status_code=400
                    )
            
            # Save the updated event
            event.save()
        
        # Return the updated event
        serializer = ChefMealEventSerializer(event)
        return standardize_response(
            status="success",
            message="Chef meal event updated successfully",
            details=serializer.data,
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"Error updating chef meal event: {str(e)}", exc_info=True)
        return standardize_response(
            status="error",
            message=f"Error updating chef meal event: {str(e)}",
            status_code=500
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_chef_meals_by_postal_code(request):
    """
    Get all chef-created meals available for the user's postal code for a specific week,
    optionally filtered by meal type, date range, and dietary compatibility.
    
    Query parameters:
    - meal_type: Filter by meal type (Breakfast, Lunch, Dinner)
    - week_start_date: Start date of the week (YYYY-MM-DD format)
    - chef_id: Filter by specific chef
    - include_compatible_only: Set to 'true' to only show compatible meals (default: false)
    """
    try:
        user = request.user
        
        # Check if user has an address with postal code
        if not hasattr(user, 'address') or not user.address or not user.address.normalized_postalcode:
            return Response({
                'status': 'error',
                'message': 'User does not have a postal code set in their profile',
                'code': 'missing_postal_code'
            }, status=400)

        user_postal_code = user.address.normalized_postalcode
        
        # Get query parameters
        meal_type = request.query_params.get('meal_type')
        week_start_date_str = request.query_params.get('week_start_date')
        date_str = request.query_params.get('date')  # Keep for backward compatibility
        chef_id = request.query_params.get('chef_id')
        include_compatible_only = request.query_params.get('include_compatible_only', 'false').lower() == 'true'
        
        # Set date range - prioritize week view if provided, otherwise use single date
        start_date = None
        end_date = None
        
        if week_start_date_str:
            try:
                start_date = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
                end_date = start_date + timedelta(days=6)  # 7-day week
            except ValueError:
                return Response({
                    'status': 'error',
                    'message': 'Invalid week_start_date format. Use YYYY-MM-DD',
                    'code': 'invalid_date_format'
                }, status=400)
        elif date_str:
            # Backward compatibility for single-day view
            try:
                start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                end_date = start_date  # Single day
            except ValueError:
                return Response({
                    'status': 'error',
                    'message': 'Invalid date format. Use YYYY-MM-DD',
                    'code': 'invalid_date_format'
                }, status=400)
        else:
            # Default to current week if no date specified
            today = timezone.now().date()
            start_date = today
            end_date = today + timedelta(days=6)
        
        # Find all chefs that serve this postal code
        from local_chefs.models import ChefPostalCode
        chef_ids = ChefPostalCode.objects.filter(
            postal_code__code=user_postal_code
        ).values_list('chef_id', flat=True)
        
        # Security check: If chef_id is provided, verify it's in the list of allowed chefs
        if chef_id:
            try:
                chef_id = int(chef_id)
                if chef_id not in chef_ids:
                    return Response({
                        'status': 'error',
                        'message': 'Specified chef does not serve your postal code',
                        'code': 'chef_not_available'
                    }, status=403)
            except ValueError:
                return Response({
                    'status': 'error',
                    'message': 'Invalid chef ID',
                    'code': 'invalid_chef_id'
                }, status=400)
            
            # If valid chef_id provided, only use that chef
            chef_ids = [chef_id]
        
        # Find meals by these chefs
        query = Q(chef_id__in=chef_ids)
        
        # Apply meal type filter if provided
        if meal_type:
            query &= Q(meal_type=meal_type)
        
        # Get meal IDs with events in the date range
        from .models import ChefMealEvent
        event_meals = ChefMealEvent.objects.filter(
            chef_id__in=chef_ids,
            event_date__gte=start_date,
            event_date__lte=end_date,
            status__in=['scheduled', 'open'],
            order_cutoff_time__gt=timezone.now()
        ).values_list('meal_id', flat=True).distinct()
        
        # Only include meals with active events in the date range
        query &= Q(id__in=event_meals)
        
        # Get all eligible chef meals
        from .models import Meal
        meals = Meal.objects.filter(query).distinct().order_by('id')
        
        # Setup pagination
        page_number = request.query_params.get('page', 1)
        page_size = request.query_params.get('page_size', 10)
        
        try:
            page_number = int(page_number)
            page_size = min(int(page_size), 50)  # Cap maximum page size
        except ValueError:
            page_number = 1
            page_size = 10
        
        # Apply pagination
        paginator = Paginator(meals, page_size)
        page_obj = paginator.get_page(page_number)
        
        # Serialize the meals with compatibility information
        serializer = MealSerializer(
            page_obj.object_list, 
            many=True,
            context={'request': request}
        )
        
        # If only compatible meals requested, filter after serialization
        serialized_meals = serializer.data
        if include_compatible_only:
            serialized_meals = [meal for meal in serialized_meals if meal['is_compatible']]
        
        # Get event availability for each meal in the date range
        for meal_data in serialized_meals:
            # Get all meal event dates for this meal in the date range
            meal_events = ChefMealEvent.objects.filter(
                meal_id=meal_data['id'],
                event_date__gte=start_date,
                event_date__lte=end_date,
                status__in=['scheduled', 'open'],
                order_cutoff_time__gt=timezone.now()
            ).order_by('event_date')
            
            # Add a list of dates when this meal is available during the week
            meal_data['available_dates'] = {
                event.event_date.strftime('%Y-%m-%d'): {
                    'day_name': event.event_date.strftime('%A'),
                    'event_id': event.id,
                    'event_time': str(event.event_time),
                    'orders_count': event.orders_count,
                    'max_orders': event.max_orders,
                    'price': float(event.current_price),
                    'meal_type': meal_data.get('meal_type')
                }
                for event in meal_events
            }
            
            # Add a quick reference to how many days this meal is available
            meal_data['available_days_count'] = len(meal_data['available_dates'])
            
            # Add a suggested day for this meal based on availability
            # This helps the frontend suggest a replacement day that makes sense
            if meal_data['available_dates']:
                # Get the first available date for meal
                first_available = min(meal_data['available_dates'].keys())
                meal_data['suggested_date'] = first_available
        
        # Return the paginated result
        return Response({
            'status': 'success',
            'message': 'Chef meals retrieved successfully',
            'data': {
                'meals': serialized_meals,
                'total_count': paginator.count,
                'page_size': page_size,
                'current_page': page_number,
                'total_pages': paginator.num_pages,
                'week_start_date': start_date.strftime('%Y-%m-%d'),
                'week_end_date': end_date.strftime('%Y-%m-%d'),
                'date_range': [(start_date + timedelta(days=i)).strftime('%Y-%m-%d') 
                              for i in range((end_date - start_date).days + 1)]
            }
        })
        
    except Exception as e:
        # N8N webhook
        if settings.DEBUG:
            logger.error(f"Error retrieving chef meals: {str(e)}", exc_info=True)
        else:
            logger.error(f"Error retrieving chef meals: {str(e)}", exc_info=True)
            n8n_webhook_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_webhook_url, json={"error": str(e), "source":"api_get_chef_meals_by_postal_code", "traceback": traceback.format_exc()})
        return Response({
            'status': 'error',
            'message': f"Error retrieving chef meals: {str(e)}",
            'code': 'server_error'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chef_payment_analytics(request):
    """Get payment analytics for a chef's meals"""
    try:
        chef = Chef.objects.get(user=request.user)
        
        # Sync recent payments first
        sync_recent_payments(chef)
        
        # Then return analytics based on updated data
        analytics = {
            'total_earnings': PaymentLog.objects.filter(
                chef=chef, 
                status='succeeded'
            ).aggregate(Sum('amount'))['amount__sum'] or 0,
            
            'recent_payments': PaymentLog.objects.filter(
                chef=chef, 
                status='succeeded',
                created_at__gte=timezone.now() - timedelta(days=30)
            ).values('created_at', 'amount', 'order__id')[:10],
            
            'payment_by_meal': PaymentLog.objects.filter(
                chef=chef, 
                status='succeeded'
            ).values(
                'chef_meal_order__meal_event__meal__name'
            ).annotate(
                total=Sum('amount'),
                count=Count('id')
            ).order_by('-total')[:5]
        }
        
        return Response(analytics)
    except Chef.DoesNotExist:
        return Response({"error": "You must be a chef to access analytics"}, status=403)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chef_dashboard_stats(request):
    """Get statistics for the chef dashboard"""
    logger.info(f"API chef dashboard stats requested by user {request.user.id}")
    from meals.models import ChefMealEvent, ChefMealOrder, ChefMealReview, PaymentLog
    from django.db.models import Avg, Sum, F, Value, DecimalField
    from django.db.models.functions import Coalesce
    from decimal import Decimal

    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} requested chef dashboard stats but is not a chef")
        return Response(
            {"error": "You must be a registered chef to access dashboard stats"},
            status=403
        )
    
    # Get counts
    now = timezone.now()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    upcoming_events_count = ChefMealEvent.objects.filter(
        chef=chef,
        event_date__gte=now.date(),
        status__in=['scheduled', 'open']
    ).count()
    
    active_orders_count = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        status__in=['placed', 'confirmed']
    ).count()
    
    past_events_count = ChefMealEvent.objects.filter(
        chef=chef,
        event_date__lt=now.date()
    ).count()
    
    # Get revenue stats (include confirmed orders, not just completed)
    revenue_this_month = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        status__in=['completed', 'confirmed'],
        updated_at__gte=this_month_start
    ).aggregate(
        total=Coalesce(Sum(F('price_paid') * F('quantity')), Value(Decimal('0.00')), output_field=DecimalField())
    )['total']
    
    # Calculate refunds this month
    refunds_this_month = PaymentLog.objects.filter(
        chef=chef,
        action='refund',
        created_at__gte=this_month_start
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total']
    
    # Calculate net revenue
    net_revenue = revenue_this_month - refunds_this_month
    
    # Calculate dynamic pricing savings (how much customers saved through group discounts)
    total_savings = Decimal('0.00')
    group_order_events = ChefMealEvent.objects.filter(
        chef=chef,
        status__in=['completed', 'closed', 'in_progress'],
        current_price__lt=F('base_price'),
        updated_at__gte=this_month_start
    ).select_related()
    
    for event in group_order_events:
        # Calculate savings per order
        savings_per_order = event.base_price - event.current_price
        # Multiply by number of orders
        total_event_savings = savings_per_order * event.orders_count
        total_savings += total_event_savings
    
    # Check for pending price adjustments
    pending_adjustments_count = ChefMealOrder.objects.filter(
        meal_event__chef=chef,
        status__in=['placed', 'confirmed', 'completed'],
        price_adjustment_processed=False,
        price_paid__gt=F('meal_event__current_price')
    ).count()
    
    # Get rating and reviews
    review_count = ChefMealReview.objects.filter(chef=chef).count()
    avg_rating = ChefMealReview.objects.filter(chef=chef).aggregate(
        avg=Avg('rating')
    )['avg'] or 0
    
    return Response({
        'upcoming_events_count': upcoming_events_count,
        'active_orders_count': active_orders_count,
        'past_events_count': past_events_count,
        'revenue_this_month': str(revenue_this_month),
        'refunds_this_month': str(refunds_this_month),
        'net_revenue': str(net_revenue),
        'customer_savings': str(total_savings),
        'pending_price_adjustments': pending_adjustments_count,
        'review_count': review_count,
        'avg_rating': avg_rating
    })

def sync_recent_payments(chef):
    """Sync recent payments from Stripe to local database"""
    try:
        # Get this chef's Stripe account
        stripe_account = StripeConnectAccount.objects.get(chef=chef)
        
        # Set the API key for this request
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Get recent payments from Stripe (last 30 days)
        thirty_days_ago = int((timezone.now() - timedelta(days=30)).timestamp())
        
        has_more = True
        starting_after = None
        total_synced = 0
        
        while has_more:
            try:
                # Get payments with pagination
                payment_list = stripe.PaymentIntent.list(
                    created={'gte': thirty_days_ago},
                    limit=100,
                    starting_after=starting_after,
                    stripe_account=stripe_account.stripe_account_id
                )
                
                
                # Process each payment
                for payment in payment_list.data:
                    try:
                        # Check if we already have this payment logged
                        if not PaymentLog.objects.filter(stripe_id=payment.id).exists():
                            # Find associated order
                            try:
                                # For direct chef meal orders
                                order = ChefMealOrder.objects.get(payment_intent_id=payment.id)
                                # Log the payment
                                PaymentLog.objects.create(
                                    chef_meal_order=order,
                                    user=order.customer,
                                    chef=chef,
                                    action='charge',
                                    amount=payment.amount / 100,
                                    stripe_id=payment.id,
                                    status=payment.status,
                                    details=payment
                                )
                                
                                # Update order status if needed
                                if payment.status == 'succeeded' and not order.is_paid:
                                    order.is_paid = True
                                    order.save()
                                    
                            except ChefMealOrder.DoesNotExist:
                                # Could be a meal plan order or other type
                                pass
                            except Exception as e:
                                logger.error(f"Error processing payment {payment.id}: {str(e)}", exc_info=True)
                    
                    except stripe.error.StripeError as e:
                        logger.error(f"Stripe error processing payment: {str(e)}", exc_info=True)
                    except Exception as e:
                        logger.error(f"Error processing payment: {str(e)}", exc_info=True)
                
                total_synced += len(payment_list.data)
                
                # Check if there are more payments to fetch
                has_more = payment_list.has_more
                if has_more:
                    # Get the ID of the last payment for pagination
                    starting_after = payment_list.data[-1].id
                else:
                    break
                    
            except stripe.error.StripeError as e:
                logger.error(f"Stripe API error: {str(e)}", exc_info=True)
                break
                
        logger.info(f"Successfully synced {total_synced} payments total")
                    
    except StripeConnectAccount.DoesNotExist:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"No Stripe account found for chef {chef.id}", "source":"sync_recent_payments", "traceback": traceback.format_exc()})
        logger.warning(f"No Stripe account found for chef {chef.id}")
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}", exc_info=True)
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Stripe error: {str(e)}", "source":"sync_recent_payments", "traceback": traceback.format_exc()})
    except Exception as e:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Error syncing payments: {str(e)}", "source":"sync_recent_payments", "traceback": traceback.format_exc()})
        logger.error(f"Error syncing payments: {str(e)}", exc_info=True)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_success(request):
    """
    Handle success redirect from Stripe Checkout.
    This serves as a fallback mechanism in case the webhook fails.
    """
    # Get session ID from query parameters
    session_id = request.GET.get('session_id')
    if not session_id:
        logger.error("No session_id provided in payment success redirect")
        return Response(
            {"success": False, "message": "No session ID provided"}, 
            status=400
        )
    
    try:
        # Retrieve the session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        order_id = session.metadata.get('order_id')
        order_type = session.metadata.get('order_type', '')
        
        if not order_id:
            logger.error(f"No order_id in metadata for session {session_id}")
            return Response(
                {"success": False, "message": "No order ID found in session metadata"}, 
                status=400
            )
        
        from django.db import transaction
        
        # Process chef meal orders
        if order_type == 'chef_meal':
            try:
                with transaction.atomic():
                    # Get the chef meal order and ensure it belongs to the current user
                    chef_order = ChefMealOrder.objects.select_for_update().get(id=order_id, customer=request.user)
                    
                    # Only process if the order isn't already confirmed
                    if chef_order.status != STATUS_CONFIRMED:
                        logger.info(f"Processing success redirect for chef meal order {chef_order.id} (session {session_id})")
                        
                        # Update order status
                        chef_order.status = STATUS_CONFIRMED
                        chef_order.payment_intent_id = session.payment_intent
                        chef_order.save()
                        
                        # Update corresponding Order if it exists
                        if chef_order.order:
                            chef_order.order.is_paid = True
                            chef_order.order.status = 'Confirmed'
                            chef_order.order.save()
                        
                        # Get amount from either session or order
                        amount = float(session.amount_total) / 100  # Convert from cents to dollars
                        if not amount and chef_order.price_paid:
                            amount = float(chef_order.price_paid) * chef_order.quantity
                        
                        # Create payment log if it doesn't exist
                        if not PaymentLog.objects.filter(chef_meal_order=chef_order, stripe_id=session.payment_intent).exists():
                            PaymentLog.objects.create(
                                chef_meal_order=chef_order,
                                user=chef_order.customer,
                                chef=chef_order.meal_event.chef,
                                action='charge',
                                amount=amount,
                                stripe_id=session.payment_intent,
                                status='succeeded',
                                details={
                                    'session_id': session.id,
                                    'payment_intent_id': session.payment_intent,
                                    'created_in_success_redirect': True
                                }
                            )
                        
                        logger.info(f"Successfully updated chef meal order {chef_order.id} in success redirect")
                        
                        # Send email notification
                        from meals.email_service import send_payment_confirmation_email
                        send_payment_confirmation_email(chef_order.id)
                    else:
                        logger.info(f"Chef meal order {chef_order.id} was already confirmed, skipping processing")
            except ChefMealOrder.DoesNotExist:
                # n8n traceback
                n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
                requests.post(n8n_traceback_url, json={"error": f"Order {order_id} not found or doesn't belong to user {request.user.id}", "source":"payment_success", "traceback": traceback.format_exc()})
                return Response(
                    {"success": False, "message": "Order not found"}, 
                    status=404
                )
        
        # Process regular meal plan orders
        else:
            try:
                with transaction.atomic():
                    # Get the order and ensure it belongs to the current user
                    from meals.models import Order, PaymentLog
                    order = Order.objects.select_for_update().get(id=order_id, customer=request.user)
                    
                    # Only process if the order isn't already marked as paid
                    if not order.is_paid:
                        logger.info(f"Processing success redirect for meal plan order {order.id} (session {session_id})")
                        
                        # Mark order as paid
                        order.is_paid = True
                        order.status = 'Confirmed'
                        # Store the session ID if not already set
                        if not order.stripe_session_id:
                            order.stripe_session_id = session.id
                        order.save()
                        
                        # Mark all associated meal plan meals as paid to prevent double-charging
                        for order_meal in order.ordermeal_set.select_related('meal_plan_meal').all():
                            if hasattr(order_meal, 'meal_plan_meal') and order_meal.meal_plan_meal:
                                order_meal.meal_plan_meal.already_paid = True
                                order_meal.meal_plan_meal.save(update_fields=['already_paid'])
                                logger.info(f"Marked MealPlanMeal {order_meal.meal_plan_meal.id} as already paid in success redirect")
                        
                        # Process any associated ChefMealOrders
                        chef_meal_orders = ChefMealOrder.objects.filter(order=order)
                        for chef_order in chef_meal_orders:
                            if chef_order.status == STATUS_PLACED:
                                chef_order.status = STATUS_CONFIRMED
                                chef_order.payment_intent_id = session.payment_intent
                                chef_order.save()
                                logger.info(f"Updated ChefMealOrder {chef_order.id} to confirmed status in success redirect")
                                
                                # Create payment log if it doesn't exist
                                if not PaymentLog.objects.filter(chef_meal_order=chef_order, stripe_id=session.payment_intent).exists():
                                    PaymentLog.objects.create(
                                        chef_meal_order=chef_order,
                                        user=chef_order.customer,
                                        chef=chef_order.meal_event.chef,
                                        action='charge',
                                        amount=float(chef_order.price_paid) * chef_order.quantity,
                                        stripe_id=session.payment_intent,
                                        status='succeeded',
                                        details={
                                            'session_id': session.id,
                                            'payment_intent_id': session.payment_intent,
                                            'created_in_success_redirect': True
                                        }
                                    )
                        
                        # Create payment log for the order
                        PaymentLog.objects.create(
                            order=order,
                            user=order.customer,
                            action='charge',
                            amount=float(session.amount_total) / 100,  # Convert cents to dollars
                            stripe_id=session.payment_intent,
                            status='succeeded',
                            details={
                                'session_id': session.id,
                                'payment_intent_id': session.payment_intent,
                                'created_in_success_redirect': True
                            }
                        )
                        
                        logger.info(f"Successfully processed payment for meal plan order {order.id} in success redirect")
                    else:
                        logger.info(f"Order {order.id} was already marked as paid, skipping processing")
            except Order.DoesNotExist:
                logger.error(f"Order {order_id} not found or doesn't belong to user {request.user.id}")
                return Response(
                    {"success": False, "message": "Order not found"}, 
                    status=404
                )
        
        # Return success response
        return Response({
            "success": True,
            "message": "Payment successful",
            "order_id": order_id,
            "order_type": order_type
        })
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error in payment success redirect: {str(e)}")
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Stripe error in payment success redirect: {str(e)}", "source":"payment_success", "traceback": traceback.format_exc()})
        return Response(
            {"success": False, "message": f"Payment processing error: {str(e)}"}, 
            status=400
        )
    except Exception as e:
        logger.error(f"Unexpected error in payment success redirect: {str(e)}", exc_info=True)
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Unexpected error in payment success redirect: {str(e)}", "source":"payment_success", "traceback": traceback.format_exc()})
        return Response(
            {"success": False, "message": "An unexpected error occurred"}, 
            status=500
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_cancelled(request):
    """
    Handle cancellation redirect from Stripe Checkout.
    This endpoint processes when a user cancels a Stripe payment flow.
    """
    logger.info(f"Payment cancelled by user {request.user.id}")
    
    # Get any available information from the request
    session_id = request.GET.get('session_id')
    
    # Return a standard response
    return Response({
        "success": False,
        "status": "cancelled",
        "message": "Payment was cancelled",
        "redirected": True
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_debug_order_info(request, order_id):
    """
    Debug endpoint to check if an order exists and what chef meal orders are associated with it.
    Only usable in development.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    from meals.models import Order, ChefMealOrder, OrderMeal, ChefMealEvent
    
    logger.info(f"Debug order info for order_id={order_id}")
    
    try:
        # Check if the order exists at all
        if Order.objects.filter(id=order_id).exists():
            order = Order.objects.get(id=order_id)
            owner_id = order.customer_id
            
            # Check for associated ChefMealOrders
            chef_meal_orders = ChefMealOrder.objects.filter(order_id=order_id)
            
            # Check for OrderMeals that might have chef_meal_event references
            order_meals = OrderMeal.objects.filter(order_id=order_id)
            order_meals_with_chef_events = OrderMeal.objects.filter(
                order_id=order_id, 
                chef_meal_event__isnull=False
            )
            
            # Check for meals that are from chefs
            meals_from_chefs = []
            for order_meal in order_meals:
                if order_meal.meal.chef:
                    meals_from_chefs.append({
                        'order_meal_id': order_meal.id,
                        'meal_id': order_meal.meal_id,
                        'meal_name': order_meal.meal.name,
                        'chef_id': order_meal.meal.chef_id,
                        'chef_name': order_meal.meal.chef.user.username,
                        'has_chef_meal_event': order_meal.chef_meal_event_id is not None
                    })
            
            # Direct query for any chef meal orders that might have this order
            result = {
                "order_exists": True,
                "order_id": order_id,
                "owner_id": owner_id,
                "request_user_id": request.user.id,
                "is_owner": owner_id == request.user.id,
                "chef_meal_orders_count": chef_meal_orders.count(),
                "chef_meal_orders": [{
                    "id": cmo.id,
                    "customer_id": cmo.customer_id,
                    "status": cmo.status,
                    "created_at": cmo.created_at.isoformat() if hasattr(cmo, 'created_at') else None
                } for cmo in chef_meal_orders],
                "order_meals_count": order_meals.count(),
                "order_meals_with_chef_events_count": order_meals_with_chef_events.count(),
                "order_meals_with_chef_events": [{
                    "id": om.id, 
                    "chef_meal_event_id": om.chef_meal_event_id,
                    "meal_id": om.meal_id,
                    "meal_name": om.meal.name if om.meal else 'Unknown',
                } for om in order_meals_with_chef_events],
                "meals_from_chefs": meals_from_chefs
            }
            
            # Let's fix the issue - if there are OrderMeals with chef_meal_event but no ChefMealOrder
            fix = request.query_params.get('fix') == 'true'
            if fix and order_meals_with_chef_events.exists() and not chef_meal_orders.exists():
                logger.info(f"Fixing missing ChefMealOrders for Order {order_id}")
                fixed_orders = []
                
                for order_meal in order_meals_with_chef_events:
                    if order_meal.chef_meal_event:
                        # Create the missing ChefMealOrder
                        chef_meal_order = ChefMealOrder.objects.create(
                            order=order,
                            meal_event=order_meal.chef_meal_event,
                            customer=order.customer,
                            quantity=order_meal.quantity,
                            price_paid=order_meal.chef_meal_event.current_price,
                            status='placed'
                        )
                        fixed_orders.append({
                            "id": chef_meal_order.id,
                            "meal_event_id": chef_meal_order.meal_event_id,
                            "customer_id": chef_meal_order.customer_id
                        })
                
                result["fixed"] = True
                result["fixed_orders"] = fixed_orders
            
            return Response(result)
        else:
            return Response({"order_exists": False, "order_id": order_id})
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Error in debug endpoint: {str(e)}", "source":"api_debug_order_info", "traceback": traceback.format_exc()})
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_create_chef_meal_order(request, event_id):
    """
    Create a new chef meal order for a specific event.
    Uses the new order_service with idempotency support.
    
    Request body should include:
    - quantity: Integer (required)
    - special_requests: String (optional)
    """
    from meals.models import ChefMealEvent, ChefMealOrder
    from meals.services.order_service import create_order
    import json
    
    try:
        # Get the event
        event = get_object_or_404(ChefMealEvent, id=event_id)
        
        # Validate quantity
        try:
            quantity = int(request.data.get('quantity', 1))
            if quantity < 1:
                return Response(
                    {"error": "Quantity must be at least 1"},
                    status=400
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid quantity format"},
                status=400
            )
        
        # Get optional fields
        special_requests = request.data.get('special_requests', '')
        
        # Check for idempotency key in headers
        idempotency_key = request.headers.get('Idempotency-Key')
        if not idempotency_key:
            # Generate one if not provided
            import uuid
            idempotency_key = f"order_{event_id}_{request.user.id}_{uuid.uuid4()}"
        
        try:
            # Create the order using the service
            order = create_order(
                user=request.user,
                event=event,
                qty=quantity,
                idem_key=idempotency_key
            )
            
            # Update special requests if provided
            if special_requests:
                order.special_requests = special_requests
                order.save(update_fields=['special_requests'])
            
            # Return the created order
            from meals.serializers import ChefMealOrderSerializer
            serializer = ChefMealOrderSerializer(order)
            return Response(serializer.data, status=201)
            
        except ValueError as e:
            # Handle validation errors from the service
            return Response(
                {"error": str(e)},
                status=409 if "already exists" in str(e).lower() else 400
            )
        except Exception as e:
            # Log the error and return a generic message
            # n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": f"Error creating chef meal order: {str(e)}", "source":"api_create_chef_meal_order", "traceback": traceback.format_exc()})
            return Response(
                {"error": "Failed to create order"},
                status=500
            )
    
    except Exception as e:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Unexpected error in api_create_chef_meal_order: {str(e)}", "source":"api_create_chef_meal_order", "traceback": traceback.format_exc()})
        return Response(
            {"error": "An unexpected error occurred"},
            status=500
        )

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def api_adjust_chef_meal_quantity(request, order_id):
    """
    Adjust the quantity of an existing chef meal order.
    Uses the new order_service with idempotency support.
    
    Request body should include:
    - quantity: Integer (required)
    """
    from meals.models import ChefMealOrder
    from meals.services.order_service import adjust_quantity
    
    try:
        # Get the order and verify ownership
        order = get_object_or_404(ChefMealOrder, id=order_id)
        
        # Verify ownership
        if order.customer != request.user:
            return Response(
                {"error": "You don't have permission to modify this order"},
                status=403
            )
        
        # Validate quantity
        try:
            new_quantity = int(request.data.get('quantity', 1))
            if new_quantity < 1:
                return Response(
                    {"error": "Quantity must be at least 1"},
                    status=400
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid quantity format"},
                status=400
            )
        
        # No change needed
        if new_quantity == order.quantity:
            return Response(
                {"message": "No change in quantity"},
                status=200
            )
        
        # Check for idempotency key in headers
        idempotency_key = request.headers.get('Idempotency-Key')
        if not idempotency_key:
            # Generate one if not provided
            import uuid
            idempotency_key = f"adjust_{order_id}_{new_quantity}_{uuid.uuid4()}"
        
        try:
            # Adjust the quantity using the service
            adjust_quantity(
                order=order,
                new_qty=new_quantity,
                idem_key=idempotency_key
            )
            
            # Return the updated order
            from meals.serializers import ChefMealOrderSerializer
            serializer = ChefMealOrderSerializer(order)
            return Response(serializer.data, status=200)
            
        except ValueError as e:
            # Handle validation errors from the service
            return Response(
                {"error": str(e)},
                status=400
            )
        except Exception as e:
            # n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": f"Error adjusting chef meal order quantity: {str(e)}", "source":"api_adjust_chef_meal_quantity", "traceback": traceback.format_exc()})
            return Response(
                {"error": "Failed to adjust order quantity"},
                status=500
            )
    
    except Exception as e:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Unexpected error in api_adjust_chef_meal_quantity: {str(e)}", "source":"api_adjust_chef_meal_quantity", "traceback": traceback.format_exc()})
        return Response(
            {"error": "An unexpected error occurred"},
            status=500
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated]) 
def api_cancel_chef_meal_order(request, order_id):
    """
    Cancel a chef meal order.
    Uses the new order_service with idempotency support.
    """
    from meals.models import ChefMealOrder
    from meals.services.order_service import cancel_order
    
    try:
        # Get the order and verify ownership
        order = get_object_or_404(ChefMealOrder, id=order_id)
        
        # Verify ownership
        if order.customer != request.user:
            return Response(
                {"error": "You don't have permission to cancel this order"},
                status=403
            )
        
        # Order already cancelled
        if order.status == 'cancelled':
            return Response(
                {"message": "Order already cancelled"},
                status=200
            )
        
        # Check for idempotency key in headers
        idempotency_key = request.headers.get('Idempotency-Key')
        if not idempotency_key:
            # Generate one if not provided
            import uuid
            idempotency_key = f"cancel_{order_id}_{uuid.uuid4()}"
        
        # Get cancellation reason
        reason = request.data.get('reason', 'customer_requested')
        
        try:
            # Cancel the order using the service
            cancel_order(
                order=order,
                reason=reason,
                idem_key=idempotency_key
            )
            
            # Return success response
            return Response(
                {"message": "Order cancelled successfully"},
                status=200
            )
            
        except Exception as e:
            # n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": f"Error cancelling chef meal order: {str(e)}", "source":"api_cancel_chef_meal_order", "traceback": traceback.format_exc()})
            return Response(
                {"error": "Failed to cancel order"},
                status=500
            )
    
    except Exception as e:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Unexpected error in api_cancel_chef_meal_order: {str(e)}", "source":"api_cancel_chef_meal_order", "traceback": traceback.format_exc()})
        return Response(
            {"error": "An unexpected error occurred"},
            status=500
        )
