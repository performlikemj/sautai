import django.core.validators
import django.db.models
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('chefs', '0001_initial'),
        ('meals', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SurveyTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('is_default', models.BooleanField(default=False, help_text="If True, this template is used as the chef's default for new surveys.")),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chef', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='survey_templates', to='chefs.chef')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SurveyQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_text', models.CharField(max_length=500)),
                ('question_type', models.CharField(choices=[('rating', 'Rating (1-5 stars)'), ('text', 'Text'), ('yes_no', 'Yes / No')], max_length=10)),
                ('order', models.PositiveIntegerField()),
                ('is_required', models.BooleanField(default=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='surveys.surveytemplate')),
            ],
            options={
                'ordering': ['order'],
                'unique_together': {('template', 'order')},
            },
        ),
        migrations.CreateModel(
            name='EventSurvey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('access_token', models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('active', 'Active'), ('closed', 'Closed')], default='draft', max_length=10)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('email_send_count', models.PositiveIntegerField(default=0)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chef', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='event_surveys', to='chefs.chef')),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='surveys', to='meals.chefmealevent')),
                ('template', models.ForeignKey(blank=True, help_text='Source template this survey was created from.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='surveys.surveytemplate')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='EventSurveyQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_text', models.CharField(max_length=500)),
                ('question_type', models.CharField(choices=[('rating', 'Rating (1-5 stars)'), ('text', 'Text'), ('yes_no', 'Yes / No')], max_length=10)),
                ('order', models.PositiveIntegerField()),
                ('is_required', models.BooleanField(default=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('survey', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='surveys.eventsurvey')),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='SurveyResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('respondent_email', models.EmailField(blank=True, max_length=254)),
                ('respondent_name', models.CharField(blank=True, max_length=200)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('survey', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='responses', to='surveys.eventsurvey')),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='surveyresponse',
            constraint=models.UniqueConstraint(
                condition=models.Q(('customer__isnull', False)),
                fields=['survey', 'customer'],
                name='unique_survey_response_per_customer',
            ),
        ),
        migrations.CreateModel(
            name='QuestionResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating_value', models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ('text_value', models.TextField(blank=True)),
                ('boolean_value', models.BooleanField(blank=True, null=True)),
                ('response', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='surveys.surveyresponse')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='surveys.eventsurveyquestion')),
            ],
        ),
    ]
