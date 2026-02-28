"""MEHKO/IFSI compliance API endpoints."""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chefs.models import Chef
from chefs.serializers import ChefMehkoSerializer
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
