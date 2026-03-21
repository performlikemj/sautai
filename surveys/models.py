"""
Survey system models for post-event feedback collection.

Provides customizable surveys that chefs can send to attendees after events.
Supports reusable templates, per-dish rating questions, and public token-based access.
"""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class SurveyTemplate(models.Model):
    """Reusable survey template owned by a chef."""

    chef = models.ForeignKey(
        'chefs.Chef', on_delete=models.CASCADE, related_name='survey_templates'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(
        default=False,
        help_text="If True, this template is used as the chef's default for new surveys.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} (Chef: {self.chef})"

    def save(self, *args, **kwargs):
        # Enforce only one default per chef
        if self.is_default:
            SurveyTemplate.objects.filter(chef=self.chef, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)
        super().save(*args, **kwargs)


QUESTION_TYPE_CHOICES = [
    ('rating', 'Rating (1-5 stars)'),
    ('text', 'Text'),
    ('yes_no', 'Yes / No'),
]


class SurveyQuestion(models.Model):
    """A question within a reusable survey template."""

    template = models.ForeignKey(
        SurveyTemplate, on_delete=models.CASCADE, related_name='questions'
    )
    question_text = models.CharField(max_length=500)
    question_type = models.CharField(max_length=10, choices=QUESTION_TYPE_CHOICES)
    order = models.PositiveIntegerField()
    is_required = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['order']
        unique_together = ('template', 'order')

    def __str__(self):
        return f"Q{self.order}: {self.question_text[:60]}"


class EventSurvey(models.Model):
    """A survey instance tied to a specific chef event, with a public access token."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ]

    chef = models.ForeignKey(
        'chefs.Chef', on_delete=models.CASCADE, related_name='event_surveys'
    )
    event = models.ForeignKey(
        'meals.ChefMealEvent',
        on_delete=models.CASCADE,
        related_name='surveys',
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        SurveyTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Source template this survey was created from.",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    access_token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')

    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_send_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        event_str = f" for {self.event}" if self.event else ""
        return f"{self.title}{event_str}"

    def is_expired(self):
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    def can_accept_responses(self):
        return self.status == 'active' and not self.is_expired()

    def get_survey_url(self):
        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://www.sautai.com')
        return f"{frontend_url}/survey/{self.access_token}"


class EventSurveyQuestion(models.Model):
    """A question within a specific event survey (copied from template, editable per-event)."""

    survey = models.ForeignKey(
        EventSurvey, on_delete=models.CASCADE, related_name='questions'
    )
    question_text = models.CharField(max_length=500)
    question_type = models.CharField(max_length=10, choices=QUESTION_TYPE_CHOICES)
    order = models.PositiveIntegerField()
    is_required = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Q{self.order}: {self.question_text[:60]}"


class SurveyResponse(models.Model):
    """A single respondent's submission to an event survey."""

    survey = models.ForeignKey(
        EventSurvey, on_delete=models.CASCADE, related_name='responses'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    respondent_email = models.EmailField(blank=True)
    respondent_name = models.CharField(max_length=200, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        constraints = [
            models.UniqueConstraint(
                fields=['survey', 'customer'],
                condition=models.Q(customer__isnull=False),
                name='unique_survey_response_per_customer',
            ),
        ]

    def __str__(self):
        who = self.respondent_name or self.respondent_email or str(self.customer or 'Anonymous')
        return f"Response to {self.survey} by {who}"


class QuestionResponse(models.Model):
    """An individual answer to a question within a survey response."""

    response = models.ForeignKey(
        SurveyResponse, on_delete=models.CASCADE, related_name='answers'
    )
    question = models.ForeignKey(
        EventSurveyQuestion, on_delete=models.CASCADE, related_name='answers'
    )
    rating_value = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    text_value = models.TextField(blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)

    def __str__(self):
        return f"Answer to Q{self.question.order}"
