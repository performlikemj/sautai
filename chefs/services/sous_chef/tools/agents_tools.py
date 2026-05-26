# chefs/services/sous_chef/tools/agents_tools.py
"""
Agents SDK compatible tools for Sous Chef.

Wraps existing tool implementations with @function_tool decorator
for use with OpenAI Agents SDK.
"""

import logging
from typing import List, Any, Optional
from functools import wraps

from .categories import (
    ToolCategory,
    TOOL_REGISTRY,
    get_categories_for_channel,
    SENSITIVE_RESTRICTED_CHANNELS,
)

logger = logging.getLogger(__name__)

# Check if Agents SDK is available
try:
    from agents import function_tool
    AGENTS_SDK_AVAILABLE = True
except ImportError:
    AGENTS_SDK_AVAILABLE = False
    # Fallback decorator that does nothing
    def function_tool(fn):
        return fn


# =============================================================================
# Context holder for tool execution
# =============================================================================

class ToolContext:
    """
    Holds execution context for tools.
    
    This is set by the service before running the agent,
    so tools can access chef/customer/lead without parameters.
    """
    chef = None
    customer = None
    lead = None
    channel = "web"
    
    @classmethod
    def set(cls, chef=None, customer=None, lead=None, channel="web"):
        cls.chef = chef
        cls.customer = customer
        cls.lead = lead
        cls.channel = channel
    
    @classmethod
    def clear(cls):
        cls.chef = None
        cls.customer = None
        cls.lead = None
        cls.channel = "web"


# =============================================================================
# Sensitive data wrapper for agents tools
# =============================================================================

def _check_sensitive_restriction(tool_name: str) -> Optional[dict]:
    """
    Check if tool should be restricted on current channel.
    
    Returns redirect message dict if restricted, None otherwise.
    """
    category = TOOL_REGISTRY.get(tool_name)
    if category != ToolCategory.SENSITIVE:
        return None
    
    if ToolContext.channel not in SENSITIVE_RESTRICTED_CHANNELS:
        return None
    
    # Return redirect message
    from .sensitive_wrapper import get_redirect_message
    return {
        "status": "restricted",
        "channel": ToolContext.channel,
        "tool": tool_name,
        "message": get_redirect_message(tool_name, ToolContext.channel),
    }


# =============================================================================
# Tool implementations wrapped with @function_tool
# =============================================================================

@function_tool(strict_mode=False)
def get_family_dietary_summary(include_member_details: bool = True) -> dict:
    """
    Get dietary preferences and restrictions for the current family.

    Args:
        include_member_details: Include per-member dietary details (default True)

    Returns comprehensive dietary info including allergies,
    dietary restrictions, and per-member details.
    """
    # Check sensitive restriction
    restricted = _check_sensitive_restriction("get_family_dietary_summary")
    if restricted:
        return restricted

    from meals.sous_chef_tools import _get_family_dietary_summary
    result = _get_family_dietary_summary(
        {}, ToolContext.chef, ToolContext.customer, ToolContext.lead
    )
    if not include_member_details and isinstance(result, dict):
        result.pop("member_details", None)
    return result


@function_tool(strict_mode=False)
def get_household_members(include_dietary_info: bool = True) -> dict:
    """
    Get information about household members.

    Args:
        include_dietary_info: Include dietary preferences per member (default True)

    Returns member names, ages, and dietary information.
    """
    restricted = _check_sensitive_restriction("get_household_members")
    if restricted:
        return restricted

    from meals.sous_chef_tools import _get_household_members
    result = _get_household_members(
        {}, ToolContext.chef, ToolContext.customer, ToolContext.lead
    )
    if not include_dietary_info and isinstance(result, dict) and "members" in result:
        for member in result.get("members", []):
            member.pop("dietary_info", None)
    return result


