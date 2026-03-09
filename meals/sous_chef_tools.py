# meals/sous_chef_tools.py
"""
Sous Chef Tools - Chef-specific AI tools for family meal planning.

These tools are designed to help chefs make better decisions when 
planning and preparing meals for the families they serve.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime, timedelta

from django.utils import timezone
from django.db.models import Sum, F

from chefs.models import Chef
from custom_auth.models import CustomUser
from crm.models import Lead, LeadInteraction, LeadHouseholdMember

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS (OpenAI Function Schema)
# ═══════════════════════════════════════════════════════════════════════════════

SOUS_CHEF_TOOLS = [
    {
        "type": "function",
        "name": "get_family_dietary_summary",
        "description": "Get a comprehensive summary of all dietary restrictions and allergies for the entire household. Use this to understand what ingredients to avoid and what dietary preferences to honor.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "check_recipe_compliance",
        "description": "Check if a recipe or list of ingredients is safe for this family, considering all dietary restrictions and allergies across household members.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipe_name": {
                    "type": "string",
                    "description": "Name of the recipe or dish"
                },
                "ingredients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ingredients in the recipe"
                }
            },
            "required": ["ingredients"]
        }
    },
    {
        "type": "function",
        "name": "suggest_family_menu",
        "description": "Generate menu suggestions for this family based on their dietary needs, preferences, and order history. Optionally specify the number of days and meal types.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to plan for (default: 7)",
                    "default": 7
                },
                "meal_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["Breakfast", "Lunch", "Dinner", "Snack"]
                    },
                    "description": "Which meals to include (default: all)"
                },
                "cuisine_preference": {
                    "type": ["string", "null"],
                    "description": "Optional cuisine style preference (can be null)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "scale_recipe_for_household",
        "description": "Calculate scaled ingredient quantities for a recipe based on the household size and optional serving adjustments.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipe_name": {
                    "type": "string",
                    "description": "Name of the recipe"
                },
                "original_servings": {
                    "type": "integer",
                    "description": "Number of servings the original recipe makes"
                },
                "ingredients": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string"}
                        }
                    },
                    "description": "Original ingredient list with quantities"
                },
                "servings_per_person": {
                    "type": "number",
                    "description": "Servings per household member (default: 1)",
                    "default": 1
                }
            },
            "required": ["recipe_name", "original_servings", "ingredients"]
        }
    },
    {
        "type": "function",
        "name": "get_family_order_history",
        "description": "Retrieve the order history between this chef and this family, including what dishes were ordered and when.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of orders to return (default: 10)",
                    "default": 10
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "add_family_note",
        "description": "Add a note about this family to the chef's CRM. Use this to record important preferences, feedback, or observations.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of the note (max 255 chars)"
                },
                "details": {
                    "type": ["string", "null"],
                    "description": "Full details of the note (can be null)"
                },
                "interaction_type": {
                    "type": ["string", "null"],
                    "enum": ["note", "call", "email", "meeting", "message"],
                    "description": "Type of interaction (default: note, can be null)",
                    "default": "note"
                },
                "next_steps": {
                    "type": ["string", "null"],
                    "description": "Any follow-up actions needed (can be null)"
                }
            },
            "required": ["summary"]
        }
    },
    {
        "type": "function",
        "name": "get_upcoming_family_orders",
        "description": "Get scheduled/upcoming orders for this family.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "estimate_prep_time",
        "description": "Estimate total preparation time for a menu or list of dishes, considering the household size.",
        "parameters": {
            "type": "object",
            "properties": {
                "dishes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "base_prep_minutes": {"type": "integer"},
                            "base_cook_minutes": {"type": "integer"}
                        }
                    },
                    "description": "List of dishes with their base prep/cook times"
                },
                "parallel_cooking": {
                    "type": "boolean",
                    "description": "Whether dishes can be cooked in parallel (default: true)",
                    "default": True
                }
            },
            "required": ["dishes"]
        }
    },
    {
        "type": "function",
        "name": "get_household_members",
        "description": "Get detailed information about each household member, including their individual dietary needs.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "save_family_insight",
        "description": "Save a persistent insight about this family for future reference. Use this when you discover important preferences, tips, things to avoid, or successes that should be remembered across conversations.",
        "parameters": {
            "type": "object",
            "properties": {
                "insight_type": {
                    "type": "string",
                    "enum": ["preference", "tip", "avoid", "success"],
                    "description": "Type of insight: preference (what they like), tip (useful info), avoid (things to not do), success (what worked well)"
                },
                "content": {
                    "type": "string",
                    "description": "The insight to remember (max 500 chars). Be specific and actionable."
                }
            },
            "required": ["insight_type", "content"]
        }
    },
    {
        "type": "function",
        "name": "get_family_insights",
        "description": "Get all saved insights about this family. Use this to recall what you've learned about them.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    # ═══════════════════════════════════════════════════════════════════════════════
    # PREP PLANNING TOOLS
    # ═══════════════════════════════════════════════════════════════════════════════
    {
        "type": "function",
        "name": "get_prep_plan_summary",
        "description": "Get a summary of your current prep planning status including active plans, items to purchase today, and overdue items. Use this to understand your upcoming shopping and prep needs.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "generate_prep_plan",
        "description": "Generate a new prep plan for an upcoming date range. This will analyze your upcoming meal shares and service orders, then create an optimized shopping list with timing suggestions based on ingredient shelf life.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to plan for (default: 7, max: 30)",
                    "default": 7
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_shopping_list",
        "description": "Get your current shopping list from the active prep plan, organized by purchase date or storage category. Shows what to buy when, considering ingredient shelf life and when each ingredient will be used.",
        "parameters": {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": ["string", "null"],
                    "enum": ["date", "category"],
                    "description": "How to organize the list: 'date' groups by when to buy, 'category' groups by storage type (can be null, defaults to date)",
                    "default": "date"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_batch_cooking_suggestions",
        "description": "Get AI-powered batch cooking suggestions to optimize your prep and reduce food waste. Identifies ingredients that appear in multiple meals and can be prepped together.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "check_ingredient_shelf_life",
        "description": "Look up the shelf life and recommended storage for specific ingredients. Useful for planning when to purchase items.",
        "parameters": {
            "type": "object",
            "properties": {
                "ingredients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ingredient names to check"
                }
            },
            "required": ["ingredients"]
        }
    },
    {
        "type": "function",
        "name": "get_upcoming_commitments",
        "description": "Get all your upcoming meal shares and service orders for the next few days. Useful for understanding what you need to prepare for.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days ahead to look (default: 7)",
                    "default": 7
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "lookup_chef_hub_help",
        "description": "Look up detailed documentation about a Chef Hub feature. Use when a chef asks 'how do I...' questions about platform features like profile, services, payment links, meal shares, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The feature or topic to look up (e.g., 'payment links', 'services', 'break mode', 'profile')"
                }
            },
            "required": ["topic"]
        }
    },
    # ═══════════════════════════════════════════════════════════════════════════════
    # NAVIGATION & UI ACTION TOOLS
    # ═══════════════════════════════════════════════════════════════════════════════
    {
        "type": "function",
        "name": "navigate_to_dashboard_tab",
        "description": "Navigate the chef to a specific dashboard tab. Use when the chef asks how to do something or wants help with a specific feature. The chef will see a button they can click to navigate.",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    "enum": ["dashboard", "prep", "profile", "photos", "kitchen", "connections", "clients", "messages", "payments", "services", "meal-shares", "orders", "meals"],
                    "description": "The dashboard tab to navigate to. Note: 'meal-shares' is a sub-tab under 'services'."
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why navigating here helps (shown to the chef)"
                }
            },
            "required": ["tab", "reason"]
        }
    },
    {
        "type": "function",
        "name": "prefill_form",
        "description": "Pre-fill a form with suggested values and navigate to it. Use when helping the chef create something new like a dish, meal, or meal share. The chef will see a button to create the item with pre-filled data.",
        "parameters": {
            "type": "object",
            "properties": {
                "form_type": {
                    "type": "string",
                    "enum": ["ingredient", "dish", "meal", "meal-share", "service"],
                    "description": "Which form to prefill"
                },
                "fields": {
                    "type": "object",
                    "description": "Key-value pairs of field names and suggested values. For ingredient: name, calories, fat, carbohydrates, protein. For dish: name, featured. For meal: name, description, meal_type, price. For meal-share: event_date, event_time, base_price, max_orders. For service: title, description, service_type."
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of the suggestion (shown to the chef)"
                }
            },
            "required": ["form_type", "fields", "reason"]
        }
    },
    {
        "type": "function",
        "name": "scaffold_meal",
        "description": "Generate a complete meal structure with dishes and optionally ingredients using AI. Shows the chef a preview tree that they can edit before creating all items at once. Use when a chef wants to create a new meal and you want to help them quickly scaffold out the entire structure.",
        "parameters": {
            "type": "object",
            "properties": {
                "meal_name": {
                    "type": "string",
                    "description": "Name or hint for the meal (e.g., 'Sunday Soul Food Dinner', 'Italian Date Night')"
                },
                "meal_description": {
                    "type": ["string", "null"],
                    "description": "Optional description for the meal"
                },
                "meal_type": {
                    "type": "string",
                    "enum": ["Breakfast", "Lunch", "Dinner"],
                    "description": "Type of meal (default: Dinner)"
                },
                "include_dishes": {
                    "type": "boolean",
                    "description": "Whether to generate dish suggestions (default: true)"
                },
                "include_ingredients": {
                    "type": "boolean",
                    "description": "Whether to generate ingredient suggestions for each dish (default: false)"
                }
            },
            "required": ["meal_name"]
        }
    },
    # ═══════════════════════════════════════════════════════════════════════════════
    # NEW TOOLS: Search, Analytics, Seasonal, Substitutions, Messaging
    # ═══════════════════════════════════════════════════════════════════════════════
    {
        "type": "function",
        "name": "search_chef_dishes",
        "description": "Search through the chef's existing dishes by name, ingredient, or dietary tag. Use this to find dishes that match specific criteria or to check if the chef already has similar dishes in their menu.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - can be a dish name, ingredient name, or dietary tag (e.g., 'pasta', 'chicken', 'gluten-free')"
                },
                "search_type": {
                    "type": "string",
                    "enum": ["name", "ingredient", "dietary_tag", "all"],
                    "description": "What to search: 'name' for dish names, 'ingredient' for dishes containing an ingredient, 'dietary_tag' for dietary preferences, or 'all' to search everywhere (default: all)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10, max: 25)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "suggest_ingredient_substitution",
        "description": "Suggest safe ingredient substitutes for a given allergen or dietary restriction. Use this when a recipe contains an ingredient that conflicts with a family's allergies or dietary preferences.",
        "parameters": {
            "type": "object",
            "properties": {
                "ingredient": {
                    "type": "string",
                    "description": "The problematic ingredient that needs to be substituted (e.g., 'peanuts', 'milk', 'wheat flour')"
                },
                "reason": {
                    "type": "string",
                    "enum": ["allergy", "vegan", "vegetarian", "kosher", "halal", "gluten-free", "dairy-free", "low-sodium", "other"],
                    "description": "Why the substitution is needed"
                },
                "recipe_context": {
                    "type": ["string", "null"],
                    "description": "Optional: What dish is this for? Helps provide context-appropriate substitutions (e.g., 'for a cake' vs 'for a stir-fry')"
                }
            },
            "required": ["ingredient", "reason"]
        }
    },
    {
        "type": "function",
        "name": "get_chef_analytics",
        "description": "Get analytics and performance metrics for the chef's business, including revenue, popular dishes, client retention, and order trends.",
        "parameters": {
            "type": "object",
            "properties": {
                "time_period": {
                    "type": "string",
                    "enum": ["week", "month", "quarter", "year", "all_time"],
                    "description": "Time period for analytics (default: month)"
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["revenue", "orders", "popular_dishes", "client_retention", "meal_shares", "services"]
                    },
                    "description": "Which metrics to include (default: all)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_seasonal_ingredients",
        "description": "Get a list of ingredients that are currently in season based on the month. Useful for menu planning to ensure freshness, better prices, and sustainability.",
        "parameters": {
            "type": "object",
            "properties": {
                "month": {
                    "type": ["integer", "null"],
                    "description": "Month number (1-12). If not specified, uses the current month."
                },
                "category": {
                    "type": ["string", "null"],
                    "enum": ["vegetables", "fruits", "proteins", "herbs", "all"],
                    "description": "Filter by ingredient category (default: all)"
                },
                "region": {
                    "type": ["string", "null"],
                    "enum": ["northeast_us", "southeast_us", "midwest_us", "southwest_us", "west_coast_us", "general"],
                    "description": "Regional seasonality (default: general US seasonality)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "draft_client_message",
        "description": "Draft a professional message to send to a client. The message will be shown to the chef for review before sending. Use this for meal plan updates, order confirmations, dietary discussions, or general communication.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_type": {
                    "type": "string",
                    "enum": ["meal_plan_update", "order_confirmation", "dietary_question", "schedule_change", "general", "thank_you", "follow_up"],
                    "description": "Type of message to draft"
                },
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key points to include in the message"
                },
                "tone": {
                    "type": "string",
                    "enum": ["professional", "friendly", "casual"],
                    "description": "Tone of the message (default: friendly)"
                }
            },
            "required": ["message_type", "key_points"]
        }
    },
    # ═══════════════════════════════════════════════════════════════════════════════
    # MEMORY SYSTEM TOOLS
    # ═══════════════════════════════════════════════════════════════════════════════
    {
        "type": "function",
        "name": "save_chef_memory",
        "description": "Save a learning, pattern, preference, or reminder to long-term memory. Use this when you discover something important that should be remembered across conversations - like work patterns, personal preferences, lessons learned, or to-do items.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_type": {
                    "type": "string",
                    "enum": ["pattern", "preference", "lesson", "todo"],
                    "description": "Type of memory: 'pattern' (recurring patterns), 'preference' (chef's preferences), 'lesson' (things learned), 'todo' (reminders)"
                },
                "content": {
                    "type": "string",
                    "description": "The memory to save (max 1000 chars). Be specific and actionable."
                },
                "importance": {
                    "type": "integer",
                    "enum": [1, 2, 3, 4, 5],
                    "description": "Importance level: 1=low, 3=normal, 5=critical (default: 3)"
                },
                "family_specific": {
                    "type": "boolean",
                    "description": "Whether this memory is about the current family (default: false, meaning it's a general chef memory)"
                }
            },
            "required": ["memory_type", "content"]
        }
    },
    {
        "type": "function",
        "name": "recall_chef_memories",
        "description": "Search and recall memories by type or keyword. Use this to remember what you've learned about the chef's preferences, patterns, or any to-do items.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["pattern", "preference", "lesson", "todo"]
                    },
                    "description": "Filter by memory types (default: all)"
                },
                "keyword": {
                    "type": ["string", "null"],
                    "description": "Optional keyword to search for in memory content"
                },
                "include_family_memories": {
                    "type": "boolean",
                    "description": "Whether to include memories specific to the current family (default: true)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum memories to return (default: 10, max: 20)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "update_chef_memory",
        "description": "Update or delete an existing memory. Use when information has changed or a to-do is complete.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "integer",
                    "description": "ID of the memory to update"
                },
                "action": {
                    "type": "string",
                    "enum": ["update", "complete", "delete"],
                    "description": "'update' to modify content, 'complete' for todos, 'delete' to remove"
                },
                "new_content": {
                    "type": ["string", "null"],
                    "description": "New content for the memory (required for 'update' action)"
                }
            },
            "required": ["memory_id", "action"]
        }
    },
    # ═══════════════════════════════════════════════════════════════════════════════
    # PAYMENT LINK TOOLS
    # ═══════════════════════════════════════════════════════════════════════════════
    {
        "type": "function",
        "name": "preview_payment_link",
        "description": "Generate a preview of a payment link before creating it. Shows a summary with amount, recipient, description, and estimated platform fee. The chef can review and confirm, or request changes. Requires a family context (customer or lead).",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Payment amount in the main currency unit (e.g., 50.00 for $50). Must be at least $0.50 for most currencies."
                },
                "description": {
                    "type": "string",
                    "description": "What this payment is for (e.g., 'Weekly meal prep service', 'Catering deposit'). Max 500 chars."
                },
                "currency": {
                    "type": ["string", "null"],
                    "description": "ISO 4217 currency code (default: chef's default currency, usually 'usd')"
                },
                "expires_days": {
                    "type": "integer",
                    "description": "Days until the link expires (default: 30, min: 1, max: 90)",
                    "default": 30
                },
                "internal_notes": {
                    "type": ["string", "null"],
                    "description": "Optional private notes for the chef (not shown to client)"
                }
            },
            "required": ["amount", "description"]
        }
    },
    {
        "type": "function",
        "name": "create_and_send_payment_link",
        "description": "Create a Stripe payment link and send it to the current client via email. This creates a real payment link and emails it immediately. Should only be called after the chef has reviewed a preview from preview_payment_link and confirmed. Requires a family context (customer or lead).",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Payment amount in the main currency unit (e.g., 50.00 for $50). Must be at least $0.50 for most currencies."
                },
                "description": {
                    "type": "string",
                    "description": "What this payment is for. Max 500 chars."
                },
                "currency": {
                    "type": ["string", "null"],
                    "description": "ISO 4217 currency code (default: chef's default currency)"
                },
                "expires_days": {
                    "type": "integer",
                    "description": "Days until expiry (default: 30, min: 1, max: 90)",
                    "default": 30
                },
                "internal_notes": {
                    "type": ["string", "null"],
                    "description": "Optional private notes for the chef"
                }
            },
            "required": ["amount", "description"]
        }
    },
    {
        "type": "function",
        "name": "check_payment_link_status",
        "description": "Check the status of payment links for the current client. Returns recent payment links with their status (pending, paid, expired, cancelled), amounts, and dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": ["string", "null"],
                    "enum": ["pending", "paid", "expired", "cancelled", None],
                    "description": "Optional filter by status. If null, returns all statuses."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 5, max: 10)",
                    "default": 5
                }
            },
            "required": []
        }
    },
    # ═══════════════════════════════════════════════════════════════════════════════
    # PROACTIVE INSIGHTS TOOLS
    # ═══════════════════════════════════════════════════════════════════════════════
    {
        "type": "function",
        "name": "get_proactive_insights",
        "description": "Fetch unread proactive insights and recommendations for the chef. These are AI-generated suggestions like follow-up reminders, batch cooking opportunities, and client wins.",
        "parameters": {
            "type": "object",
            "properties": {
                "insight_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["followup_needed", "batch_opportunity", "seasonal_suggestion", "client_win", "scheduling_tip"]
                    },
                    "description": "Filter by insight types (default: all)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum insights to return (default: 5)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "dismiss_insight",
        "description": "Dismiss a proactive insight when it's no longer relevant or the chef has seen it.",
        "parameters": {
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "integer",
                    "description": "ID of the insight to dismiss"
                }
            },
            "required": ["insight_id"]
        }
    },
    {
        "type": "function",
        "name": "act_on_insight",
        "description": "Take action on a proactive insight. The action depends on the insight type - could be drafting a message, creating a prep plan, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "integer",
                    "description": "ID of the insight to act on"
                },
                "action": {
                    "type": "string",
                    "enum": ["draft_message", "create_prep_plan", "schedule_followup", "acknowledge", "other"],
                    "description": "What action to take"
                },
                "notes": {
                    "type": ["string", "null"],
                    "description": "Optional notes about the action taken"
                }
            },
            "required": ["insight_id", "action"]
        }
    }
]


# Tools that require a family/customer context to function
# These will be disabled when no family is selected
FAMILY_REQUIRED_TOOLS = {
    "get_family_dietary_summary",
    "check_recipe_compliance",
    "suggest_family_menu",
    "scale_recipe_for_household",
    "get_family_order_history",
    "add_family_note",
    "get_upcoming_family_orders",
    "get_household_members",
    "save_family_insight",
    "get_family_insights",
    "estimate_prep_time",  # needs household size context
    "draft_client_message",  # needs a client to message
    "preview_payment_link",  # needs a recipient
    "create_and_send_payment_link",  # needs a recipient
    "check_payment_link_status",  # needs a client to check
}


def get_sous_chef_tools(include_family_tools: bool = True) -> List[Dict[str, Any]]:
    """
    Return the list of Sous Chef tool definitions in Groq/OpenAI format.
    
    Args:
        include_family_tools: If False, exclude tools that require a family context.
                              Used when chef is using Sous Chef without selecting a family.
    """
    # Transform to the nested function format that Groq expects:
    # {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    formatted_tools = []
    for tool in SOUS_CHEF_TOOLS:
        tool_name = tool["name"]
        
        # Skip family-required tools if not including them
        if not include_family_tools and tool_name in FAMILY_REQUIRED_TOOLS:
            continue
            
        formatted_tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool["description"],
                "parameters": tool["parameters"]
            }
        })
    return formatted_tools


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

# SOP file mapping for Chef Hub help lookup
SOP_TOPIC_MAP = {
    "profile": "CHEF_PROFILE_GALLERY_SOP.md",
    "gallery": "CHEF_PROFILE_GALLERY_SOP.md",
    "photos": "CHEF_PROFILE_GALLERY_SOP.md",
    "break": "CHEF_PROFILE_GALLERY_SOP.md",
    "stripe": "CHEF_PROFILE_GALLERY_SOP.md",
    "kitchen": "CHEF_KITCHEN_SOP.md",
    "ingredients": "CHEF_KITCHEN_SOP.md",
    "dishes": "CHEF_KITCHEN_SOP.md",
    "services": "CHEF_SERVICES_PRICING_SOP.md",
    "pricing": "CHEF_SERVICES_PRICING_SOP.md",
    "tiers": "CHEF_SERVICES_PRICING_SOP.md",
    "meal-shares": "CHEF_MEAL_SHARES_SOP.md",
    "meal shares": "CHEF_MEAL_SHARES_SOP.md",
    "shared meals": "CHEF_MEAL_SHARES_SOP.md",
    "events": "CHEF_MEAL_SHARES_SOP.md",  # Legacy alias - "Events" renamed to "Meal Shares"
    "meals": "CHEF_MEAL_SHARES_SOP.md",
    "clients": "CHEF_CLIENT_MANAGEMENT_SOP.md",
    "households": "CHEF_CLIENT_MANAGEMENT_SOP.md",
    "connections": "CHEF_CLIENT_MANAGEMENT_SOP.md",  # Connection management is now in Clients tab
    "accept": "CHEF_CLIENT_MANAGEMENT_SOP.md",
    "decline": "CHEF_CLIENT_MANAGEMENT_SOP.md",
    "payment": "CHEF_PAYMENT_LINKS_SOP.md",
    "invoice": "CHEF_PAYMENT_LINKS_SOP.md",
    "prep": "CHEF_PREP_PLANNING_SOP.md",
    "shopping": "CHEF_PREP_PLANNING_SOP.md",
}


def handle_sous_chef_tool_call(
    name: str,
    arguments: str,
    chef: Chef,
    customer: Optional[CustomUser] = None,
    lead: Optional[Lead] = None
) -> Dict[str, Any]:
    """
    Route and execute a sous chef tool call.
    
    Args:
        name: Tool name
        arguments: JSON string of arguments
        chef: The Chef instance
        customer: Optional platform customer
        lead: Optional CRM lead
        
    Returns:
        Tool execution result
    """
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        args = {}
    
    tool_map = {
        "get_family_dietary_summary": _get_family_dietary_summary,
        "check_recipe_compliance": _check_recipe_compliance,
        "suggest_family_menu": _suggest_family_menu,
        "scale_recipe_for_household": _scale_recipe_for_household,
        "get_family_order_history": _get_family_order_history,
        "add_family_note": _add_family_note,
        "get_upcoming_family_orders": _get_upcoming_family_orders,
        "estimate_prep_time": _estimate_prep_time,
        "get_household_members": _get_household_members,
        "save_family_insight": _save_family_insight,
        "get_family_insights": _get_family_insights,
        # Prep planning tools
        "get_prep_plan_summary": _get_prep_plan_summary,
        "generate_prep_plan": _generate_prep_plan,
        "get_shopping_list": _get_shopping_list,
        "get_batch_cooking_suggestions": _get_batch_cooking_suggestions,
        "check_ingredient_shelf_life": _check_ingredient_shelf_life,
        "get_upcoming_commitments": _get_upcoming_commitments_tool,
        # Chef Hub help tool
        "lookup_chef_hub_help": _lookup_chef_hub_help,
        # Navigation & UI action tools
        "navigate_to_dashboard_tab": _navigate_to_dashboard_tab,
        "prefill_form": _prefill_form,
        "scaffold_meal": _scaffold_meal,
        # New tools: Search, Analytics, Seasonal, Substitutions, Messaging
        "search_chef_dishes": _search_chef_dishes,
        "suggest_ingredient_substitution": _suggest_ingredient_substitution,
        "get_chef_analytics": _get_chef_analytics,
        "get_seasonal_ingredients": _get_seasonal_ingredients,
        "draft_client_message": _draft_client_message,
        # Memory system tools
        "save_chef_memory": _save_chef_memory,
        "recall_chef_memories": _recall_chef_memories,
        "update_chef_memory": _update_chef_memory,
        # Proactive insights tools
        "get_proactive_insights": _get_proactive_insights,
        "dismiss_insight": _dismiss_insight,
        "act_on_insight": _act_on_insight,
        # Payment link tools
        "preview_payment_link": _preview_payment_link,
        "create_and_send_payment_link": _create_and_send_payment_link,
        "check_payment_link_status": _check_payment_link_status,
    }
    
    handler = tool_map.get(name)
    if not handler:
        return {"status": "error", "message": f"Unknown tool: {name}"}
    
    try:
        return handler(args, chef, customer, lead)
    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        return {"status": "error", "message": str(e)}


def _lookup_chef_hub_help(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Look up Chef Hub documentation for a topic."""
    import os
    from django.conf import settings
    
    topic = args.get("topic", "").lower()
    
    # Find matching SOP file
    sop_file = None
    for keyword, filename in SOP_TOPIC_MAP.items():
        if keyword in topic:
            sop_file = filename
            break
    
    if not sop_file:
        return {
            "status": "success",
            "content": "No specific documentation found for that topic. Available topics: profile, gallery, photos, kitchen, services, meal shares, meals, clients (including connection management), payment links, prep planning, break mode."
        }
    
    # Read the SOP file
    docs_path = os.path.join(settings.BASE_DIR, "docs", sop_file)
    try:
        with open(docs_path, "r") as f:
            content = f.read()
        
        # Extract relevant section based on topic (simplified: return key sections)
        # For now, return a trimmed version to stay within token limits
        if len(content) > 4000:
            content = content[:4000] + "\n\n[Content trimmed for length...]"
        
        return {
            "status": "success", 
            "source": sop_file,
            "content": content
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "message": f"Documentation file not found: {sop_file}"
        }


