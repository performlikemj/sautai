"""
Chef Payment Links API endpoints.

Provides endpoints for creating, managing, and sending Stripe payment links
to clients (both platform users and manual contacts).
"""

import logging
import os
from datetime import timedelta

import stripe
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from chefs.models import Chef, ChefPaymentLink
from crm.models import Lead
from custom_auth.models import CustomUser
from meals.utils.stripe_utils import (
    calculate_platform_fee_cents,
    get_active_stripe_account,
    get_platform_fee_percentage,
    StripeAccountError,
)

logger = logging.getLogger(__name__)

# Set Stripe API key
stripe.api_key = settings.STRIPE_SECRET_KEY

# Zero-decimal currencies (amount is not in cents but whole units)
ZERO_DECIMAL_CURRENCIES = {
    'bif', 'clp', 'djf', 'gnf', 'jpy', 'kmf', 'krw', 'mga', 'pyg', 
    'rwf', 'ugx', 'vnd', 'vuv', 'xaf', 'xof', 'xpf'
}

# Currency symbols mapping
CURRENCY_SYMBOLS = {
    'usd': '$', 'eur': '€', 'gbp': '£', 'jpy': '¥', 'cny': '¥',
    'krw': '₩', 'inr': '₹', 'rub': '₽', 'brl': 'R$', 'aud': 'A$',
    'cad': 'C$', 'chf': 'CHF', 'hkd': 'HK$', 'sgd': 'S$', 'sek': 'kr',
    'nok': 'kr', 'dkk': 'kr', 'pln': 'zł', 'thb': '฿', 'mxn': 'MX$',
    'nzd': 'NZ$', 'zar': 'R', 'php': '₱', 'idr': 'Rp', 'myr': 'RM',
    'vnd': '₫', 'twd': 'NT$', 'aed': 'د.إ', 'sar': '﷼', 'ils': '₪',
    'try': '₺', 'cop': 'COL$', 'clp': 'CLP$', 'ars': 'AR$', 'pen': 'S/',
}


def format_currency(amount_cents, currency='usd'):
    """
    Format amount in cents to a display string with currency symbol.
    Handles zero-decimal currencies like JPY.
    """
    currency_lower = (currency or 'usd').lower()
    symbol = CURRENCY_SYMBOLS.get(currency_lower, currency_lower.upper() + ' ')
    
    if currency_lower in ZERO_DECIMAL_CURRENCIES:
        # Zero-decimal currencies: amount is already in whole units
        return f"{symbol}{amount_cents:,}"
    else:
        # Standard currencies: convert cents to main unit
        amount = amount_cents / 100
        return f"{symbol}{amount:,.2f}"


def _get_chef_or_403(request):
    """Get the Chef instance for the authenticated user."""
    try:
        chef = Chef.objects.get(user=request.user)
        return chef, None
    except Chef.DoesNotExist:
        return None, Response(
            {"error": "Not a chef. Only chefs can access payment links."},
            status=403
        )


class PaymentLinkPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _serialize_payment_link(link):
    """Serialize a ChefPaymentLink for API response."""
    return {
        'id': link.id,
        'recipient': {
            'type': 'lead' if link.lead else 'customer' if link.customer else None,
            'id': link.lead_id or link.customer_id,
            'name': link.get_recipient_name(),
            'email': link.get_recipient_email(),
            'email_verified': link.lead.email_verified if link.lead else True,
        } if link.lead or link.customer else None,
        'amount_cents': link.amount_cents,
        'amount_display': format_currency(link.amount_cents, link.currency),
        'currency': link.currency.upper(),
        'description': link.description,
        'status': link.status,
        'status_display': link.get_status_display(),
        'payment_url': link.stripe_payment_link_url,
        'email_sent_at': link.email_sent_at.isoformat() if link.email_sent_at else None,
        'email_send_count': link.email_send_count,
        'paid_at': link.paid_at.isoformat() if link.paid_at else None,
        'expires_at': link.expires_at.isoformat() if link.expires_at else None,
        'is_expired': link.is_expired(),
        'internal_notes': link.internal_notes,
        'created_at': link.created_at.isoformat(),
        'updated_at': link.updated_at.isoformat(),
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def payment_link_list(request):
    """
    GET /api/chefs/me/payment-links/
    
    Returns paginated list of payment links created by the chef.
    
    Query Parameters:
    - status: Filter by status (draft, pending, paid, expired, cancelled)
    - client_type: Filter by client type (lead, customer)
    - search: Search by recipient name or description
    - ordering: Sort field (created_at, -created_at, expires_at, amount_cents)
    
    POST /api/chefs/me/payment-links/
    
    Creates a new payment link.
    
    Request Body:
    ```json
    {
        "amount_cents": 5000,
        "description": "Weekly meal prep service",
        "lead_id": 123,  // OR "customer_id": 456
        "expires_days": 30,  // Optional, default 30
        "internal_notes": "First-time client"  // Optional
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    if request.method == 'POST':
        return _create_payment_link(request, chef)
    
    try:
        # Base queryset
        links = ChefPaymentLink.objects.filter(chef=chef).select_related('lead', 'customer')
        
        # Apply filters
        status = request.query_params.get('status')
        if status and status in dict(ChefPaymentLink.Status.choices):
            links = links.filter(status=status)
        
        client_type = request.query_params.get('client_type')
        if client_type == 'lead':
            links = links.filter(lead__isnull=False)
        elif client_type == 'customer':
            links = links.filter(customer__isnull=False)
        
        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            links = links.filter(
                Q(description__icontains=search) |
                Q(lead__first_name__icontains=search) |
                Q(lead__last_name__icontains=search) |
                Q(customer__first_name__icontains=search) |
                Q(customer__last_name__icontains=search)
            )
        
        # Apply ordering
        ordering = request.query_params.get('ordering', '-created_at')
        valid_orderings = ['created_at', '-created_at', 'expires_at', '-expires_at', 'amount_cents', '-amount_cents']
        if ordering in valid_orderings:
            links = links.order_by(ordering)
        else:
            links = links.order_by('-created_at')
        
        # Check and update expired links
        _check_and_update_expired_links(links)
        
        # Paginate
        paginator = PaymentLinkPagination()
        page = paginator.paginate_queryset(links, request)
        
        if page is not None:
            data = [_serialize_payment_link(link) for link in page]
            return paginator.get_paginated_response(data)
        
        data = [_serialize_payment_link(link) for link in links]
        return Response(data)
        
    except Exception as e:
        logger.exception(f"Error fetching payment links for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to fetch payment links. Please try again."},
            status=500
        )


def _check_and_update_expired_links(links_queryset):
    """Update status of expired payment links."""
    now = timezone.now()
    links_queryset.filter(
        status=ChefPaymentLink.Status.PENDING,
        expires_at__lt=now
    ).update(status=ChefPaymentLink.Status.EXPIRED)


def _create_payment_link(request, chef):
    """Create a new payment link with Stripe integration."""
    try:
        data = request.data
        
        # Validate required fields
        amount_cents = data.get('amount_cents')
        if amount_cents is not None:
            try:
                amount_cents = int(amount_cents)
            except (ValueError, TypeError):
                return Response(
                    {"error": "amount_cents must be a valid number."},
                    status=400
                )
        currency = data.get('currency', 'usd').lower()
        # Minimum amount varies by currency - Stripe requires 50 cents for most currencies
        min_amount = 1 if currency in ZERO_DECIMAL_CURRENCIES else 50
        if not amount_cents or amount_cents < min_amount:
            min_display = format_currency(min_amount, currency)
            return Response(
                {"error": f"Amount must be at least {min_display}."},
                status=400
            )
        
        description = data.get('description', '').strip()
        if not description:
            return Response(
                {"error": "Description is required."},
                status=400
            )
        
        # Get recipient
        lead_id = data.get('lead_id')
        customer_id = data.get('customer_id')
        
        if lead_id and customer_id:
            return Response(
                {"error": "Specify either lead_id or customer_id, not both."},
                status=400
            )
        
        lead = None
        customer = None
        
        if lead_id:
            try:
                lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
            except Lead.DoesNotExist:
                return Response({"error": "Contact not found."}, status=404)
        elif customer_id:
            try:
                from chef_services.models import ChefCustomerConnection
                connection = ChefCustomerConnection.objects.get(
                    chef=chef,
                    customer_id=customer_id,
                    status='accepted'
                )
                customer = connection.customer
            except ChefCustomerConnection.DoesNotExist:
                return Response({"error": "Customer not found or not connected."}, status=404)
        
        # Calculate expiration
        expires_days = int(data.get('expires_days', 30))
        expires_at = timezone.now() + timedelta(days=expires_days)
        
        # Verify chef has Stripe account
        try:
            destination_account_id, _ = get_active_stripe_account(chef)
        except StripeAccountError as exc:
            return Response({"error": str(exc)}, status=400)
        
        # Create the payment link record (draft first)
        payment_link = ChefPaymentLink.objects.create(
            chef=chef,
            lead=lead,
            customer=customer,
            amount_cents=amount_cents,
            currency=data.get('currency', 'usd').lower(),
            description=description,
            internal_notes=data.get('internal_notes', ''),
            expires_at=expires_at,
            status=ChefPaymentLink.Status.DRAFT,
        )
        
        # Create Stripe Payment Link
        try:
            stripe_link_data = _create_stripe_payment_link(
                chef=chef,
                payment_link=payment_link,
                destination_account_id=destination_account_id,
            )
            
            # Update payment link with Stripe details
            payment_link.stripe_product_id = stripe_link_data['product_id']
            payment_link.stripe_price_id = stripe_link_data['price_id']
            payment_link.stripe_payment_link_id = stripe_link_data['payment_link_id']
            payment_link.stripe_payment_link_url = stripe_link_data['payment_link_url']
            payment_link.status = ChefPaymentLink.Status.PENDING
            payment_link.save()
            
        except stripe.error.StripeError as se:
            logger.error(f"Stripe error creating payment link: {se}")
            payment_link.delete()
            return Response(
                {"error": f"Failed to create payment link: {str(se)}"},
                status=500
            )
        
        logger.info(f"Payment link {payment_link.id} created by chef {chef.id}")
        
        return Response(_serialize_payment_link(payment_link), status=201)
        
    except Exception as e:
        logger.exception(f"Error creating payment link for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to create payment link. Please try again."},
            status=500
        )


def _create_stripe_payment_link(chef, payment_link, destination_account_id):
    """
    Create Stripe Product, Price, and Payment Link.
    Uses Stripe Connect to route payments to chef's account.
    """
    # Create a product for this payment
    product = stripe.Product.create(
        name=payment_link.description[:250],
        metadata={
            'chef_id': str(chef.id),
            'payment_link_id': str(payment_link.id),
            'type': 'chef_payment_link',
        }
    )
    
    # Create a price for the product
    price = stripe.Price.create(
        product=product.id,
        unit_amount=payment_link.amount_cents,
        currency=payment_link.currency,
    )
    
    # Calculate platform fee as a fixed amount (application_fee_percent only works with recurring prices)
    platform_fee_percent = get_platform_fee_percentage()
    platform_fee_cents = 0
    if platform_fee_percent > 0:
        platform_fee_cents = int(payment_link.amount_cents * platform_fee_percent / 100)
    
    # Build the return URL
    frontend_url = os.getenv('STREAMLIT_URL', 'http://localhost:8501')
    success_url = f"{frontend_url}/payment-success?link_id={payment_link.id}&session_id={{CHECKOUT_SESSION_ID}}"
    
    # Create the payment link with transfer to connected account
    payment_link_params = {
        'line_items': [{'price': price.id, 'quantity': 1}],
        'after_completion': {
            'type': 'redirect',
            'redirect': {'url': success_url}
        },
        'metadata': {
            'chef_id': str(chef.id),
            'payment_link_id': str(payment_link.id),
            'type': 'chef_payment_link',
        },
        'transfer_data': {
            'destination': destination_account_id,
        },
    }
    
    # Add application fee as fixed amount if platform fee is configured
    if platform_fee_cents > 0:
        payment_link_params['application_fee_amount'] = platform_fee_cents
    
    stripe_payment_link = stripe.PaymentLink.create(**payment_link_params)
    
    return {
        'product_id': product.id,
        'price_id': price.id,
        'payment_link_id': stripe_payment_link.id,
        'payment_link_url': stripe_payment_link.url,
    }


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def payment_link_detail(request, link_id):
    """
    GET /api/chefs/me/payment-links/{link_id}/
    
    Returns detailed information about a payment link.
    
    DELETE /api/chefs/me/payment-links/{link_id}/
    
    Cancels a pending payment link.
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        payment_link = ChefPaymentLink.objects.select_related('lead', 'customer').get(
            id=link_id,
            chef=chef
        )
    except ChefPaymentLink.DoesNotExist:
        return Response({"error": "Payment link not found."}, status=404)
    
    try:
        if request.method == 'GET':
            # Check if expired
            if payment_link.status == ChefPaymentLink.Status.PENDING and payment_link.is_expired():
                payment_link.status = ChefPaymentLink.Status.EXPIRED
                payment_link.save(update_fields=['status', 'updated_at'])
            
            return Response(_serialize_payment_link(payment_link))
        
        elif request.method == 'DELETE':
            if payment_link.status == ChefPaymentLink.Status.PAID:
                return Response(
                    {"error": "Cannot cancel a paid payment link."},
                    status=400
                )
            
            payment_link.cancel()
            
            # Optionally deactivate the Stripe payment link
            if payment_link.stripe_payment_link_id:
                try:
                    stripe.PaymentLink.modify(
                        payment_link.stripe_payment_link_id,
                        active=False
                    )
                except stripe.error.StripeError as se:
                    logger.warning(f"Failed to deactivate Stripe payment link: {se}")
            
            return Response({"status": "success", "message": "Payment link cancelled."})
        
    except Exception as e:
        logger.exception(f"Error managing payment link {link_id}: {e}")
        return Response(
            {"error": "Failed to manage payment link. Please try again."},
            status=500
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_payment_link(request, link_id):
    """
    POST /api/chefs/me/payment-links/{link_id}/send/
    
    Sends (or resends) the payment link via email.
    
    Request Body (optional):
    ```json
    {
        "email": "override@email.com"  // Optional: override recipient email
    }
    ```
    
    Requirements:
    - For leads: email must be verified
    - Payment link must be in pending status
    - Payment link must not be expired
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        payment_link = ChefPaymentLink.objects.select_related('lead', 'customer').get(
            id=link_id,
            chef=chef
        )
    except ChefPaymentLink.DoesNotExist:
        return Response({"error": "Payment link not found."}, status=404)
    
    try:
        # Check if can send
        can_send, error_msg = payment_link.can_send_email()
        if not can_send:
            return Response({"error": error_msg}, status=400)
        
        # Get email address
        override_email = request.data.get('email')
        recipient_email = override_email or payment_link.get_recipient_email()
        
        if not recipient_email:
            return Response(
                {"error": "No email address available. Please add an email to the contact."},
                status=400
            )
        
        # Send the email
        _send_payment_link_email(payment_link, chef, recipient_email)
        
        # Record that email was sent
        payment_link.record_email_sent(recipient_email)
        
        logger.info(f"Payment link {link_id} sent to {recipient_email} by chef {chef.id}")
        
        return Response({
            "status": "success",
            "message": f"Payment link sent to {recipient_email}",
            "email_send_count": payment_link.email_send_count
        })
        
    except Exception as e:
        logger.exception(f"Error sending payment link {link_id}: {e}")
        return Response(
            {"error": "Failed to send payment link. Please try again."},
            status=500
        )


def _send_payment_link_email(payment_link, chef, recipient_email):
    """Send the payment link email using the notification assistant."""
    try:
        from meals.meal_assistant_implementation import MealPlanningAssistant
        
        chef_name = chef.user.get_full_name() or chef.user.username
        recipient_name = payment_link.get_recipient_name()
        amount_display = format_currency(payment_link.amount_cents, payment_link.currency)
        
        message_content = (
            f"Please send a payment request email to {recipient_name}. "
            f"Chef {chef_name} is requesting payment of {amount_display} for: {payment_link.description}. "
            f"The secure payment link is: {payment_link.stripe_payment_link_url} "
            f"This link expires on {payment_link.expires_at.strftime('%B %d, %Y')}. "
            f"Make it professional, friendly, and include the payment amount prominently."
        )
        
        result = MealPlanningAssistant.send_notification_via_assistant(
            user_id=None,  # May be a lead (non-platform user)
            message_content=message_content,
            subject=f"Payment Request from {chef_name} - {amount_display}",
            template_key='chef_payment_link_email',
            template_context={
                'recipient_name': recipient_name,
                'chef_name': chef_name,
                'amount_display': amount_display,
                'description': payment_link.description,
                'payment_url': payment_link.stripe_payment_link_url,
                'expires_at': payment_link.expires_at.strftime('%B %d, %Y'),
            },
            recipient_email=recipient_email,
        )
        
        if result.get('status') != 'success':
            logger.error(f"Failed to send payment link email: {result}")
            raise Exception("Email service returned error")
            
    except Exception as e:
        logger.exception(f"Error in _send_payment_link_email: {e}")
        # Fall back to simple email
        _send_simple_payment_link_email(payment_link, chef, recipient_email)


def _send_simple_payment_link_email(payment_link, chef, recipient_email):
    """Fallback simple email sender for payment links."""
    import requests
    
    n8n_webhook_url = os.getenv('N8N_PAYMENT_LINK_WEBHOOK_URL')
    if not n8n_webhook_url:
        logger.warning("N8N_PAYMENT_LINK_WEBHOOK_URL not configured")
        return
    
    chef_name = chef.user.get_full_name() or chef.user.username
    recipient_name = payment_link.get_recipient_name()
    amount_display = format_currency(payment_link.amount_cents, payment_link.currency)
    
    html_body = render_to_string('meals/chef_payment_link_email.html', {
        'recipient_name': recipient_name,
        'chef_name': chef_name,
        'amount_display': amount_display,
        'description': payment_link.description,
        'payment_url': payment_link.stripe_payment_link_url,
        'expires_at': payment_link.expires_at.strftime('%B %d, %Y'),
    })
    
    email_data = {
        'to': recipient_email,
        'subject': f"Payment Request from {chef_name} - {amount_display}",
        'html_body': html_body,
    }
    
    try:
        requests.post(n8n_webhook_url, json=email_data, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send fallback payment link email: {e}")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_link_stats(request):
    """
    GET /api/chefs/me/payment-links/stats/
    
    Returns summary statistics for the chef's payment links.
    Amounts are filtered by the chef's default currency to avoid mixing currencies.
    
    Response:
    ```json
    {
        "total_count": 25,
        "pending_count": 5,
        "paid_count": 18,
        "expired_count": 2,
        "total_pending_amount_cents": 75000,
        "total_paid_amount_cents": 450000,
        "currency": "USD",
        "default_currency": "usd"
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        from django.db.models import Sum, Count, Q
        
        # Update expired links first
        now = timezone.now()
        ChefPaymentLink.objects.filter(
            chef=chef,
            status=ChefPaymentLink.Status.PENDING,
            expires_at__lt=now
        ).update(status=ChefPaymentLink.Status.EXPIRED)
        
        # Determine the dominant currency from actual payment links
        # (fall back to chef default if no links exist)
        from django.db.models import Count as CountAnnotation
        currency_counts = (
            ChefPaymentLink.objects.filter(chef=chef)
            .values('currency')
            .annotate(cnt=CountAnnotation('id'))
            .order_by('-cnt')
        )
        if currency_counts:
            dominant_currency = currency_counts[0]['currency']
        else:
            dominant_currency = chef.default_currency or 'usd'

        currency_filter = Q(currency=dominant_currency)

        stats = ChefPaymentLink.objects.filter(chef=chef).aggregate(
            total_count=Count('id'),
            pending_count=Count('id', filter=Q(status=ChefPaymentLink.Status.PENDING)),
            paid_count=Count('id', filter=Q(status=ChefPaymentLink.Status.PAID)),
            expired_count=Count('id', filter=Q(status=ChefPaymentLink.Status.EXPIRED)),
            cancelled_count=Count('id', filter=Q(status=ChefPaymentLink.Status.CANCELLED)),
            # Sum amounts for the dominant currency to avoid mixing currencies
            total_pending_amount_cents=Sum(
                'amount_cents',
                filter=Q(status=ChefPaymentLink.Status.PENDING) & currency_filter
            ),
            total_paid_amount_cents=Sum(
                'paid_amount_cents',
                filter=Q(status=ChefPaymentLink.Status.PAID) & currency_filter
            ),
        )

        # Handle None values
        for key in stats:
            if stats[key] is None:
                stats[key] = 0

        # Include currency info so frontend can format correctly
        stats['currency'] = dominant_currency.upper()
        stats['default_currency'] = dominant_currency
        
        return Response(stats)
        
    except Exception as e:
        logger.exception(f"Error fetching payment link stats for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to fetch statistics. Please try again."},
            status=500
        )


@api_view(['POST'])
@permission_classes([])  # Allow unauthenticated - payer may not be a platform user
def verify_payment_link(request, link_id):
    """
    POST /api/chefs/payment-links/{link_id}/verify/
    
    Verify and update payment link status by checking Stripe directly.
    This serves as a fallback when webhooks fail or are delayed.
    
    Query Parameters:
    - session_id: The Stripe checkout session ID from the success redirect
    
    Returns:
    ```json
    {
        "status": "paid",
        "payment_link_id": 123,
        "amount_display": "$50.00",
        "paid_at": "2025-12-19T14:30:00Z"
    }
    ```
    """
    session_id = request.query_params.get('session_id') or request.data.get('session_id')
    
    if not session_id:
        return Response(
            {"error": "session_id is required"},
            status=400
        )
    
    try:
        # Get the payment link
        payment_link = ChefPaymentLink.objects.select_related('chef').get(id=link_id)
    except ChefPaymentLink.DoesNotExist:
        return Response({"error": "Payment link not found"}, status=404)
    
    # If already paid, return success immediately
    if payment_link.status == ChefPaymentLink.Status.PAID:
        return Response({
            "status": "paid",
            "payment_link_id": payment_link.id,
            "amount_display": format_currency(payment_link.amount_cents, payment_link.currency),
            "paid_at": payment_link.paid_at.isoformat() if payment_link.paid_at else None,
            "message": "Payment already confirmed"
        })
    
    try:
        # Retrieve the checkout session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['payment_intent']
        )
        
        # Verify metadata matches this payment link
        md = checkout_session.metadata or {}
        if md.get('payment_link_id') != str(link_id):
            logger.warning(
                f"Session {session_id} payment_link_id mismatch: "
                f"expected {link_id}, got {md.get('payment_link_id')}"
            )
            return Response(
                {"error": "Session does not match this payment link"},
                status=400
            )
        
        # Check if payment was successful
        if checkout_session.status == 'complete' and checkout_session.payment_status == 'paid':
            from django.db import transaction
            
            with transaction.atomic():
                # Re-fetch with lock to prevent race conditions
                payment_link = ChefPaymentLink.objects.select_for_update().get(id=link_id)
                
                # Double-check it wasn't already updated
                if payment_link.status == ChefPaymentLink.Status.PAID:
                    return Response({
                        "status": "paid",
                        "payment_link_id": payment_link.id,
                        "amount_display": format_currency(payment_link.amount_cents, payment_link.currency),
                        "paid_at": payment_link.paid_at.isoformat() if payment_link.paid_at else None,
                        "message": "Payment already confirmed"
                    })
                
                # Update the payment link
                payment_link.status = ChefPaymentLink.Status.PAID
                payment_link.paid_at = timezone.now()
                payment_link.stripe_checkout_session_id = session_id
                
                if checkout_session.payment_intent:
                    pi = checkout_session.payment_intent
                    if isinstance(pi, str):
                        payment_link.stripe_payment_intent_id = pi
                    else:
                        payment_link.stripe_payment_intent_id = pi.id
                
                if checkout_session.amount_total:
                    payment_link.paid_amount_cents = checkout_session.amount_total
                
                payment_link.save(update_fields=[
                    'status', 'paid_at', 'stripe_checkout_session_id',
                    'stripe_payment_intent_id', 'paid_amount_cents', 'updated_at'
                ])
                
                logger.info(
                    f"Payment link {link_id} verified and marked as paid via fallback. "
                    f"Session: {session_id}"
                )
            
            return Response({
                "status": "paid",
                "payment_link_id": payment_link.id,
                "amount_display": format_currency(payment_link.amount_cents, payment_link.currency),
                "paid_at": payment_link.paid_at.isoformat() if payment_link.paid_at else None,
                "message": "Payment verified successfully"
            })
        
        else:
            # Payment not complete yet
            return Response({
                "status": payment_link.status,
                "payment_link_id": payment_link.id,
                "checkout_status": checkout_session.status,
                "payment_status": checkout_session.payment_status,
                "message": "Payment not yet completed"
            })
        
    except stripe.error.InvalidRequestError as e:
        logger.warning(f"Invalid Stripe session {session_id}: {e}")
        return Response(
            {"error": "Invalid or expired session"},
            status=400
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error verifying payment link {link_id}: {e}")
        return Response(
            {"error": "Failed to verify payment with Stripe"},
            status=500
        )
    except Exception as e:
        logger.exception(f"Error verifying payment link {link_id}: {e}")
        return Response(
            {"error": "Failed to verify payment. Please try again."},
            status=500
        )








