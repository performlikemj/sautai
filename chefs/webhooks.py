"""
Webhook handlers for chef-related Stripe events.

Handles payment link completion and other chef-specific payment events.
"""

import logging
import os
import requests
import traceback

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ChefPaymentLink

logger = logging.getLogger(__name__)


def handle_payment_link_completed(session):
    """
    Handle Stripe checkout.session.completed for chef payment links.
    
    Expects metadata:
    - type: 'chef_payment_link'
    - payment_link_id: The ChefPaymentLink ID
    - chef_id: The chef ID
    
    Args:
        session: Stripe checkout session object
    """
    metadata = getattr(session, 'metadata', {}) or {}
    
    if metadata.get('type') != 'chef_payment_link':
        logger.warning("handle_payment_link_completed called with wrong type")
        return
    
    payment_link_id = metadata.get('payment_link_id')
    if not payment_link_id:
        logger.error("Payment link webhook missing payment_link_id in metadata")
        return
    
    try:
        with transaction.atomic():
            payment_link = ChefPaymentLink.objects.select_for_update().get(id=payment_link_id)
            
            # Idempotency: if already paid, do nothing
            if payment_link.status == ChefPaymentLink.Status.PAID:
                logger.info(f"Payment link {payment_link_id} already marked as paid")
                return
            
            # Verify chef ID matches
            md_chef_id = metadata.get('chef_id')
            if md_chef_id and str(payment_link.chef_id) != str(md_chef_id):
                logger.warning(
                    f"Payment link {payment_link_id} chef mismatch: "
                    f"got {md_chef_id}, expected {payment_link.chef_id}"
                )
            
            # Get payment details from session
            payment_intent_id = getattr(session, 'payment_intent', None)
            amount_total = getattr(session, 'amount_total', None)
            
            # Mark as paid
            payment_link.status = ChefPaymentLink.Status.PAID
            payment_link.paid_at = timezone.now()
            payment_link.stripe_checkout_session_id = session.id
            
            if payment_intent_id:
                payment_link.stripe_payment_intent_id = payment_intent_id
            
            if amount_total:
                payment_link.paid_amount_cents = amount_total

            payment_link.save(update_fields=[
                'status', 'paid_at', 'stripe_checkout_session_id',
                'stripe_payment_intent_id', 'paid_amount_cents', 'updated_at'
            ])

            logger.info(
                f"Payment link {payment_link_id} marked as paid. "
                f"Payment intent: {payment_intent_id}, Amount: {amount_total} cents"
            )

            # Fetch settlement data from Stripe balance transaction
            if payment_intent_id:
                try:
                    _fetch_and_store_settlement(payment_link, payment_intent_id)
                except Exception as settle_err:
                    logger.warning(
                        f"Failed to fetch settlement data for {payment_link_id}: {settle_err}"
                    )
            
            # Send payment confirmation notification
            try:
                _send_payment_confirmation(payment_link)
            except Exception as notify_err:
                logger.warning(f"Failed to send payment confirmation: {notify_err}")
            
    except ChefPaymentLink.DoesNotExist:
        logger.error(f"Payment link {payment_link_id} not found for webhook session {session.id}")
        _send_traceback(
            error=f"Payment link {payment_link_id} not found",
            source='handle_payment_link_completed'
        )
    except Exception as e:
        logger.error(f"Error processing payment link webhook: {e}", exc_info=True)
        _send_traceback(
            error=str(e),
            source='handle_payment_link_completed'
        )
        raise


def _fetch_and_store_settlement(payment_link, payment_intent_id):
    """Fetch the balance transaction from Stripe and store settlement data."""
    pi = stripe.PaymentIntent.retrieve(
        payment_intent_id,
        expand=['latest_charge.balance_transaction'],
    )
    bt = pi.latest_charge.balance_transaction
    payment_link.settled_amount_cents = bt.amount
    payment_link.settled_currency = bt.currency
    payment_link.exchange_rate = bt.exchange_rate  # None when no conversion
    payment_link.save(update_fields=[
        'settled_amount_cents', 'settled_currency', 'exchange_rate', 'updated_at'
    ])
    logger.info(
        f"Settlement stored for payment link {payment_link.id}: "
        f"{bt.amount} {bt.currency} (rate: {bt.exchange_rate})"
    )


def _send_payment_confirmation(payment_link):
    """Send a payment confirmation notification to the chef."""
    try:
        from meals.meal_assistant_implementation import MealPlanningAssistant
        from chefs.api.payment_links import format_currency
        
        chef = payment_link.chef
        recipient_name = payment_link.get_recipient_name()
        amount_display = format_currency(payment_link.amount_cents, payment_link.currency)
        
        message_content = (
            f"Great news! {recipient_name} has completed their payment of {amount_display} "
            f"for: {payment_link.description}. "
            f"The payment was processed successfully via Stripe."
        )
        
        MealPlanningAssistant.send_notification_via_assistant(
            user_id=chef.user_id,
            message_content=message_content,
            subject=f"Payment Received: {amount_display} from {recipient_name}",
            template_key='payment_confirmation',
            template_context={
                'recipient_name': recipient_name,
                'amount_display': amount_display,
                'description': payment_link.description,
                'paid_at': payment_link.paid_at.strftime('%B %d, %Y at %I:%M %p'),
            },
        )
        
    except Exception as e:
        logger.warning(f"Failed to send payment confirmation to chef: {e}")


def _send_traceback(error, source):
    """Send error traceback to N8N for monitoring."""
    n8n_url = os.getenv('N8N_TRACEBACK_URL')
    if not n8n_url:
        return
    
    try:
        requests.post(
            n8n_url,
            json={
                'error': str(error),
                'source': source,
                'traceback': traceback.format_exc()
            },
            timeout=5
        )
    except requests.exceptions.RequestException:
        pass  # Don't fail silently but don't raise either










