from django.contrib import admin
from django.utils.html import format_html
from meals.models import Meal  
from .models import (
    Chef,
    ChefRequest,
    ChefPostalCode,
    PostalCode,
    ChefPhoto,
    ChefDefaultBanner,
    ChefVerificationDocument,
    MehkoComplaint,
    ChefWaitlistConfig,
    ChefWaitlistSubscription,
    ChefAvailabilityState,
    ChefPaymentLink,
    PlatformCalendlyConfig,
    ChefVerificationMeeting,
)
from custom_auth.models import UserRole
from django.contrib import messages
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

class MealInline(admin.TabularInline):  # You can also use admin.StackedInline
    model = Meal
    extra = 1  # How many extra empty rows to display
    # Any other options you want to include
    exclude = ('meal_embedding',)

class ChefPostalCodeInline(admin.TabularInline):
    model = ChefPostalCode
    extra = 1  # Number of extra forms to display

class ChefAdmin(admin.ModelAdmin):
    list_display = ('user', 'experience', 'is_verified', 'is_live', 'background_checked', 'insured', 'food_handlers_cert', 'is_on_break')
    search_fields = ('user__username', 'experience', 'bio')
    list_filter = ('user__is_active', 'is_on_break', 'is_verified', 'is_live', 'background_checked', 'insured', 'food_handlers_cert', 'mehko_active')
    # Exclude the pgvector field from the editable form to avoid numpy truth-value issues
    fields = (
        'user', 'experience', 'bio', 'is_on_break', 'is_live', 'profile_pic', 'banner_image',
        'is_verified', 'background_checked', 'insured', 'insurance_expiry', 'food_handlers_cert',
        'permit_number', 'permitting_agency', 'permit_expiry', 'county',
        'mehko_consent', 'mehko_active',
    )
    readonly_fields = ()
    inlines = [MealInline, ChefPostalCodeInline]
    
    def save_model(self, request, obj, form, change):
        """
        Update UserRole when Chef is created or saved
        """
        try:
            super().save_model(request, obj, form, change)
            # Update or create UserRole for this user
            user_role, created = UserRole.objects.get_or_create(user=obj.user)
            user_role.is_chef = True
            user_role.current_role = 'chef'
            user_role.save()
        except Exception as e:
            self.message_user(request, f"Error saving: {str(e)}", level='ERROR')
            # Log the error for debugging
            logger = logging.getLogger(__name__)
            logger.error(f"Error saving Chef: {str(e)}")
            raise

admin.site.register(Chef, ChefAdmin)


class ChefRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_approved',)
    actions = ['approve_chef_requests']
    
    def save_model(self, request, obj, form, change):
        """
        Handle individual approval when admin checks is_approved checkbox
        """
        was_approved_before = False
        if change:  # If this is an update, not a new record
            try:
                original_obj = ChefRequest.objects.get(pk=obj.pk)
                was_approved_before = original_obj.is_approved
            except ChefRequest.DoesNotExist:
                pass
        
        # Save the ChefRequest first
        super().save_model(request, obj, form, change)
        
        # If the request was just approved (not already approved before)
        if obj.is_approved and not was_approved_before:
            try:
                with transaction.atomic():
                    # Try to get existing Chef or create a new one
                    chef, created = Chef.objects.get_or_create(
                        user=obj.user
                    )
                    
                    # Always update the Chef with data from ChefRequest
                    if obj.experience:
                        chef.experience = obj.experience
                    if obj.bio:
                        chef.bio = obj.bio
                    if obj.profile_pic:
                        chef.profile_pic = obj.profile_pic
                    
                    # Mark chef as verified upon approval
                    chef.is_verified = True
                    
                    # Save the chef object
                    chef.save()
                    
                    # Set postal codes if there are any
                    if obj.requested_postalcodes.exists():
                        chef.serving_postalcodes.set(obj.requested_postalcodes.all())
                        # Notify area waitlist users for each postal code
                        # (M2M .set() doesn't trigger post_save signals on through model)
                        from .tasks import notify_area_waitlist_users
                        chef_username = getattr(chef.user, 'username', 'chef')
                        for postal_code_obj in obj.requested_postalcodes.all():
                            notify_area_waitlist_users(
                                postal_code_obj.code,
                                str(postal_code_obj.country),
                                chef_username
                            )
                    
                    # Update UserRole for this user
                    user_role, created = UserRole.objects.get_or_create(user=obj.user)
                    user_role.is_chef = True
                    user_role.current_role = 'chef'
                    user_role.save()
                    
                    # Send approval notification email
                    from .emails import send_chef_approved_email
                    email_sent = send_chef_approved_email(chef)
                    
                    if email_sent:
                        messages.success(request, f"Successfully approved chef request for {obj.user.username}. Approval email sent!")
                    else:
                        messages.success(request, f"Successfully approved chef request for {obj.user.username}.")
                        messages.warning(request, f"Could not send approval email to {obj.user.username}. Check their email address.")
                    
            except Exception as e:
                messages.error(request, f"Error approving request for {obj.user.username}: {str(e)}")
                logger.error(f"Error in save_model for ChefRequest {obj.pk}: {str(e)}")


    def approve_chef_requests(self, request, queryset):
        success_count = 0
        error_count = 0
        
        for chef_request in queryset:
            try:
                with transaction.atomic():
                    if not chef_request.is_approved:
                        # Mark the request as approved
                        chef_request.is_approved = True
                        chef_request.save()
                        
                        # Try to get existing Chef or create a new one
                        chef, created = Chef.objects.get_or_create(
                            user=chef_request.user
                        )
                        
                        # Always update the Chef with data from ChefRequest
                        if chef_request.experience:
                            chef.experience = chef_request.experience
                        if chef_request.bio:
                            chef.bio = chef_request.bio
                        if chef_request.profile_pic:
                            chef.profile_pic = chef_request.profile_pic
                        
                        # Mark chef as verified upon approval
                        chef.is_verified = True
                        
                        # Save the chef object
                        chef.save()
                        
                        # Set postal codes if there are any
                        if chef_request.requested_postalcodes.exists():
                            chef.serving_postalcodes.set(chef_request.requested_postalcodes.all())
                            # Notify area waitlist users for each postal code
                            # (M2M .set() doesn't trigger post_save signals on through model)
                            from .tasks import notify_area_waitlist_users
                            chef_username = getattr(chef.user, 'username', 'chef')
                            for postal_code_obj in chef_request.requested_postalcodes.all():
                                notify_area_waitlist_users(
                                    postal_code_obj.code,
                                    str(postal_code_obj.country),
                                    chef_username
                                )
                        
                        # Update UserRole for this user
                        user_role, created = UserRole.objects.get_or_create(user=chef_request.user)
                        user_role.is_chef = True
                        user_role.current_role = 'chef'
                        user_role.save()
                        
                        # Send approval notification email
                        from .emails import send_chef_approved_email
                        send_chef_approved_email(chef)
                        
                        success_count += 1
            except Exception as e:
                error_count += 1
                messages.error(request, f"Error approving request for {chef_request.user.username}: {str(e)}")
        
        if success_count > 0:
            messages.success(request, f"Successfully approved {success_count} chef request(s). Approval emails sent!")
        if error_count > 0:
            messages.warning(request, f"Failed to approve {error_count} chef request(s).")

    approve_chef_requests.short_description = "Approve selected chef requests"
    filter_horizontal = ('requested_postalcodes',)



admin.site.register(ChefRequest, ChefRequestAdmin)


@admin.register(ChefPhoto)
class ChefPhotoAdmin(admin.ModelAdmin):
    list_display = ('chef', 'title', 'is_featured', 'created_at')
    list_filter = ('is_featured', 'chef')
    search_fields = ('title', 'caption', 'chef__user__username')