@function_tool(strict_mode=False)
def check_recipe_compliance(
    ingredients: List[str],
    recipe_name: str = "Recipe",
) -> dict:
    """
    Check if a recipe is safe for the family's dietary needs.
    
    Args:
        ingredients: List of ingredients in the recipe
        recipe_name: Name of the recipe (optional)
    
    Returns:
        Compliance status and any issues found.
    """
    restricted = _check_sensitive_restriction("check_recipe_compliance")
    if restricted:
        # For compliance, still return safe/unsafe without details
        from meals.sous_chef_tools import _check_recipe_compliance
        result = _check_recipe_compliance(
            {"ingredients": ingredients, "recipe_name": recipe_name},
            ToolContext.chef, ToolContext.customer, ToolContext.lead
        )
        is_compliant = result.get("is_compliant", True)
        return {
            "status": "restricted",
            "is_compliant": is_compliant,
            "channel": ToolContext.channel,
            "message": "✅ Safe" if is_compliant else "⚠️ Has issues - check dashboard for details",
        }
    
    from meals.sous_chef_tools import _check_recipe_compliance
    return _check_recipe_compliance(
        {"ingredients": ingredients, "recipe_name": recipe_name},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def get_family_order_history(limit: int = 10) -> dict:
    """
    Get order history between chef and family.
    
    Args:
        limit: Maximum orders to return (default 10)
    
    Returns:
        List of past orders with dishes and dates.
    """
    from meals.sous_chef_tools import _get_family_order_history
    return _get_family_order_history(
        {"limit": limit},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def get_upcoming_family_orders(days_ahead: int = 30) -> dict:
    """
    Get upcoming/scheduled orders for this family.

    Args:
        days_ahead: Number of days ahead to look for orders (default 30)

    Returns:
        List of upcoming orders with dates and details.
    """
    from meals.sous_chef_tools import _get_upcoming_family_orders
    return _get_upcoming_family_orders(
        {"days_ahead": days_ahead}, ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def add_family_note(
    summary: str,
    details: Optional[str] = None,
    interaction_type: str = "note",
) -> dict:
    """
    Add a note about this family to the CRM.
    
    Args:
        summary: Brief summary (max 255 chars)
        details: Full details (optional)
        interaction_type: Type: note, call, email, meeting, message
    
    Returns:
        Confirmation of saved note.
    """
    from meals.sous_chef_tools import _add_family_note
    return _add_family_note(
        {"summary": summary, "details": details, "interaction_type": interaction_type},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def search_chef_dishes(query: str, limit: int = 10) -> dict:
    """
    Search dishes in the chef's catalog.
    
    Args:
        query: Search query
        limit: Maximum results (default 10)
    
    Returns:
        Matching dishes with names and descriptions.
    """
    from meals.sous_chef_tools import _search_chef_dishes
    return _search_chef_dishes(
        {"query": query, "limit": limit},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def get_seasonal_ingredients(
    month: Optional[int] = None,
    category: str = "all",
) -> dict:
    """
    Get ingredients that are currently in season.
    
    Args:
        month: Month number 1-12 (default: current month)
        category: vegetables, fruits, proteins, herbs, or all
    
    Returns:
        List of seasonal ingredients.
    """
    from meals.sous_chef_tools import _get_seasonal_ingredients
    return _get_seasonal_ingredients(
        {"month": month, "category": category},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def get_chef_analytics(days: int = 30) -> dict:
    """
    Get analytics and performance metrics for the chef.
    
    Args:
        days: Number of days to analyze (default 30)
    
    Returns:
        Order counts, revenue, popular dishes, etc.
    """
    from meals.sous_chef_tools import _get_chef_analytics
    return _get_chef_analytics(
        {"days": days},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool(strict_mode=False)
def draft_client_message(
    message_type: str,
    key_points: List[str],
    tone: str = "friendly",
) -> dict:
    """
    Draft a message to send to a client.
    
    Args:
        message_type: meal_plan_update, order_confirmation, dietary_question, 
                     schedule_change, general, thank_you, follow_up
        key_points: Key points to include
        tone: professional, friendly, or casual
    
    Returns:
        Drafted message for review.
    """
    from meals.sous_chef_tools import _draft_client_message
    return _draft_client_message(
        {"message_type": message_type, "key_points": key_points, "tone": tone},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


# Navigation tools (web only)

@function_tool
def navigate_to_dashboard_tab(tab_name: str) -> dict:
    """
    Navigate the user to a specific dashboard tab.
    
    Args:
        tab_name: Tab to navigate to (kitchen, orders, clients, etc.)
    
    Returns:
        Navigation action for the frontend.
    """
    from meals.sous_chef_tools import _navigate_to_dashboard_tab
    return _navigate_to_dashboard_tab(
        {"tab": tab_name},  # Use "tab" key to match what the underlying function expects
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


@function_tool
def prefill_form(
    form_type: str,
    values_json: str,
) -> dict:
    """
    Pre-fill a form with suggested values.
    
    Args:
        form_type: Type of form to prefill
        values_json: JSON string of key-value pairs to fill, e.g. '{"name": "John", "email": "john@example.com"}'
    
    Returns:
        Prefill action for the frontend.
    """
    import json
    try:
        values = json.loads(values_json)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON in values_json parameter"}
    
    from meals.sous_chef_tools import _prefill_form
    return _prefill_form(
        {"form_type": form_type, "values": values},
        ToolContext.chef, ToolContext.customer, ToolContext.lead
    )


# =============================================================================
# Tool registry for channel-aware loading
# =============================================================================

# All available tools mapped by name
ALL_TOOLS = {
    # Sensitive tools
    "get_family_dietary_summary": get_family_dietary_summary,
    "get_household_members": get_household_members,
    "check_recipe_compliance": check_recipe_compliance,
    
    # Core tools
    "get_family_order_history": get_family_order_history,
    "get_upcoming_family_orders": get_upcoming_family_orders,
    "add_family_note": add_family_note,
    "search_chef_dishes": search_chef_dishes,
    "get_seasonal_ingredients": get_seasonal_ingredients,
    "get_chef_analytics": get_chef_analytics,
    
    # Messaging tools
    "draft_client_message": draft_client_message,
    
    # Navigation tools (web only)
    "navigate_to_dashboard_tab": navigate_to_dashboard_tab,
    "prefill_form": prefill_form,
}


def get_tools_for_agents(
    channel: str = "web",
    chef: Any = None,
    customer: Any = None,
    lead: Any = None,
) -> List[Any]:
    """
    Get list of @function_tool decorated tools for a channel.
    
    Sets the ToolContext for tool execution.
    
    Args:
        channel: Channel type (web, telegram, line, api)
        chef: Chef model instance
        customer: Optional customer instance
        lead: Optional lead instance
    
    Returns:
        List of function_tool decorated functions appropriate for channel.
    """
    # Set context for tool execution
    ToolContext.set(chef=chef, customer=customer, lead=lead, channel=channel)
    
    # Get allowed categories for this channel
    allowed_categories = get_categories_for_channel(channel)
    
    # Filter tools by category
    tools = []
    for tool_name, tool_fn in ALL_TOOLS.items():
        category = TOOL_REGISTRY.get(tool_name)
        
        if category is None:
            # Unknown tool - skip
            logger.warning(f"Tool '{tool_name}' not in registry, skipping")
            continue
        
        if category in allowed_categories:
            tools.append(tool_fn)
        else:
            logger.debug(f"Tool '{tool_name}' ({category}) excluded for channel '{channel}'")
    
    logger.info(f"Loaded {len(tools)} tools for Agents SDK on channel '{channel}'")
    return tools
