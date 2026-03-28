from django.db import transaction
from django.utils import timezone
from meals.models import ChefMealOrder, ChefMealEvent
from django.db.models import F
import stripe
from django.conf import settings

from meals.utils.stripe_utils import (
    calculate_platform_fee_cents,
    get_active_stripe_account,
    StripeAccountError,
)

stripe.api_key = settings.STRIPE_SECRET_KEY

def create_order(user, event: ChefMealEvent, qty: int, idem_key: str):
    """
    Create a new chef meal order with Stripe payment intent for manual capture.
    
    Args:
        user: The user placing the order
        event: The ChefMealEvent being ordered
        qty: Quantity of the meal being ordered
        idem_key: Idempotency key to prevent duplicate operations
        
    Returns:
        The created ChefMealOrder object
        
    Raises:
        ValueError: If an active order already exists or if other validation fails
    """
    with transaction.atomic():
        # Lock the event row to prevent race conditions
        event = ChefMealEvent.objects.select_for_update().get(id=event.id)
        
        # Check if user already has an active order for this event
        if ChefMealOrder.objects.filter(
            customer=user, 
            meal_event=event,
            status__in=['placed', 'confirmed']
        ).exists():
            raise ValueError("Active order already exists")
        
        try:
            destination_account_id, _ = get_active_stripe_account(event.chef)
        except StripeAccountError as exc:
            raise ValueError(str(exc))

        amount_cents = int(event.current_price * qty * 100)
        platform_fee_cents = calculate_platform_fee_cents(amount_cents)

        intent_kwargs = {
            'amount': amount_cents,
            'currency': 'usd',
            'capture_method': 'manual',
            'metadata': {
                'order_type': 'chef_meal',
                'meal_event': event.id,
                'customer': user.id,
                'quantity': qty,
            },
            'transfer_data': {'destination': destination_account_id},
            'on_behalf_of': destination_account_id,
            'idempotency_key': idem_key,
        }
        if platform_fee_cents:
            intent_kwargs['application_fee_amount'] = platform_fee_cents

        # Create payment intent with manual capture
        intent = stripe.PaymentIntent.create(**intent_kwargs)
        
        # Create the order
        from meals.models import Order, OrderMeal
        # Check if the user already has an active order
        order, created = Order.objects.get_or_create(
            customer=user,
            status='Placed',
            is_paid=False,
            defaults={
                'delivery_method': 'Pickup',  # Default, can be updated later
            }
        )
        
        # Create the chef meal order
        chef_meal_order = ChefMealOrder.objects.create(
            order=order,
            meal_event=event,
            customer=user,
            quantity=qty,
            unit_price=event.current_price,
            price_paid=event.current_price,
            stripe_payment_intent_id=intent.id
        )

        # Ensure a corresponding OrderMeal row exists and is linked to this event
        try:
            # We need a MealPlanMeal to link when available; if not, create a minimal OrderMeal
            # Prefer to find an existing OrderMeal for this meal/event, else create new
            order_meal = (
                OrderMeal.objects
                .select_for_update()
                .filter(order=order, chef_meal_event=event)
                .first()
            )
            if not order_meal:
                order_meal = OrderMeal.objects.create(
                    order=order,
                    meal=event.meal,
                    meal_plan_meal=chef_meal_order.meal_plan_meal or event.meal.mealplanmeal_set.filter(meal=event.meal).first(),
                    chef_meal_event=event,
                    quantity=qty,
                )
            else:
                # Update quantity by adding this line's quantity (basic merge)
                order_meal.quantity = max(1, (order_meal.quantity or 0) + qty)
                order_meal.chef_meal_event = event
                order_meal.save(update_fields=['quantity', 'chef_meal_event'])
        except Exception:
            # Do not fail the transaction if OrderMeal creation fails; payment-init will fallback to ChefMealOrders
            pass
        
        # Capture at cutoff time
        from meals.tasks import schedule_capture
        schedule_capture(event.id)
        
        return chef_meal_order

def adjust_quantity(order: ChefMealOrder, new_qty: int, idem_key: str):
    """
    Adjust the quantity of an existing order.
    
    Args:
        order: The ChefMealOrder to update
        new_qty: The new quantity
        idem_key: Idempotency key to prevent duplicate operations
        
    Raises:
        ValueError: If cutoff time has passed or validation fails
    """
    cutoff = order.meal_event.order_cutoff_time
    
    # Check if cutoff time has passed
    if timezone.now() >= cutoff:
        raise ValueError("Order cutoff time has passed")
    
    # Calculate payment difference
    diff_amount = int(order.unit_price * (new_qty - order.quantity) * 100)
    
    # Update payment intent amount
    stripe.PaymentIntent.modify(
        order.stripe_payment_intent_id,
        amount=int(order.unit_price * new_qty * 100),
        idempotency_key=idem_key
    )
    
    # Update order quantity
    order.quantity = new_qty
    order.save(update_fields=['quantity'])

def cancel_order(order: ChefMealOrder, reason: str, idem_key: str):
    """
    Cancel an order and void the payment authorization.
    
    Args:
        order: The ChefMealOrder to cancel
        reason: Reason for cancellation
        idem_key: Idempotency key to prevent duplicate operations
        
    Returns:
        bool: True if cancelled successfully
        
    Raises:
        Exception: If Stripe API call fails
    """
    # Void the payment authorization
    if order.stripe_payment_intent_id:
        stripe.PaymentIntent.cancel(
            order.stripe_payment_intent_id,
            cancellation_reason=reason,
            idempotency_key=idem_key
        )
    
    # Update order status
    order.status = 'cancelled'
    order.save(update_fields=['status'])
    
    return True 
