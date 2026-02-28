"""
Chef Verification Document API Endpoints

Provides endpoints for chefs to upload and manage their verification documents
(insurance, food handler certificates, background checks, etc.)
"""
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from chefs.models import Chef, ChefVerificationDocument
from chefs.serializers import (
    ChefVerificationDocumentSerializer,
    ChefVerificationDocumentUploadSerializer,
)
from custom_auth.models import UserRole


def _get_chef_or_403(request):
    """Helper to get chef for current user, ensuring chef mode is active."""
    try:
        chef = Chef.objects.get(user=request.user)
    except Chef.DoesNotExist:
        return None, Response({'detail': 'Not a chef'}, status=status.HTTP_404_NOT_FOUND)
    
    try:
        user_role = UserRole.objects.get(user=request.user)
        if not user_role.is_chef or user_role.current_role != 'chef':
            return None, Response(
                {'detail': 'Switch to chef mode to access documents'},
                status=status.HTTP_403_FORBIDDEN
            )
    except UserRole.DoesNotExist:
        return None, Response(
            {'detail': 'Switch to chef mode to access documents'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    return chef, None


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def verification_documents(request):
    """
    GET: List all verification documents for the authenticated chef.
    POST: Upload a new verification document.
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    if request.method == 'GET':
        documents = ChefVerificationDocument.objects.filter(chef=chef)
        
        # Optional filtering by doc_type
        doc_type = request.query_params.get('doc_type')
        if doc_type:
            documents = documents.filter(doc_type=doc_type)
        
        serializer = ChefVerificationDocumentSerializer(
            documents, many=True, context={'request': request}
        )
        return Response({
            'documents': serializer.data,
            'counts': {
                'total': documents.count(),
                'approved': documents.filter(is_approved=True).count(),
                'pending': documents.filter(is_approved=False, rejected_reason='').count(),
                'rejected': documents.exclude(rejected_reason='').count(),
            }
        })
    
    elif request.method == 'POST':
        serializer = ChefVerificationDocumentUploadSerializer(data=request.data)
        if serializer.is_valid():
            document = serializer.save(chef=chef)
            return Response(
                ChefVerificationDocumentSerializer(document, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def verification_document_detail(request, document_id):
    """
    GET: Get details of a specific verification document.
    DELETE: Delete a verification document (only if not yet approved).
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    document = get_object_or_404(ChefVerificationDocument, id=document_id, chef=chef)
    
    if request.method == 'GET':
        serializer = ChefVerificationDocumentSerializer(document, context={'request': request})
        return Response(serializer.data)
    
    elif request.method == 'DELETE':
        # Only allow deletion if not approved (pending or rejected)
        if document.is_approved:
            return Response(
                {'detail': 'Cannot delete an approved document. Contact support for assistance.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verification_status(request):
    """
    Get the overall verification status for the chef.
    Shows which document types are approved, pending, or missing.
    """
    chef, error_response = _get_chef_or_403(request)
    if error_response:
        return error_response
    
    documents = ChefVerificationDocument.objects.filter(chef=chef)
    
    # Get status for each document type
    doc_types = ['insurance', 'background', 'food_handlers', 'permit', 'other']
    status_data = {}
    
    for doc_type in doc_types:
        type_docs = documents.filter(doc_type=doc_type)
        approved = type_docs.filter(is_approved=True).first()
        pending = type_docs.filter(is_approved=False, rejected_reason='').first()
        rejected = type_docs.filter(is_approved=False).exclude(rejected_reason='').first()
        
        if approved:
            status_data[doc_type] = {
                'status': 'approved',
                'document_id': approved.id,
                'uploaded_at': approved.uploaded_at.isoformat(),
            }
        elif pending:
            status_data[doc_type] = {
                'status': 'pending',
                'document_id': pending.id,
                'uploaded_at': pending.uploaded_at.isoformat(),
            }
        elif rejected:
            status_data[doc_type] = {
                'status': 'rejected',
                'document_id': rejected.id,
                'uploaded_at': rejected.uploaded_at.isoformat(),
                'reason': rejected.rejected_reason,
            }
        else:
            status_data[doc_type] = {
                'status': 'missing',
                'document_id': None,
            }
    
    # Calculate overall readiness
    required_types = ['insurance', 'food_handlers']
    all_approved = all(
        status_data.get(t, {}).get('status') == 'approved'
        for t in required_types
    )
    
    return Response({
        'document_status': status_data,
        'chef_verified': chef.is_verified,
        'all_required_approved': all_approved,
        'required_types': required_types,
    })








