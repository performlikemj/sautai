"""
Chef connection tools for the OpenAI Responses API integration.

This module implements the chef connection tools defined in the optimized tool structure,
connecting them to the existing chef connection functionality in the application.
"""

import json
import logging
import requests
import traceback
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Union
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import Q, F
from django.forms.models import model_to_dict
from custom_auth.models import CustomUser
from chefs.models import Chef
from meals.models import Meal, Order, MealPlanMeal, ChefMealEvent, ChefMealOrder, STATUS_SCHEDULED, STATUS_OPEN
from local_chefs.models import PostalCode, ChefPostalCode
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
# Tool definitions for the OpenAI Responses API
CHEF_CONNECTION_TOOLS = [
    {
        "type": "function",
        "name": "find_local_chefs",
        "description": "Find chefs serving the the user's postal code area",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The ID of the user"
                },
            },
            "required": ["user_id"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "get_chef_details",
        "description": "Get detailed information about a chef",
        "parameters": {
                "type": "object",
                "properties": {
                    "chef_id": {
                        "type": "integer",
                        "description": "The ID of the chef"
                    }
                },
                "required": ["chef_id"],
                "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "view_chef_meal_events",
        "description": "View upcoming meal events offered by a specific chef",
        "parameters": {
                "type": "object",
                "properties": {
                    "chef_id": {
                        "type": "integer",
                        "description": "The ID of the chef"
                    },
                    "meal_type": {
                        "type": "string",
                        "description": "Optional meal type to filter by (e.g., Breakfast, Lunch, Dinner)"
                    },
                    "dietary_preference": {
                        "type": "string",
                        "description": "Optional dietary preference to filter by"
                    }
                },
                "required": ["chef_id"],
                "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "place_chef_meal_event_order",
        "description": "Place an order for a chef meal event",
        "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "The ID of the user placing the order"
                    },
                    "meal_event_id": {
                        "type": "integer",
                        "description": "The ID of the meal event to order"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Number of servings to order"
                    },
                    "special_instructions": {
                        "type": "string",
                        "description": "Optional special instructions for the order"
                    }
                },
                "required": ["user_id", "meal_event_id", "quantity"],
                "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "get_order_details",
        "description": "Get details of a chef meal order",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The ID of the user who placed the order"
                },
                "order_id": {
                    "type": "integer",
                    "description": "The ID of the order to retrieve"
                }
            },
            "required": ["user_id", "order_id"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "update_chef_meal_order",
        "description": "Customer can update their chef-meal order (change quantity or notes) before the order is confirmed by the chef",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Current user"},
                "chef_meal_order_id": {"type": "integer", "description": "The order row to update"},
                "quantity": {"type": "integer", "description": "New quantity (≥1)"},
                "special_requests": {"type": "string", "description": "Optional new notes"}
            },
            "required": ["user_id", "chef_meal_order_id", "quantity"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "replace_meal_plan_meal",
        "description": "Used to replace a meal in a user's meal plan with a chef‑created meal, so the user can order the chef meal. Always be sure the replacement meal is for the same date and week as the original meal.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "ID of the user who owns the meal plan"
                },
                "meal_plan_meal_id": {
                    "type": "integer",
                    "description": "ID of the MealPlanMeal being replaced"
                },
                "chef_meal_id": {
                    "type": "integer",
                    "description": "ID of the chef‑created Meal that will replace the original"
                },
                "event_id": {
                    "type": "integer",
                    "description": "Optional ID of a specific ChefMealEvent to use"
                },
                "quantity": {
                    "type": "integer",
                    "description": "Number of servings to order",
                    "default": 1
                },
                "special_requests": {
                    "type": "string",
                    "description": "Optional notes for the chef"
                }
            },
            "required": ["user_id", "meal_plan_meal_id", "chef_meal_id"],
            "additionalProperties": False
        }
    },
]

# Tool implementation functions

