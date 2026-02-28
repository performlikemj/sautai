import json
import logging
import stripe
from datetime import datetime, timedelta, timezone as tz
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.utils.dateparse import parse_date, parse_time
from django.utils import timezone
from django.core.exceptions import ValidationError

from chefs.models import Chef
from custom_auth.models import CustomUser
from local_chefs.geo import ensure_postal_code_coordinates
from crm.models import Lead, LeadInteraction
from crm.service import create_or_update_lead_for_user
from .models import (
    ChefServiceOffering,
    ChefServicePriceTier,
    ChefServiceOrder,
    ChefCustomerConnection,
)
from .serializers import (
    ChefServiceOfferingSerializer,
    ChefServicePriceTierSerializer,
    ChefServiceOrderSerializer,
    PublicChefServiceOfferingSerializer,
    ChefCustomerConnectionSerializer,
)
from .payments import create_service_checkout_session
from .tasks import sync_pending_service_tiers, _ensure_product
from django.conf import settings


logger = logging.getLogger(__name__)


def _sync_tier_to_stripe(tier):
    """
    Synchronously sync a tier to Stripe.
    
    Creates/updates the Stripe Product and Price for the given tier.
    Updates tier fields (stripe_price_id, price_sync_status, etc.) in place.
    
    Args:
        tier: ChefServicePriceTier instance (must be saved first to have an ID)
        
    Returns:
        bool: True if sync succeeded, False if it failed
    """
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Ensure the offering has a Stripe product
        product_id = _ensure_product(tier.offering)
        
        # Build Price creation kwargs
        kwargs = dict(
            product=product_id,
            currency=tier.currency,
            unit_amount=int(tier.desired_unit_amount_cents)
        )
        if tier.is_recurring:
            kwargs['recurring'] = {'interval': tier.recurrence_interval or 'week'}
        
        # Create the Stripe Price with idempotency key
        idempotency_key = f"service_tier_{tier.id}_{tier.desired_unit_amount_cents}_{'rec' if tier.is_recurring else 'ot'}"
        price = stripe.Price.create(**kwargs, idempotency_key=idempotency_key)
        
        # Update tier with success
        tier.stripe_price_id = price.id
        tier.price_sync_status = 'success'
        tier.price_synced_at = datetime.now(tz.utc)
        tier.last_price_sync_error = None
        tier.save(update_fields=['stripe_price_id', 'price_sync_status', 'price_synced_at', 'last_price_sync_error'])
        
        return True
        
    except Exception as e:
        # Record the error on the tier
        tier.price_sync_status = 'error'
        tier.last_price_sync_error = str(e)[:500]
        tier.save(update_fields=['price_sync_status', 'last_price_sync_error'])
        logger.exception("Stripe sync failed for tier %s", tier.id)
        return False


