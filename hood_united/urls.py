"""
URL configuration for hood_united project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.conf.urls.static import static
from django.conf import settings
from meals.api_dashboard_views import chef_dashboard
from chefs.api.telegram_webhook import telegram_webhook


urlpatterns = [
    # Simple health check endpoint for load balancers and CI smoke tests
    path('healthz/', lambda request: HttpResponse('ok'), name='healthz'),
    path('admin/', admin.site.urls),
    # API endpoints including QStash cron triggers
    path('api/', include('api.urls')),
    # Telegram webhook at /api/ prefix for Azure SWA linked backend routing
    path('api/telegram/webhook/', telegram_webhook, name='telegram_webhook_swa'),
    path('chefs/', include('chefs.urls')),
    path('chef_admin/', include('chef_admin.urls')),
    path('customer_dashboard/', include('customer_dashboard.urls')),
    path('auth/', include('custom_auth.urls')),
    path('meals/', include('meals.urls')),
    path('chef/api/dashboard/', chef_dashboard, name='chef_dashboard_api'),
    path('services/', include('chef_services.urls')),
    path('reviews/', include('reviews.urls')),
    path('local_chefs/', include('local_chefs.urls')),
    path('crm/', include('crm.urls')),
    path('memberships/', include('memberships.urls')),
    path('messaging/', include('messaging.urls')),
    path('surveys/', include('surveys.urls')),
]

# Serve media files in development only
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Static files are automatically served by Django's development server when DEBUG=True
