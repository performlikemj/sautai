"""
Survey API endpoints.

Chef-authenticated endpoints for managing surveys and templates.
Public token-based endpoints for filling out surveys.
"""

import logging

from django.db import models
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chefs.models import Chef
from meals.models.chef_events import ChefMealEvent

from .emails import send_survey_emails
from .models import (
    EventSurvey,
    EventSurveyQuestion,
    QuestionResponse,
    SurveyQuestion,
    SurveyResponse,
    SurveyTemplate,
)
from .serializers import (
    EventSurveySerializer,
    EventSurveyUpdateSerializer,
    PublicSurveySerializer,
    SurveyResponseSerializer,
    SurveySubmitSerializer,
    SurveyTemplateSerializer,
    SurveyTemplateWriteSerializer,
)
from .services import create_survey_from_template, generate_default_survey

logger = logging.getLogger(__name__)


def _get_chef_or_403(request):
    """Get the Chef instance for the authenticated user."""
    try:
        chef = Chef.objects.get(user=request.user)
        return chef, None
    except Chef.DoesNotExist:
        return None, Response(
            {"error": "Not a chef. Only chefs can access surveys."},
            status=403,
        )


# =============================================================================
# Chef Survey CRUD
# =============================================================================


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def survey_list(request):
    """
    GET  — List all surveys for the chef.
    POST — Create a new survey for an event (auto-generates default questions).

    POST body:
        {
            "event_id": 123,              // required
            "template_id": 456,           // optional — use template instead of default
        }
    """
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    if request.method == 'GET':
        surveys = EventSurvey.objects.filter(chef=chef).select_related('event', 'template')
        status_filter = request.query_params.get('status')
        if status_filter:
            surveys = surveys.filter(status=status_filter)
        data = EventSurveySerializer(surveys, many=True).data
        return Response(data)

    # POST — create survey
    event_id = request.data.get('event_id')
    if not event_id:
        return Response({"error": "event_id is required."}, status=400)

    try:
        event = ChefMealEvent.objects.get(id=event_id, chef=chef)
    except ChefMealEvent.DoesNotExist:
        return Response({"error": "Event not found."}, status=404)

    template_id = request.data.get('template_id')
    if template_id:
        try:
            template = SurveyTemplate.objects.get(id=template_id, chef=chef)
        except SurveyTemplate.DoesNotExist:
            return Response({"error": "Template not found."}, status=404)
        survey = create_survey_from_template(template, event, chef)
    else:
        survey = generate_default_survey(event, chef)

    return Response(EventSurveySerializer(survey).data, status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def survey_detail(request, survey_id):
    """
    GET    — Get survey detail with questions.
    PATCH  — Update survey (title, description, questions, expires_at). Only drafts.
    DELETE — Delete a draft survey.
    """
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    try:
        survey = EventSurvey.objects.get(id=survey_id, chef=chef)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    if request.method == 'GET':
        return Response(EventSurveySerializer(survey).data)

    if request.method == 'DELETE':
        if survey.status != 'draft':
            return Response({"error": "Only draft surveys can be deleted."}, status=400)
        survey.delete()
        return Response(status=204)

    # PATCH
    if survey.status == 'closed':
        return Response({"error": "Closed surveys cannot be edited."}, status=400)

    serializer = EventSurveyUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    if 'title' in data:
        survey.title = data['title']
    if 'description' in data:
        survey.description = data['description']
    if 'expires_at' in data:
        survey.expires_at = data['expires_at']
    survey.save()

    # Replace questions if provided
    if 'questions' in data:
        survey.questions.all().delete()
        for q_data in data['questions']:
            EventSurveyQuestion.objects.create(survey=survey, **q_data)

    return Response(EventSurveySerializer(survey).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def survey_activate(request, survey_id):
    """Set survey status from draft to active."""
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    try:
        survey = EventSurvey.objects.get(id=survey_id, chef=chef)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    if survey.status != 'draft':
        return Response({"error": "Only draft surveys can be activated."}, status=400)

    if not survey.questions.exists():
        return Response({"error": "Cannot activate a survey with no questions."}, status=400)

    survey.status = 'active'
    survey.save()
    return Response(EventSurveySerializer(survey).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def survey_close(request, survey_id):
    """Close the survey to new responses."""
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    try:
        survey = EventSurvey.objects.get(id=survey_id, chef=chef)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    if survey.status != 'active':
        return Response({"error": "Only active surveys can be closed."}, status=400)

    survey.status = 'closed'
    survey.save()
    return Response(EventSurveySerializer(survey).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def survey_send(request, survey_id):
    """Send survey link via email to event attendees with completed orders."""
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    try:
        survey = EventSurvey.objects.get(id=survey_id, chef=chef)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    if not survey.can_accept_responses():
        return Response(
            {"error": "Survey must be active and not expired to send emails."},
            status=400,
        )

    if not survey.event:
        return Response({"error": "Survey is not linked to an event."}, status=400)

    sent_count = send_survey_emails(survey)

    survey.email_sent_at = timezone.now()
    survey.email_send_count += 1
    survey.save()

    return Response({
        "message": f"Survey sent to {sent_count} attendee(s).",
        "sent_count": sent_count,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def survey_responses(request, survey_id):
    """List all responses for a survey with aggregated stats."""
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    try:
        survey = EventSurvey.objects.get(id=survey_id, chef=chef)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    responses = survey.responses.prefetch_related('answers__question').all()

    # Aggregate rating stats per question
    questions = survey.questions.all()
    question_stats = []
    for q in questions:
        stat = {'question_id': q.id, 'question_text': q.question_text, 'question_type': q.question_type}
        if q.question_type == 'rating':
            answers = QuestionResponse.objects.filter(
                question=q, response__survey=survey, rating_value__isnull=False
            )
            agg = answers.aggregate(
                avg=models.Avg('rating_value'),
                count=models.Count('id'),
            )
            stat['average_rating'] = round(agg['avg'], 2) if agg['avg'] else None
            stat['response_count'] = agg['count']
        else:
            stat['response_count'] = QuestionResponse.objects.filter(
                question=q, response__survey=survey,
            ).count()
        question_stats.append(stat)

    return Response({
        'survey': EventSurveySerializer(survey).data,
        'question_stats': question_stats,
        'responses': SurveyResponseSerializer(responses, many=True).data,
    })


# =============================================================================
# Chef Survey Templates
# =============================================================================


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def template_list(request):
    """
    GET  — List all survey templates for the chef.
    POST — Create a new template with nested questions.
    """
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    if request.method == 'GET':
        templates = SurveyTemplate.objects.filter(chef=chef).prefetch_related('questions')
        return Response(SurveyTemplateSerializer(templates, many=True).data)

    # POST
    serializer = SurveyTemplateWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save(chef=chef)
    return Response(SurveyTemplateSerializer(serializer.instance).data, status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def template_detail(request, template_id):
    """
    GET    — Get template detail with questions.
    PATCH  — Update template (title, description, is_default, questions).
    DELETE — Delete a template.
    """
    chef, error = _get_chef_or_403(request)
    if error:
        return error

    try:
        template = SurveyTemplate.objects.get(id=template_id, chef=chef)
    except SurveyTemplate.DoesNotExist:
        return Response({"error": "Template not found."}, status=404)

    if request.method == 'GET':
        return Response(SurveyTemplateSerializer(template).data)

    if request.method == 'DELETE':
        template.delete()
        return Response(status=204)

    # PATCH
    serializer = SurveyTemplateWriteSerializer(template, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(SurveyTemplateSerializer(serializer.instance).data)


# =============================================================================
# Public Survey Endpoints (No Auth)
# =============================================================================


@api_view(['GET'])
@permission_classes([])
def public_survey(request, token):
    """Get survey questions for the public form (no auth required)."""
    try:
        survey = EventSurvey.objects.get(access_token=token)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    if not survey.can_accept_responses():
        status_msg = "expired" if survey.is_expired() else "closed"
        return Response(
            {"error": f"This survey is {status_msg} and no longer accepting responses."},
            status=410,
        )

    return Response(PublicSurveySerializer(survey).data)


@api_view(['POST'])
@permission_classes([])
def public_survey_submit(request, token):
    """
    Submit a survey response (no auth required).

    Request body:
    {
        "respondent_email": "user@example.com",  // optional
        "respondent_name": "Jane Doe",            // optional
        "answers": [
            {"question_id": 1, "rating_value": 5},
            {"question_id": 2, "text_value": "Great food!"},
            {"question_id": 3, "boolean_value": true}
        ]
    }
    """
    try:
        survey = EventSurvey.objects.get(access_token=token)
    except EventSurvey.DoesNotExist:
        return Response({"error": "Survey not found."}, status=404)

    if not survey.can_accept_responses():
        status_msg = "expired" if survey.is_expired() else "closed"
        return Response(
            {"error": f"This survey is {status_msg} and no longer accepting responses."},
            status=410,
        )

    serializer = SurveySubmitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # Check for duplicate by email
    email = data.get('respondent_email', '').strip()
    if email and survey.responses.filter(respondent_email=email).exists():
        return Response(
            {"error": "A response with this email has already been submitted."},
            status=409,
        )

    # Create response
    response_obj = SurveyResponse.objects.create(
        survey=survey,
        respondent_email=email,
        respondent_name=data.get('respondent_name', '').strip(),
    )

    # Create question answers
    survey_question_ids = set(survey.questions.values_list('id', flat=True))
    for answer_data in data['answers']:
        question_id = answer_data['question_id']
        if question_id not in survey_question_ids:
            continue  # Skip invalid question IDs

        QuestionResponse.objects.create(
            response=response_obj,
            question_id=question_id,
            rating_value=answer_data.get('rating_value'),
            text_value=answer_data.get('text_value', ''),
            boolean_value=answer_data.get('boolean_value'),
        )

    return Response({"message": "Thank you for your feedback!"}, status=201)
