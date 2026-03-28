"""Backfill NULL price_paid on ChefMealOrder records and reconcile event orders_count."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum, Q

from meals.models import ChefMealEvent, ChefMealOrder


class Command(BaseCommand):
    help = "Backfill NULL price_paid on ChefMealOrders and reconcile event orders_count"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prefix = "[DRY RUN] " if dry_run else ""

        # --- 1. Backfill NULL price_paid ---
        null_orders = ChefMealOrder.objects.filter(price_paid__isnull=True).select_related(
            "meal_event"
        )
        self.stdout.write(f"\n{prefix}Found {null_orders.count()} orders with NULL price_paid")

        fixed = 0
        skipped = 0
        for order in null_orders:
            price = order.unit_price or (
                order.meal_event.current_price if order.meal_event else None
            )
            if price is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Order {order.id}: cannot determine price (unit_price and event price both NULL) — skipped"
                    )
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  {prefix}Order {order.id}: setting price_paid={price} "
                f"(unit_price={order.unit_price}, event.current_price={order.meal_event.current_price if order.meal_event else 'N/A'})"
            )
            if not dry_run:
                order.price_paid = price
                order.save(update_fields=["price_paid"])
            fixed += 1

        self.stdout.write(self.style.SUCCESS(f"\n{prefix}Backfilled price_paid on {fixed} orders ({skipped} skipped)"))

        # --- 2. Fix orders where price_paid was stored as total (price * qty) ---
        multi_qty_orders = (
            ChefMealOrder.objects.filter(quantity__gt=1, price_paid__isnull=False, unit_price__isnull=False)
            .select_related("meal_event")
        )
        total_fixed = 0
        for order in multi_qty_orders:
            # If price_paid == unit_price * quantity, it was stored as total — fix to per-unit
            if order.unit_price and order.price_paid == order.unit_price * order.quantity:
                self.stdout.write(
                    f"  {prefix}Order {order.id}: fixing price_paid from total {order.price_paid} to per-unit {order.unit_price}"
                )
                if not dry_run:
                    order.price_paid = order.unit_price
                    order.save(update_fields=["price_paid"])
                total_fixed += 1

        if total_fixed:
            self.stdout.write(self.style.SUCCESS(f"{prefix}Fixed {total_fixed} orders with total-as-price_paid"))

        # --- 3. Reconcile orders_count on events ---
        events = ChefMealEvent.objects.all()
        count_fixes = 0
        for event in events:
            actual = (
                ChefMealOrder.objects.filter(
                    meal_event=event,
                    status__in=["confirmed", "completed"],
                )
                .aggregate(total_qty=Sum("quantity"))["total_qty"]
                or 0
            )
            if event.orders_count != actual:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {prefix}Event {event.id} ({event.meal.name} on {event.event_date}): "
                        f"orders_count={event.orders_count} → {actual}"
                    )
                )
                if not dry_run:
                    event.orders_count = actual
                    event.save(update_fields=["orders_count"])
                count_fixes += 1

        self.stdout.write(self.style.SUCCESS(f"\n{prefix}Reconciled orders_count on {count_fixes} events"))
        self.stdout.write(self.style.SUCCESS(f"\n{prefix}Done."))
