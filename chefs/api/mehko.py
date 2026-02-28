"""MEHKO/IFSI compliance API endpoints."""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.utils import timezone

from chefs.models import Chef
from chefs.serializers import ChefMehkoSerializer
from chefs.constants import COUNTY_ENFORCEMENT_AGENCIES
from custom_auth.models import UserRole


def _get_chef_or_error(request):
    """Get the authenticated user's Chef record, or return an error Response."""
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return None, Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)

    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return None, Response({'detail': 'Switch to chef mode'}, status=status.HTTP_403_FORBIDDEN)
    except UserRole.DoesNotExist:
        return None, Response({'detail': 'Switch to chef mode'}, status=status.HTTP_403_FORBIDDEN)

    return chef, None


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me_chef_mehko(request):
    """
    GET: Return current MEHKO compliance status.
    PATCH: Update MEHKO fields and auto-compute mehko_active.
    """
    chef, error = _get_chef_or_error(request)
    if error:
        return error

    if request.method == 'GET':
        serializer = ChefMehkoSerializer(chef)
        return Response(serializer.data)

    # PATCH
    serializer = ChefMehkoSerializer(chef, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()

    # Capture consent audit trail if consent was just given
    if 'mehko_consent' in request.data and request.data['mehko_consent'] and not chef.mehko_consent_at:
        chef.mehko_consent_at = timezone.now()
        # Get client IP (handles reverse proxies)
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        chef.mehko_consent_ip = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')
        chef.save(update_fields=['mehko_consent_at', 'mehko_consent_ip'])

    # Re-check eligibility and update mehko_active
    eligible, missing = chef.check_mehko_eligibility()
    chef.mehko_active = eligible
    chef.save(update_fields=['mehko_active'])

    # Re-serialize to include updated mehko_active and missing_requirements
    result = ChefMehkoSerializer(chef)
    return Response(result.data)


# ---- Consumer-facing disclosure endpoints ----

MEHKO_REQUIREMENTS_CONTENT = {
    'what_is_mehko': (
        "A Microenterprise Home Kitchen Operation (MEHKO) is a home-based food business "
        "permitted under California's AB 626 and AB 1325. MEHKO operators prepare and sell "
        "food directly from their home kitchens, subject to local health department oversight."
    ),
    'food_safety': (
        "All MEHKO operators must hold a valid food handler certificate and a permit from "
        "their local county health department. Food must be prepared and served on the same day. "
        "Home kitchens are subject to inspection by the local enforcement agency."
    ),
    'consumer_rights': (
        "As a consumer, you have the right to: know the chef's permit number and issuing agency; "
        "file a complaint with the platform or directly with the local enforcement agency; "
        "and receive clear information about fees before placing an order."
    ),
    'meal_limits': (
        "MEHKO operators are limited to 30 meals per day and 90 meals per week. "
        "Annual gross sales are capped at $100,000."
    ),
    'delivery_info': (
        "Food from a MEHKO must be delivered by the operator or a member of their household. "
        "Third-party delivery services are not permitted, except as a disability accommodation."
    ),
    'disclaimer': (
        "This food is prepared in a home kitchen that is permitted by the local enforcement "
        "agency. It has not been prepared in a commercial kitchen or restaurant."
    ),
}


@api_view(['GET'])
@permission_classes([AllowAny])
def mehko_requirements(request):
    """Return MEHKO/CDPH requirements in plain language."""
    return Response(MEHKO_REQUIREMENTS_CONTENT)


@api_view(['GET'])
@permission_classes([AllowAny])
def mehko_fees(request):
    """Return platform fee structure for transparency."""
    from django.conf import settings
    return Response({
        'platform_fee_percent': getattr(settings, 'MEHKO_PLATFORM_FEE_PERCENT', 10),
        'payment_processing': 'Stripe standard processing fees apply (approximately 2.9% + $0.30)',
        'additional_fees': 'None',
        'note': 'All fees are displayed before checkout. No hidden charges.',
        # §114367.6(a)(4): disclose platform liability insurance status
        'platform_liability_insurance': getattr(settings, 'MEHKO_PLATFORM_HAS_LIABILITY_INSURANCE', False),
        'platform_insurance_note': (
            'Sautai does not currently carry liability insurance covering incidents '
            'arising from food sold through the platform. Individual MEHKO operators '
            'may carry their own liability insurance.'
        ),
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def mehko_complaint_contact(request):
    """Return complaint contact info including county enforcement agencies."""
    return Response({
        'platform_email': 'complaints@sautai.com',
        'platform_form_url': '/mehko/complaints',
        'enforcement_agencies': COUNTY_ENFORCEMENT_AGENCIES,
        # §114367.6(a)(6): link to CDPH for filing complaints with enforcement agency
        'cdph_url': 'https://www.cdph.ca.gov/Programs/CEH/DFDCS/Pages/FDBPrograms/FoodSafetyProgram/MicroenterpriseHomeKitchenOperations.aspx',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mehko_accept_disclosure(request):
    """Record that user has accepted MEHKO disclosures."""
    user = request.user
    if not user.mehko_disclosure_accepted_at:
        user.mehko_disclosure_accepted_at = timezone.now()
        user.save(update_fields=['mehko_disclosure_accepted_at'])
    return Response({
        'accepted': True,
        'accepted_at': user.mehko_disclosure_accepted_at.isoformat(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mehko_disclosure_status(request):
    """Check if user has accepted MEHKO disclosures."""
    user = request.user
    accepted_at = getattr(user, 'mehko_disclosure_accepted_at', None)
    return Response({
        'accepted': accepted_at is not None,
        'accepted_at': accepted_at.isoformat() if accepted_at else None,
    })


# ---- Complaint pipeline ----

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mehko_submit_complaint(request):
    """Submit a food safety complaint against a MEHKO chef."""
    from chefs.models import MehkoComplaint
    from chefs.models.proactive import ChefNotification
    from chefs.serializers import MehkoComplaintSerializer
    from datetime import timedelta

    serializer = MehkoComplaintSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    chef = Chef.objects.get(id=data['chef_id'])

    complaint = MehkoComplaint.objects.create(
        chef=chef,
        complainant=request.user,
        complaint_text=data['complaint_text'],
        incident_date=data.get('incident_date'),
    )

    # Check threshold after creation (§114367.6(a)(7): 3+ unrelated in calendar year)
    year = timezone.now().year
    distinct_count = MehkoComplaint.distinct_complainants_in_calendar_year(chef, year)
    if distinct_count >= 3:
        # Dedup by count bracket so we notify at 3, but not again until next distinct complainant
        dedup_key = f"complaint_threshold_{chef.id}_{year}_n{distinct_count}"
        existing = ChefNotification.objects.filter(
            chef=chef,
            notification_type=ChefNotification.TYPE_COMPLAINT_THRESHOLD,
            dedup_key=dedup_key,
        ).exists()
        if not existing:
            total = MehkoComplaint.complaints_in_calendar_year(chef, year)
            # Calculate 2-week reporting deadline per §114367.6(a)(7)
            report_deadline = (timezone.now() + timedelta(weeks=2)).date()
            ChefNotification.objects.create(
                chef=chef,
                notification_type=ChefNotification.TYPE_COMPLAINT_THRESHOLD,
                title="⚠️ MEHKO Complaint Threshold — Report Required",
                message=(
                    f"Chef {chef.user.get_full_name() or chef.user.username} has "
                    f"{total} complaints ({distinct_count} distinct complainants) "
                    f"in calendar year {year}. "
                    f"Permit #{chef.permit_number}, Agency: {chef.permitting_agency}. "
                    f"County: {chef.county}. "
                    f"LEGAL DEADLINE: Report to enforcement agency by {report_deadline.strftime('%B %d, %Y')} "
                    f"(2 weeks from third complaint per §114367.6(a)(7))."
                ),
                dedup_key=dedup_key,
            )

    return Response({
        'id': complaint.id,
        'message': 'Complaint submitted successfully.',
    }, status=201)


@api_view(['GET'])
@permission_classes([AllowAny])
def mehko_complaint_count(request, chef_id):
    """Return complaint count for a chef (public, no details)."""
    from chefs.models import MehkoComplaint

    try:
        chef = Chef.objects.get(id=chef_id)
    except Chef.DoesNotExist:
        return Response({'error': 'Chef not found'}, status=404)

    count = MehkoComplaint.complaints_in_calendar_year(chef)
    return Response({
        'count': count,
    })
