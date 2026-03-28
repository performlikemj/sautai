"""Quick diagnostic: list all ChefMealOrder records."""

from django.core.management.base import BaseCommand
from meals.models import ChefMealOrder, ChefMealEvent


class Command(BaseCommand):
    help = "List all ChefMealOrder and ChefMealEvent records for diagnosis"

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
        self.stdout.write(f"  Total orders: {orders.count()}")

        self.stdout.write("\n=== ChefMealEvents ===")
        events = ChefMealEvent.objects.select_related("chef", "chef__user", "meal").all()
        for e in events:
            self.stdout.write(
                f"  Event {e.id}: status={e.status}, orders_count={e.orders_count}, "
                f"base={e.base_price}, current={e.current_price}, min={e.min_price}, "
                f"chef={e.chef.user.username}, meal={e.meal.name}, date={e.event_date}"
            )
        self.stdout.write(f"  Total events: {events.count()}")