def find_local_chefs(
    user_id: int,
    postal_code: str = None,
) -> dict:
    """
    Find chefs serving the specified postal code (or the user's saved postal code).
    """
    try:
        # 1. Load the user
        user = get_object_or_404(CustomUser, id=user_id)

        # 2. Try to grab their address (OneToOneField related_name='address')
        try:
            address = user.address
        except ObjectDoesNotExist:
            address = None

        # 3. Determine which postal code to use
        code = address.normalized_postalcode if address and address.normalized_postalcode else None
        country = address.country if address and address.country else None

        if not code:
            return {
                "status": "error",
                "message": "No postal code on file. Please save a postal code in your profile settings."
            }

        # 4. Fetch the PostalCode instance (filter by country if we have it)
        if country:
            user_pc = get_object_or_404(PostalCode, code=code, country=country)
        else:
            user_pc = get_object_or_404(PostalCode, code=code)

        # 5. Find chefs serving that postal code
        chefs_qs = (
            Chef.objects
            .filter(serving_postalcodes=user_pc)
            .select_related("user")
            .prefetch_related("serving_postalcodes")
        )

        # Finished building queryset — already optimized with select_related/prefetch

        # 6. Build the response
        chefs = []
        for chef in chefs_qs:
            served_codes = ChefPostalCode.objects.filter(chef=chef) \
                                                .values_list('postal_code__code', flat=True)
            chefs.append({
                "chef_id": str(chef.id),
                "name": chef.user.username,
                "experience": chef.experience,
                "bio": chef.bio,
                "profile_pic": chef.profile_pic.url if chef.profile_pic else None,
                "service_postal_codes": list(served_codes),
            })

        return {
            "status": "success",
            "count": len(chefs),
            "postal_code": code,
            "chefs": chefs
        }

    except PostalCode.DoesNotExist:
        return {
            "status": "error",
            "message": f"We do not serve postal code '{code}'. Please check back later."
        }

    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"find_local_chefs", "traceback": traceback.format_exc()})
        return {"status": "error", "message": str(e)}

def get_chef_details(chef_id: int) -> Dict[str, Any]:
    """
    Get detailed information about a chef.
    
    Args:
        chef_id: The ID of the chef
        
    Returns:
        Dict containing the chef details
    """
    from chefs.base_serializers import ChefSerializer

    try:
        # Get the chef
        chef = get_object_or_404(Chef, id=chef_id)
        
        # Serialize the chef
        serializer = ChefSerializer(chef, context={'detailed': True})
        
        # Get the chef's rating
        rating = None
        
        # Get the chef's specialties
        specialties = []
        
        # Get upcoming meal events count
        upcoming_events_count = ChefMealEvent.objects.filter(
            chef=chef,
            event_date__gte=timezone.now().date(),
            status__in=['scheduled', 'open']
        ).count()
        
        return {
            "status": "success",
            "chef": serializer.data,
            "rating": rating,
            "specialties": specialties,
            "upcoming_events_count": upcoming_events_count
        }
        
    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"get_chef_details", "traceback": traceback.format_exc()})
        return {
            "status": "error",
            "message": f"Failed to get chef details"
        }

