from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import HttpResponseBadRequest, JsonResponse
from django.contrib.auth.decorators import login_required
from .forms import ChefProfileForm, ChefPhotoForm
from .models import Chef, ChefRequest, ChefPhoto
from meals.models import Dish, Meal, StripeConnectAccount
from .forms import MealForm
from .decorators import chef_required
from meals.forms import IngredientForm 
from custom_auth.models import UserRole
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from .serializers import (
    ChefPublicSerializer, ChefMeUpdateSerializer, ChefPhotoSerializer,
    GalleryPhotoSerializer, GalleryStatsSerializer
)
from .models import ChefAvailabilityState
from django.utils import timezone
from django.db.models import F, Prefetch, Q
from meals.models import (
    ChefMealEvent, ChefMealOrder, PaymentLog,
    STATUS_SCHEDULED, STATUS_OPEN, STATUS_CANCELLED, STATUS_COMPLETED,
    STATUS_PLACED, STATUS_CONFIRMED,
)
from custom_auth.models import Address
from django_countries import countries
import os
import requests
import traceback
import logging
from local_chefs.models import PostalCode, ChefPostalCode
from django.db import transaction
import stripe

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

def chef_list(request):
    return HttpResponseBadRequest('Legacy endpoint removed')


def chef_detail(request, chef_id):
    return HttpResponseBadRequest('Legacy endpoint removed')


@login_required
def chef_request(request):
    return HttpResponseBadRequest('Legacy endpoint removed')


