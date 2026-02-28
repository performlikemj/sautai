from rest_framework import serializers
from .models import ChefRequest, Chef, ChefPhoto, ChefDefaultBanner, ChefVerificationDocument
from django.contrib.auth import get_user_model
from local_chefs.models import PostalCode
from custom_auth.serializers import CustomUserSerializer
from custom_auth.models import Address
from meals.models import Dish, Meal, MealPlanReceipt


class ChefRequestSerializer(serializers.ModelSerializer):
    user = CustomUserSerializer(read_only=True)

    class Meta:
        model = ChefRequest
        fields = ['id', 'user', 'experience', 'bio', 'profile_pic', 'is_approved']
        read_only_fields = ['id', 'user', 'is_approved']


class PostalCodePublicSerializer(serializers.ModelSerializer):
    postal_code = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    place_name = serializers.SerializerMethodField()

    class Meta:
        model = PostalCode
        fields = ['postal_code', 'city', 'country', 'place_name']

    def get_postal_code(self, obj):
        return obj.display_code or obj.code

    def get_city(self, obj):
        # Priority order for city name:
        # 1. admin_area.name (most reliable - the actual city/ward/district)
        # 2. place_name from GeoNames
        # 3. Infer from user Address records (fallback)
        
        # Try admin_area first (city/ward/district this postal code belongs to)
        if obj.admin_area and obj.admin_area.name:
            return obj.admin_area.name
        
        # Try place_name from GeoNames
        if obj.place_name:
            return obj.place_name.strip()
        
        # Fallback: infer from user addresses
        try:
            city_qs = (
                Address.objects
                .filter(input_postalcode=obj.code, country=obj.country)
                .exclude(city__isnull=True)
                .exclude(city__exact='')
                .values_list('city', flat=True)
            )
            return city_qs.first() if city_qs.exists() else None
        except Exception:
            return None

    def get_place_name(self, obj):
        """Return the GeoNames place_name for additional context."""
        return obj.place_name if obj.place_name else None

    def get_country(self, obj):
        return {
            'code': getattr(obj.country, 'code', None),
            'name': getattr(obj.country, 'name', None),
        }


class ChefPhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ChefPhoto
        fields = ['id', 'image_url', 'title', 'caption', 'is_featured', 'created_at']
        read_only_fields = ['id', 'image_url', 'created_at']

    def get_image_url(self, obj):
        # Safe check: ImageFieldFile.url raises if no file; rely on name to detect presence
        if not obj.image or not getattr(obj.image, 'name', None):
            return None
        # Return relative URL for better compatibility across different hosts/proxies
        return obj.image.url


class UserPublicSerializer(serializers.ModelSerializer):
    is_email_verified = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ['username', 'is_active', 'is_email_verified']

    def get_is_email_verified(self, obj):
        if hasattr(obj, 'is_email_verified'):
            return bool(obj.is_email_verified)
        return bool(getattr(obj, 'email_confirmed', False))


class ChefPublicSerializer(serializers.ModelSerializer):
    user = UserPublicSerializer(read_only=True)
    serving_postalcodes = PostalCodePublicSerializer(many=True, read_only=True)
    photos = serializers.SerializerMethodField()
    profile_pic_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    class Meta:
        model = Chef
        fields = ['id', 'user', 'experience', 'bio', 'is_on_break', 'is_live',
                  'serving_postalcodes', 'profile_pic_url', 'banner_url',
                  'review_summary', 'photos',
                  'is_verified', 'background_checked', 'insured', 'insurance_expiry',
                  'food_handlers_cert', 'sous_chef_emoji', 'calendly_url', 'default_currency']

    def get_profile_pic_url(self, obj):
        # Safe check: ImageFieldFile.url raises if no file; rely on name to detect presence
        if not obj.profile_pic or not getattr(obj.profile_pic, 'name', None):
            return None
        # Return relative URL for better compatibility across different hosts/proxies
        return obj.profile_pic.url

    def get_banner_url(self, obj):
        # Prefer chef's own banner - return relative URL for better compatibility
        if getattr(obj, 'banner_image', None) and getattr(obj.banner_image, 'name', None):
            return obj.banner_image.url
        # Fallback to most recent default banner if available
        default = ChefDefaultBanner.objects.first()
        if default and getattr(default.image, 'name', None):
            return default.image.url
        return None

    def get_photos(self, obj):
        """Return public photos; include full gallery when explicitly requested."""
        public_photos = getattr(obj, 'public_photos', None)
        if public_photos is None:
            public_photos = obj.photos.filter(is_public=True)
        include_all = bool(self.context.get('include_all_photos'))
        if hasattr(public_photos, 'order_by'):
            public_photos = public_photos.order_by('-created_at')
        else:
            public_photos = list(public_photos)
        if include_all:
            serializer = ChefPhotoSerializer(public_photos, many=True, context=self.context)
        else:
            serializer = ChefPhotoSerializer(public_photos[:6], many=True, context=self.context)
        return serializer.data

    


class ChefMeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chef
        fields = ['experience', 'bio', 'profile_pic', 'banner_image', 'is_on_break', 'sous_chef_emoji', 'calendly_url', 'default_currency']
    
    def validate_default_currency(self, value):
        if value:
            value = value.lower().strip()
            # Validate it's a valid 3-letter currency code
            if len(value) != 3 or not value.isalpha():
                raise serializers.ValidationError('Currency must be a 3-letter ISO 4217 code (e.g., usd, eur, jpy)')
        return value

    def validate_calendly_url(self, value):
        if value:
            value = value.strip()
            if not value.startswith('https://calendly.com/'):
                raise serializers.ValidationError(
                    'Please enter a valid Calendly URL (must start with https://calendly.com/)'
                )
        return value or None


# Gallery-specific serializers for the new public gallery endpoints


class DishMinimalSerializer(serializers.ModelSerializer):
    """Minimal dish info for gallery photos."""
    class Meta:
        model = Dish
        fields = ['id', 'name']


class MealMinimalSerializer(serializers.ModelSerializer):
    """Minimal meal info for gallery photos."""
    class Meta:
        model = Meal
        fields = ['id', 'name', 'description']


class GalleryPhotoSerializer(serializers.ModelSerializer):
    """Enhanced serializer for public gallery display with all metadata."""
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    dish = DishMinimalSerializer(read_only=True)
    meal = MealMinimalSerializer(read_only=True)
    
    class Meta:
        model = ChefPhoto
        fields = [
            'id', 'image_url', 'thumbnail_url', 'title', 'caption', 
            'description', 'tags', 'category', 'created_at', 'updated_at',
            'dish', 'meal', 'width', 'height', 'file_size', 'is_featured'
        ]
        read_only_fields = ['id', 'image_url', 'thumbnail_url', 'created_at', 'updated_at']
    
    def get_image_url(self, obj):
        if not obj.image or not getattr(obj.image, 'name', None):
            return None
        # Return relative URL for better compatibility across different hosts/proxies
        return obj.image.url
    
    def get_thumbnail_url(self, obj):
        # Return thumbnail if available, otherwise return main image
        if obj.thumbnail and getattr(obj.thumbnail, 'name', None):
            return obj.thumbnail.url
        # Fallback to main image
        return self.get_image_url(obj)


class GalleryStatsSerializer(serializers.Serializer):
    """Serializer for gallery statistics."""
    total_photos = serializers.IntegerField()
    categories = serializers.DictField(child=serializers.IntegerField())
    tags = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField())
    )
    date_range = serializers.DictField()


# =============================================================================
# Chef Verification Documents Serializers
# =============================================================================


class ChefVerificationDocumentSerializer(serializers.ModelSerializer):
    """Serializer for chef verification documents (insurance, licenses, etc.)."""
    file_url = serializers.SerializerMethodField()
    doc_type_display = serializers.CharField(source='get_doc_type_display', read_only=True)
    
    class Meta:
        model = ChefVerificationDocument
        fields = [
            'id', 'doc_type', 'doc_type_display', 'file', 'file_url',
            'uploaded_at', 'is_approved', 'rejected_reason'
        ]
        read_only_fields = ['id', 'uploaded_at', 'is_approved', 'rejected_reason']
    
    def get_file_url(self, obj):
        if not obj.file or not getattr(obj.file, 'name', None):
            return None
        # Return relative URL for better compatibility across different hosts/proxies
        return obj.file.url