@admin.register(ChefDefaultBanner)
class ChefDefaultBannerAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChefVerificationDocument)
class ChefVerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ('chef', 'doc_type', 'is_approved', 'uploaded_at')
    list_filter = ('doc_type', 'is_approved')
    search_fields = ('chef__user__username',)
    actions = ['approve_documents', 'reject_documents']

    def approve_documents(self, request, queryset):
        updated = queryset.update(is_approved=True, rejected_reason='')
        self.message_user(request, f"Approved {updated} document(s)")

    def reject_documents(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"Marked {updated} document(s) as rejected")


@admin.register(ChefWaitlistConfig)
class ChefWaitlistConfigAdmin(admin.ModelAdmin):
    list_display = ('enabled', 'cooldown_hours', 'updated_at')
    list_editable = ('enabled', 'cooldown_hours')
    # Make a non-editable column the change-link target so the first
    # editable column passes Django admin validation
    list_display_links = ('updated_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChefAvailabilityState)
class ChefAvailabilityStateAdmin(admin.ModelAdmin):
    list_display = ('chef', 'is_active', 'activation_epoch', 'last_activated_at', 'last_deactivated_at')
    list_filter = ('is_active',)
    search_fields = ('chef__user__username',)


@admin.register(ChefWaitlistSubscription)
class ChefWaitlistSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'chef', 'active', 'last_notified_epoch', 'last_notified_at', 'created_at')
    list_filter = ('active',)
    search_fields = ('user__username', 'user__email', 'chef__user__username')