def view_chef_meal_events(
    chef_id: int, 
    meal_type: str = None, 
    dietary_preference: str = None,
) -> Dict[str, Any]:
    """
    View upcoming meal events offered by a specific chef.
    """
    
    try:
        # Get the chef
        chef = get_object_or_404(Chef, id=chef_id)
        
        # First, get ALL events for this chef without any filtering
        all_chef_events = ChefMealEvent.objects.filter(chef=chef)
        
        if all_chef_events.count() == 0:
            logger.error(f"⚠️ No events found for this chef at all. Check if chef has created any events.")
        else:
            # Print details of all events
            logger.info("ALL EVENTS FOR THIS CHEF:")
            for i, event in enumerate(all_chef_events):
                logger.info(f"  Event {i+1}: id={event.id}, meal={event.meal.name}, status={event.status}")
                logger.info(f"    date={event.event_date}, time={event.event_time}")
                logger.info(f"    cutoff={event.order_cutoff_time}, orders={event.orders_count}/{event.max_orders}")
        
        # Build the base query for events
        now = timezone.now()
        
        # Check event dates individually
        future_events = all_chef_events.filter(event_date__gte=now.date())
        
        # Check statuses individually 
        from meals.models import STATUS_SCHEDULED, STATUS_OPEN
        status_events = all_chef_events.filter(Q(status=STATUS_SCHEDULED) | Q(status=STATUS_OPEN))
        if status_events.count() == 0 and all_chef_events.count() > 0:
            logger.error("⚠️ Status filter is eliminating all events. Statuses found:")
            statuses = all_chef_events.values_list('status', flat=True).distinct()
            logger.error(f"  Available statuses: {list(statuses)}")
        
        # Check cutoff times
        cutoff_events = all_chef_events.filter(order_cutoff_time__gt=now)
        if cutoff_events.count() == 0 and all_chef_events.count() > 0:
            first_event = all_chef_events.first()
            if first_event:
                logger.error(f"⚠️ Cutoff time issue. Sample event cutoff: {first_event.order_cutoff_time}")
        
        # Check orders count
        orders_events = all_chef_events.filter(orders_count__lt=F('max_orders'))
        
        # Start building the combined query
        logger.info(f"\nBuilding combined query...")
        query = Q(chef=chef) & Q(event_date__gte=now.date()) & Q(
            Q(status=STATUS_SCHEDULED) | Q(status=STATUS_OPEN)
        ) & Q(order_cutoff_time__gt=now) & Q(orders_count__lt=F('max_orders'))
        
        # Show effect of additional filters
        if meal_type:
            logger.info(f"Adding meal_type filter: {meal_type}")
            meal_type_events = all_chef_events.filter(meal__meal_type=meal_type)
            logger.info(f"Events matching meal type '{meal_type}': {meal_type_events.count()}")
            query &= Q(meal__meal_type=meal_type)
            
                
        # Execute the final query
        logger.info(f"\nExecuting final query...")
        events = (
            ChefMealEvent.objects
            .filter(query)
            .select_related("chef", "meal")
            .prefetch_related("meal__dietary_preferences", "meal__custom_dietary_preferences")
            .order_by('event_date', 'event_time')
        )
        
        event_count = events.count()
        
        if event_count == 0:
            logger.error("⚠️ No events matched the combined criteria.")
        else:
            logger.info("Events that matched all criteria:")
            for i, event in enumerate(events):
                logger.info(f"  Event {i+1}: id={event.id}, meal={event.meal.name}, status={event.status}")
                logger.info(f"    date={event.event_date}, time={event.event_time}")
                logger.info(f"    cutoff={event.order_cutoff_time}, orders={event.orders_count}/{event.max_orders}")
        
        # Create serialized response as before
        serialized_events = []
        for event in events:
            serialized_events.append({
                "event_id": event.id,
                "meal_id": event.meal.id,
                "meal_name": event.meal.name,
                "meal_description": event.meal.description,
                "meal_type": event.meal.meal_type,
                "image": event.meal.image.url if event.meal.image else None,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.strftime("%H:%M"),
                "order_cutoff_time": event.order_cutoff_time.isoformat(),
                "current_price": str(event.current_price),
                "base_price": str(event.base_price),
                "min_price": str(event.min_price),
                "orders_count": event.orders_count,
                "max_orders": event.max_orders,
                "min_orders": event.min_orders,
                "status": event.status,
                "dietary_preferences": list(event.meal.dietary_preferences.values_list("name", flat=True)),
                "custom_dietary_preferences": list(event.meal.custom_dietary_preferences.values_list("name", flat=True)),
                "special_instructions": event.special_instructions
            })
        
        logger.info(f"Returning {len(serialized_events)} serialized events")
        
        return {
            "status": "success",
            "chef_name": chef.user.username,
            "events": serialized_events,
            "count": len(serialized_events)
        }
        
    except Chef.DoesNotExist:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Chef with id={chef_id} does not exist", "source":"view_chef_meal_events", "traceback": traceback.format_exc()})
        return {
            "status": "error",
            "message": f"Chef with ID {chef_id} not found"
        }
    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"view_chef_meal_events", "traceback": traceback.format_exc()})
        return {
            "status": "error",
            "message": f"Failed to view chef meal events"
        }

