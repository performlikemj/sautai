"""
API views for community membership management.

These endpoints allow chefs to subscribe to the community membership,
check their status, manage billing via Stripe portal, and cancel.
"""

import logging
import os

import stripe
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chefs.models import Chef
from .models import (
    ChefMembership,
    MembershipPaymentLog,
    MEMBERSHIP_PRODUCT_ID,
    MEMBERSHIP_MONTHLY_PRICE_ID,
    MEMBERSHIP_ANNUAL_PRICE_ID,
)

logger = logging.getLogger(__name__)


def get_chef_for_user(user):
    """Get the Chef instance for a user, or None if not a chef."""
    try:
        return Chef.objects.get(user=user)
    except Chef.DoesNotExist:
        return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    """
    Create a Stripe Checkout session for membership subscription.
    
    POST /memberships/subscribe/
    
    Body:
        billing_cycle: 'monthly' or 'annual' (default: 'monthly')
    
    Returns:
        checkout_url: URL to redirect the user to Stripe Checkout
    """
    chef = get_chef_for_user(request.user)
    if not chef:
        return Response(
            {'error': 'You must be a chef to subscribe to community membership'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Check for existing active membership
    try:
        existing = ChefMembership.objects.get(chef=chef)
        if existing.is_active_member:
            return Response(
                {'error': 'You already have an active membership'},
                status=status.HTTP_400_BAD_REQUEST
            )
    except ChefMembership.DoesNotExist:
        existing = None
    
    billing_cycle = request.data.get('billing_cycle', 'monthly')
    if billing_cycle == 'annual':
        price_id = MEMBERSHIP_ANNUAL_PRICE_ID
    else:
        price_id = MEMBERSHIP_MONTHLY_PRICE_ID
        billing_cycle = 'monthly'  # Normalize
    
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    # Get or create Stripe customer
    customer_id = None
    if existing and existing.stripe_customer_id:
        customer_id = existing.stripe_customer_id
    
    if not customer_id:
        # Create new Stripe customer
        try:
            customer = stripe.Customer.create(
                email=request.user.email,
                name=request.user.get_full_name() or request.user.username,
                metadata={
                    'chef_id': str(chef.id),
                    'user_id': str(request.user.id),
                }
            )
            customer_id = customer.id
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            return Response(
                {'error': 'Failed to set up billing. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # Determine return URLs
    frontend_url = os.getenv('STREAMLIT_URL', 'http://localhost:8501')
    success_url = f"{frontend_url}/membership?status=success"
    cancel_url = f"{frontend_url}/membership?status=cancelled"
    
    try:
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode='subscription',
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            subscription_data={
                'metadata': {
                    'chef_id': str(chef.id),
                    'type': 'community_membership',
                },
                'trial_period_days': 7,  # 1-week free trial
            },
            metadata={
                'chef_id': str(chef.id),
                'type': 'community_membership',
            },
            allow_promotion_codes=True,
        )
        
        # Update or create membership record with customer ID
        if existing:
            existing.stripe_customer_id = customer_id
            existing.billing_cycle = billing_cycle
            existing.save(update_fields=['stripe_customer_id', 'billing_cycle', 'updated_at'])
        else:
            ChefMembership.objects.create(
                chef=chef,
                stripe_customer_id=customer_id,
                billing_cycle=billing_cycle,
                status=ChefMembership.Status.TRIAL,
            )
        
        logger.info(f"Created checkout session for chef {chef.id}")
        
        return Response({
            'checkout_url': session.url,
            'session_id': session.id,
        })
        
    except stripe.error.StripeError as e:
        logger.error(f"Failed to create checkout session: {e}")
        return Response(
            {'error': 'Failed to create checkout session. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Need to import models for the aggregate
from django.db import models as db_models


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def membership_status(request):
    """
    Get the current membership status for the authenticated chef.
    
    GET /memberships/status/
    
    Returns:
        has_membership: bool
        status: trial/active/past_due/cancelled/paused
        billing_cycle: monthly/annual
        is_active: bool (can access features)
        trial_days_remaining: int or null
        current_period_end: datetime or null
        total_contributed: float (total amount paid)
    """
    chef = get_chef_for_user(request.user)
    if not chef:
        return Response({
            'has_membership': False,
            'is_chef': False,
            'message': 'You must be a chef to have a community membership'
        })
    
    try:
        membership = ChefMembership.objects.get(chef=chef)
        
        # Calculate total contributed
        total_cents = MembershipPaymentLog.objects.filter(
            membership=membership
        ).aggregate(
            total=db_models.Sum('amount_cents')
        )['total'] or 0
        
        return Response({
            'has_membership': True,
            'is_chef': True,
            'status': membership.status,
            'billing_cycle': membership.billing_cycle,
            'is_active': membership.is_active_member,
            'is_in_trial': membership.is_in_trial,
            'is_founding_member': membership.is_founding_member,
            'trial_days_remaining': membership.days_until_trial_ends,
            'current_period_start': membership.current_period_start,
            'current_period_end': membership.current_period_end,
            'total_contributed': total_cents / 100,
            'started_at': membership.started_at,
        })
        
    except ChefMembership.DoesNotExist:
        return Response({
            'has_membership': False,
            'is_chef': True,
            'message': 'No membership found. Subscribe to join the community!'
        })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_portal_session(request):
    """
    Create a Stripe Customer Portal session for billing management.
    
    POST /memberships/portal/
    
    Returns:
        portal_url: URL to redirect the user to Stripe Customer Portal
    """
    chef = get_chef_for_user(request.user)
    if not chef:
        return Response(
            {'error': 'You must be a chef to manage membership'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        membership = ChefMembership.objects.get(chef=chef)
    except ChefMembership.DoesNotExist:
        return Response(
            {'error': 'No membership found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    if not membership.stripe_customer_id:
        return Response(
            {'error': 'No billing account found'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    # Determine return URL
    frontend_url = os.getenv('STREAMLIT_URL', 'http://localhost:8501')
    return_url = f"{frontend_url}/membership"
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=membership.stripe_customer_id,
            return_url=return_url,
        )
        
        return Response({
            'portal_url': session.url,
        })
        
    except stripe.error.StripeError as e:
        logger.error(f"Failed to create portal session: {e}")
        return Response(
            {'error': 'Failed to open billing portal. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_membership(request):
    """
    Cancel the membership subscription.
    
    POST /memberships/cancel/
    
    Body:
        at_period_end: bool (default: True) - Cancel at end of billing period
    
    Returns:
        success: bool
        message: str
        cancels_at: datetime (when the membership will be cancelled)
    """
    chef = get_chef_for_user(request.user)
    if not chef:
        return Response(
            {'error': 'You must be a chef to manage membership'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        membership = ChefMembership.objects.get(chef=chef)
    except ChefMembership.DoesNotExist:
        return Response(
            {'error': 'No membership found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    if not membership.stripe_subscription_id:
        return Response(
            {'error': 'No active subscription found'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if membership.status == ChefMembership.Status.CANCELLED:
        return Response(
            {'error': 'Membership is already cancelled'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    at_period_end = request.data.get('at_period_end', True)
    
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    try:
        if at_period_end:
            # Cancel at end of billing period
            subscription = stripe.Subscription.modify(
                membership.stripe_subscription_id,
                cancel_at_period_end=True,
            )
            cancels_at = subscription.current_period_end
            message = 'Your membership will be cancelled at the end of your billing period.'
        else:
            # Cancel immediately
            stripe.Subscription.delete(membership.stripe_subscription_id)
            cancels_at = None
            membership.cancel()
            message = 'Your membership has been cancelled.'
        
        logger.info(
            f"Cancelled membership for chef {chef.id} "
            f"(at_period_end={at_period_end})"
        )
        
        return Response({
            'success': True,
            'message': message,
            'cancels_at': cancels_at,
        })
        
    except stripe.error.StripeError as e:
        logger.error(f"Failed to cancel subscription: {e}")
        return Response(
            {'error': 'Failed to cancel membership. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_history(request):
    """
    Get payment history for the membership.
    
    GET /memberships/payments/
    
    Returns:
        payments: list of payment records
    """
    chef = get_chef_for_user(request.user)
    if not chef:
        return Response(
            {'error': 'You must be a chef to view payment history'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        membership = ChefMembership.objects.get(chef=chef)
    except ChefMembership.DoesNotExist:
        return Response({'payments': []})
    
    payments = MembershipPaymentLog.objects.filter(
        membership=membership
    ).order_by('-paid_at')[:50]  # Last 50 payments
    
    return Response({
        'payments': [
            {
                'amount': payment.amount_cents / 100,
                'currency': payment.currency,
                'paid_at': payment.paid_at,
                'period_start': payment.period_start,
                'period_end': payment.period_end,
            }
            for payment in payments
        ]
    })










