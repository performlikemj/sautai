from decimal import Decimal

from django.core.exceptions import ValidationError
from rest_framework import serializers

from custom_auth.models import CustomUser
from .models import (
    ChefServiceOffering,
    ChefServicePriceTier,
    ChefServiceOrder,
    ChefCustomerConnection,
)


# Currency symbols for all supported currencies
# Must stay in sync with ChefServicePriceTier.SUPPORTED_CURRENCIES
_CURRENCY_SYMBOLS = {
    "usd": "$",
    "eur": "€",
    "gbp": "£",
    "jpy": "¥",
    "cad": "CA$",
    "aud": "A$",
    "chf": "CHF ",
    "hkd": "HK$",
    "sgd": "S$",
    "nzd": "NZ$",
    "mxn": "MX$",
}

# Zero-decimal currencies (no cents - amount is in whole units)
# https://stripe.com/docs/currencies#zero-decimal
_ZERO_DECIMAL_CURRENCIES = {"jpy"}


def _format_amount(amount_smallest_unit, currency_code):
    """
    Format an amount for display.
    
    Args:
        amount_smallest_unit: Amount in smallest currency unit (cents for USD, whole yen for JPY)
        currency_code: ISO 4217 currency code (e.g., 'usd', 'jpy')
    
    Returns:
        Formatted string like "$50" or "¥5,000"
    """
    if amount_smallest_unit is None:
        return "Price TBD"

    currency_lower = (currency_code or "").lower()
    
    # Handle zero-decimal currencies (like JPY) vs decimal currencies (like USD)
    if currency_lower in _ZERO_DECIMAL_CURRENCIES:
        # JPY: amount is already in whole units (e.g., 5000 = ¥5000)
        amount = Decimal(amount_smallest_unit)
        amount_text = f"{int(amount):,}"
    else:
        # USD/EUR/etc: amount is in cents (e.g., 5000 = $50.00)
        amount = (Decimal(amount_smallest_unit) / Decimal(100)).quantize(Decimal("0.01"))
        if amount == amount.to_integral():
            amount_text = f"{int(amount):,}"
        else:
            amount_text = f"{amount:,.2f}".rstrip("0").rstrip(".")

    symbol = _CURRENCY_SYMBOLS.get(currency_lower)
    if symbol:
        return f"{symbol}{amount_text}"
    return f"{currency_code.upper() if currency_code else 'CURRENCY'} {amount_text}"


def _format_household_label(tier):
    if tier.display_label:
        return tier.display_label

    if tier.household_max is None:
        return f"{tier.household_min}+ people"
    if tier.household_min == tier.household_max:
        return f"{tier.household_min} people"
    return f"{tier.household_min}-{tier.household_max} people"


def _format_recurrence(tier):
    if not tier.is_recurring:
        return "one-time"

    interval_map = {
        "week": "weekly",
        "month": "monthly",
    }
    interval = interval_map.get(tier.recurrence_interval or "", tier.recurrence_interval or "recurring")
    return f"recurring {interval}"


def build_tier_summary(tier):
    price_text = _format_amount(tier.desired_unit_amount_cents, tier.currency)
    recurrence_text = _format_recurrence(tier)
    return f"{_format_household_label(tier)}: {price_text}, {recurrence_text}"


class ChefServicePriceTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChefServicePriceTier
        fields = [
            'id', 'offering', 'household_min', 'household_max', 'currency',
            'desired_unit_amount_cents',
            'is_recurring', 'recurrence_interval', 'active', 'display_label',
            'stripe_price_id', 'price_sync_status', 'last_price_sync_error', 'price_synced_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'offering', 'stripe_price_id', 'price_sync_status', 'last_price_sync_error', 'price_synced_at']

    def validate(self, data):
        # Leverage model.clean via is_valid + instance creation in views
        return data


class ChefServiceOfferingSerializer(serializers.ModelSerializer):
    tiers = ChefServicePriceTierSerializer(many=True, read_only=True)
    service_type_label = serializers.CharField(source='get_service_type_display', read_only=True)
    tier_summary = serializers.SerializerMethodField()
    target_customer_ids = serializers.PrimaryKeyRelatedField(
        source='target_customers',
        queryset=CustomUser.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = ChefServiceOffering
        fields = [
            'id', 'chef', 'service_type', 'title', 'description', 'active',
            'default_duration_minutes', 'max_travel_miles', 'notes',
            'created_at', 'updated_at', 'tiers', 'service_type_label', 'tier_summary',
            'target_customer_ids',
        ]
        read_only_fields = ['chef', 'created_at', 'updated_at', 'tiers', 'service_type_label', 'tier_summary']

    def get_tier_summary(self, obj):
        tiers = getattr(obj, 'tiers', None)
        if tiers is None:
            return []
        tier_qs = tiers.all() if hasattr(tiers, 'all') else tiers
        if hasattr(tier_qs, 'order_by'):
            iterable = tier_qs.order_by('household_min', 'household_max', 'id')
        else:
            iterable = sorted(
                tier_qs,
                key=lambda t: (t.household_min, t.household_max or 10**9, t.id or 0),
            )
        return [build_tier_summary(tier) for tier in iterable if tier.active]

    def _resolve_chef(self):
        chef = self.context.get('chef')
        if chef:
            return chef
        instance = getattr(self, 'instance', None)
        if instance is not None:
            return instance.chef
        return None

    def validate_target_customers(self, customers):
        chef = self._resolve_chef()
        if not chef or not customers:
            return customers

        accepted_ids = set(
            ChefCustomerConnection.objects.filter(
                chef=chef,
                customer__in=customers,
                status=ChefCustomerConnection.STATUS_ACCEPTED,
            ).values_list('customer_id', flat=True)
        )
        invalid = [c.id for c in customers if c.id not in accepted_ids]
        if invalid:
            raise serializers.ValidationError(
                "Target customers must have an accepted connection with the chef. Invalid IDs: %s" % (
                    ", ".join(str(pk) for pk in invalid)
                )
            )
        return customers

    def create(self, validated_data):
        target_customers = validated_data.pop('target_customers', [])
        offering = super().create(validated_data)
        if target_customers:
            offering.target_customers.set(target_customers)
        return offering

    def update(self, instance, validated_data):
        target_customers = validated_data.pop('target_customers', None)
        offering = super().update(instance, validated_data)
        if target_customers is not None:
            offering.target_customers.set(target_customers)
        return offering

    def validate_title(self, value):
        chef = self._resolve_chef()
        if chef:
            from chefs.validators import validate_no_catering
            validate_no_catering(value, chef)
        return value

    def validate_description(self, value):
        chef = self._resolve_chef()
        if chef:
            from chefs.validators import validate_no_catering
            validate_no_catering(value, chef)
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Run model-level clean() to catch any validators
        instance = self.instance or ChefServiceOffering()
        for k, v in attrs.items():
            if k != 'target_customers':
                setattr(instance, k, v)
        if not instance.chef_id:
            chef = self._resolve_chef()
            if chef:
                instance.chef = chef
        try:
            instance.clean()
        except ValidationError as e:
            raise serializers.ValidationError(
                e.message_dict if hasattr(e, 'message_dict') else {'non_field_errors': [str(e)]}
            )
        return attrs


class ChefServiceOrderSerializer(serializers.ModelSerializer):
    offering_title = serializers.CharField(source='offering.title', read_only=True)
    service_type = serializers.CharField(source='offering.service_type', read_only=True)
    chef_id = serializers.IntegerField(read_only=True)
    customer_username = serializers.CharField(source='customer.username', read_only=True)
    customer_first_name = serializers.CharField(source='customer.first_name', read_only=True)
    customer_last_name = serializers.CharField(source='customer.last_name', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    total_value_for_chef = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()

    class Meta:
        model = ChefServiceOrder
        fields = [
            'id', 'customer', 'chef', 'offering', 'tier', 'household_size',
            'service_date', 'service_start_time', 'duration_minutes', 'address', 'special_requests',
            'schedule_preferences',
            'stripe_session_id', 'stripe_subscription_id', 'is_subscription',
            'status', 'created_at', 'updated_at',
            'offering_title', 'service_type', 'chef_id',
            'customer_username', 'customer_first_name', 'customer_last_name', 'customer_email',
            'total_value_for_chef', 'currency',
            'delivery_method', 'charged_amount_cents',
        ]
        read_only_fields = ['customer', 'chef', 'stripe_session_id', 'stripe_subscription_id', 'is_subscription', 'status', 'created_at', 'updated_at', 'charged_amount_cents']

    def get_total_value_for_chef(self, obj):
        """Calculate total value from tier price (in dollars, not cents)."""
        if obj.tier and obj.tier.desired_unit_amount_cents:
            return float(obj.tier.desired_unit_amount_cents) / 100
        return 0

    def validate_delivery_method(self, value):
        """Block third-party delivery for MEHKO chefs at serializer level."""
        if value == 'third_party':
            offering_id = self.initial_data.get('offering') or self.initial_data.get('offering_id')
            if offering_id:
                try:
                    offering = ChefServiceOffering.objects.select_related('chef').get(id=offering_id)
                    if offering.chef.mehko_active:
                        raise serializers.ValidationError(
                            "MEHKO orders cannot use third-party delivery per §114367.5."
                        )
                except ChefServiceOffering.DoesNotExist:
                    pass
        return value

    def get_currency(self, obj):
        """Get currency from tier."""
        if obj.tier and obj.tier.currency:
            return obj.tier.currency.upper()
        return 'USD'


# Public variants to avoid exposing stripe_price_id in discovery endpoints
class PublicChefServicePriceTierSerializer(serializers.ModelSerializer):
    ready_for_checkout = serializers.SerializerMethodField()

    class Meta:
        model = ChefServicePriceTier
        fields = [
            'id', 'household_min', 'household_max', 'currency',
            'is_recurring', 'recurrence_interval', 'active', 'display_label',
            'ready_for_checkout',
        ]

    def get_ready_for_checkout(self, obj):
        return bool(obj.stripe_price_id and obj.price_sync_status == 'success')


class PublicChefServiceOfferingSerializer(serializers.ModelSerializer):
    tiers = PublicChefServicePriceTierSerializer(many=True, read_only=True)
    service_type_label = serializers.CharField(source='get_service_type_display', read_only=True)
    tier_summary = serializers.SerializerMethodField()

    class Meta:
        model = ChefServiceOffering
        fields = [
            'id', 'chef', 'service_type', 'title', 'description', 'active',
            'default_duration_minutes', 'max_travel_miles', 'notes',
            'created_at', 'updated_at', 'tiers', 'service_type_label', 'tier_summary'
        ]
        read_only_fields = ['chef', 'created_at', 'updated_at', 'tiers', 'service_type_label', 'tier_summary']

    def get_tier_summary(self, obj):
        tiers = getattr(obj, 'tiers', None)
        if tiers is None:
            return []
        tier_qs = tiers.all() if hasattr(tiers, 'all') else tiers
        if hasattr(tier_qs, 'order_by'):
            iterable = tier_qs.order_by('household_min', 'household_max', 'id')
        else:
            iterable = sorted(
                tier_qs,
                key=lambda t: (t.household_min, t.household_max or 10**9, t.id or 0),
            )
        return [build_tier_summary(tier) for tier in iterable if tier.active]


class ChefCustomerConnectionSerializer(serializers.ModelSerializer):
    chef_id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    # Include partner names for display purposes
    chef_username = serializers.CharField(source='chef.user.username', read_only=True)
    chef_display_name = serializers.SerializerMethodField()
    chef_photo = serializers.SerializerMethodField()
    customer_username = serializers.CharField(source='customer.username', read_only=True)
    customer_first_name = serializers.CharField(source='customer.first_name', read_only=True)
    customer_last_name = serializers.CharField(source='customer.last_name', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)

    class Meta:
        model = ChefCustomerConnection
        fields = [
            'id', 'chef_id', 'customer_id', 'status', 'initiated_by',
            'requested_at', 'responded_at', 'ended_at',
            'chef_username', 'chef_display_name', 'chef_photo',
            'customer_username',
            'customer_first_name', 'customer_last_name', 'customer_email',
        ]
        read_only_fields = fields
    
    def get_chef_display_name(self, obj):
        """Return chef's display name (first + last or username)"""
        user = obj.chef.user
        if user.first_name and user.last_name:
            return f"{user.first_name} {user.last_name}"
        if user.first_name:
            return user.first_name
        return user.username
    
    def get_chef_photo(self, obj):
        """Return chef's profile photo URL"""
        if obj.chef.profile_pic:
            return obj.chef.profile_pic.url
        return None