class ChefVerificationDocumentUploadSerializer(serializers.ModelSerializer):
    """Serializer for uploading new verification documents."""
    
    class Meta:
        model = ChefVerificationDocument
        fields = ['doc_type', 'file']
    
    def validate_file(self, value):
        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError('File size must be less than 10MB.')
        
        # Validate file type
        allowed_types = [
            'image/jpeg', 'image/png', 'image/gif', 'image/webp',
            'application/pdf'
        ]
        if hasattr(value, 'content_type') and value.content_type not in allowed_types:
            raise serializers.ValidationError(
                'File must be an image (JPEG, PNG, GIF, WebP) or PDF.'
            )
        return value


# =============================================================================
# Meal Plan Receipt Serializers
# =============================================================================


class MealPlanReceiptSerializer(serializers.ModelSerializer):
    """Full serializer for meal plan receipts."""
    receipt_image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = MealPlanReceipt
        fields = [
            'id', 'receipt_image', 'receipt_image_url', 'thumbnail_url',
            'amount', 'currency', 'tax_amount', 'subtotal',
            'category', 'category_display', 'merchant_name', 'purchase_date',
            'description', 'items',
            'customer', 'customer_name', 'meal_plan', 'chef_meal_plan', 'prep_plan',
            'status', 'status_display', 'reviewed_at', 'reviewer_notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'receipt_image_url', 'thumbnail_url', 'subtotal',
            'status', 'reviewed_at', 'reviewer_notes', 'created_at', 'updated_at'
        ]
    
    def get_receipt_image_url(self, obj):
        if not obj.receipt_image or not getattr(obj.receipt_image, 'name', None):
            return None
        # Return relative URL for better compatibility across different hosts/proxies
        return obj.receipt_image.url
    
    def get_thumbnail_url(self, obj):
        if obj.receipt_thumbnail and getattr(obj.receipt_thumbnail, 'name', None):
            return obj.receipt_thumbnail.url
        return self.get_receipt_image_url(obj)
    
    def get_customer_name(self, obj):
        if obj.customer:
            return obj.customer.get_full_name() or obj.customer.username
        return None


class MealPlanReceiptUploadSerializer(serializers.ModelSerializer):
    """Serializer for uploading new receipts."""
    
    class Meta:
        model = MealPlanReceipt
        fields = [
            'receipt_image', 'amount', 'currency', 'tax_amount',
            'category', 'merchant_name', 'purchase_date', 'description', 'items',
            'customer', 'meal_plan', 'chef_meal_plan', 'prep_plan'
        ]
    
    def validate_receipt_image(self, value):
        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError('File size must be less than 10MB.')
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if hasattr(value, 'content_type') and value.content_type not in allowed_types:
            raise serializers.ValidationError(
                'Receipt image must be JPEG, PNG, GIF, or WebP.'
            )
        return value
    
    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class MealPlanReceiptListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing receipts."""
    thumbnail_url = serializers.SerializerMethodField()
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = MealPlanReceipt
        fields = [
            'id', 'thumbnail_url', 'amount', 'currency',
            'category', 'category_display', 'merchant_name', 'purchase_date',
            'status', 'status_display', 'created_at'
        ]
    
    def get_thumbnail_url(self, obj):
        # Return relative URLs for better compatibility across different hosts/proxies
        if obj.receipt_thumbnail and getattr(obj.receipt_thumbnail, 'name', None):
            return obj.receipt_thumbnail.url
        if obj.receipt_image and getattr(obj.receipt_image, 'name', None):
            return obj.receipt_image.url
        return None


class ChefMehkoSerializer(serializers.ModelSerializer):
    """Serializer for MEHKO/IFSI compliance fields."""
    mehko_active = serializers.BooleanField(read_only=True)
    missing_requirements = serializers.SerializerMethodField()

    class Meta:
        model = Chef
        fields = [
            'permit_number', 'permitting_agency', 'permit_expiry',
            'county', 'mehko_consent', 'mehko_active', 'missing_requirements',
        ]

    def get_missing_requirements(self, obj):
        _, missing = obj.check_mehko_eligibility()
        return missing

    def validate_county(self, value):
        if value:
            from chefs.constants import MEHKO_APPROVED_COUNTIES
            if value not in MEHKO_APPROVED_COUNTIES:
                raise serializers.ValidationError(
                    f"'{value}' is not an approved MEHKO county. "
                    f"Approved: {', '.join(MEHKO_APPROVED_COUNTIES)}"
                )
        return value

    def validate_permit_expiry(self, value):
        if value:
            from django.utils import timezone
            if value < timezone.now().date():
                raise serializers.ValidationError(
                    "Permit expiry date must be today or in the future."
                )
        return value
