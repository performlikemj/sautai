"""MEHKO/IFSI compliance validators."""
import re
from django.core.exceptions import ValidationError


def validate_no_catering(value, chef=None):
    """
    Reject text containing the word 'catering' for MEHKO-active chefs.
    Per California Health & Safety Code §114367.6, IFSI platforms must not
    use the word 'catering' in MEHKO listings.

    Args:
        value: Text to validate
        chef: Chef instance (if None or not mehko_active, validation is skipped)
    """
    if not chef or not getattr(chef, 'mehko_active', False):
        return
    if not value:
        return
    # §114367.6(a)(10): "the word 'catering' or any variation of that word"
    # Match: catering, caterer, caterers, cater, catered, etc.
    if re.search(r'\bcater(?:ing|er|ers|ed)?\b', value, re.IGNORECASE):
        raise ValidationError(
            "MEHKO listings cannot use the word 'catering' or any variation "
            "per California Health & Safety Code §114367.6(a)(10)."
        )
