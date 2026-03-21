import os
import urllib.parse
from decimal import Decimal, ROUND_HALF_UP

import stripe
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from rest_framework.response import Response

from meals.models import PlatformFeeConfig, StripeConnectAccount


class StripeAccountError(Exception):
    """Base error for Stripe account availability issues."""


class StripeAccountNotFound(StripeAccountError):
    """Raised when a chef has not connected a Stripe account."""


class StripeAccountNotReady(StripeAccountError):
    """Raised when the connected Stripe account cannot process charges."""

def standardize_stripe_response(success, message, redirect_url=None, data=None, status_code=200):
    """
    Standardize the response format for Stripe-related operations.
    Returns a JSON response that the Streamlit app can handle.
    """
    response_data = {
        "success": success,
        "message": message,
        "status": "success" if success else "error"
    }
    
    if redirect_url:
        response_data["redirect_url"] = redirect_url
    
    if data:
        response_data.update(data)
    
    return Response(response_data, status=status_code)

def handle_stripe_error(request, error_message, status_code=400):
    """
    Handle Stripe errors consistently across the application.
    Returns JSON response that Streamlit can handle.
    """
    return Response({
        "success": False,
        "status": "error",
        "message": str(error_message),
        "error_details": str(error_message)
    }, status=status_code)

def get_stripe_return_urls(success_path="", cancel_path=""):
    """
    Generate standard success and cancel URLs for Stripe sessions.
    Uses environment variables to determine the full URLs for redirects.
    """
    streamlit_url = os.getenv("STREAMLIT_URL")
    if not streamlit_url:
        # Fallback if STREAMLIT_URL is not set
        streamlit_url = "http://localhost:8501"

    # Allow configuration of the default frontend path (e.g., /orders)
    default_path = os.getenv("STRIPE_CHECKOUT_RETURN_PATH", "orders")
    if not success_path:
        success_path = default_path
    if not cancel_path:
        cancel_path = default_path

    # If success_path starts with /api/, it's a backend endpoint (doesn't need streamlit_url prefix)
    if success_path.startswith("/api/"):
        base_url = os.getenv("BACKEND_URL", streamlit_url)  # Use BACKEND_URL if defined
        success_url = f"{base_url}{success_path}"
        # If success_path doesn't contain session_id parameter, add it
        if "{CHECKOUT_SESSION_ID}" not in success_path:
            success_url += ("&" if "?" in success_path else "?") + "session_id={CHECKOUT_SESSION_ID}"
    else:
        # For frontend paths, use the Streamlit URL with appropriate paths
        # Remove leading slash if present to avoid double slashes
        success_path = success_path.lstrip('/')
        cancel_path = cancel_path.lstrip('/')
        
        # Default to payment-success and payment-cancelled if paths are just "/"
        if success_path == "/":
            success_path = "" 
        if cancel_path == "/":
            cancel_path = ""
            
        success_url = f"{streamlit_url}/{success_path}"
        
    # For cancel URL, also handle API endpoints vs frontend paths
    if cancel_path.startswith("/api/"):
        base_url = os.getenv("BACKEND_URL", streamlit_url)
        cancel_url = f"{base_url}{cancel_path}"
    else:
        # Remove leading slash if present
        cancel_path = cancel_path.lstrip('/')
        if cancel_path == "/":
            cancel_path = ""
        cancel_url = f"{streamlit_url}/{cancel_path}"
        
    return {
        "success_url": success_url,
        "cancel_url": cancel_url
    }


def get_platform_fee_percentage():
    """Return the active platform fee percentage as a Decimal."""
    return Decimal(str(PlatformFeeConfig.get_active_fee()))


def calculate_platform_fee_cents(amount_cents):
    """Calculate the platform fee for a charge amount (in cents).

    The fee includes both the platform commission *and* an allowance for
    Stripe processing & FX fees so that the platform balance doesn't go
    negative after the transfer to the connected account.
    """
    fee_pct = get_platform_fee_percentage()
    if amount_cents <= 0 or fee_pct <= 0:
        return 0
    # Stripe processing ≈ 2.9% + 30¢ domestic, up to ~3.4% + FX 2% for
    # international / cross-currency charges.  We use 5.5% as a safe
    # ceiling so the platform never loses money on fees.
    STRIPE_FEE_BUFFER_PCT = Decimal("5.5")
    total_pct = fee_pct + STRIPE_FEE_BUFFER_PCT
    fee = (Decimal(amount_cents) * total_pct / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee)


def get_active_stripe_account(chef):
    """Ensure the chef has an active Stripe account ready to accept charges."""
    try:
        account_record = StripeConnectAccount.objects.get(chef=chef)
    except StripeConnectAccount.DoesNotExist as exc:
        raise StripeAccountNotFound("Chef payments are not available yet. Please check back soon.") from exc

    stripe.api_key = settings.STRIPE_SECRET_KEY
    account = stripe.Account.retrieve(account_record.stripe_account_id)

    is_ready = bool(
        getattr(account, "charges_enabled", False)
        and getattr(account, "details_submitted", False)
        and getattr(account, "payouts_enabled", False)
    )

    if account_record.is_active != is_ready:
        account_record.is_active = is_ready
        account_record.save(update_fields=["is_active"])

    if not is_ready:
        raise StripeAccountNotReady(
            "This chef's payout account requires additional verification before payments can be processed."
        )

    return account_record.stripe_account_id, account
