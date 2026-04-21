"""
Backfill settlement data for existing paid ChefPaymentLinks.

Fetches the Stripe balance transaction for each paid link that has a
payment intent but no settlement data, and stores the settled amount
in the account's settlement currency (typically USD).
"""

import stripe
from django.core.management.base import BaseCommand

from chefs.models import ChefPaymentLink


class Command(BaseCommand):
    help = 'Backfill settlement amounts from Stripe balance transactions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be updated without saving',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        links = ChefPaymentLink.objects.filter(
            status=ChefPaymentLink.Status.PAID,
            stripe_payment_intent_id__isnull=False,
            settled_amount_cents__isnull=True,
        ).exclude(stripe_payment_intent_id='')

        total = links.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('No payment links need backfilling.'))
            return

        self.stdout.write(f'Found {total} paid link(s) to backfill.')
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes will be saved.'))

        updated = 0
        errors = 0

        for link in links:
            try:
                pi = stripe.PaymentIntent.retrieve(
                    link.stripe_payment_intent_id,
                    expand=['latest_charge.balance_transaction'],
                )
                bt = pi.latest_charge.balance_transaction

                if dry_run:
                    self.stdout.write(
                        f'  [dry run] {link.id}: {link.amount_cents} {link.currency} '
                        f'-> {bt.amount} {bt.currency} (rate: {bt.exchange_rate})'
                    )
                else:
                    link.settled_amount_cents = bt.amount
                    link.settled_currency = bt.currency
                    link.exchange_rate = bt.exchange_rate
                    link.save(update_fields=[
                        'settled_amount_cents', 'settled_currency',
                        'exchange_rate', 'updated_at',
                    ])
                updated += 1
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(
                    f'  Error backfilling link {link.id} (pi={link.stripe_payment_intent_id}): {e}'
                ))

        self.stdout.write(
            self.style.SUCCESS(f'Done. Updated: {updated}, errors: {errors}, total: {total}')
        )
