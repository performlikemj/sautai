# custom_auth/models.py

from django.db import models
from django.utils import timezone
from datetime import timezone as py_tz
from django.apps import apps
from django.contrib.auth.models import AbstractUser
from django.contrib.auth import get_user_model
from django_countries.fields import CountryField
from local_chefs.models import PostalCode, ChefPostalCode
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.conf.locale import LANG_INFO
import uuid

# Create your models here.
class CustomUser(AbstractUser):
    MEASUREMENT_CHOICES = [
        ('US', 'US Customary'),
        ('METRIC', 'Metric'),
    ]
    DIETARY_CHOICES = [
    ('Vegan', 'Vegan'),
    ('Vegetarian', 'Vegetarian'),
    ('Pescatarian', 'Pescatarian'),
    ('Gluten-Free', 'Gluten-Free'),
    ('Keto', 'Keto'),
    ('Paleo', 'Paleo'),
    ('Halal', 'Halal'),
    ('Kosher', 'Kosher'),
    ('Low-Calorie', 'Low-Calorie'),
    ('Low-Sodium', 'Low-Sodium'),
    ('High-Protein', 'High-Protein'),
    ('Dairy-Free', 'Dairy-Free'),
    ('Nut-Free', 'Nut-Free'),
    ('Raw Food', 'Raw Food'),
    ('Whole 30', 'Whole 30'),
    ('Low-FODMAP', 'Low-FODMAP'),
    ('Diabetic-Friendly', 'Diabetic-Friendly'),
    ('Everything', 'Everything'),
    # ... add more as needed
    ]

    ALLERGY_CHOICES = [
    ('Peanuts', 'Peanuts'),
    ('Tree nuts', 'Tree nuts'),  # Includes almonds, cashews, walnuts, etc.
    ('Milk', 'Milk'),  # Refers to dairy allergy
    ('Egg', 'Egg'),
    ('Wheat', 'Wheat'),  # Common in gluten intolerance
    ('Soy', 'Soy'),
    ('Fish', 'Fish'),  # Includes allergies to specific types of fish
    ('Shellfish', 'Shellfish'),  # Includes shrimp, crab, lobster, etc.
    ('Sesame', 'Sesame'),
    ('Mustard', 'Mustard'),
    ('Celery', 'Celery'),
    ('Lupin', 'Lupin'),  # Common in Europe, refers to Lupin beans and seeds
    ('Sulfites', 'Sulfites'),  # Often found in dried fruits and wine
    ('Molluscs', 'Molluscs'),  # Includes snails, slugs, mussels, oysters, etc.
    ('Corn', 'Corn'),
    ('Gluten', 'Gluten'),  # For broader gluten-related allergies beyond wheat
    ('Kiwi', 'Kiwi'),
    ('Latex', 'Latex'),  # Latex-fruit syndrome related allergies
    ('Pine Nuts', 'Pine Nuts'),
    ('Sunflower Seeds', 'Sunflower Seeds'),
    ('Poppy Seeds', 'Poppy Seeds'),
    ('Fennel', 'Fennel'),
    ('Peach', 'Peach'),
    ('Banana', 'Banana'),
    ('Avocado', 'Avocado'),
    ('Chocolate', 'Chocolate'),
    ('Coffee', 'Coffee'),
    ('Cinnamon', 'Cinnamon'),
    ('Garlic', 'Garlic'),
    ('Chickpeas', 'Chickpeas'),
    ('Lentils', 'Lentils'),
    ('None', 'None'),
    ]

    # Get language choices from Django's built-in language info
    @staticmethod
    def get_language_choices():
        """
        Returns a list of tuples (language_code, language_name) for all languages
        supported by Django, sorted by language name.
        """
        # Filter out languages without a name or name_local for stability
        choices = [(code, info['name']) for code, info in LANG_INFO.items() 
                  if 'name' in info and 'name_local' in info]
        return sorted(choices, key=lambda x: x[1])  # Sort by language name

    email = models.EmailField(unique=True, blank=False, null=False)
    email_confirmed = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    new_email = models.EmailField(blank=True, null=True)
    token_created_at = models.DateTimeField(blank=True, null=True)
    initial_email_confirmed = models.BooleanField(default=False)
    # Field to store week_shift for context when chatting with assistant
    week_shift = models.IntegerField(default=0)
    email_token = models.UUIDField(editable=False, unique=True, db_index=True)
    # Measurement system preference (default Metric; US users can switch or be defaulted during onboarding)
    measurement_system = models.CharField(
        max_length=10,
        choices=MEASUREMENT_CHOICES,
        default='METRIC'
    )
    dietary_preferences = models.ManyToManyField(
        'meals.DietaryPreference',  # Use the app name and model name as a string
        blank=True,
        related_name='users'
    )
    custom_dietary_preferences = models.ManyToManyField(
        'meals.CustomDietaryPreference',
        blank=True,
        related_name='users'
    )
    preferred_language = models.CharField(max_length=10, default='en')  # Increased max_length to accommodate longer language codes
    allergies = ArrayField(
        models.CharField(max_length=20, choices=ALLERGY_CHOICES),
        default=list,
        blank=True,
    )
    custom_allergies = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
    )
    timezone = models.CharField(max_length=100, default='UTC')
    # MEHKO disclosure acceptance
    mehko_disclosure_accepted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When user accepted MEHKO home kitchen food safety disclosures"
    )
    # Email preference field
    unsubscribed_from_emails = models.BooleanField(default=False)
    emergency_supply_goal = models.PositiveIntegerField(default=0)  # Number of days of supplies the user wants
    # Number of household members (replaces preferred_servings)
    household_member_count = models.PositiveIntegerField(
        default=1,
        help_text="Total number of people in the user's household."
    )
    # Controls whether the system auto-generates weekly meal plans for the user
    auto_meal_plans_enabled = models.BooleanField(
        default=True,
        help_text="If False, do not auto-generate weekly meal plans."
    )
    # Chef Preview Mode: tracks if user has generated their one-time sample plan
    sample_plan_generated = models.BooleanField(
        default=False,
        help_text="Whether the user has generated their one-time sample meal plan preview."
    )
    sample_plan_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the sample plan was generated."
    )
    
    @property
    def personal_assistant_email(self):
        if self.email_token:
            return f"mj+{self.email_token}@sautai.com"
        return None

    @property
    def is_email_verified(self):
        """Convenience alias used by public APIs/badges."""
        return bool(getattr(self, 'email_confirmed', False))

    def save(self, *args, **kwargs):
        self.username = self.username.lower()
        # Ensure timezone-aware datetimes for fields when USE_TZ is enabled
        try:
            if getattr(self, 'date_joined', None) and timezone.is_naive(self.date_joined):
                try:
                    self.date_joined = timezone.make_aware(self.date_joined, timezone.get_current_timezone())
                except Exception:
                    self.date_joined = self.date_joined.replace(tzinfo=py_tz.utc)
            if getattr(self, 'last_login', None) and timezone.is_naive(self.last_login):
                try:
                    self.last_login = timezone.make_aware(self.last_login, timezone.get_current_timezone())
                except Exception:
                    self.last_login = self.last_login.replace(tzinfo=py_tz.utc)
            if getattr(self, 'token_created_at', None) and timezone.is_naive(self.token_created_at):
                try:
                    self.token_created_at = timezone.make_aware(self.token_created_at, timezone.get_current_timezone())
                except Exception:
                    self.token_created_at = self.token_created_at.replace(tzinfo=py_tz.utc)
        except Exception:
            pass
        if not self.pk and not self.email_token:  # If creating a new user and token isn't set
            self.email_token = uuid.uuid4()
        super().save(*args, **kwargs)

