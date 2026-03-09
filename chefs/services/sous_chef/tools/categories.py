# chefs/services/sous_chef/tools/categories.py
"""
Tool categories and registry for channel-aware tool loading.

Security: SENSITIVE tools contain health/PII data and are wrapped
on restricted channels (Telegram, LINE) to prevent data exposure.
"""

from enum import Enum
from typing import Set, Dict


class ToolCategory(str, Enum):
    """Categories of tools based on where they can be used."""
    
    # Core tools - available on all channels
    # Queries, data retrieval, analysis (non-sensitive)
    CORE = "core"
    
    # Sensitive tools - contain health/PII data
    # Available on all channels but WRAPPED on restricted channels
    # to return redirect messages instead of actual data
    SENSITIVE = "sensitive"
    
    # Navigation tools - web dashboard only
    # UI navigation, form prefills, scaffolding
    NAVIGATION = "navigation"
    
    # Messaging tools - for composing customer messages
    # Available on Telegram, LINE, web
    MESSAGING = "messaging"


# Channels where sensitive data should be restricted (wrapped)
# On these channels, sensitive tools return "check dashboard" messages
SENSITIVE_RESTRICTED_CHANNELS: Set[str] = {"telegram", "line"}


# Registry mapping tool names to their categories
TOOL_REGISTRY: Dict[str, ToolCategory] = {
    # ═══════════════════════════════════════════════════════════════════════
    # SENSITIVE TOOLS - Contain health/PII data
    # These are WRAPPED on restricted channels (Telegram, LINE)
    # ═══════════════════════════════════════════════════════════════════════
    
    # Health/dietary data - names + allergies + restrictions
    "get_family_dietary_summary": ToolCategory.SENSITIVE,
    "get_household_members": ToolCategory.SENSITIVE,
    "check_recipe_compliance": ToolCategory.SENSITIVE,
    "suggest_ingredient_substitution": ToolCategory.SENSITIVE,
    
    # ═══════════════════════════════════════════════════════════════════════
    # CORE TOOLS - Work everywhere (no sensitive data)
    # ═══════════════════════════════════════════════════════════════════════
    
    # Family/Customer data (non-sensitive)
    "get_family_order_history": ToolCategory.CORE,
    "get_upcoming_family_orders": ToolCategory.CORE,
    "get_family_insights": ToolCategory.CORE,
    "save_family_insight": ToolCategory.CORE,
    "add_family_note": ToolCategory.CORE,
    
    # Recipe & menu planning (non-sensitive outputs)
    "suggest_family_menu": ToolCategory.CORE,
    "scale_recipe_for_household": ToolCategory.CORE,
    "get_seasonal_ingredients": ToolCategory.CORE,
    
    # Prep & cooking
    "estimate_prep_time": ToolCategory.CORE,
    "get_prep_plan_summary": ToolCategory.CORE,
    "generate_prep_plan": ToolCategory.CORE,
    "get_shopping_list": ToolCategory.CORE,
    "get_batch_cooking_suggestions": ToolCategory.CORE,
    "check_ingredient_shelf_life": ToolCategory.CORE,
    
    # Chef operations
    "search_chef_dishes": ToolCategory.CORE,
    "get_chef_analytics": ToolCategory.CORE,
    "get_upcoming_commitments": ToolCategory.CORE,
    
    # Memory system
    "save_chef_memory": ToolCategory.CORE,
    "recall_chef_memories": ToolCategory.CORE,
    "update_chef_memory": ToolCategory.CORE,
    
    # Proactive insights
    "get_proactive_insights": ToolCategory.CORE,
    "dismiss_insight": ToolCategory.CORE,
    "act_on_insight": ToolCategory.CORE,

    # Payment link tools
    "preview_payment_link": ToolCategory.CORE,
    "create_and_send_payment_link": ToolCategory.CORE,
    "check_payment_link_status": ToolCategory.CORE,
    
    # ═══════════════════════════════════════════════════════════════════════
    # NAVIGATION TOOLS - Web dashboard only
    # ═══════════════════════════════════════════════════════════════════════
    
    "lookup_chef_hub_help": ToolCategory.NAVIGATION,
    "navigate_to_dashboard_tab": ToolCategory.NAVIGATION,
    "prefill_form": ToolCategory.NAVIGATION,
    "scaffold_meal": ToolCategory.NAVIGATION,
    
    # ═══════════════════════════════════════════════════════════════════════
    # MESSAGING TOOLS - For customer communication
    # ═══════════════════════════════════════════════════════════════════════
    
    "draft_client_message": ToolCategory.MESSAGING,
}


# Which categories are allowed per channel
# Note: SENSITIVE is included but tools are WRAPPED on restricted channels
CHANNEL_TOOLS: Dict[str, Set[ToolCategory]] = {
    # Web dashboard - full access (sensitive tools work normally)
    "web": {
        ToolCategory.CORE,
        ToolCategory.SENSITIVE,
        ToolCategory.NAVIGATION,
        ToolCategory.MESSAGING,
    },
    
    # Telegram - no UI navigation, sensitive tools are WRAPPED
    "telegram": {
        ToolCategory.CORE,
        ToolCategory.SENSITIVE,  # Loaded but wrapped to return redirects
        ToolCategory.MESSAGING,
    },
    
    # LINE - no UI navigation, sensitive tools are WRAPPED
    "line": {
        ToolCategory.CORE,
        ToolCategory.SENSITIVE,  # Loaded but wrapped to return redirects
        ToolCategory.MESSAGING,
    },
    
    # API/programmatic - core only (no sensitive data via API)
    "api": {
        ToolCategory.CORE,
    },
}


def get_categories_for_channel(channel: str) -> Set[ToolCategory]:
    """Get allowed tool categories for a channel."""
    return CHANNEL_TOOLS.get(channel, {ToolCategory.CORE})


def is_tool_allowed(tool_name: str, channel: str) -> bool:
    """Check if a tool is allowed on a given channel."""
    category = TOOL_REGISTRY.get(tool_name)
    if category is None:
        return False
    
    allowed = get_categories_for_channel(channel)
    return category in allowed
