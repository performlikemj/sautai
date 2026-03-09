"""
Custom middleware for request processing.
"""
import re
import asyncio
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django.utils.decorators import sync_and_async_middleware
from utils.model_selection import choose_model, _get_groq_model
from utils.openai_helpers import token_length
from utils.redis_client import get, set, delete
import logging

logger = logging.getLogger(__name__)


# Regex patterns for Azure internal IPs (compiled once at module load)
INTERNAL_IP_PATTERNS = [
    re.compile(r'^10\.'),        # 10.x.x.x - Azure internal network
    re.compile(r'^100\.'),       # 100.x.x.x - Carrier Grade NAT (health probes)
    re.compile(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.'),  # 172.16-31.x.x - Private range
    re.compile(r'^192\.168\.'),  # 192.168.x.x - Private range
    re.compile(r'^127\.'),       # 127.x.x.x - Localhost
]


def _is_internal_ip(host):
    """Check if the host is an internal Azure IP."""
    host_ip = host.split(':')[0] if ':' in host else host
    return any(pattern.match(host_ip) for pattern in INTERNAL_IP_PATTERNS)


def _process_health_probe(request):
    """
    Process request for Azure health probes.
    Returns HttpResponse if handled, None to continue.
    """
    # Get the host from the request
    host = request.META.get('HTTP_HOST', '')
    path = getattr(request, 'path', 'unknown')
    
    # For internal IPs (Azure health probes, load balancer checks)
    if _is_internal_ip(host):
        # Health check paths - return 200 OK immediately, bypassing all other middleware
        if path in ('/healthz/', '/healthz', '/health/', '/health', '/'):
            return HttpResponse('ok', content_type='text/plain', status=200)
        
        # For other paths from internal IPs, rewrite the Host header
        # Store original for logging, then set to localhost
        request.META['HTTP_X_ORIGINAL_HOST'] = host
        request.META['HTTP_HOST'] = 'localhost'
        request.META['SERVER_NAME'] = 'localhost'
        # Also set X-Forwarded-Host which Django checks if USE_X_FORWARDED_HOST is True
        request.META['HTTP_X_FORWARDED_HOST'] = 'localhost'
    
    return None


@sync_and_async_middleware
def AzureHealthProbeMiddleware(get_response):
    """
    Middleware to handle Azure Container Apps health probes.
    
    Azure Container Apps health probes come from internal IPs (100.x.x.x, 10.x.x.x)
    that are not in ALLOWED_HOSTS. This middleware:
    1. Detects health probe requests (by path or internal IP)
    2. Returns a quick 200 OK response for /healthz/ path
    3. Rewrites the Host header for internal IPs so Django's SecurityMiddleware accepts them
    
    This middleware MUST be placed BEFORE django.middleware.security.SecurityMiddleware
    
    Uses @sync_and_async_middleware to properly support both WSGI and ASGI.
    """
    if asyncio.iscoroutinefunction(get_response):
        # Async mode (ASGI/Uvicorn)
        async def middleware(request):
            response = _process_health_probe(request)
            if response:
                return response
            return await get_response(request)
    else:
        # Sync mode (WSGI/Gunicorn)
        def middleware(request):
            response = _process_health_probe(request)
            if response:
                return response
            return get_response(request)
    
    return middleware

class ModelSelectionMiddleware(MiddlewareMixin):
    """
    Middleware that selects the appropriate OpenAI model based on:
    - User authentication status
    - Request complexity
    - User quotas
    - Conversation history complexity
    
    This allows API views to access the selected model through request.openai_model
    """
    
    def process_request(self, request):
        """
        Process the request to determine the appropriate model.
        """
        # Default to the configured Groq model
        default_model = _get_groq_model()
        
        # Extract the user (if authenticated)
        user_id = None
        is_guest = True
        guest_id = None  # Initialize guest_id to None
        
        if request.user and request.user.is_authenticated:
            user_id = request.user.id
            is_guest = False
        else:
            # Make sure session key exists for guests
            if not request.session.session_key:
                request.session.create()  # Force creation of a session key
            
            session_key = request.session.session_key
            
            # Check request.data for guest_id (for POST/PUT JSON requests)
            if hasattr(request, 'data') and isinstance(request.data, dict) and 'guest_id' in request.data:
                guest_id = request.data.get('guest_id')
                logger.info(f"MIDDLEWARE: Found guest_id {guest_id} in request.data")
            
            # Fallback to session if not in data
            if not guest_id:
                guest_id = request.session.get('guest_id')
                
            # If we're still missing guest_id, fall back to cookie-backed session_key
            if not guest_id:
                guest_id = session_key
            
            # Diagnostic logging
            logger.info(f"MIDDLEWARE: Session key: {session_key}, Guest ID: {guest_id}")
            
            # Use the guest_id from session if available, otherwise use session_key
            user_id = guest_id
        
        # Get request content (for complexity measurement)
        # Try common places where content might be found
        content = ''
        
        if request.method == 'POST':
            # For JSON API requests
            if hasattr(request, 'data') and request.data:
                if isinstance(request.data, dict) and 'message' in request.data:
                    content = request.data.get('message', '')
                elif isinstance(request.data, dict) and 'question' in request.data:
                    content = request.data.get('question', '')
            
            # For form submissions
            elif request.POST:
                content = request.POST.get('message', request.POST.get('question', ''))
        
        # Calculate conversation history tokens (last 10 turns from cache)
        history_tokens = 0
        if user_id:
            # Get conversation history from cache (keyed by user_id)
            conversation_key = f"conversation_history:{user_id}"
            history = get(conversation_key, [])
            
            # Calculate tokens from history (up to last 10 turns)
            history_slice = history[-10:] if len(history) > 10 else history
            history_tokens = sum(token_length(msg) for msg in history_slice)
            
            # Add current message to history for next time
            if content:
                if len(history) >= 50:  # Limit history to last 50 messages
                    history = history[-49:] 
                history.append(content)
                set(conversation_key, history, 86400)  # Store for 24 hours
        
        # Select the model
        if user_id and content:
            model = choose_model(user_id, is_guest, content, history_tokens)
        else:
            # If we can't determine content complexity, use the configured Groq model
            model = default_model
        
        # Attach to the request object for views to access
        request.openai_model = model


class CloudflareAccessMiddleware(MiddlewareMixin):
    """Block /admin/ access unless the request comes through Cloudflare Access."""

    def process_request(self, request):
        if not request.path.startswith('/admin/'):
            return None
        from django.conf import settings as django_settings
        if django_settings.DEBUG:
            return None
        if not request.META.get('HTTP_CF_ACCESS_JWT_ASSERTION', ''):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Access denied. Use admin.sautai.com.')
        return None