def _haversine_miles(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2

    R = 3958.8  # Earth radius in miles
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def _normalize_country(code):
    if not code:
        return 'US'
    return str(getattr(code, 'code', code)).upper()


def _resolve_viewer_coordinates(request):
    postal_code = request.query_params.get('postal_code')
    country = request.query_params.get('country')
    if postal_code:
        postal_row = ensure_postal_code_coordinates(postal_code, country or 'US')
        if postal_row and postal_row.latitude is not None and postal_row.longitude is not None:
            return float(postal_row.latitude), float(postal_row.longitude)

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None

    address = getattr(user, 'address', None)
    if not address:
        return None

    if address.latitude is not None and address.longitude is not None:
        return float(address.latitude), float(address.longitude)

    # Try normalized_postalcode first (preferred), then fall back to original_postalcode
    postal_code = getattr(address, 'normalized_postalcode', None) or getattr(address, 'original_postalcode', None)
    country = getattr(address, 'country', None)
    if postal_code and country:
        postal_row = ensure_postal_code_coordinates(postal_code, country)
        if postal_row and postal_row.latitude is not None and postal_row.longitude is not None:
            return float(postal_row.latitude), float(postal_row.longitude)

    return None


def _chef_coordinates(chef):
    # Prefer existing geocoded service postal codes
    postal = chef.serving_postalcodes.filter(latitude__isnull=False, longitude__isnull=False).first()
    if postal:
        return float(postal.latitude), float(postal.longitude)

    # Attempt to geocode the first service postal code
    any_postal = chef.serving_postalcodes.first()
    if any_postal:
        ensured = ensure_postal_code_coordinates(any_postal.code, any_postal.country)
        if ensured and ensured.latitude is not None and ensured.longitude is not None:
            return float(ensured.latitude), float(ensured.longitude)

    # Fall back to chef's address
    address = getattr(chef.user, 'address', None)
    if address:
        if address.latitude is not None and address.longitude is not None:
            return float(address.latitude), float(address.longitude)
        postal_code = getattr(address, 'normalized_postalcode', None) or getattr(address, 'original_postalcode', None)
        if postal_code and address.country:
            ensured = ensure_postal_code_coordinates(postal_code, address.country)
            if ensured and ensured.latitude is not None and ensured.longitude is not None:
                return float(ensured.latitude), float(ensured.longitude)

    return None


def _get_request_chef_or_403(request):
    chef = Chef.objects.filter(user=request.user).first()
    if not chef:
        return None
    return chef


def _resolve_connection_scope(request):
    chef = Chef.objects.filter(user=request.user).first()
    if chef:
        return 'chef', chef
    return 'customer', getattr(request, 'user', None)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def offerings(request):
    """
    GET: Public discovery with optional filters (chef_id, service_type) but require auth to match existing pattern.
    POST: Create an offering for the authenticated chef.
    """
    if request.method == 'POST':
        if not request.user or not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=401)
        chef = _get_request_chef_or_403(request)
        if not chef:
            return Response({"error": "Only chefs can create offerings"}, status=403)
        data = request.data.copy()
        data['chef'] = chef.id
        serializer = ChefServiceOfferingSerializer(data=data, context={'request': request, 'chef': chef})
        if serializer.is_valid():
            offering = serializer.save(chef=chef)
            return Response(ChefServiceOfferingSerializer(offering).data, status=201)
        return Response(serializer.errors, status=400)

    # GET
    chef_id = request.query_params.get('chef_id')
    service_type = request.query_params.get('service_type')
    qs = ChefServiceOffering.objects.filter(active=True)
    if chef_id:
        qs = qs.filter(chef_id=chef_id)
    if service_type:
        qs = qs.filter(service_type=service_type)
    if request.user and request.user.is_authenticated:
        qs = qs.filter(
            Q(target_customers__isnull=True) | Q(target_customers=request.user)
        )
    else:
        qs = qs.filter(target_customers__isnull=True)
    qs = qs.distinct()
    # Hide offerings without any active tier
    qs = qs.prefetch_related(
        Prefetch('tiers', queryset=ChefServicePriceTier.objects.filter(active=True)),
        'target_customers',
    )
    viewer_coords = _resolve_viewer_coordinates(request)
    results = []
    for off in qs:
        if off.tiers.all().exists():
            if viewer_coords and off.max_travel_miles is not None:
                chef_coords = _chef_coordinates(off.chef)
                if not chef_coords:
                    logger.warning(
                        "Skipping offering %s for chef %s due to missing coordinates",
                        off.id,
                        off.chef_id,
                    )
                    continue
                distance = _haversine_miles(viewer_coords[0], viewer_coords[1], chef_coords[0], chef_coords[1])
                if distance > float(off.max_travel_miles):
                    continue
            results.append(off)
    serializer = PublicChefServiceOfferingSerializer(results, many=True)
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_offering(request, offering_id):
    offering = get_object_or_404(ChefServiceOffering, id=offering_id)
    if offering.chef.user_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    serializer = ChefServiceOfferingSerializer(offering, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_offering(request, offering_id):
    """
    Delete a service offering if it has no associated orders.
    """
    from django.db.models import ProtectedError

    logger = logging.getLogger(__name__)
    offering = get_object_or_404(ChefServiceOffering, id=offering_id)

    if offering.chef.user_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)

    order_count = offering.orders.count()
    if order_count > 0:
        return Response({
            "error": f"Cannot delete this service because it has {order_count} associated order{'s' if order_count > 1 else ''}. Consider deactivating it instead."
        }, status=400)

    try:
        offering.delete()
        return Response(status=204)
    except ProtectedError:
        logger.warning(f"Protected error deleting offering {offering_id}")
        return Response({
            "error": "Cannot delete this service because it has associated orders. Consider deactivating it instead."
        }, status=400)
    except Exception as e:
        logger.exception(f"Failed to delete offering {offering_id}")
        return Response({"error": "Failed to delete service"}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_offerings(request):
    chef = _get_request_chef_or_403(request)
    if not chef:
        return Response({"error": "Only chefs can list their offerings"}, status=403)
    qs = ChefServiceOffering.objects.filter(chef=chef).prefetch_related('tiers', 'target_customers')
    return Response(ChefServiceOfferingSerializer(qs, many=True).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def connections(request):
    role, actor = _resolve_connection_scope(request)
    if request.method == 'GET':
        if role == 'chef' and actor:
            qs = ChefCustomerConnection.objects.filter(chef=actor)
        else:
            qs = ChefCustomerConnection.objects.filter(customer=request.user)
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        qs = qs.select_related('chef__user').order_by('-requested_at')
        serializer = ChefCustomerConnectionSerializer(qs, many=True)
        return Response(serializer.data)

    # POST
    if role == 'chef' and actor:
        customer_id = request.data.get('customer_id')
        if not customer_id:
            logger.warning(
                "customer_id is required for connection requests (chef_user=%s)",
                getattr(request.user, 'id', None),
            )
            return Response({"error": "customer_id is required"}, status=400)
        try:
            customer = CustomUser.objects.get(id=customer_id)
        except CustomUser.DoesNotExist:
            logger.warning(
                "Connection request invalid customer_id=%s (chef_user=%s)",
                customer_id,
                getattr(request.user, 'id', None),
            )
            return Response({"error": "Customer not found"}, status=404)
        chef = actor
        initiator = ChefCustomerConnection.INITIATED_BY_CHEF
    else:
        chef_id = request.data.get('chef_id')
        if not chef_id:
            logger.warning(
                "chef_id is required for connection requests (customer_user=%s)",
                getattr(request.user, 'id', None),
            )
            return Response({"error": "chef_id is required"}, status=400)
        chef = Chef.objects.filter(id=chef_id).first()
        if not chef:
            logger.warning(
                "Connection request invalid chef_id=%s (customer_user=%s)",
                chef_id,
                getattr(request.user, 'id', None),
            )
            return Response({"error": "Chef not found"}, status=404)
        customer = request.user
        initiator = ChefCustomerConnection.INITIATED_BY_CUSTOMER

    if not isinstance(customer, CustomUser):
        return Response({"error": "Only authenticated customers can create connections"}, status=401)

    if chef.user_id == customer.id:
        return Response({"error": "Cannot connect a chef account to itself"}, status=400)

    defaults = {"initiated_by": initiator}
    try:
        connection, created = ChefCustomerConnection.objects.get_or_create(
            chef=chef,
            customer=customer,
            defaults=defaults,
        )
    except Exception:
        logger.exception(
            "Failed to create or fetch connection (chef=%s, customer=%s)",
            chef.id,
            customer.id,
        )
        return Response({"error": "Could not process connection request"}, status=500)
    if not created:
        now = timezone.now()
        connection.initiated_by = initiator
        if connection.status != ChefCustomerConnection.STATUS_PENDING:
            connection.status = ChefCustomerConnection.STATUS_PENDING
        connection.responded_at = None
        connection.ended_at = None
        connection.requested_at = now
        try:
            connection.full_clean()
        except ValidationError as exc:
            logger.warning(
                "Validation error refreshing connection (chef=%s, customer=%s): %s",
                connection.chef_id,
                connection.customer_id,
                exc,
            )
            return Response({"error": exc.message_dict or exc.messages}, status=400)
        try:
            connection.save(update_fields=['initiated_by', 'status', 'responded_at', 'ended_at', 'requested_at'])
        except Exception:
            logger.exception(
                "Failed to save connection refresh (chef=%s, customer=%s)",
                connection.chef_id,
                connection.customer_id,
            )
            return Response({"error": "Could not process connection request"}, status=500)
    serializer = ChefCustomerConnectionSerializer(connection)
    return Response(serializer.data, status=201 if created else 200)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def connection_detail(request, connection_id):
    connection = get_object_or_404(ChefCustomerConnection, id=connection_id)
    user = request.user
    is_chef_party = connection.chef.user_id == user.id
    is_customer_party = connection.customer_id == user.id
    if not (is_chef_party or is_customer_party):
        return Response({"error": "Forbidden"}, status=403)

    action = (request.data or {}).get('action')
    if action not in {"accept", "decline", "end"}:
        logger.warning(
            "Invalid connection action '%s' attempted by user %s on connection %s",
            action,
            getattr(user, 'id', None),
            connection_id,
        )
        return Response({"error": "Invalid action"}, status=400)

    now = timezone.now()

    if action in {"accept", "decline"}:
        if connection.status != ChefCustomerConnection.STATUS_PENDING:
            logger.warning(
                "Connection %s not pending for action '%s' by user %s",
                connection_id,
                action,
                getattr(user, 'id', None),
            )
            return Response({"error": "Only pending connections can be responded to"}, status=400)
        if connection.initiated_by == ChefCustomerConnection.INITIATED_BY_CHEF and is_chef_party:
            logger.warning(
                "Chef %s attempted to respond to their own pending request (connection %s)",
                connection.chef_id,
                connection_id,
            )
            return Response({"error": "Awaiting customer response"}, status=400)
        if connection.initiated_by == ChefCustomerConnection.INITIATED_BY_CUSTOMER and is_customer_party:
            logger.warning(
                "Customer %s attempted to respond to their own pending request (connection %s)",
                connection.customer_id,
                connection_id,
            )
            return Response({"error": "Awaiting chef response"}, status=400)

    if action == 'accept':
        connection.status = ChefCustomerConnection.STATUS_ACCEPTED
        connection.responded_at = now
        connection.ended_at = None
        save_fields = ['status', 'responded_at', 'ended_at']
    elif action == 'decline':
        connection.status = ChefCustomerConnection.STATUS_DECLINED
        connection.responded_at = now
        connection.ended_at = now
        save_fields = ['status', 'responded_at', 'ended_at']
    else:  # end
        if connection.status != ChefCustomerConnection.STATUS_ACCEPTED:
            logger.warning(
                "Attempt to end non-accepted connection %s by user %s",
                connection_id,
                getattr(user, 'id', None),
            )
            return Response({"error": "Only accepted connections can be ended"}, status=400)
        connection.status = ChefCustomerConnection.STATUS_ENDED
        connection.ended_at = now
        save_fields = ['status', 'ended_at']
        if not connection.responded_at:
            connection.responded_at = now
            save_fields.append('responded_at')

    try:
        connection.save(update_fields=save_fields)
    except Exception:
        logger.exception(
            "Failed to persist connection %s state change '%s' by user %s",
            connection_id,
            action,
            getattr(user, 'id', None),
        )
        return Response({"error": "Could not update connection"}, status=500)
    serializer = ChefCustomerConnectionSerializer(connection)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_tier(request, offering_id):
    offering = get_object_or_404(ChefServiceOffering, id=offering_id)
    if offering.chef.user_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    data = request.data.copy()
    # Prevent client from setting stripe_price_id/sync fields
    for forbidden in ('stripe_price_id', 'price_sync_status', 'last_price_sync_error', 'price_synced_at', 'offering'):
        data.pop(forbidden, None)
    serializer = ChefServicePriceTierSerializer(data=data)
    if serializer.is_valid():
        tier = ChefServicePriceTier(
            offering=offering,
            **{k: v for k, v in serializer.validated_data.items()}
        )
        try:
            tier.full_clean()
            # Save tier first (needed for idempotency key)
            tier.price_sync_status = 'pending'
            tier.last_price_sync_error = None
            tier.price_synced_at = None
            tier.save()
            
            # Sync to Stripe synchronously for immediate feedback
            _sync_tier_to_stripe(tier)
            
        except Exception as e:
            return Response({"error": str(e)}, status=400)
        return Response(ChefServicePriceTierSerializer(tier).data, status=201)
    return Response(serializer.errors, status=400)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_tier(request, tier_id):
    tier = get_object_or_404(ChefServicePriceTier, id=tier_id)
    if tier.offering.chef.user_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    # Whitelist updatable fields to prevent mass assignment
    allowed = {
        'household_min', 'household_max', 'currency',
        'is_recurring', 'recurrence_interval', 'active', 'display_label',
        'desired_unit_amount_cents',
    }
    price_related = {'currency', 'is_recurring', 'recurrence_interval', 'desired_unit_amount_cents'}
    touched_price = False
    for field, value in request.data.items():
        if field in allowed:
            setattr(tier, field, value)
            if field in price_related:
                touched_price = True
    try:
        tier.full_clean()
        if touched_price:
            tier.price_sync_status = 'pending'
            tier.last_price_sync_error = None
            tier.price_synced_at = None
        tier.save()
        
        # Sync to Stripe synchronously if price-related fields changed
        if touched_price:
            _sync_tier_to_stripe(tier)
            
    except Exception as e:
        return Response({"error": str(e)}, status=400)
    return Response(ChefServicePriceTierSerializer(tier).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    """
    Create a draft ChefServiceOrder.
    Body: offering_id, household_size, schedule/address; optional tier_id.
    If tier_id not provided, server selects a tier if exactly one tier matches.
    """
    customer = request.user
    offering_id = request.data.get('offering_id')
    household_size = request.data.get('household_size')
    tier_id = request.data.get('tier_id')

    if not offering_id or not household_size:
        return Response({"error": "offering_id and household_size are required"}, status=400)

    offering = get_object_or_404(ChefServiceOffering, id=offering_id, active=True)
    chef = offering.chef

    # Prevent chefs from ordering their own services (money laundering risk)
    if chef.user_id == customer.id:
        return Response({"error": "Chefs cannot order their own services"}, status=400)

    # Resolve tier
    tier = None
    if tier_id:
        tier = get_object_or_404(ChefServicePriceTier, id=tier_id, offering=offering, active=True)
    else:
        size = int(household_size)
        tiers = offering.tiers.filter(active=True)
        candidates = []
        for t in tiers:
            max_sz = t.household_max or 10**9
            if t.household_min <= size <= max_sz:
                candidates.append(t)
        if len(candidates) == 1:
            tier = candidates[0]
        else:
            return Response({"error": "Could not uniquely determine a tier for the given household size"}, status=400)

    # Parse and validate schedule types
    sd = request.data.get('service_date')
    st = request.data.get('service_start_time')
    parsed_date = parse_date(sd) if isinstance(sd, str) else sd
    parsed_time = parse_time(st) if isinstance(st, str) else st

    # Address ownership (if provided)
    address_id = request.data.get('address_id')
    if address_id:
        from custom_auth.models import Address
        try:
            addr = Address.objects.get(id=address_id)
            if addr.user_id != request.user.id:
                return Response({"error": "Invalid address for this user"}, status=403)
        except Address.DoesNotExist:
            return Response({"error": "Address not found"}, status=404)

    # Duration
    dur = request.data.get('duration_minutes')
    duration = None
    if dur is not None and dur != "":
        try:
            duration = int(dur)
            if duration <= 0:
                duration = None
        except Exception:
            duration = None
    if duration is None:
        duration = offering.default_duration_minutes

    # --- MEHKO compliance checks ---
    if chef.mehko_active:
        from chef_services.mehko_limits import check_meal_cap, _get_caps

        # Disclosure acceptance required
        if not getattr(customer, 'mehko_disclosure_accepted_at', None):
            return Response({
                "error": "mehko_disclosure_required",
                "message": "Please review and accept the home kitchen food safety "
                           "disclosures before ordering from a MEHKO chef."
            }, status=400)

        # Same-day ordering constraint (use California time, not server UTC)
        import zoneinfo
        ca_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        ca_today = timezone.now().astimezone(ca_tz).date()
        if parsed_date and parsed_date != ca_today:
            return Response({
                "error": "mehko_same_day",
                "message": "MEHKO orders must be for same-day service "
                           "(food prepared and served same day per California law)."
            }, status=400)
        if not parsed_date:
            parsed_date = ca_today

        # Meal cap check
        cap_result = check_meal_cap(chef, parsed_date)
        if not cap_result['allowed']:
            return Response({
                "error": "mehko_cap_reached",
                "message": "This chef has reached their meal limit for home kitchen operations.",
                "daily_count": cap_result['daily_count'],
                "daily_remaining": cap_result['daily_remaining'],
                "weekly_count": cap_result['weekly_count'],
                "weekly_remaining": cap_result['weekly_remaining'],
            }, status=400)

        # Revenue cap check
        from chef_services.mehko_limits import check_revenue_cap
        order_amount = tier.desired_unit_amount_cents if tier else 0
        rev_result = check_revenue_cap(chef, order_amount_cents=order_amount)
        if not rev_result['under_cap']:
            return Response({
                "error": "mehko_revenue_cap",
                "message": "This chef has reached the annual revenue limit "
                           f"(${rev_result['cap']:,}) for home kitchen operations.",
                "current_revenue": str(rev_result['current_revenue']),
                "cap": rev_result['cap'],
                "percent_used": rev_result['percent_used'],
            }, status=400)

        # Delivery mode enforcement
        delivery_method = request.data.get('delivery_method', 'customer_pickup')
        if delivery_method == 'third_party':
            return Response({
                "error": "mehko_no_third_party",
                "message": "MEHKO orders cannot use third-party delivery "
                           "services per California law."
            }, status=400)
    else:
        delivery_method = request.data.get('delivery_method', 'customer_pickup')

    order = ChefServiceOrder(
        customer=customer,
        chef=chef,
        offering=offering,
        tier=tier,
        household_size=int(household_size),
        service_date=parsed_date,
        service_start_time=parsed_time,
        duration_minutes=duration,
        address_id=address_id,
        special_requests=request.data.get('special_requests', ''),
        schedule_preferences=request.data.get('schedule_preferences'),
        delivery_method=delivery_method,
        charged_amount_cents=tier.desired_unit_amount_cents if tier else 0,
        status='draft',
    )
    try:
        order.full_clean()
        order.save()
    except Exception as e:
        return Response({"error": str(e)}, status=400)

    create_or_update_lead_for_user(
        user=customer,
        chef_user=chef.user,
        source=Lead.Source.WEB,
        offering=offering,
        summary="Created service order",
        details=f"Order #{order.id} created for offering {offering.id}",
        interaction_type=LeadInteraction.InteractionType.MESSAGE,
        interaction_payload={"household_size": household_size, "tier_id": tier.id if tier else None},
    )

    return Response(ChefServiceOrderSerializer(order).data, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_order(request, order_id):
    order = get_object_or_404(ChefServiceOrder, id=order_id)
    if order.customer_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    return Response(ChefServiceOrderSerializer(order).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_order(request, order_id):
    """
    Update a draft order with scheduling details and other information.
    Allows users to add service_date, service_start_time, address, etc. before checkout.
    """
    order = get_object_or_404(ChefServiceOrder, id=order_id)
    if order.customer_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    
    # Only allow updates to draft orders
    if order.status != 'draft':
        return Response({"error": f"Cannot update order with status: {order.status}"}, status=400)
    
    # Parse and update allowed fields
    if 'service_date' in request.data:
        sd = request.data['service_date']
        order.service_date = parse_date(sd) if isinstance(sd, str) else sd
    
    if 'service_start_time' in request.data:
        st = request.data['service_start_time']
        order.service_start_time = parse_time(st) if isinstance(st, str) else st
    
    if 'duration_minutes' in request.data:
        dur = request.data['duration_minutes']
        try:
            duration = int(dur)
            if duration > 0:
                order.duration_minutes = duration
        except (ValueError, TypeError):
            pass
    
    if 'address_id' in request.data:
        address_id = request.data['address_id']
        if address_id:
            from custom_auth.models import Address
            try:
                addr = Address.objects.get(id=address_id)
                if addr.user_id != request.user.id:
                    return Response({"error": "Invalid address for this user"}, status=403)
                order.address = addr
            except Address.DoesNotExist:
                return Response({"error": "Address not found"}, status=404)
    
    if 'special_requests' in request.data:
        order.special_requests = request.data['special_requests']
    
    if 'schedule_preferences' in request.data:
        order.schedule_preferences = request.data['schedule_preferences']
    
    if 'household_size' in request.data:
        try:
            household_size = int(request.data['household_size'])
            if household_size > 0:
                order.household_size = household_size
        except (ValueError, TypeError):
            return Response({"error": "Invalid household_size"}, status=400)
    
    try:
        order.full_clean()
        order.save()
    except Exception as e:
        return Response({"error": str(e)}, status=400)
    
    return Response(ChefServiceOrderSerializer(order).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders(request):
    chef = _get_request_chef_or_403(request)
    if not chef:
        return Response({"error": "Only chefs can view service orders"}, status=403)

    qs = (
        ChefServiceOrder.objects
        .filter(chef=chef)
        .select_related('offering', 'tier', 'customer')
        .order_by('-created_at')
    )
    return Response(ChefServiceOrderSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_customer_orders(request):
    """
    Get service orders for the authenticated customer with filtering and pagination.
    
    Query params:
    - status: 'active' (default), 'completed', 'cancelled', or 'all'
    - page: page number (default 1)
    - page_size: items per page (default 10, max 100)
    """
    status_filter = request.query_params.get('status', 'active')
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = min(100, max(1, int(request.query_params.get('page_size', 10))))
    except (ValueError, TypeError):
        page_size = 10
    
    qs = ChefServiceOrder.objects.filter(customer=request.user)
    
    # Apply status filter
    if status_filter == 'active':
        qs = qs.filter(status__in=['draft', 'awaiting_payment', 'confirmed'])
    elif status_filter == 'completed':
        qs = qs.filter(status='completed')
    elif status_filter == 'cancelled':
        qs = qs.filter(status__in=['cancelled', 'refunded'])
    # 'all' returns everything (no filter)
    
    qs = qs.select_related('offering', 'tier', 'chef', 'chef__user', 'address')
    qs = qs.order_by('-created_at')
    
    # Pagination
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    orders = qs[start:end]
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    return Response({
        'results': ChefServiceOrderSerializer(orders, many=True).data,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def checkout_order(request, order_id):
    order = get_object_or_404(ChefServiceOrder, id=order_id)
    if order.customer_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)

    # Disallow re-checkout if already processed
    if order.status not in ("draft", "awaiting_payment"):
        if order.status == 'confirmed':
            return Response({
                "success": True,
                "already_paid": True,
                "status": order.status,
            })
        return Response({"error": f"Order is {order.status}; cannot create checkout session"}, status=400)

    # If awaiting_payment and we have a session, return it
    if order.status == 'awaiting_payment' and order.stripe_session_id:
        try:
            from django.conf import settings
            stripe.api_key = settings.STRIPE_SECRET_KEY
            sess = stripe.checkout.Session.retrieve(order.stripe_session_id)
            return Response({"success": True, "session_id": sess.id, "session_url": getattr(sess, 'url', None)})
        except Exception:
            # Fall through to create a new session if retrieval fails
            pass

    # Validate scheduling details before checkout
    validation_errors = {}
    if order.offering.service_type == "home_chef":
        if not order.service_date:
            validation_errors["service_date"] = "Service date is required for home chef services."
        if not order.service_start_time:
            validation_errors["service_start_time"] = "Service start time is required for home chef services."
    elif order.offering.service_type == "weekly_prep":
        if order.tier and order.tier.is_recurring:
            if not order.schedule_preferences and (not order.service_date or not order.service_start_time):
                validation_errors["schedule_preferences"] = "Provide schedule preferences or a preferred date/time for recurring weekly prep."
        else:
            if not order.service_date:
                validation_errors["service_date"] = "Service date is required for weekly prep services."
            if not order.service_start_time:
                validation_errors["service_start_time"] = "Service start time is required for weekly prep services."
    
    # Check if address is required and missing
    if not order.address:
        validation_errors["address"] = "Delivery address is required."
    
    # Minimum notice validation (24 hours)
    if order.service_date and order.service_start_time:
        service_datetime = datetime.combine(order.service_date, order.service_start_time)
        if timezone.is_naive(service_datetime):
            service_datetime = timezone.make_aware(service_datetime)
        min_datetime = timezone.now() + timedelta(hours=24)
        if service_datetime < min_datetime:
            validation_errors["service_date"] = "Service must be scheduled at least 24 hours in advance."
    
    if validation_errors:
        return Response({
            "error": "Missing required fields for checkout",
            "validation_errors": validation_errors
        }, status=400)

    # Validate the order can transition to awaiting_payment (don't save yet - 
    # create_service_checkout_session will save status + session_id atomically)
    try:
        order.full_clean()
    except Exception as e:
        return Response({"error": str(e)}, status=400)

    ok, payload = create_service_checkout_session(order.id, customer_email=request.user.email)
    if not ok:
        return Response(payload, status=400)
    return Response({"success": True, **payload})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verify_service_payment(request, order_id):
    """
    Verify payment status for a service order by checking the Stripe session.
    This is a fallback for when webhooks don't reach the server (e.g., local development).
    
    Query params:
    - session_id: Optional Stripe session ID to check (uses order's stored session if not provided)
    """
    order = get_object_or_404(ChefServiceOrder, id=order_id)
    if order.customer_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    
    # If already confirmed, just return success
    if order.status == 'confirmed':
        return Response({
            "success": True,
            "status": order.status,
            "already_confirmed": True
        })
    
    # Get session ID from query params or order
    session_id = request.query_params.get('session_id') or order.stripe_session_id
    if not session_id:
        return Response({
            "success": False,
            "status": order.status,
            "error": "No checkout session found for this order"
        }, status=400)
    
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)
        
        session_status = getattr(session, 'status', None)
        payment_status = getattr(session, 'payment_status', None)
        
        # Check if payment is complete
        if session_status == 'complete' and payment_status == 'paid':
            # Update order status to confirmed
            with transaction.atomic():
                order = ChefServiceOrder.objects.select_for_update().get(id=order_id)
                if order.status != 'confirmed':
                    order.status = 'confirmed'
                    if not order.stripe_session_id:
                        order.stripe_session_id = session_id
                    # Store subscription ID if present
                    subscription_id = getattr(session, 'subscription', None)
                    if subscription_id and not order.stripe_subscription_id:
                        order.stripe_subscription_id = subscription_id
                    order.save(update_fields=['status', 'stripe_session_id', 'stripe_subscription_id'])
                    logger.info(f"Service order {order_id} confirmed via verify_service_payment endpoint")
            
            return Response({
                "success": True,
                "status": "confirmed",
                "session_status": session_status,
                "payment_status": payment_status
            })
        else:
            return Response({
                "success": False,
                "status": order.status,
                "session_status": session_status,
                "payment_status": payment_status,
                "message": "Payment not yet complete"
            })
    
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error verifying payment for order {order_id}: {e}")
        return Response({
            "success": False,
            "status": order.status,
            "error": str(e)
        }, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_order(request, order_id):
    order = get_object_or_404(ChefServiceOrder, id=order_id)
    if order.customer_id != request.user.id and not request.user.is_staff:
        return Response({"error": "Forbidden"}, status=403)
    if order.status in ("confirmed", "awaiting_payment"):
        # Business rules TBD; allow simple cancellation for now
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        return Response({"status": "cancelled"})
    order.status = 'cancelled'
    order.save(update_fields=['status'])
    return Response({"status": "cancelled"})


@api_view(['GET'])
@permission_classes([AllowAny])
def supported_currencies(request):
    """
    Return list of supported currencies for service tier pricing.
    
    This endpoint helps frontends populate currency dropdowns and
    display appropriate validation messages.
    
    Response format:
    {
        "currencies": [
            {
                "code": "usd",
                "symbol": "$",
                "name": "US Dollar",
                "min_amount": 50,
                "min_display": "$0.50",
                "zero_decimal": false
            },
            ...
        ]
    }
    """
    from .serializers import _CURRENCY_SYMBOLS, _ZERO_DECIMAL_CURRENCIES
    
    currency_names = {
        'usd': 'US Dollar',
        'eur': 'Euro',
        'gbp': 'British Pound',
        'jpy': 'Japanese Yen',
        'cad': 'Canadian Dollar',
        'aud': 'Australian Dollar',
        'chf': 'Swiss Franc',
        'hkd': 'Hong Kong Dollar',
        'sgd': 'Singapore Dollar',
        'nzd': 'New Zealand Dollar',
        'mxn': 'Mexican Peso',
    }
    
    currencies = []
    for code, info in ChefServicePriceTier.SUPPORTED_CURRENCIES.items():
        is_zero_decimal = info['zero_decimal']
        min_amount = info['min']
        symbol = _CURRENCY_SYMBOLS.get(code, code.upper())
        
        # Format minimum for display
        if is_zero_decimal:
            min_display = f"{symbol}{min_amount:,}"
        else:
            min_display = f"{symbol}{min_amount / 100:.2f}".rstrip('0').rstrip('.')
        
        currencies.append({
            'code': code,
            'symbol': symbol,
            'name': currency_names.get(code, code.upper()),
            'min_amount': min_amount,
            'min_display': min_display,
            'zero_decimal': is_zero_decimal,
        })
    
    # Sort by code for consistent ordering
    currencies.sort(key=lambda c: c['code'])
    
    return Response({'currencies': currencies})
