from django.urls import path

from chefs.api import waitlist as waitlist_api
from chefs.api import dashboard as dashboard_api
from chefs.api import clients as clients_api
from chefs.api import analytics as analytics_api
from chefs.api import leads as leads_api
from chefs.api import unified_clients as unified_api
from chefs.api import sous_chef as sous_chef_api
from chefs.api import availability as availability_api
from chefs.api import workspace as workspace_api
from chefs.api import onboarding as onboarding_api
from chefs.api import proactive as proactive_api
from chefs.api import notifications as notifications_api
from chefs.api import meal_plans as meal_plans_api
from chefs.api import payment_links as payment_links_api
from chefs.api import documents as documents_api
from chefs.api import receipts as receipts_api
from chefs.api import verification_meeting as meeting_api
from chefs.api import mehko as mehko_api
from chefs.api import telegram_views as telegram_api
from chefs.api import telegram_webhook
from chefs.resource_planning import views as prep_plan_api
from . import views


app_name = 'chefs'

urlpatterns = [
    # Chef Availability API
    path('api/availability/', availability_api.check_chef_availability, name='check_chef_availability'),
    path('api/availability/check/', availability_api.check_area_chef_availability, name='check_area_chef_availability'),
    
    # Area Waitlist API
    path('api/area-waitlist/join/', availability_api.join_area_waitlist, name='join_area_waitlist'),
    path('api/area-waitlist/leave/', availability_api.leave_area_waitlist, name='leave_area_waitlist'),
    path('api/area-waitlist/status/', availability_api.area_waitlist_status, name='area_waitlist_status'),
    
    # Public API
    path('api/public/<int:chef_id>/', views.chef_public, name='chef_public'),
    path('api/public/by-username/<slug:slug>/', views.chef_public_by_username, name='chef_public_by_username'),
    path('api/lookup/by-username/<str:username>/', views.chef_lookup_by_username, name='chef_lookup_by_username'),
    path('api/public/', views.chef_public_directory, name='chef_public_directory'),
    path('api/public/<int:chef_id>/serves-my-area/', views.chef_serves_my_area, name='chef_serves_my_area'),
    path('api/public/<int:chef_id>/stripe-status/', views.chef_stripe_status, name='chef_stripe_status'),
    
    # Waitlist API
    path('api/waitlist/config/', waitlist_api.waitlist_config, name='waitlist_config'),
    path('api/public/<int:chef_id>/waitlist/status/', waitlist_api.waitlist_status, name='waitlist_status'),
    path('api/public/<int:chef_id>/waitlist/subscribe', waitlist_api.waitlist_subscribe, name='waitlist_subscribe'),
    path('api/public/<int:chef_id>/waitlist/unsubscribe', waitlist_api.waitlist_unsubscribe, name='waitlist_unsubscribe'),
    
    # Gallery API - Public endpoints for chef photo galleries
    path('api/<str:username>/photos/', views.chef_gallery_photos, name='chef_gallery_photos'),
    path('api/<str:username>/gallery/stats/', views.chef_gallery_stats, name='chef_gallery_stats'),
    path('api/<str:username>/photos/<int:photo_id>/', views.chef_gallery_photo_detail, name='chef_gallery_photo_detail'),
    
    # React API endpoints for chef profile management
    path('api/me/chef/profile/', views.me_chef_profile, name='me_chef_profile'),
    path('api/me/chef/profile/update/', views.me_update_profile, name='me_update_profile'),
    path('api/me/chef/break/', views.me_set_break, name='me_set_break'),
    path('api/me/chef/live/', views.me_set_live, name='me_set_live'),

    # MEHKO/IFSI Compliance
    path('api/me/chef/mehko/', mehko_api.me_chef_mehko, name='me_chef_mehko'),
    path('api/mehko/requirements/', mehko_api.mehko_requirements, name='mehko_requirements'),
    path('api/mehko/fees/', mehko_api.mehko_fees, name='mehko_fees'),
    path('api/mehko/complaint-contact/', mehko_api.mehko_complaint_contact, name='mehko_complaint_contact'),
    path('api/mehko/accept-disclosure/', mehko_api.mehko_accept_disclosure, name='mehko_accept_disclosure'),
    path('api/mehko/disclosure-status/', mehko_api.mehko_disclosure_status, name='mehko_disclosure_status'),
    path('api/mehko/complaints/', mehko_api.mehko_submit_complaint, name='mehko_submit_complaint'),
    path('api/mehko/complaints/chef/<int:chef_id>/count/', mehko_api.mehko_complaint_count, name='mehko_complaint_count'),
    path('api/me/chef/photos/', views.me_upload_photo, name='me_upload_photo'),
    path('api/me/chef/photos/<int:photo_id>/', views.me_delete_photo, name='me_delete_photo'),
    
    # Chef-related endpoints
    path('api/check-chef-status/', views.check_chef_status, name='check_chef_status'),
    path('api/submit-chef-request/', views.submit_chef_request, name='submit_chef_request'),
    
    # ==========================================================================
    # Chef CRM Dashboard API Endpoints
    # ==========================================================================
    
    # Dashboard Summary
    path('api/me/dashboard/', dashboard_api.dashboard_summary, name='chef_dashboard'),
    
    # Client Management
    path('api/me/clients/', clients_api.client_list, name='chef_clients'),
    path('api/me/clients/<int:customer_id>/', clients_api.client_detail, name='chef_client_detail'),
    path('api/me/clients/<int:customer_id>/notes/', clients_api.client_notes, name='chef_client_notes'),
    
    # Revenue & Analytics
    path('api/me/revenue/', analytics_api.revenue_breakdown, name='chef_revenue'),
    path('api/me/orders/upcoming/', analytics_api.upcoming_orders, name='chef_upcoming_orders'),
    path('api/analytics/time-series/', analytics_api.time_series, name='chef_analytics_time_series'),
    
    # Lead Pipeline (CRM) - Contacts / Off-Platform Clients
    path('api/me/leads/', leads_api.lead_list, name='chef_leads'),
    path('api/me/leads/<int:lead_id>/', leads_api.lead_detail, name='chef_lead_detail'),
    path('api/me/leads/<int:lead_id>/interactions/', leads_api.lead_interactions, name='chef_lead_interactions'),
    path('api/me/leads/<int:lead_id>/household/', leads_api.lead_household_members, name='chef_lead_household'),
    path('api/me/leads/<int:lead_id>/household/<int:member_id>/', leads_api.lead_household_member_detail, name='chef_lead_household_detail'),
    
    # Email Verification for Manual Contacts
    path('api/me/leads/<int:lead_id>/send-verification/', leads_api.send_email_verification, name='chef_lead_send_verification'),
    path('api/me/leads/<int:lead_id>/verification-status/', leads_api.check_email_verification_status, name='chef_lead_verification_status'),
    
    # Public email verification endpoint
    path('api/verify-email/<str:token>/', leads_api.verify_email_token, name='verify_email_token'),
    
    # ==========================================================================
    # Chef Payment Links API
    # ==========================================================================
    
    path('api/me/payment-links/', payment_links_api.payment_link_list, name='chef_payment_links'),
    path('api/me/payment-links/stats/', payment_links_api.payment_link_stats, name='chef_payment_link_stats'),
    path('api/me/payment-links/<int:link_id>/', payment_links_api.payment_link_detail, name='chef_payment_link_detail'),
    path('api/me/payment-links/<int:link_id>/send/', payment_links_api.send_payment_link, name='chef_send_payment_link'),
    
    # Public payment link verification (for payers who may not be logged in)
    path('api/payment-links/<int:link_id>/verify/', payment_links_api.verify_payment_link, name='verify_payment_link'),
    
    # Unified Clients View (All Clients - Platform + Manual)
    path('api/me/all-clients/', unified_api.unified_client_list, name='chef_all_clients'),
    path('api/me/all-clients/<str:client_id>/', unified_api.unified_client_detail, name='chef_all_client_detail'),
    path('api/me/dietary-summary/', unified_api.dietary_summary, name='chef_dietary_summary'),
    
    # ==========================================================================
    # Sous Chef AI Assistant Endpoints
    # ==========================================================================
    
    # Streaming message endpoint
    path('api/me/sous-chef/stream/', sous_chef_api.sous_chef_stream_message, name='sous_chef_stream'),
    
    # Non-streaming message endpoint
    path('api/me/sous-chef/message/', sous_chef_api.sous_chef_send_message, name='sous_chef_message'),
    
    # Structured output message endpoint (new - returns JSON blocks)
    path('api/me/sous-chef/structured/', sous_chef_api.sous_chef_structured_message, name='sous_chef_structured'),
    
    # Start new conversation
    path('api/me/sous-chef/new-conversation/', sous_chef_api.sous_chef_new_conversation, name='sous_chef_new_conversation'),
    
    # Get conversation history for a family
    path('api/me/sous-chef/history/<str:family_type>/<int:family_id>/', sous_chef_api.sous_chef_thread_history, name='sous_chef_history'),
    
    # Get family context for display
    path('api/me/sous-chef/context/<str:family_type>/<int:family_id>/', sous_chef_api.sous_chef_family_context, name='sous_chef_context'),
    
    # Contextual suggestions endpoint
    path('api/me/sous-chef/suggest/', sous_chef_api.sous_chef_get_suggestions, name='sous_chef_suggest'),
    
    # Scaffold endpoints for meal creation
    path('api/me/sous-chef/scaffold/generate/', sous_chef_api.sous_chef_scaffold_generate, name='sous_chef_scaffold_generate'),
    path('api/me/sous-chef/scaffold/execute/', sous_chef_api.sous_chef_scaffold_execute, name='sous_chef_scaffold_execute'),

    # ==========================================================================
    # Sous Chef Workspace Settings API
    # ==========================================================================

    path('api/me/workspace/', workspace_api.workspace_get, name='chef_workspace'),
    path('api/me/workspace/update/', workspace_api.workspace_update, name='chef_workspace_update'),
    path('api/me/workspace/reset/', workspace_api.workspace_reset, name='chef_workspace_reset'),

    # ==========================================================================
    # Sous Chef Onboarding API
    # ==========================================================================

    path('api/me/onboarding/', onboarding_api.onboarding_get, name='chef_onboarding'),
    path('api/me/onboarding/welcomed/', onboarding_api.onboarding_welcomed, name='chef_onboarding_welcomed'),
    path('api/me/onboarding/start/', onboarding_api.onboarding_start, name='chef_onboarding_start'),
    path('api/me/onboarding/complete/', onboarding_api.onboarding_complete, name='chef_onboarding_complete'),
    path('api/me/onboarding/skip/', onboarding_api.onboarding_skip, name='chef_onboarding_skip'),
    path('api/me/onboarding/milestone/', onboarding_api.onboarding_milestone, name='chef_onboarding_milestone'),
    path('api/me/onboarding/tip/show/', onboarding_api.onboarding_tip_show, name='chef_onboarding_tip_show'),
    path('api/me/onboarding/tip/dismiss/', onboarding_api.onboarding_tip_dismiss, name='chef_onboarding_tip_dismiss'),
    path('api/me/onboarding/personality/', onboarding_api.onboarding_personality, name='chef_onboarding_personality'),

    # ==========================================================================
    # Sous Chef Proactive Settings API
    # ==========================================================================

    path('api/me/proactive/', proactive_api.proactive_get, name='chef_proactive'),
    path('api/me/proactive/update/', proactive_api.proactive_update, name='chef_proactive_update'),
    path('api/me/proactive/disable/', proactive_api.proactive_disable, name='chef_proactive_disable'),
    path('api/me/proactive/enable/', proactive_api.proactive_enable, name='chef_proactive_enable'),

    # ==========================================================================
    # Sous Chef Notifications API
    # ==========================================================================

    path('api/me/notifications/', notifications_api.notifications_list, name='chef_notifications'),
    path('api/me/notifications/unread-count/', notifications_api.notifications_unread_count, name='chef_notifications_unread_count'),
    path('api/me/notifications/mark-all-read/', notifications_api.notifications_mark_all_read, name='chef_notifications_mark_all_read'),
    path('api/me/notifications/dismiss-all/', notifications_api.notifications_dismiss_all, name='chef_notifications_dismiss_all'),
    path('api/me/notifications/<int:notification_id>/', notifications_api.notification_detail, name='chef_notification_detail'),
    path('api/me/notifications/<int:notification_id>/read/', notifications_api.notification_mark_read, name='chef_notification_read'),
    path('api/me/notifications/<int:notification_id>/dismiss/', notifications_api.notification_dismiss, name='chef_notification_dismiss'),

    # ==========================================================================
    # Collaborative Meal Plans API (Chef endpoints)
    # ==========================================================================
    
    # Client meal plans (accepts both int and prefixed IDs like "contact_123" or "platform_456")
    path('api/me/clients/<str:client_id>/plans/', meal_plans_api.client_plans, name='chef_client_plans'),
    
    # Plan management
    path('api/me/plans/<int:plan_id>/', meal_plans_api.plan_detail, name='chef_plan_detail'),
    path('api/me/plans/<int:plan_id>/publish/', meal_plans_api.publish_plan, name='chef_publish_plan'),
    path('api/me/plans/<int:plan_id>/archive/', meal_plans_api.archive_plan, name='chef_archive_plan'),
    path('api/me/plans/<int:plan_id>/unpublish/', meal_plans_api.unpublish_plan, name='chef_unpublish_plan'),

    # Plan days
    path('api/me/plans/<int:plan_id>/days/', meal_plans_api.add_plan_day, name='chef_add_plan_day'),
    path('api/me/plans/<int:plan_id>/days/<int:day_id>/', meal_plans_api.plan_day_detail, name='chef_plan_day_detail'),
    
    # Plan items
    path('api/me/plans/<int:plan_id>/days/<int:day_id>/items/', meal_plans_api.add_plan_item, name='chef_add_plan_item'),
    path('api/me/plans/<int:plan_id>/days/<int:day_id>/items/<int:item_id>/', meal_plans_api.plan_item_detail, name='chef_plan_item_detail'),
    
    # Suggestions management
    path('api/me/plans/<int:plan_id>/suggestions/', meal_plans_api.plan_suggestions, name='chef_plan_suggestions'),
    path('api/me/suggestions/<int:suggestion_id>/respond/', meal_plans_api.respond_to_suggestion, name='chef_respond_suggestion'),
    
    # AI meal generation (async)
    path('api/me/plans/<int:plan_id>/generate/', meal_plans_api.generate_meals_for_plan, name='chef_generate_meals'),
    path('api/me/plans/<int:plan_id>/generation-jobs/', meal_plans_api.list_generation_jobs, name='chef_list_generation_jobs'),
    path('api/me/generation-jobs/<int:job_id>/', meal_plans_api.get_generation_job_status, name='chef_generation_job_status'),
    
    # Chef's saved dishes
    path('api/me/dishes/', meal_plans_api.chef_dishes, name='chef_dishes'),
    
    # ==========================================================================
    # Chef Resource Planning / Prep Plan API
    # ==========================================================================
    
    # Prep Plan CRUD
    path('api/me/prep-plans/', prep_plan_api.prep_plan_list, name='chef_prep_plans'),
    path('api/me/prep-plans/<int:plan_id>/', prep_plan_api.prep_plan_detail, name='chef_prep_plan_detail'),
    path('api/me/prep-plans/<int:plan_id>/regenerate/', prep_plan_api.prep_plan_regenerate, name='chef_prep_plan_regenerate'),
    
    # Shopping List
    path('api/me/prep-plans/<int:plan_id>/shopping-list/', prep_plan_api.prep_plan_shopping_list, name='chef_prep_plan_shopping'),
    path('api/me/prep-plans/<int:plan_id>/mark-purchased/', prep_plan_api.mark_items_purchased, name='chef_mark_purchased'),
    path('api/me/prep-plans/<int:plan_id>/unmark-purchased/', prep_plan_api.unmark_items_purchased, name='chef_unmark_purchased'),
    
    # Batch Suggestions
    path('api/me/prep-plans/<int:plan_id>/batch-suggestions/', prep_plan_api.prep_plan_batch_suggestions, name='chef_batch_suggestions'),
    
    # Utility Endpoints
    path('api/me/ingredients/shelf-life/', prep_plan_api.shelf_life_lookup, name='chef_shelf_life'),
    path('api/me/prep-plans/quick-generate/', prep_plan_api.quick_generate_prep_plan, name='chef_quick_prep_plan'),
    path('api/me/prep-plans/summary/', prep_plan_api.prep_plan_summary, name='chef_prep_plan_summary'),

    # Live View Endpoints (no plan generation required)
    path('api/me/prep-plans/live/commitments/', prep_plan_api.live_commitments, name='chef_live_commitments'),
    path('api/me/prep-plans/live/shopping-list/', prep_plan_api.live_shopping_list, name='chef_live_shopping_list'),
    
    # ==========================================================================
    # Chef Verification Documents API
    # ==========================================================================
    
    # Document CRUD
    path('api/me/documents/', documents_api.verification_documents, name='chef_documents'),
    path('api/me/documents/<int:document_id>/', documents_api.verification_document_detail, name='chef_document_detail'),
    path('api/me/documents/status/', documents_api.verification_status, name='chef_verification_status'),
    
    # ==========================================================================
    # Chef Receipt Management API
    # ==========================================================================

    # Receipt CRUD
    path('api/me/receipts/', receipts_api.receipt_list, name='chef_receipts'),
    path('api/me/receipts/stats/', receipts_api.receipt_stats, name='chef_receipt_stats'),
    path('api/me/receipts/<int:receipt_id>/', receipts_api.receipt_detail, name='chef_receipt_detail'),
    path('api/me/clients/<int:customer_id>/receipts/', receipts_api.customer_receipts, name='chef_customer_receipts'),

    # ==========================================================================
    # Chef Verification Meeting API (Calendly Integration)
    # ==========================================================================

    # Public config (shows if feature is enabled)
    path('api/calendly-config/', meeting_api.calendly_config_public, name='calendly_config_public'),

    # Chef endpoints
    path('api/me/verification-meeting/', meeting_api.chef_meeting_status, name='chef_meeting_status'),
    path('api/me/verification-meeting/schedule/', meeting_api.chef_mark_scheduled, name='chef_mark_scheduled'),

    # Admin endpoints
    path('api/admin/calendly-config/', meeting_api.admin_calendly_config, name='admin_calendly_config'),
    path('api/admin/chefs/<int:chef_id>/meeting/complete/', meeting_api.admin_mark_meeting_complete, name='admin_mark_meeting_complete'),
    path('api/admin/meetings/pending/', meeting_api.admin_pending_meetings, name='admin_pending_meetings'),

    # ==========================================================================
    # Proactive Insights API
    # ==========================================================================
    
    path('api/me/insights/', views.chef_proactive_insights, name='chef_proactive_insights'),
    path('api/me/insights/<int:insight_id>/', views.chef_insight_action, name='chef_insight_action'),

    # ==========================================================================
    # Telegram Integration API
    # ==========================================================================
    
    path('api/telegram/generate-link/', telegram_api.telegram_generate_link, name='telegram_generate_link'),
    path('api/telegram/unlink/', telegram_api.telegram_unlink, name='telegram_unlink'),
    path('api/telegram/status/', telegram_api.telegram_status, name='telegram_status'),
    path('api/telegram/settings/', telegram_api.telegram_settings, name='telegram_settings'),
    
    # Telegram Webhook (public - validated via secret token header)
    path('api/telegram/webhook/', telegram_webhook.telegram_webhook, name='telegram_webhook'),
]