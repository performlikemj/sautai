from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('meals', '0080_add_lead_to_chef_meal_plan'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymentlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('charge', 'Charge'),
                    ('refund', 'Refund'),
                    ('payout', 'Payout to Chef'),
                    ('adjustment', 'Manual Adjustment'),
                    ('dispute', 'Dispute/Chargeback'),
                    ('transfer', 'Transfer to Chef'),
                    ('transfer_reversal', 'Transfer Reversal'),
                ],
                max_length=20,
            ),
        ),
    ]
