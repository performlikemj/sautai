"""
Survey email utilities.

Sends survey invitation emails to event attendees.
"""

import logging

from django.template.loader import render_to_string

from meals.models.chef_events import ChefMealOrder
from utils.email import send_html_email

logger = logging.getLogger(__name__)


def send_survey_emails(survey):
    """
    Send survey invitation emails to all attendees with completed orders.

    Returns the number of emails sent successfully.
    """
    if not survey.event:
        return 0

    # Get completed orders for this event
    orders = ChefMealOrder.objects.filter(
        meal_event=survey.event,
        status='completed',
    ).select_related('customer')

    # Collect unique emails
    recipients = {}
    for order in orders:
        email = order.customer.email
        if email and email not in recipients:
            recipients[email] = {
                'name': order.customer.get_full_name() or order.customer.username,
                'email': email,
            }

    chef_name = survey.chef.user.get_full_name() or survey.chef.user.username
    survey_url = survey.get_survey_url()
    meal_name = survey.event.meal.name if survey.event.meal else "the meal"

    sent = 0
    for recipient in recipients.values():
        try:
            html_content = render_to_string(
                'surveys/survey_invitation_email.html',
                {
                    'chef_name': chef_name,
                    'recipient_name': recipient['name'],
                    'meal_name': meal_name,
                    'event_date': survey.event.event_date.strftime('%B %d, %Y'),
                    'survey_url': survey_url,
                    'expires_at': (
                        survey.expires_at.strftime('%B %d, %Y')
                        if survey.expires_at
                        else None
                    ),
                },
            )
            success = send_html_email(
                subject=f"{chef_name} would love your feedback!",
                html_content=html_content,
                recipient_email=recipient['email'],
            )
            if success:
                sent += 1
        except Exception:
            logger.exception(
                "Failed to send survey email to %s for survey %d",
                recipient['email'],
                survey.id,
            )

    logger.info("Sent %d/%d survey emails for survey %d", sent, len(recipients), survey.id)
    return sent
