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
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def mehko_complaint_contact(request):
    """Return complaint contact info including county enforcement agencies."""
    return Response({
        'platform_email': 'complaints@sautai.com',
        'platform_form_url': '/mehko/complaints',
        'enforcement_agencies': COUNTY_ENFORCEMENT_AGENCIES,
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