class Address(models.Model):
    """
    User address with postal code handling.
    
    Field naming convention:
    - normalized_postalcode: Normalized format for DB lookups (uppercase, no special chars)
    - original_postalcode: Original user input format for display
    """
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='address')
    street = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=255, blank=True, null=True)
    normalized_postalcode = models.CharField(max_length=10, blank=True, null=True, help_text="Normalized format for lookups")
    original_postalcode = models.CharField(max_length=15, blank=True, null=True, help_text="Original user input format")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    country = CountryField(blank=True, null=True)

    # Backwards compatibility properties for code that still uses old field names
    @property
    def input_postalcode(self):
        """Backwards compatibility alias for normalized_postalcode."""
        return self.normalized_postalcode
    
    @input_postalcode.setter
    def input_postalcode(self, value):
        """Backwards compatibility setter - normalizes and stores the value."""
        from shared.services.location_service import LocationService
        if value:
            # Store original if not already set
            if not self.original_postalcode:
                self.original_postalcode = value
            self.normalized_postalcode = LocationService.normalize(value)
        else:
            self.normalized_postalcode = None
    
    @property
    def display_postalcode(self):
        """Backwards compatibility alias for original_postalcode."""
        return self.original_postalcode
    
    @display_postalcode.setter
    def display_postalcode(self, value):
        """Backwards compatibility setter."""
        self.original_postalcode = value

    def __str__(self):
        display_code = self.original_postalcode or self.normalized_postalcode
        return f'{self.user} - {display_code}, {self.country}'

    def clean(self):
        from shared.services.location_service import LocationService
        
        # Store the original user input for display if we have a postal code
        if self.normalized_postalcode and not self.original_postalcode:
            self.original_postalcode = self.normalized_postalcode
            
        # Normalize postal code for lookups
        if self.normalized_postalcode and self.country:
            # Store the original format before normalizing
            if not self.original_postalcode:
                self.original_postalcode = self.normalized_postalcode
                
            # Normalize for database storage and lookups
            self.normalized_postalcode = LocationService.normalize(self.normalized_postalcode)
            
            # Validate postal code format using LocationService
            is_valid, error_message = LocationService.validate_postal_code(
                self.normalized_postalcode,
                str(self.country)
            )
            if not is_valid:
                raise ValidationError({'normalized_postalcode': error_message})
                
        # Require both country and postal code if either is provided
        if (self.country and not self.normalized_postalcode) or (self.normalized_postalcode and not self.country):
            raise ValidationError('Both country and postal code must be provided together')

    def get_or_create_postal_code(self):
        """
        Gets the corresponding PostalCode object for this address, creating one if it doesn't exist.
        Returns None if either country or normalized_postalcode is missing.
        """
        from shared.services.location_service import LocationService
        
        if not self.country or not self.normalized_postalcode:
            return None
        
        return LocationService.get_or_create_postal_code(
            self.normalized_postalcode,
            str(self.country),
            display_code=self.original_postalcode
        )

    def is_postalcode_served(self):
        """
        Checks if the postal code is served by any chef.
        Returns True if served, False otherwise.
        """
        from shared.services.location_service import LocationService
        
        if not self.country or not self.normalized_postalcode:
            return False
        
        return LocationService.has_chef_coverage_for_area(
            self.normalized_postalcode,
            str(self.country)
        )

    def save(self, *args, **kwargs):
        from shared.services.location_service import LocationService
        
        # Check if this is an update and if postal code has changed
        should_run_full_clean = True
        if self.pk:  # Existing instance
            try:
                original = Address.objects.get(pk=self.pk)
                # Normalize the current postal code for accurate comparison
                current_normalized = LocationService.normalize(self.normalized_postalcode)
                if original.normalized_postalcode != current_normalized:
                    self.latitude = None
                    self.longitude = None

                # Only run full_clean if either country or postal code changed
                original_country = original.country
                original_postal = original.normalized_postalcode
                new_country = self.country
                new_postal = current_normalized
                should_run_full_clean = (original_country != new_country) or (original_postal != new_postal)
            except Address.DoesNotExist:
                # If somehow not found, treat as new and validate
                should_run_full_clean = True
        else:
            # New instance – validate
            should_run_full_clean = True

        if should_run_full_clean:
            self.full_clean()  # Validate only when relevant fields changed or on create

        super().save(*args, **kwargs)



class HouseholdMember(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='household_members')
    name = models.CharField(max_length=100)
    age = models.PositiveIntegerField(blank=True, null=True)
    dietary_preferences = models.ManyToManyField(
        'meals.DietaryPreference',
        blank=True,
        related_name='household_members'
    )
    allergies = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
    )
    custom_allergies = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
    )
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class UserRole(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    is_chef = models.BooleanField(default=False)
    current_role = models.CharField(max_length=10, choices=[('chef', 'Chef'), ('customer', 'Customer')], default='customer')
    
    def switch_to_chef(self):
        self.current_role = 'chef'
        self.save()

    # more methods for role management
    def switch_to_customer(self):
        self.current_role = 'customer'
        self.save()

    def __str__(self):
        return f'{self.user.username} - {self.current_role}'


class OnboardingSession(models.Model):
    """Track registration info collected for guest onboarding."""

    guest_id = models.CharField(max_length=40, unique=True)
    data = models.JSONField(default=dict)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OnboardingSession({self.guest_id})"
    