@admin.register(ChefPaymentLink)
class ChefPaymentLinkAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'chef', 'recipient_display', 'amount_display', 
        'status', 'email_sent_at', 'paid_at', 'created_at'
    )
    list_filter = ('status', 'chef', 'created_at')
    search_fields = (
        'chef__user__username', 'lead__first_name', 'lead__last_name',
        'lead__email', 'customer__email', 'customer__username', 'description'
    )
    readonly_fields = (
        'stripe_payment_link_id', 'stripe_payment_link_url', 'stripe_price_id',
        'stripe_product_id', 'stripe_checkout_session_id', 'stripe_payment_intent_id',
        'paid_at', 'paid_amount_cents', 'email_sent_at', 'email_send_count',
        'created_at', 'updated_at'
    )
    raw_id_fields = ('chef', 'lead', 'customer')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (None, {
            'fields': ('chef', 'status')
        }),
        ('Recipient', {
            'fields': ('lead', 'customer', 'recipient_email')
        }),
        ('Payment Details', {
            'fields': ('amount_cents', 'currency', 'description', 'expires_at')
        }),
        ('Stripe Integration', {
            'fields': (
                'stripe_payment_link_id', 'stripe_payment_link_url',
                'stripe_price_id', 'stripe_product_id',
                'stripe_checkout_session_id', 'stripe_payment_intent_id'
            ),
            'classes': ('collapse',)
        }),
        ('Email Tracking', {
            'fields': ('email_sent_at', 'email_send_count'),
            'classes': ('collapse',)
        }),
        ('Payment Completion', {
            'fields': ('paid_at', 'paid_amount_cents'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('internal_notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def recipient_display(self, obj):
        return obj.get_recipient_name()
    recipient_display.short_description = 'Recipient'
    
    def amount_display(self, obj):
        amount = obj.amount_cents / 100
        return format_html('<strong>${:,.2f}</strong>', amount)
    amount_display.short_description = 'Amount'


@admin.register(PlatformCalendlyConfig)
class PlatformCalendlyConfigAdmin(admin.ModelAdmin):
    """Admin for platform Calendly configuration (singleton)."""
    list_display = ('calendly_url', 'enabled', 'is_required', 'updated_at')
    list_editable = ('enabled', 'is_required')
    list_display_links = ('calendly_url',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('enabled', 'is_required')
        }),
        ('Calendly Settings', {
            'fields': ('calendly_url', 'meeting_title', 'meeting_description')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        # Only allow one config record
        return not PlatformCalendlyConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False  # Prevent accidental deletion


@admin.register(ChefVerificationMeeting)
class ChefVerificationMeetingAdmin(admin.ModelAdmin):
    """Admin for managing chef verification meetings."""
    list_display = ('chef', 'status', 'scheduled_at', 'completed_at', 'marked_complete_by')
    list_filter = ('status', 'completed_at')
    search_fields = ('chef__user__username', 'chef__user__email')
    readonly_fields = ('created_at', 'updated_at', 'completed_at', 'marked_complete_by')
    raw_id_fields = ('chef',)
    actions = ['mark_as_completed', 'mark_as_no_show']

    fieldsets = (
        (None, {
            'fields': ('chef', 'status')
        }),
        ('Schedule', {
            'fields': ('scheduled_at', 'completed_at')
        }),
        ('Admin Notes', {
            'fields': ('admin_notes', 'marked_complete_by')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def mark_as_completed(self, request, queryset):
        for meeting in queryset:
            meeting.mark_as_completed(admin_user=request.user)
        self.message_user(request, f'Marked {queryset.count()} meeting(s) as completed')
    mark_as_completed.short_description = 'Mark selected meetings as completed'

    def mark_as_no_show(self, request, queryset):
        queryset.update(status='no_show')
        self.message_user(request, f'Marked {queryset.count()} meeting(s) as no-show')
    mark_as_no_show.short_description = 'Mark selected meetings as no-show'


class MehkoComplaintAdmin(admin.ModelAdmin):
    list_display = (
        'chef', 'complainant', 'submitted_at', 'is_significant',
        'reported_to_agency', 'resolved', 'complaints_12mo', 'threshold_status',
    )
    list_filter = ('is_significant', 'reported_to_agency', 'resolved')
    search_fields = ('chef__user__username', 'complaint_text')
    raw_id_fields = ('chef', 'complainant')
    readonly_fields = ('submitted_at', 'complaints_12mo', 'threshold_status')
    actions = ['mark_significant_buyer_list', 'mark_reported', 'mark_resolved']
    fieldsets = (
        (None, {
            'fields': ('chef', 'complainant', 'complaint_text', 'is_significant')
        }),
        ('Status', {
            'fields': ('reported_to_agency', 'reported_at', 'resolved', 'resolved_at')
        }),
        ('MEHKO Stats', {
            'fields': ('complaints_12mo', 'threshold_status'),
        }),
        ('Admin', {
            'fields': ('admin_notes', 'submitted_at'),
            'classes': ('collapse',)
        }),
    )

    @admin.display(description='12-mo complaints')
    def complaints_12mo(self, obj):
        return MehkoComplaint.complaints_in_window(obj.chef)

    @admin.display(description='Threshold')
    def threshold_status(self, obj):
        return "⚠️ THRESHOLD" if MehkoComplaint.threshold_reached(obj.chef) else "OK"

    @admin.action(description="Mark significant + generate buyer list CSV")
    def mark_significant_buyer_list(self, request, queryset):
        import csv
        from django.http import HttpResponse
        from chef_services.models import ChefServiceOrder

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="mehko_buyer_list.csv"'
        writer = csv.writer(response)
        writer.writerow(['Complaint ID', 'Chef', 'Order ID', 'Customer', 'Email', 'Service Date', 'Status'])

        for complaint in queryset:
            complaint.is_significant = True
            complaint.save(update_fields=['is_significant'])
            orders = ChefServiceOrder.objects.filter(
                chef=complaint.chef,
                service_date=complaint.submitted_at.date(),
                status__in=['confirmed', 'completed'],
            ).select_related('customer')
            for order in orders:
                writer.writerow([
                    complaint.id, complaint.chef.user.username,
                    order.id, order.customer.get_full_name() or order.customer.username,
                    order.customer.email, order.service_date, order.status,
                ])
        return response

    @admin.action(description="Mark as reported to agency")
    def mark_reported(self, request, queryset):
        from django.utils import timezone as tz
        queryset.update(reported_to_agency=True, reported_at=tz.now())

    @admin.action(description="Mark as resolved")
    def mark_resolved(self, request, queryset):
        from django.utils import timezone as tz
        queryset.update(resolved=True, resolved_at=tz.now())

admin.site.register(MehkoComplaint, MehkoComplaintAdmin)
