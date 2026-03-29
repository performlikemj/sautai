"""
Serializers for Chef CRM Dashboard API endpoints.

These serializers provide clean, documented response structures
for frontend consumption.
"""

from decimal import Decimal
from rest_framework import serializers

from custom_auth.models import CustomUser, HouseholdMember
from chef_services.models import ChefCustomerConnection
from crm.models import Lead, LeadInteraction, LeadHouseholdMember, DIETARY_CHOICES, ALLERGY_CHOICES


# =============================================================================
# Dashboard Summary Serializers
# =============================================================================

class RevenueStatsSerializer(serializers.Serializer):
    """Revenue breakdown by time period, grouped by currency."""
    today = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))
    this_week = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))
    this_month = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))


class ClientStatsSerializer(serializers.Serializer):
    """Client connection statistics."""
    total = serializers.IntegerField(help_text="Total connections (all statuses)")
    active = serializers.IntegerField(help_text="Active (accepted) connections")
    new_this_month = serializers.IntegerField(help_text="New connections this month")


class OrderStatsSerializer(serializers.Serializer):
    """Order statistics for dashboard."""
    upcoming = serializers.IntegerField(help_text="Orders scheduled for future dates")
    pending_confirmation = serializers.IntegerField(help_text="Orders awaiting payment/confirmation")
    completed_this_month = serializers.IntegerField(help_text="Orders completed this month")


class TopServiceSerializer(serializers.Serializer):
    """Top service offering by order count."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    service_type = serializers.CharField(required=False)
    order_count = serializers.IntegerField()


class DashboardSummarySerializer(serializers.Serializer):
    """
    Dashboard summary response for GET /api/chefs/me/dashboard/
    
    Aggregates key metrics for the chef's dashboard home view.
    """
    revenue = RevenueStatsSerializer()
    clients = ClientStatsSerializer()
    orders = OrderStatsSerializer()
    top_services = TopServiceSerializer(many=True)


# =============================================================================
# Client Management Serializers
# =============================================================================

class ClientListItemSerializer(serializers.Serializer):
    """
    Client list item for GET /api/chefs/me/clients/
    
    Compact representation with key stats for list view.
    """
    customer_id = serializers.IntegerField(help_text="Customer user ID")
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    connection_status = serializers.CharField(help_text="Connection status: pending, accepted, declined, ended")
    connected_since = serializers.DateTimeField(allow_null=True, help_text="Date connection was established")
    total_orders = serializers.IntegerField(help_text="Total confirmed/completed orders")
    total_spent = serializers.DecimalField(max_digits=10, decimal_places=2, help_text="Total amount spent (USD)")


class FavoriteServiceSerializer(serializers.Serializer):
    """Favorite service for client detail."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    order_count = serializers.IntegerField()


class ClientDetailSerializer(serializers.Serializer):
    """
    Client detail for GET /api/chefs/me/clients/{customer_id}/
    
    Full client profile with stats, preferences, and order history summary.
    """
    # Basic info
    customer_id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    
    # Connection info
    connection_status = serializers.CharField()
    connected_since = serializers.DateTimeField(allow_null=True)
    
    # Order stats
    total_orders = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=10, decimal_places=2)
    last_order_date = serializers.DateTimeField(allow_null=True)
    average_order_value = serializers.DecimalField(max_digits=10, decimal_places=2)
    
    # Preferences
    dietary_preferences = serializers.ListField(child=serializers.CharField())
    allergies = serializers.ListField(child=serializers.CharField())
    household_size = serializers.IntegerField()
    
    # Favorites
    favorite_services = FavoriteServiceSerializer(many=True)


class ClientNoteInputSerializer(serializers.Serializer):
    """
    Input for POST /api/chefs/me/clients/{customer_id}/notes/
    """
    summary = serializers.CharField(max_length=255, help_text="Brief summary of the interaction")
    details = serializers.CharField(required=False, allow_blank=True, help_text="Detailed notes")
    interaction_type = serializers.ChoiceField(
        choices=[
            ('note', 'Note'),
            ('call', 'Call'),
            ('meeting', 'Meeting'),
            ('email', 'Email'),
            ('message', 'Message'),
        ],
        default='note',
        help_text="Type of interaction"
    )
    next_steps = serializers.CharField(required=False, allow_blank=True, help_text="Follow-up actions")


class ClientNoteSerializer(serializers.ModelSerializer):
    """
    Client interaction note from LeadInteraction model.
    """
    author_name = serializers.SerializerMethodField()
    
    class Meta:
        model = LeadInteraction
        fields = [
            'id', 'interaction_type', 'summary', 'details', 
            'happened_at', 'next_steps', 'author_name', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_author_name(self, obj):
        if obj.author:
            return obj.author.username
        return None


# =============================================================================
# Revenue & Analytics Serializers
# =============================================================================

class RevenueBreakdownSerializer(serializers.Serializer):
    """
    Revenue breakdown for GET /api/chefs/me/revenue/
    """
    period = serializers.CharField(help_text="Period type: day, week, month, year")
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    total_revenue = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2), help_text="Revenue by currency")
    meal_revenue = serializers.DecimalField(max_digits=10, decimal_places=2, help_text="Revenue from meal events (USD)")
    service_revenue = serializers.DecimalField(max_digits=10, decimal_places=2, help_text="Revenue from services (USD)")
    payment_link_revenue = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2), help_text="Payment link revenue by currency")
    order_count = serializers.IntegerField()


# =============================================================================
# Upcoming Orders Serializers
# =============================================================================

