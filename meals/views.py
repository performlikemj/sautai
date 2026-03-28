import logging
import os
import traceback
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from datetime import date, datetime, timedelta, timezone as py_tz
from .forms import DishForm, IngredientForm, MealForm
from .models import (
    Meal, Cart, Dish, Ingredient, Order, OrderMeal, MealPlan, MealPlanMeal, Instruction, PantryItem, 
    ChefMealEvent, ChefMealOrder, ChefMealReview, PostalCode, ChefPostalCode, StripeConnectAccount, 
    PlatformFeeConfig, PaymentLog, DietaryPreference,
    STATUS_CANCELLED, STATUS_PLACED, STATUS_CONFIRMED, STATUS_COMPLETED,
    STATUS_REFUNDED, STATUS_SCHEDULED, STATUS_OPEN, STATUS_CLOSED, 
    STATUS_IN_PROGRESS
)
from django.http import JsonResponse, HttpResponseBadRequest
from .serializers import (
    MealPlanSerializer, MealSerializer, PantryItemSerializer, UserSerializer, ChefMealEventSerializer, 
    ChefMealEventCreateSerializer, ChefMealOrderSerializer, ChefMealOrderCreateSerializer, 
    ChefMealReviewSerializer, StripeConnectAccountSerializer, DietaryPreferenceSerializer,
    DishSerializer, IngredientSerializer, MealPlanMealSerializer, ChefReceivedOrderSerializer
)
from chefs.models import Chef
from shared.utils import day_to_offset, standardize_response, ChefMealEventPagination
from django.conf import settings
import requests
from django.http import JsonResponse
from rest_framework.response import Response
from django.urls import reverse
from django.http import HttpResponseBadRequest
from custom_auth.models import Address, CustomUser
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponseForbidden
from django.http import HttpResponse
from custom_auth.models import UserRole
import json
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.db.models import Q, F, Sum, Avg, Count, Max
from django.core.paginator import Paginator
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, renderer_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status, viewsets, renderers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
import stripe
import json
import decimal
try:
    from groq import Groq
except ImportError:
    Groq = None
from utils.redis_client import get, set, delete
from django.db import transaction
import uuid
from .audio_utils import process_audio_for_pantry_item
from .utils.stripe_utils import (
    standardize_stripe_response,
    handle_stripe_error,
    get_stripe_return_urls,
    get_active_stripe_account,
    calculate_platform_fee_cents,
    StripeAccountError,
)
from .utils.order_utils import create_chef_meal_orders
import django.db.utils
from django.template.loader import render_to_string
import time
import html
from django.contrib.postgres.fields import ArrayField
from meals.meal_plan_service import apply_modifications
import pytz
from django.views.decorators.csrf import csrf_exempt
from zoneinfo import ZoneInfo
from django.http import HttpResponseForbidden
from meals.feature_flags import legacy_meal_plan_enabled, require_legacy_meal_plan_enabled


LEGACY_MEAL_PLAN = True

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def api_meals_config(request):
    """Expose meal-related feature flags for frontend consumers."""

    return Response({"legacy_meal_plan_enabled": legacy_meal_plan_enabled()})


class EventStreamRenderer(renderers.BaseRenderer):
    media_type = 'text/event-stream'
    format = 'event-stream'
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data

GROQ_API_KEY = getattr(settings, "GROQ_API_KEY", None) or os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY and Groq else None

stripe.api_key = settings.STRIPE_SECRET_KEY

# Helper functions for Redis lock management
def _cleanup_lock_on_task_completion(task_id, user_id, week_start_date):
    """
    Clean up Redis lock when task completes (success or failure).
    This should be called from the Celery task or signal handlers.
    """
    try:
        from utils.redis_client import delete
        lock_key = f"meal_plan_generation_lock_{user_id}_{week_start_date.strftime('%Y_%m_%d')}"
        deleted = delete(lock_key)
        if deleted:
            logger.info(f"Successfully cleaned up Redis lock {lock_key} for completed task {task_id}")
        else:
            logger.warning(f"Redis lock {lock_key} was not found or already expired for task {task_id}")
    except Exception as e:
        logger.error(f"Error cleaning up Redis lock for task {task_id}: {str(e)}")

def _cleanup_meal_plan_locks_for_task(task_id, user_id):
    """
    Clean up Redis locks associated with a specific task ID and user.
    Used when a task completes (success or failure).
    """
    from utils.redis_client import get, delete
    from datetime import datetime, timedelta
    import re
    
    try:
        # Find locks that contain this task_id
        # Pattern: meal_plan_generation_lock_{user_id}_{YYYY_MM_DD}
        lock_pattern = f"meal_plan_generation_lock_{user_id}_*"
        
        # Since Redis doesn't have a scan pattern in our utils, we'll check common date ranges
        # Check last 30 days to find potential locks
        today = timezone.now().date()
        for i in range(30):
            check_date = today - timedelta(days=i)
            lock_key = f"meal_plan_generation_lock_{user_id}_{check_date.strftime('%Y_%m_%d')}"
            lock_value = get(lock_key)
            
            if lock_value == task_id:
                delete(lock_key)
                logger.info(f"Cleaned up meal plan lock {lock_key} for completed task {task_id}")
                break
                
    except Exception as e:
        logger.warning(f"Error during lock cleanup for task {task_id}: {str(e)}")

def _check_and_cleanup_stale_locks(task_id, user_id):
    """
    Check if a lock exists for the given task and clean up if stale.
    Returns True if a valid lock exists, False if no lock or lock was cleaned up.
    """
    from utils.redis_client import get, delete
    from datetime import datetime, timedelta
    from celery.result import AsyncResult
    
    try:
        # Check last 7 days for potential locks
        today = timezone.now().date()
        for i in range(7):
            check_date = today - timedelta(days=i)
            lock_key = f"meal_plan_generation_lock_{user_id}_{check_date.strftime('%Y_%m_%d')}"
            lock_value = get(lock_key)
            
            if lock_value == task_id:
                # Found the lock, now check if task is actually running
                try:
                    task = AsyncResult(task_id)
                    # If task is genuinely pending/started, keep the lock
                    if task.state in ['PENDING', 'STARTED', 'RETRY']:
                        return True
                    else:
                        # Task is not actually running, clean up the lock
                        delete(lock_key)
                        logger.info(f"Cleaned up stale lock {lock_key} for task {task_id} (state: {task.state})")
                        return False
                except Exception:
                    # If we can't check task state, assume it's stale and clean up
                    delete(lock_key)
                    logger.info(f"Cleaned up stale lock {lock_key} for unreachable task {task_id}")
                    return False
        
        # No lock found for this task
        return False
        
    except Exception as e:
        logger.warning(f"Error checking stale locks for task {task_id}: {str(e)}")
        return False

def cleanup_expired_meal_plan_locks(user_id=None, max_age_hours=6):
    """
    Utility function to clean up expired meal plan generation locks.
    Can be called manually or from a periodic task for maintenance.
    
    Args:
        user_id: If provided, only clean locks for this user. Otherwise clean all.
        max_age_hours: Remove locks older than this many hours (default: 6 hours)
    
    Returns:
        dict: Summary of cleanup results
    """
    from utils.redis_client import get, delete
    from datetime import datetime, timedelta
    from celery.result import AsyncResult
    
    cleanup_stats = {
        'locks_checked': 0,
        'locks_removed': 0,
        'active_locks_kept': 0,
        'errors': []
    }
    
    try:
        # Determine date range to check
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=7)  # Check last 7 days
        cutoff_time = timezone.now() - timedelta(hours=max_age_hours)
        
        # If user_id provided, check only that user's locks
        if user_id:
            user_ids = [user_id]
        else:
            # For maintenance mode, we'd need to check all users
            # This is a simplified version - in production you might want to 
            # store a list of user IDs that have active locks
            logger.warning("cleanup_expired_meal_plan_locks called without user_id - limited cleanup")
            return cleanup_stats
        
        for uid in user_ids:
            current_date = start_date
            while current_date <= end_date:
                lock_key = f"meal_plan_generation_lock_{uid}_{current_date.strftime('%Y_%m_%d')}"
                cleanup_stats['locks_checked'] += 1
                
                try:
                    lock_value = get(lock_key)
                    if lock_value:
                        # Check if task is still running
                        task = AsyncResult(lock_value)
                        if task.state in ['PENDING', 'STARTED', 'RETRY']:
                            # Task is active, keep the lock
                            cleanup_stats['active_locks_kept'] += 1
                        else:
                            # Task is complete or failed, remove lock
                            delete(lock_key)
                            cleanup_stats['locks_removed'] += 1
                            logger.info(f"Cleaned up expired lock {lock_key} (task state: {task.state})")
                
                except Exception as e:
                    cleanup_stats['errors'].append(f"Error processing {lock_key}: {str(e)}")
                    logger.warning(f"Error processing lock {lock_key}: {str(e)}")
                
                current_date += timedelta(days=1)
        
        logger.info(f"Lock cleanup completed: {cleanup_stats}")
        return cleanup_stats
        
    except Exception as e:
        cleanup_stats['errors'].append(f"General cleanup error: {str(e)}")
        logger.error(f"Error in cleanup_expired_meal_plan_locks: {str(e)}")
        return cleanup_stats

def is_chef(user):
    if user.is_authenticated:
        try:
            user_role = UserRole.objects.get(user=user)
            result = user_role.current_role == 'chef'
            logger.debug(f"is_chef check for user {user.id}: {result}")
            return result
        except UserRole.DoesNotExist:
            logger.warning(f"UserRole does not exist for user {user.id}")
            return False
    return False


def debug_payment_link_email(request):
    """DEBUG-only: Render the meals/payment_link_email.html with sample or query data."""
    if not settings.DEBUG:
        return HttpResponseForbidden("Previews are only available in DEBUG mode.")

    user = request.user if getattr(request.user, 'is_authenticated', False) else None
    safe_user_name = 'there'
    if user is not None:
        try:
            full_name = getattr(user, 'get_full_name', None)
            if callable(full_name):
                fn = full_name()
                if fn:
                    safe_user_name = fn
            if safe_user_name == 'there':
                uname = getattr(user, 'username', None)
                if not uname and hasattr(user, 'get_username'):
                    try:
                        uname = user.get_username()
                    except Exception:
                        uname = None
                if uname:
                    safe_user_name = uname
        except Exception:
            pass
    ctx = {
        'user_name': safe_user_name,
        'meal_plan_week': request.GET.get('week') or f"{timezone.now().date().strftime('%b %d')} – {(timezone.now().date()+timedelta(days=6)).strftime('%b %d')}",
        'checkout_url': request.GET.get('checkout_url') or 'https://checkout.example.com/session/abc123',
        'order_id': request.GET.get('order_id') or 'ORDER12345',
        'profile_url': request.build_absolute_uri('/'),
    }

    html = render_to_string('meals/payment_link_email.html', ctx)
    return HttpResponse(html)

def is_customer(user):
    if user.is_authenticated:
        try:
            user_role = UserRole.objects.get(user=user)
            return user_role.current_role == 'customer'
        except UserRole.DoesNotExist:
            return False
    return False

def api_search_ingredients(request):
    query = request.GET.get('query', '')
    results = search_ingredients(query)
    return JsonResponse(results)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_meal_plan_preference(request):
    if request.method == 'GET':
        # Retrieve the meal plans for the current user
        meal_plans = MealPlan.objects.filter(user=request.user)
        serializer = MealPlanSerializer(meal_plans, many=True)
        return Response(serializer.data, status=200)


@api_view(['POST'])
@permission_classes([AllowAny])
def api_post_meal_plan_preference(request):
    if request.method == 'POST':
        data = request.data.copy()
        data['user'] = request.user.id  # Assign the current user

        serializer = MealPlanSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        else:
            return Response(serializer.errors, status=400)
        
@csrf_exempt
@api_view(['POST', 'GET', 'OPTIONS'])
@permission_classes([AllowAny])  # Allow unauthenticated access
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_email_approved_meal_plan(request):
    # Support GET query params for environments where POST may be blocked from email clients
    if request.method == 'GET':
        approval_token = request.GET.get('approval_token')
        meal_prep_preference = request.GET.get('meal_prep_preference')
    else:
        approval_token = request.data.get('approval_token')
        meal_prep_preference = request.data.get('meal_prep_preference')
    valid_preferences = dict(MealPlan.MEAL_PREP_CHOICES).keys()

    if not approval_token:
        return Response({'error': 'Approval token is required.'}, status=400)
    
    if not meal_prep_preference or meal_prep_preference not in valid_preferences:
        return Response({'error': 'Invalid meal prep preference.'}, status=400)
    try:
        meal_plan = MealPlan.objects.get(approval_token=approval_token)
        meal_plan.is_approved = True
        meal_plan.has_changes = False
        meal_plan.meal_prep_preference = meal_prep_preference
        meal_plan.save()
        return Response({'status': 'success', 'message': 'Meal plan approved successfully.'})
    except MealPlan.DoesNotExist:
        return Response({'status': 'error', 'message': 'Invalid or expired approval token.'}, status=400)
    
def search_ingredients(query, number=20, apiKey=settings.SPOONACULAR_API_KEY):
    search_url = "https://api.spoonacular.com/food/ingredients/search"
    search_params = {
        "query": query,
        "number": number,
        "apiKey": apiKey,
    }
    response = requests.get(search_url, params=search_params)
    response.raise_for_status()  # Raises an HTTPError if the response status isn't 200
    return response.json()

def embeddings_list(request):
    meals = Meal.objects.all()  # Fetch all meals, or filter as needed
    return render(request, 'meals/embeddings_list.html', {'meals': meals})

def get_ingredient_info(id, apiKey=settings.SPOONACULAR_API_KEY):
    info_url = f"https://api.spoonacular.com/food/ingredients/{id}/information"
    info_params = {
        "amount": 1,
        "apiKey": apiKey,
    }
    response = requests.get(info_url, params=info_params)
    response.raise_for_status()  # Raises an HTTPError if the response status isn't 200
    return response.json()

@user_passes_test(is_chef, login_url='custom_auth:login')
def api_create_ingredient(request):
    if request.method == 'POST':
        chef = request.user.chef
        name = request.POST.get('name')
        spoonacular_id = request.POST.get('spoonacular_id')
        if chef.ingredients.filter(spoonacular_id=spoonacular_id).exists():
            # Ingredient already exists, no need to add it again
            return JsonResponse({"message": "Ingredient already added"}, status=400)
        
        ingredient_info = get_ingredient_info(spoonacular_id)
        if 'error' in ingredient_info:
            return JsonResponse({"message": "Error fetching ingredient information"}, status=400)
        # Extract nutritional information
        calories = next((nutrient['amount'] for nutrient in ingredient_info['nutrition']['nutrients'] if nutrient['name'] == 'Calories'), None)
        fat = next((nutrient['amount'] for nutrient in ingredient_info['nutrition']['nutrients'] if nutrient['name'] == 'Fat'), None)
        carbohydrates = next((nutrient['amount'] for nutrient in ingredient_info['nutrition']['nutrients'] if nutrient['name'] == 'Net Carbohydrates'), None)
        protein = next((nutrient['amount'] for nutrient in ingredient_info['nutrition']['nutrients'] if nutrient['name'] == 'Protein'), None)

        # Create Ingredient object
        ingredient = Ingredient.objects.create(
            chef=chef,
            name=name,
            spoonacular_id=spoonacular_id,
            calories=calories,
            fat=fat,
            carbohydrates=carbohydrates,
            protein=protein,
        )

        # Save the ingredient
        ingredient.save()

        return JsonResponse({
            'name': ingredient.name,
            'spoonacular_id': ingredient.spoonacular_id,
            'calories': ingredient.calories,
            'message': "Ingredient created successfully"
        })




@login_required
@require_http_methods(["GET", "POST"])  # Restrict to GET and POST methods
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_customize_meal_plan(request, meal_plan_id):
    meal_plan = get_object_or_404(MealPlan, id=meal_plan_id, user=request.user)

    if request.method == 'POST':
        # Handle AJAX requests for meal plan modifications
        if request.is_ajax():
            data = json.loads(request.body)
            action = data.get('action')
            meal_id = data.get('meal_id')
            day = data.get('day')

            if action == 'remove':
                MealPlanMeal.objects.filter(meal_plan=meal_plan, meal__id=meal_id, day=day).delete()
                return JsonResponse({'status': 'success', 'action': 'removed'})

            elif action == 'replace':
                new_meal_id = data.get('new_meal_id')
                new_meal = get_object_or_404(Meal, id=new_meal_id)
                MealPlanMeal.objects.filter(meal_plan=meal_plan, meal__id=meal_id, day=day).update(meal=new_meal)
                return JsonResponse({'status': 'success', 'action': 'replaced', 'new_meal': new_meal.name})

            elif action == 'add':
                new_meal_id = data.get('new_meal_id')
                new_meal = get_object_or_404(Meal, id=new_meal_id)
                offset = day_to_offset(day)
                meal_date = meal_plan.week_start_date + timedelta(days=offset)
                MealPlanMeal.objects.create(meal_plan=meal_plan, meal=new_meal, day=day, meal_date=meal_date)
                return JsonResponse({'status': 'success', 'action': 'added', 'new_meal': new_meal.name})

            return JsonResponse({'status': 'error', 'message': 'Invalid action'}, status=400)

        # Render the customization form or UI for GET requests
        else:
            return render(request, 'customize_meal_plan.html', {'meal_plan': meal_plan})

    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)


@login_required
@user_passes_test(is_customer, login_url='custom_auth:profile')
def get_alternative_meals(request):

    # Calculate the current week's date range
    week_shift = max(int(request.user.week_shift), 0)
    adjusted_today = timezone.now().date() + timedelta(weeks=week_shift)
    start_of_week = adjusted_today - timedelta(days=adjusted_today.weekday()) + timedelta(weeks=week_shift)
    end_of_week = start_of_week + timedelta(days=6)

    # Get current day from the request
    current_day = request.GET.get('day', adjusted_today.strftime('%A'))
    # Convert DAYS_OF_WEEK to a list of day names
    days_of_week_list = [day[0] for day in MealPlanMeal.DAYS_OF_WEEK]

    # Convert the day name to a date object
    current_day_date = start_of_week + timedelta(days=days_of_week_list.index(current_day))
    # Retrieve the meal plan for the specified week
    meal_plan = MealPlan.objects.filter(
        user=request.user,
        week_start_date=start_of_week,
        week_end_date=end_of_week
    ).first()

    if not meal_plan:
        return JsonResponse({"message": "No meal plan found for the specified week."})

    # Query MealPlanMeal for the specific day within the meal plan
    meal_plan_meals = MealPlanMeal.objects.filter(meal_plan=meal_plan, day=current_day)

    # Query meals based on postal code, and availability for the specific day
    postal_query = Meal.postal_objects.for_user(user=request.user).filter(start_date=current_day_date)
    # Apply dietary preference filter only if it's not None
    meals = postal_query.filter(id__in=Meal.dietary_objects.for_user(request.user))


    # Return the meals as JSON
    if meals.exists():
        meals_data = [{
            'id': meal.id,
            'name': meal.name,
            'chef': meal.chef.user.username,
            # ... include other meal details as needed ...
        } for meal in meals]
        return JsonResponse({"success": True, "meals": meals_data})
    else:
        return JsonResponse({"success": False, "message": "No alternative meals available."})



