# chefs/models/__init__.py
"""
Chefs models package.

Re-exports all models for backward compatibility.
"""

# Base models (formerly in chefs/models.py)
from .base import (
    Chef,
    ChefRequest,
    ChefPhoto,
    ChefDefaultBanner,
    ChefVerificationDocument,
    MehkoComplaint,
    ChefWaitlistConfig,
    ChefAvailabilityState,
    ChefWaitlistSubscription,
    AreaWaitlist,
    PlatformCalendlyConfig,
    ChefVerificationMeeting,
    ChefPaymentLink,
)

# Re-export from local_chefs for backward compatibility
from local_chefs.models import PostalCode, ChefPostalCode

# Sous Chef memory models
from .sous_chef_memory import (
    ChefWorkspace,
    ClientContext,
    SousChefUsage,
    hybrid_memory_search,
)

# Proactive engine models
from .proactive import (
    ChefProactiveSettings,
    ChefOnboardingState,
    ChefNotification,
)

# Telegram integration models
from .telegram_integration import (
    ChefTelegramLink,
    TelegramLinkToken,
    ChefTelegramSettings,
)

__all__ = [
    # Base models
    'Chef',
    'ChefRequest',
    'ChefPhoto',
    'ChefDefaultBanner',
    'ChefVerificationDocument',
    'MehkoComplaint',
    'ChefWaitlistConfig',
    'ChefAvailabilityState',
    'ChefWaitlistSubscription',
    'AreaWaitlist',
    'PlatformCalendlyConfig',
    'ChefVerificationMeeting',
    'ChefPaymentLink',
    # Re-exported from local_chefs
    'PostalCode',
    'ChefPostalCode',
    # Sous Chef memory
    'ChefWorkspace',
    'ClientContext',
    'SousChefUsage',
    'hybrid_memory_search',
    # Proactive engine
    'ChefProactiveSettings',
    'ChefOnboardingState',
    'ChefNotification',
    # Telegram integration
    'ChefTelegramLink',
    'TelegramLinkToken',
    'ChefTelegramSettings',
]