def place_chef_meal_event_order(
    user_id: int, 
    meal_event_id: int, 
    quantity: int, 
    special_instructions: str = ''
) -> Dict[str, Any]:
    """
    Place an order for a chef meal event.
    
    Args:
        user_id: The ID of the user placing the order
        meal_event_id: The ID of the meal event to order
        quantity: Number of servings to order
        special_instructions: Optional special instructions for the order
        
    Returns:
        Dict containing the order details
    """
    try:
        # Get the user and meal event
        user = get_object_or_404(CustomUser, id=user_id)
        meal_event = get_object_or_404(ChefMealEvent, id=meal_event_id)
        
        # Validate the event is still available for orders
        now = timezone.now()
        if not meal_event.is_available_for_orders():
            return {
                "status": "error",
                "message": "This meal event is no longer available for orders."
            }
        
        # Validate quantity
        if quantity <= 0:
            return {
                "status": "error",
                "message": "Quantity must be greater than zero."
            }
            
        # Check if ordering would exceed the max orders
        if meal_event.orders_count + quantity > meal_event.max_orders:
            return {
                "status": "error",
                "message": f"Only {meal_event.max_orders - meal_event.orders_count} servings remain available."
            }
        
        # Calculate the total price
        total_price = meal_event.current_price * Decimal(quantity)
        
        # Resolve the user's active address
        user_address = getattr(user, "address", None)
        if not user_address:
            return {
                "status": "error",
                "message": "User does not have a saved address for the order."
            }
        
        # Dynamically determine which address field the Order model expects.
        # Older versions use `address`; newer versions may use `delivery_address`.
        order_address_kwargs = {}
        if hasattr(Order, "delivery_address"):
            order_address_kwargs["delivery_address"] = user_address
        elif hasattr(Order, "address"):
            order_address_kwargs["address"] = user_address
        else:
            return {
                "status": "error",
                "message": "Order model is missing an address field. Please contact support."
            }
        
        # Create the Order with the appropriate address field
        order = Order.objects.create(
            customer=user,
            status="Placed",
            special_requests=special_instructions or "",
            **order_address_kwargs
        )
        
        # Create the ChefMealOrder
        chef_meal_order = ChefMealOrder.objects.create(
            order=order,
            meal_event=meal_event,
            customer=user,
            quantity=quantity,
            price_paid=meal_event.current_price,  # Store the current price at the time of order
            special_requests=special_instructions or "",
            status='placed'
        )
        
        # Serialize the order
        order_dict = model_to_dict(order, exclude=['customer', 'address', 'meal', 'meal_plan'])
        order_dict['id'] = str(order.id)
        order_dict['order_date'] = order.order_date.isoformat()
        order_dict['updated_at'] = order.updated_at.isoformat()
        order_dict['total_price'] = str(total_price)
        order_dict['chef_meal_order_id'] = chef_meal_order.id
        
        # Include event details
        event_details = {
            "event_id": meal_event.id,
            "meal_name": meal_event.meal.name,
            "event_date": meal_event.event_date.isoformat(),
            "event_time": meal_event.event_time.strftime("%H:%M"),
            "price_per_serving": str(meal_event.current_price),
            "quantity": quantity,
            "chef_name": meal_event.chef.user.username
        }
        
        return {
            "status": "success",
            "message": "Order placed successfully",
            "order": order_dict,
            "event_details": event_details,
            "payment_required": not order.is_paid
        }
        
    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"place_chef_meal_event_order", "traceback": traceback.format_exc()})
        return {
            "status": "error",
            "message": f"Failed to place order"
        }