@login_required
@user_passes_test(is_customer, login_url='custom_auth:profile')
@require_http_methods(["POST"])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def submit_meal_plan_updates(request):
    try:
        # Load the JSON data from the request
        data = json.loads(request.body)
        updated_meals = data.get('mealPlan')

        # Assuming each meal in updated_meals includes a 'meal_plan_id'
        if not updated_meals:
            raise ValueError("Updated meal plan is empty.")

        # Example: getting the meal_plan_id from the first meal
        meal_plan_id = updated_meals[0].get('meal_plan_id')
        meal_plan = MealPlan.objects.get(id=meal_plan_id, user=request.user)

        # Clear existing MealPlanMeal entries
        MealPlanMeal.objects.filter(meal_plan=meal_plan).delete()

        # Create new MealPlanMeal entries based on the updated meal plan
        offset = day_to_offset(day)
        meal_date = meal_plan.week_start_date + timedelta(days=offset)

        for meal in updated_meals:
            day=meal['day']
            offset = day_to_offset(day)
            meal_date = meal_plan.week_start_date + timedelta(days=offset)
            MealPlanMeal.objects.create(
                meal_plan=meal_plan,
                meal_id=meal['meal_id'],
                day=day,
                meal_date=meal_date
            )

        # Mark plan as changed and require manual approval
        meal_plan.has_changes = True
        meal_plan.is_approved = False
        meal_plan.save()
        return JsonResponse({'status': 'success', 'message': 'Meal plan updated successfully.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_legacy_meal_plan_enabled
def meal_plan_approval(request):
    # Step 1: Retrieve the current MealPlan for the user
    week_shift = max(int(request.user.week_shift), 0)
    today = timezone.now().date() + timedelta(weeks=week_shift)
    meal_plan = get_object_or_404(MealPlan, user=request.user, week_start_date__lte=today, week_end_date__gte=today)
    
    # Check if the meal plan is already associated with an order
    if meal_plan.order:
        if meal_plan.order.is_paid:
            # If the order is paid, redirect to the confirmation page
            messages.info(request, 'This meal plan has already been paid for.')
            return redirect('meals:meal_plan_confirmed')
        else:
            # If the order is not paid, redirect to the payment page
            messages.info(request, 'This meal plan has an unpaid order. Please complete the payment.')
            return redirect('meals:process_payment', order_id=meal_plan.order.id)

    # Step 2: Display it for approval
    if request.method == 'POST':
        # Step 3: Handle meal plan approval
        # Create an Order object
        order = Order.objects.create(
            customer=request.user,
            status='Placed',
            meal_plan=meal_plan
        )

        # Step 5: Create OrderMeal objects for each meal in the meal plan
        for meal in meal_plan.meal.all():
            meal_plan_meal = MealPlanMeal.objects.get(meal_plan=meal_plan, meal=meal)
            order_meal = OrderMeal.objects.create(
                order=order,
                meal=meal, 
                meal_plan_meal=meal_plan_meal,
                quantity=1
            )
            
            # Check if this meal is associated with a ChefMealEvent
            # If so, create a ChefMealOrder
            # Get the date from the meal_plan_meal
            meal_date = meal_plan_meal.meal_date if meal_plan_meal.meal_date else meal_plan.week_start_date + timedelta(days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].index(meal_plan_meal.day))
            
            # Find chef meal events for this meal on the specific date that are still accepting orders
            chef_meal_event = ChefMealEvent.objects.filter(
                meal=meal,
                event_date=meal_date,
                status__in=['scheduled', 'open'],
                order_cutoff_time__gt=timezone.now(),
                orders_count__lt=F('max_orders')
            ).first()
            
            if chef_meal_event:
                # Update the OrderMeal with the chef_meal_event
                order_meal.chef_meal_event = chef_meal_event
                order_meal.save()
                
                # Create the corresponding ChefMealOrder
                try:
                    ChefMealOrder.objects.create(
                        order=order,
                        meal_event=chef_meal_event,
                        customer=request.user,
                        quantity=1,
                        price_paid=chef_meal_event.current_price,
                        status='placed',
                        special_requests=order.special_requests if order.special_requests else ''
                    )
                    logger.info(f"Created ChefMealOrder for order_id={order.id}, meal_event_id={chef_meal_event.id}")
                except Exception as e:
                    logger.error(f"Failed to create ChefMealOrder for order_id={order.id}, meal_event_id={chef_meal_event.id}: {str(e)}")
                    logger.error(traceback.format_exc())
            elif meal.chef:
                # This is a chef meal without a specific event, we should log this case
                logger.warning(f"Meal {meal.id} has chef_id={meal.chef.id} but no valid ChefMealEvent was found for date {meal_date}")
                
                # Try to find any event for this meal to help with debugging
                any_event = ChefMealEvent.objects.filter(meal=meal).first()
                if any_event:
                    logger.warning(f"Found event with id={any_event.id}, date={any_event.event_date}, status={any_event.status}, cutoff={any_event.order_cutoff_time}, orders={any_event.orders_count}/{any_event.max_orders}")

        # Step 4: Link the Order to the MealPlan
        meal_plan.order = order
        meal_plan.save()


        # Step 6: Redirect to payment
        return redirect('meals:process_payment', order_id=order.id)
    
    # Render the meal plan approval page
    return render(request, 'meals/approve_meal_plan.html', {'meal_plan': meal_plan})



@api_view(['GET'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_get_meal_plans(request):
    try:
        user = request.user

        week_start_date_str = request.query_params.get('week_start_date')
        
        if week_start_date_str:
            week_start_date = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
            week_end_date = week_start_date + timedelta(days=6)
            meal_plans = MealPlan.objects.filter(
                user=user,
                week_start_date__lte=week_end_date,   # starts on or before the last day
                week_end_date__gte=week_start_date    # ends on or after the first day
            )
        else:
            meal_plans = MealPlan.objects.filter(user=user)

        serializer = MealPlanSerializer(meal_plans, many=True)

        # Flatten all meals across the selected meal plans for easier polling
        from .models import MealPlanMeal
        from .serializers import MealPlanMealSerializer
        all_plan_meals_qs = MealPlanMeal.objects.filter(meal_plan__in=meal_plans).select_related('meal', 'meal_plan', 'meal__chef')
        flattened_meals = MealPlanMealSerializer(all_plan_meals_qs, many=True, context={'request': request}).data

        # Count how many chef meals are in these meal plans
        chef_meal_count = 0
        for meal_plan in meal_plans:
            chef_meals = MealPlanMeal.objects.filter(
                meal_plan=meal_plan,
                meal__chef__isnull=False
            ).count()
            chef_meal_count += chef_meals
        
        response_data = {
            "meal_plans": serializer.data,
            # Top-level meals array for easy polling UI merge; includes meal_plan_meal_id
            "meals": flattened_meals,
            # Alias maintained for backwards-compat with older UI code
            "meal_plan_meals": flattened_meals,
            "has_chef_meals": chef_meal_count > 0,
            "chef_meal_count": chef_meal_count
        }
        

        # Count chef meal recommendations
        chef_meal_count = sum(1 for mp in meal_plans for meal in mp.meal.all() if hasattr(meal, 'chef') and meal.chef is not None)

        
        return Response(response_data, status=200)
    
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_get_meal_plan_by_id(request, meal_plan_id):
    try:
        user = request.user
        meal_plan = MealPlan.objects.get(id=meal_plan_id, user=user)
        serializer = MealPlanSerializer(meal_plan)
        return Response(serializer.data, status=200)
    except MealPlan.DoesNotExist:
        return Response({"error": "Meal plan not found."}, status=404)
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@renderer_classes([EventStreamRenderer, renderers.JSONRenderer])
# @deprecated Legacy meal-plan SSE endpoint guarded by LEGACY_MEAL_PLAN.
def api_stream_meal_plan_detail(request, meal_plan_id):
    """Stream an existing meal plan incrementally via Server-Sent Events."""

    import json
    from django.core.serializers.json import DjangoJSONEncoder
    from django.http import StreamingHttpResponse
    from django.db.models import Prefetch, F
    from django.utils import timezone

    try:
        user = request.user
        meal_plan = MealPlan.objects.select_related('user', 'order').get(id=meal_plan_id, user=user)
    except MealPlan.DoesNotExist:
        return Response({"error": "Meal plan not found."}, status=404)
    except Exception as e:  # pragma: no cover - defensive logging
        logger.exception("Unexpected error locating meal plan during streaming", exc_info=e)
        return Response({"error": str(e)}, status=500)

    from meals.models import MealPlanMeal, ChefMealEvent
    from meals.serializers import MealPlanMealSerializer, MealPlanSummarySerializer

    now = timezone.now()
    upcoming_events_qs = ChefMealEvent.objects.filter(
        event_date__gte=now.date(),
        status__in=['scheduled', 'open'],
        order_cutoff_time__gt=now,
        orders_count__lt=F('max_orders')
    ).order_by('event_date', 'event_time')

    meals_qs = (
        MealPlanMeal.objects
        .filter(meal_plan=meal_plan)
        .select_related('meal', 'meal__chef', 'meal_plan', 'meal_plan__user')
        .prefetch_related(
            'meal__dietary_preferences',
            'meal__custom_dietary_preferences',
            'meal__dishes',
            'meal__meal_dishes',
            Prefetch('meal__events', queryset=upcoming_events_qs, to_attr='prefetched_upcoming_events')
        )
        .order_by('day', 'meal_type', 'id')
    )

    total_meals = meals_qs.count()

    def dump(payload):
        return json.dumps(payload, cls=DjangoJSONEncoder)

    def event_stream():
        sent_done = False
        try:
            yield ":keepalive\n\n"

            summary = MealPlanSummarySerializer(meal_plan, context={'request': request}).data
            yield "event: summary\n"
            yield f"data: {dump(summary)}\n\n"

            yield "event: progress\n"
            yield f"data: {dump({'count': 0, 'total': total_meals, 'pct': 0 if total_meals else 100})}\n\n"

            for idx, meal_plan_meal in enumerate(meals_qs, start=1):
                meal_payload = MealPlanMealSerializer(meal_plan_meal, context={'request': request}).data
                yield "event: meal\n"
                yield f"data: {dump(meal_payload)}\n\n"

                if total_meals:
                    pct = int((idx / total_meals) * 100)
                else:
                    pct = 100
                yield "event: progress\n"
                yield f"data: {dump({'count': idx, 'total': total_meals, 'pct': pct})}\n\n"

            yield "event: done\n\n"
            sent_done = True
        except Exception as exc:  # pragma: no cover - streaming safety
            logger.exception("Error while streaming meal plan detail", exc_info=exc)
            yield "event: error\n"
            yield f"data: {dump({'message': str(exc)})}\n\n"
        finally:
            if not sent_done:
                yield "event: done\n\n"
            yield "event: close\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache, no-transform'
    response['X-Accel-Buffering'] = 'no'
    return response

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_generate_cooking_instructions(request):
    try:
        from .meal_instructions import generate_instructions
        # Extract meal_plan_meal_ids from request data
        meal_plan_meal_ids = request.data.get('meal_plan_meal_ids', [])
        if not meal_plan_meal_ids:
            return Response({"error": "meal_plan_meal_ids are required"}, status=400)

        # Verify that each MealPlanMeal exists and belongs to the current user
        valid_meal_plan_meal_ids = []
        for meal_plan_meal_id in meal_plan_meal_ids:
            try:
                meal_plan_meal = MealPlanMeal.objects.get(id=meal_plan_meal_id)
                valid_meal_plan_meal_ids.append(meal_plan_meal.id)  # Append the ID, not the MealPlanMeal instance
            except MealPlanMeal.DoesNotExist:
                logger.warning(f"MealPlanMeal with ID {meal_plan_meal_id} not found or unauthorized access attempted.")
                continue

        if not valid_meal_plan_meal_ids:
            return Response({"error": "No valid meal plan meals found or you do not have permission to access them."}, status=404)

        # Generate cooking instructions for each valid meal plan meal
        # Frontend-triggered generation should never send emails
        generate_instructions(valid_meal_plan_meal_ids)

        return Response({"message": "Cooking instructions generation initiated successfully for the selected meal plan meals."}, status=200)

    except Exception as e:
        logger.error(f"An error occurred while initiating cooking instructions generation: {str(e)}")
        return Response({"error": "An unexpected error occurred. Please try again later."}, status=500)
    
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_remove_meal_from_plan(request):
    """
    API endpoint to remove meals from a user's meal plan.
    Expects a list of MealPlanMeal IDs in the request data.
    """
    logger.info("Starting api_remove_meal_from_plan")
    user = request.user
    meal_plan_meal_ids = request.data.get('meal_plan_meal_ids', [])
    logger.info(f"Removing meals from meal plan: {meal_plan_meal_ids}") 
    logger.info(f"User: {user}")
    if not meal_plan_meal_ids:
        return Response({"error": "No meal_plan_meal_ids provided."}, status=400)

    # Ensure meal_plan_meal_ids is a list of integers
    try:
        meal_plan_meal_ids = [int(id) for id in meal_plan_meal_ids if id]
    except ValueError:
        return Response({"error": "Invalid meal_plan_meal_ids provided."}, status=400)

    # Fetch MealPlanMeal instances that belong to the user
    meal_plan_meals = MealPlanMeal.objects.filter(
        id__in=meal_plan_meal_ids,
        meal_plan__user=user
    )

    if not meal_plan_meals.exists():
        return Response({"error": "No meal plan meals found to delete."}, status=404)

    # Delete meal plan meals
    for meal_plan_meal in meal_plan_meals:
        meal_plan_meal.delete()

    return Response({"message": "Selected meals removed from the plan."}, status=200)
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_fetch_instructions(request):
    from meals.models import MealPlanMeal, Instruction, MealPlan, MealPlanInstruction
    meal_plan_meal_ids = request.query_params.get('meal_plan_meal_ids', '').split(',')
    meal_plan_id = request.query_params.get('meal_plan_id', None)
    
    # Get the meal plan ID from the first meal plan meal if not provided
    if not meal_plan_id and meal_plan_meal_ids:
        try:
            meal_plan_meal = MealPlanMeal.objects.filter(id=meal_plan_meal_ids[0]).first()
            if meal_plan_meal:
                meal_plan_id = meal_plan_meal.meal_plan.id
            else:
                return Response({"error": "Invalid meal plan meal ID"}, status=404)
        except MealPlanMeal.DoesNotExist:
            return Response({"error": "Invalid meal plan meal ID"}, status=404)
    
    meal_plan = get_object_or_404(MealPlan, id=meal_plan_id)
    meal_prep_preference = meal_plan.meal_prep_preference
    instructions = []

    if meal_prep_preference == 'daily':
        if not meal_plan_meal_ids:
            return Response({"error": "meal_plan_meal_ids are required for daily meal prep preference"}, status=400)
        meal_plan_meal_ids = [int(id) for id in meal_plan_meal_ids if id]

        for meal_plan_meal_id in meal_plan_meal_ids:
            meal_plan_meal = get_object_or_404(MealPlanMeal, id=meal_plan_meal_id)
            instruction = Instruction.objects.filter(meal_plan_meal=meal_plan_meal).first()
            # Calculate the date based on the meal plan's week start date and the meal's day
            meal_plan = meal_plan_meal.meal_plan
            day_of_week = meal_plan_meal.day  # e.g., 'Monday'
            week_start_date = meal_plan.week_start_date

            # Map day names to offsets from the start date
            day_offset = {
                'Monday': 0,
                'Tuesday': 1,
                'Wednesday': 2,
                'Thursday': 3,
                'Friday': 4,
                'Saturday': 5,
                'Sunday': 6,
            }
            meal_date = week_start_date + timedelta(days=day_offset[day_of_week])

            meal_name = meal_plan_meal.meal.name
            if instruction:
                instructions.append({
                    "meal_plan_meal_id": meal_plan_meal_id,
                    "instruction_type": "daily",
                    "date": meal_date.isoformat(),
                    "meal_name": meal_name,
                    "instructions": instruction.content
                })
            else:
                instructions.append({
                    "meal_plan_meal_id": meal_plan_meal_id,
                    "instruction_type": "daily",
                    "date": meal_date.isoformat(),
                    "meal_name": meal_name,
                    "instructions": None
                })

    elif meal_prep_preference == 'one_day_prep':
        # Fetch all instructions for the meal plan
        meal_plan_instructions = MealPlanInstruction.objects.filter(
            meal_plan=meal_plan
        ).order_by('date')

        for instruction in meal_plan_instructions:
            instruction_data = {
                "meal_plan_id": meal_plan.id,
                "instruction_type": "bulk_prep" if instruction.is_bulk_prep else "follow_up",
                "date": instruction.date.isoformat(),
                "instructions": instruction.instruction_text
            }
            instructions.append(instruction_data)

    else:
        return Response({"error": f"Unknown meal_prep_preference '{meal_prep_preference}'"}, status=400)

    return Response({
        "meal_prep_preference": meal_prep_preference,
        "instructions": instructions
    }, status=200)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_approve_meal_plan(request):
    """
    Endpoint to approve a meal plan with specified meal prep preference.
    Expects meal_plan_id and meal_prep_preference in request data.
    Finds corresponding ChefMealEvents for chef meals and uses their price.
    """

    meal_plan_id = request.data.get('meal_plan_id')
    meal_prep_preference = request.data.get('meal_prep_preference')
    # user_id is available via request.user, no need to pass in request data usually
    

    
    if not meal_plan_id:
        return Response({'error': 'Meal plan ID is required.'}, status=400)
    
    valid_preferences = dict(MealPlan.MEAL_PREP_CHOICES).keys()
    if not meal_prep_preference or meal_prep_preference not in valid_preferences:
        return Response({'error': 'Invalid meal prep preference.'}, status=400)

    try:
        with transaction.atomic():
            meal_plan = get_object_or_404(MealPlan, id=meal_plan_id, user=request.user)


            if meal_plan.is_approved:
                return Response({
                    'status': 'success',
                    'message': 'Meal plan already approved.',
                    'requires_payment': any(
                        meal_plan_meal.meal.chef is not None and 
                        ChefMealEvent.objects.filter(
                            meal=meal_plan_meal.meal,
                            chef=meal_plan_meal.meal.chef,
                            event_date=meal_plan_meal.meal_date,
                            status__in=[STATUS_SCHEDULED, STATUS_OPEN],
                            order_cutoff_time__gt=timezone.now(),
                            current_price__gt=0
                        ).exists()
                        for meal_plan_meal in meal_plan.mealplanmeal_set.all().select_related('meal', 'meal__chef')
                    )
                })

            # Data structure to hold meal plan meals and their corresponding event/price
            items_to_order = [] # List of tuples: (meal_plan_meal, event, event_price)
            total_cost = decimal.Decimal('0.00') # Use Decimal for currency
            now = timezone.now()


            for meal_plan_meal in meal_plan.mealplanmeal_set.all().select_related('meal', 'meal__chef'):
                meal = meal_plan_meal.meal


                # Check if it's a chef meal
                if meal.chef is not None:

                    # Find the corresponding active ChefMealEvent for this meal on this date
                    event = ChefMealEvent.objects.filter(
                        meal=meal,
                        chef=meal.chef, # Ensure it's the same chef
                        event_date=meal_plan_meal.meal_date,
                        status__in=[STATUS_SCHEDULED, STATUS_OPEN], # Ensure event is active
                        order_cutoff_time__gt=now # Ensure ordering is still open
                    ).order_by('-created_at').first() # Get the most recent if multiple somehow exist

                    if event:
                        if event.current_price is not None and event.current_price > 0:

                            items_to_order.append((meal_plan_meal, event, event.current_price))
                            total_cost += event.current_price # Assuming quantity 1 per meal plan meal
                        else:
                            logger.warning(f"No current price found for event {event.id} for meal {meal.name} on date {meal_plan_meal.meal_date}")
                    else:
                        logger.warning(f"No active event found for meal {meal.name} on date {meal_plan_meal.meal_date}")
                else:
                    logger.warning(f"No chef found for meal {meal.name} on date {meal_plan_meal.meal_date}")




            # Update meal plan preferences regardless of payment
            meal_plan.is_approved = True
            meal_plan.has_changes = False
            meal_plan.meal_prep_preference = meal_prep_preference
            meal_plan.save()


            # Only create an order if there are items to pay for
            if items_to_order and total_cost > 0:

                # Create an Order for the approved meal plan
                order = Order.objects.create(
                    customer=request.user,
                    status='Placed', # Initial status
                    meal_plan=meal_plan,
                    # Add address if available
                    address=request.user.address if hasattr(request.user, 'address') else None,
                )


                # Add meals from the list to the order
                for meal_plan_meal, event, price in items_to_order:
                    OrderMeal.objects.create(
                        order=order,
                        meal=meal_plan_meal.meal,
                        meal_plan_meal=meal_plan_meal,
                        chef_meal_event=event, # Link the specific event
                        quantity=1 # Assuming quantity 1 from meal plan
                    )

                    
                # Link the order to the meal plan
                meal_plan.order = order
                meal_plan.save()


                return Response({
                    'status': 'success',
                    'message': 'Meal plan approved successfully. Payment required.',
                    'order_id': order.id,
                    'requires_payment': True
                })
            else:
                # No payment required

                return Response({
                    'status': 'success',
                    'message': 'Meal plan approved successfully. No payment required.',
                    'requires_payment': False
                })

    except MealPlan.DoesNotExist:

        logger.warning(f"Meal plan not found for ID {meal_plan_id} requested by user {request.user.id}")
        return Response({
            'status': 'error',
            'message': 'Meal plan not found.'
        }, status=404)
    except Exception as e:

        logger.error(f"Error approving meal plan {meal_plan_id} for user {request.user.id}: {str(e)}", exc_info=True) # Log full traceback
        return Response({
            'status': 'error',
            'message': 'An error occurred while approving the meal plan.'
        }, status=500)

class PantryItemPagination(PageNumberPagination):
    page_size = 10  # Adjust as needed
    page_size_query_param = 'page_size'
    max_page_size = 100

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_pantry_items(request):
    """
    GET: List all pantry items for the authenticated user with pagination.
    POST: Create a new pantry item for the authenticated user.
    """
    
    if request.method == 'GET':
        pantry_items = PantryItem.objects.filter(user=request.user).order_by('-expiration_date')
        paginator = PantryItemPagination()
        result_page = paginator.paginate_queryset(pantry_items, request)
        serializer = PantryItemSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == 'POST':
        # Ensure request.data is a dictionary, not a string
        if isinstance(request.data, str):
            try:
                data = json.loads(request.data)
            except json.JSONDecodeError:
                return Response({"error": "Invalid JSON format."}, status=400)
        else:
            data = request.data

        serializer = PantryItemSerializer(data=data)
        if serializer.is_valid():
            serializer.save(user=request.user) 
            return Response(serializer.data, status=201)
        else:
            return Response(serializer.errors, status=400)
    
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_pantry_item_detail(request, pk):
    """
    Handles GET, PUT/PATCH, DELETE methods for a single pantry item.
    """
    pantry_item = get_object_or_404(PantryItem, pk=pk, user=request.user)

    if request.method == 'GET':
        serializer = PantryItemSerializer(pantry_item)
        return Response(serializer.data, status=200)

    elif request.method in ['PUT', 'PATCH']:
        # If request.data is a string (which it shouldn't be in a correctly configured API request)
        if isinstance(request.data, str):
            try:
                # Convert the string to a dictionary
                data = json.loads(request.data)
            except json.JSONDecodeError:
                return Response({"error": "Invalid JSON format."}, status=400)
        else:
            # Otherwise, use request.data as is
            data = request.data


        # Set partial=True for PATCH and False for PUT
        partial = request.method == 'PATCH'
        serializer = PantryItemSerializer(pantry_item, data=data, partial=partial)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        else:
            return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        pantry_item.delete()
        return Response(status=204)


# Emergency pantry item API
@api_view(['POST'])
def api_generate_emergency_plan(request):
    from meals.email_service import generate_emergency_supply_list
    """
    API endpoint to generate emergency supply list for users.
    """
    try:
        approval_token = request.data.get('approval_token')
        
        if not approval_token:
            return Response({'error': 'Approval token is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get the meal plan associated with this approval token
        try:
            meal_plan = MealPlan.objects.get(approval_token=approval_token)
            user = meal_plan.user
        except MealPlan.DoesNotExist:
            return Response({'error': 'Invalid or expired approval token'}, status=status.HTTP_404_NOT_FOUND)
        
        # Generate emergency supply list via email
        try:
            generate_emergency_supply_list(user.id)
            return Response({'message': 'Emergency supply list generated and sent via email'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'Failed to generate emergency supply list: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        return Response({'error': f'Unexpected error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_update_meals_with_prompt(request):
    """
    API endpoint to update meals in a meal plan based on a text prompt.
    Requires meal_plan_meal_ids and their corresponding dates to ensure correct meal updates.
    """
    logger.info("Starting api_update_meals_with_prompt")
    from meals.meal_generation import generate_and_create_meal
    try:
        meal_plan_meal_ids = request.data.get('meal_plan_meal_ids', [])
        meal_dates = request.data.get('meal_dates', [])
        prompt = request.data.get('prompt', '').strip()
        logger.info(f"Received meal_plan_meal_ids: {meal_plan_meal_ids}, dates: {meal_dates}, prompt: {prompt}")
        if not meal_plan_meal_ids or not meal_dates:
            logger.warning("Missing required data: meal_plan_meal_ids or meal_dates")
            return Response({
                "error": "Both meal_plan_meal_ids and meal_dates are required."
            }, status=400)

        if len(meal_plan_meal_ids) != len(meal_dates):
            logger.warning("Mismatched lengths: meal_plan_meal_ids and meal_dates")
            return Response({
                "error": "Number of meal IDs must match number of dates."
            }, status=400)

        # Get current date in the user's timezone for comparisons
        user_tz = ZoneInfo(getattr(request.user, 'timezone', 'UTC') or 'UTC')
        today = timezone.now().astimezone(user_tz).date()
        logger.info(f"Current date (user tz {user_tz}): {today}")

        # Convert string dates to date objects and create ID-to-date mapping
        try:
            id_date_pairs = []
            past_date_pairs = []
            for meal_id, date_str in zip(meal_plan_meal_ids, meal_dates):
                meal_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Check if date is in the past
                if meal_date < today:
                    logger.info(f"Skipping past date: {date_str} for meal_id: {meal_id}")
                    past_date_pairs.append((meal_id, meal_date))
                    continue  # Skip past dates
                id_date_pairs.append((meal_id, meal_date))
                logger.info(f"Added valid date pair: meal_id={meal_id}, date={date_str}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
            return Response({
                "error": "Invalid date format. Use YYYY-MM-DD."
            }, status=400)

        if not id_date_pairs:
            # If all provided dates are in the past, return a specific message
            if 'past_date_pairs' in locals() and past_date_pairs:
                past_dates_str = [d.strftime('%Y-%m-%d') for _, d in past_date_pairs]
                logger.warning(f"All selected meals are in the past; cannot update. Past dates: {past_dates_str}")
                return Response({
                    "error": "Cannot update past meals. Selected dates are in the past and cannot be edited.",
                    "past_dates": past_dates_str
                }, status=400)
            logger.warning("No valid future dates found in request")
            return Response({
                "error": "No valid future dates provided for meal updates."
            }, status=400)

        updates = []
        logger.info("Starting meal updates process")
        total_meals = len(id_date_pairs)
        processed_meals = 0

        # Process each meal plan meal directly from ID-date pairs
        for meal_plan_meal_id, meal_date in id_date_pairs:
            try:
                meal_plan_meal = MealPlanMeal.objects.select_related('meal_plan', 'meal').get(
                    id=meal_plan_meal_id,
                    meal_plan__user=request.user
                )
                logger.info(f"Processing meal: ID={meal_plan_meal.id}, Name={meal_plan_meal.meal.name}, Date={meal_date}")

                # Add day verification
                expected_day = meal_date.strftime("%A")
                if meal_plan_meal.day != expected_day:
                    error_message = (
                        f"Day mismatch for MealPlanMeal ID {meal_plan_meal.id}: "
                        f"expected day '{expected_day}' (from provided date {meal_date}), "
                        f"but found day '{meal_plan_meal.day}' with meal type '{meal_plan_meal.meal_type}'."
                    )
                    logger.error(error_message)
                    return Response({
                        "error": error_message,
                        "meal_plan_meal": {
                            "id": meal_plan_meal.id,
                            "name": meal_plan_meal.meal.name,
                            "day": meal_plan_meal.day,
                            "meal_type": meal_plan_meal.meal_type,
                            "provided_date": meal_date.strftime("%Y-%m-%d")
                        }
                    }, status=400)

            except MealPlanMeal.DoesNotExist:
                error_message = f"Meal plan meal with ID {meal_plan_meal_id} not found or unauthorized"
                logger.warning(error_message)
                return Response({
                    "error": error_message,
                    "details": {
                        "meal_plan_meal_id": meal_plan_meal_id,
                        "provided_date": meal_date.strftime("%Y-%m-%d")
                    }
                }, status=404)

        # Get the meal plan from the first valid meal
        meal_plan = None
        for meal_plan_meal_id, _ in id_date_pairs:
            try:
                meal_plan_meal = MealPlanMeal.objects.select_related('meal_plan').get(
                    id=meal_plan_meal_id,
                    meal_plan__user=request.user
                )
                meal_plan = meal_plan_meal.meal_plan
                break
            except MealPlanMeal.DoesNotExist:
                continue

        if not meal_plan:
            logger.warning("No valid meal plan found")
            return Response({
                "error": "No valid meal plan found for the specified meals."
            }, status=404)

        logger.info(f"Retrieved meal plan with ID: {meal_plan.id}")

        # Create a mapping of meal dates
        meal_dates_map = {meal_id: date for meal_id, date in id_date_pairs}

        # If no prompt is provided, try suggest_alternative_meals first
        if not prompt:
            logger.info("No prompt provided, attempting to find alternative meals")
            # Perform the whole no-prompt flow atomically to avoid partial deletions
            with transaction.atomic():
                # Collect days, meal types, and old meal IDs without deleting yet
                days_of_week = []
                meal_types = []
                old_meal_ids = []
                for meal_plan_meal_id, _ in id_date_pairs:
                    try:
                        meal_plan_meal = MealPlanMeal.objects.get(id=meal_plan_meal_id, meal_plan__user=request.user)
                        days_of_week.append(meal_plan_meal.day)
                        meal_types.append(meal_plan_meal.meal_type)
                        old_meal_ids.append(meal_plan_meal.meal.id)
                        logger.info(f"Queued for update: Day={meal_plan_meal.day}, Type={meal_plan_meal.meal_type}, Old Meal ID={meal_plan_meal.meal.id}")
                    except MealPlanMeal.DoesNotExist:
                        logger.warning(f"Meal plan meal with ID {meal_plan_meal_id} not found or unauthorized")
                        continue

                # Use the existing suggest_alternative_meals function to get alternatives
                from shared.utils import suggest_alternative_meals
                alternatives_response = suggest_alternative_meals(
                    request=request,
                    meal_ids=old_meal_ids,
                    days_of_week=days_of_week,
                    meal_types=meal_types
                )
                logger.info(f"Alternatives response: {alternatives_response}")

                # If the helper returned an error, abort and rollback
                if isinstance(alternatives_response, dict) and alternatives_response.get('status') == 'error':
                    raise Exception(alternatives_response.get('message', 'Failed to suggest alternative meals'))

                # Get the alternative meals
                alternative_meals = alternatives_response.get('alternative_meals', [])

                if alternative_meals:
                    logger.info(f"Found {len(alternative_meals)} alternative meals")
                    # Use the alternative meals to update the meal plan without prior deletion
                    from shared.utils import replace_meal_in_plan
                    for old_meal_id, day, meal_type, alternative in zip(old_meal_ids, days_of_week, meal_types, alternative_meals):
                        new_meal_id = alternative['meal_id']
                        logger.info(f"Processing alternative meal: Day={day}, Type={meal_type}, New ID={new_meal_id}")
                        result = replace_meal_in_plan(
                            request=request,
                            meal_plan_id=meal_plan.id,
                            old_meal_id=old_meal_id,
                            new_meal_id=new_meal_id,
                            day=day,
                            meal_type=meal_type
                        )

                        if result['status'] != 'success':
                            raise Exception(result.get('message', 'Failed to replace meal'))

                        updates.append({
                            "old_meal": {
                                "id": old_meal_id,
                                "name": result['replaced_meal']['old_meal']
                            },
                            "new_meal": {
                                "id": new_meal_id,
                                "name": result['replaced_meal']['new_meal'],
                                "was_generated": False
                            }
                        })
                        processed_meals += 1
                        logger.info(f"Successfully replaced meal {processed_meals}/{total_meals}")

                else:
                    logger.info("No alternatives found, proceeding to generate new meals without deleting existing entries first")
                    # Generate new meals and then replace existing entries atomically
                    from shared.utils import create_meal, replace_meal_in_plan
                    for old_meal_id, day, meal_type in zip(old_meal_ids, days_of_week, meal_types):
                        # Generate the new meal
                        gen_response = create_meal(request=request, meal_type=meal_type)
                        if not isinstance(gen_response, dict) or gen_response.get('status') not in ('success', 'info'):
                            raise Exception(gen_response.get('message', 'Failed to generate meal'))

                        # Extract meal object/id
                        if gen_response.get('meal') and isinstance(gen_response['meal'], dict):
                            new_meal_id = gen_response['meal']['id']
                            new_meal_name = gen_response['meal']['name']
                        else:
                            # In some paths create_meal may return a model instance
                            new_meal = gen_response.get('meal') or gen_response.get('generated_meal')
                            new_meal_id = getattr(new_meal, 'id', None)
                            new_meal_name = getattr(new_meal, 'name', 'Unknown')
                        if not new_meal_id:
                            raise Exception('Generated meal did not return a valid ID')

                        # Replace existing plan entry with the newly generated meal
                        rep_result = replace_meal_in_plan(
                            request=request,
                            meal_plan_id=meal_plan.id,
                            old_meal_id=old_meal_id,
                            new_meal_id=new_meal_id,
                            day=day,
                            meal_type=meal_type
                        )
                        if rep_result['status'] != 'success':
                            raise Exception(rep_result.get('message', 'Failed to replace meal with generated meal'))

                        updates.append({
                            "old_meal": {
                                "id": old_meal_id,
                                "name": rep_result['replaced_meal']['old_meal']
                            },
                            "new_meal": {
                                "id": new_meal_id,
                                "name": new_meal_name,
                                "was_generated": True,
                                "used_pantry_items": gen_response.get('used_pantry_items', [])
                            }
                        })
                        processed_meals += 1
                        logger.info(f"Successfully generated and replaced meal {processed_meals}/{total_meals}")

        elif prompt:
            logger.info(f"Prompt provided: '{prompt}', proceeding to update {total_meals} meals")
            
            # Store meal info before deletion
            meal_info = []
            for meal_plan_meal_id, meal_date in id_date_pairs:
                try:
                    meal_plan_meal = MealPlanMeal.objects.get(id=meal_plan_meal_id, meal_plan__user=request.user)
                    meal_info.append({
                        'id': meal_plan_meal_id,
                        'day': meal_plan_meal.day,
                        'meal_type': meal_plan_meal.meal_type,
                        'old_meal': meal_plan_meal.meal,
                        'meal_date': meal_date
                    })
                    logger.info(f"Removing meal plan meal: {meal_plan_meal.meal.name} from {meal_plan_meal.day} {meal_plan_meal.meal_type}")
                    
                    # Delete only the specific meal plan meal
                    try:
                        with transaction.atomic():
                            # Verify no existing meal plan meal before deletion
                            existing = MealPlanMeal.objects.filter(
                                meal_plan=meal_plan,
                                day=meal_plan_meal.day,
                                meal_type=meal_plan_meal.meal_type
                            ).exclude(id=meal_plan_meal_id).exists()
                            
                            if existing:
                                raise Exception(f"Found existing meal plan meal for {meal_plan_meal.day} {meal_plan_meal.meal_type}")
                            
                            # Delete only this specific meal plan meal
                            meal_plan_meal.delete()
                            logger.info(f"Deleted meal plan meal ID {meal_plan_meal_id}")
                            
                            # Verify the deletion
                            if MealPlanMeal.objects.filter(id=meal_plan_meal_id).exists():
                                raise Exception(f"Failed to delete meal plan meal ID {meal_plan_meal_id}")
                    except Exception as e:
                        logger.error(f"Error during meal deletion: {str(e)}")
                        return Response({
                            "error": f"Failed to delete meal plan meal: {str(e)}"
                        }, status=500)
                except MealPlanMeal.DoesNotExist:
                    logger.warning(f"Meal plan meal with ID {meal_plan_meal_id} not found or unauthorized")
                    continue

            # Get existing meal names and embeddings once before the loop
            existing_meal_names = {name for name in meal_plan.mealplanmeal_set.values_list('meal__name', flat=True)}
            existing_meal_embeddings = list(meal_plan.mealplanmeal_set.values_list('meal__meal_embedding', flat=True))
            
            # Now create new meals for each removed meal
            for info in meal_info:
                logger.info(f"Generating new meal for {info['day']} {info['meal_type']}")
                result = generate_and_create_meal(
                    user=request.user,
                    meal_plan=meal_plan,
                    meal_type=info['meal_type'],
                    existing_meal_names=existing_meal_names,
                    existing_meal_embeddings=existing_meal_embeddings,
                    user_id=request.user.id,
                    day_name=info['day'],
                    user_prompt=prompt
                )

                if result['status'] == 'success':
                    new_meal = result['meal']
                    logger.info(f"Successfully generated meal '{new_meal.name}' for {info['day']} {info['meal_type']}")
                    
                    # Add to updates list - no need to create MealPlanMeal as it's already created by generate_and_create_meal
                    updates.append({
                        "old_meal": {
                            "id": info['old_meal'].id,
                            "name": info['old_meal'].name
                        },
                        "new_meal": {
                            "id": new_meal.id,
                            "name": new_meal.name,
                            "was_generated": True,
                            "used_pantry_items": result.get('used_pantry_items', [])
                        }
                    })
                    processed_meals += 1
                    logger.info(f"Successfully processed meal {processed_meals}/{total_meals}")

        # Mark the meal plan as having changes
        if updates:
            logger.info(f"Updates completed: {len(updates)} meals updated out of {total_meals} selected")
            # Mark plan changed; keep unapproved until user approves
            meal_plan.has_changes = True
            meal_plan.is_approved = False
            meal_plan.save()
        
        logger.info("Successfully completed meal updates")
        return Response({
            "message": f"Successfully updated {len(updates)} meals",
            "updates": updates
        }, status=200)

    except Exception as e:
        logger.error(f"Error in api_update_meals_with_prompt: {str(e)}")
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Error in api_update_meals_with_prompt: {str(e)}", "source":"api_update_meals_with_prompt", "traceback": traceback.format_exc()})
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return Response({
            "error": f"An error occurred: {str(e)}"
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_suggest_meal_alternatives(request):
    """
    API endpoint to suggest alternative meals for given meal plan entries.
    Accepts the same parameters as api_update_meals_with_prompt except for `prompt`.

    Request body:
    - meal_plan_meal_ids: List[int]
    - meal_dates: List[str] in YYYY-MM-DD format corresponding to each meal_plan_meal_id

    Response:
    {
      "alternatives": [
        {
          "meal_plan_meal_id": int,
          "day": str,
          "meal_type": str,
          "original_meal": { "id": int, "name": str },
          "alternatives": [
            { "meal_id": int, "name": str, "start_date": str, "is_available": bool, "chef": str, "meal_type": str },
            ...
          ]
        },
        ...
      ]
    }
    """
    logger.info("Starting api_suggest_meal_alternatives")
    try:
        meal_plan_meal_ids = request.data.get('meal_plan_meal_ids', [])
        meal_dates = request.data.get('meal_dates', [])
        logger.info(f"Received meal_plan_meal_ids: {meal_plan_meal_ids}, dates: {meal_dates}")

        if not meal_plan_meal_ids or not meal_dates:
            logger.warning("Missing required data: meal_plan_meal_ids or meal_dates")
            return Response({
                "error": "Both meal_plan_meal_ids and meal_dates are required."
            }, status=400)

        if len(meal_plan_meal_ids) != len(meal_dates):
            logger.warning("Mismatched lengths: meal_plan_meal_ids and meal_dates")
            return Response({
                "error": "Number of meal IDs must match number of dates."
            }, status=400)

        # Get current date in the user's timezone for comparisons
        user_tz = ZoneInfo(getattr(request.user, 'timezone', 'UTC') or 'UTC')
        today = timezone.now().astimezone(user_tz).date()
        logger.info(f"Current date (user tz {user_tz}): {today}")

        # Convert string dates to date objects and create ID-to-date mapping
        try:
            id_date_pairs = []
            past_date_pairs = []
            for meal_id, date_str in zip(meal_plan_meal_ids, meal_dates):
                meal_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                if meal_date < today:
                    logger.info(f"Skipping past date: {date_str} for meal_id: {meal_id}")
                    past_date_pairs.append((meal_id, meal_date))
                    continue
                id_date_pairs.append((meal_id, meal_date))
                logger.info(f"Added valid date pair: meal_id={meal_id}, date={date_str}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
            return Response({
                "error": "Invalid date format. Use YYYY-MM-DD."
            }, status=400)

        if not id_date_pairs:
            if 'past_date_pairs' in locals() and past_date_pairs:
                past_dates_str = [d.strftime('%Y-%m-%d') for _, d in past_date_pairs]
                logger.warning(f"All selected meals are in the past; cannot suggest alternatives. Past dates: {past_dates_str}")
                return Response({
                    "error": "Cannot suggest alternatives for past meals. Selected dates are in the past.",
                    "past_dates": past_dates_str
                }, status=400)
            logger.warning("No valid future dates found in request")
            return Response({
                "error": "No valid future dates provided."
            }, status=400)

        results = []

        # For each requested meal, validate ownership and day alignment, then fetch alternatives
        for meal_plan_meal_id, meal_date in id_date_pairs:
            try:
                meal_plan_meal = MealPlanMeal.objects.select_related('meal_plan', 'meal').get(
                    id=meal_plan_meal_id,
                    meal_plan__user=request.user
                )
            except MealPlanMeal.DoesNotExist:
                error_message = f"Meal plan meal with ID {meal_plan_meal_id} not found or unauthorized"
                logger.warning(error_message)
                return Response({
                    "error": error_message,
                    "details": {
                        "meal_plan_meal_id": meal_plan_meal_id,
                        "provided_date": meal_date.strftime("%Y-%m-%d")
                    }
                }, status=404)

            # Verify provided date corresponds to the stored day
            expected_day = meal_date.strftime("%A")
            if meal_plan_meal.day != expected_day:
                error_message = (
                    f"Day mismatch for MealPlanMeal ID {meal_plan_meal.id}: "
                    f"expected day '{expected_day}' (from provided date {meal_date}), "
                    f"but found day '{meal_plan_meal.day}' with meal type '{meal_plan_meal.meal_type}'."
                )
                logger.error(error_message)
                return Response({
                    "error": error_message,
                    "meal_plan_meal": {
                        "id": meal_plan_meal.id,
                        "name": meal_plan_meal.meal.name,
                        "day": meal_plan_meal.day,
                        "meal_type": meal_plan_meal.meal_type,
                        "provided_date": meal_date.strftime("%Y-%m-%d")
                    }
                }, status=400)

            # Fetch alternatives for this specific meal/day/type
            from shared.utils import suggest_alternative_meals
            alt_response = suggest_alternative_meals(
                request=request,
                meal_ids=[meal_plan_meal.meal.id],
                days_of_week=[meal_plan_meal.day],
                meal_types=[meal_plan_meal.meal_type]
            )

            if isinstance(alt_response, dict) and alt_response.get('status') == 'error':
                logger.error(f"Error from suggest_alternative_meals: {alt_response}")
                return Response({
                    "error": alt_response.get('message', 'Failed to suggest alternative meals')
                }, status=500)

            alternatives = alt_response.get('alternative_meals', [])

            results.append({
                "meal_plan_meal_id": meal_plan_meal.id,
                "day": meal_plan_meal.day,
                "meal_type": meal_plan_meal.meal_type,
                "original_meal": {
                    "id": meal_plan_meal.meal.id,
                    "name": meal_plan_meal.meal.name
                },
                "alternatives": alternatives
            })

        logger.info("Successfully generated alternative suggestions")
        return Response({
            "alternatives": results
        }, status=200)

    except Exception as e:
        logger.error(f"Error in api_suggest_meal_alternatives: {str(e)}")
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        try:
            requests.post(n8n_traceback_url, json={"error": f"Error in api_suggest_meal_alternatives: {str(e)}", "source":"api_suggest_meal_alternatives", "traceback": traceback.format_exc()})
        except Exception:
            pass
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return Response({
            "error": f"An error occurred: {str(e)}"
        }, status=500)


def get_user_dietary_preferences(user_id):
    """
    Get a user's dietary preferences with caching to improve performance.
    
    Parameters:
    - user_id: The ID of the user
    
    Returns:
    - A list of dietary preference names
    """
    cache_key = f"user_dietary_prefs_{user_id}"
    prefs = get(cache_key)
    
    if prefs is None:
        try:
            user = CustomUser.objects.get(id=user_id)
            regular_dietary_prefs = list(user.dietary_preferences.values_list('name', flat=True))
            custom_dietary_prefs = list(user.custom_dietary_preferences.values_list('name', flat=True))
            prefs = regular_dietary_prefs + custom_dietary_prefs        
            # Cache for 1 hour (3600 seconds)
            set(cache_key, prefs, 3600)
            logger.debug(f"Cached dietary preferences for user {user_id}")
        except Exception as e:
            logger.error(f"Error fetching dietary preferences for user {user_id}: {str(e)}")
            prefs = []
    
    return prefs

def get_available_meals_count(user_id):
    """
    Get the count of available meals for a user with caching to improve performance.
    
    Parameters:
    - user_id: The ID of the user
    
    Returns:
    - The count of available meals
    """
    cache_key = f"available_meals_count_{user_id}"
    count = get(cache_key)
    
    if count is None:
        try:
            count = Meal.objects.filter(creator_id=user_id).count()
            # Cache for 15 minutes (900 seconds) as this might change more frequently
            set(cache_key, count, 900)
        except Exception as e:
            # N8N traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            try:
                requests.post(n8n_traceback_url, json={"error": f"Error in get_available_meals_count: {str(e)}", "source":"get_available_meals_count", "traceback": traceback.format_exc()})
            except Exception:
                pass
            count = 0
    
    return count

def get_user_postal_code(user):
    """
    Get a user's postal code with caching to improve performance.
    
    Parameters:
    - user: The user object
    
    Returns:
    - The user's postal code or None if not available
    """
    cache_key = f"user_postal_code_{user.id}"
    postal_code = get(cache_key)
    
    if postal_code is None:
        try:
            if hasattr(user, 'address') and user.address:
                postal_code = user.address.normalized_postalcode
                # Cache for 1 day (86400 seconds) as this rarely changes
                set(cache_key, postal_code, 86400)
                logger.debug(f"Cached postal code for user {user.id}")
        except Exception as e:
            logger.error(f"Error fetching postal code for user {user.id}: {str(e)}")
            postal_code = None

    return postal_code

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_generate_meal_plan(request):
    """
    Start asynchronous meal plan generation for a specific week.
    Returns a task ID that can be used to check the status.
    """
    try:
        # Get week_start_date from request parameters
        week_start_date_str = request.data.get('week_start_date') or request.query_params.get('week_start_date')
        if not week_start_date_str:
            return Response({
                "status": "error",
                "message": "week_start_date parameter is required in YYYY-MM-DD format"
            }, status=400)

        # Basic date validation
        try:
            week_start_date = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
            week_end_date = week_start_date + timedelta(days=6)
        except ValueError:
            return Response({
                "status": "error",
                "message": "Invalid date format. Please use YYYY-MM-DD"
            }, status=400)

        # Check if the date is in the past
        today = timezone.now().date()
        if week_end_date < today:
            return Response({
                "status": "error",
                "message": "Cannot generate meal plans for past weeks",
                "details": {
                    "current_date": today.strftime('%Y-%m-%d'),
                    "provided_date": week_start_date.strftime('%Y-%m-%d')
                }
            }, status=400)

        # Quick check for existing meal plan to avoid unnecessary task creation
        existing_plan = MealPlan.objects.filter(
            user=request.user,
            week_start_date=week_start_date,
            week_end_date=week_end_date
        ).first()

        if existing_plan:
            meal_count = MealPlanMeal.objects.filter(meal_plan=existing_plan).count()
            if meal_count > 0:
                status_message = "approved" if existing_plan.is_approved else "ready"
                return Response({
                    "status": "existing_plan",
                    "message": f"A meal plan already exists for this week ({status_message})",
                    "details": {
                        "meal_plan_id": existing_plan.id,
                        "is_approved": existing_plan.is_approved,
                        "has_changes": existing_plan.has_changes,
                        "meal_count": meal_count,
                        "week_start_date": existing_plan.week_start_date.strftime('%Y-%m-%d'),
                        "week_end_date": existing_plan.week_end_date.strftime('%Y-%m-%d')
                    },
                    "meal_plan": {
                        "id": existing_plan.id,
                        "week_start_date": existing_plan.week_start_date.strftime('%Y-%m-%d'),
                        "week_end_date": existing_plan.week_end_date.strftime('%Y-%m-%d'),
                        "is_approved": existing_plan.is_approved
                    }
                })

        # Generate deterministic task ID to prevent duplicate tasks
        task_id = f"meal_plan_generation_{request.user.id}_{week_start_date.strftime('%Y_%m_%d')}"
        
        # Use Redis marker key to prevent duplicate requests for this user/week combination
        lock_key = f"meal_plan_generation_lock_{request.user.id}_{week_start_date.strftime('%Y_%m_%d')}"
        lock_duration = 300  # 5 minutes lock duration
        
        # Check if a generation is already in progress for this user/week
        from utils.redis_client import get, set, delete
        existing_lock = get(lock_key)
        if existing_lock:
            logger.info(f"Meal plan generation already in progress for user {request.user.username}, week {week_start_date}")
            return Response({
                "status": "processing", 
                "message": "Meal plan generation already in progress for this week",
                "task_id": existing_lock if isinstance(existing_lock, str) else task_id,
                "polling_url": f"/meals/api/meal_plan_status/{existing_lock if isinstance(existing_lock, str) else task_id}",
                "estimated_time": "30-60 seconds"
            }, status=202)
        
        # Set the lock with the task ID and expiration
        set(lock_key, task_id, lock_duration)
        
        # Start the async task using existing meal plan service with custom task ID
        from .meal_plan_service import create_meal_plan_for_user
        
        try:
            # Execute meal plan creation directly
            result = create_meal_plan_for_user(
                user_id=request.user.id,
                start_of_week=week_start_date,
                end_of_week=week_end_date,
                request_id=str(uuid.uuid4()),
                user_prompt=request.data.get('user_prompt') if request.data else None
            )
        except Exception as e:
            # Clean up the lock if task fails
            delete(lock_key)
            # Log error
            logger.exception(f"Error in api_generate_meal_plan: {str(e)}")
            

        logger.info(f"Started meal plan generation task {task.id} for user {request.user.username}")

        return Response({
            "status": "processing",
            "message": "Meal plan generation started",
            "task_id": task.id,
            "polling_url": f"/meals/api/meal_plan_status/{task.id}",
            "estimated_time": "30-60 seconds"
        }, status=202)  # 202 Accepted

    except Exception as e:
        # Clean up the lock if any error occurs
        try:
            from utils.redis_client import delete
            lock_key = f"meal_plan_generation_lock_{request.user.id}_{week_start_date.strftime('%Y_%m_%d')}"
            delete(lock_key)
            logger.info(f"Cleaned up Redis lock {lock_key} due to error: {str(e)}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup lock during error handling: {str(cleanup_error)}")
        
        logger.error(f"Error starting meal plan generation: {str(e)}")
        traceback.print_exc()
        return Response({
            "status": "error",
            "message": "Failed to start meal plan generation",
            "details": str(e)
                 }, status=500)

from rest_framework.decorators import renderer_classes
from rest_framework.renderers import BaseRenderer

class EventStreamRenderer(BaseRenderer):
    media_type = 'text/event-stream'
    format = 'event-stream'
    charset = None
    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, str):
            return data.encode('utf-8')
        try:
            import json as _json
            return (_json.dumps(data) + "\n").encode('utf-8')
        except Exception:
            return str(data).encode('utf-8')

@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
@renderer_classes([EventStreamRenderer])
# @deprecated Legacy meal-plan SSE endpoint guarded by LEGACY_MEAL_PLAN.
def api_stream_meal_plan_generation(request):
    """
    SSE endpoint to stream meal plan generation events for a given week.
    Emits:
      - event: meal_added, data: { meal_plan_meal }
      - event: progress, data: { pct }
      - event: done
    If no job is running, starts an idempotent generation job and streams results.
    """
    import json
    import uuid
    from datetime import datetime, timedelta
    from django.utils import timezone
    from django.http import StreamingHttpResponse
    from utils.redis_client import get as redis_get, set as redis_set, delete as redis_delete, get_redis_connection
    from .models import MealPlan, MealPlanMeal
    
    try:
        # Troubleshooting headers
        try:
            accept = request.META.get('HTTP_ACCEPT')
            
        except Exception:
            pass

        # Support both DRF Request and plain Django HttpRequest
        week_start_date_str = None
        if hasattr(request, 'query_params') and request.query_params is not None:
            week_start_date_str = request.query_params.get('week_start_date')
        if not week_start_date_str and hasattr(request, 'GET'):
            week_start_date_str = request.GET.get('week_start_date')
        if not week_start_date_str:
            def err_stream():
                yield f"event: error\n"
                yield f"data: {json.dumps({'message': 'week_start_date is required (YYYY-MM-DD)'})}\n\n"
                yield 'event: close\n\n'
            response = StreamingHttpResponse(err_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            return response
        try:
            week_start_date = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
            week_end_date = week_start_date + timedelta(days=6)
        except ValueError:
            def err_stream2():
                yield f"event: error\n"
                yield f"data: {json.dumps({'message': 'Invalid date format. Use YYYY-MM-DD'})}\n\n"
                yield 'event: close\n\n'
            response = StreamingHttpResponse(err_stream2(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            return response

        # Channel and keys
        user_id = request.user.id
        channel = f"meal_plan_stream:{user_id}:{week_start_date.strftime('%Y_%m_%d')}"
        lock_key = f"meal_plan_generation_lock_{user_id}_{week_start_date.strftime('%Y_%m_%d')}"
        job_key = f"meal_plan_job:{user_id}:{week_start_date.strftime('%Y_%m_%d')}"

        # If plan already exists with meals, short-circuit and emit done
        existing_plan = MealPlan.objects.filter(
            user=request.user,
            week_start_date=week_start_date,
            week_end_date=week_end_date
        ).first()
        if existing_plan and MealPlanMeal.objects.filter(meal_plan=existing_plan).exists():
            def done_stream():
                yield "event: progress\n"
                yield f"data: {json.dumps({'pct': 100})}\n\n"
                yield "event: done\n\n"
            response = StreamingHttpResponse(done_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            response['X-Accel-Buffering'] = 'no'
            return response

        # Prepare Redis pubsub
        conn = get_redis_connection()
        if conn is None:
            def err_stream3():
                yield f"event: error\n"
                yield f"data: {json.dumps({'message': 'Redis unavailable for SSE'})}\n\n"
                yield 'event: close\n\n'
            response = StreamingHttpResponse(err_stream3(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            return response
        pubsub = conn.pubsub()
        pubsub.subscribe(channel)
        

        # Start job idempotently if not already running
        lock_val = redis_get(lock_key)
        if not lock_val:
            try:
                # set lock to avoid races
                lock_value_to_set = f"meal_plan_generation_{user_id}_{week_start_date.strftime('%Y_%m_%d')}"
                redis_set(lock_key, lock_value_to_set, 7200)
                from .meal_plan_service import create_meal_plan_for_user
                create_meal_plan_for_user(
                    user_id=user_id,
                    start_of_week=week_start_date,
                    end_of_week=week_start_date + timedelta(days=6),
                    request_id=str(uuid.uuid4()),
                    user_prompt=request.query_params.get('user_prompt') if hasattr(request, 'query_params') else None
                )
            except Exception:
                # Best effort cleanup of lock
                try:
                    redis_delete(lock_key)
                except Exception:
                    pass
                raise
        else:
            logger.info(f"[SSE] Job already running with lock value: {lock_val}")

        def event_stream():
            try:
                # Immediate heartbeat to open the stream promptly
                yield ":keepalive\n\n"
                # Optional initial progress snapshot if available
                job_info = redis_get(job_key)
                if isinstance(job_info, dict) and 'total' in job_info and 'added' in job_info:
                    total = max(job_info.get('total', 0), 1)
                    pct = int((job_info.get('added', 0) / total) * 100)
                    yield "event: progress\n"
                    yield f"data: {json.dumps({'pct': pct})}\n\n"

                # Switch to non-blocking poll with periodic keepalive
                last_heartbeat = time.time()
                while True:
                    message = pubsub.get_message(timeout=1.0)
                    now_ts = time.time()
                    if message and message.get('type') == 'message':
                        try:
                            payload = json.loads(message.get('data'))
                        except Exception:
                            payload = None
                        if not isinstance(payload, dict):
                            continue
                        event = payload.get('event') or payload.get('type')  # support alternate naming
                        data = payload.get('data') if 'data' in payload else payload
                        if not event:
                            continue
                        yield f"event: {event}\n"
                        if data is None:
                            yield "data: {}\n\n"
                        else:
                            yield f"data: {json.dumps(data)}\n\n"
                        if event == 'progress':
                            try:
                                pct_val = data.get('pct') if isinstance(data, dict) else None
                            except Exception:
                                pct_val = None
                        else:
                            logger.info(f"[SSE] Emitted event={event}", flush=True)
                        if event == 'done':
                            logger.info("[SSE] Received done event; breaking stream loop", flush=True)
                            break
                        last_heartbeat = now_ts
                    else:
                        if now_ts - last_heartbeat >= 20:
                            yield ":keepalive\n\n"
                            last_heartbeat = now_ts
            except GeneratorExit:
                #n8n traceback
                n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
                requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_stream_meal_plan_generation", "traceback": traceback.format_exc()})
            finally:
                try:
                    pubsub.unsubscribe(channel)
                except Exception:
                    #n8n traceback
                    n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
                    requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_stream_meal_plan_generation", "traceback": traceback.format_exc()})
            yield 'event: close\n\n'

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache, no-transform'
        response['X-Accel-Buffering'] = 'no'
        return response

    except Exception as e:
        logger.error(f"Error in api_stream_meal_plan_generation: {str(e)}")
        #n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_stream_meal_plan_generation", "traceback": traceback.format_exc()})
        def err_stream4():
            yield f"event: error\n"
            yield f"data: {json.dumps({'message': str(e)})}\n\n"
            yield 'event: done\n\n'
            yield 'event: close\n\n'
        response = StreamingHttpResponse(err_stream4(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache, no-transform'
        response['X-Accel-Buffering'] = 'no'
        return response

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_cleanup_meal_plan_locks(request):
    """
    Manual cleanup endpoint for meal plan generation locks.
    Useful for debugging or maintenance.
    
    POST data:
    - user_id (optional): Clean locks for specific user, defaults to current user
    - max_age_hours (optional): Remove locks older than this, defaults to 6 hours
    """
    try:
        # Only allow users to clean their own locks, unless they're staff
        target_user_id = request.data.get('user_id', request.user.id)
        if target_user_id != request.user.id and not request.user.is_staff:
            return Response({
                "status": "error",
                "message": "You can only clean up your own locks"
            }, status=403)
        
        max_age_hours = int(request.data.get('max_age_hours', 6))
        if max_age_hours < 1 or max_age_hours > 168:  # 1 hour to 1 week
            return Response({
                "status": "error",
                "message": "max_age_hours must be between 1 and 168 (1 week)"
            }, status=400)
        
        # Perform cleanup
        results = cleanup_expired_meal_plan_locks(
            user_id=target_user_id,
            max_age_hours=max_age_hours
        )
        
        return Response({
            "status": "success",
            "message": "Lock cleanup completed",
            "results": results
        })
        
    except ValueError as e:
        return Response({
            "status": "error",
            "message": f"Invalid input: {str(e)}"
        }, status=400)
    except Exception as e:
        #n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_cleanup_meal_plan_locks", "traceback": traceback.format_exc()})
        logger.error(f"Error in manual lock cleanup: {str(e)}")
        return Response({
            "status": "error",
            "message": "Failed to cleanup locks"
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_meal_plan_status(request, task_id):
    """
    Check the status of a meal plan generation task.
    Also handles cleanup of expired locks.
    """
    try:
        from utils.redis_client import get, delete
        from celery.result import AsyncResult
        
        # Get task result from Redis first (more detailed)
        task_result = get(f"meal_plan_task_{task_id}")
        
        if task_result:
            # If we have a result, the task is complete, so clean up any locks
            _cleanup_meal_plan_locks_for_task(task_id, request.user.id)
            return Response(task_result)
        
        # Fallback to Celery task state
        task = AsyncResult(task_id)
        
        if task.state == 'PENDING':
            # Check if this is a real pending task or a stale lock
            lock_exists = _check_and_cleanup_stale_locks(task_id, request.user.id)
            if not lock_exists:
                return Response({
                    "status": "error",
                    "message": "Task not found or expired. Please try generating again.",
                    "code": "TASK_EXPIRED"
                }, status=404)
            
            return Response({
                "status": "processing",
                "message": "Task is queued or starting...",
                "progress": 5
            })
        elif task.state == 'SUCCESS':
            # Clean up locks on successful completion
            _cleanup_meal_plan_locks_for_task(task_id, request.user.id)
            return Response(task.result or {
                "status": "success",
                "message": "Task completed successfully"
            })
        elif task.state == 'FAILURE':
            # Clean up locks on failure
            _cleanup_meal_plan_locks_for_task(task_id, request.user.id)
            return Response({
                "status": "error",
                "message": "Task failed",
                "details": str(task.info)
            }, status=500)
        else:
            return Response({
                "status": "processing",
                "message": f"Task is {task.state.lower()}",
                "progress": 50
            })
    
    except Exception as e:
        #n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_meal_plan_status", "traceback": traceback.format_exc()})
        logger.error(f"Error checking task status {task_id}: {str(e)}")
        return Response({
            "status": "error",
            "message": "Failed to check task status"
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_user_profile(request):
    """
    API endpoint to retrieve the authenticated user's profile information
    including properly serialized dietary preferences.
    """
    if request.method == 'GET':
        # Serialize the current user with the UserSerializer
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_meal_by_id(request, meal_id):
    """
    API endpoint to retrieve details for a specific meal,
    including properly serialized dietary preferences.
    
    Security: 
    - Chefs can only view their own meals
    - Admin users can view any meal
    - Regular users can only view public meals
    """
    try:
        user = request.user
        meal = get_object_or_404(Meal, id=meal_id)
        
        # Security check: restrict access based on user role
        if user.is_staff:
            # Admin can view any meal
            pass
        elif hasattr(user, 'chef') and meal.chef == user.chef:
            # Chef can view their own meals
            pass
        else:
            # Regular users can only see public meals
            if not getattr(meal, 'is_public', True):  # Default to True if is_public field doesn't exist
                return Response(
                    {"error": "You don't have permission to view this meal"}, 
                    status=403
                )
        
        serializer = MealSerializer(meal)
        return Response(serializer.data, status=200)
    except Exception as e:
        logger.error(f"Error fetching meal details: {str(e)}")
        return Response({"error": str(e)}, status=500)

# Chef Meal Event Views
@login_required
def chef_meal_dashboard(request):
    """Dashboard for chefs to manage their meal events"""
    logger.info(f"Chef meal dashboard accessed by user {request.user.id}")
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} tried to access chef dashboard but does not have a chef profile")
        messages.error(request, "You do not have a chef profile.")
        return redirect('home')
    
    # Get all chef's meal events
    upcoming_events = ChefMealEvent.objects.filter(
        chef=chef,
        event_date__gte=timezone.now().date()
    ).order_by('event_date', 'event_time')
    
    past_events = ChefMealEvent.objects.filter(
        chef=chef,
        event_date__lt=timezone.now().date()
    ).order_by('-event_date', '-event_time')[:10]  # Show only 10 past events
    
    logger.debug(f"Chef dashboard loaded for chef {chef.id}: {upcoming_events.count()} upcoming events, {past_events.count()} recent past events")
    context = {
        'chef': chef,
        'upcoming_events': upcoming_events,
        'past_events': past_events,
    }
    return render(request, 'meals/chef_meal_dashboard.html', context)

@login_required
def create_chef_meal_event(request):
    """Create a new meal event as a chef"""
    logger.info(f"Create chef meal event page accessed by user {request.user.id}")
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} tried to create meal event but does not have a chef profile")
        messages.error(request, "You do not have a chef profile.")
        return redirect('home')
    
    # Get meals that belong to this chef
    chef_meals = Meal.objects.filter(chef=chef)
    logger.debug(f"Found {chef_meals.count()} meals for chef {chef.id}")
    
    # Get chef's timezone for context/validation
    chef_timezone = chef.user.timezone if hasattr(chef.user, 'timezone') else 'UTC'
    try:
        chef_tz = ZoneInfo(chef_timezone)
    except Exception:
        chef_tz = ZoneInfo("UTC")
    
    if request.method == 'POST':
        # Get form data
        meal_id = request.POST.get('meal')
        event_date = request.POST.get('event_date')
        event_time = request.POST.get('event_time')
        cutoff_time = request.POST.get('order_cutoff_time')
        base_price = request.POST.get('base_price')
        min_price = request.POST.get('min_price')
        max_orders = request.POST.get('max_orders')
        min_orders = request.POST.get('min_orders')
        description = request.POST.get('description')
        special_instructions = request.POST.get('special_instructions')
        
        logger.debug(f"Attempting to create meal event: meal_id={meal_id}, date={event_date}, time={event_time}, max_orders={max_orders}")
        try:
            # Validate form data
            meal = Meal.objects.get(id=meal_id, chef=chef)
            
            # Convert cutoff time string to datetime and make it timezone-aware
            cutoff_datetime = datetime.strptime(
                f"{event_date} {cutoff_time}", 
                "%Y-%m-%d %H:%M"
            )
            
            # Assume cutoff time is in chef's timezone, make aware and convert to UTC for storage
            cutoff_datetime = timezone.make_aware(cutoff_datetime, chef_tz)
            cutoff_datetime_utc = cutoff_datetime.astimezone(py_tz.utc)
            
            # Check if the event_date/time is in the future in chef's timezone
            event_datetime = datetime.strptime(
                f"{event_date} {event_time}", 
                "%Y-%m-%d %H:%M"
            )
            event_datetime = timezone.make_aware(event_datetime, chef_tz)
            
            # Get current time in chef's timezone
            now = timezone.now().astimezone(chef_tz)
            
            if event_datetime <= now:
                messages.error(request, f"Event date and time must be in the future in your local timezone ({chef_timezone}).")
                context = {
                    'chef': chef,
                    'chef_meals': chef_meals,
                    'chef_timezone': chef_timezone,
                }
                return render(request, 'meals/create_chef_meal_event.html', context)
                
            if cutoff_datetime >= event_datetime:
                messages.error(request, "Order cutoff time must be before the event time.")
                context = {
                    'chef': chef,
                    'chef_meals': chef_meals,
                    'chef_timezone': chef_timezone,
                }
                return render(request, 'meals/create_chef_meal_event.html', context)
            
            # Create the ChefMealEvent
            event = ChefMealEvent.objects.create(
                chef=chef,
                meal=meal,
                event_date=event_date,
                event_time=event_time,
                order_cutoff_time=cutoff_datetime_utc,  # Store in UTC timezone
                base_price=base_price,
                current_price=base_price,  # Initially same as base price
                min_price=min_price,
                max_orders=max_orders,
                min_orders=min_orders,
                description=description,
                special_instructions=special_instructions,
                status='scheduled'
            )
            
            messages.success(request, f"Meal event '{meal.name}' scheduled successfully for {event_date} in your local timezone ({chef_timezone}).")
            return redirect('chef_meal_dashboard')
            
        except (Meal.DoesNotExist, ValueError) as e:
            messages.error(request, f"Error creating meal event: {str(e)}")
    
    context = {
        'chef': chef,
        'chef_meals': chef_meals,
        'chef_timezone': chef_timezone,  # Add timezone to context
    }
    return render(request, 'meals/create_chef_meal_event.html', context)

@login_required
def edit_chef_meal_event(request, event_id):
    logger.info(f"Edit chef meal event page accessed by user {request.user.id} for event {event_id}")
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} tried to edit meal event but does not have a chef profile")
        messages.error(request, "You do not have a chef profile.")
        return redirect('home')
    
    event = get_object_or_404(ChefMealEvent, id=event_id, chef=chef)
    
    # Get chef's timezone for context/validation
    chef_timezone = chef.user.timezone if hasattr(chef.user, 'timezone') else 'UTC'
    try:
        chef_tz = ZoneInfo(chef_timezone)
    except Exception:
        chef_tz = ZoneInfo("UTC")
    
    # Check if event can be edited (not too close to event date or has orders)
    now = timezone.now().astimezone(chef_tz)
    
    # Convert event_datetime to chef's timezone for comparison
    event_datetime = event.get_event_datetime()
    if event_datetime:
        # Check if the event is within 24 hours
        if now + timezone.timedelta(hours=24) >= event_datetime:
            messages.error(request, f"This event is too close to its scheduled date and cannot be edited (within 24 hours in your timezone: {chef_timezone}).")
            return redirect('chef_meal_dashboard')
    
    if event.orders_count > 0:
        messages.warning(request, "This event has orders. Some fields cannot be modified.")
    
    if request.method == 'POST':
        # Get form data
        event_date = request.POST.get('event_date')
        event_time = request.POST.get('event_time')
        cutoff_time = request.POST.get('order_cutoff_time')
        description = request.POST.get('description')
        special_instructions = request.POST.get('special_instructions')
        
        # Fields that can only be edited if no orders exist
        if event.orders_count == 0:
            base_price = request.POST.get('base_price')
            min_price = request.POST.get('min_price')
            max_orders = request.POST.get('max_orders')
            min_orders = request.POST.get('min_orders')
            
            event.base_price = base_price
            event.min_price = min_price
            event.max_orders = max_orders
            event.min_orders = min_orders
            
            # If price is changing, update current price too
            if float(base_price) != float(event.base_price):
                event.current_price = base_price
        
        try:
            # Convert cutoff time string to datetime in chef's timezone
            cutoff_datetime = datetime.strptime(
                f"{event_date} {cutoff_time}", 
                "%Y-%m-%d %H:%M"
            )
            
            # Make aware in chef's timezone and convert to UTC for storage
            cutoff_datetime = timezone.make_aware(cutoff_datetime, chef_tz)
            cutoff_datetime_utc = cutoff_datetime.astimezone(py_tz.utc)
            
            # Create event datetime in chef's timezone
            event_datetime = datetime.strptime(
                f"{event_date} {event_time}", 
                "%Y-%m-%d %H:%M"
            )
            event_datetime = timezone.make_aware(event_datetime, chef_tz)
            
            # Validate cutoff is before event time
            if cutoff_datetime >= event_datetime:
                messages.error(request, "Order cutoff time must be before the event time.")
                context = {
                    'chef': chef,
                    'event': event,
                    'has_orders': event.orders_count > 0,
                    'chef_timezone': chef_timezone,
                }
                return render(request, 'meals/edit_chef_meal_event.html', context)
            
            # Update the event
            event.event_date = event_date
            event.event_time = event_time
            event.order_cutoff_time = cutoff_datetime_utc
            event.description = description
            event.special_instructions = special_instructions
            event.save()
            
            messages.success(request, f"Meal event updated successfully in your local timezone ({chef_timezone}).")
            return redirect('chef_meal_dashboard')
        except ValueError as e:
            messages.error(request, f"Error updating meal event: {str(e)}")
    
    # Pre-populate the form
    context = {
        'chef': chef,
        'event': event,
        'has_orders': event.orders_count > 0,
        'chef_timezone': chef_timezone,
    }
    return render(request, 'meals/edit_chef_meal_event.html', context)

@login_required
def cancel_chef_meal_event(request, event_id):
    logger.info(f"Cancel chef meal event page accessed by user {request.user.id} for event {event_id}")
    
    # Verify the user is the chef who created this event
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        messages.error(request, "You must be a chef to cancel events.")
        return redirect('chef_meal_dashboard')
    
    # Get the event
    try:
        event = ChefMealEvent.objects.get(id=event_id, chef=chef)
    except ChefMealEvent.DoesNotExist:
        messages.error(request, "Event not found or you don't have permission to cancel it.")
        return redirect('chef_meal_dashboard')
    
    # Process cancellation
    if request.method == 'POST':
        reason = request.POST.get('cancellation_reason', '')
        
        # Cancel the event
        event.status = STATUS_CANCELLED
        event.save()
        
        # Cancel all orders and prepare for refunds
        orders = ChefMealOrder.objects.filter(meal_event=event, status__in=[STATUS_PLACED, STATUS_CONFIRMED])
        
        # For now, just mark orders as cancelled
        # In a real implementation, we would trigger Stripe refunds here
        orders.update(status=STATUS_CANCELLED)
        
        # Create payment logs for all cancelled orders
        for order in orders:
            PaymentLog.objects.create(
                chef_meal_order=order,
                user=order.customer,
                chef=chef,
                action='refund',
                amount=order.price_paid * order.quantity,
                status='pending',
                details={'reason': reason or 'Chef cancelled event'}
            )
        
        messages.success(request, f"Meal event cancelled successfully. {orders.count()} orders have been cancelled.")
        return redirect('chef_meal_dashboard')
    
    context = {
        'event': event,
        'orders_count': event.orders_count,
    }
    return render(request, 'meals/cancel_chef_meal_event.html', context)

@login_required
def browse_chef_meals(request):
    """Browse available chef meal events"""
    # Get the user's location/postal code to filter by service area
    user_address = getattr(request.user, 'address', None)

    # Get all upcoming meal events
    now = timezone.now()
    upcoming_events = ChefMealEvent.objects.filter(
        event_date__gte=now.date(),
        status__in=['scheduled', 'open'],
        order_cutoff_time__gt=now
    ).select_related('chef', 'meal').order_by('event_date', 'event_time')

    # Filter by postal code if the user has an address
    if user_address and user_address.normalized_postalcode:
        # Get all chefs serving this postal code
        postal_code_obj = PostalCode.objects.filter(code=user_address.normalized_postalcode).first()
        if postal_code_obj:
            chef_ids = ChefPostalCode.objects.filter(
                postal_code=postal_code_obj
            ).values_list('chef_id', flat=True)
            
            upcoming_events = upcoming_events.filter(chef_id__in=chef_ids)
    
    # Group by date for display
    events_by_date = {}
    for event in upcoming_events:
        date_str = event.event_date.strftime('%Y-%m-%d')
        if date_str not in events_by_date:
            events_by_date[date_str] = []
        events_by_date[date_str].append(event)
    
    context = {
        'events_by_date': events_by_date,
        'user_address': user_address,
    }
    return render(request, 'meals/browse_chef_meals.html', context)

@login_required
def chef_meal_detail(request, event_id):
    """View details for a specific chef meal event"""
    try:
        event = ChefMealEvent.objects.select_related('chef', 'meal').get(id=event_id)
    except ChefMealEvent.DoesNotExist:
        messages.error(request, "Meal event not found.")
        return redirect('browse_chef_meals')
    
    # Check if user is in chef's service area
    user_can_order = True
    user_address = getattr(request.user, 'address', None)

    if user_address and user_address.normalized_postalcode:
        postal_code_obj = PostalCode.objects.filter(code=user_address.normalized_postalcode).first()
        if postal_code_obj:
            chef_serves_area = ChefPostalCode.objects.filter(
                chef=event.chef,
                postal_code=postal_code_obj
            ).exists()

            user_can_order = chef_serves_area

    # Check if user already has an order for this event
    user_order = None
    if request.user.is_authenticated:
        user_order = ChefMealOrder.objects.filter(
            customer=request.user,
            meal_event=event
        ).first()
    
    # Get chef's other upcoming events
    other_events = ChefMealEvent.objects.filter(
        chef=event.chef,
        event_date__gte=timezone.now().date(),
        status__in=['scheduled', 'open']
    ).exclude(id=event.id).order_by('event_date', 'event_time')[:5]
    
    context = {
        'event': event,
        'user_can_order': user_can_order and event.is_available_for_orders(),
        'user_address': user_address,
        'user_order': user_order,
        'other_events': other_events,
    }
    return render(request, 'meals/chef_meal_detail.html', context)

@login_required
def place_chef_meal_order(request, event_id):
    """Place an order for a chef meal event"""
    try:
        event = ChefMealEvent.objects.select_related('chef', 'meal').get(id=event_id)
    except ChefMealEvent.DoesNotExist:
        messages.error(request, "Meal event not found.")
        return redirect('browse_chef_meals')
    
    # Check if the event is available for orders
    if not event.is_available_for_orders():
        messages.error(request, "This meal is no longer available for orders.")
        return redirect('chef_meal_detail', event_id=event.id)
    
    # Check if user is in chef's service area
    user_address = getattr(request.user, 'address', None)

    if user_address and user_address.normalized_postalcode:
        postal_code_obj = PostalCode.objects.filter(code=user_address.normalized_postalcode).first()
        if postal_code_obj:
            chef_serves_area = ChefPostalCode.objects.filter(
                chef=event.chef,
                postal_code=postal_code_obj
            ).exists()

            if not chef_serves_area:
                messages.error(request, "This chef does not deliver to your area.")
                return redirect('chef_meal_detail', event_id=event.id)
    
    # Handle form submission
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        special_requests = request.POST.get('special_requests', '')
        
        # Create/get the main order
        order, created = Order.objects.get_or_create(
            customer=request.user,
            status='Placed',
            is_paid=False,
            defaults={
                'address': user_address,
                'delivery_method': 'Delivery' if user_address else 'Pickup',
            }
        )
        
        # Create the chef meal order
        chef_meal_order = ChefMealOrder.objects.create(
            order=order,
            meal_event=event,
            customer=request.user,
            quantity=quantity,
            price_paid=event.current_price,
            special_requests=special_requests,
            status='placed'
        )
        
        # Here, we would typically redirect to a payment page
        # For now, just redirect to the order confirmation
        messages.success(request, f"Your order for {event.meal.name} has been placed. Please complete payment.")
        return redirect('view_chef_meal_order', order_id=chef_meal_order.id)
    
    context = {
        'event': event,
        'user_address': user_address,
    }
    return render(request, 'meals/place_chef_meal_order.html', context)

@login_required
def view_chef_meal_order(request, order_id):
    """View a specific chef meal order"""
    try:
        order = ChefMealOrder.objects.select_related('meal_event', 'meal_event__chef', 'meal_event__meal').get(
            id=order_id,
            customer=request.user
        )
    except ChefMealOrder.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect('user_orders')
    
    context = {
        'order': order,
        'event': order.meal_event,
    }
    return render(request, 'meals/view_chef_meal_order.html', context)

@login_required
def user_chef_meal_orders(request):
    """View all chef meal orders for a user"""
    # Get upcoming and past orders
    upcoming_orders = ChefMealOrder.objects.filter(
        customer=request.user,
        meal_event__event_date__gte=timezone.now().date(),
        status__in=['placed', 'confirmed']
    ).select_related('meal_event', 'meal_event__meal', 'meal_event__chef').order_by('meal_event__event_date', 'meal_event__event_time')
    
    past_orders = ChefMealOrder.objects.filter(
        customer=request.user,
        meal_event__event_date__lt=timezone.now().date()
    ).select_related('meal_event', 'meal_event__meal', 'meal_event__chef').order_by('-meal_event__event_date', '-meal_event__event_time')
    
    # Get cancelled orders
    cancelled_orders = ChefMealOrder.objects.filter(
        customer=request.user,
        status__in=['cancelled', 'refunded']
    ).select_related('meal_event', 'meal_event__meal', 'meal_event__chef').order_by('-created_at')
    
    context = {
        'upcoming_orders': upcoming_orders,
        'past_orders': past_orders,
        'cancelled_orders': cancelled_orders,
    }
    return render(request, 'meals/user_chef_meal_orders.html', context)

@login_required
def cancel_chef_meal_order(request, order_id):
    """Cancel a chef meal order"""
    try:
        order = ChefMealOrder.objects.select_related('meal_event').get(
            id=order_id,
            customer=request.user
        )
    except ChefMealOrder.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect('user_chef_meal_orders')
    
    # Check if order can be cancelled
    now = timezone.now()
    cutoff = timezone.datetime.combine(order.meal_event.event_date, order.meal_event.event_time, tzinfo=timezone.get_current_timezone()) - timezone.timedelta(hours=24)
    
    if now > cutoff:
        messages.error(request, "This order is too close to its scheduled date and cannot be cancelled.")
        return redirect('user_chef_meal_orders')
    
    if order.status not in [STATUS_PLACED, STATUS_CONFIRMED]:
        messages.error(request, "This order cannot be cancelled.")
        return redirect('user_chef_meal_orders')
    
    if request.method == 'POST':
        reason = request.POST.get('cancellation_reason', '')
        
        # Process cancellation
        success = order.cancel()
        
        if success:
            # Create payment log for refund
            PaymentLog.objects.create(
                chef_meal_order=order,
                user=request.user,
                chef=order.meal_event.chef,
                action='refund',
                amount=order.price_paid * order.quantity,
                status='pending',
                details={
                    'cancellation_reason': reason,
                    'cancelled_by': 'customer',
                    'order_id': order.id
                }
            )
            
            messages.success(request, "Your order has been cancelled. If you made a payment, you will receive a refund.")
        else:
            messages.error(request, "Could not cancel your order.")
        
        return redirect('user_chef_meal_orders')
    
    context = {
        'order': order,
        'event': order.meal_event,
    }
    return render(request, 'meals/cancel_chef_meal_order.html', context)

@login_required
def review_chef_meal(request, order_id):
    """Leave a review for a completed chef meal"""
    try:
        order = ChefMealOrder.objects.select_related('meal_event', 'meal_event__chef', 'meal_event__meal').get(
            id=order_id,
            customer=request.user,
            status='completed'
        )
    except ChefMealOrder.DoesNotExist:
        messages.error(request, "Order not found or not eligible for review.")
        return redirect('user_chef_meal_orders')
    
    # Check if review already exists
    existing_review = ChefMealReview.objects.filter(chef_meal_order=order).first()
    
    if existing_review:
        messages.info(request, "You have already reviewed this meal.")
        return redirect('user_chef_meal_orders')
    
    if request.method == 'POST':
        rating = int(request.POST.get('rating', 5))
        comment = request.POST.get('comment', '')
        
        # Create the review
        review = ChefMealReview.objects.create(
            chef_meal_order=order,
            customer=request.user,
            chef=order.meal_event.chef,
            meal_event=order.meal_event,
            rating=rating,
            comment=comment
        )
        
        messages.success(request, "Thank you for your review!")
        return redirect('user_chef_meal_orders')
    
    context = {
        'order': order,
        'event': order.meal_event,
    }
    return render(request, 'meals/review_chef_meal.html', context)

# API Endpoints for Chef Meal functionality


class ChefMealEventViewSet(viewsets.ModelViewSet):
    pagination_class = ChefMealEventPagination
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        # Filter by chef if we're looking at chef's own events
        if self.action in ['list', 'retrieve'] and self.request.query_params.get('my_events') == 'true':
            try:
                chef = Chef.objects.get(user=user)
                return ChefMealEvent.objects.filter(chef=chef).order_by('event_date', 'event_time')
            except Chef.DoesNotExist:
                return ChefMealEvent.objects.none()
                
        # Filter by postal code if provided
        postal_code = self.request.query_params.get('postal_code')
        if postal_code:
            # Find all chefs that serve this postal code
            chef_ids = ChefPostalCode.objects.filter(
                postal_code__code=postal_code
            ).values_list('chef_id', flat=True)
            
            # Filter events by these chefs and availability
            now = timezone.now()
            return ChefMealEvent.objects.filter(
                chef_id__in=chef_ids,
                status__in=['scheduled', 'open'],
                order_cutoff_time__gt=now,
                orders_count__lt=F('max_orders')
            ).order_by('event_date', 'event_time')
        
        # Default: show available events
        now = timezone.now()
        return ChefMealEvent.objects.filter(
            status__in=['scheduled', 'open'],
            order_cutoff_time__gt=now,
            orders_count__lt=F('max_orders')
        ).order_by('event_date', 'event_time')
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ChefMealEventCreateSerializer
        return ChefMealEventSerializer
    
    def perform_create(self, serializer):
        try:
            chef = Chef.objects.get(user=self.request.user)
        except Chef.DoesNotExist:
            return Response(
                {"error": "You must be a registered chef to create meal events"},
                status=403
            )
        
        serializer.save(chef=chef)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        event = self.get_object()
        
        # Check if the user is the owner of this event
        if event.chef.user != request.user:
            return Response(
                {"error": "You don't have permission to cancel this event"},
                status=403
            )
        
        # Check if the event can be cancelled
        if event.status == 'cancelled':
            return Response(
                {"error": "This event is already cancelled"},
                status=400
            )
        
        if event.event_date < timezone.now().date():
            return Response(
                {"error": "You cannot cancel past events"},
                status=400
            )
        
        # Cancel the event and issue refunds
        try:
            event.cancel()
            return Response({"status": "Event cancelled successfully"})
        except Exception as e:
            return Response(
                {"error": f"Failed to cancel event: {str(e)}"},
                status=500
            )

class ChefMealOrderViewSet(viewsets.ModelViewSet):
    """
    DEPRECATED: This ViewSet is being replaced with function-based views:
    - api_chef_meal_orders
    - api_chef_meal_order_detail
    - api_cancel_chef_meal_order
    
    Keep this for now to ensure backward compatibility, but new code should
    use the function-based API views instead.
    """
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        # Chef viewing their received orders
        if self.request.query_params.get('as_chef') == 'true':
            try:
                chef = Chef.objects.get(user=user)
                return ChefMealOrder.objects.filter(meal_event__chef=chef).order_by('-created_at')
            except Chef.DoesNotExist:
                return ChefMealOrder.objects.none()
        
        # Default: customer viewing their own orders
        return ChefMealOrder.objects.filter(customer=user).order_by('-created_at')
    
    def get_serializer_class(self):
        if self.action in ['create']:
            return ChefMealOrderCreateSerializer
        return ChefMealOrderSerializer
    
    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        
        # Check if the user is the owner of this order
        if order.customer != request.user:
            return Response(
                {"error": "You don't have permission to cancel this order"},
                status=403
            )
        
        # Check if the order can be cancelled
        if order.status not in ['placed', 'confirmed']:
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

class ChefMealReviewViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ChefMealReviewSerializer
    
    def get_queryset(self):
        user = self.request.user
        
        # Filter by chef if requested
        chef_id = self.request.query_params.get('chef_id')
        if chef_id:
            return ChefMealReview.objects.filter(chef_id=chef_id).order_by('-created_at')
        
        # Filter by meal event if requested
        event_id = self.request.query_params.get('event_id')
        if event_id:
            return ChefMealReview.objects.filter(meal_event_id=event_id).order_by('-created_at')
        
        # Default: return reviews left by this user
        return ChefMealReview.objects.filter(customer=user).order_by('-created_at')
    
    def perform_create(self, serializer):
        order = serializer.validated_data['chef_meal_order']
        
        # Ensure the user is the owner of this order
        if order.customer != self.request.user:
            raise PermissionDenied("You don't have permission to review this order")
        
        serializer.save(
            customer=self.request.user,
            chef=order.meal_event.chef,
            meal_event=order.meal_event
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_stripe_account_status(request):
    """Check if a chef has a connected Stripe account and its status"""
    logger.info(f"API Stripe account status requested by user {request.user.id}")
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} requested Stripe account status but is not a chef")
        return Response(
            {"error": "You must be a registered chef to access this endpoint"},
            status=403
        )
    
    try:
        stripe_account = StripeConnectAccount.objects.get(chef=chef)
        # Sync with Stripe - expand external_accounts to access bank account data
        account_info = stripe.Account.retrieve(
            stripe_account.stripe_account_id,
            expand=['external_accounts']
        )
        stripe_account.is_active = (
            account_info.charges_enabled and 
            account_info.details_submitted and 
            account_info.payouts_enabled
        )
        stripe_account.save()
        
        # Enhanced diagnostic information
        diagnostic_info = {
            'charges_enabled': account_info.charges_enabled,
            'details_submitted': account_info.details_submitted,
            'payouts_enabled': account_info.payouts_enabled,
            'currently_due': account_info.requirements.currently_due or [],
            'eventually_due': account_info.requirements.eventually_due or [],
            'past_due': account_info.requirements.past_due or [],
            'disabled_reason': account_info.requirements.disabled_reason,
            'capabilities': dict(account_info.capabilities) if account_info.capabilities else {},
            'external_accounts_count': len(getattr(account_info, 'external_accounts', {}).get('data', [])) if hasattr(account_info, 'external_accounts') else 0
        }
        
        # Check if user needs to complete onboarding to add bank accounts
        needs_onboarding = bool(
            diagnostic_info['currently_due'] or 
            diagnostic_info['past_due'] or
            diagnostic_info['external_accounts_count'] == 0
        )
        
        # Generate continuation link if needed
        continue_onboarding_url = None
        if needs_onboarding:
            try:
                base_url = os.getenv("STREAMLIT_URL")
                if base_url:
                    account_link = stripe.AccountLink.create(
                        account=stripe_account.stripe_account_id,
                        refresh_url=f"{base_url}/",
                        return_url=f"{base_url}/",
                        type="account_onboarding",
                    )
                    continue_onboarding_url = account_link.url
            except stripe.error.StripeError as e:
                logger.error(f"Failed to create continuation link: {str(e)}")
        
        return Response({
            'has_account': True,
            'is_active': stripe_account.is_active,
            'account_id': stripe_account.stripe_account_id,
            'disabled_reason': account_info.requirements.disabled_reason,
            'needs_onboarding': needs_onboarding,
            'continue_onboarding_url': continue_onboarding_url,
            'diagnostic': diagnostic_info,  # Add this for debugging
        }, status=200)
    except StripeConnectAccount.DoesNotExist:
        return Response({'has_account': False}, status=200)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_create_stripe_account_link(request):
    """Create a Stripe account link for onboarding or updating"""
    from custom_auth.models import CustomUser
    try:
        user_id = request.data.get('user_id')
    except Exception as e:
        logger.error(f"Error getting user ID: {str(e)}")
        return Response(
            {"error": "Failed to get user ID"},
            status=500
        )
    user = CustomUser.objects.get(id=user_id)
            
    logger.info(f"API create Stripe account link requested by user {user.id}")
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} tried to create Stripe account link but is not a chef")
        return Response(
            {"error": "You must be a registered chef to access this endpoint"},
            status=403
        )
    
    # Set Stripe API version to latest
    stripe.api_version = '2023-10-16'
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    # Check if we already have a Stripe account and update it if necessary
    try:
        stripe_account = StripeConnectAccount.objects.get(chef=chef)
        account_id = stripe_account.stripe_account_id
        logger.info(f"Found existing Stripe account {account_id} for chef {chef.id}")
        stripe_account_info = stripe.Account.retrieve(account_id)
        stripe_account.is_active = (
            stripe_account_info.charges_enabled and 
            stripe_account_info.details_submitted and 
            stripe_account_info.payouts_enabled
        )
        stripe_account.save()

        # If there are requirements due, you might want to log them
        if stripe_account_info.requirements.currently_due:
            logger.info(f"Stripe account {stripe_account.stripe_account_id} has pending requirements: {stripe_account_info.requirements.currently_due}")
        
    except StripeConnectAccount.DoesNotExist:
        # Create a new Stripe account using the latest controller pattern
        try:
            logger.info(f"Creating new Stripe account for chef {chef.id}")
            
            # Check if user has a country code set
            try:
                user_address = request.user.address
                if not user_address or not user_address.country:
                    return Response(
                        {
                            "error": "Please add your country in your profile settings before creating a Stripe account",
                            "details": "Country code is required for Stripe account creation"
                        },
                        status=400
                    )
                country_code = user_address.country.code
            except Address.DoesNotExist:
                return Response(
                    {
                        "error": "Please add your address and country in your profile settings before creating a Stripe account",
                        "details": "Address and country code are required for Stripe account creation"
                    },
                    status=400
                )

            account = stripe.Account.create(
                controller={
                    "stripe_dashboard": {
                        "type": "express",
                    },
                    "fees": {
                        "payer": "application"
                    },
                    "losses": {
                        "payments": "application"
                    },
                },
                email=request.user.email,
                country=country_code,
                business_profile={
                    "name": f"{request.user.first_name} {request.user.last_name}",
                    "product_description": "Chef prepared meals"
                },
                capabilities={
                    "transfers": {"requested": True},
                    # Chefs only receive transfers from platform, not process payments directly
                },
                tos_acceptance={
                    "service_agreement": "recipient"  # Recipient agreement for transfer-only accounts
                }
            )
            
            # Set payout schedule for new accounts
            try:
                stripe.Account.modify(
                    account.id,
                    settings={
                        "payouts": {
                            "schedule": {
                                "interval": "daily",
                            },
                            "debit_negative_balances": True,
                        },
                    },
                )
                logger.info(f"Set weekly payout schedule for new Stripe account {account.id}")
            except stripe.error.StripeError as sched_err:
                logger.warning(f"Could not set payout schedule for {account.id}: {sched_err}")

            # Save the account to our database
            stripe_account = StripeConnectAccount.objects.create(
                chef=chef,
                stripe_account_id=account.id,
                is_active=False
            )
            account_id = account.id
            logger.info(f"Created new Stripe account {account_id} for chef {chef.id}")
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create Stripe account for chef {chef.id}: {str(e)}")
            return Response(
                {"error": f"Failed to create Stripe account: {str(e)}"},
                status=500
            )
    
    # Since this is a backend API, we don't need to generate return URLs
    # We'll just create the account link and return the data to Streamlit
    
    try:
        logger.info(f"Creating account link for Stripe account {account_id}")
        # We still need to provide return_url and refresh_url to Stripe
        # but these can be dummy URLs since Streamlit will handle the flow
        base_url = os.getenv("STREAMLIT_URL")
        if not base_url:
            return Response({
                "error": "Front end URL environment variable not set",
                "status": "error",
                "account_id": account_id
            }, status=500)
        
        account_link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=f"{base_url}/meal-plans",
            return_url=f"{base_url}/meal-plans",
            type="account_onboarding",
        )
        # Return data directly to Streamlit frontend
        return Response({
            "url": account_link.url,
            "account_id": account_id,
            "status": "success"
        }, status=200)
    except stripe.error.StripeError as e:
        logger.error(f"Failed to create account link for Stripe account {account_id}: {str(e)}")
        return Response({
            "error": f"Failed to create account link: {str(e)}",
            "status": "error",
            "account_id": account_id
        }, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_process_chef_meal_payment(request, order_id):

    
    try:
        # Wrap the flow in a transaction and lock the order row to avoid races
        with transaction.atomic():
            # Get the regular Order object (locked for update)
            order = Order.objects.select_for_update().get(id=order_id, customer=request.user)
            # Short-circuit if already paid
            if order.is_paid:
                return standardize_stripe_response(
                    success=True,
                    message="Order already paid.",
                    data={"order_id": order.id, "status": order.status}
                )

            # Reuse an open Checkout session if it exists
            if order.stripe_session_id:
                try:
                    session_existing = stripe.checkout.Session.retrieve(order.stripe_session_id)
                    if session_existing and getattr(session_existing, 'status', None) == 'open':
                        return standardize_stripe_response(
                            success=True,
                            message="Reusing existing checkout session",
                            data={"session_id": session_existing.id, "session_url": getattr(session_existing, 'url', None)}
                        )
                    # If the session has completed, mark paid if not already
                    if session_existing and getattr(session_existing, 'status', None) == 'complete' and not order.is_paid:
                        order.is_paid = True
                        order.status = order.status or 'Confirmed'
                        order.save(update_fields=['is_paid', 'status'])
                        return standardize_stripe_response(
                            success=True,
                            message="Order payment already completed.",
                            data={"order_id": order.id, "status": order.status}
                        )
                except Exception:
                    # Fall through to create a fresh session
                    pass
        
        # Get chef meal events from OrderMeal objects
        order_meals = order.ordermeal_set.filter(
            chef_meal_event__isnull=False
        ).select_related('chef_meal_event', 'meal', 'meal_plan_meal')
        
        if not order_meals.exists():
            return standardize_stripe_response(
                success=False,
                message="No chef meal events found for this order.",
                status_code=400
            )
        
        # Prepare line items for Stripe Checkout
        line_items = []
        checkout_chef = None
        total_amount_cents = 0

        for order_meal in order_meals:
            meal = order_meal.meal
            meal_event = order_meal.chef_meal_event
            meal_plan_meal = order_meal.meal_plan_meal

            # Skip meals that have already been paid for
            if hasattr(meal_plan_meal, 'already_paid') and meal_plan_meal.already_paid:
                continue

            current_chef = meal_event.chef
            if checkout_chef is None:
                checkout_chef = current_chef
            elif checkout_chef.id != current_chef.id:
                return standardize_stripe_response(
                    success=False,
                    message="Orders that include multiple chefs must be paid separately.",
                    status_code=400
                )

            # Get the associated ChefMealOrder for the correct quantity
            try:
                chef_meal_order = ChefMealOrder.objects.get(
                    order=order,
                    meal_plan_meal=meal_plan_meal
                )
                actual_quantity = chef_meal_order.quantity
            except ChefMealOrder.DoesNotExist:
                actual_quantity = order_meal.quantity

            # Always use the current price from the meal event
            current_price = meal_event.current_price
            unit_amount = int(decimal.Decimal(current_price) * 100)
            if unit_amount <= 0 or actual_quantity <= 0:
                continue

            total_amount_cents += unit_amount * actual_quantity
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': meal.name,
                        'description': meal_event.description[:500] if meal_event.description else "",
                    },
                    'unit_amount': unit_amount,
                },
                'quantity': actual_quantity,
            })

        if not line_items:
            return standardize_stripe_response(
                success=False,
                message="No items requiring payment found in this order.",
                status_code=400
            )

        if checkout_chef is None or total_amount_cents <= 0:
            return standardize_stripe_response(
                success=False,
                message="Unable to process payment for this order.",
                status_code=400
            )

        try:
            destination_account_id, _ = get_active_stripe_account(checkout_chef)
        except StripeAccountError as exc:
            return standardize_stripe_response(False, str(exc), status_code=400)

        platform_fee_cents = calculate_platform_fee_cents(total_amount_cents)
        
        # Create Stripe Checkout Session
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        return_urls = get_stripe_return_urls(
            success_path="",
            cancel_path=""
        )
        
        session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            **return_urls,
            metadata={
                'order_id': str(order.id),
                'order_type': 'chef_meal',
                'customer_id': str(request.user.id),
                'chef_id': str(checkout_chef.id),
            },
            payment_intent_data={
                'transfer_data': {'destination': destination_account_id},
                'on_behalf_of': destination_account_id,
                'metadata': {
                    'order_id': str(order.id),
                    'chef_id': str(checkout_chef.id),
                    'order_type': 'chef_meal',
                },
                **({'application_fee_amount': platform_fee_cents} if platform_fee_cents else {}),
            }
        )
        
        # Save the session ID to the order (outside tx is acceptable; if this fails, status endpoint can still finalize)
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=order_id, customer=request.user)
                order.stripe_session_id = session.id
                order.save(update_fields=['stripe_session_id'])
        except Exception:
            logger.warning(f"Could not persist stripe_session_id for order {order_id}; will rely on status endpoint/webhook.")
        

        
        # Return success response
        return standardize_stripe_response(
            success=True,
            message="Checkout session created successfully",
            data={"session_id": session.id, "session_url": session.url}
        )
    
    except Order.DoesNotExist:
        return standardize_stripe_response(
            success=False,
            message="Order not found.",
            status_code=404
        )
    except Exception as e:
        logger.error(f"Error processing chef meal payment: {str(e)}", exc_info=True)
        return standardize_stripe_response(
            success=False,
            message=f"Payment processing error: {str(e)}",
            status_code=400
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_process_meal_payment(request, order_id):
    """
    API endpoint for processing payments for regular meal orders using Stripe Checkout.
    """

    # Get the order object
    order = get_object_or_404(Order, id=order_id, customer=request.user)

    if order.is_paid:

        return standardize_stripe_response(
            success=False,
            message="This order has already been paid for.",
            status_code=400
        )

    try:

        total_price_decimal = order.total_price()
        if total_price_decimal is None or total_price_decimal <= 0:

            return standardize_stripe_response(
                success=False,
                message="Cannot process payment for an order with zero or invalid total price.",
                status_code=400
            )
        
        total_price_cents = int(total_price_decimal * 100)


        # Get return URLs
        return_urls = get_stripe_return_urls(
            success_path="", 
            cancel_path="" 
        )


        # Prepare line items for Stripe Checkout
        line_items = []
        checkout_chef = None
        total_amount_cents = 0
        for order_meal in order.ordermeal_set.all():
            meal = order_meal.meal
            chef_meal_event = order_meal.chef_meal_event
            meal_plan_meal = order_meal.meal_plan_meal
            
            # Skip if no valid chef meal event
            if not chef_meal_event:

                continue

            current_chef = chef_meal_event.chef
            if checkout_chef is None:
                checkout_chef = current_chef
            elif checkout_chef.id != current_chef.id:
                return standardize_stripe_response(
                    success=False,
                    message="Orders that include multiple chefs must be paid separately.",
                    status_code=400
                )
            
            # Get the quantity from the ChefMealOrder if it exists
            try:
                chef_meal_order = ChefMealOrder.objects.get(
                    order=order,
                    meal_plan_meal=meal_plan_meal
                )
                actual_quantity = chef_meal_order.quantity

            except ChefMealOrder.DoesNotExist:
                actual_quantity = order_meal.quantity

            
            # Always use the current price from the chef meal event
            unit_price = chef_meal_event.current_price

            if not unit_price or unit_price <= 0:

                continue
            
            unit_amount = int(decimal.Decimal(unit_price) * 100)
            if unit_amount <= 0 or actual_quantity <= 0:
                continue

            total_amount_cents += unit_amount * actual_quantity
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': meal.name,
                    },
                    'unit_amount': unit_amount, # Price per unit in cents
                },
                'quantity': actual_quantity,
            })
        
        if not line_items:

             return standardize_stripe_response(
                 success=False,
                 message="No items requiring payment found in this order.",
                 status_code=400
             )


        if checkout_chef is None or total_amount_cents <= 0:
            return standardize_stripe_response(
                success=False,
                message="Unable to process payment for this order.",
                status_code=400
            )

        try:
            destination_account_id, _ = get_active_stripe_account(checkout_chef)
        except StripeAccountError as exc:
            return standardize_stripe_response(False, str(exc), status_code=400)

        platform_fee_cents = calculate_platform_fee_cents(total_amount_cents)


        
        # Create an idempotency key based on order ID to prevent duplicate charges
        idempotency_key = f"order_{order.id}_{int(time.time())}"
        
        # Create Stripe Checkout Session with idempotency key
        session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            **return_urls,
            metadata={
                'order_id': str(order.id),
                'order_type': 'standard',
                'customer_id': str(request.user.id),
                'chef_id': str(checkout_chef.id),
            },
            idempotency_key=idempotency_key,
            payment_intent_data={
                'transfer_data': {'destination': destination_account_id},
                'on_behalf_of': destination_account_id,
                'metadata': {
                    'order_id': str(order.id),
                    'chef_id': str(checkout_chef.id),
                    'order_type': 'standard',
                },
                **({'application_fee_amount': platform_fee_cents} if platform_fee_cents else {}),
            }
        )

        
        # Store the session ID in the order
        order.stripe_session_id = session.id
        order.save(update_fields=['stripe_session_id'])

        # --- Start: Trigger n8n Webhook with HTML Email Body --- 
        try:
            n8n_webhook_url = os.getenv('N8N_PAYMENT_LINK_WEBHOOK_URL')
            
            # Check if user has unsubscribed from emails
            user = request.user
            if hasattr(user, 'unsubscribed_from_emails') and user.unsubscribed_from_emails:
                logger.info(f"User {user.id} has unsubscribed from emails. Skipping payment link email.")
            elif n8n_webhook_url and session.url:
                meal_plan = order.meal_plan
                user_name = user.get_full_name() or user.username
                meal_plan_week_str = f"{meal_plan.week_start_date.strftime('%Y-%m-%d')} to {meal_plan.week_end_date.strftime('%Y-%m-%d')}" if meal_plan else 'N/A'

                # Prepare context for the email template
                context = {
                    'user_name': user_name,
                    'checkout_url': session.url,
                    'order_id': order.id,
                    'meal_plan_week': meal_plan_week_str,
                    'profile_url': os.getenv('STREAMLIT_URL') + '/meal-plans' # Or construct your profile URL differently
                }

                # Render the HTML email body
                email_body_html = render_to_string('meals/payment_link_email.html', context)

                # Prepare payload for n8n (matching the shopping list format)
                email_data = {
                    'subject': f'Payment Required for Your Meal Plan (Order #{order.id})',
                    'html_message': email_body_html, # Send rendered HTML
                    'to': user.email,
                    'from': getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@sautai.com') # Use setting or default
                }
                

                # Send POST request to n8n webhook (fire and forget)
                response = requests.post(n8n_webhook_url, json=email_data, timeout=10) # Added timeout
                response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

            elif not session.url:
                 print("[WARN] Stripe session URL not found. Cannot trigger n8n webhook.")
            else:
                print("[WARN] N8N_PAYMENT_LINK_WEBHOOK_URL not configured in Django settings. Skipping n8n trigger.")
        except requests.exceptions.RequestException as webhook_error:
            # Log error but don't fail the payment process
            logger.error(f"Error triggering n8n webhook for order {order_id} email: {webhook_error}", exc_info=True)
            #n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_process_meal_payment", "traceback": traceback.format_exc()})
        except Exception as general_error: # Catch any other unexpected errors
            #n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": str(e), "source":"api_process_meal_payment", "traceback": traceback.format_exc()})
            logger.error(f"Unexpected error during n8n trigger for order {order_id} email: {general_error}", exc_info=True)
        # --- End: Trigger n8n Webhook --- 

        # Return the original response to Streamlit
        return standardize_stripe_response(
            success=True,
            message="Checkout session created successfully",
            data={"session_id": session.id, "session_url": session.url},
            status_code=200 # Explicitly set 200 OK
        )

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error processing payment for order {order_id}: {str(e)}")
        return handle_stripe_error(request, f"Payment processing error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error processing payment for order {order_id}: {str(e)}", exc_info=True) # Log traceback
        return handle_stripe_error(request, "An unexpected error occurred while processing your payment.")
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_order_payment_status(request, order_id):
    """
    Lightweight status check for an order's payment state and reusable Checkout session.
    """
    try:
        logger.info(f"PAYMENT_STATUS: user={request.user.id} order_id={order_id}")
        order = Order.objects.get(id=order_id, customer=request.user)
        payload = {
            "order_id": order.id,
            "is_paid": bool(order.is_paid),
            "status": order.status,
            "has_session": bool(order.stripe_session_id),
            "session_status": None,
            "session_url": None,
        }
        # Prefer a provided session_id/stripe_payment_intent_id  (e.g., from Stripe success redirect) when present
        provided_session_id = request.query_params.get('session_id') or request.GET.get('session_id')
        provided_pi_id = request.query_params.get('payment_intent_id') or request.GET.get('payment_intent_id')
        session_id_to_check = provided_session_id or order.stripe_session_id
        if session_id_to_check:
            try:
                session = stripe.checkout.Session.retrieve(session_id_to_check)
                logger.info(f"PAYMENT_STATUS: session_id={session.id} status={getattr(session,'status',None)} payment_status={getattr(session,'payment_status',None)} (provided={bool(provided_session_id)})")
                payload["session_status"] = getattr(session, "status", None)
                payload["session_url"] = getattr(session, "url", None)

                # Opportunistic finalize: if session completed and paid but order not yet marked paid,
                # update the order and confirm related chef items. This avoids relying solely on webhooks.
                is_complete = getattr(session, "status", None) == "complete"
                is_paid = getattr(session, "payment_status", None) == "paid"
                # Verify the session belongs to this order via metadata when present
                meta_order_id = None
                try:
                    meta_order_id = int(getattr(session, 'metadata', {}).get('order_id')) if getattr(session, 'metadata', None) else None
                except Exception:
                    meta_order_id = None
                session_matches_order = (meta_order_id == order.id) or (meta_order_id is None)

                if (is_complete or is_paid) and session_matches_order and not order.is_paid:
                    logger.info(f"PAYMENT_STATUS: finalizing order={order.id} from session={session.id}")
                    # Mark order paid and move to active status
                    order.is_paid = True
                    # Keep existing status if already advanced; else use a valid active status
                    order.status = order.status or 'In Progress'
                    order.save(update_fields=['is_paid', 'status'])

                    # If a provided session_id was used and differs from stored, update it
                    if provided_session_id and order.stripe_session_id != provided_session_id:
                        order.stripe_session_id = provided_session_id
                        order.save(update_fields=['stripe_session_id'])

                    # Confirm associated chef items
                    chef_items = ChefMealOrder.objects.filter(order=order, status__in=['placed']).select_related('meal_event')
                    for item in chef_items:
                        try:
                            # Save payment intent from session
                            item.stripe_payment_intent_id  = getattr(session, 'payment_intent', None)
                            item.mark_as_paid()
                        except Exception:
                            item.status = 'confirmed'
                            item.save(update_fields=['status', 'stripe_payment_intent_id'])

                    # Best-effort order-level payment log
                    try:
                        total_amount = float(getattr(session, 'amount_total', 0) or 0) / 100.0
                        PaymentLog.objects.create(
                            order=order,
                            user=order.customer,
                            action='charge',
                            amount=total_amount,
                            stripe_id=getattr(session, 'payment_intent', None),
                            status='succeeded',
                            details={
                                'session_id': session.id,
                                'stripe_payment_intent_id ': getattr(session, 'payment_intent', None),
                                'finalized_via': 'status_endpoint'
                            }
                        )
                    except Exception as log_err:
                        logger.warning(f"PAYMENT_STATUS: failed to log payment for order={order.id}: {log_err}")

                    # Reflect new state in return payload
                    payload["is_paid"] = True
                    payload["status"] = order.status
            except Exception as sess_err:
                logger.warning(f"PAYMENT_STATUS: failed to retrieve session for order={order.id}: {sess_err}")

        # PaymentIntent fallback if provided explicitly and not yet paid
        if not payload["is_paid"] and provided_pi_id:
            try:
                pi = stripe.PaymentIntent.retrieve(provided_pi_id)
                pi_status = getattr(pi, 'status', None)
                pi_meta = getattr(pi, 'metadata', {}) or {}
                logger.info(f"PAYMENT_STATUS: PI fallback id={pi.id} status={pi_status} meta={pi_meta}")

                # Validate that PI belongs to this order/user when metadata available
                meta_order_ok = False
                try:
                    meta_order_id = int(pi_meta.get('order_id')) if pi_meta.get('order_id') else None
                    if meta_order_id == order.id:
                        meta_order_ok = True
                except Exception:
                    meta_order_ok = False

                meta_user_ok = False
                try:
                    meta_customer = int(pi_meta.get('customer')) if pi_meta.get('customer') else None
                    if meta_customer == request.user.id:
                        meta_user_ok = True
                except Exception:
                    meta_user_ok = False

                if meta_order_ok or meta_user_ok:
                    # If requires_capture, attempt capture (idempotent)
                    if pi_status == 'requires_capture':
                        try:
                            stripe.PaymentIntent.capture(
                                pi.id,
                                idempotency_key=f"status_endpoint_capture_{pi.id}"
                            )
                            # Re-fetch PI for updated status
                            pi = stripe.PaymentIntent.retrieve(pi.id)
                            pi_status = getattr(pi, 'status', None)
                            logger.info(f"PAYMENT_STATUS: PI captured id={pi.id} new_status={pi_status}")
                        except Exception as cap_err:
                            logger.warning(f"PAYMENT_STATUS: PI capture failed id={pi.id}: {cap_err}")

                    if pi_status == 'succeeded' and not order.is_paid:
                        logger.info(f"PAYMENT_STATUS: finalizing order={order.id} from payment_intent={pi.id}")
                        order.is_paid = True
                        order.status = order.status or 'In Progress'
                        order.save(update_fields=['is_paid', 'status'])

                        # Confirm associated chef items
                        chef_items = ChefMealOrder.objects.filter(order=order, status__in=['placed']).select_related('meal_event')
                        for item in chef_items:
                            try:
                                item.stripe_payment_intent_id  = pi.id
                                item.mark_as_paid()
                            except Exception:
                                item.status = 'confirmed'
                                item.save(update_fields=['status', 'stripe_payment_intent_id'])

                        # Log payment
                        try:
                            amount = float(getattr(pi, 'amount', 0) or 0) / 100.0
                            PaymentLog.objects.create(
                                order=order,
                                user=order.customer,
                                action='charge',
                                amount=amount,
                                stripe_id=pi.id,
                                status='succeeded',
                                details={'finalized_via': 'pi_fallback'}
                            )
                        except Exception as _log_e:
                            logger.warning(f"PAYMENT_STATUS: failed to log PI payment for order={order.id}: {_log_e}")

                        payload["is_paid"] = True
                        payload["status"] = order.status
                else:
                    logger.warning(f"PAYMENT_STATUS: PI metadata did not match order/user (order={order.id}, user={request.user.id})")
            except Exception as pi_err:
                logger.warning(f"PAYMENT_STATUS: PI fallback failed id={provided_pi_id}: {pi_err}")
        return Response(payload)
    except Order.DoesNotExist:
        return Response({"error": "Order not found"}, status=404)


@api_view(['POST'])
@permission_classes([])  # Allow unauthenticated requests from Stripe
def api_stripe_webhook(request):
    logger.info("Stripe webhook received")
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
        logger.debug(f"Stripe webhook event type: {event.type}")
    except ValueError as e:
        # Invalid payload
        logger.error(f"Invalid Stripe webhook payload: {e}")
        return Response({"status": "error", "message": "Invalid payload"}, status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logger.error(f"Invalid Stripe webhook signature: {e}")
        return Response({"status": "error", "message": "Invalid signature"}, status=400)
    
    # Handle the event
    if event.type == 'checkout.session.completed':
        session = event.data.object
        logger.info(f"Checkout session completed: {session.id}")
        
        # Route Chef Service orders first by metadata
        try:
            md = getattr(session, 'metadata', {}) or {}
        except Exception:
            md = {}
        if md.get('order_type') == 'service' and md.get('service_order_id'):
            try:
                # Delegate to chef_services webhook handler
                from chef_services.webhooks import handle_checkout_session_completed
                handle_checkout_session_completed(session)
                logger.info(f"Delegated service order webhook for service_order_id={md.get('service_order_id')}")
            except Exception as svc_err:
                logger.error(f"Service order webhook handling failed: {svc_err}", exc_info=True)
            return Response({"status": "success"})

        # Route chef payment links by metadata
        if md.get('type') == 'chef_payment_link' and md.get('payment_link_id'):
            try:
                from chefs.webhooks import handle_payment_link_completed
                handle_payment_link_completed(session)
                logger.info(f"Delegated payment link webhook for payment_link_id={md.get('payment_link_id')}")
            except Exception as pl_err:
                logger.error(f"Payment link webhook handling failed: {pl_err}", exc_info=True)
            return Response({"status": "success"})

        # Extract order details from metadata
        order_id = session.metadata.get('order_id')
        order_type = session.metadata.get('order_type', '')
        
        if order_id:
            try:
                # Get the order
                order = Order.objects.get(id=order_id)
                logger.info(f"Found order {order.id} for completed checkout session {session.id}")
                
                # SECURITY CHECK: Prevent duplicate payments by checking session ID
                if order.is_paid:
                    logger.warning(f"Order {order.id} is already marked as paid. Possible duplicate webhook. Ignoring.")
                    return Response({"status": "success", "message": "Order already paid"})
                
                # SECURITY CHECK: Verify this payment session belongs to this order if we have a stored session ID
                if order.stripe_session_id and order.stripe_session_id != session.id:
                    logger.error(f"Session ID mismatch for order {order.id}. Expected {order.stripe_session_id}, got {session.id}")
                    # Log this as a security concern but still process the payment since it might be legitimate
                    # (e.g., payment retried with a new session)
                    PaymentLog.objects.create(
                        order=order,
                        action='security_warning',
                        amount=0,
                        stripe_id=session.id,
                        status='warning',
                        details={
                            'message': 'Session ID mismatch',
                            'expected_session': order.stripe_session_id,
                            'received_session': session.id
                        }
                    )
                
                # SECURITY CHECK: Verify the amount paid matches what we expect
                expected_total = order.total_price()
                amount_paid = session.amount_total / 100  # Convert from cents to dollars
                
                # Allow for small rounding differences (1 cent tolerance)
                if abs(float(expected_total) - float(amount_paid)) > 0.01:
                    logger.error(f"Amount mismatch for order {order.id}. Expected ${expected_total}, got ${amount_paid}")
                    PaymentLog.objects.create(
                        order=order,
                        action='security_warning',
                        amount=amount_paid,
                        stripe_id=session.id,
                        status='warning',
                        details={
                            'message': 'Amount mismatch',
                            'expected_amount': str(expected_total),
                            'paid_amount': str(amount_paid)
                        }
                    )
                    # Continue processing - the difference might be due to legitimate reasons
                    # like coupons applied directly in Stripe
                
                # Mark order as paid
                order.is_paid = True
                # Store the session ID if not already set
                if not order.stripe_session_id:
                    order.stripe_session_id = session.id
                order.save()
                
                # Mark all associated meal plan meals as paid to prevent double-charging
                for order_meal in order.ordermeal_set.select_related('meal_plan_meal').all():
                    if hasattr(order_meal, 'meal_plan_meal') and order_meal.meal_plan_meal:
                        order_meal.meal_plan_meal.already_paid = True
                        order_meal.meal_plan_meal.save(update_fields=['already_paid'])
                        logger.info(f"Marked MealPlanMeal {order_meal.meal_plan_meal.id} as already paid")
                
                # Create ChefMealOrder entries for any chef meal events using the utility function
                created_count = create_chef_meal_orders(order)
                
                # Update the status of all ChefMealOrder records tied to this order
                from meals.models import STATUS_CONFIRMED, PaymentLog
                chef_meal_orders = order.chef_meal_orders.all()
                for chef_order in chef_meal_orders:
                    if chef_order.status == 'placed':
                        # Use mark_as_paid to properly update order counts and pricing
                        chef_order.mark_as_paid()
                        
                        # Update payment details
                        chef_order.stripe_payment_intent_id  = session.payment_intent
                        chef_order.save(update_fields=['stripe_payment_intent_id '])
                        
                        logger.info(f"Updated ChefMealOrder {chef_order.id} to confirmed status and updated meal counts")
                        
                        # Create payment log if it doesn't exist
                        if not PaymentLog.objects.filter(chef_meal_order=chef_order).exists():
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
                                    'stripe_payment_intent_id ': session.payment_intent,
                                    'created_in_success_redirect': True
                                }
                            )
                
                if created_count > 0:
                    logger.info(f"Created {created_count} ChefMealOrder records for order {order.id}")
                else:
                    logger.info(f"No new ChefMealOrder records needed for order {order.id}")
                
            except Order.DoesNotExist:
                logger.error(f"Order {order_id} not found for completed checkout session")
                
    elif event.type == 'payment_intent.succeeded':
        payment_intent = event.data.object
        logger.info(f"Payment intent succeeded: {payment_intent.id}")
        
        # Check if this is for a chef meal order
        try:
            chef_meal_order = ChefMealOrder.objects.get(stripe_payment_intent_id =payment_intent.id)
            logger.info(f"Found chef meal order {chef_meal_order.id} for payment {payment_intent.id}")
            
            # Use mark_as_paid to update order status and pricing
            if chef_meal_order.status == 'placed':
                chef_meal_order.mark_as_paid()
                logger.info(f"Updated ChefMealOrder {chef_meal_order.id} to confirmed and updated meal counts")
            
            # Log the payment
            PaymentLog.objects.create(
                chef_meal_order=chef_meal_order,
                user=chef_meal_order.customer,
                chef=chef_meal_order.meal_event.chef,
                action='payment',
                amount=payment_intent.amount / 100,  # Convert cents to dollars
                stripe_id=payment_intent.id,
                status='succeeded',
                details={'payment_intent': payment_intent}
            )
            logger.info(f"Payment recorded for chef meal order {chef_meal_order.id}")
        except ChefMealOrder.DoesNotExist:
            logger.warning(f"No chef meal order found for payment intent {payment_intent.id}")
            # Not a chef meal order, check if it's a regular order
            pass
    
    elif event.type == 'charge.refunded':
        charge = event.data.object
        refund = charge.refunds.data[0] if charge.refunds.data else None
        
        if not refund:
            logger.warning(f"Charge refunded but no refund data found: {charge.id}")
            return Response({"status": "error", "message": "No refund data found"})
            
        logger.info(f"Charge refunded: {charge.id}, refund: {refund.id}")
        
        # Check if this is for a chef meal order
        try:
            chef_meal_order = ChefMealOrder.objects.get(stripe_charge_id=charge.id)
            logger.info(f"Found chef meal order {chef_meal_order.id} for refunded charge {charge.id}")
            
            # Update order status
            chef_meal_order.payment_status = 'refunded'
            chef_meal_order.status = 'cancelled'
            chef_meal_order.stripe_refund_id = refund.id
            chef_meal_order.save()
            
            # Log the refund
            PaymentLog.objects.create(
                chef_meal_order=chef_meal_order,
                user=chef_meal_order.customer,
                chef=chef_meal_order.meal_event.chef,
                action='refund',
                amount=refund.amount / 100,  # Convert cents to dollars
                stripe_id=refund.id,
                status='succeeded',
                details={'refund': refund}
            )
            logger.info(f"Refund recorded for chef meal order {chef_meal_order.id}")
        except ChefMealOrder.DoesNotExist:
            logger.warning(f"No chef meal order found for refunded charge {charge.id}")
            # Not a chef meal order, check if it's a regular order
            pass
    
    # Return a 200 response to acknowledge receipt of the event
    return Response({"status": "success"})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_pantry_item_from_audio(request):
    """
    Process an audio recording to create a new pantry item.
    
    The audio file should be sent as a multipart/form-data request.
    The API will:
    1. Transcribe the audio using OpenAI's Whisper API
    2. Extract pantry item information from the transcription
    3. Create a new pantry item based on the extracted information
    
    Returns:
        The created pantry item data and the original transcription.
    """
    
    # Check if there's an audio file in the request
    if not request.FILES.get('audio_file'):
        return Response({
            "error": "No audio file provided.",
            "details": "Please provide an audio file in the 'audio_file' field."
        }, status=400)
        
    # Get the uploaded file
    uploaded_file = request.FILES['audio_file']
    
    try:
        # Process the audio file to extract pantry item information
        # The OpenAI API expects a file-like object opened in binary mode
        pantry_item_info = process_audio_for_pantry_item(uploaded_file)
                
        # Create a new pantry item using the extracted information
        serializer = PantryItemSerializer(data={
            'item_name': pantry_item_info['item_name'],
            'quantity': pantry_item_info['quantity'],
            'expiration_date': pantry_item_info['expiration_date'],
            'item_type': pantry_item_info['item_type'],
            'notes': pantry_item_info['notes'],
            'weight_per_unit': pantry_item_info.get('weight_per_unit'),
            'weight_unit': pantry_item_info.get('weight_unit')
        })
        
        if serializer.is_valid():
            # Save the pantry item
            serializer.save(user=request.user)
            
            # Return the pantry item data and transcription
            return Response({
                'pantry_item': serializer.data,
                'transcription': pantry_item_info['transcription']
            }, status=status.HTTP_201_CREATED)
        else:
            # Return validation errors
            return Response({
                'error': 'Could not create pantry item with extracted information',
                'details': serializer.errors,
                'transcription': pantry_item_info['transcription'],
                'extracted_info': pantry_item_info
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        # Log the error
        logger.error(f"Error processing audio file: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return an error response
        return Response({
            'error': 'Error processing audio file',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([])  # Allow access without authentication for public dietary preferences
def api_dietary_preferences(request):
    """
    Get all dietary preferences available in the system.
    
    Returns:
    - A list of dietary preferences with id and name.
    """
    try:
        preferences = DietaryPreference.objects.all()
        serializer = DietaryPreferenceSerializer(preferences, many=True)
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Error fetching dietary preferences: {str(e)}")
        return Response(
            {"status": "error", "message": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_replace_meal_plan_meal(request):
    """
    Replace a meal in a meal plan with either a chef-created meal or an auto-generated/user-created meal.
    Handles creating/updating OrderMeal and ChefMealOrder atomically when applicable.

    Required parameters:
    - meal_plan_meal_id: ID of the MealPlanMeal to replace
    - One of:
      - chef_meal_id: ID of the chef-created Meal to use as replacement.
        Note: If your frontend only knows a ChefMealEvent ID, you may pass that
        value as chef_meal_id and the API will resolve it to the underlying Meal.
      - new_meal_id: ID of a non-chef (auto-generated/user) Meal to use as replacement

    Optional parameters (chef meals only unless noted):
    - event_id: Specific ChefMealEvent to use (if not provided, will attempt to find one)
    - quantity: Number of servings (default: 1)
    - special_requests: Any special requests for the chef (chef meals only)
    """
    from django.db import transaction
    from django.db.models import F
    
    logger.info(f"Starting api_replace_meal_plan_meal for user {request.user.id}")
    
    try:
        user = request.user
        meal_plan_meal_id = request.data.get('meal_plan_meal_id')
        chef_meal_id = request.data.get('chef_meal_id')
        new_meal_id = request.data.get('new_meal_id')
        event_id = request.data.get('event_id')
        # --- Print incoming quantity ---
        quantity_str = request.data.get('quantity', '1') # Get as string first

        try:
            quantity = int(quantity_str)
        except Exception:
            return Response({'status': 'error', 'message': 'quantity must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

        # --- End Print ---
        special_requests = request.data.get('special_requests', '')
        # Validate required parameters
        if not meal_plan_meal_id:
            logger.warning("Missing required parameter: meal_plan_meal_id")
            return Response({
                'status': 'error',
                'message': 'meal_plan_meal_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Ensure exactly one of chef_meal_id or new_meal_id is provided
        if bool(chef_meal_id) == bool(new_meal_id):
            logger.warning(f"Exactly one of chef_meal_id or new_meal_id must be provided. Provided chef_meal_id={chef_meal_id}, new_meal_id={new_meal_id}")
            return Response({
                'status': 'error',
                'message': 'Provide exactly one of chef_meal_id or new_meal_id'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Use transaction.atomic to ensure all operations are performed together
        with transaction.atomic():
            # Lock the MealPlanMeal record to prevent race conditions
            # Only select_related meal_plan to avoid outer join with nullable meal_plan__order
            try:
                meal_plan_meal = MealPlanMeal.objects.select_for_update().select_related(
                    'meal_plan'
                ).get(id=meal_plan_meal_id, meal_plan__user=user)
                logger.info(f"Locked MealPlanMeal id={meal_plan_meal.id} for user {user.id}")
                
                # Now fetch the meal plan and check for an order separately
                meal_plan = meal_plan_meal.meal_plan
                order = Order.objects.filter(associated_meal_plan=meal_plan).first()
                
            except MealPlanMeal.DoesNotExist:
                logger.warning(f"MealPlanMeal id={meal_plan_meal_id} not found for user {user.id}")
                return Response({
                    'status': 'error',
                    'message': 'Meal plan meal not found or not owned by this user'
                }, status=status.HTTP_404_NOT_FOUND)

            # Determine replacement meal
            replacement_meal = None
            is_chef_replacement = False

            if chef_meal_id:
                # Chef-created meal path
                # First, try interpreting chef_meal_id as a Meal.id
                try:
                    replacement_meal = Meal.objects.select_related('chef').get(id=chef_meal_id, chef__isnull=False)
                    is_chef_replacement = True
                    logger.info(f"Found chef meal by Meal.id={chef_meal_id}: {replacement_meal.id} - {replacement_meal.name}")
                except Meal.DoesNotExist:
                    # If not found, try interpreting chef_meal_id as a ChefMealEvent.id
                    try:
                        event_obj = ChefMealEvent.objects.select_related('meal', 'chef').get(id=chef_meal_id)
                        replacement_meal = event_obj.meal
                        is_chef_replacement = True
                        # If event_id wasn't provided, use this event
                        if not event_id:
                            event_id = str(event_obj.id)
                        logger.info(f"Resolved chef_meal_id={chef_meal_id} as ChefMealEvent.id; using Meal.id={replacement_meal.id}")
                    except ChefMealEvent.DoesNotExist:
                        logger.warning(f"Chef meal not found as Meal.id or ChefMealEvent.id for value={chef_meal_id}")
                        return Response({
                            'status': 'error',
                            'message': 'Chef meal not found'
                        }, status=status.HTTP_404_NOT_FOUND)

                # Validate the meal type matches
                if replacement_meal.meal_type != meal_plan_meal.meal_type:
                    logger.warning(f"Meal type mismatch: meal_plan_meal={meal_plan_meal.meal_type}, chef_meal={replacement_meal.meal_type}")
                    return Response({
                        'status': 'error',
                        'message': f'Chef meal type ({replacement_meal.meal_type}) does not match meal plan meal type ({meal_plan_meal.meal_type})'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Validate the chef serves the user's postal code (if applicable)
                if hasattr(user, 'address') and user.address and user.address.normalized_postalcode:
                    postal_code = user.address.normalized_postalcode
                    country = user.address.country

                    chef_serves_area = ChefPostalCode.objects.filter(
                        chef=replacement_meal.chef,
                        postal_code__code=postal_code,
                        postal_code__country=country
                    ).exists()
                    
                    if not chef_serves_area:
                        logger.warning(f"Chef {replacement_meal.chef.id} does not serve postal code {postal_code}")
                        return Response({
                            'status': 'error',
                            'message': 'This chef does not serve your postal code area'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    logger.info(f"Chef {replacement_meal.chef.id} serves postal code {postal_code}")

            else:
                # Non-chef (auto-generated/user-created) meal path
                try:
                    replacement_meal = Meal.objects.get(id=new_meal_id)
                except Meal.DoesNotExist:
                    logger.warning(f"Meal id={new_meal_id} not found")
                    return Response({
                        'status': 'error',
                        'message': 'Replacement meal not found'
                    }, status=status.HTTP_404_NOT_FOUND)

                # Enforce non-chef for new_meal_id to avoid ambiguity
                if replacement_meal.chef is not None:
                    logger.warning(f"new_meal_id {new_meal_id} is a chef meal; use chef_meal_id instead")
                    return Response({
                        'status': 'error',
                        'message': 'new_meal_id must refer to a non-chef meal; use chef_meal_id for chef meals'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Validate the meal type matches
                if replacement_meal.meal_type != meal_plan_meal.meal_type:
                    logger.warning(f"Meal type mismatch: meal_plan_meal={meal_plan_meal.meal_type}, new_meal={replacement_meal.meal_type}")
                    return Response({
                        'status': 'error',
                        'message': f'Replacement meal type ({replacement_meal.meal_type}) does not match meal plan meal type ({meal_plan_meal.meal_type})'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Mark plan as changed and require manual approval
            if meal_plan.is_approved:
                meal_plan.has_changes = True
                meal_plan.is_approved = False
                meal_plan.save(update_fields=['has_changes', 'is_approved'])
                logger.info(f"Marked MealPlan id={meal_plan.id} as having changes and not approved")

            # Mark as already paid if associated order is paid
            if order and order.is_paid:
                meal_plan_meal.already_paid = True
                meal_plan_meal.save(update_fields=['already_paid'])
                logger.info(f"Marked MealPlanMeal id={meal_plan_meal.id} as already paid")

            # Update the MealPlanMeal itself
            original_meal = meal_plan_meal.meal
            meal_plan_meal.meal = replacement_meal
            meal_plan_meal.save(update_fields=['meal'])
            logger.info(f"Updated MealPlanMeal id={meal_plan_meal.id} from Meal id={original_meal.id} to Meal id={replacement_meal.id}")

            # Process associated Order if it exists
            if order:
                logger.info(f"Processing associated Order id={order.id}")
                
                # 1. Update or create OrderMeal
                # --- Print before OrderMeal update/create ---

                # --- End Print ---
                order_meal, om_created = OrderMeal.objects.update_or_create(
                    order=order,
                    meal_plan_meal=meal_plan_meal,
                    defaults={
                        'meal': replacement_meal,
                        'quantity': quantity # <-- Make sure this uses the parsed quantity
                    }
                )
                log_action = "Created" if om_created else "Updated"
                logger.info(f"{log_action} OrderMeal id={order_meal.id} for MealPlanMeal id={meal_plan_meal.id}")
                # --- Print after OrderMeal update/create ---

                # --- End Print ---
                if is_chef_replacement:
                    # 2. Find the target ChefMealEvent
                    chef_meal_event = None
                    if event_id:
                        try:
                            chef_meal_event = ChefMealEvent.objects.get(id=event_id, meal=replacement_meal)
                            # Validate the event is available for orders
                            if not chef_meal_event.is_available_for_orders():
                                logger.warning(f"ChefMealEvent id={event_id} is not available for orders")
                                return Response({
                                    'status': 'error',
                                    'message': 'The selected chef meal event is not available for orders'
                                }, status=status.HTTP_400_BAD_REQUEST)
                            logger.info(f"Using provided ChefMealEvent id={event_id}")
                        except ChefMealEvent.DoesNotExist:
                            logger.warning(f"Provided event_id={event_id} not found or not valid")
                            return Response({
                                'status': 'error',
                                'message': 'The specified chef meal event was not found'
                            }, status=status.HTTP_404_NOT_FOUND)
                    else:
                        # Automatic event finding logic
                        from django.utils import timezone
                        today = timezone.now().date()
                        meal_date = meal_plan_meal.meal_date or today
                        available_events = ChefMealEvent.objects.filter(
                            meal=replacement_meal,
                            event_date__gte=today,
                            event_date__lte=meal_date + timedelta(days=3),  # Allow up to 3 days after meal date
                            status__in=['scheduled', 'open'],
                            order_cutoff_time__gt=timezone.now(),
                            orders_count__lt=F('max_orders')
                        ).order_by('event_date', 'event_time')
                        if available_events.exists():
                            chef_meal_event = available_events.first()
                            logger.info(f"Automatically found ChefMealEvent id={chef_meal_event.id} for meal {replacement_meal.id}")
                        else:
                            logger.warning(f"No available ChefMealEvent found for meal {replacement_meal.id}")

                    # 3. Update or create ChefMealOrder
                    if chef_meal_event:
                        chef_meal_order, cmo_created = ChefMealOrder.objects.update_or_create(
                            order=order,
                            meal_plan_meal=meal_plan_meal,  # Use this as the unique constraint
                            defaults={
                                'meal_event': chef_meal_event,
                                'customer': user,
                                'quantity': quantity,
                                'price_paid': chef_meal_event.current_price,
                                'special_requests': special_requests
                            }
                        )
                        log_action = "Created" if cmo_created else "Updated"
                        logger.info(f"{log_action} ChefMealOrder id={chef_meal_order.id} for MealPlanMeal id={meal_plan_meal.id}")
                        # Update the OrderMeal to link it to the ChefMealEvent
                        order_meal.chef_meal_event = chef_meal_event
                        order_meal.save(update_fields=['chef_meal_event'])
                        logger.info(f"Linked OrderMeal id={order_meal.id} to ChefMealEvent id={chef_meal_event.id}")
                    else:
                        # No valid event found - ensure no ChefMealOrder exists for this slot
                        deleted_count, _ = ChefMealOrder.objects.filter(
                            order=order,
                            meal_plan_meal=meal_plan_meal
                        ).delete()
                        if deleted_count > 0:
                            logger.info(f"Deleted {deleted_count} ChefMealOrder(s) for MealPlanMeal id={meal_plan_meal.id}")
                        # Clear link in OrderMeal
                        if order_meal.chef_meal_event:
                            order_meal.chef_meal_event = None
                            order_meal.save(update_fields=['chef_meal_event'])
                            logger.info(f"Cleared ChefMealEvent link from OrderMeal id={order_meal.id}")
                else:
                    # Replacement is a non-chef meal: remove any ChefMealOrder and unlink event
                    deleted_count, _ = ChefMealOrder.objects.filter(
                        order=order,
                        meal_plan_meal=meal_plan_meal
                    ).delete()
                    if deleted_count > 0:
                        logger.info(f"Deleted {deleted_count} ChefMealOrder(s) for MealPlanMeal id={meal_plan_meal.id} due to non-chef replacement")
                    if order_meal.chef_meal_event:
                        order_meal.chef_meal_event = None
                        order_meal.save(update_fields=['chef_meal_event'])
                        logger.info(f"Cleared ChefMealEvent link from OrderMeal id={order_meal.id} due to non-chef replacement")
            else:
                logger.info(f"No Order associated with MealPlan id={meal_plan.id}. No OrderMeal/ChefMealOrder processing needed.")

        # Success response with serialized data
        from meals.serializers import MealPlanMealSerializer
        serializer = MealPlanMealSerializer(meal_plan_meal, context={'request': request})
        return Response({
            'status': 'success',
            'message': 'Meal plan meal replaced successfully',
            'meal_plan_meal': serializer.data
        })

    except ValueError as e:
        logger.error(f"Value error in api_replace_meal_plan_meal: {str(e)}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error in api_replace_meal_plan_meal: {str(e)}", exc_info=True)
        return Response({
            'status': 'error',
            'message': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_add_meal_slot(request):
    """
    Create or fill an empty meal slot for a user's meal plan when there is no existing MealPlanMeal to replace.

    Required parameters:
    - week_start_date: YYYY-MM-DD for the plan week
    - day: Weekday name (e.g., 'Monday')
    - meal_type: One of ['Breakfast','Lunch','Dinner']

    One of:
    - chef_meal_id: Use an existing chef-created meal
    - new_meal_id: Use an existing non-chef meal

    If neither chef_meal_id nor new_meal_id is provided, this will generate a new meal for that slot using existing generation logic.
    """
    from django.db import transaction
    from datetime import datetime, timedelta
    
    user = request.user
    week_start_date_str = request.data.get('week_start_date') or request.query_params.get('week_start_date')
    day_name = request.data.get('day')
    meal_type = request.data.get('meal_type')
    chef_meal_id = request.data.get('chef_meal_id')
    new_meal_id = request.data.get('new_meal_id')
    user_prompt = request.data.get('user_prompt')
    if not week_start_date_str or not day_name or not meal_type:
        return Response({'status': 'error', 'message': 'week_start_date, day, and meal_type are required'}, status=400)
    try:
        start_of_week = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'status': 'error', 'message': 'Invalid week_start_date format. Use YYYY-MM-DD'}, status=400)
    end_of_week = start_of_week + timedelta(days=6)

    valid_days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    if day_name not in valid_days:
        return Response({'status': 'error', 'message': 'Invalid day'}, status=400)
    if meal_type not in ['Breakfast','Lunch','Dinner']:
        return Response({'status': 'error', 'message': 'Invalid meal_type'}, status=400)

    # Get or create the meal plan for that week
    with transaction.atomic():
        meal_plan, _ = MealPlan.objects.get_or_create(
            user=user,
            week_start_date=start_of_week,
            week_end_date=end_of_week,
            defaults={}
        )

        # compute meal_date from day
        day_to_idx = {name: idx for idx, name in enumerate(valid_days)}
        meal_date = start_of_week + timedelta(days=day_to_idx[day_name])

        # If slot already exists, return conflict
        if MealPlanMeal.objects.filter(meal_plan=meal_plan, day=day_name, meal_type=meal_type).exists():
            return Response({'status': 'error', 'message': 'Slot already filled'}, status=409)

        # If a concrete meal id was given
        if chef_meal_id or new_meal_id:
            try:
                meal_id = chef_meal_id or new_meal_id
                meal = Meal.objects.get(id=meal_id)
            except Meal.DoesNotExist:
                return Response({'status': 'error', 'message': 'Meal not found'}, status=404)
            if meal.meal_type != meal_type:
                return Response({'status': 'error', 'message': 'Meal type mismatch'}, status=400)
            mpm = MealPlanMeal.objects.create(
                meal_plan=meal_plan,
                meal=meal,
                day=day_name,
                meal_date=meal_date,
                meal_type=meal_type,
            )
        else:
            # Generate a new meal for this slot using existing helper
            # Reuse generate_and_create_meal to ensure parity with planning pipeline
            existing_meals = MealPlanMeal.objects.filter(meal_plan=meal_plan)
            existing_names = set(existing_meals.values_list('meal__name', flat=True))
            existing_embs = list(existing_meals.values_list('meal__meal_embedding', flat=True))

            from meals.meal_generation import generate_and_create_meal
            result = generate_and_create_meal(
                user=user,
                meal_plan=meal_plan,
                meal_type=meal_type,
                existing_meal_names=existing_names,
                existing_meal_embeddings=existing_embs,
                user_id=user.id,
                day_name=day_name,
                user_prompt=user_prompt,
            )
            if result.get('status') != 'success':
                return Response({'status': 'error', 'message': result.get('message', 'Generation failed')}, status=500)
            # Find created slot
            mpm = MealPlanMeal.objects.filter(meal_plan=meal_plan, day=day_name, meal_type=meal_type).order_by('-id').first()
            if not mpm:
                return Response({'status': 'error', 'message': 'Generated meal not attached'}, status=500)

        # If plan was previously approved, mark as changed
        if meal_plan.is_approved:
            meal_plan.has_changes = True
            meal_plan.is_approved = False
            meal_plan.save(update_fields=['has_changes','is_approved'])

    from meals.serializers import MealPlanMealSerializer
    serializer = MealPlanMealSerializer(mpm, context={'request': request})
    return Response({'status': 'success', 'meal_plan_meal': serializer.data})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_suggest_alternatives_for_slot(request):
    """
    Suggest alternative meals for a slot where there is no existing MealPlanMeal.

    Params:
    - week_start_date: YYYY-MM-DD
    - day: Monday–Sunday
    - meal_type: Breakfast/Lunch/Dinner

    Returns a list of alternative meals (chef-first then user/auto meals) suitable for that date and type.
    """
    from datetime import datetime, timedelta
    user = request.user
    week_start_date_str = request.data.get('week_start_date') or request.query_params.get('week_start_date')
    day_name = request.data.get('day')
    meal_type = request.data.get('meal_type')

    if not week_start_date_str or not day_name or not meal_type:
        return Response({'status': 'error', 'message': 'week_start_date, day, and meal_type are required'}, status=400)
    try:
        start_of_week = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'status': 'error', 'message': 'Invalid week_start_date format. Use YYYY-MM-DD'}, status=400)

    valid_days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    if day_name not in valid_days:
        return Response({'status': 'error', 'message': 'Invalid day'}, status=400)
    if meal_type not in ['Breakfast','Lunch','Dinner']:
        return Response({'status': 'error', 'message': 'Invalid meal_type'}, status=400)

    # Compute the target date from the week start and day
    day_to_idx = {name: idx for idx, name in enumerate(valid_days)}
    target_date = start_of_week + timedelta(days=day_to_idx[day_name])

    # Reuse suggest_alternative_meals by passing a dummy meal id list but correct day/type
    # We'll pick a representative meal_id that won't be included (0), the util excludes by id but we just want candidates.
    from shared.utils import suggest_alternative_meals
    alt_response = suggest_alternative_meals(
        request=request,
        meal_ids=[0],
        days_of_week=[day_name],
        meal_types=[meal_type]
    )
    if isinstance(alt_response, dict) and alt_response.get('status') == 'error':
        return Response({'status': 'error', 'message': alt_response.get('message', 'Failed to suggest alternatives')}, status=500)

    alternatives = alt_response.get('alternative_meals', [])

    # Filter to the exact target_date for chef meals (they include start_date), keep all user meals
    filtered = []
    for m in alternatives:
        if m.get('is_chef_meal'):
            # Include only if start_date matches target_date
            if m.get('start_date') == target_date.strftime('%Y-%m-%d'):
                filtered.append(m)
        else:
            filtered.append(m)

    return Response({'status': 'success', 'alternatives': filtered})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_fill_meal_slot(request):
    """
    Fill an empty meal slot with a specific existing meal (chef or non‑chef), mirroring order-handling from api_replace_meal_plan_meal.
    This is the equivalent of replace when there is no existing MealPlanMeal.

    Required:
    - week_start_date: YYYY-MM-DD
    - day: Monday–Sunday
    - meal_type: Breakfast/Lunch/Dinner
    - one of: chef_meal_id | new_meal_id

    Optional (chef): event_id, quantity (default 1), special_requests
    """
    from django.db import transaction
    from datetime import datetime, timedelta
    from django.db.models import F

    user = request.user
    week_start_date_str = request.data.get('week_start_date') or request.query_params.get('week_start_date')
    day_name = request.data.get('day')
    meal_type = request.data.get('meal_type')
    chef_meal_id = request.data.get('chef_meal_id')
    new_meal_id = request.data.get('new_meal_id')
    event_id = request.data.get('event_id')
    quantity = int(request.data.get('quantity', 1))
    special_requests = request.data.get('special_requests', '')

    if not week_start_date_str or not day_name or not meal_type:
        return Response({'status': 'error', 'message': 'week_start_date, day, and meal_type are required'}, status=400)
    if bool(chef_meal_id) == bool(new_meal_id):
        return Response({'status': 'error', 'message': 'Provide exactly one of chef_meal_id or new_meal_id'}, status=400)
    try:
        start_of_week = datetime.strptime(week_start_date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'status': 'error', 'message': 'Invalid week_start_date format. Use YYYY-MM-DD'}, status=400)
    if day_name not in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']:
        return Response({'status': 'error', 'message': 'Invalid day'}, status=400)
    if meal_type not in ['Breakfast','Lunch','Dinner']:
        return Response({'status': 'error', 'message': 'Invalid meal_type'}, status=400)

    end_of_week = start_of_week + timedelta(days=6)
    day_to_idx = {name: idx for idx, name in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}
    meal_date = start_of_week + timedelta(days=day_to_idx[day_name])

    with transaction.atomic():
        meal_plan, _ = MealPlan.objects.get_or_create(
            user=user,
            week_start_date=start_of_week,
            week_end_date=end_of_week,
            defaults={}
        )

        # Prevent accidental overwrite
        if MealPlanMeal.objects.filter(meal_plan=meal_plan, day=day_name, meal_type=meal_type).exists():
            return Response({'status': 'error', 'message': 'Slot already filled'}, status=409)

        # Determine meal to attach
        if chef_meal_id:
            try:
                meal = Meal.objects.select_related('chef').get(id=chef_meal_id, chef__isnull=False)
            except Meal.DoesNotExist:
                return Response({'status': 'error', 'message': 'Chef meal not found'}, status=404)
            if meal.meal_type != meal_type:
                return Response({'status': 'error', 'message': 'Chef meal type mismatch'}, status=400)
        else:
            try:
                meal = Meal.objects.get(id=new_meal_id)
            except Meal.DoesNotExist:
                return Response({'status': 'error', 'message': 'Meal not found'}, status=404)
            if meal.chef is not None:
                return Response({'status': 'error', 'message': 'new_meal_id must refer to a non-chef meal'}, status=400)
            if meal.meal_type != meal_type:
                return Response({'status': 'error', 'message': 'Meal type mismatch'}, status=400)

        # Create the MealPlanMeal
        meal_plan_meal = MealPlanMeal.objects.create(
            meal_plan=meal_plan,
            meal=meal,
            day=day_name,
            meal_date=meal_date,
            meal_type=meal_type,
        )

        # If plan approved, mark changed
        if meal_plan.is_approved:
            meal_plan.has_changes = True
            meal_plan.is_approved = False
            meal_plan.save(update_fields=['has_changes','is_approved'])

        # Order handling mirrors api_replace_meal_plan_meal
        order = Order.objects.filter(associated_meal_plan=meal_plan).first()
        if order:
            order_meal, _ = OrderMeal.objects.update_or_create(
                order=order,
                meal_plan_meal=meal_plan_meal,
                defaults={
                    'meal': meal,
                    'quantity': quantity,
                }
            )

            if meal.chef is not None:
                chef_meal_event = None
                if event_id:
                    try:
                        chef_meal_event = ChefMealEvent.objects.get(id=event_id, meal=meal)
                        if not chef_meal_event.is_available_for_orders():
                            return Response({'status': 'error', 'message': 'The selected chef meal event is not available for orders'}, status=400)
                    except ChefMealEvent.DoesNotExist:
                        return Response({'status': 'error', 'message': 'The specified chef meal event was not found'}, status=404)
                else:
                    # Auto-pick an event near the slot date
                    available_events = ChefMealEvent.objects.filter(
                        meal=meal,
                        event_date__gte=timezone.now().date(),
                        event_date__lte=meal_date + timedelta(days=3),
                        status__in=['scheduled', 'open'],
                        order_cutoff_time__gt=timezone.now(),
                        orders_count__lt=F('max_orders')
                    ).order_by('event_date', 'event_time')
                    chef_meal_event = available_events.first() if available_events.exists() else None

                if chef_meal_event:
                    chef_meal_order, _ = ChefMealOrder.objects.update_or_create(
                        order=order,
                        meal_plan_meal=meal_plan_meal,
                        defaults={
                            'meal_event': chef_meal_event,
                            'customer': user,
                            'quantity': quantity,
                            'price_paid': chef_meal_event.current_price,
                            'special_requests': special_requests,
                        }
                    )
                    order_meal.chef_meal_event = chef_meal_event
                    order_meal.save(update_fields=['chef_meal_event'])
                else:
                    # Ensure no stale ChefMealOrder link for chef meal without event
                    ChefMealOrder.objects.filter(order=order, meal_plan_meal=meal_plan_meal).delete()
                    if order_meal.chef_meal_event:
                        order_meal.chef_meal_event = None
                        order_meal.save(update_fields=['chef_meal_event'])
            else:
                # Non-chef path: remove any chef order if existed
                ChefMealOrder.objects.filter(order=order, meal_plan_meal=meal_plan_meal).delete()
                if hasattr(order_meal, 'chef_meal_event') and order_meal.chef_meal_event:
                    order_meal.chef_meal_event = None
                    order_meal.save(update_fields=['chef_meal_event'])

    from meals.serializers import MealPlanMealSerializer
    serializer = MealPlanMealSerializer(meal_plan_meal, context={'request': request})
    return Response({'status': 'success', 'meal_plan_meal': serializer.data})
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_resend_payment_link(request, order_id):
    """
    Resend a payment link for an order that hasn't been paid yet.
    This creates a new Stripe checkout session.
    """
    try:
        # Get the order details
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        
        if order.is_paid:
            return Response({
                "success": False,
                "message": "This order has already been paid for."
            }, status=400)
        
        # Calculate the total price
        total_price = order.total_price()
        if total_price <= 0:
            return Response({
                "success": False,
                "message": "Cannot process payment for an order with zero or invalid total price."
            }, status=400)
        
        # Get return URLs
        return_urls = get_stripe_return_urls(
            success_path="", 
            cancel_path="" 
        )
        
        # Prepare line items for Stripe Checkout
        line_items = []
        checkout_chef = None
        total_amount_cents = 0
        for order_meal in order.ordermeal_set.all():
            meal = order_meal.meal
            chef_meal_event = order_meal.chef_meal_event
            
            # Skip this meal if it's already been paid for in a previous order
            if not chef_meal_event:

                continue

            current_chef = chef_meal_event.chef
            if checkout_chef is None:
                checkout_chef = current_chef
            elif checkout_chef.id != current_chef.id:
                return Response({
                    "success": False,
                    "message": "Orders that include multiple chefs must be paid separately."
                }, status=400)
            unit_price = chef_meal_event.current_price
            if not unit_price or unit_price <= 0:

                continue
            
            unit_amount = int(decimal.Decimal(unit_price) * 100)
            if unit_amount <= 0 or order_meal.quantity <= 0:
                continue

            total_amount_cents += unit_amount * order_meal.quantity
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': meal.name,
                    },
                    'unit_amount': unit_amount,
                },
                'quantity': order_meal.quantity,
            })
        
        if not line_items:
            return Response({
                "success": False,
                "message": "No items requiring payment found in this order."
            }, status=400)

        if checkout_chef is None or total_amount_cents <= 0:
            return Response({
                "success": False,
                "message": "Unable to process payment for this order."
            }, status=400)

        try:
            destination_account_id, _ = get_active_stripe_account(checkout_chef)
        except StripeAccountError as exc:
            return Response({
                "success": False,
                "message": str(exc)
            }, status=400)

        platform_fee_cents = calculate_platform_fee_cents(total_amount_cents)
            
        # SECURITY: Create a unique idempotency key for this resend request
        # Include timestamp to ensure it's different from previous requests
        idempotency_key = f"order_{order.id}_resend_{int(time.time())}"
        
        # Create a new Stripe checkout session - ALWAYS create a new session for security
        session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            **return_urls,
            metadata={
                'order_id': str(order.id),
                'order_type': 'meal_plan',
                'customer_id': str(request.user.id),
                'is_resend': 'true',  # Mark this as a resent payment link
                'chef_id': str(checkout_chef.id),
            },
            idempotency_key=idempotency_key,
            payment_intent_data={
                'transfer_data': {'destination': destination_account_id},
                'on_behalf_of': destination_account_id,
                'metadata': {
                    'order_id': str(order.id),
                    'chef_id': str(checkout_chef.id),
                    'order_type': 'meal_plan',
                },
                **({'application_fee_amount': platform_fee_cents} if platform_fee_cents else {}),
            }
        )
        
        # Update the order with the new session ID for tracking
        order.stripe_session_id = session.id
        order.save(update_fields=['stripe_session_id'])
        
        # Log that a new payment link was sent
        logger.info(f"New payment link generated for order {order.id} with session {session.id}")

        # Trigger email with the new payment link
        try:
            n8n_webhook_url = os.getenv('N8N_PAYMENT_LINK_WEBHOOK_URL')
            
            # Check if user has unsubscribed from emails
            user = request.user
            if hasattr(user, 'unsubscribed_from_emails') and user.unsubscribed_from_emails:
                logger.info(f"User {user.id} has unsubscribed from emails. Skipping payment link email resend.")
            elif n8n_webhook_url and session.url:
                meal_plan = order.meal_plan
                user_name = user.get_full_name() or user.username
                meal_plan_week_str = f"{meal_plan.week_start_date.strftime('%Y-%m-%d')} to {meal_plan.week_end_date.strftime('%Y-%m-%d')}" if meal_plan else 'N/A'

                # Prepare context for the email template with sanitized values
                streamlit_url = os.getenv('STREAMLIT_URL') + '/meal-plans' if os.getenv('STREAMLIT_URL') else '#'
                context = {
                    'user_name': html.escape(user_name),
                    'checkout_url': session.url,  # URLs from Stripe are safe
                    'order_id': order.id,
                    'meal_plan_week': html.escape(meal_plan_week_str),
                    'profile_url': streamlit_url  # Fallback to # if not set
                }

                # Render the HTML email body
                email_body_html = render_to_string('meals/payment_link_email.html', context)

                # Prepare payload for n8n
                email_data = {
                    'subject': f'Payment Required for Your Meal Plan (Order #{order.id})',
                    'html_message': email_body_html,
                    'to': user.email,
                    'from': getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@sautai.com')
                }
                
                # Send POST request to n8n webhook with timeout
                response = requests.post(n8n_webhook_url, json=email_data, timeout=10)
                response.raise_for_status()
                logger.info(f"Successfully triggered n8n webhook for payment link resend. Status: {response.status_code}")
            
        except requests.exceptions.RequestException as webhook_error:
            # Log error but don't fail the process
            logger.error(f"Error triggering n8n webhook for payment link resend: {webhook_error}", exc_info=True)
        except Exception as general_error:
            logger.error(f"Unexpected error during n8n trigger for payment link resend: {general_error}", exc_info=True)
        
        return Response({
            "success": True,
            "message": "Payment link sent successfully",
            "data": {
                "checkout_url": session.url,
                "session_id": session.id
            }
        })
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error resending payment link: {str(e)}")
        return Response({
            "success": False,
            "message": f"Payment link generation failed: {str(e)}"
        }, status=400)
    except Exception as e:
        logger.error(f"Unexpected error resending payment link: {str(e)}", exc_info=True)
        return Response({
            "success": False,
            "message": "An unexpected error occurred"
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chef_received_orders(request):
    """
    API endpoint for chefs to retrieve ALL orders containing their meals,
    regardless of origin (MealPlan approval or direct ChefMealEvent order).
    """


    # 1. Verify user is a chef
    try:
        chef = Chef.objects.get(user=request.user)

    except Chef.DoesNotExist:
        logger.warning(f"User {request.user.id} attempted to access chef received orders but is not a chef.")
        return Response(
            {"status": "error", "message": "You must be a registered chef to view received orders."},
            status=403
        )

    # 2. Find all Order IDs that contain OrderMeal items linked to this chef
    # This finds orders where the meal's chef OR the linked event's chef matches
    order_ids = OrderMeal.objects.filter(
        Q(meal__chef=chef) | Q(chef_meal_event__chef=chef)
    ).values_list('order_id', flat=True).distinct()



    # 3. Fetch the actual Order objects
    # Prefetch related objects for efficiency in the serializer
    orders = Order.objects.filter(
        id__in=order_ids
    ).select_related('customer', 'meal_plan').order_by('-order_date') # Order by most recent



    # 4. Serialize the data, passing the chef object in the context
    # The context is used by the serializer's get_meals_for_chef method
    serializer = ChefReceivedOrderSerializer(orders, many=True, context={'chef': chef})

    return Response(serializer.data, status=200)

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
        
        if not order_id:
            logger.error(f"No order_id in metadata for session {session_id}")
            return Response(
                {"success": False, "message": "No order ID found in session metadata"}, 
                status=400
            )
        
        from django.db import transaction
        
        # Use transaction.atomic to ensure all database operations are atomic
        # This prevents race conditions if both webhook and success redirect try to update together
        try:
            with transaction.atomic():
                # Get the order and ensure it belongs to the current user - use select_for_update to lock the row
                order = Order.objects.select_for_update().get(id=order_id, customer=request.user)
                
                # Only process if the order isn't already marked as paid
                if not order.is_paid:
                    logger.info(f"Processing success redirect for order {order.id} (session {session_id})")
                    
                    # SECURITY CHECK: Verify the amount paid matches what we expect
                    expected_total = order.total_price()
                    amount_paid = session.amount_total / 100  # Convert from cents to dollars
                    
                    # Allow for small rounding differences (1 cent tolerance)
                    if abs(float(expected_total) - float(amount_paid)) > 0.01:
                        logger.warning(f"Amount mismatch for order {order.id}. Expected ${expected_total}, got ${amount_paid}")
                        # Log the discrepancy but continue processing
                        PaymentLog.objects.create(
                            order=order,
                            action='security_warning',
                            amount=amount_paid,
                            stripe_id=session.id,
                            status='warning',
                            details={
                                'message': 'Amount mismatch in success redirect',
                                'expected_amount': str(expected_total),
                                'paid_amount': str(amount_paid)
                            }
                        )
                    
                    # Mark order as paid
                    order.is_paid = True
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
                    
                    # Create ChefMealOrder records if they don't exist yet using the utility function
                    created_count = create_chef_meal_orders(order)
                    
                    # Update the status of all ChefMealOrder records tied to this order
                    from meals.models import STATUS_CONFIRMED, PaymentLog
                    chef_meal_orders = order.chef_meal_orders.all()
                    for chef_order in chef_meal_orders:
                        if chef_order.status == 'placed':
                            chef_order.status = STATUS_CONFIRMED
                            chef_order.stripe_payment_intent_id  = session.payment_intent
                            chef_order.save()
                            logger.info(f"Updated ChefMealOrder {chef_order.id} to confirmed status")
                            
                            # Create payment log if it doesn't exist
                            if not PaymentLog.objects.filter(chef_meal_order=chef_order).exists():
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
                                        'stripe_payment_intent_id ': session.payment_intent,
                                        'created_in_success_redirect': True
                                    }
                                )
                    
                    if created_count > 0:
                        logger.info(f"Created {created_count} ChefMealOrder records in success redirect for order {order.id}")
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
            "order_id": order.id
        })
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error in payment success redirect: {str(e)}")
        return Response(
            {"success": False, "message": f"Payment processing error: {str(e)}"}, 
            status=400
        )
    except Exception as e:
        logger.error(f"Unexpected error in payment success redirect: {str(e)}", exc_info=True)
        return Response(
            {"success": False, "message": "An unexpected error occurred"}, 
            status=500
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
# @deprecated Legacy meal-plan endpoint guarded by LEGACY_MEAL_PLAN.
def api_modify_meal_plan(request, meal_plan_id):
    """
    API endpoint to modify an existing meal plan using free-form text input.
    
    POST data:
    - prompt (str): Free-form text describing the changes to make to the meal plan
    
    Returns:
    - JSON data with meal plan details and status message
    """
    try:
        
        # Get the meal plan and ensure it belongs to the requesting user
        meal_plan = MealPlan.objects.get(id=meal_plan_id, user=request.user)
        
        # Get the prompt from the request data
        prompt = request.data.get('prompt')
        
        if not prompt:
            return Response(
                {"error": "Prompt is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate a request_id for tracing
        request_id = str(uuid.uuid4())
        
        try:
            # Apply the modifications
            updated_meal_plan = apply_modifications(
                user=request.user,
                meal_plan=meal_plan,
                raw_prompt=prompt,
                request_id=request_id
            )
        except Exception as e:
            # N8N traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            try:
                requests.post(n8n_traceback_url, json={"error": f"Error in api_modify_meal_plan: {str(e)}", "source":"api_modify_meal_plan", "traceback": traceback.format_exc()})
            except Exception:
                pass
            raise
        try:
            # Fetch the updated meal plan meals to return in the response
            meal_plan_meals = MealPlanMeal.objects.filter(meal_plan=updated_meal_plan).select_related('meal')
            
            # Format the response data
            meals_data = []
            for mpm in meal_plan_meals:
                try:
                    is_chef = mpm.meal.is_chef_created() if hasattr(mpm.meal, 'is_chef_created') else False
                    meals_data.append({
                        "id": mpm.id,
                        "day": mpm.day,
                        "meal_type": mpm.meal_type,
                        "meal_name": mpm.meal.name,
                        "meal_description": mpm.meal.description,
                        "is_chef_meal": is_chef,
                    })
                except Exception as meal_err:
                    # N8N traceback
                    n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
                    try:
                        requests.post(n8n_traceback_url, json={"error": f"Error in api_modify_meal_plan: {str(meal_err)}", "source":"api_modify_meal_plan", "traceback": traceback.format_exc()})
                    except Exception:
                        pass
                    raise
            
            response_data = {
                "status": "success",
                "message": "Meal plan updated successfully",
                "meal_plan_id": updated_meal_plan.id,
                "meals": meals_data
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as format_err:
            # N8N traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            try:
                requests.post(n8n_traceback_url, json={"error": f"Error in api_modify_meal_plan: {str(format_err)}", "source":"api_modify_meal_plan", "traceback": traceback.format_exc()})
            except Exception:
                pass
            raise
    
    except MealPlan.DoesNotExist:
        return Response(
            {"error": "Meal plan not found or does not belong to you"}, 
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        # N8N traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        try:
            requests.post(n8n_traceback_url, json={"error": f"Error in api_modify_meal_plan: {str(e)}", "source":"api_modify_meal_plan", "traceback": traceback.format_exc()})
        except Exception:
            pass
        logger.error(f"Error modifying meal plan: {str(e)}")
        return Response(
            {"error": f"Failed to modify meal plan: {str(e)}"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_generate_instacart_link(request):
    """Legacy endpoint - Instacart integration has been removed."""
    return Response(
        {"status": "error", "message": "Instacart integration has been removed from this application."},
        status=status.HTTP_410_GONE
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_instacart_url(request, meal_plan_id):
    """Legacy endpoint - Instacart integration has been removed."""
    return Response(
        {"status": "error", "message": "Instacart integration has been removed from this application.", "has_url": False},
        status=status.HTTP_410_GONE
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_bank_account_guidance(request):
    """
    Provide country-specific guidance for bank account setup
    Helps users understand why bank search might be empty and what to do
    """
    try:
        chef = Chef.objects.get(user=request.user)
        stripe_account = StripeConnectAccount.objects.get(chef=chef)
        
        # Set Stripe API
        stripe.api_version = '2023-10-16'
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Get account country
        account_info = stripe.Account.retrieve(stripe_account.stripe_account_id)
        country = account_info.country
        
        # Country-specific guidance
        guidance = {
            "country": country,
            "financial_connections_available": country == "US",
            "instructions": {},
            "common_issues": []
        }
        
        if country == "JP":
            guidance["instructions"] = {
                "title": "Bank Account Setup for Japan",
                "steps": [
                    "Click 'Enter bank details manually instead' in the Stripe form",
                    "Provide your bank details:",
                    "• Bank name (in English or Japanese)",
                    "• Branch code (4 digits)", 
                    "• Account number",
                    "• Account type (checking/savings)",
                    "Stripe will verify via micro-deposits (1-2 business days)"
                ],
                "note": "Bank search is not available in Japan - manual entry is the standard process"
            }
            guidance["common_issues"] = [
                "Empty bank search results → This is normal for Japan, use manual entry",
                "Can't find my bank → Use manual entry with bank details",
                "Verification needed → Micro-deposits will be sent to verify your account"
            ]
        elif country == "US":
            guidance["instructions"] = {
                "title": "Bank Account Setup for United States", 
                "steps": [
                    "Search for your bank by name",
                    "Log in to your online banking to instantly verify",
                    "Or choose 'Enter bank details manually' for traditional verification"
                ],
                "note": "Financial Connections enables instant bank verification"
            }
        else:
            guidance["instructions"] = {
                "title": f"Bank Account Setup for {country}",
                "steps": [
                    "Use 'Enter bank details manually instead'",
                    "Provide your local bank account details",
                    "Verification will be completed according to local banking requirements"
                ],
                "note": "Bank search is currently available only in the United States"
            }
            
        return Response(guidance, status=200)
        
    except (Chef.DoesNotExist, StripeConnectAccount.DoesNotExist):
        return Response({"error": "No Stripe account found"}, status=404)
    except Exception as e:
        logger.error(f"Error getting bank guidance: {str(e)}")
        return Response({"error": "Failed to get guidance"}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_regenerate_stripe_account_link(request):
    """
    Regenerate account link for users already in onboarding process
    Useful when dashboard settings have been updated and user needs new link
    """
    logger.info(f"Regenerating account link for user {request.user.id}")
    try:
        chef = Chef.objects.get(user=request.user)
        stripe_account = StripeConnectAccount.objects.get(chef=chef)
        
        # Set Stripe API
        stripe.api_version = '2023-10-16'
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Get the current account status
        account_info = stripe.Account.retrieve(stripe_account.stripe_account_id)
        
        # Generate new account link with current dashboard settings
        base_url = os.getenv("STREAMLIT_URL")
        if not base_url:
            return Response({
                "error": "Front end URL environment variable not set",
                "status": "error"
            }, status=500)
        
        # Create fresh account link - this will use current dashboard settings
        account_link = stripe.AccountLink.create(
            account=stripe_account.stripe_account_id,
            refresh_url=f"{base_url}/",
            return_url=f"{base_url}/",
            type="account_onboarding",
        )
        
        return Response({
            "status": "success",
            "message": "New onboarding link generated with updated settings",
            "onboarding_url": account_link.url,
            "account_status": {
                "details_submitted": account_info.details_submitted,
                "charges_enabled": account_info.charges_enabled,
                "payouts_enabled": account_info.payouts_enabled
            },
            "note": "This link uses your current dashboard configuration for bank account collection"
        }, status=200)
        
    except Chef.DoesNotExist:
        return Response({"error": "User is not a chef"}, status=404)
    except StripeConnectAccount.DoesNotExist:
        return Response({"error": "No Stripe account found"}, status=404)
    except Exception as e:
        logger.error(f"Error regenerating account link: {str(e)}")
        return Response({"error": f"Failed to regenerate link: {str(e)}"}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_fix_restricted_stripe_account(request):
    """
    Fix a restricted Stripe account by creating a new properly configured account
    This is needed when the account isn't configured for platform-collected requirements
    """
    logger.info(f"Fixing restricted Stripe account for user {request.user.id}")
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({"error": "User is not a chef"}, status=404)
    
    try:
        # Check if there's an existing account
        existing_account = StripeConnectAccount.objects.filter(chef=chef).first()
        
        if existing_account:
            # Deactivate the old account (keep for records)
            existing_account.is_active = False
            existing_account.save()
            logger.info(f"Deactivated old Stripe account: {existing_account.stripe_account_id}")
        
        # Set Stripe API
        stripe.api_version = '2023-10-16'
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Get user's country
        try:
            user_address = request.user.address
            if not user_address or not user_address.country:
                return Response({
                    "error": "Please add your country in your profile settings before creating a Stripe account",
                    "details": "Country code is required for Stripe account creation"
                }, status=400)
            country_code = user_address.country.code
        except:
            return Response({
                "error": "Please add your address and country in your profile settings",
                "details": "Address and country code are required"
            }, status=400)

        # Create NEW account with recipient service agreement (transfers only)
        account = stripe.Account.create(
            controller={
                "stripe_dashboard": {
                    "type": "express",
                },
                "fees": {
                    "payer": "application"  # Platform pays Stripe fees
                },
                "losses": {
                    "payments": "application"  # Platform handles disputes
                },
                "requirement_collection": "application"  # KEY: Platform collects requirements
            },
            email=request.user.email,
            country=country_code,
            business_profile={
                "name": f"{request.user.first_name} {request.user.last_name}",
                "product_description": "Chef prepared meals"
            },
            capabilities={
                "transfers": {"requested": True},
                # Chefs only receive transfers from platform, not process payments directly
            },
            tos_acceptance={
                "service_agreement": "recipient"  # Recipient agreement for transfer-only accounts
            }
        )
        
        # Create new StripeConnectAccount record
        new_stripe_account = StripeConnectAccount.objects.create(
            chef=chef,
            stripe_account_id=account.id,
            is_active=False  # Will be activated after onboarding
        )
        
        # Generate onboarding link
        base_url = os.getenv("STREAMLIT_URL")
        if not base_url:
            return Response({
                "error": "Front end URL not configured"
            }, status=500)
        
        account_link = stripe.AccountLink.create(
            account=account.id,
            refresh_url=f"{base_url}/",
            return_url=f"{base_url}/", 
            type="account_onboarding",
        )
        
        return Response({
            "status": "success",
            "message": "New Stripe account created with proper configuration",
            "old_account_id": existing_account.stripe_account_id if existing_account else None,
            "new_account_id": account.id,
            "onboarding_url": account_link.url,
            "note": "This account is configured to collect external account information via the dashboard toggle"
        }, status=200)
        
    except Exception as e:
        logger.error(f"Error fixing restricted account: {str(e)}")
        return Response({
            "error": f"Failed to fix account: {str(e)}"
        }, status=500)