class UpcomingOrderSerializer(serializers.Serializer):
    """
    Unified order representation for GET /api/chefs/me/orders/upcoming/
    
    Combines both ChefMealOrders and ChefServiceOrders into a single format.
    """
    order_type = serializers.ChoiceField(
        choices=[('meal_event', 'Meal Event'), ('service', 'Service')],
        help_text="Type of order"
    )
    order_id = serializers.IntegerField()
    customer_id = serializers.IntegerField()
    customer_username = serializers.CharField()
    customer_name = serializers.CharField(help_text="Full name or username")
    service_date = serializers.DateField(allow_null=True)
    service_time = serializers.TimeField(allow_null=True)
    service_name = serializers.CharField()
    status = serializers.CharField()
    quantity = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)


# =============================================================================
# Lead Pipeline Serializers (Contacts / Off-Platform Clients)
# =============================================================================

class LeadHouseholdMemberSerializer(serializers.ModelSerializer):
    """
    Household member for a Lead (off-platform contact).
    """
    class Meta:
        model = LeadHouseholdMember
        fields = [
            'id', 'name', 'relationship', 'age',
            'dietary_preferences', 'allergies', 'custom_allergies', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class LeadHouseholdMemberInputSerializer(serializers.Serializer):
    """
    Input serializer for creating/updating household members.
    """
    name = serializers.CharField(max_length=100)
    relationship = serializers.CharField(max_length=50, required=False, allow_blank=True)
    age = serializers.IntegerField(required=False, allow_null=True)
    dietary_preferences = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    allergies = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    custom_allergies = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class LeadListSerializer(serializers.ModelSerializer):
    """
    Lead list item for GET /api/chefs/me/leads/

    Includes household size for quick overview.
    """
    full_name = serializers.SerializerMethodField()
    days_since_interaction = serializers.SerializerMethodField()
    household_member_count = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'email', 'phone',
            'company', 'status', 'source', 'is_priority', 'budget_cents',
            'household_size', 'household_member_count',
            'dietary_preferences', 'allergies',
            'birthday_month', 'birthday_day', 'anniversary',
            'last_interaction_at', 'days_since_interaction', 'created_at'
        ]
    
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()
    
    def get_days_since_interaction(self, obj):
        if not obj.last_interaction_at:
            return None
        from django.utils import timezone
        delta = timezone.now() - obj.last_interaction_at
        return delta.days
    
    def get_household_member_count(self, obj):
        return obj.household_members.count()


class LeadDetailSerializer(serializers.ModelSerializer):
    """
    Lead detail for GET /api/chefs/me/leads/{id}/

    Full contact profile including household members and dietary info.
    """
    full_name = serializers.SerializerMethodField()
    interactions = ClientNoteSerializer(many=True, read_only=True, source='interactions.all')
    household_members = LeadHouseholdMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'email', 'phone',
            'company', 'status', 'source', 'is_priority', 'budget_cents',
            'notes', 'household_size',
            'dietary_preferences', 'allergies', 'custom_allergies',
            'birthday_month', 'birthday_day', 'anniversary',
            'household_members', 'interactions',
            'last_interaction_at', 'created_at', 'updated_at',
        ]
    
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


class LeadUpdateSerializer(serializers.ModelSerializer):
    """
    Lead update for PATCH /api/chefs/me/leads/{id}/

    Allows updating contact info, status, priority, notes, dietary info, household size, and special dates.
    """
    class Meta:
        model = Lead
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'status', 'is_priority', 'notes', 'budget_cents',
            'household_size', 'dietary_preferences', 'allergies', 'custom_allergies',
            'birthday_month', 'birthday_day', 'anniversary',
        ]


class LeadCreateSerializer(serializers.ModelSerializer):
    """
    Input serializer for creating a new Lead (contact).
    """
    household_members = LeadHouseholdMemberInputSerializer(many=True, required=False)

    class Meta:
        model = Lead
        fields = [
            'first_name', 'last_name', 'email', 'phone', 'company',
            'status', 'source', 'notes', 'budget_cents', 'is_priority',
            'household_size', 'dietary_preferences', 'allergies', 'custom_allergies',
            'birthday_month', 'birthday_day', 'anniversary',
            'household_members'
        ]
    
    def create(self, validated_data):
        household_members_data = validated_data.pop('household_members', [])
        lead = Lead.objects.create(**validated_data)
        
        for member_data in household_members_data:
            LeadHouseholdMember.objects.create(lead=lead, **member_data)
        
        return lead


# =============================================================================
# Unified Client View (Platform + Manual Contacts)
# =============================================================================

class PlatformHouseholdMemberSerializer(serializers.ModelSerializer):
    """
    Household member for platform users.
    """
    dietary_preferences = serializers.SerializerMethodField()

    class Meta:
        model = HouseholdMember
        fields = ['id', 'name', 'age', 'dietary_preferences', 'allergies', 'custom_allergies', 'notes']

    def get_dietary_preferences(self, obj):
        return list(obj.dietary_preferences.values_list('name', flat=True))


class UnifiedClientSerializer(serializers.Serializer):
    """
    Unified client representation combining platform users and manual contacts.
    
    Used for displaying all clients in one view.
    """
    # Common fields
    id = serializers.CharField(help_text="Unique identifier (prefixed: 'platform_' or 'contact_')")
    source_type = serializers.ChoiceField(
        choices=[('platform', 'Platform User'), ('contact', 'Manual Contact')],
        help_text="Where this client came from"
    )
    
    # Identity
    name = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    
    # Relationship info
    status = serializers.CharField(help_text="Connection status or contact status")
    connected_since = serializers.DateTimeField(allow_null=True)
    
    # Dietary info
    dietary_preferences = serializers.ListField(child=serializers.CharField())
    allergies = serializers.ListField(child=serializers.CharField())
    
    # Household
    household_size = serializers.IntegerField()
    household_members = serializers.ListField(allow_null=True)
    
    # Notes
    notes = serializers.CharField(allow_blank=True)