@login_required
@chef_required
def chef_view(request):
    return HttpResponseBadRequest('Legacy endpoint removed')

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_chef_status(request):
    """
    Check if a user is a chef or has a pending chef request
    """
    user = request.user
    
    # Check if user is a chef
    is_chef = Chef.objects.filter(user=user).exists()
    
    # Check if user has a pending chef request
    has_pending_request = ChefRequest.objects.filter(
        user=user, 
        is_approved=False
    ).exists()
    
    return JsonResponse({
        'is_chef': is_chef,
        'has_pending_request': has_pending_request
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_stripe_status(request, chef_id):
    """
    Public endpoint to check if a chef can accept payments.
    Returns customer-safe information about payment capability without exposing sensitive data.
    
    Response format:
    {
        "can_accept_payments": boolean,
        "has_account": boolean,
        "is_active": boolean,
        "disabled_reason": string or null,
        "message": string
    }
    """
    try:
        # Get the chef
        chef = get_object_or_404(Chef, id=chef_id)
        
        # Check if chef is on break (business logic)
        if chef.is_on_break:
            return Response({
                'can_accept_payments': False,
                'has_account': True,  # Assume they have account, just on break
                'is_active': False,
                'disabled_reason': 'chef_on_break',
                'message': 'This chef is temporarily not accepting orders.'
            })
        
        # Check if chef has a Stripe account
        try:
            stripe_account = StripeConnectAccount.objects.get(chef=chef)
            has_account = True
            
            # Optionally sync with Stripe to get real-time status
            # Only do this if we want to check live status (adds latency)
            try:
                account_info = stripe.Account.retrieve(stripe_account.stripe_account_id)
                
                # Determine if account is fully active
                is_fully_active = bool(
                    getattr(account_info, 'charges_enabled', False) and
                    getattr(account_info, 'details_submitted', False) and
                    getattr(account_info, 'payouts_enabled', False)
                )
                
                # Update local database if status changed
                if stripe_account.is_active != is_fully_active:
                    stripe_account.is_active = is_fully_active
                    stripe_account.save(update_fields=['is_active'])
                
                # Get disabled reason if any
                disabled_reason = getattr(account_info.requirements, 'disabled_reason', None) if hasattr(account_info, 'requirements') else None
                
                # Determine customer-facing message
                if is_fully_active:
                    message = 'This chef is ready to accept orders!'
                elif disabled_reason:
                    # Provide user-friendly messages based on disabled_reason
                    reason_messages = {
                        'requirements.past_due': 'This chef is currently setting up payments. Please check back soon.',
                        'requirements.pending_verification': 'This chef is completing payment verification. Please check back soon.',
                        'listed': 'Payment setup is in progress for this chef.',
                        'rejected.fraud': 'This chef is not available for orders at this time.',
                        'rejected.terms_of_service': 'This chef is not available for orders at this time.',
                        'rejected.other': 'This chef is not available for orders at this time.',
                        'under_review': 'This chef\'s payment setup is under review. Please check back soon.',
                    }
                    message = reason_messages.get(disabled_reason, 'This chef is setting up payments. Please check back soon.')
                else:
                    message = 'This chef is setting up payments. Please check back soon.'
                
                return Response({
                    'can_accept_payments': is_fully_active,
                    'has_account': has_account,
                    'is_active': is_fully_active,
                    'disabled_reason': disabled_reason,
                    'message': message
                })
                
            except stripe.error.StripeError as e:
                # If Stripe API fails, fall back to database status
                logger.warning(f"Stripe API error for chef {chef_id}: {str(e)}")
                return Response({
                    'can_accept_payments': stripe_account.is_active,
                    'has_account': has_account,
                    'is_active': stripe_account.is_active,
                    'disabled_reason': None,
                    'message': 'This chef is ready to accept orders!' if stripe_account.is_active else 'This chef is setting up payments. Please check back soon.'
                })
                
        except StripeConnectAccount.DoesNotExist:
            # Chef has no Stripe account yet
            return Response({
                'can_accept_payments': False,
                'has_account': False,
                'is_active': False,
                'disabled_reason': 'no_account',
                'message': 'This chef is setting up payments. Please check back soon.'
            })
            
    except Exception as e:
        logger.error(f"Error checking stripe status for chef {chef_id}: {str(e)}")
        return Response({
            'error': 'Unable to check payment status at this time.',
            'can_accept_payments': False,
            'has_account': False,
            'is_active': False,
            'disabled_reason': 'error',
            'message': 'Unable to check payment status at this time. Please try again later.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_chef_request(request):
    """
    Submit a new chef request or update an existing one
    """
    try:
        # Validate required fields
        required_fields = ['experience', 'bio', 'city', 'country']
        missing_fields = [field for field in required_fields if not request.data.get(field)]

        if missing_fields:
            # Filter out file objects to avoid JSON serialization errors
            safe_data = {k: v for k, v in request.data.items() if not hasattr(v, 'read')}
            return JsonResponse({
                'error': f'Missing required fields: {", ".join(missing_fields)}',
                'required_fields': required_fields,
                'received_data': {
                    'data': safe_data,
                    'post': dict(request.POST),
                    'files': list(request.FILES.keys()) if request.FILES else []
                }
            }, status=400)

        # Use authenticated user from request (more secure than accepting user_id in POST)
        user = request.user
        user_id = user.id
        
        # Check if user is already a chef
        if Chef.objects.filter(user=user).exists():
            return JsonResponse({
                'error': 'User is already a chef',
                'user_id': user_id
            }, status=400)
        
        # Check if user already has a pending request
        existing_request = ChefRequest.objects.filter(user=user).first()
        if existing_request:
            if not existing_request.is_approved:
                return JsonResponse({
                    'error': 'User already has a pending chef request',
                    'request_id': existing_request.id,
                    'user_id': user_id
                }, status=409)
            else:
                chef_request = existing_request
        else:
            chef_request = ChefRequest(user=user)
        
        # Validate and resolve country (accepts code like "US" or full name like "United States")
        country_input = request.data.get('country')
        def _resolve_country_code(value: str):
            if not value:
                return None
            candidate = value.strip()
            # If looks like a 2-letter code and is valid
            if len(candidate) == 2:
                for code, _name in countries:
                    if code.upper() == candidate.upper():
                        return code.upper()
            # Otherwise try name lookup
            for code, name in countries:
                if name.lower() == candidate.lower():
                    return code
            return None

        country_code = _resolve_country_code(country_input)
        if not country_code:
            return JsonResponse({
                'error': 'Invalid country provided. Use ISO code (e.g., "US") or full country name (e.g., "United States").',
                'received_country': country_input
            }, status=400)

        # Ensure city present (already checked above) and persist to user's Address
        city_value = request.data.get('city')
        try:
            address, _created = Address.objects.get_or_create(user=user)
            address.city = city_value
            address.country = country_code
            address.save(update_fields=['city', 'country'])
        except Exception as e:
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": f"Failed to save address info for chef request: {str(e)}", "source":"submit_chef_request", "traceback": traceback.format_exc()})
            return JsonResponse({
                'error': 'Failed to save address info for chef request',
                'details': str(e)
            }, status=500)

        # Update chef request with new data
        try:
            chef_request.experience = request.data.get('experience', '')
            chef_request.bio = request.data.get('bio', '')
            
            # Handle profile pic if provided
            if 'profile_pic' in request.FILES:
                try:
                    profile_pic = request.FILES['profile_pic']
                    
                    # Get file extension
                    file_ext = os.path.splitext(profile_pic.name)[1].lower()
                    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif']
                    
                    # Check either content type or file extension
                    allowed_types = ['image/jpeg', 'image/png', 'image/gif']
                    is_valid_type = (profile_pic.content_type in allowed_types) or (file_ext in allowed_extensions)
                    if not is_valid_type:
                        return JsonResponse({
                            'error': 'Invalid file type',
                            'details': f'File must be a valid image (jpg, jpeg, png, or gif)',
                            'received_type': profile_pic.content_type,
                            'file_extension': file_ext
                        }, status=400)
                    
                    # Validate file size (max 5MB)
                    if profile_pic.size > 5 * 1024 * 1024:
                        return JsonResponse({
                            'error': 'File too large',
                            'details': 'Profile picture must be less than 5MB',
                            'received_size': profile_pic.size
                        }, status=400)
                    
                    chef_request.profile_pic = profile_pic
                except Exception as e:
                    # n8n traceback
                    n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
                    requests.post(n8n_traceback_url, json={"error": f"Failed to process profile picture", "source":"submit_chef_request", "traceback": traceback.format_exc()})
                    return JsonResponse({
                        'error': 'Failed to process profile picture',
                        'details': str(e)
                    }, status=400)
            
            chef_request.save()
            
        except Exception as e:
            # n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": f"Failed to save chef request", "source":"submit_chef_request", "traceback": traceback.format_exc()})
            return JsonResponse({
                'error': 'Failed to save chef request',
                'details': str(e)
            }, status=500)
        
        # Handle postal codes (use provided country)
        postal_codes = request.data.get('postal_codes', [])
        # Ensure postal_codes is a list
        if not isinstance(postal_codes, list):
            postal_codes = [postal_codes] if postal_codes else []
        
        # Handle selected area IDs (from ServiceAreaPicker)
        selected_area_ids = request.data.get('selected_area_ids', [])
        if isinstance(selected_area_ids, str):
            try:
                import json
                selected_area_ids = json.loads(selected_area_ids)
            except:
                selected_area_ids = []
        
        processed_codes = []
        failed_codes = []
        processed_areas = []
        
        try:
            from local_chefs.models import PostalCode, AdministrativeArea
            # Clear existing postal codes
            chef_request.requested_postalcodes.clear()
            
            # Process selected areas - add all postal codes from those areas
            if selected_area_ids:
                for area_id in selected_area_ids:
                    try:
                        area = AdministrativeArea.objects.get(id=area_id)
                        area_postal_codes = area.get_all_postal_codes()
                        for pc in area_postal_codes:
                            chef_request.requested_postalcodes.add(pc)
                        processed_areas.append({
                            'id': area_id, 
                            'name': area.name,
                            'postal_code_count': area_postal_codes.count()
                        })
                    except AdministrativeArea.DoesNotExist:
                        logger.warning(f"Area {area_id} not found")
                    except Exception as e:
                        logger.error(f"Error processing area {area_id}: {e}")
            
            # Also process individual postal codes
            if postal_codes:
                for code in postal_codes:
                    try:
                        # Normalize and get/create per country
                        postal_code, _created_pc = PostalCode.get_or_create_normalized(code, country_code)
                        chef_request.requested_postalcodes.add(postal_code)
                        processed_codes.append(code)
                    except Exception as e:
                        # n8n traceback
                        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
                        requests.post(n8n_traceback_url, json={"error": f"Error processing postal code {code}: {str(e)}", "source":"submit_chef_request", "traceback": traceback.format_exc()})
                        failed_codes.append({'code': code, 'error': str(e)})
            
            if failed_codes:
                logger.error(f"Some postal codes failed: {failed_codes}")
            
        except Exception as e:
            # n8n traceback
            n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
            requests.post(n8n_traceback_url, json={"error": f"Failed to process postal codes", "source":"submit_chef_request", "traceback": traceback.format_exc()})
            return JsonResponse({
                'error': 'Failed to process postal codes',
                'details': str(e),
                'processed_codes': processed_codes,
                'failed_codes': failed_codes
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'message': 'Chef request submitted successfully',
            'request_id': chef_request.id,
            'user_id': user_id,
            'processed_postal_codes': processed_codes,
            'processed_areas': processed_areas,
            'total_postal_codes': chef_request.requested_postalcodes.count(),
            'profile_pic_saved': 'profile_pic' in request.FILES
        })
        
    except Exception as e:
        # n8n traceback
        n8n_traceback_url = os.getenv("N8N_TRACEBACK_URL")
        requests.post(n8n_traceback_url, json={"error": f"Unexpected error in submit_chef_request: {str(e)}", "source":"submit_chef_request", "traceback": traceback.format_exc()})
        return JsonResponse({
            'error': 'An unexpected error occurred',
            'details': str(e),
            'request_data': dict(request.data)
        }, status=500)


# React API for chef profile and photos
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_chef_profile(request):
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)
    # Ensure user is in chef mode and approved
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return Response({'detail': 'Switch to chef mode to access profile'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Switch to chef mode to access profile'}, status=status.HTTP_403_FORBIDDEN)
    # Ignore any stray user_id in query/body
    if 'user_id' in request.query_params or 'user_id' in request.data:
        pass
    serializer = ChefPublicSerializer(chef, context={'request': request, 'include_all_photos': True})
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def me_update_profile(request):
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)
    # Ensure user is in chef mode and approved
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return Response({'detail': 'Switch to chef mode to update profile'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Switch to chef mode to update profile'}, status=status.HTTP_403_FORBIDDEN)
    # Ignore any stray user_id in query/body
    if 'user_id' in request.query_params or 'user_id' in request.data:
        pass
    serializer = ChefMeUpdateSerializer(chef, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(ChefPublicSerializer(chef, context={'request': request}).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def me_upload_photo(request):
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)
    # Ensure user is in chef mode and approved
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return Response({'detail': 'Switch to chef mode to upload photos'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Switch to chef mode to upload photos'}, status=status.HTTP_403_FORBIDDEN)
    # Ignore any stray user_id in query/body
    if 'user_id' in request.query_params or 'user_id' in request.data:
        pass

    # Pass chef to form so it can filter dish/meal choices
    form = ChefPhotoForm(request.POST, request.FILES, chef=chef)
    if not form.is_valid():
        return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

    photo = form.save(commit=False)
    photo.chef = chef
    if 'is_public' not in request.data:
        photo.is_public = True
    if photo.is_featured:
        ChefPhoto.objects.filter(chef=chef, is_featured=True).update(is_featured=False)
    photo.save()
    
    # Return enhanced serializer with all new fields
    return Response(GalleryPhotoSerializer(photo, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def me_delete_photo(request, photo_id):
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)
    # Ensure user is in chef mode and approved
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return Response({'detail': 'Switch to chef mode to delete photos'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Switch to chef mode to delete photos'}, status=status.HTTP_403_FORBIDDEN)
    photo = get_object_or_404(ChefPhoto, id=photo_id, chef=chef)
    photo.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def me_set_break(request):
    """
    Toggle a chef's break status. When enabling break, cancel all upcoming events and refund paid orders.

    Request JSON:
    - is_on_break: bool (required)
    - reason: str (optional; defaults to "Chef is on break")

    Response JSON (when enabling break):
    - is_on_break: true
    - cancelled_events: int
    - orders_cancelled: int
    - refunds_processed: int
    - refunds_failed: int
    - errors: [str]
    """
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)

    # Ensure user is in chef mode and approved
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return Response({'detail': 'Switch to chef mode to modify break status'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Switch to chef mode to modify break status'}, status=status.HTTP_403_FORBIDDEN)

    is_on_break = request.data.get('is_on_break', None)
    if is_on_break is None:
        return Response({'error': 'is_on_break is required'}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(is_on_break, bool):
        return Response({'error': 'is_on_break must be a boolean'}, status=status.HTTP_400_BAD_REQUEST)

    reason = request.data.get('reason') or 'Chef is going on break'

    # Turning OFF break: just flip the flag
    if is_on_break is False:
        chef.is_on_break = False
        chef.save(update_fields=['is_on_break'])
        return Response({'is_on_break': False})

    # Turning ON break: set flag, then cancel upcoming events + refund
    chef.is_on_break = True
    chef.save(update_fields=['is_on_break'])

    today = timezone.now().date()
    # Future/present events not already finalized
    events_qs = (
        ChefMealEvent.objects
        .filter(chef=chef)
        .exclude(status__in=[STATUS_CANCELLED, STATUS_COMPLETED])
        .filter(event_date__gte=today)
        .order_by('event_date', 'event_time')
    )

    cancelled_events = 0
    orders_cancelled = 0
    refunds_processed = 0
    refunds_failed = 0
    errors = []

    for event in events_qs:
        try:
            with transaction.atomic():
                # Cancel all active orders on this event
                orders = ChefMealOrder.objects.select_for_update().filter(
                    meal_event=event,
                    status__in=[STATUS_PLACED, STATUS_CONFIRMED]
                )

                for order in orders:
                    prev_status = order.status
                    order.status = STATUS_CANCELLED
                    # Non-persistent attribute used by some email templates; safe if absent
                    try:
                        order.cancellation_reason = f'Event cancelled by chef: {reason}'
                    except Exception:
                        pass
                    order.save(update_fields=['status'])
                    orders_cancelled += 1

                    # If previously confirmed and paid, refund
                    if prev_status == STATUS_CONFIRMED and order.stripe_payment_intent_id:
                        try:
                            refund = stripe.Refund.create(payment_intent=order.stripe_payment_intent_id)
                            # Persist refund id if field exists
                            try:
                                order.stripe_refund_id = refund.id
                                order.save(update_fields=['stripe_refund_id'])
                            except Exception:
                                pass
                            # Log payment
                            try:
                                PaymentLog.objects.create(
                                    chef_meal_order=order,
                                    user=order.customer,
                                    chef=chef,
                                    action='refund',
                                    amount=(order.price_paid or 0) * (order.quantity or 1),
                                    stripe_id=refund.id,
                                    status='succeeded',
                                    details={'reason': 'Chef break – bulk cancellation'},
                                )
                            except Exception:
                                pass
                            # Notify user
                            try:
                                from meals.email_service import (
                                    send_refund_notification_email,
                                    send_order_cancellation_email,
                                )
                                send_refund_notification_email(order.id)
                                send_order_cancellation_email(order.id)
                            except Exception:
                                pass
                            refunds_processed += 1
                        except Exception as e:
                            refunds_failed += 1
                            errors.append(f"Order {order.id} refund failed: {str(e)}")
                            # Still send cancellation email
                            try:
                                from meals.email_service import send_order_cancellation_email
                                send_order_cancellation_email(order.id)
                            except Exception:
                                pass

                # Finally, cancel the event itself
                event.status = STATUS_CANCELLED
                event.cancellation_reason = reason if hasattr(event, 'cancellation_reason') else getattr(event, 'cancellation_reason', None)
                event.cancellation_date = timezone.now() if hasattr(event, 'cancellation_date') else getattr(event, 'cancellation_date', None)
                event.save(update_fields=['status'])
                cancelled_events += 1
        except Exception as e:
            errors.append(f"Event {event.id} cancellation error: {str(e)}")

    return Response({
        'is_on_break': True,
        'cancelled_events': cancelled_events,
        'orders_cancelled': orders_cancelled,
        'refunds_processed': refunds_processed,
        'refunds_failed': refunds_failed,
        'errors': errors,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def me_set_live(request):
    """
    Toggle a chef's live status (public visibility).
    Chef must have an active Stripe account to go live.

    Request JSON:
    - is_live: bool (required)

    Response JSON:
    - is_live: bool
    - error: str (if validation fails)
    - message: str (user-friendly error message)
    """
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)

    # Ensure user is in chef mode
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return Response({'detail': 'Switch to chef mode'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Switch to chef mode'}, status=status.HTTP_403_FORBIDDEN)

    is_live = request.data.get('is_live', None)
    if is_live is None:
        return Response({'error': 'is_live is required'}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(is_live, bool):
        return Response({'error': 'is_live must be a boolean'}, status=status.HTTP_400_BAD_REQUEST)

    # Going offline is always allowed
    if is_live is False:
        chef.is_live = False
        chef.save(update_fields=['is_live'])
        return Response({'is_live': False})

    # MEHKO compliance check (only if chef has set a county, indicating MEHKO intent)
    if chef.county:
        eligible, missing = chef.check_mehko_eligibility()
        if not eligible:
            return Response({
                'error': 'mehko_incomplete',
                'missing': missing,
                'message': 'Complete MEHKO requirements before going live.'
            }, status=status.HTTP_400_BAD_REQUEST)

    # Going live requires active Stripe account
    try:
        stripe_account = StripeConnectAccount.objects.get(chef=chef)
        if not stripe_account.is_active:
            return Response({
                'error': 'stripe_not_active',
                'message': 'Complete your Stripe setup before going live.'
            }, status=status.HTTP_400_BAD_REQUEST)
    except StripeConnectAccount.DoesNotExist:
        return Response({
            'error': 'stripe_not_connected',
            'message': 'Connect your Stripe account before going live.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Set live
    chef.is_live = True
    chef.save(update_fields=['is_live'])

    return Response({'is_live': True})


PUBLIC_PHOTO_PREFETCH = Prefetch(
    'photos',
    queryset=ChefPhoto.objects.filter(is_public=True).order_by('-is_featured', '-created_at'),
    to_attr='public_photos',
)


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_public(request, chef_id):
    chef = get_object_or_404(
        Chef.objects.select_related('user').prefetch_related('serving_postalcodes', PUBLIC_PHOTO_PREFETCH),
        id=chef_id,
    )
    if not chef.is_verified or not chef.is_live:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    # Ensure approved – presence of Chef row generally indicates approval; optionally check UserRole
    try:
        user_role = UserRole.objects.get(user=chef.user)
        if not user_role.is_chef:
            return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    serializer = ChefPublicSerializer(chef, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_public_by_username(request, slug):
    chef = (
        Chef.objects.select_related('user')
        .prefetch_related('serving_postalcodes', PUBLIC_PHOTO_PREFETCH)
        .filter(user__username__iexact=slug)
        .first()
    )
    if not chef:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    if not chef.is_verified or not chef.is_live:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        user_role = UserRole.objects.get(user=chef.user)
        if not user_role.is_chef:
            return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    serializer = ChefPublicSerializer(chef, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_lookup_by_username(request, username):
    chef = Chef.objects.filter(user__username__iexact=username).first()
    if not chef:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        user_role = UserRole.objects.get(user=chef.user)
        if not user_role.is_chef:
            return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'id': chef.user.id, 'chef_id': chef.id})


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_public_directory(request):
    from django.db.models import Count, Q
    queryset = Chef.objects.select_related('user').prefetch_related('serving_postalcodes', PUBLIC_PHOTO_PREFETCH)

    # Only approved and live chefs (not on break)
    queryset = queryset.filter(user__userrole__is_chef=True, is_verified=True, is_live=True)

    q = request.query_params.get('q')
    serves_postal = request.query_params.get('serves_postal')
    country = request.query_params.get('country')
    ordering = request.query_params.get('ordering')

    if q:
        queryset = queryset.filter(
            Q(user__username__icontains=q) |
            Q(serving_postalcodes__code__icontains=q) |
            Q(serving_postalcodes__display_code__icontains=q)
        )

    if serves_postal:
        from shared.services.location_service import LocationService
        normalized = LocationService.normalize(serves_postal)
        queryset = queryset.filter(serving_postalcodes__code=normalized)

    if country:
        queryset = queryset.filter(serving_postalcodes__country=country)

    # MEHKO county gating: exclude MEHKO-active chefs in non-approved counties
    from chefs.constants import MEHKO_APPROVED_COUNTIES
    queryset = queryset.exclude(
        Q(mehko_active=True) & ~Q(county__in=MEHKO_APPROVED_COUNTIES)
    )

    queryset = queryset.distinct()

    if ordering == 'popular':
        queryset = queryset.annotate(num_events=Count('meal_events')).order_by('-num_events', '-id')
    elif ordering == 'recent':
        queryset = queryset.order_by('-id')
    else:
        # Ensure deterministic ordering for pagination
        queryset = queryset.order_by('id')

    # Pagination
    from rest_framework.pagination import PageNumberPagination
    paginator = PageNumberPagination()
    paginator.page_size = 12
    page_size = request.query_params.get('page_size')
    if page_size:
        try:
            paginator.page_size = max(1, min(100, int(page_size)))
        except Exception:
            paginator.page_size = 12
    page = paginator.paginate_queryset(queryset, request)
    serializer = ChefPublicSerializer(page or queryset, many=True, context={'request': request})
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chef_serves_my_area(request, chef_id):
    from shared.services.location_service import LocationService
    
    try:
        chef = Chef.objects.get(id=chef_id)
    except Chef.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)

    location = LocationService.get_user_location(request.user)
    if not location.is_complete:
        return Response({
            'serves': False,
            'detail': 'Missing user address country or postal code'
        }, status=status.HTTP_400_BAD_REQUEST)

    serves = ChefPostalCode.objects.filter(
        chef=chef,
        postal_code__code=location.normalized_postal,
        postal_code__country=location.country
    ).exists()

    return Response({
        'serves': serves,
        'chef_id': chef.id,
        'user_postal_code': location.display_postal,
        'user_country': location.country
    })


# ============================================================================
# CHEF GALLERY ENDPOINTS - Public API for chef photo galleries
# ============================================================================


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_gallery_photos(request, username):
    """
    Get paginated list of photos for a chef's gallery.
    Supports filtering by tags, category, dish_id, meal_id and ordering.
    
    Query params:
    - page: page number (default: 1)
    - page_size: items per page (default: 12, max: 50)
    - tags: comma-separated tags to filter by
    - category: filter by category (appetizer, main, dessert, etc.)
    - dish_id: filter by specific dish
    - meal_id: filter by specific meal
    - ordering: sort order (default: -created_at)
    """
    # Get chef by username
    try:
        chef = Chef.objects.select_related('user').get(user__username__iexact=username)
    except Chef.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Verify chef is approved
    try:
        user_role = UserRole.objects.get(user=chef.user)
        if not user_role.is_chef:
            return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Start with base queryset - only public photos
    queryset = ChefPhoto.objects.filter(
        chef=chef,
        is_public=True
    ).select_related('dish', 'meal')
    
    # Apply filters
    tags_param = request.query_params.get('tags')
    if tags_param:
        # Filter photos that contain any of the specified tags
        tags_list = [tag.strip() for tag in tags_param.split(',') if tag.strip()]
        if tags_list:
            # Use JSONField contains lookup
            from django.db.models import Q
            tag_queries = Q()
            for tag in tags_list:
                tag_queries |= Q(tags__contains=[tag])
            queryset = queryset.filter(tag_queries)
    
    category = request.query_params.get('category')
    if category:
        queryset = queryset.filter(category=category)
    
    dish_id = request.query_params.get('dish_id')
    if dish_id:
        try:
            queryset = queryset.filter(dish_id=int(dish_id))
        except (ValueError, TypeError):
            pass
    
    meal_id = request.query_params.get('meal_id')
    if meal_id:
        try:
            queryset = queryset.filter(meal_id=int(meal_id))
        except (ValueError, TypeError):
            pass
    
    # Apply ordering
    ordering = request.query_params.get('ordering', '-created_at')
    valid_orderings = ['-created_at', 'created_at', '-updated_at', 'updated_at', 'title', '-title']
    if ordering in valid_orderings:
        queryset = queryset.order_by(ordering)
    else:
        queryset = queryset.order_by('-created_at')
    
    # Ensure consistent ordering for pagination
    if 'id' not in ordering and '-id' not in ordering:
        queryset = queryset.order_by(ordering, '-id')
    
    # Paginate
    from rest_framework.pagination import PageNumberPagination
    paginator = PageNumberPagination()
    
    # Get page_size from query params with validation
    page_size = request.query_params.get('page_size', '12')
    try:
        paginator.page_size = max(1, min(50, int(page_size)))
    except (ValueError, TypeError):
        paginator.page_size = 12
    
    page = paginator.paginate_queryset(queryset, request)
    serializer = GalleryPhotoSerializer(page or queryset, many=True, context={'request': request})
    
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_gallery_stats(request, username):
    """
    Get statistics for a chef's gallery including total photos,
    category breakdown, popular tags, and date range.
    """
    # Get chef by username
    try:
        chef = Chef.objects.select_related('user').get(user__username__iexact=username)
    except Chef.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Verify chef is approved
    try:
        user_role = UserRole.objects.get(user=chef.user)
        if not user_role.is_chef:
            return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get public photos only
    photos = ChefPhoto.objects.filter(chef=chef, is_public=True)
    
    # Total count
    total_photos = photos.count()
    
    # Category breakdown
    from django.db.models import Count
    category_counts = {}
    category_data = photos.values('category').annotate(count=Count('id'))
    for item in category_data:
        cat = item['category'] or 'other'
        category_counts[cat] = item['count']
    
    # Tags aggregation
    from collections import Counter
    all_tags = []
    for photo in photos.exclude(tags__isnull=True).exclude(tags=[]):
        if isinstance(photo.tags, list):
            all_tags.extend(photo.tags)
    
    tag_counter = Counter(all_tags)
    # Get top 20 tags
    top_tags = [
        {'name': tag, 'count': count}
        for tag, count in tag_counter.most_common(20)
    ]
    
    # Date range
    date_range = {}
    if total_photos > 0:
        first_photo = photos.order_by('created_at').first()
        latest_photo = photos.order_by('-created_at').first()
        if first_photo and latest_photo:
            date_range = {
                'first_photo': first_photo.created_at.isoformat(),
                'latest_photo': latest_photo.created_at.isoformat(),
            }
    
    stats_data = {
        'total_photos': total_photos,
        'categories': category_counts,
        'tags': top_tags,
        'date_range': date_range,
    }
    
    serializer = GalleryStatsSerializer(stats_data)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def chef_gallery_photo_detail(request, username, photo_id):
    """
    Get detailed information about a specific photo in a chef's gallery.
    Optional endpoint for photo detail view with navigation.
    """
    # Get chef by username
    try:
        chef = Chef.objects.select_related('user').get(user__username__iexact=username)
    except Chef.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Verify chef is approved
    try:
        user_role = UserRole.objects.get(user=chef.user)
        if not user_role.is_chef:
            return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    except UserRole.DoesNotExist:
        return Response({'detail': 'Chef not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get the photo
    try:
        photo = ChefPhoto.objects.select_related('dish', 'meal').get(
            id=photo_id,
            chef=chef,
            is_public=True
        )
    except ChefPhoto.DoesNotExist:
        return Response({'detail': 'Photo not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Serialize the photo
    serializer = GalleryPhotoSerializer(photo, context={'request': request})
    data = serializer.data
    
    # Add navigation (previous/next photo IDs)
    # Get previous photo (older)
    previous_photo = ChefPhoto.objects.filter(
        chef=chef,
        is_public=True,
        created_at__lt=photo.created_at
    ).order_by('-created_at').first()
    
    # Get next photo (newer)
    next_photo = ChefPhoto.objects.filter(
        chef=chef,
        is_public=True,
        created_at__gt=photo.created_at
    ).order_by('created_at').first()
    
    data['navigation'] = {
        'previous_photo_id': previous_photo.id if previous_photo else None,
        'next_photo_id': next_photo.id if next_photo else None,
    }
    
    return Response(data)


# ═══════════════════════════════════════════════════════════════════════════════
# PROACTIVE INSIGHTS API
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chef_proactive_insights(request):
    """
    Get proactive insights for the current chef.
    
    Query params:
    - limit: Max insights to return (default: 10, max: 20)
    - type: Filter by insight type (optional)
    - include_read: Include already-read insights (default: false)
    
    Response:
    {
        "insights": [...],
        "unread_count": int,
        "total_count": int
    }
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    # Get chef
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_403_FORBIDDEN)
    
    # Parse query params
    limit = min(max(int(request.query_params.get('limit', 10)), 1), 20)
    insight_type = request.query_params.get('type', None)
    include_read = request.query_params.get('include_read', 'false').lower() == 'true'
    
    # Build query
    now = timezone.now()
    queryset = ChefProactiveInsight.objects.filter(
        chef=chef,
        is_dismissed=False
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    
    if not include_read:
        queryset = queryset.filter(is_read=False)
    
    if insight_type:
        queryset = queryset.filter(insight_type=insight_type)
    
    # Order by priority, then recency
    from django.db.models import Case, When, IntegerField
    priority_order = Case(
        When(priority='high', then=1),
        When(priority='medium', then=2),
        When(priority='low', then=3),
        output_field=IntegerField(),
    )
    
    insights = queryset.annotate(
        priority_rank=priority_order
    ).order_by('priority_rank', '-created_at').select_related('customer', 'lead')[:limit]
    
    # Format response
    results = []
    for insight in insights:
        family_name = None
        if insight.customer:
            family_name = f"{insight.customer.first_name} {insight.customer.last_name}".strip() or insight.customer.username
        elif insight.lead:
            family_name = f"{insight.lead.first_name} {insight.lead.last_name}".strip()
        
        results.append({
            'id': insight.id,
            'type': insight.insight_type,
            'type_display': insight.get_insight_type_display(),
            'title': insight.title,
            'content': insight.content,
            'priority': insight.priority,
            'family': family_name,
            'family_id': insight.customer_id or insight.lead_id,
            'family_type': 'customer' if insight.customer_id else 'lead' if insight.lead_id else None,
            'is_read': insight.is_read,
            'created_at': insight.created_at.isoformat(),
            'expires_at': insight.expires_at.isoformat() if insight.expires_at else None,
            'action_data': insight.action_data,
        })
    
    # Get counts
    unread_count = ChefProactiveInsight.get_count_for_chef(chef)
    total_count = ChefProactiveInsight.objects.filter(
        chef=chef,
        is_dismissed=False
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()
    
    return Response({
        'insights': results,
        'unread_count': unread_count,
        'total_count': total_count
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chef_insight_action(request, insight_id):
    """
    Take action on a proactive insight.
    
    Request body:
    {
        "action": "read" | "dismiss" | "act",
        "action_taken": "string (optional, for 'act')"
    }
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    # Get chef
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return Response({'detail': 'Not a chef'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get insight
    try:
        insight = ChefProactiveInsight.objects.get(id=insight_id, chef=chef)
    except ChefProactiveInsight.DoesNotExist:
        return Response({'detail': 'Insight not found'}, status=status.HTTP_404_NOT_FOUND)
    
    action = request.data.get('action', 'read')
    
    if action == 'read':
        insight.mark_read()
        message = 'Insight marked as read'
    elif action == 'dismiss':
        insight.dismiss()
        message = 'Insight dismissed'
    elif action == 'act':
        action_taken = request.data.get('action_taken', '')
        insight.mark_actioned(action_taken=action_taken)
        message = 'Insight marked as actioned'
    else:
        return Response({'detail': f'Unknown action: {action}'}, status=status.HTTP_400_BAD_REQUEST)
    
    return Response({
        'status': 'success',
        'message': message,
        'insight_id': insight.id
    })
