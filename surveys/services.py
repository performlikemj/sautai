"""
Survey generation services.

Handles creating default surveys from events (with per-dish questions)
and creating surveys from reusable templates.
"""

import logging

from .models import EventSurvey, EventSurveyQuestion, SurveyTemplate

logger = logging.getLogger(__name__)


def generate_default_survey(event, chef):
    """
    Generate a default survey for a ChefMealEvent.

    If the chef has a default template, use that. Otherwise:
    - If the event's meal has dishes, create a rating question per dish.
    - Otherwise, create a generic meal rating.
    Always adds an overall experience rating and a free-text comment question.

    Returns the created EventSurvey instance.
    """
    # Check for chef's default template first
    default_template = SurveyTemplate.objects.filter(
        chef=chef, is_default=True
    ).first()
    if default_template:
        return create_survey_from_template(default_template, event, chef)

    # Create the survey
    meal_name = event.meal.name if event.meal else "the meal"
    survey = EventSurvey.objects.create(
        chef=chef,
        event=event,
        title=f"Feedback: {meal_name} on {event.event_date}",
        description=f"We'd love to hear your thoughts on {meal_name}!",
        status='draft',
    )

    order = 1

    # Per-dish rating questions
    if event.meal:
        dishes = event.meal.dishes.all()
        if dishes.exists():
            for dish in dishes:
                EventSurveyQuestion.objects.create(
                    survey=survey,
                    question_text=f"How would you rate the {dish.name}?",
                    question_type='rating',
                    order=order,
                    is_required=True,
                    metadata={'dish_id': dish.id},
                )
                order += 1
        else:
            # No dishes — generic meal rating
            EventSurveyQuestion.objects.create(
                survey=survey,
                question_text=f"How would you rate {meal_name}?",
                question_type='rating',
                order=order,
                is_required=True,
            )
            order += 1

    # Overall experience rating
    EventSurveyQuestion.objects.create(
        survey=survey,
        question_text="How was the overall experience?",
        question_type='rating',
        order=order,
        is_required=True,
    )
    order += 1

    # Free-text feedback
    EventSurveyQuestion.objects.create(
        survey=survey,
        question_text="Any comments or feedback?",
        question_type='text',
        order=order,
        is_required=False,
    )

    logger.info(
        "Generated default survey %d for event %d (chef %d)",
        survey.id, event.id, chef.id,
    )
    return survey


def create_survey_from_template(template, event, chef):
    """
    Create an EventSurvey by copying questions from a SurveyTemplate.

    Returns the created EventSurvey instance.
    """
    title = template.title
    if event:
        meal_name = event.meal.name if event.meal else "Event"
        title = f"{template.title} — {meal_name} ({event.event_date})"

    survey = EventSurvey.objects.create(
        chef=chef,
        event=event,
        template=template,
        title=title,
        description=template.description,
        status='draft',
    )

    for q in template.questions.all():
        EventSurveyQuestion.objects.create(
            survey=survey,
            question_text=q.question_text,
            question_type=q.question_type,
            order=q.order,
            is_required=q.is_required,
            metadata=q.metadata,
        )

    logger.info(
        "Created survey %d from template %d for event %s (chef %d)",
        survey.id, template.id, event.id if event else 'None', chef.id,
    )
    return survey