def _get_family_dietary_summary(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get comprehensive dietary summary for the household."""
    all_restrictions = set()
    all_allergies = set()
    member_details = []
    household_size = 1
    
    if customer:
        household_size = getattr(customer, 'household_member_count', 1)
        
        # Primary contact
        prefs = [p.name for p in customer.dietary_preferences.all()]
        allergies = list(customer.allergies or []) + list(customer.custom_allergies or [])
        
        all_restrictions.update(prefs)
        all_allergies.update(allergies)
        
        member_details.append({
            "name": customer.first_name or customer.username,
            "role": "Primary Contact",
            "dietary_preferences": prefs,
            "allergies": allergies
        })
        
        # Household members
        if hasattr(customer, 'household_members'):
            for member in customer.household_members.all():
                m_prefs = [p.name for p in member.dietary_preferences.all()]
                all_restrictions.update(m_prefs)
                
                member_details.append({
                    "name": member.name,
                    "age": member.age,
                    "dietary_preferences": m_prefs,
                    "notes": member.notes
                })
    
    elif lead:
        household_size = lead.household_size
        
        # Primary contact
        prefs = list(lead.dietary_preferences or [])
        allergies = list(lead.allergies or []) + list(lead.custom_allergies or [])
        
        all_restrictions.update(prefs)
        all_allergies.update(allergies)
        
        member_details.append({
            "name": f"{lead.first_name} {lead.last_name}".strip(),
            "role": "Primary Contact",
            "dietary_preferences": prefs,
            "allergies": allergies
        })
        
        # Household members
        for member in lead.household_members.all():
            m_prefs = list(member.dietary_preferences or [])
            m_allergies = list(member.allergies or []) + list(member.custom_allergies or [])
            
            all_restrictions.update(m_prefs)
            all_allergies.update(m_allergies)
            
            member_details.append({
                "name": member.name,
                "relationship": member.relationship,
                "age": member.age,
                "dietary_preferences": m_prefs,
                "allergies": m_allergies,
                "notes": member.notes
            })
    
    return {
        "status": "success",
        "household_size": household_size,
        "all_dietary_restrictions": sorted(list(all_restrictions)),
        "all_allergies_must_avoid": sorted(list(all_allergies)),
        "member_details": member_details,
        "compliance_note": "Any meal must satisfy ALL listed restrictions and avoid ALL listed allergies."
    }


def _check_recipe_compliance(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Check if a recipe is compliant with family dietary needs."""
    recipe_name = args.get("recipe_name", "Unnamed Recipe")
    ingredients = args.get("ingredients", [])
    
    if not ingredients:
        return {"status": "error", "message": "No ingredients provided"}
    
    # Get family dietary info
    dietary_summary = _get_family_dietary_summary({}, chef, customer, lead)
    
    all_allergies = set(a.lower() for a in dietary_summary.get("all_allergies_must_avoid", []))
    all_restrictions = set(r.lower() for r in dietary_summary.get("all_dietary_restrictions", []))
    
    # Common allergen mappings (simplified)
    allergen_keywords = {
        "peanuts": ["peanut", "groundnut"],
        "tree nuts": ["almond", "walnut", "cashew", "pecan", "pistachio", "hazelnut", "macadamia", "brazil nut"],
        "milk": ["milk", "cream", "butter", "cheese", "yogurt", "whey", "casein", "lactose"],
        "egg": ["egg", "mayonnaise", "meringue"],
        "wheat": ["wheat", "flour", "bread", "pasta", "couscous"],
        "soy": ["soy", "tofu", "edamame", "tempeh", "miso"],
        "fish": ["fish", "salmon", "tuna", "cod", "tilapia", "anchovy"],
        "shellfish": ["shrimp", "crab", "lobster", "oyster", "clam", "mussel", "scallop"],
        "sesame": ["sesame", "tahini"],
        "gluten": ["wheat", "barley", "rye", "flour", "bread", "pasta"],
    }
    
    # Diet restriction incompatible ingredients (simplified)
    restriction_conflicts = {
        "vegan": ["meat", "chicken", "beef", "pork", "fish", "egg", "milk", "cheese", "butter", "cream", "honey"],
        "vegetarian": ["meat", "chicken", "beef", "pork", "fish", "bacon", "gelatin"],
        "pescatarian": ["meat", "chicken", "beef", "pork", "bacon"],
        "gluten-free": ["wheat", "flour", "bread", "pasta", "barley", "rye"],
        "dairy-free": ["milk", "cheese", "butter", "cream", "yogurt", "whey"],
        "keto": ["sugar", "bread", "pasta", "rice", "potato", "corn"],
        "halal": ["pork", "bacon", "ham", "lard", "alcohol", "wine"],
        "kosher": ["pork", "shellfish", "mixing dairy and meat"],
    }
    
    issues = []
    warnings = []
    
    ingredients_lower = [i.lower() for i in ingredients]
    
    # Check allergens
    for allergen in all_allergies:
        allergen_lower = allergen.lower()
        keywords = allergen_keywords.get(allergen_lower, [allergen_lower])
        
        for ingredient in ingredients_lower:
            for keyword in keywords:
                if keyword in ingredient:
                    issues.append(f"⚠️ ALLERGEN ALERT: '{ingredient}' may contain {allergen}")
    
    # Check dietary restrictions
    for restriction in all_restrictions:
        restriction_lower = restriction.lower()
        conflicts = restriction_conflicts.get(restriction_lower, [])
        
        for ingredient in ingredients_lower:
            for conflict in conflicts:
                if conflict in ingredient:
                    warnings.append(f"⚡ Dietary conflict: '{ingredient}' may not be compatible with {restriction}")
    
    is_compliant = len(issues) == 0
    
    return {
        "status": "success",
        "recipe_name": recipe_name,
        "is_compliant": is_compliant,
        "allergen_issues": issues,
        "dietary_warnings": warnings,
        "ingredients_checked": len(ingredients),
        "recommendation": "SAFE to prepare" if is_compliant else "DO NOT prepare without modifications"
    }


def _suggest_family_menu(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Suggest menu ideas based on family preferences."""
    days = args.get("days", 7)
    meal_types = args.get("meal_types", ["Breakfast", "Lunch", "Dinner"])
    cuisine_preference = args.get("cuisine_preference")
    
    # Get dietary summary
    dietary_summary = _get_family_dietary_summary({}, chef, customer, lead)
    
    restrictions = dietary_summary.get("all_dietary_restrictions", [])
    allergies = dietary_summary.get("all_allergies_must_avoid", [])
    household_size = dietary_summary.get("household_size", 1)
    
    return {
        "status": "success",
        "message": "Menu suggestion framework ready",
        "parameters": {
            "days_to_plan": days,
            "meal_types": meal_types,
            "household_size": household_size,
            "cuisine_preference": cuisine_preference,
        },
        "constraints": {
            "must_satisfy_diets": restrictions,
            "must_avoid_allergens": allergies,
        },
        "suggestion_note": "Please generate menu suggestions that comply with ALL listed constraints. Each dish should be clearly labeled with which dietary restrictions it satisfies."
    }


def _scale_recipe_for_household(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Scale recipe ingredients for household size."""
    recipe_name = args.get("recipe_name", "Recipe")
    original_servings = args.get("original_servings", 4)
    ingredients = args.get("ingredients", [])
    servings_per_person = args.get("servings_per_person", 1)
    
    # Get household size
    if customer:
        household_size = getattr(customer, 'household_member_count', 1)
    elif lead:
        household_size = lead.household_size
    else:
        household_size = 1
    
    target_servings = household_size * servings_per_person
    scale_factor = target_servings / original_servings if original_servings > 0 else 1
    
    scaled_ingredients = []
    for ing in ingredients:
        scaled = {
            "name": ing.get("name", "Unknown"),
            "original_quantity": ing.get("quantity", 0),
            "scaled_quantity": round(ing.get("quantity", 0) * scale_factor, 2),
            "unit": ing.get("unit", "")
        }
        scaled_ingredients.append(scaled)
    
    return {
        "status": "success",
        "recipe_name": recipe_name,
        "original_servings": original_servings,
        "target_servings": target_servings,
        "household_size": household_size,
        "scale_factor": round(scale_factor, 2),
        "scaled_ingredients": scaled_ingredients
    }


def _get_family_order_history(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get order history for this family with this chef."""
    from chef_services.models import ChefServiceOrder
    from meals.models import ChefMealOrder
    
    limit = args.get("limit", 10)
    orders = []
    
    if customer:
        # Service orders
        service_orders = ChefServiceOrder.objects.filter(
            chef=chef,
            customer=customer,
            status__in=['confirmed', 'completed']
        ).select_related('offering', 'tier').order_by('-created_at')[:limit]
        
        for order in service_orders:
            orders.append({
                "type": "service",
                "date": order.created_at.strftime('%Y-%m-%d'),
                "service": order.offering.title if order.offering else "Service",
                "status": order.status,
                "household_size": order.household_size,
            })
        
        # Meal orders
        meal_orders = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            customer=customer,
            status__in=['confirmed', 'completed']
        ).select_related('meal_event__meal').order_by('-created_at')[:limit]
        
        for order in meal_orders:
            orders.append({
                "type": "meal_event",
                "date": order.created_at.strftime('%Y-%m-%d'),
                "meal": order.meal_event.meal.name if order.meal_event and order.meal_event.meal else "Meal",
                "quantity": order.quantity,
                "status": order.status,
            })
    
    # Sort combined by date
    orders.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    return {
        "status": "success",
        "total_orders": len(orders),
        "orders": orders[:limit],
        "family_type": "customer" if customer else "lead"
    }


def _add_family_note(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Add a note to the family's CRM record."""
    summary = args.get("summary", "")[:255]
    details = args.get("details", "")
    interaction_type = args.get("interaction_type", "note")
    next_steps = args.get("next_steps", "")
    
    if not summary:
        return {"status": "error", "message": "Summary is required"}
    
    # Find or create lead for this family
    if customer:
        target_lead, _ = Lead.objects.get_or_create(
            owner=chef.user,
            email=customer.email,
            defaults={
                'first_name': customer.first_name or customer.username,
                'last_name': customer.last_name or '',
                'status': Lead.Status.WON,
                'source': Lead.Source.WEB,
            }
        )
    elif lead:
        target_lead = lead
    else:
        return {"status": "error", "message": "No family context available"}
    
    # Create interaction
    interaction = LeadInteraction.objects.create(
        lead=target_lead,
        author=chef.user,
        interaction_type=interaction_type,
        summary=summary,
        details=details,
        next_steps=next_steps,
        happened_at=timezone.now(),
    )
    
    return {
        "status": "success",
        "message": "Note added successfully",
        "note_id": interaction.id,
        "summary": summary,
        "created_at": interaction.created_at.isoformat()
    }


def _get_upcoming_family_orders(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get upcoming orders for this family."""
    from chef_services.models import ChefServiceOrder
    from meals.models import ChefMealOrder
    
    now = timezone.now()
    upcoming = []
    
    if customer:
        # Upcoming service orders
        service_orders = ChefServiceOrder.objects.filter(
            chef=chef,
            customer=customer,
            service_date__gte=now.date(),
            status__in=['draft', 'awaiting_payment', 'confirmed']
        ).select_related('offering').order_by('service_date')
        
        for order in service_orders:
            upcoming.append({
                "type": "service",
                "service_date": order.service_date.isoformat() if order.service_date else None,
                "service_time": order.service_start_time.isoformat() if order.service_start_time else None,
                "service": order.offering.title if order.offering else "Service",
                "status": order.status,
            })
        
        # Upcoming meal events
        meal_orders = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            customer=customer,
            meal_event__event_date__gte=now.date(),
            status__in=['placed', 'confirmed']
        ).select_related('meal_event__meal').order_by('meal_event__event_date')
        
        for order in meal_orders:
            upcoming.append({
                "type": "meal_event",
                "event_date": order.meal_event.event_date.isoformat() if order.meal_event else None,
                "meal": order.meal_event.meal.name if order.meal_event and order.meal_event.meal else "Meal",
                "quantity": order.quantity,
                "status": order.status,
            })
    
    # Sort by date
    upcoming.sort(key=lambda x: x.get('service_date') or x.get('event_date') or '')
    
    return {
        "status": "success",
        "upcoming_orders": upcoming,
        "total_upcoming": len(upcoming)
    }


def _estimate_prep_time(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Estimate total prep time for dishes."""
    dishes = args.get("dishes", [])
    parallel_cooking = args.get("parallel_cooking", True)
    
    if not dishes:
        return {"status": "error", "message": "No dishes provided"}
    
    # Get household size for scaling
    if customer:
        household_size = getattr(customer, 'household_member_count', 1)
    elif lead:
        household_size = lead.household_size
    else:
        household_size = 1
    
    # Scale factor for larger households (more prep, same cook time)
    prep_scale = 1 + (household_size - 1) * 0.15  # 15% more prep per extra person
    
    total_prep = 0
    total_cook = 0
    max_cook = 0
    
    dish_breakdown = []
    
    for dish in dishes:
        base_prep = dish.get("base_prep_minutes", 15)
        base_cook = dish.get("base_cook_minutes", 30)
        
        scaled_prep = round(base_prep * prep_scale)
        
        dish_breakdown.append({
            "name": dish.get("name", "Dish"),
            "prep_minutes": scaled_prep,
            "cook_minutes": base_cook,
        })
        
        total_prep += scaled_prep
        total_cook += base_cook
        max_cook = max(max_cook, base_cook)
    
    # If parallel cooking, cook time is the longest dish, not sum
    effective_cook = max_cook if parallel_cooking else total_cook
    total_time = total_prep + effective_cook
    
    return {
        "status": "success",
        "household_size": household_size,
        "dishes": dish_breakdown,
        "total_prep_minutes": total_prep,
        "total_cook_minutes": effective_cook,
        "total_time_minutes": total_time,
        "total_time_formatted": f"{total_time // 60}h {total_time % 60}m" if total_time >= 60 else f"{total_time}m",
        "parallel_cooking": parallel_cooking,
        "note": f"Prep time scaled by {round(prep_scale, 2)}x for {household_size} people"
    }


def _get_household_members(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get detailed info about household members."""
    members = []
    
    if customer:
        # Primary contact
        prefs = [p.name for p in customer.dietary_preferences.all()]
        allergies = list(customer.allergies or []) + list(customer.custom_allergies or [])
        
        members.append({
            "name": f"{customer.first_name} {customer.last_name}".strip() or customer.username,
            "role": "Primary Contact",
            "email": customer.email,
            "dietary_preferences": prefs,
            "allergies": allergies,
        })
        
        # Other members
        if hasattr(customer, 'household_members'):
            for member in customer.household_members.all():
                m_prefs = [p.name for p in member.dietary_preferences.all()]
                members.append({
                    "name": member.name,
                    "age": member.age,
                    "dietary_preferences": m_prefs,
                    "notes": member.notes,
                })
    
    elif lead:
        # Primary contact
        prefs = list(lead.dietary_preferences or [])
        allergies = list(lead.allergies or []) + list(lead.custom_allergies or [])
        
        members.append({
            "name": f"{lead.first_name} {lead.last_name}".strip(),
            "role": "Primary Contact",
            "email": lead.email,
            "phone": lead.phone,
            "dietary_preferences": prefs,
            "allergies": allergies,
        })
        
        # Other members
        for member in lead.household_members.all():
            m_prefs = list(member.dietary_preferences or [])
            m_allergies = list(member.allergies or []) + list(member.custom_allergies or [])
            
            members.append({
                "name": member.name,
                "relationship": member.relationship,
                "age": member.age,
                "dietary_preferences": m_prefs,
                "allergies": m_allergies,
                "notes": member.notes,
            })
    
    return {
        "status": "success",
        "total_members": len(members),
        "members": members
    }


def _save_family_insight(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Save a persistent insight about this family."""
    from customer_dashboard.models import FamilyInsight, SousChefThread
    
    insight_type = args.get("insight_type", "preference")
    content = args.get("content", "").strip()
    
    if not content:
        return {"status": "error", "message": "Content is required"}
    
    if len(content) > 500:
        content = content[:500]
    
    valid_types = ["preference", "tip", "avoid", "success"]
    if insight_type not in valid_types:
        return {"status": "error", "message": f"Invalid insight_type. Must be one of: {valid_types}"}
    
    # Find the current active thread (for source_thread reference)
    thread_filter = {'chef': chef, 'is_active': True}
    if customer:
        thread_filter['customer'] = customer
    elif lead:
        thread_filter['lead'] = lead
    
    source_thread = SousChefThread.objects.filter(**thread_filter).first()
    
    # Create the insight
    insight = FamilyInsight.objects.create(
        chef=chef,
        customer=customer,
        lead=lead,
        insight_type=insight_type,
        content=content,
        source_thread=source_thread
    )
    
    # Get family name for response
    family_name = "this family"
    if customer:
        family_name = f"{customer.first_name} {customer.last_name}".strip() or customer.username
    elif lead:
        family_name = f"{lead.first_name} {lead.last_name}".strip()
    
    type_labels = {
        "preference": "Preference",
        "tip": "Useful Tip",
        "avoid": "Thing to Avoid",
        "success": "Success"
    }
    
    return {
        "status": "success",
        "message": f"Saved {type_labels[insight_type].lower()} for {family_name}",
        "insight_id": insight.id,
        "insight_type": insight_type,
        "content": content
    }


def _get_family_insights(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get all saved insights about this family."""
    from customer_dashboard.models import FamilyInsight
    
    # Build filter for this family
    insight_filter = {'chef': chef, 'is_active': True}
    if customer:
        insight_filter['customer'] = customer
        insight_filter['lead__isnull'] = True
    elif lead:
        insight_filter['lead'] = lead
        insight_filter['customer__isnull'] = True
    else:
        return {"status": "error", "message": "No family selected"}
    
    insights = FamilyInsight.objects.filter(**insight_filter).order_by('-created_at')[:20]
    
    # Group by type
    grouped = {
        "preference": [],
        "tip": [],
        "avoid": [],
        "success": []
    }
    
    for insight in insights:
        grouped[insight.insight_type].append({
            "id": insight.id,
            "content": insight.content,
            "created_at": insight.created_at.isoformat()
        })
    
    # Get family name
    family_name = "this family"
    if customer:
        family_name = f"{customer.first_name} {customer.last_name}".strip() or customer.username
    elif lead:
        family_name = f"{lead.first_name} {lead.last_name}".strip()
    
    return {
        "status": "success",
        "family": family_name,
        "total_insights": len(insights),
        "insights_by_type": {
            "preferences": grouped["preference"],
            "tips": grouped["tip"],
            "things_to_avoid": grouped["avoid"],
            "successes": grouped["success"]
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PREP PLANNING TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_prep_plan_summary(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get summary of chef's prep planning status."""
    from datetime import date
    from chefs.resource_planning.models import ChefPrepPlan, ChefPrepPlanItem
    
    today = date.today()
    
    # Active plans
    active_plans = ChefPrepPlan.objects.filter(
        chef=chef,
        plan_end_date__gte=today,
        status__in=['generated', 'in_progress']
    )
    active_count = active_plans.count()
    
    # Items to purchase today
    items_today = ChefPrepPlanItem.objects.filter(
        prep_plan__chef=chef,
        prep_plan__status__in=['generated', 'in_progress'],
        suggested_purchase_date=today,
        is_purchased=False
    ).count()
    
    # Overdue items
    items_overdue = ChefPrepPlanItem.objects.filter(
        prep_plan__chef=chef,
        prep_plan__status__in=['generated', 'in_progress'],
        suggested_purchase_date__lt=today,
        is_purchased=False
    ).count()
    
    # Get latest active plan summary
    latest_plan = active_plans.order_by('-plan_start_date').first()
    latest_plan_info = None
    if latest_plan:
        latest_plan_info = {
            "id": latest_plan.id,
            "date_range": f"{latest_plan.plan_start_date} to {latest_plan.plan_end_date}",
            "total_meals": latest_plan.total_meals,
            "total_servings": latest_plan.total_servings,
            "unique_ingredients": latest_plan.unique_ingredients,
            "status": latest_plan.status
        }
    
    return {
        "status": "success",
        "active_plans_count": active_count,
        "items_to_purchase_today": items_today,
        "items_overdue": items_overdue,
        "latest_plan": latest_plan_info,
        "recommendation": (
            "You have overdue shopping items!" if items_overdue > 0
            else f"You have {items_today} items to purchase today." if items_today > 0
            else "Your prep planning is up to date!" if active_count > 0
            else "No active prep plans. Generate one to optimize your shopping."
        )
    }


def _generate_prep_plan(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Generate a new prep plan for the chef."""
    from datetime import date, timedelta
    from chefs.resource_planning.services import generate_prep_plan
    
    days = min(max(args.get("days", 7), 1), 30)  # Clamp between 1-30
    
    today = date.today()
    end_date = today + timedelta(days=days - 1)
    
    try:
        prep_plan = generate_prep_plan(
            chef=chef,
            start_date=today,
            end_date=end_date,
            notes=""
        )
        
        return {
            "status": "success",
            "message": f"Generated prep plan for {days} days",
            "plan_id": prep_plan.id,
            "date_range": f"{prep_plan.plan_start_date} to {prep_plan.plan_end_date}",
            "total_meals": prep_plan.total_meals,
            "total_servings": prep_plan.total_servings,
            "unique_ingredients": prep_plan.unique_ingredients,
            "items_count": prep_plan.items.count(),
            "tip": "Use get_shopping_list to see what to buy and when."
        }
        
    except Exception as e:
        logger.error(f"Failed to generate prep plan: {e}")
        return {
            "status": "error",
            "message": f"Failed to generate prep plan: {str(e)}"
        }


def _get_shopping_list(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get shopping list from the active prep plan."""
    from datetime import date
    from chefs.resource_planning.models import ChefPrepPlan
    from chefs.resource_planning.services import get_shopping_list_by_date, get_shopping_list_by_category
    
    group_by = args.get("group_by", "date")
    today = date.today()
    
    # Get latest active plan
    prep_plan = ChefPrepPlan.objects.filter(
        chef=chef,
        plan_end_date__gte=today,
        status__in=['generated', 'in_progress']
    ).order_by('-plan_start_date').first()
    
    if not prep_plan:
        return {
            "status": "error",
            "message": "No active prep plan found. Use generate_prep_plan to create one."
        }
    
    if group_by == "category":
        shopping_list = get_shopping_list_by_category(prep_plan)
    else:
        shopping_list = get_shopping_list_by_date(prep_plan)
    
    # Count items and summarize
    total_items = sum(len(items) for items in shopping_list.values())
    unpurchased = sum(
        1 for items in shopping_list.values() 
        for item in items 
        if not item.get('is_purchased')
    )
    
    # Format for readability
    formatted_list = {}
    for key, items in shopping_list.items():
        formatted_list[key] = [
            {
                "ingredient": item['ingredient'],
                "quantity": f"{item['quantity']} {item.get('unit', 'units')}",
                "shelf_life": f"{item.get('shelf_life_days', '?')} days",
                "storage": item.get('storage', 'refrigerated'),
                "timing_status": item.get('timing_status', 'unknown'),
                "purchased": item.get('is_purchased', False)
            }
            for item in items
        ]
    
    return {
        "status": "success",
        "plan_id": prep_plan.id,
        "date_range": f"{prep_plan.plan_start_date} to {prep_plan.plan_end_date}",
        "grouped_by": group_by,
        "total_items": total_items,
        "unpurchased_items": unpurchased,
        "shopping_list": formatted_list,
        "tip": (
            "Items are organized by suggested purchase date based on shelf life." if group_by == "date"
            else "Items are organized by storage type (refrigerated, frozen, pantry, counter)."
        )
    }


def _get_batch_cooking_suggestions(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get batch cooking suggestions from the active prep plan."""
    from datetime import date
    from chefs.resource_planning.models import ChefPrepPlan
    
    today = date.today()
    
    # Get latest active plan
    prep_plan = ChefPrepPlan.objects.filter(
        chef=chef,
        plan_end_date__gte=today,
        status__in=['generated', 'in_progress']
    ).order_by('-plan_start_date').first()
    
    if not prep_plan:
        return {
            "status": "error",
            "message": "No active prep plan found. Use generate_prep_plan to create one."
        }
    
    batch_data = prep_plan.batch_suggestions or {}
    suggestions = batch_data.get('suggestions', [])
    tips = batch_data.get('general_tips', [])
    
    return {
        "status": "success",
        "plan_id": prep_plan.id,
        "date_range": f"{prep_plan.plan_start_date} to {prep_plan.plan_end_date}",
        "batch_suggestions": [
            {
                "ingredient": s.get('ingredient'),
                "total_quantity": f"{s.get('total_quantity', 0)} {s.get('unit', 'units')}",
                "suggestion": s.get('suggestion'),
                "prep_day": s.get('prep_day'),
                "meals_covered": s.get('meals_covered', [])
            }
            for s in suggestions
        ],
        "general_tips": tips,
        "summary": f"Found {len(suggestions)} batch cooking opportunities to save time and reduce waste."
    }


def _check_ingredient_shelf_life(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Look up shelf life for ingredients."""
    from chefs.resource_planning.shelf_life import get_ingredient_shelf_lives, get_default_shelf_life
    
    ingredients = args.get("ingredients", [])
    
    if not ingredients:
        return {"status": "error", "message": "No ingredients provided"}
    
    if len(ingredients) > 20:
        ingredients = ingredients[:20]  # Limit to 20
    
    try:
        response = get_ingredient_shelf_lives(ingredients)
        
        results = []
        for ing in response.ingredients:
            results.append({
                "ingredient": ing.ingredient_name,
                "shelf_life_days": ing.shelf_life_days,
                "storage": ing.storage_type,
                "notes": ing.notes
            })
        
        return {
            "status": "success",
            "ingredients": results,
            "tip": "Shelf life assumes proper storage. Refrigerated items should be kept at 35-40°F."
        }
        
    except Exception as e:
        # Fallback to defaults
        logger.warning(f"Shelf life API failed, using defaults: {e}")
        results = []
        for name in ingredients:
            defaults = get_default_shelf_life(name)
            results.append({
                "ingredient": name,
                "shelf_life_days": defaults['shelf_life_days'],
                "storage": defaults['storage_type'],
                "notes": "Estimated based on ingredient category"
            })
        
        return {
            "status": "success",
            "ingredients": results,
            "note": "Using estimated shelf life data"
        }


def _get_upcoming_commitments_tool(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Get upcoming meal commitments including client meal plans, meal shares, and services."""
    from datetime import date, timedelta
    from chefs.resource_planning.services import get_upcoming_commitments
    
    days = min(max(args.get("days", 7), 1), 30)
    
    today = date.today()
    end_date = today + timedelta(days=days - 1)
    
    commitments = get_upcoming_commitments(chef, today, end_date)
    
    # Count by type
    type_counts = {'client_meal_plan': 0, 'meal_event': 0, 'service_order': 0}
    formatted = []
    for c in commitments:
        type_counts[c.commitment_type] = type_counts.get(c.commitment_type, 0) + 1
        
        type_labels = {
            'client_meal_plan': 'Client Meal Plan',
            'meal_event': 'Meal Share',  # "Events" renamed to "Meal Shares"
            'service_order': 'Service'
        }
        
        formatted.append({
            "type": type_labels.get(c.commitment_type, c.commitment_type),
            "date": c.service_date.isoformat(),
            "meal_name": c.meal_name,
            "servings": c.servings,
            "customer": c.customer_name or None,
            "dishes_count": len(c.dishes)
        })
    
    # Group by date
    by_date = {}
    for c in formatted:
        date_key = c["date"]
        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(c)
    
    total_servings = sum(c.servings for c in commitments)
    
    # Build detailed summary
    summary_parts = []
    if type_counts['client_meal_plan'] > 0:
        summary_parts.append(f"{type_counts['client_meal_plan']} client meal plan meals")
    if type_counts['meal_event'] > 0:
        summary_parts.append(f"{type_counts['meal_event']} meal shares")
    if type_counts['service_order'] > 0:
        summary_parts.append(f"{type_counts['service_order']} service appointments")
    
    if summary_parts:
        summary = f"Over the next {days} days, you have: {', '.join(summary_parts)} ({total_servings} total servings)."
    else:
        summary = f"No commitments scheduled for the next {days} days."
    
    return {
        "status": "success",
        "date_range": f"{today} to {end_date}",
        "total_commitments": len(commitments),
        "total_servings": total_servings,
        "breakdown": {
            "client_meal_plans": type_counts['client_meal_plan'],
            "meal_shares": type_counts['meal_event'],
            "service_orders": type_counts['service_order']
        },
        "commitments_by_date": by_date,
        "summary": summary
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION & UI ACTION TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Tab name to display label mapping
TAB_LABELS = {
    "dashboard": "Dashboard",
    "prep": "Prep Planning",
    "profile": "Profile",
    "photos": "Photos",
    "kitchen": "Kitchen",
    "connections": "Connections",
    "clients": "Clients",
    "messages": "Messages",
    "payments": "Payment Links",
    "services": "Services",
    "meal-shares": "Meal Shares",
    "orders": "Orders",
    "meals": "Meals",
}

# Form type to tab mapping
FORM_TAB_MAP = {
    "ingredient": "kitchen",
    "dish": "kitchen",
    "meal": "meals",
    "meal-share": "services",
    "service": "services",
}


def _navigate_to_dashboard_tab(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Navigate the chef to a specific dashboard tab.
    Returns action metadata that the frontend will render as an interactive button.
    """
    tab = args.get("tab", "dashboard")
    reason = args.get("reason", "")
    
    # Validate tab
    if tab not in TAB_LABELS:
        return {
            "status": "error",
            "message": f"Unknown tab: {tab}. Valid tabs: {', '.join(TAB_LABELS.keys())}"
        }
    
    tab_label = TAB_LABELS[tab]
    
    return {
        "status": "success",
        "action_type": "navigate",
        "tab": tab,
        "label": f"Go to {tab_label}",
        "reason": reason,
        "render_as_action": True,  # Flag for response builder to render as clickable action
        "auto_execute": True  # Auto-navigate without requiring button click
    }


def _prefill_form(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Pre-fill a form with suggested values.
    Returns action metadata that the frontend will render as an interactive button.
    """
    form_type = args.get("form_type", "")
    fields = args.get("fields", {})
    reason = args.get("reason", "")
    
    # Validate form type
    if form_type not in FORM_TAB_MAP:
        return {
            "status": "error",
            "message": f"Unknown form type: {form_type}. Valid types: {', '.join(FORM_TAB_MAP.keys())}"
        }
    
    # Get the destination tab
    target_tab = FORM_TAB_MAP[form_type]
    
    # Create a friendly label
    form_labels = {
        "ingredient": "Ingredient",
        "dish": "Dish",
        "meal": "Meal",
        "meal-share": "Meal Share",
        "service": "Service",
    }
    label = f"Create {form_labels.get(form_type, form_type.title())}"
    
    return {
        "status": "success",
        "action_type": "prefill",
        "form_type": form_type,
        "target_tab": target_tab,
        "fields": fields,
        "label": label,
        "reason": reason,
        "render_as_action": True  # Flag for response builder to render as clickable action
    }


def _scaffold_meal(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Generate a meal scaffold with dishes and optionally ingredients.
    Returns the scaffold tree that the frontend will render for preview/editing.
    """
    from meals.scaffold_engine import ScaffoldEngine
    
    meal_name = args.get("meal_name", "")
    meal_description = args.get("meal_description", "")
    meal_type = args.get("meal_type", "Dinner")
    include_dishes = args.get("include_dishes", True)
    include_ingredients = args.get("include_ingredients", False)
    
    if not meal_name:
        return {
            "status": "error",
            "message": "meal_name is required"
        }
    
    try:
        engine = ScaffoldEngine(chef)
        scaffold = engine.generate_scaffold(
            hint=meal_name,
            include_dishes=include_dishes,
            include_ingredients=include_ingredients,
            meal_type=meal_type
        )
        
        # If a description was provided, override the AI-generated one
        if meal_description:
            scaffold.data['description'] = meal_description
        
        return {
            "status": "success",
            "action_type": "scaffold",
            "scaffold": scaffold.to_dict(),
            "render_as_scaffold": True,  # Flag for frontend to render scaffold preview
            "summary": {
                "meal": scaffold.data.get('name'),
                "dish_count": len([c for c in scaffold.children if c.status != 'removed']),
                "ingredient_count": sum(
                    len([i for i in d.children if i.status != 'removed'])
                    for d in scaffold.children if d.status != 'removed'
                )
            }
        }
        
    except Exception as e:
        logger.error(f"Scaffold generation failed: {e}")
        return {
            "status": "error",
            "message": f"Failed to generate scaffold: {str(e)}"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NEW TOOL IMPLEMENTATIONS: Search, Analytics, Seasonal, Substitutions, Messaging
# ═══════════════════════════════════════════════════════════════════════════════

def _search_chef_dishes(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Search chef's existing dishes by name, ingredient, or dietary tag.
    """
    from meals.models import Dish, Meal, Ingredient
    from django.db.models import Q
    
    query = args.get("query", "").strip().lower()
    search_type = args.get("search_type", "all")
    limit = min(max(args.get("limit", 10), 1), 25)
    
    if not query:
        return {"status": "error", "message": "Query is required"}
    
    results = []
    
    # Search by dish name
    if search_type in ("name", "all"):
        dishes = Dish.objects.filter(
            chef=chef,
            name__icontains=query
        ).prefetch_related('ingredients')[:limit]
        
        for dish in dishes:
            ingredient_names = [i.name for i in dish.ingredients.all()[:5]]
            results.append({
                "type": "dish",
                "id": dish.id,
                "name": dish.name,
                "featured": dish.featured,
                "ingredients": ingredient_names,
                "match_type": "name"
            })
    
    # Search by ingredient
    if search_type in ("ingredient", "all"):
        # Find dishes that contain an ingredient matching the query
        dishes = Dish.objects.filter(
            chef=chef,
            ingredients__name__icontains=query
        ).distinct().prefetch_related('ingredients')[:limit]
        
        for dish in dishes:
            # Don't add duplicates
            if any(r["id"] == dish.id and r["type"] == "dish" for r in results):
                continue
            ingredient_names = [i.name for i in dish.ingredients.all()[:5]]
            matching_ingredients = [i.name for i in dish.ingredients.all() if query in i.name.lower()]
            results.append({
                "type": "dish",
                "id": dish.id,
                "name": dish.name,
                "featured": dish.featured,
                "ingredients": ingredient_names,
                "matching_ingredients": matching_ingredients,
                "match_type": "ingredient"
            })
    
    # Search by dietary tag (in meals)
    if search_type in ("dietary_tag", "all"):
        meals = Meal.objects.filter(
            chef=chef,
            dietary_preferences__name__icontains=query
        ).distinct().prefetch_related('dietary_preferences', 'dishes')[:limit]
        
        for meal in meals:
            prefs = [p.name for p in meal.dietary_preferences.all()]
            dishes_in_meal = [d.name for d in meal.dishes.all()[:3]]
            results.append({
                "type": "meal",
                "id": meal.id,
                "name": meal.name,
                "dietary_preferences": prefs,
                "dishes": dishes_in_meal,
                "match_type": "dietary_tag"
            })
    
    # Deduplicate and limit
    seen = set()
    unique_results = []
    for r in results:
        key = (r["type"], r["id"])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    unique_results = unique_results[:limit]
    
    return {
        "status": "success",
        "query": query,
        "search_type": search_type,
        "total_results": len(unique_results),
        "results": unique_results,
        "tip": "Use these results to reference existing dishes or identify gaps in your menu."
    }


def _suggest_ingredient_substitution(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Suggest safe ingredient substitutes for allergens or dietary restrictions.
    """
    ingredient = args.get("ingredient", "").strip().lower()
    reason = args.get("reason", "other")
    recipe_context = args.get("recipe_context", "")
    
    if not ingredient:
        return {"status": "error", "message": "Ingredient is required"}
    
    # Comprehensive substitution database
    substitutions = {
        # Dairy substitutions
        "milk": {
            "allergy": ["oat milk", "almond milk", "coconut milk", "soy milk", "rice milk"],
            "vegan": ["oat milk", "almond milk", "coconut milk", "soy milk", "cashew milk"],
            "dairy-free": ["oat milk", "almond milk", "coconut milk", "soy milk"],
        },
        "butter": {
            "allergy": ["coconut oil", "olive oil", "vegan butter", "avocado"],
            "vegan": ["coconut oil", "vegan butter", "olive oil", "nut butters"],
            "dairy-free": ["coconut oil", "olive oil", "vegan butter"],
        },
        "cream": {
            "allergy": ["coconut cream", "cashew cream", "oat cream"],
            "vegan": ["coconut cream", "cashew cream", "silken tofu blended"],
            "dairy-free": ["coconut cream", "oat cream"],
        },
        "cheese": {
            "allergy": ["nutritional yeast", "vegan cheese", "cashew cheese"],
            "vegan": ["nutritional yeast", "vegan cheese", "cashew cheese", "tofu ricotta"],
            "dairy-free": ["vegan cheese", "nutritional yeast"],
        },
        "yogurt": {
            "allergy": ["coconut yogurt", "almond yogurt", "soy yogurt"],
            "vegan": ["coconut yogurt", "almond yogurt", "cashew yogurt"],
            "dairy-free": ["coconut yogurt", "oat yogurt"],
        },
        
        # Egg substitutions
        "eggs": {
            "allergy": ["flax egg (1 tbsp flax + 3 tbsp water)", "chia egg", "applesauce", "mashed banana"],
            "vegan": ["flax egg", "chia egg", "aquafaba", "commercial egg replacer", "silken tofu"],
            "vegetarian": ["eggs are vegetarian - no substitution needed"],
        },
        "egg": {
            "allergy": ["flax egg (1 tbsp flax + 3 tbsp water)", "chia egg", "applesauce", "mashed banana"],
            "vegan": ["flax egg", "chia egg", "aquafaba", "commercial egg replacer"],
        },
        
        # Nut substitutions
        "peanuts": {
            "allergy": ["sunflower seed butter", "soy nut butter", "tahini", "pumpkin seed butter"],
        },
        "peanut butter": {
            "allergy": ["sunflower seed butter", "soy nut butter", "tahini", "pumpkin seed butter"],
        },
        "almonds": {
            "allergy": ["sunflower seeds", "pumpkin seeds", "oats", "coconut flakes"],
        },
        "tree nuts": {
            "allergy": ["seeds (sunflower, pumpkin)", "coconut", "oats", "crispy rice"],
        },
        "walnuts": {
            "allergy": ["sunflower seeds", "pumpkin seeds", "hemp seeds"],
        },
        
        # Gluten substitutions
        "wheat flour": {
            "allergy": ["almond flour", "coconut flour", "rice flour", "oat flour (certified GF)"],
            "gluten-free": ["almond flour", "coconut flour", "rice flour", "tapioca flour", "1-to-1 GF flour blend"],
        },
        "flour": {
            "gluten-free": ["almond flour", "coconut flour", "rice flour", "1-to-1 GF flour blend"],
            "allergy": ["rice flour", "oat flour (certified GF)", "cassava flour"],
        },
        "bread": {
            "gluten-free": ["gluten-free bread", "lettuce wraps", "rice paper", "corn tortillas"],
        },
        "pasta": {
            "gluten-free": ["rice pasta", "quinoa pasta", "chickpea pasta", "zucchini noodles"],
        },
        "breadcrumbs": {
            "gluten-free": ["crushed rice crackers", "almond meal", "GF panko", "crushed GF cereal"],
        },
        
        # Soy substitutions
        "soy sauce": {
            "allergy": ["coconut aminos", "liquid aminos", "tamari (if just gluten-free)"],
            "gluten-free": ["tamari (GF certified)", "coconut aminos"],
        },
        "tofu": {
            "allergy": ["chickpeas", "white beans", "seitan (if not gluten-free)", "jackfruit"],
        },
        
        # Meat/protein substitutions
        "chicken": {
            "vegetarian": ["tofu", "seitan", "tempeh", "jackfruit", "cauliflower"],
            "vegan": ["tofu", "seitan", "tempeh", "jackfruit", "chickpeas"],
        },
        "beef": {
            "vegetarian": ["portobello mushrooms", "seitan", "tempeh", "lentils"],
            "vegan": ["portobello mushrooms", "seitan", "lentils", "black beans"],
        },
        "pork": {
            "halal": ["chicken", "turkey", "lamb", "beef"],
            "kosher": ["chicken", "turkey", "beef"],
            "vegetarian": ["jackfruit", "seitan", "tempeh"],
        },
        "bacon": {
            "halal": ["turkey bacon", "beef bacon"],
            "vegetarian": ["tempeh bacon", "coconut bacon", "mushroom bacon"],
            "vegan": ["tempeh bacon", "coconut bacon", "smoked paprika + mushrooms"],
        },
        
        # Shellfish
        "shrimp": {
            "allergy": ["hearts of palm", "king oyster mushrooms", "white fish"],
        },
        "crab": {
            "allergy": ["hearts of palm", "jackfruit", "artichoke hearts"],
        },
        
        # Other common substitutions
        "sugar": {
            "low-sodium": ["sugar is fine for low-sodium"],
            "other": ["honey", "maple syrup", "coconut sugar", "stevia", "monk fruit"],
        },
        "salt": {
            "low-sodium": ["herbs", "lemon juice", "vinegar", "garlic", "spices", "salt-free seasoning blends"],
        },
    }
    
    # Look up substitutions
    subs = substitutions.get(ingredient, {})
    reason_subs = subs.get(reason, subs.get("allergy", subs.get("other", [])))
    
    # If no specific substitution found, provide general guidance
    if not reason_subs and not subs:
        return {
            "status": "success",
            "ingredient": ingredient,
            "reason": reason,
            "substitutions": [],
            "general_tips": [
                f"No specific substitution database entry for '{ingredient}'.",
                "Consider the function of the ingredient (binding, leavening, flavor, texture).",
                "Search online for specific recipe-based alternatives.",
                "Consult with the customer about their preferred alternatives."
            ],
            "recipe_context": recipe_context
        }
    
    # Build response with context-aware tips
    tips = []
    if "baking" in recipe_context.lower() or "cake" in recipe_context.lower():
        tips.append("For baking, measure substitutions carefully as ratios matter.")
    if "sauce" in recipe_context.lower():
        tips.append("For sauces, start with less substitute and adjust to taste.")
    
    return {
        "status": "success",
        "ingredient": ingredient,
        "reason": reason,
        "substitutions": reason_subs if isinstance(reason_subs, list) else list(subs.values())[0] if subs else [],
        "all_options": {k: v for k, v in subs.items()} if subs else {},
        "recipe_context": recipe_context,
        "tips": tips,
        "note": "Always verify allergen safety with specific product labels."
    }


def _get_chef_analytics(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Get analytics and performance metrics for the chef's business.
    """
    from meals.models import ChefMealOrder, ChefMealEvent, Meal
    from chef_services.models import ChefServiceOrder
    from django.db.models import Sum, Count, Avg, F
    from datetime import date, timedelta
    from decimal import Decimal
    
    time_period = args.get("time_period", "month")
    requested_metrics = args.get("metrics", ["revenue", "orders", "popular_dishes", "client_retention", "meal_shares", "services"])
    
    # Calculate date range
    today = date.today()
    if time_period == "week":
        start_date = today - timedelta(days=7)
    elif time_period == "month":
        start_date = today - timedelta(days=30)
    elif time_period == "quarter":
        start_date = today - timedelta(days=90)
    elif time_period == "year":
        start_date = today - timedelta(days=365)
    else:  # all_time
        start_date = None
    
    analytics = {
        "time_period": time_period,
        "date_range": {
            "start": start_date.isoformat() if start_date else "all time",
            "end": today.isoformat()
        }
    }
    
    # Revenue and orders from meal events
    if "revenue" in requested_metrics or "orders" in requested_metrics:
        meal_order_filter = {"meal_event__chef": chef, "status": "confirmed"}
        if start_date:
            meal_order_filter["created_at__date__gte"] = start_date
        
        meal_orders = ChefMealOrder.objects.filter(**meal_order_filter)
        meal_order_count = meal_orders.count()
        meal_revenue = meal_orders.aggregate(total=Sum('price_paid'))['total'] or Decimal('0')
        
        # Revenue from services
        service_filter = {"chef": chef, "status": "completed"}
        if start_date:
            service_filter["created_at__date__gte"] = start_date
        
        service_orders = ChefServiceOrder.objects.filter(**service_filter)
        service_count = service_orders.count()
        service_revenue = service_orders.aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        
        if "revenue" in requested_metrics:
            analytics["revenue"] = {
                "total": float(meal_revenue + service_revenue),
                "from_meal_shares": float(meal_revenue),
                "from_services": float(service_revenue),
                "currency": "USD"
            }
        
        if "orders" in requested_metrics:
            analytics["orders"] = {
                "total": meal_order_count + service_count,
                "meal_share_orders": meal_order_count,
                "service_orders": service_count
            }
    
    # Popular dishes
    if "popular_dishes" in requested_metrics:
        popular_filter = {"events__orders__status": "confirmed", "chef": chef}
        if start_date:
            popular_filter["events__orders__created_at__date__gte"] = start_date
        
        popular_meals = Meal.objects.filter(**popular_filter).annotate(
            order_count=Count('events__orders')
        ).order_by('-order_count')[:5]
        
        analytics["popular_dishes"] = [
            {"name": m.name, "orders": m.order_count}
            for m in popular_meals
        ]
    
    # Client retention
    if "client_retention" in requested_metrics:
        # Count unique customers with multiple orders
        meal_customers = ChefMealOrder.objects.filter(
            meal_event__chef=chef,
            status="confirmed"
        ).values('customer').annotate(
            order_count=Count('id')
        )
        
        total_customers = meal_customers.count()
        repeat_customers = meal_customers.filter(order_count__gt=1).count()
        
        analytics["client_retention"] = {
            "total_customers": total_customers,
            "repeat_customers": repeat_customers,
            "retention_rate": f"{(repeat_customers / total_customers * 100):.1f}%" if total_customers > 0 else "N/A"
        }
    
    # Meal shares stats
    if "meal_shares" in requested_metrics:
        event_filter = {"chef": chef}
        if start_date:
            event_filter["event_date__gte"] = start_date
        
        events = ChefMealEvent.objects.filter(**event_filter)
        analytics["meal_shares"] = {
            "total_events": events.count(),
            "completed": events.filter(status="completed").count(),
            "cancelled": events.filter(status="cancelled").count(),
            "avg_orders_per_event": events.aggregate(avg=Avg('orders_count'))['avg'] or 0
        }
    
    # Services stats
    if "services" in requested_metrics:
        service_filter = {"chef": chef}
        if start_date:
            service_filter["created_at__date__gte"] = start_date
        
        services = ChefServiceOrder.objects.filter(**service_filter)
        analytics["services"] = {
            "total": services.count(),
            "completed": services.filter(status="completed").count(),
            "pending": services.filter(status__in=["draft", "awaiting_payment", "confirmed"]).count()
        }
    
    return {
        "status": "success",
        **analytics
    }


def _get_seasonal_ingredients(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Get a list of ingredients that are currently in season.
    """
    from datetime import date
    
    month = args.get("month")
    if month is None:
        month = date.today().month
    
    category = args.get("category", "all")
    region = args.get("region", "general")
    
    # Validate month
    if not 1 <= month <= 12:
        return {"status": "error", "message": "Month must be between 1 and 12"}
    
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    
    # Comprehensive seasonal ingredient database (general US)
    seasonal_data = {
        # Winter (Dec, Jan, Feb)
        1: {  # January
            "vegetables": ["brussels sprouts", "cabbage", "kale", "leeks", "parsnips", "turnips", "winter squash", "beets", "carrots", "celery root"],
            "fruits": ["citrus (oranges, grapefruits, lemons)", "pomegranates", "pears", "apples", "kiwi"],
            "proteins": ["oysters", "mussels", "duck", "game birds"],
            "herbs": ["rosemary", "thyme", "sage", "bay leaves"],
        },
        2: {  # February
            "vegetables": ["brussels sprouts", "cabbage", "kale", "leeks", "parsnips", "rutabaga", "winter squash", "potatoes"],
            "fruits": ["citrus", "apples", "pears", "blood oranges"],
            "proteins": ["oysters", "clams", "halibut"],
            "herbs": ["rosemary", "thyme", "sage"],
        },
        # Spring (Mar, Apr, May)
        3: {  # March
            "vegetables": ["artichokes", "asparagus", "broccoli", "green onions", "lettuce", "spinach", "peas", "radishes"],
            "fruits": ["citrus", "strawberries (early)"],
            "proteins": ["lamb", "salmon (wild)", "trout"],
            "herbs": ["chives", "parsley", "mint", "dill"],
        },
        4: {  # April
            "vegetables": ["artichokes", "asparagus", "fava beans", "peas", "spinach", "spring onions", "radishes", "ramps", "morels"],
            "fruits": ["strawberries", "rhubarb"],
            "proteins": ["lamb", "salmon", "soft-shell crab"],
            "herbs": ["chives", "parsley", "mint", "tarragon"],
        },
        5: {  # May
            "vegetables": ["asparagus", "fava beans", "peas", "artichokes", "new potatoes", "zucchini", "green beans"],
            "fruits": ["strawberries", "cherries (early)", "apricots"],
            "proteins": ["salmon", "halibut", "soft-shell crab"],
            "herbs": ["basil", "cilantro", "mint", "chives"],
        },
        # Summer (Jun, Jul, Aug)
        6: {  # June
            "vegetables": ["corn", "cucumbers", "green beans", "peppers", "summer squash", "zucchini", "tomatoes", "eggplant"],
            "fruits": ["cherries", "berries (all)", "peaches", "plums", "apricots", "melons"],
            "proteins": ["salmon", "halibut", "swordfish", "tuna"],
            "herbs": ["basil", "cilantro", "mint", "oregano", "dill"],
        },
        7: {  # July
            "vegetables": ["corn", "cucumbers", "eggplant", "peppers", "tomatoes", "zucchini", "okra", "green beans"],
            "fruits": ["berries", "peaches", "nectarines", "plums", "watermelon", "cantaloupe", "figs"],
            "proteins": ["swordfish", "tuna", "lobster", "crab"],
            "herbs": ["basil", "cilantro", "mint", "oregano"],
        },
        8: {  # August
            "vegetables": ["corn", "cucumbers", "eggplant", "peppers", "tomatoes", "zucchini", "summer squash"],
            "fruits": ["berries", "peaches", "nectarines", "plums", "grapes", "melons", "figs"],
            "proteins": ["lobster", "crab", "tuna"],
            "herbs": ["basil", "cilantro", "oregano"],
        },
        # Fall (Sep, Oct, Nov)
        9: {  # September
            "vegetables": ["butternut squash", "eggplant", "peppers", "tomatoes", "corn (late)", "broccoli", "cauliflower"],
            "fruits": ["apples", "grapes", "pears", "figs", "plums"],
            "proteins": ["salmon", "halibut", "duck"],
            "herbs": ["sage", "rosemary", "thyme"],
        },
        10: {  # October
            "vegetables": ["butternut squash", "pumpkin", "brussels sprouts", "cauliflower", "kale", "sweet potatoes", "parsnips"],
            "fruits": ["apples", "pears", "cranberries", "pomegranates", "persimmons"],
            "proteins": ["duck", "game birds", "venison"],
            "herbs": ["sage", "rosemary", "thyme"],
        },
        11: {  # November
            "vegetables": ["butternut squash", "pumpkin", "brussels sprouts", "kale", "turnips", "parsnips", "sweet potatoes", "celery root"],
            "fruits": ["apples", "pears", "cranberries", "pomegranates", "citrus (beginning)"],
            "proteins": ["turkey", "duck", "game birds"],
            "herbs": ["sage", "rosemary", "thyme"],
        },
        12: {  # December
            "vegetables": ["brussels sprouts", "cabbage", "kale", "parsnips", "turnips", "winter squash", "potatoes", "celery root"],
            "fruits": ["citrus", "pomegranates", "pears", "apples", "cranberries"],
            "proteins": ["oysters", "duck", "game birds", "ham"],
            "herbs": ["rosemary", "thyme", "sage", "bay leaves"],
        },
    }
    
    # Get ingredients for the month
    month_data = seasonal_data.get(month, {})
    
    if category == "all":
        result = month_data
    else:
        result = {category: month_data.get(category, [])}
    
    # Flatten for easy reading
    all_ingredients = []
    for cat, items in result.items():
        for item in items:
            all_ingredients.append({"name": item, "category": cat})
    
    return {
        "status": "success",
        "month": month_names[month - 1],
        "month_number": month,
        "region": region,
        "seasonal_ingredients": result,
        "all_ingredients": all_ingredients,
        "total_count": len(all_ingredients),
        "tips": [
            "Seasonal ingredients are typically fresher and more affordable.",
            "Consider building your menu around what's in season for best results.",
            "Local farmers markets are great for finding peak-season produce."
        ]
    }


def _draft_client_message(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Draft a professional message to send to a client.
    Returns the draft for chef review before sending.
    """
    message_type = args.get("message_type", "general")
    key_points = args.get("key_points", [])
    tone = args.get("tone", "friendly")
    
    if not key_points:
        return {"status": "error", "message": "key_points are required"}
    
    # Get client name
    if customer:
        client_name = customer.first_name or customer.username
        client_full = f"{customer.first_name} {customer.last_name}".strip() or customer.username
    elif lead:
        client_name = lead.first_name or "there"
        client_full = f"{lead.first_name} {lead.last_name}".strip()
    else:
        return {"status": "error", "message": "No client context available"}
    
    chef_name = chef.user.first_name or chef.user.username
    
    # Tone adjustments
    greeting = {
        "professional": f"Dear {client_name},",
        "friendly": f"Hi {client_name}!",
        "casual": f"Hey {client_name}!"
    }.get(tone, f"Hi {client_name},")
    
    sign_off = {
        "professional": f"Best regards,\n{chef_name}",
        "friendly": f"Looking forward to cooking for you!\n{chef_name}",
        "casual": f"Cheers,\n{chef_name}"
    }.get(tone, f"Best,\n{chef_name}")
    
    # Build message based on type
    if message_type == "meal_plan_update":
        intro = "I wanted to share some updates about your meal plan."
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = f"{intro}\n\n{points_formatted}\n\nPlease let me know if you have any questions or would like to make any changes."
        
    elif message_type == "order_confirmation":
        intro = "Great news! Your order has been confirmed."
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = f"{intro}\n\n{points_formatted}\n\nI'll be preparing everything fresh for you. Looking forward to it!"
        
    elif message_type == "dietary_question":
        intro = "I wanted to check in about some dietary details to make sure I'm preparing the perfect meals for your family."
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = f"{intro}\n\n{points_formatted}\n\nPlease let me know your preferences, and I'll adjust accordingly."
        
    elif message_type == "schedule_change":
        intro = "I need to let you know about a schedule update."
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = f"{intro}\n\n{points_formatted}\n\nI apologize for any inconvenience and appreciate your understanding."
        
    elif message_type == "thank_you":
        intro = "I just wanted to take a moment to thank you!"
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = f"{intro}\n\n{points_formatted}\n\nIt's truly a pleasure cooking for your family."
        
    elif message_type == "follow_up":
        intro = "I wanted to follow up with you."
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = f"{intro}\n\n{points_formatted}\n\nPlease don't hesitate to reach out if you need anything."
        
    else:  # general
        points_formatted = "\n".join([f"• {point}" for point in key_points])
        body = points_formatted
    
    # Assemble full message
    full_message = f"{greeting}\n\n{body}\n\n{sign_off}"
    
    return {
        "status": "success",
        "message_type": message_type,
        "tone": tone,
        "recipient": client_full,
        "draft": full_message,
        "editable": True,
        "note": "This is a draft for your review. Edit as needed before sending to the client.",
        "render_as_draft": True  # Flag for frontend to show as editable draft
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY SYSTEM TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _save_chef_memory(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Save a learning/pattern/preference to long-term memory.
    
    Generates embedding for semantic search when the memory service is available.
    """
    from customer_dashboard.models import ChefMemory
    
    memory_type = args.get("memory_type", "lesson")
    content = args.get("content", "").strip()
    importance = args.get("importance", 3)
    family_specific = args.get("family_specific", False)
    
    if not content:
        return {"status": "error", "message": "Content is required"}
    
    if len(content) > 1000:
        content = content[:1000]
    
    valid_types = ["pattern", "preference", "lesson", "todo"]
    if memory_type not in valid_types:
        return {"status": "error", "message": f"Invalid memory_type. Must be one of: {valid_types}"}
    
    # Clamp importance
    importance = max(1, min(5, importance))
    
    # Build context metadata
    context = {
        "source": "conversation",
        "created_via": "sous_chef_tool"
    }
    
    # Create memory kwargs
    memory_kwargs = {
        "chef": chef,
        "memory_type": memory_type,
        "content": content,
        "importance": importance,
        "context": context,
    }
    
    # Link to family if specified
    if family_specific:
        if customer:
            memory_kwargs["customer"] = customer
            context["family_type"] = "customer"
            context["family_id"] = customer.id
        elif lead:
            memory_kwargs["lead"] = lead
            context["family_type"] = "lead"
            context["family_id"] = lead.id
    
    # Generate embedding for semantic search
    embedding_generated = False
    try:
        from chefs.services import EmbeddingService
        embedding = EmbeddingService.get_embedding(content)
        if embedding:
            memory_kwargs["embedding"] = embedding
            embedding_generated = True
    except Exception as e:
        logger.debug(f"Embedding generation skipped: {e}")
    
    memory = ChefMemory.objects.create(**memory_kwargs)
    
    type_labels = {
        "pattern": "Pattern",
        "preference": "Preference",
        "lesson": "Lesson",
        "todo": "To-Do"
    }
    
    return {
        "status": "success",
        "message": f"Saved {type_labels[memory_type].lower()} to long-term memory",
        "memory_id": memory.id,
        "memory_type": memory_type,
        "importance": importance,
        "family_specific": family_specific,
        "embedding_generated": embedding_generated,
        "content_preview": content[:100] + "..." if len(content) > 100 else content
    }


def _recall_chef_memories(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Search and recall memories by type or keyword.
    
    Uses hybrid search (vector + full-text) when a keyword is provided,
    falling back to importance-based retrieval when no keyword given.
    """
    from customer_dashboard.models import ChefMemory
    from django.db.models import Q
    
    memory_types = args.get("memory_types", None)
    keyword = args.get("keyword", "")
    include_family = args.get("include_family_memories", True)
    limit = min(max(args.get("limit", 10), 1), 20)
    
    # Determine client filter
    client_filter = None
    lead_filter = None
    if include_family:
        client_filter = customer
        lead_filter = lead
    
    # Try hybrid search if keyword provided
    if keyword:
        try:
            from chefs.models import hybrid_memory_search
            from chefs.services import EmbeddingService
            
            # Generate query embedding for semantic search
            query_embedding = EmbeddingService.get_embedding(keyword)
            
            # Use hybrid search (vector + BM25)
            search_results = hybrid_memory_search(
                chef=chef,
                query=keyword,
                query_embedding=query_embedding,
                memory_types=memory_types,
                client=client_filter,
                lead=lead_filter,
                limit=limit,
                vector_weight=0.6,  # Slightly favor semantic matching
                text_weight=0.4,
                min_score=0.05,  # Lower threshold to be inclusive
            )
            
            # Format results with relevance scores
            results = []
            for memory, score in search_results:
                memory.mark_accessed()
                
                family_info = None
                if memory.customer:
                    family_info = f"{memory.customer.first_name} {memory.customer.last_name}".strip() or memory.customer.username
                elif memory.lead:
                    family_info = f"{memory.lead.first_name} {memory.lead.last_name}".strip()
                
                results.append({
                    "id": memory.id,
                    "type": memory.memory_type,
                    "content": memory.content,
                    "importance": memory.importance,
                    "family": family_info,
                    "created_at": memory.created_at.isoformat(),
                    "access_count": memory.access_count,
                    "relevance_score": round(score, 3),
                })
            
            return {
                "status": "success",
                "search_mode": "hybrid",
                "total_found": len(results),
                "memories": results,
                "filters_applied": {
                    "types": memory_types,
                    "keyword": keyword,
                    "include_family": include_family
                }
            }
            
        except Exception as e:
            # Fall back to simple search if hybrid not available
            logger.warning(f"Hybrid search failed, using fallback: {e}")
    
    # Fallback: simple importance-based retrieval
    queryset = ChefMemory.objects.filter(chef=chef, is_active=True)
    
    # Filter by types
    if memory_types:
        queryset = queryset.filter(memory_type__in=memory_types)
    
    # Filter by keyword (simple contains)
    if keyword:
        queryset = queryset.filter(content__icontains=keyword)
    
    # Handle family-specific memories
    if include_family and (customer or lead):
        if customer:
            queryset = queryset.filter(
                Q(customer__isnull=True, lead__isnull=True) | Q(customer=customer)
            )
        elif lead:
            queryset = queryset.filter(
                Q(customer__isnull=True, lead__isnull=True) | Q(lead=lead)
            )
    else:
        queryset = queryset.filter(customer__isnull=True, lead__isnull=True)
    
    # Order and limit
    memories = queryset.order_by('-importance', '-updated_at')[:limit]
    
    # Mark as accessed
    for memory in memories:
        memory.mark_accessed()
    
    # Format results
    results = []
    for memory in memories:
        family_info = None
        if memory.customer:
            family_info = f"{memory.customer.first_name} {memory.customer.last_name}".strip() or memory.customer.username
        elif memory.lead:
            family_info = f"{memory.lead.first_name} {memory.lead.last_name}".strip()
        
        results.append({
            "id": memory.id,
            "type": memory.memory_type,
            "content": memory.content,
            "importance": memory.importance,
            "family": family_info,
            "created_at": memory.created_at.isoformat(),
            "access_count": memory.access_count
        })
    
    return {
        "status": "success",
        "search_mode": "fallback",
        "total_found": len(results),
        "memories": results,
        "filters_applied": {
            "types": memory_types,
            "keyword": keyword if keyword else None,
            "include_family": include_family
        }
    }


def _update_chef_memory(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Update or delete an existing memory.
    """
    from customer_dashboard.models import ChefMemory
    
    memory_id = args.get("memory_id")
    action = args.get("action", "update")
    new_content = args.get("new_content", "")
    
    if not memory_id:
        return {"status": "error", "message": "memory_id is required"}
    
    try:
        memory = ChefMemory.objects.get(id=memory_id, chef=chef, is_active=True)
    except ChefMemory.DoesNotExist:
        return {"status": "error", "message": f"Memory {memory_id} not found"}
    
    if action == "update":
        if not new_content:
            return {"status": "error", "message": "new_content is required for update action"}
        memory.content = new_content[:1000]
        memory.save(update_fields=['content', 'updated_at'])
        return {
            "status": "success",
            "message": "Memory updated",
            "memory_id": memory.id,
            "new_content": memory.content
        }
    
    elif action == "complete":
        if memory.memory_type != "todo":
            return {"status": "error", "message": "Can only complete 'todo' type memories"}
        memory.is_active = False
        memory.context["completed_at"] = timezone.now().isoformat()
        memory.save(update_fields=['is_active', 'context', 'updated_at'])
        return {
            "status": "success",
            "message": "To-do marked as complete",
            "memory_id": memory.id
        }
    
    elif action == "delete":
        memory.is_active = False
        memory.save(update_fields=['is_active', 'updated_at'])
        return {
            "status": "success",
            "message": "Memory deleted",
            "memory_id": memory.id
        }
    
    return {"status": "error", "message": f"Unknown action: {action}"}


# ═══════════════════════════════════════════════════════════════════════════════
# PROACTIVE INSIGHTS TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_proactive_insights(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Fetch unread proactive insights for the chef.
    """
    from customer_dashboard.models import ChefProactiveInsight
    from django.db.models import Q
    
    insight_types = args.get("insight_types", None)
    limit = min(max(args.get("limit", 5), 1), 15)
    
    now = timezone.now()
    queryset = ChefProactiveInsight.objects.filter(
        chef=chef,
        is_dismissed=False
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    
    if insight_types:
        queryset = queryset.filter(insight_type__in=insight_types)
    
    # Order by priority and recency
    from django.db.models import Case, When, IntegerField
    priority_order = Case(
        When(priority='high', then=1),
        When(priority='medium', then=2),
        When(priority='low', then=3),
        output_field=IntegerField(),
    )
    
    insights = queryset.annotate(
        priority_rank=priority_order
    ).order_by('priority_rank', '-created_at')[:limit]
    
    # Mark as read
    for insight in insights:
        insight.mark_read()
    
    # Format results
    results = []
    for insight in insights:
        family_name = None
        if insight.customer:
            family_name = f"{insight.customer.first_name} {insight.customer.last_name}".strip() or insight.customer.username
        elif insight.lead:
            family_name = f"{insight.lead.first_name} {insight.lead.last_name}".strip()
        
        results.append({
            "id": insight.id,
            "type": insight.insight_type,
            "type_display": insight.get_insight_type_display(),
            "title": insight.title,
            "content": insight.content,
            "priority": insight.priority,
            "family": family_name,
            "created_at": insight.created_at.isoformat(),
            "expires_at": insight.expires_at.isoformat() if insight.expires_at else None,
            "suggested_actions": _get_suggested_actions(insight)
        })
    
    unread_count = ChefProactiveInsight.get_count_for_chef(chef)
    
    return {
        "status": "success",
        "insights": results,
        "total_returned": len(results),
        "unread_remaining": max(0, unread_count - len(results)),
        "tip": "Use act_on_insight to take action or dismiss_insight to hide."
    }


def _get_suggested_actions(insight) -> List[str]:
    """Get suggested actions based on insight type."""
    action_map = {
        'followup_needed': ['draft_message', 'schedule_followup'],
        'batch_opportunity': ['create_prep_plan', 'acknowledge'],
        'seasonal_suggestion': ['create_prep_plan', 'acknowledge'],
        'client_win': ['draft_message', 'acknowledge'],
        'scheduling_tip': ['acknowledge'],
    }
    return action_map.get(insight.insight_type, ['acknowledge'])


def _dismiss_insight(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Dismiss a proactive insight.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insight_id = args.get("insight_id")
    
    if not insight_id:
        return {"status": "error", "message": "insight_id is required"}
    
    try:
        insight = ChefProactiveInsight.objects.get(id=insight_id, chef=chef)
    except ChefProactiveInsight.DoesNotExist:
        return {"status": "error", "message": f"Insight {insight_id} not found"}
    
    insight.dismiss()
    
    return {
        "status": "success",
        "message": "Insight dismissed",
        "insight_id": insight.id
    }


def _act_on_insight(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """
    Take action on a proactive insight.
    """
    from customer_dashboard.models import ChefProactiveInsight
    
    insight_id = args.get("insight_id")
    action = args.get("action", "acknowledge")
    notes = args.get("notes", "")
    
    if not insight_id:
        return {"status": "error", "message": "insight_id is required"}
    
    try:
        insight = ChefProactiveInsight.objects.get(id=insight_id, chef=chef)
    except ChefProactiveInsight.DoesNotExist:
        return {"status": "error", "message": f"Insight {insight_id} not found"}
    
    # Mark as actioned
    insight.mark_actioned(action_taken=f"{action}: {notes}" if notes else action)
    
    # Prepare action-specific response
    result = {
        "status": "success",
        "insight_id": insight.id,
        "action": action,
        "insight_type": insight.insight_type
    }
    
    if action == "draft_message":
        # Return data for drafting a message
        family_name = insight.family_name or "the client"
        result["next_step"] = "draft_client_message"
        result["suggested_key_points"] = [
            f"Following up on: {insight.title}",
            insight.content[:200] if insight.content else ""
        ]
        result["message"] = f"Ready to draft a message to {family_name}. Use draft_client_message tool with these suggested points."
        
    elif action == "create_prep_plan":
        result["next_step"] = "generate_prep_plan"
        result["message"] = "Ready to create a prep plan. Use generate_prep_plan tool."
        
    elif action == "schedule_followup":
        # This could integrate with calendar/CRM in the future
        result["next_step"] = "add_family_note"
        result["message"] = "Consider adding a note to track this follow-up. Use add_family_note tool."
        
    else:  # acknowledge or other
        result["message"] = "Insight acknowledged and marked as handled."

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT LINK TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════


def _preview_payment_link(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Generate a payment link preview card for chef review. No Stripe calls."""
    from chefs.api.payment_links import format_currency, ZERO_DECIMAL_CURRENCIES
    from meals.utils.stripe_utils import (
        get_active_stripe_account,
        get_platform_fee_percentage,
        StripeAccountError,
    )

    if not customer and not lead:
        return {"status": "error", "message": "No client selected. Please select a client first."}

    # Validate Stripe account early
    try:
        get_active_stripe_account(chef)
    except StripeAccountError:
        return {
            "status": "error",
            "message": "Payment links unavailable. Set up Stripe in your profile first.",
        }

    # Parse and validate amount
    amount = args.get("amount")
    if amount is None:
        return {"status": "error", "message": "Amount is required."}
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return {"status": "error", "message": "Amount must be a valid number."}

    currency = (args.get("currency") or getattr(chef, 'default_currency', None) or "usd").lower()

    if currency in ZERO_DECIMAL_CURRENCIES:
        amount_cents = int(amount)
    else:
        amount_cents = int(round(amount * 100))

    min_amount = 1 if currency in ZERO_DECIMAL_CURRENCIES else 50
    if amount_cents < min_amount:
        min_display = format_currency(min_amount, currency)
        return {"status": "error", "message": f"Minimum amount is {min_display}."}

    description = (args.get("description") or "").strip()
    if not description:
        return {"status": "error", "message": "Description is required."}
    if len(description) > 500:
        description = description[:500]

    expires_days = min(max(int(args.get("expires_days", 30)), 1), 90)

    # Recipient info
    if customer:
        recipient_name = customer.get_full_name() or customer.username
        recipient_email = customer.email
        recipient_type = "customer"
    else:
        recipient_name = f"{lead.first_name} {lead.last_name}".strip() or lead.email
        recipient_email = lead.email
        recipient_type = "lead"

    email_warning = None
    if not recipient_email:
        email_warning = "No email address on file. Add an email before sending."
    elif lead and not lead.email_verified:
        email_warning = "Email not yet verified. The client should verify their email before you send."

    # Calculate platform fee
    fee_pct = float(get_platform_fee_percentage())
    fee_cents = int(amount_cents * fee_pct / 100) if fee_pct > 0 else 0
    chef_receives_cents = amount_cents - fee_cents

    from datetime import timedelta
    expires_at = timezone.now() + timedelta(days=expires_days)

    return {
        "status": "success",
        "render_as_payment_preview": True,
        "preview": {
            "recipient_name": recipient_name,
            "recipient_email": recipient_email,
            "recipient_type": recipient_type,
            "amount_cents": amount_cents,
            "amount_display": format_currency(amount_cents, currency),
            "currency": currency.upper(),
            "description": description,
            "expires_days": expires_days,
            "expires_date": expires_at.strftime("%B %d, %Y"),
            "platform_fee_display": format_currency(fee_cents, currency) if fee_cents > 0 else None,
            "chef_receives_display": format_currency(chef_receives_cents, currency),
            "internal_notes": args.get("internal_notes", ""),
            "email_warning": email_warning,
        },
        "note": "Review the details above. Say 'send it' to create and email the payment link, or request changes.",
    }


def _create_and_send_payment_link(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Create a Stripe payment link and send it via email."""
    import stripe
    from django.conf import settings
    from chefs.models import ChefPaymentLink
    from chefs.api.payment_links import (
        format_currency,
        ZERO_DECIMAL_CURRENCIES,
        _create_stripe_payment_link,
        _send_payment_link_email,
        _serialize_payment_link,
    )
    from meals.utils.stripe_utils import (
        get_active_stripe_account,
        StripeAccountError,
    )

    stripe.api_key = settings.STRIPE_SECRET_KEY

    if not customer and not lead:
        return {"status": "error", "message": "No client selected."}

    # Validate Stripe account
    try:
        destination_account_id, _ = get_active_stripe_account(chef)
    except StripeAccountError as exc:
        return {"status": "error", "message": str(exc)}

    # Parse amount
    amount = args.get("amount")
    if amount is None:
        return {"status": "error", "message": "Amount is required."}
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return {"status": "error", "message": "Amount must be a valid number."}

    currency = (args.get("currency") or getattr(chef, 'default_currency', None) or "usd").lower()

    if currency in ZERO_DECIMAL_CURRENCIES:
        amount_cents = int(amount)
    else:
        amount_cents = int(round(amount * 100))

    min_amount = 1 if currency in ZERO_DECIMAL_CURRENCIES else 50
    if amount_cents < min_amount:
        min_display = format_currency(min_amount, currency)
        return {"status": "error", "message": f"Minimum amount is {min_display}."}

    description = (args.get("description") or "").strip()
    if not description:
        return {"status": "error", "message": "Description is required."}
    if len(description) > 500:
        description = description[:500]

    expires_days = min(max(int(args.get("expires_days", 30)), 1), 90)

    # Validate recipient email
    if customer:
        recipient_email = customer.email
    elif lead:
        recipient_email = lead.email
        if not lead.email_verified:
            return {"status": "error", "message": "Cannot send: email not verified for this contact."}
    else:
        recipient_email = None

    if not recipient_email:
        return {"status": "error", "message": "No email address on file for this client. Add an email first."}

    # Validate customer connection
    if customer:
        from chef_services.models import ChefCustomerConnection
        if not ChefCustomerConnection.objects.filter(
            chef=chef, customer=customer, status='accepted'
        ).exists():
            return {"status": "error", "message": "No active connection with this customer."}

    expires_at = timezone.now() + timedelta(days=expires_days)

    # Create the ChefPaymentLink record
    payment_link = ChefPaymentLink.objects.create(
        chef=chef,
        lead=lead,
        customer=customer,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        internal_notes=args.get("internal_notes") or "",
        expires_at=expires_at,
        status=ChefPaymentLink.Status.DRAFT,
    )

    # Create Stripe payment link
    try:
        stripe_link_data = _create_stripe_payment_link(
            chef=chef,
            payment_link=payment_link,
            destination_account_id=destination_account_id,
        )
        payment_link.stripe_product_id = stripe_link_data['product_id']
        payment_link.stripe_price_id = stripe_link_data['price_id']
        payment_link.stripe_payment_link_id = stripe_link_data['payment_link_id']
        payment_link.stripe_payment_link_url = stripe_link_data['payment_link_url']
        payment_link.status = ChefPaymentLink.Status.PENDING
        payment_link.save()
    except stripe.error.StripeError as se:
        payment_link.delete()
        logger.error(f"Stripe error creating payment link: {se}")
        return {"status": "error", "message": f"Stripe error: {str(se)}"}
    except Exception as e:
        payment_link.delete()
        logger.error(f"Error creating payment link: {e}")
        return {"status": "error", "message": f"Failed to create payment link: {str(e)}"}

    # Send email
    try:
        _send_payment_link_email(payment_link, chef, recipient_email)
        payment_link.record_email_sent(recipient_email)
    except Exception as e:
        logger.error(f"Email send failed for payment link {payment_link.id}: {e}")
        return {
            "status": "partial_success",
            "render_as_payment_confirmation": True,
            "payment_link": _serialize_payment_link(payment_link),
            "warning": "Payment link created but email failed to send. You can resend from the Payments tab.",
        }

    amount_display = format_currency(amount_cents, currency)
    recipient_name = payment_link.get_recipient_name()

    return {
        "status": "success",
        "render_as_payment_confirmation": True,
        "payment_link": _serialize_payment_link(payment_link),
        "summary": f"Payment link for {amount_display} sent to {recipient_name} at {recipient_email}.",
    }


def _check_payment_link_status(
    args: Dict[str, Any],
    chef: Chef,
    customer: Optional[CustomUser],
    lead: Optional[Lead]
) -> Dict[str, Any]:
    """Check payment link status for the current family."""
    from chefs.models import ChefPaymentLink
    from chefs.api.payment_links import format_currency, _serialize_payment_link

    if not customer and not lead:
        return {"status": "error", "message": "No client selected."}

    links = ChefPaymentLink.objects.filter(chef=chef)
    if customer:
        links = links.filter(customer=customer)
    elif lead:
        links = links.filter(lead=lead)

    status_filter = args.get("status_filter")
    if status_filter:
        links = links.filter(status=status_filter)

    # Auto-expire stale pending links
    now = timezone.now()
    links.filter(
        status=ChefPaymentLink.Status.PENDING,
        expires_at__lt=now
    ).update(status=ChefPaymentLink.Status.EXPIRED)

    limit = min(max(args.get("limit", 5), 1), 10)
    links = links.order_by('-created_at')[:limit]

    results = [_serialize_payment_link(link) for link in links]

    if not results:
        return {
            "status": "success",
            "payment_links": [],
            "message": "No payment links found for this client.",
        }

    return {
        "status": "success",
        "payment_links": results,
        "total_found": len(results),
    }
