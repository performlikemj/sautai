"""Quick diagnostic: list all order-related records across all order types."""

from django.core.management.base import BaseCommand
from meals.models import ChefMealOrder, ChefMealEvent, PaymentLog


class Command(BaseCommand):
    help = "List all order records for diagnosis"

    def handle(self, *args, **options):
        self.stdout.write("\n=== ChefMealOrders ===")
        orders = ChefMealOrder.objects.select_related(
            "meal_event", "meal_event__chef", "meal_event__chef__user", "customer"
        ).all()
        for o in orders:
            chef_name = o.meal_event.chef.user.username if o.meal_event and o.meal_event.chef else "?"
            self.stdout.write(
                f"  Order {o.id}: status={o.status}, price_paid={o.price_paid}, "
                f"unit_price={o.unit_price}, qty={o.quantity}, "
                f"chef={chef_name}, customer={o.customer.username}, "
                f"event_id={o.meal_event_id}, created={o.created_at}"
            )
        self.stdout.write(f"  Total: {orders.count()}")

        self.stdout.write("\n=== ChefMealEvents ===")
        events = ChefMealEvent.objects.select_related("chef", "chef__user", "meal").all()
        for e in events:
            self.stdout.write(
                f"  Event {e.id}: status={e.status}, orders_count={e.orders_count}, "
                f"base={e.base_price}, current={e.current_price}, min={e.min_price}, "
                f"chef={e.chef.user.username}, meal={e.meal.name}, date={e.event_date}"
            )
        self.stdout.write(f"  Total: {events.count()}")

        self.stdout.write("\n=== ChefServiceOrders ===")
        from chef_services.models import ChefServiceOrder
        svc_orders = ChefServiceOrder.objects.select_related(
            "chef", "chef__user", "customer", "offering", "tier"
        ).all()
        for o in svc_orders:
            chef_name = o.chef.user.username if o.chef else "?"
            tier_cents = o.tier.desired_unit_amount_cents if o.tier else 0
            self.stdout.write(
                f"  SvcOrder {o.id}: status={o.status}, tier_cents={tier_cents}, "
                f"charged_cents={o.charged_amount_cents}, "
                f"chef={chef_name}, customer={o.customer.username if o.customer else '?'}, "
                f"offering={o.offering.title if o.offering else '?'}, "
                f"created={o.created_at}"
            )
        self.stdout.write(f"  Total: {svc_orders.count()}")

        self.stdout.write("\n=== ChefPaymentLinks ===")
        try:
            from chefs.models import ChefPaymentLink
            links = ChefPaymentLink.objects.select_related("chef", "chef__user").all()
            for pl in links:
                self.stdout.write(
                    f"  PayLink {pl.id}: status={pl.status}, amount={getattr(pl, 'amount', '?')}, "
                    f"chef={pl.chef.user.username if pl.chef else '?'}, "
                    f"paid_at={getattr(pl, 'paid_at', '?')}, created={pl.created_at}"
                )
            self.stdout.write(f"  Total: {links.count()}")
        except ImportError:
            self.stdout.write("  (ChefPaymentLink model not found)")

        self.stdout.write("\n=== PaymentLogs (last 20) ===")
        logs = PaymentLog.objects.all().order_by("-created_at")[:20]
        for log in logs:
            self.stdout.write(
                f"  Log {log.id}: action={log.action}, amount={log.amount}, "
                f"status={log.status}, stripe_id={log.stripe_id}, "
                f"user={log.user.username if log.user else '?'}, "
                f"created={log.created_at}"
            )
        self.stdout.write(f"  Total logs: {PaymentLog.objects.count()}")