def get_order_details(user_id: int, order_id: int) -> Dict[str, Any]:
    """
    Get details of a chef meal order.
    
    Args:
        user_id: The ID of the user who placed the order
        order_id: The ID of the order to retrieve
        
    Returns:
        Dict containing the order details
    """
    try:
        # Get the user and order
        user = get_object_or_404(CustomUser, id=user_id)
        order = get_object_or_404(Order, id=order_id, customer=user)
        
        # Basic order info
        order_dict = model_to_dict(order, exclude=['customer', 'address', 'meal', 'meal_plan'])
        order_dict['id'] = str(order.id)
        order_dict['order_date'] = order.order_date.isoformat()
        order_dict['updated_at'] = order.updated_at.isoformat()
        order_dict['total_price'] = str(order.total_price())
        
        # Get chef meal orders associated with this order
        chef_meal_orders = ChefMealOrder.objects.filter(order=order).select_related('meal_event', 'meal_event__meal', 'meal_event__chef')
        
        # Add chef meal event details
        event_orders = []
        for cmo in chef_meal_orders:
            event = cmo.meal_event
            event_orders.append({
                "chef_meal_order_id": cmo.id,
                "event_id": event.id,
                "meal_name": event.meal.name,
                "chef_name": event.chef.user.username,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.strftime("%H:%M"),
                "quantity": cmo.quantity,
                "price_paid": str(cmo.price_paid),
                "status": cmo.status,
                "special_requests": cmo.special_requests or "",
                "created_at": cmo.created_at.isoformat(),
                "can_cancel": cmo.status in ['placed', 'confirmed'] and event.event_date > timezone.now().date()
            })
            
        # Add to response
        order_dict['chef_meal_orders'] = event_orders
        
        return {
            "status": "success",
            "order": order_dict
        }
        
    except Order.DoesNotExist:
        return { "status": "error", "message": f"Order with ID {order_id} not found for user {user_id}."}
    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"get_order_details", "traceback": traceback.format_exc()})
        return {
            "status": "error",
            "message": f"Failed to get order details: {str(e)}"
        }

def update_chef_meal_order(
    user_id: int,
    chef_meal_order_id: int,
    quantity: int,
    special_requests: str = ""
) -> Dict[str, Any]:
    """
    Customer changes quantity / notes on their ChefMealOrder.
    """
    try:
        user = get_object_or_404(CustomUser, id=user_id)
        cmo = get_object_or_404(ChefMealOrder, id=chef_meal_order_id, customer=user)
        event = cmo.meal_event

        # Basic guards
        if quantity <= 0:
            return {"status": "error", "message": "Quantity must be at least 1"}
        if not event.is_available_for_orders():
            return {"status": "error", "message": "Event is closed for changes"}

        # Check we won't exceed max_orders
        delta = quantity - cmo.quantity
        if event.orders_count + delta > event.max_orders:
            remain = event.max_orders - event.orders_count
            return {"status": "error",
                    "message": f"Only {remain} servings remain on this event"}

        # Update rows + counts atomically
        with transaction.atomic():
            event.orders_count = F('orders_count') + delta
            event.save(update_fields=['orders_count'])
            cmo.quantity = quantity
            cmo.special_requests = special_requests
            cmo.price_paid = event.current_price
            cmo.save()

        return {
            "status": "success",
            "message": "Order updated",
            "chef_meal_order": {
                "id": cmo.id,
                "quantity": cmo.quantity,
                "price_paid": str(cmo.price_paid),
                "special_requests": cmo.special_requests
            }
        }
    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"update_chef_meal_order", "traceback": traceback.format_exc()})
        return {"status": "error", "message": f"Failed to update chef meal order"}


