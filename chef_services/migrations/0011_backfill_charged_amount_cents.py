"""Backfill charged_amount_cents from tier price for existing orders."""

from django.db import migrations


def backfill_charged_amount(apps, schema_editor):
    ChefServiceOrder = apps.get_model('chef_services', 'ChefServiceOrder')
    # Update orders that have a tier but no charged amount yet
    orders = ChefServiceOrder.objects.filter(
        charged_amount_cents=0,
        tier__isnull=False,
    ).select_related('tier')
    updated = 0
    for order in orders.iterator():
        order.charged_amount_cents = order.tier.desired_unit_amount_cents
        order.save(update_fields=['charged_amount_cents'])
        updated += 1
    if updated:
        print(f"  Backfilled charged_amount_cents for {updated} orders")


class Migration(migrations.Migration):

    dependencies = [
        ('chef_services', '0010_chefserviceorder_charged_amount_cents_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_charged_amount, migrations.RunPython.noop),
    ]
