"""
Chef Lead Pipeline API endpoints.

Provides CRM lead management endpoints for tracking potential customers,
including email verification for off-platform client communications.
"""

import logging
import os

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from chefs.models import Chef
from crm.models import Lead, LeadInteraction, LeadHouseholdMember
from .serializers import (
    LeadListSerializer,
    LeadDetailSerializer,
    LeadUpdateSerializer,
    LeadCreateSerializer,
    LeadHouseholdMemberSerializer,
    LeadHouseholdMemberInputSerializer,
    ClientNoteInputSerializer,
    ClientNoteSerializer,
)

logger = logging.getLogger(__name__)


def _get_chef_or_403(request):
    """
    Get the Chef instance for the authenticated user.
    Returns (chef, None) on success, (None, Response) on failure.
    """
    try:
        chef = Chef.objects.get(user=request.user)
        return chef, None
    except Chef.DoesNotExist:
        return None, Response(
            {"error": "Not a chef. Only chefs can access leads."},
            status=403
        )


class LeadPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def lead_list(request):
    """
    GET /api/chefs/me/leads/
    
    Returns paginated list of leads for the chef's pipeline.
    
    Query Parameters:
    - status: Filter by status (new, contacted, qualified, won, lost)
    - source: Filter by source (web, referral, outbound, event, other)
    - is_priority: Filter by priority (true/false)
    - search: Search by name, email, or company
    - ordering: Sort field (created_at, last_interaction_at, -created_at, etc.)
    - page: Page number
    - page_size: Items per page (default: 20, max: 100)
    
    Response:
    ```json
    {
        "count": 15,
        "next": null,
        "previous": null,
        "results": [
            {
                "id": 1,
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "email": "john@example.com",
                "phone": "+1234567890",
                "company": "Acme Inc",
                "status": "qualified",
                "source": "web",
                "is_priority": true,
                "budget_cents": 50000,
                "last_interaction_at": "2024-03-10T14:30:00Z",
                "days_since_interaction": 5,
                "created_at": "2024-02-15T10:00:00Z"
            }
        ]
    }
    ```
    
    POST /api/chefs/me/leads/
    
    Creates a new lead.
    
    Request Body:
    ```json
    {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "+1234567890",
        "company": "Acme Inc",
        "source": "referral",
        "notes": "Referred by existing customer",
        "budget_cents": 50000
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    if request.method == 'POST':
        return _create_lead(request, chef)
    
    try:
        # Base queryset - leads owned by this chef
        leads = Lead.objects.filter(owner=chef.user, is_deleted=False)
        
        # Apply filters
        status = request.query_params.get('status')
        if status and status in dict(Lead.Status.choices):
            leads = leads.filter(status=status)
        
        source = request.query_params.get('source')
        if source and source in dict(Lead.Source.choices):
            leads = leads.filter(source=source)
        
        is_priority = request.query_params.get('is_priority')
        if is_priority is not None:
            leads = leads.filter(is_priority=is_priority.lower() == 'true')
        
        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            leads = leads.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(company__icontains=search)
            )
        
        # Apply ordering
        ordering = request.query_params.get('ordering', '-created_at')
        valid_orderings = [
            'created_at', '-created_at',
            'last_interaction_at', '-last_interaction_at',
            'status', '-status',
            'first_name', '-first_name',
        ]
        if ordering in valid_orderings:
            leads = leads.order_by(ordering)
        else:
            leads = leads.order_by('-created_at')
        
        # Paginate
        paginator = LeadPagination()
        try:
            page = paginator.paginate_queryset(leads, request)
        except NotFound:
            # Invalid page number - return empty paginated response
            return Response({
                "count": leads.count(),
                "next": None,
                "previous": None,
                "results": []
            })
        
        if page is not None:
            serializer = LeadListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = LeadListSerializer(leads, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.exception(f"Error fetching leads for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to fetch leads. Please try again."},
            status=500
        )


def _create_lead(request, chef):
    """Helper function to create a new lead (contact) with household members."""
    try:
        data = request.data.copy()
        
        # Validate required fields
        if not data.get('first_name'):
            return Response(
                {"error": "first_name is required"},
                status=400
            )
        
        # Extract household members before creating lead
        household_members_data = data.pop('household_members', [])
        
        # Create lead with dietary info
        lead = Lead.objects.create(
            owner=chef.user,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            company=data.get('company', ''),
            status=data.get('status', Lead.Status.NEW),
            source=data.get('source', Lead.Source.WEB),
            budget_cents=data.get('budget_cents'),
            notes=data.get('notes', ''),
            is_priority=data.get('is_priority', False),
            # New dietary/household fields
            household_size=data.get('household_size', 1),
            dietary_preferences=data.get('dietary_preferences', []),
            allergies=data.get('allergies', []),
            custom_allergies=data.get('custom_allergies', []),
            # Special dates for proactive notifications
            birthday_month=data.get('birthday_month'),
            birthday_day=data.get('birthday_day'),
            anniversary=data.get('anniversary'),
        )
        
        # Create household members
        for member_data in household_members_data:
            if member_data.get('name'):
                LeadHouseholdMember.objects.create(
                    lead=lead,
                    name=member_data.get('name', ''),
                    relationship=member_data.get('relationship', ''),
                    age=member_data.get('age'),
                    dietary_preferences=member_data.get('dietary_preferences', []),
                    allergies=member_data.get('allergies', []),
                    custom_allergies=member_data.get('custom_allergies', []),
                    notes=member_data.get('notes', ''),
                )
        
        serializer = LeadDetailSerializer(lead)
        return Response(serializer.data, status=201)
        
    except Exception as e:
        logger.exception(f"Error creating lead for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to create lead. Please try again."},
            status=500
        )


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def lead_detail(request, lead_id):
    """
    GET /api/chefs/me/leads/{lead_id}/
    
    Returns detailed lead information including interaction history.
    
    PATCH /api/chefs/me/leads/{lead_id}/
    
    Updates lead fields. Only status, is_priority, notes, and budget_cents can be updated.
    
    Request Body:
    ```json
    {
        "status": "qualified",
        "is_priority": true,
        "notes": "Updated notes..."
    }
    ```
    
    DELETE /api/chefs/me/leads/{lead_id}/
    
    Soft-deletes the lead.
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    # Verify lead exists and belongs to this chef
    try:
        lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
    except Lead.DoesNotExist:
        return Response({"error": "Lead not found."}, status=404)
    
    try:
        if request.method == 'GET':
            serializer = LeadDetailSerializer(lead)
            return Response(serializer.data)
        
        elif request.method == 'PATCH':
            serializer = LeadUpdateSerializer(lead, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(LeadDetailSerializer(lead).data)
            return Response(serializer.errors, status=400)
        
        elif request.method == 'DELETE':
            lead.is_deleted = True
            lead.save(update_fields=['is_deleted', 'updated_at'])
            return Response(status=204)
        
    except Exception as e:
        logger.exception(f"Error managing lead {lead_id} for chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to manage lead. Please try again."},
            status=500
        )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def lead_interactions(request, lead_id):
    """
    GET /api/chefs/me/leads/{lead_id}/interactions/
    
    Returns interaction history for a lead.
    
    POST /api/chefs/me/leads/{lead_id}/interactions/
    
    Adds a new interaction to the lead.
    
    Request Body:
    ```json
    {
        "summary": "Initial phone call",
        "details": "Discussed dining needs for corporate event...",
        "interaction_type": "call",
        "next_steps": "Send proposal by Friday"
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    # Verify lead exists and belongs to this chef
    try:
        lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
    except Lead.DoesNotExist:
        return Response({"error": "Lead not found."}, status=404)
    
    try:
        if request.method == 'GET':
            interactions = LeadInteraction.objects.filter(
                lead=lead,
                is_deleted=False
            ).order_by('-happened_at')
            
            serializer = ClientNoteSerializer(interactions, many=True)
            return Response(serializer.data)
        
        # POST - Create new interaction
        input_serializer = ClientNoteInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=400)
        
        data = input_serializer.validated_data
        
        interaction = LeadInteraction.objects.create(
            lead=lead,
            author=request.user,
            interaction_type=data['interaction_type'],
            summary=data['summary'],
            details=data.get('details', ''),
            next_steps=data.get('next_steps', ''),
            happened_at=timezone.now(),
        )
        
        output_serializer = ClientNoteSerializer(interaction)
        return Response(output_serializer.data, status=201)
        
    except Exception as e:
        logger.exception(f"Error managing lead interactions for lead {lead_id}, chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to manage lead interactions. Please try again."},
            status=500
        )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def lead_household_members(request, lead_id):
    """
    GET /api/chefs/me/leads/{lead_id}/household/
    
    Returns household members for a contact.
    
    POST /api/chefs/me/leads/{lead_id}/household/
    
    Adds a household member to the contact.
    
    Request Body:
    ```json
    {
        "name": "Jane Doe",
        "relationship": "spouse",
        "age": 35,
        "dietary_preferences": ["Vegetarian"],
        "allergies": ["Peanuts"],
        "notes": "Prefers spicy food"
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
    except Lead.DoesNotExist:
        return Response({"error": "Contact not found."}, status=404)
    
    try:
        if request.method == 'GET':
            members = lead.household_members.all()
            serializer = LeadHouseholdMemberSerializer(members, many=True)
            return Response(serializer.data)
        
        # POST - Create household member
        input_serializer = LeadHouseholdMemberInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=400)
        
        data = input_serializer.validated_data
        member = LeadHouseholdMember.objects.create(
            lead=lead,
            name=data.get('name', ''),
            relationship=data.get('relationship', ''),
            age=data.get('age'),
            dietary_preferences=data.get('dietary_preferences', []),
            allergies=data.get('allergies', []),
            custom_allergies=data.get('custom_allergies', []),
            notes=data.get('notes', ''),
        )
        
        # Update household size
        lead.household_size = lead.household_members.count() + 1  # +1 for primary contact
        lead.save(update_fields=['household_size', 'updated_at'])
        
        serializer = LeadHouseholdMemberSerializer(member)
        return Response(serializer.data, status=201)
        
    except Exception as e:
        logger.exception(f"Error managing household for lead {lead_id}, chef {chef.id}: {e}")
        return Response(
            {"error": "Failed to manage household members. Please try again."},
            status=500
        )


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def lead_household_member_detail(request, lead_id, member_id):
    """
    PATCH /api/chefs/me/leads/{lead_id}/household/{member_id}/
    
    Updates a household member.
    
    DELETE /api/chefs/me/leads/{lead_id}/household/{member_id}/
    
    Removes a household member.
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
    except Lead.DoesNotExist:
        return Response({"error": "Contact not found."}, status=404)
    
    try:
        member = LeadHouseholdMember.objects.get(id=member_id, lead=lead)
    except LeadHouseholdMember.DoesNotExist:
        return Response({"error": "Household member not found."}, status=404)
    
    try:
        if request.method == 'PATCH':
            serializer = LeadHouseholdMemberInputSerializer(data=request.data, partial=True)
            if not serializer.is_valid():
                return Response(serializer.errors, status=400)
            
            data = serializer.validated_data
            for key, value in data.items():
                setattr(member, key, value)
            member.save()
            
            return Response(LeadHouseholdMemberSerializer(member).data)
        
        elif request.method == 'DELETE':
            member.delete()
            
            # Update household size
            lead.household_size = max(1, lead.household_members.count() + 1)
            lead.save(update_fields=['household_size', 'updated_at'])
            
            return Response(status=204)
        
    except Exception as e:
        logger.exception(f"Error managing household member {member_id} for lead {lead_id}: {e}")
        return Response(
            {"error": "Failed to manage household member. Please try again."},
            status=500
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_email_verification(request, lead_id):
    """
    POST /api/chefs/me/leads/{lead_id}/send-verification/
    
    Sends an email verification link to the lead's email address.
    The lead must have a valid email address to receive verification.
    
    Response:
    ```json
    {
        "status": "success",
        "message": "Verification email sent to john@example.com"
    }
    ```
    
    Errors:
    - 400: No email address on lead
    - 400: Email already verified
    - 404: Lead not found
    - 429: Verification email sent too recently (wait 5 minutes)
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
    except Lead.DoesNotExist:
        return Response({"error": "Contact not found."}, status=404)
    
    try:
        # Validate email exists
        if not lead.email:
            return Response(
                {"error": "This contact does not have an email address."},
                status=400
            )
        
        # Check if already verified
        if lead.email_verified:
            return Response(
                {"error": "This email address has already been verified."},
                status=400
            )
        
        # Rate limiting: prevent spam (5 minute cooldown)
        if lead.email_verification_sent_at:
            from datetime import timedelta
            cooldown = timedelta(minutes=5)
            if timezone.now() - lead.email_verification_sent_at < cooldown:
                remaining = int((lead.email_verification_sent_at + cooldown - timezone.now()).total_seconds() // 60)
                return Response(
                    {"error": f"Please wait {remaining + 1} minute(s) before requesting another verification email."},
                    status=429
                )
        
        # Generate token
        token = lead.generate_verification_token()
        
        # Build verification URL
        frontend_url = os.getenv('STREAMLIT_URL', 'http://localhost:8501')
        verification_url = f"{frontend_url}/verify-email/{token}"
        
        # Send verification email
        _send_verification_email(lead, chef, verification_url)
        
        logger.info(f"Email verification sent to {lead.email} for lead {lead.id} by chef {chef.id}")
        
        return Response({
            "status": "success",
            "message": f"Verification email sent to {lead.email}"
        })
        
    except Exception as e:
        logger.exception(f"Error sending email verification for lead {lead_id}: {e}")
        return Response(
            {"error": "Failed to send verification email. Please try again."},
            status=500
        )


def _send_verification_email(lead, chef, verification_url):
    """
    Send the email verification email using the notification assistant.
    """
    try:
        from meals.meal_assistant_implementation import MealPlanningAssistant
        
        chef_name = chef.user.get_full_name() or chef.user.username
        recipient_name = f"{lead.first_name} {lead.last_name}".strip() or "there"
        
        message_content = (
            f"Please send an email verification message to {recipient_name}. "
            f"Chef {chef_name} has added them as a client and wants to send them "
            f"payment links and invoices. They need to verify their email address first. "
            f"The verification link is: {verification_url} "
            f"The link expires in 72 hours. "
            f"Make it clear this is from {chef_name} via the sautai platform."
        )
        
        result = MealPlanningAssistant.send_notification_via_assistant(
            user_id=None,  # Lead is not a platform user
            message_content=message_content,
            subject=f"Verify your email for {chef_name}",
            template_key='client_email_verification',
            template_context={
                'recipient_name': recipient_name,
                'chef_name': chef_name,
                'verification_url': verification_url,
            },
            recipient_email=lead.email,
        )
        
        if result.get('status') != 'success':
            logger.error(f"Failed to send verification email: {result}")
            raise Exception("Email service returned error")
            
    except Exception as e:
        logger.exception(f"Error in _send_verification_email: {e}")
        # Fall back to simple email if MealPlanningAssistant fails
        _send_simple_verification_email(lead, chef, verification_url)


def _send_simple_verification_email(lead, chef, verification_url):
    """
    Fallback simple email sender for verification.
    """
    import requests
    
    n8n_webhook_url = os.getenv('N8N_EMAIL_WEBHOOK_URL')
    if not n8n_webhook_url:
        logger.warning("N8N_EMAIL_WEBHOOK_URL not configured, skipping fallback email")
        return
    
    chef_name = chef.user.get_full_name() or chef.user.username
    recipient_name = f"{lead.first_name} {lead.last_name}".strip() or "there"
    
    html_body = render_to_string('meals/client_email_verification.html', {
        'recipient_name': recipient_name,
        'chef_name': chef_name,
        'verification_url': verification_url,
    })
    
    email_data = {
        'to': lead.email,
        'subject': f"Verify your email for {chef_name}",
        'html_body': html_body,
    }
    
    try:
        requests.post(n8n_webhook_url, json=email_data, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send fallback verification email: {e}")


@api_view(['GET'])
@permission_classes([AllowAny])
def verify_email_token(request, token):
    """
    GET /api/verify-email/{token}/
    
    Public endpoint to verify an email address using the token sent via email.
    
    Response on success:
    ```json
    {
        "status": "success",
        "message": "Your email has been verified successfully!"
    }
    ```
    
    Response on error:
    ```json
    {
        "status": "error",
        "message": "Invalid or expired verification link."
    }
    ```
    """
    if not token or len(token) < 32:
        return Response({
            "status": "error",
            "message": "Invalid verification link."
        }, status=400)
    
    try:
        # Find lead with this token
        lead = Lead.objects.filter(
            email_verification_token=token,
            is_deleted=False
        ).first()
        
        if not lead:
            return Response({
                "status": "error",
                "message": "Invalid or expired verification link."
            }, status=400)
        
        # Verify the token
        if lead.verify_email(token):
            logger.info(f"Email verified for lead {lead.id}: {lead.email}")
            return Response({
                "status": "success",
                "message": "Your email has been verified successfully! You can now receive payment links and invoices."
            })
        else:
            return Response({
                "status": "error",
                "message": "This verification link has expired. Please request a new one."
            }, status=400)
            
    except Exception as e:
        logger.exception(f"Error verifying email token: {e}")
        return Response({
            "status": "error",
            "message": "An error occurred. Please try again later."
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_email_verification_status(request, lead_id):
    """
    GET /api/chefs/me/leads/{lead_id}/verification-status/
    
    Check the email verification status of a lead.
    
    Response:
    ```json
    {
        "has_email": true,
        "email": "john@example.com",
        "email_verified": true,
        "email_verified_at": "2024-03-15T10:30:00Z",
        "verification_sent_at": "2024-03-14T10:30:00Z",
        "can_resend": false
    }
    ```
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    try:
        lead = Lead.objects.get(id=lead_id, owner=chef.user, is_deleted=False)
    except Lead.DoesNotExist:
        return Response({"error": "Contact not found."}, status=404)
    
    # Check if can resend (5 minute cooldown)
    can_resend = True
    if lead.email_verification_sent_at:
        from datetime import timedelta
        cooldown = timedelta(minutes=5)
        can_resend = timezone.now() - lead.email_verification_sent_at >= cooldown
    
    return Response({
        "has_email": bool(lead.email),
        "email": lead.email or None,
        "email_verified": lead.email_verified,
        "email_verified_at": lead.email_verified_at.isoformat() if lead.email_verified_at else None,
        "verification_sent_at": lead.email_verification_sent_at.isoformat() if lead.email_verification_sent_at else None,
        "can_resend": can_resend and not lead.email_verified and bool(lead.email),
    })