# New tool: replace_meal_plan_meal
def replace_meal_plan_meal(
    user_id: int,
    meal_plan_meal_id: int,
    chef_meal_id: int,
    event_id: Optional[int] = None,
    quantity: int = 1,
    special_requests: str = ""
) -> Dict[str, Any]:
    """
    Replace a regular meal in a user's meal plan with a chef‑created meal.

    Performs all changes inside a single atomic transaction:
    1. Validates ownership, meal‑type compatibility, and chef service area.
    2. Swaps the Meal on the targeted MealPlanMeal.
    3. If the meal plan is linked to an Order, creates a ChefMealOrder
       entry to track the chef's meal event.
    4. Optionally attaches / validates a specific ChefMealEvent or finds the
       first available event within 3 days of the meal date.

    Returns a dict with `status`, `message`, and minimal confirmation data.
    """
    try:
        if quantity <= 0:
            return {"status": "error", "message": "Quantity must be at least 1"}

        user = get_object_or_404(CustomUser, id=user_id)

        with transaction.atomic():
            # Lock target slot
            mpm = MealPlanMeal.objects.select_for_update().select_related("meal_plan").get(
                id=meal_plan_meal_id
            )
            if mpm.meal_plan.user_id != user_id:
                return {"status": "error", "message": "You do not own this meal plan"}

            meal_plan = mpm.meal_plan
            order = Order.objects.filter(associated_meal_plan=meal_plan).first()

            chef_meal = get_object_or_404(
                Meal.objects.select_related("chef"),
                id=chef_meal_id,
                chef__isnull=False,
            )

            # Type check
            if chef_meal.meal_type != mpm.meal_type:
                return {
                    "status": "error",
                    "message": f"Chef meal type ({chef_meal.meal_type}) does not match plan meal type ({mpm.meal_type})",
                }

            # Postal‑code eligibility
            if getattr(user, "address", None) and user.address.normalized_postalcode:
                pc = user.address.normalized_postalcode
                country = user.address.country
                serves = ChefPostalCode.objects.filter(
                    chef=chef_meal.chef,
                    postal_code__code=pc,
                    postal_code__country=country,
                ).exists()
                if not serves:
                    return {"status": "error", "message": "Chef does not serve your postal code area"}

            # If plan approved, mark changed and require re‑approval
            if meal_plan.is_approved:
                meal_plan.has_changes = True
                meal_plan.is_approved = False
                meal_plan.save(update_fields=["has_changes", "is_approved"])

            # Mark slot as paid if the order is already paid
            if order and order.is_paid:
                mpm.already_paid = True
                mpm.save(update_fields=["already_paid"])

            # Swap the meal
            mpm.meal = chef_meal
            mpm.save(update_fields=["meal"])

            # ---------------- Order‑linked updates ----------------
            if order:
                # Validate / discover ChefMealEvent
                chef_meal_event = None
                if event_id:
                    chef_meal_event = get_object_or_404(
                        ChefMealEvent, id=event_id, meal=chef_meal
                    )
                    if not chef_meal_event.is_available_for_orders():
                        return {
                            "status": "error",
                            "message": "The specified chef meal event is closed",
                        }
                else:
                    today = timezone.now().date()
                    meal_date = mpm.meal_date or today
                    chef_meal_event = (
                        ChefMealEvent.objects.filter(
                            meal=chef_meal,
                            event_date__gte=today,
                            event_date__lte=meal_date + timedelta(days=3),
                            status__in=["scheduled", "open"],
                            order_cutoff_time__gt=timezone.now(),
                            orders_count__lt=F("max_orders"),
                        )
                        .order_by("event_date", "event_time")
                        .first()
                    )

                if chef_meal_event:
                    total_price = chef_meal_event.current_price * quantity
                    ChefMealOrder.objects.update_or_create(
                        order=order,
                        meal_plan_meal=mpm,
                        defaults={
                            "meal_event": chef_meal_event,
                            "customer": user,
                            "quantity": quantity,
                            "price_paid": total_price,
                            "special_requests": special_requests,
                        },
                    )
                else:
                    # No suitable event – remove any lingering links
                    ChefMealOrder.objects.filter(order=order, meal_plan_meal=mpm).delete()

        return {
            "status": "success",
            "message": "Meal replaced successfully",
            "meal_plan_meal": {
                "id": mpm.id,
                "meal_id": chef_meal.id,
                "meal_name": chef_meal.name,
                "quantity": quantity,
            },
        }
    except MealPlanMeal.DoesNotExist:
        return {"status": "error", "message": "Meal plan meal not found"}
    except Meal.DoesNotExist:
        return {"status": "error", "message": "Chef meal not found"}
    except Exception as e:
        # Send traceback to N8N via webhook at N8N_TRACEBACK_URL 
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"replace_meal_plan_meal", "traceback": traceback.format_exc()})
        return {"status": "error", "message": f"Failed to replace meal plan meal"}

# Function to get all chef connection tools
def get_chef_connection_tools():
    """
    Get all chef connection tools for the OpenAI Responses API.
    
    Returns:
        List of chef connection tools in the format required by the OpenAI Responses API
    """
    return CHEF_CONNECTION_TOOLS
