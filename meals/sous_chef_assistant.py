# meals/sous_chef_assistant.py
"""
Sous Chef Assistant - Family-focused AI assistant for chefs.

This assistant helps chefs make better meal planning and preparation decisions
by providing context about specific families they serve. Each conversation is
scoped to a single family (either a platform customer or CRM lead).
"""

import json
import logging
import traceback
import time
import os
from typing import Dict, Any, List, Generator, Optional, Union, Literal
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURED OUTPUT SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

class TextBlock(BaseModel):
    """A paragraph of text content."""
    type: Literal["text"] = "text"
    content: str = Field(description="The text content of this block")


class TableBlock(BaseModel):
    """A table with headers and rows."""
    type: Literal["table"] = "table"
    headers: List[str] = Field(description="Column headers for the table")
    rows: List[List[str]] = Field(description="Table rows, each row is a list of cell values")


class ListBlock(BaseModel):
    """A bulleted or numbered list."""
    type: Literal["list"] = "list"
    items: List[str] = Field(description="List items")
    ordered: bool = Field(default=False, description="True for numbered list, False for bulleted")


class ActionBlock(BaseModel):
    """An interactive action the chef can execute (navigation or form prefill)."""
    type: Literal["action"] = "action"
    action_type: str = Field(description="Type of action: 'navigate' or 'prefill'")
    label: str = Field(description="Button label to display")
    payload: Dict[str, Any] = Field(description="Action-specific data (tab for navigate, form_type+fields for prefill)")
    reason: str = Field(default="", description="Brief explanation of why this action is suggested")


class SousChefResponse(BaseModel):
    """Structured response from Sous Chef containing content blocks."""
    blocks: List[Union[TextBlock, TableBlock, ListBlock, ActionBlock]] = Field(
        description="Array of content blocks that make up the response"
    )

try:
    from groq import Groq
except Exception:
    Groq = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from customer_dashboard.models import SousChefThread, SousChefMessage
from chefs.models import Chef
from custom_auth.models import CustomUser
from crm.models import Lead
from shared.utils import generate_family_context_for_chef, _get_language_name
from utils.model_selection import choose_model
from utils.groq_rate_limit import groq_call_with_retry

logger = logging.getLogger(__name__)

# Model configuration - use Groq models from settings
def _get_groq_model():
    return getattr(settings, 'GROQ_MODEL', None) or os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')

MODEL_PRIMARY = _get_groq_model()
MODEL_FALLBACK = "llama-3.3-70b-versatile"


# ═══════════════════════════════════════════════════════════════════════════════
# SOUS CHEF SYSTEM PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════════
SOUS_CHEF_PROMPT_TEMPLATE = """
<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!--                    S O U S   C H E F   A S S I S T A N T                    -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<PromptTemplate id="sous_chef" version="2025-12-03">

  <!-- ───── 1. IDENTITY ───── -->
  <Identity>
    <Role>Sous Chef — Your personal AI kitchen assistant for meal planning</Role>
    <Persona traits="knowledgeable, precise, supportive, safety-conscious"/>
    <Chef name="{chef_name}" />
  </Identity>

  <!-- ───── 2. CURRENT FAMILY CONTEXT ───── -->
  <FamilyContext>
{family_context}
  </FamilyContext>

  <!-- ───── 3. MISSION ───── -->
  <Mission>
    <Primary>
      Help {chef_name} plan and prepare meals for this family by:
      • Suggesting menu ideas that comply with ALL household dietary restrictions
      • Flagging potential allergen conflicts before they become problems
      • Scaling recipes appropriately for the household size
      • Recalling what has worked well in previous orders
    </Primary>
    <Secondary>
      • Help document important notes about family preferences
      • Suggest ways to delight this family based on their history
      • Optimize prep efficiency when planning multiple dishes
    </Secondary>
    <Critical>
      ⚠️ NEVER suggest ingredients that conflict with ANY household member's allergies.
      When in doubt, ask for clarification rather than risk an allergic reaction.
    </Critical>
  </Mission>

  <!-- ───── 4. CAPABILITIES (TOOLS) ───── -->
  <Capabilities>
    You have access to the following tools to help the chef:
{all_tools}
  </Capabilities>

  <!-- ───── 5. OPERATING INSTRUCTIONS ───── -->
  <OperatingInstructions>

    <!-- 5-A. SAFETY FIRST -->
    <AllergyProtocol>
      • Before suggesting ANY recipe or ingredient, mentally check against the 
        family's allergy list in the context above.
      • If a recipe contains a potential allergen, explicitly call it out.
      • Offer safe substitutions when possible.
      • When scaling recipes, verify that substitutions don't introduce new allergens.
    </AllergyProtocol>

    <!-- 5-B. DIETARY COMPLIANCE -->
    <DietaryCompliance>
      • A dish is only compliant if it works for ALL household members.
      • When members have different restrictions, find meals that satisfy everyone.
      • Clearly indicate which restrictions a suggested meal satisfies.
    </DietaryCompliance>

    <!-- 5-C. CONTEXTUAL AWARENESS -->
    <UseContext>
      • Reference the family's order history when suggesting dishes.
      • Note any patterns (e.g., "They usually order your meal prep service").
      • If notes mention preferences, incorporate them in suggestions.
    </UseContext>

    <!-- 5-D. OUTPUT FORMAT -->
    <Format>
      <Markdown>
        Render replies in **GitHub-Flavored Markdown (GFM)**.
        Use headings, lists, and tables where helpful.
      </Markdown>
      <Concise>
        Keep responses focused and actionable.
        Chefs are busy — prioritize clarity over verbosity.
      </Concise>
      <Tables>
        For menu suggestions, use tables:
        `| Day | Meal | Compliant For | Notes |`
      </Tables>
    </Format>

    <!-- 5-E. PROFESSIONAL BOUNDARIES -->
    <Scope>
      • Focus on culinary and meal planning topics.
      • Do not provide medical advice — dietary restrictions are about food, not treatment.
      • Politely redirect off-topic questions back to meal planning.
    </Scope>

    <!-- 5-F. CHEF HUB PLATFORM KNOWLEDGE -->
    <ChefHubReference>
      You can help {chef_name} navigate Chef Hub features:
      
      | Feature | Purpose | Sidebar Location |
      |---------|---------|------------------|
      | Profile | Bio, photos, service areas, Calendly | Profile |
      | Photos | Upload gallery images | Photos |
      | Kitchen | Manage ingredients, dishes, meals | Kitchen |
      | Services | Create tiered pricing offerings and meal shares | Services |
      | Meal Shares | Schedule shared meals for multiple customers | Services > Meal Shares |
      | Clients | Manage customers, households, and connection requests (accept/decline/end) | Clients |
      | Payment Links | Send Stripe payment requests | Payment Links |
      | Prep Planning | Generate shopping lists | Prep Planning |
      | Break Mode | Temporarily pause operations | Dashboard toggle |
      
      For detailed step-by-step guidance on any feature, use the `lookup_chef_hub_help` tool to retrieve accurate documentation.
    </ChefHubReference>

    <!-- 5-G. NAVIGATION ASSISTANCE -->
    <NavigationGuidance>
      You can help {chef_name} navigate the Chef Hub dashboard and create items:
      
      • When the chef asks "how do I..." or "where can I..." questions about platform features,
        offer to navigate them to the right tab using `navigate_to_dashboard_tab`
      • When helping create new items (dishes, meals, meal shares, services, ingredients),
        use `prefill_form` to pre-fill the form with suggested values
      • Always explain WHY you're suggesting navigation in the reason field
      • The chef will see a clickable button — they control when to navigate
      • After calling a navigation/prefill tool, provide context about what they'll find there
      
      Navigation Examples:
      - "Help me add a new dish" → Use prefill_form with form_type="dish"
      - "How do I set up my prices?" → Use navigate_to_dashboard_tab with tab="services"
      - "Take me to my meal shares" → Use navigate_to_dashboard_tab with tab="services" and sub_tab="meal-shares"
    </NavigationGuidance>

  </OperatingInstructions>
</PromptTemplate>
"""


def _safe_json_dumps(obj) -> str:
    """Safely serialize objects to JSON with fallback for special types."""
    def _default(o):
        if isinstance(o, Decimal):
            return float(o)
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=_default)


class SousChefAssistant:
    """
    AI assistant for chefs to help with meal planning and platform guidance.
    
    .. deprecated::
        Use `chefs.services.sous_chef.get_sous_chef_service()` instead.
        This class will be removed in a future version.
    
    Can operate in two modes:
    1. Family mode: Scoped to a specific chef + family combination with full
       context about the family's dietary needs, household composition, and order history.
    2. General mode: Chef-only, for SOP questions, prep planning, and general guidance
       without a specific family context.
    """

    def __init__(
        self,
        chef_id: int,
        family_id: int = None,
        family_type: str = None  # 'customer' or 'lead', required if family_id provided
    ):
        """
        Initialize a Sous Chef assistant for a chef, optionally with a family context.
        
        Args:
            chef_id: The ID of the Chef using the assistant
            family_id: Optional - The ID of the family (CustomUser or Lead)
            family_type: Optional - Either 'customer' or 'lead' (required if family_id provided)
        
        .. deprecated::
            Use `chefs.services.sous_chef.get_sous_chef_service()` instead.
        """
        import warnings
        warnings.warn(
            "SousChefAssistant is deprecated. Use chefs.services.sous_chef.get_sous_chef_service() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.chef_id = chef_id
        self.family_id = family_id
        self.family_type = family_type
        
        # Initialize Groq client for AI inference
        groq_key = getattr(settings, 'GROQ_API_KEY', None) or os.getenv('GROQ_API_KEY')
        if not groq_key or Groq is None:
            raise ValueError("Groq client not available - GROQ_API_KEY must be set")
        self.groq = Groq(api_key=groq_key)
        # Alias for backward compatibility
        self.client = self.groq
        
        # Initialize OpenAI client for structured outputs (Groq doesn't support beta.parse)
        openai_key = getattr(settings, 'OPENAI_KEY', None) or os.getenv('OPENAI_KEY')
        if openai_key and OpenAI is not None:
            self.openai_client = OpenAI(api_key=openai_key)
        else:
            self.openai_client = None
            logger.warning("OpenAI client not available - structured outputs will use fallback")
        
        # Load chef
        self.chef = Chef.objects.select_related('user').get(id=chef_id)
        self.customer = None
        self.lead = None
        
        # Load family if provided
        if family_id is not None:
            if family_type == 'customer':
                self.customer = CustomUser.objects.get(id=family_id)
            elif family_type == 'lead':
                self.lead = Lead.objects.get(id=family_id)
            else:
                raise ValueError(f"Invalid family_type: {family_type}. Must be 'customer' or 'lead' when family_id is provided.")
        
        # Track if we're in family mode or general mode
        self.has_family_context = self.customer is not None or self.lead is not None
        
        # Generate family context (will be minimal if no family selected)
        if self.has_family_context:
            self.family_context = generate_family_context_for_chef(
                chef=self.chef,
                customer=self.customer,
                lead=self.lead
            )
        else:
            self.family_context = "No family selected. Operating in general assistant mode."
        
        # Load chef workspace (personality + rules) - OpenClaw pattern
        self.workspace = self._load_workspace()
        
        # Load client context if family selected
        self.client_context = self._load_client_context() if self.has_family_context else None
        
        # Build system instructions
        self.instructions = self._build_instructions()
        
        # Debug mode
        try:
            self._stream_debug = os.getenv('ASSISTANT_STREAM_DEBUG', '').lower() in ('1', 'true', 'yes', 'on') or getattr(settings, 'DEBUG', False)
        except Exception:
            self._stream_debug = False

    def _dbg(self, msg: str):
        """Debug logging helper."""
        if getattr(self, '_stream_debug', False):
            try:
                logger.info(f"SOUS_CHEF_DEBUG: {msg}")
            except Exception:
                pass

    def _load_workspace(self):
        """
        Load chef's workspace configuration (personality + rules).
        
        Like OpenClaw's SOUL.md + AGENTS.md - defines assistant behavior.
        Returns None if workspace system not available.
        """
        try:
            from chefs.models import ChefWorkspace
            return ChefWorkspace.get_or_create_for_chef(self.chef)
        except Exception as e:
            logger.debug(f"ChefWorkspace not available: {e}")
            return None
    
    def _load_client_context(self):
        """
        Load structured client context (preferences, history).
        
        Like OpenClaw's USER.md - per-client info injected into context.
        Returns None if no family selected or context not available.
        """
        if not self.has_family_context:
            return None
        
        try:
            from chefs.models import ClientContext
            return ClientContext.get_or_create_for_client(
                chef=self.chef,
                client=self.customer,
                lead=self.lead
            )
        except Exception as e:
            logger.debug(f"ClientContext not available: {e}")
            return None

    def _build_instructions(self) -> str:
        """Build the system instructions with chef and optional family context."""
        # Get chef name - prefer nickname from workspace, fall back to user name
        if self.workspace and self.workspace.chef_nickname:
            chef_name = self.workspace.chef_nickname
        else:
            chef_name = self.chef.user.get_full_name() or self.chef.user.username
        
        # Get tool descriptions (filtered based on family context)
        tools = self._get_tools()
        tool_descriptions = []
        for tool in tools:
            func_info = tool.get('function', tool)
            name = func_info.get('name', 'unknown')
            desc = func_info.get('description', 'No description')
            tool_descriptions.append(f"    • {name}: {desc}")
        
        all_tools_str = '\n'.join(tool_descriptions) if tool_descriptions else "    No tools available."
        
        # Build family context section
        if self.has_family_context:
            family_context = self.family_context
        else:
            # General mode - no family selected
            family_context = """    <GeneralMode>
      No family selected. You are operating in General Assistant mode.
      
      In this mode, you can help {chef_name} with:
      • Platform questions and SOPs (how to use Chef Hub features)
      • Prep planning and shopping lists
      • General cooking tips and ingredient information
      • Upcoming commitments and batch cooking suggestions
      
      To get family-specific meal planning help (dietary restrictions, menu suggestions, 
      recipe scaling), ask the chef to select a family from the dropdown.
    </GeneralMode>""".format(chef_name=chef_name)
        
        # Build base instructions from template
        instructions = SOUS_CHEF_PROMPT_TEMPLATE.format(
            chef_name=chef_name,
            family_context=family_context,
            all_tools=all_tools_str
        )
        
        # Add language preference instruction if chef's preferred language is not English
        chef_preferred_language = getattr(self.chef.user, 'preferred_language', 'en') or 'en'
        if chef_preferred_language.lower() not in ('en', 'english'):
            language_name = _get_language_name(chef_preferred_language)
            language_instruction = f"\n<!-- LANGUAGE PREFERENCE -->\n<LanguagePreference>\n  This chef's preferred language is {language_name}. Please respond in {language_name} unless the chef specifically requests English or another language.\n</LanguagePreference>\n"
            instructions += language_instruction
        
        # Inject chef workspace customizations (soul + rules)
        workspace_context = self._build_workspace_context()
        if workspace_context:
            instructions += workspace_context
        
        # Inject structured client context if available
        client_context = self._build_client_context_section()
        if client_context:
            instructions += client_context
        
        # Inject relevant memories from long-term memory system
        memory_context = self._build_memory_context()
        if memory_context:
            instructions += memory_context
        
        return instructions
    
    def _build_workspace_context(self) -> str:
        """
        Build workspace context section from ChefWorkspace.
        
        Injects chef's profile, personality (soul_prompt), and business rules.
        """
        if not self.workspace:
            return ""
        
        sections = []
        
        # Add chef profile info (nickname, specialties, assistant name)
        profile_parts = []
        if self.workspace.chef_nickname:
            profile_parts.append(f"  Address the chef as: {self.workspace.chef_nickname}")
        if self.workspace.chef_specialties:
            specialties = ', '.join(self.workspace.chef_specialties)
            profile_parts.append(f"  Chef specializes in: {specialties}")
        if self.workspace.sous_chef_name:
            profile_parts.append(f"  Your name is: {self.workspace.sous_chef_name} (not 'Sous Chef')")
        
        if profile_parts:
            sections.append(f"""
<!-- CHEF PROFILE -->
<ChefProfile>
{chr(10).join(profile_parts)}
</ChefProfile>""")
        
        # Add soul prompt (personality customization)
        if self.workspace.soul_prompt:
            sections.append(f"""
<!-- CHEF PERSONALITY CUSTOMIZATION -->
<PersonalityOverride>
  The chef has customized your personality and communication style:
  
{self.workspace.soul_prompt}
</PersonalityOverride>""")
        
        # Add business rules
        if self.workspace.business_rules:
            sections.append(f"""
<!-- CHEF BUSINESS RULES -->
<BusinessRules>
  Important constraints and rules from the chef:
  
{self.workspace.business_rules}
</BusinessRules>""")
        
        return "\n".join(sections)
    
    def _build_client_context_section(self) -> str:
        """
        Build structured client context section from ClientContext.
        
        Includes preferences, flavor profile, special occasions, etc.
        """
        if not self.client_context:
            return ""
        
        ctx = self.client_context
        sections = []
        
        # Build structured preferences
        prefs = []
        
        if ctx.cuisine_preferences:
            prefs.append(f"    • Cuisine preferences: {', '.join(ctx.cuisine_preferences)}")
        
        if ctx.flavor_profile:
            flavors = ", ".join(f"{k}: {v}" for k, v in ctx.flavor_profile.items())
            prefs.append(f"    • Flavor profile: {flavors}")
        
        if ctx.cooking_notes:
            prefs.append(f"    • Cooking notes: {ctx.cooking_notes}")
        
        if ctx.communication_style:
            prefs.append(f"    • Communication style: {ctx.communication_style}")
        
        if ctx.special_occasions:
            occasions = []
            for occ in ctx.special_occasions[:5]:  # Limit to 5
                name = occ.get('name', 'Event')
                date = occ.get('date', 'TBD')
                occasions.append(f"{name} ({date})")
            prefs.append(f"    • Special occasions: {', '.join(occasions)}")
        
        if ctx.total_orders > 0:
            prefs.append(f"    • Order history: {ctx.total_orders} orders, ${ctx.total_spent_cents/100:.2f} total")
        
        if ctx.summary:
            prefs.append(f"    • Summary: {ctx.summary}")
        
        if not prefs:
            return ""
        
        client_name = ctx.get_client_name()
        
        return f"""
<!-- STRUCTURED CLIENT PREFERENCES -->
<ClientPreferences client="{client_name}">
  You've learned these preferences about this client:
  
{chr(10).join(prefs)}
</ClientPreferences>"""
    
    def _build_memory_context(self) -> str:
        """
        Load and format relevant memories for injection into system prompt.
        
        Retrieves:
        - Top 5 general chef memories (patterns, preferences, lessons)
        - Top 3 active todos
        - Top 5 family-specific memories if a family is selected
        """
        try:
            from customer_dashboard.models import ChefMemory
        except ImportError:
            return ""
        
        memory_sections = []
        
        # Get general chef memories (not family-specific)
        general_memories = ChefMemory.objects.filter(
            chef=self.chef,
            is_active=True,
            customer__isnull=True,
            lead__isnull=True
        ).exclude(memory_type='todo').order_by('-importance', '-updated_at')[:5]
        
        if general_memories:
            general_items = []
            for m in general_memories:
                type_label = dict(ChefMemory.MEMORY_TYPES).get(m.memory_type, m.memory_type)
                general_items.append(f"    • [{type_label}] {m.content}")
            memory_sections.append(
                "  <GeneralMemories>\n" +
                "    These are patterns, preferences, and lessons you've learned:\n" +
                "\n".join(general_items) +
                "\n  </GeneralMemories>"
            )
        
        # Get active todos
        active_todos = ChefMemory.objects.filter(
            chef=self.chef,
            is_active=True,
            memory_type='todo'
        ).order_by('-importance', '-created_at')[:3]
        
        if active_todos:
            todo_items = []
            for m in active_todos:
                family_note = ""
                if m.customer:
                    family_note = f" (for {m.customer.first_name})"
                elif m.lead:
                    family_note = f" (for {m.lead.first_name})"
                todo_items.append(f"    • {m.content}{family_note}")
            memory_sections.append(
                "  <ActiveTodos>\n" +
                "    Remember these pending items:\n" +
                "\n".join(todo_items) +
                "\n  </ActiveTodos>"
            )
        
        # Get family-specific memories if a family is selected
        if self.has_family_context:
            family_filter = {"chef": self.chef, "is_active": True}
            if self.customer:
                family_filter["customer"] = self.customer
            elif self.lead:
                family_filter["lead"] = self.lead
            
            family_memories = ChefMemory.objects.filter(**family_filter).order_by('-importance', '-updated_at')[:5]
            
            if family_memories:
                family_items = []
                for m in family_memories:
                    type_label = dict(ChefMemory.MEMORY_TYPES).get(m.memory_type, m.memory_type)
                    family_items.append(f"    • [{type_label}] {m.content}")
                
                family_name = "this family"
                if self.customer:
                    family_name = f"{self.customer.first_name}"
                elif self.lead:
                    family_name = f"{self.lead.first_name}"
                
                memory_sections.append(
                    f"  <FamilyMemories>\n" +
                    f"    What you've learned about {family_name}:\n" +
                    "\n".join(family_items) +
                    "\n  </FamilyMemories>"
                )
        
        if not memory_sections:
            return ""
        
        return (
            "\n\n<!-- LONG-TERM MEMORY -->\n"
            "<LongTermMemory>\n" +
            "  Use these memories to provide continuity across conversations.\n" +
            "  Save new learnings with save_chef_memory tool.\n\n" +
            "\n\n".join(memory_sections) +
            "\n</LongTermMemory>\n"
        )

    def _get_tools(self) -> List[Dict[str, Any]]:
        """Get the tools available for sous chef operations.
        
        In general mode (no family), family-specific tools are excluded.
        """
        from .sous_chef_tools import get_sous_chef_tools
        return get_sous_chef_tools(include_family_tools=self.has_family_context)

    def _build_action_block(self, tool_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a tool result with render_as_action=True or render_as_scaffold=True 
        into an ActionBlock or ScaffoldBlock.
        
        Returns None if the tool result is not an action/scaffold type or is invalid.
        """
        action_type = tool_result.get("action_type")
        
        if action_type == "navigate":
            return {
                "type": "action",
                "action_type": "navigate",
                "label": tool_result.get("label", f"Go to {tool_result.get('tab', 'tab')}"),
                "payload": {
                    "tab": tool_result.get("tab")
                },
                "reason": tool_result.get("reason", "")
            }
        elif action_type == "prefill":
            return {
                "type": "action",
                "action_type": "prefill",
                "label": tool_result.get("label", f"Create {tool_result.get('form_type', 'item')}"),
                "payload": {
                    "form_type": tool_result.get("form_type"),
                    "target_tab": tool_result.get("target_tab"),
                    "fields": tool_result.get("fields", {})
                },
                "reason": tool_result.get("reason", "")
            }
        elif action_type == "scaffold":
            # Scaffold block for meal creation with dishes/ingredients
            return {
                "type": "scaffold",
                "scaffold": tool_result.get("scaffold"),
                "summary": tool_result.get("summary", {})
            }
        elif tool_result.get("render_as_payment_preview"):
            return {
                "type": "payment_preview",
                "preview": tool_result.get("preview", {}),
                "note": tool_result.get("note", ""),
            }
        elif tool_result.get("render_as_payment_confirmation"):
            return {
                "type": "payment_confirmation",
                "payment_link": tool_result.get("payment_link", {}),
                "summary": tool_result.get("summary", ""),
                "warning": tool_result.get("warning"),
            }

        return None

    def _get_or_create_thread(self) -> SousChefThread:
        """Get or create a conversation thread for this chef + optional family."""
        filter_kwargs = {
            'chef': self.chef,
            'is_active': True,
        }
        
        if self.has_family_context:
            # Family mode - thread is scoped to a specific family
            if self.family_type == 'customer':
                filter_kwargs['customer'] = self.customer
                filter_kwargs['lead__isnull'] = True
            else:
                filter_kwargs['lead'] = self.lead
                filter_kwargs['customer__isnull'] = True
        else:
            # General mode - chef-only thread (no family)
            filter_kwargs['customer__isnull'] = True
            filter_kwargs['lead__isnull'] = True
        
        try:
            thread = SousChefThread.objects.filter(**filter_kwargs).latest('updated_at')
            return thread
        except SousChefThread.DoesNotExist:
            # Create new thread
            create_kwargs = {
                'chef': self.chef,
                'is_active': True,
            }
            if self.has_family_context:
                if self.family_type == 'customer':
                    create_kwargs['customer'] = self.customer
                else:
                    create_kwargs['lead'] = self.lead
            # For general mode, both customer and lead remain null
            
            return SousChefThread.objects.create(**create_kwargs)

    def _save_message(self, thread: SousChefThread, role: str, content: str, tool_calls: List = None) -> SousChefMessage:
        """Save a message to the thread."""
        return SousChefMessage.objects.create(
            thread=thread,
            role=role,
            content=content,
            tool_calls=tool_calls or []
        )

    def _estimate_tokens(self, text: str) -> int:
        """
        Rough estimation of tokens for a given text.
        Approximates ~4 characters per token for English text.
        """
        return len(text) // 4

    def _truncate_history(self, history: List[Dict], max_messages: int = 30, max_tokens: int = 25000) -> List[Dict]:
        """
        Truncate conversation history if it's too long, keeping the system message 
        and the most recent messages. Uses both message count and token estimation.
        Special handling for function calls to maintain call/output pairs.
        
        Args:
            history: The conversation history list
            max_messages: Maximum number of messages to keep (default 30)
            max_tokens: Maximum estimated tokens to keep (default 25000)
            
        Returns:
            Truncated history list
        """
        if len(history) <= max_messages:
            # Still check token count even if message count is OK
            total_tokens = sum(self._estimate_tokens(str(msg.get("content", ""))) for msg in history)
            if total_tokens <= max_tokens:
                return history
        
        # Group messages to preserve function call pairs
        grouped_items = []
        i = 0
        while i < len(history):
            msg = history[i]
            if msg.get("type") == "function_call" and "call_id" in msg:
                # Look for the matching output
                call_id = msg["call_id"]
                output_found = False
                for j in range(i + 1, len(history)):
                    if (history[j].get("type") == "function_call_output" and 
                        history[j].get("call_id") == call_id):
                        # Group the call and output together
                        grouped_items.append([msg, history[j]])
                        output_found = True
                        # Skip both items in the main loop
                        if j == i + 1:
                            i += 2  # They're consecutive
                        else:
                            # Mark the output as processed
                            history[j] = {"_processed": True}
                            i += 1
                        break
                if not output_found:
                    # Orphaned function call, treat as single item
                    grouped_items.append([msg])
                    i += 1
            elif msg.get("type") == "function_call_output" and not msg.get("_processed"):
                # Orphaned output, treat as single item  
                grouped_items.append([msg])
                i += 1
            elif not msg.get("_processed"):
                # Regular message
                grouped_items.append([msg])
                i += 1
            else:
                i += 1
        
        # Always keep the system message groups (first few items)
        system_groups = []
        non_system_groups = []
        
        for group in grouped_items:
            if any(msg.get("role") == "system" for msg in group):
                system_groups.append(group)
            else:
                non_system_groups.append(group)
        
        # Calculate tokens for system groups
        system_tokens = 0
        for group in system_groups:
            for msg in group:
                system_tokens += self._estimate_tokens(str(msg.get("content", "") or msg.get("output", "") or str(msg)))
        
        # Keep the most recent groups within token and count limits
        available_tokens = max_tokens - system_tokens
        recent_groups = []
        current_tokens = 0
        total_messages = sum(len(group) for group in system_groups)
        
        # Add groups from most recent, checking token count and message count
        for group in reversed(non_system_groups):
            group_tokens = 0
            for msg in group:
                group_tokens += self._estimate_tokens(str(msg.get("content", "") or msg.get("output", "") or str(msg)))
            
            group_message_count = len(group)
            
            if (total_messages + len(recent_groups) * 2 + group_message_count <= max_messages and 
                current_tokens + group_tokens <= available_tokens):
                recent_groups.insert(0, group)  # Insert at beginning to maintain order
                current_tokens += group_tokens
                total_messages += group_message_count
            else:
                break
        
        # Flatten the groups back to a single list
        truncated_history = []
        for group in system_groups + recent_groups:
            truncated_history.extend(group)
        
        if len(history) > len(truncated_history):
            logger.warning(f"Truncated conversation history from {len(history)} to {len(truncated_history)} messages to fit context window (estimated {current_tokens + system_tokens} tokens)")
        
        return truncated_history

    def _generate_conversation_summary(self, messages_to_summarize: List[Dict]) -> str:
        """
        Generate AI summary of older messages using Groq OSS model (free, fast).
        Falls back to OpenAI if Groq is unavailable.
        
        Args:
            messages_to_summarize: List of message dicts to summarize
            
        Returns:
            Summary string
        """
        # Build conversation text from messages
        conversation_text = "\n".join([
            f"{m.get('role', 'unknown')}: {m.get('content', '')[:500]}"
            for m in messages_to_summarize
            if m.get('role') not in ('system',) and m.get('content')
        ])
        
        if not conversation_text.strip():
            return ""
        
        system_prompt = "You are a concise summarizer. Create brief summaries focusing on key decisions and preferences."
        user_prompt = f"""Summarize this chef/Sous Chef conversation about a client family.
Focus on: dietary decisions, menu preferences, important notes, issues raised.
Max 200 words.

Conversation:
{conversation_text}"""
        
        # Use Groq OSS model (free, fast) - already initialized as self.groq in __init__
        if self.groq:
            try:
                raw_create = getattr(getattr(self.groq.chat, 'completions', None), 'with_raw_response', None)
                if raw_create:
                    raw_create = self.groq.chat.completions.with_raw_response.create
                groq_resp = groq_call_with_retry(
                    raw_create_fn=raw_create,
                    create_fn=self.groq.chat.completions.create,
                    desc='sous_chef.conversation_summary',
                    model=getattr(settings, 'GROQ_MODEL', 'openai/gpt-oss-120b'),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    stream=False,
                )
                return groq_resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"Groq summarization failed, falling back to OpenAI: {e}")
        
        # Fallback to OpenAI only if Groq unavailable
        try:
            resp = self.client.chat.completions.create(
                model="gpt-5.1-mini",
                messages=[
                    {"role": "system", "content": system_prompt}, 
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=300
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"Failed to generate conversation summary: {e}")
            return ""

    def _truncate_with_summarization(self, history: List[Dict], thread: SousChefThread, 
                                      max_messages: int = 30, max_tokens: int = 25000) -> List[Dict]:
        """
        Truncate history with intelligent summarization of dropped messages.
        
        Instead of simply dropping old messages, this method:
        1. Identifies messages that would be dropped
        2. Generates an AI summary of those messages
        3. Stores the summary in the thread
        4. Injects the summary into the returned history
        
        Args:
            history: The conversation history list
            thread: The SousChefThread to store the summary
            max_messages: Maximum number of messages to keep (default 30)
            max_tokens: Maximum estimated tokens to keep (default 25000)
            
        Returns:
            Truncated history with summary injection if applicable
        """
        # Check if truncation is needed
        total_tokens = sum(self._estimate_tokens(str(msg.get("content", ""))) for msg in history)
        if len(history) <= max_messages and total_tokens <= max_tokens:
            # Inject existing summary if present (from previous truncations)
            if thread.conversation_summary:
                return self._inject_summary_into_history(history, thread.conversation_summary)
            return history
        
        # Separate system messages and regular messages
        system_msgs = [h for h in history if h.get('role') == 'system']
        other_msgs = [h for h in history if h.get('role') != 'system']
        
        # Calculate how many messages to keep (keeping last 15 regular messages)
        keep_recent = 15
        if len(other_msgs) <= keep_recent:
            # Not enough to truncate meaningfully
            if thread.conversation_summary:
                return self._inject_summary_into_history(history, thread.conversation_summary)
            return history
        
        # Messages to be dropped (excluding recent ones we're keeping)
        messages_to_drop = other_msgs[:-keep_recent]
        messages_to_keep = other_msgs[-keep_recent:]
        
        # Generate summary if we're dropping significant content (at least 6 messages = 3 exchanges)
        if len(messages_to_drop) >= 6:
            try:
                new_summary = self._generate_conversation_summary(messages_to_drop)
                if new_summary:
                    # Combine with existing summary if present
                    if thread.conversation_summary:
                        combined_summary = f"{thread.conversation_summary}\n\n[More recent context]: {new_summary}"
                        # Truncate combined summary if it gets too long
                        if len(combined_summary) > 2000:
                            combined_summary = new_summary  # Use only new summary
                    else:
                        combined_summary = new_summary
                    
                    # Save to thread
                    thread.conversation_summary = combined_summary
                    thread.summary_generated_at = timezone.now()
                    thread.messages_summarized_count += len(messages_to_drop)
                    thread.save(update_fields=['conversation_summary', 'summary_generated_at', 'messages_summarized_count'])
                    
                    logger.info(f"Generated conversation summary for thread {thread.id}, summarized {len(messages_to_drop)} messages")
            except Exception as e:
                logger.error(f"Failed to generate/save conversation summary: {e}")
        
        # Build truncated history: system + recent messages
        truncated_history = system_msgs + messages_to_keep
        
        # Inject summary if available
        if thread.conversation_summary:
            truncated_history = self._inject_summary_into_history(truncated_history, thread.conversation_summary)
        
        logger.info(f"Truncated history from {len(history)} to {len(truncated_history)} messages")
        return truncated_history

    def _inject_summary_into_history(self, history: List[Dict], summary: str) -> List[Dict]:
        """
        Inject conversation summary into history as a system message after the main system prompt.
        
        Args:
            history: The conversation history
            summary: The summary to inject
            
        Returns:
            History with summary injected
        """
        if not summary:
            return history
        
        summary_message = {
            "role": "system",
            "content": f"[Previous conversation summary - use this context to maintain continuity]:\n{summary}"
        }
        
        # Find position after first system message
        result = []
        system_found = False
        summary_injected = False
        
        for msg in history:
            result.append(msg)
            if not summary_injected and msg.get('role') == 'system':
                system_found = True
            elif system_found and not summary_injected:
                # Inject summary right after the first system message
                result.insert(-1, summary_message)
                summary_injected = True
        
        # If no system message found, prepend the summary
        if not summary_injected:
            result.insert(0, summary_message)
        
        return result

    def new_conversation(self) -> Dict[str, Any]:
        """Start a new conversation by deactivating the current thread."""
        # Deactivate existing threads
        filter_kwargs = {
            'chef': self.chef,
            'is_active': True,
        }
        if self.family_type == 'customer':
            filter_kwargs['customer'] = self.customer
        else:
            filter_kwargs['lead'] = self.lead
        
        SousChefThread.objects.filter(**filter_kwargs).update(is_active=False)
        
        # Create new thread
        thread = self._get_or_create_thread()
        
        return {
            'status': 'success',
            'thread_id': thread.id,
            'family_name': thread.family_name
        }

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get the conversation history for the current thread."""
        thread = self._get_or_create_thread()
        messages = thread.messages.all().order_by('created_at')
        
        result = []
        for msg in messages:
            content = msg.content
            is_structured = False
            
            # Check if assistant message is structured JSON
            if msg.role == 'assistant' and content:
                try:
                    parsed = json.loads(content)
                    
                    # Handle array-wrapped responses: [{"blocks": [...]}]
                    if isinstance(parsed, list) and len(parsed) > 0:
                        if isinstance(parsed[0], dict) and 'blocks' in parsed[0]:
                            # Unwrap and re-serialize
                            content = json.dumps(parsed[0])
                            is_structured = True
                        elif isinstance(parsed[0], dict) and parsed[0].get('type'):
                            # Direct blocks array - wrap it
                            content = json.dumps({"blocks": parsed})
                            is_structured = True
                    elif isinstance(parsed, dict) and 'blocks' in parsed:
                        # This is structured content - return as-is
                        is_structured = True
                except (json.JSONDecodeError, TypeError):
                    # Not JSON - this is legacy plain text
                    pass
            
            result.append({
                'role': msg.role,
                'content': content,
                'is_structured': is_structured,
                'created_at': msg.created_at.isoformat(),
            })
        return result

    def send_message(self, message: str) -> Dict[str, Any]:
        """Send a message and get a response (non-streaming)."""
        thread = self._get_or_create_thread()
        
        # Build history from thread
        history = thread.openai_input_history or []
        if not history:
            history.append({"role": "system", "content": self.instructions})
        history.append({"role": "user", "content": message})
        
        # Truncate with summarization if needed (preserves context via AI summary)
        history = self._truncate_with_summarization(history, thread)
        
        # Select model
        model = choose_model(
            user_id=self.chef.user_id,
            is_guest=False,
            question=message
        ) or MODEL_PRIMARY
        
        # Save user message
        self._save_message(thread, 'chef', message)
        
        # Convert history to Groq chat format
        chat_messages = []
        
        # Add system message with instructions
        chat_messages.append({"role": "system", "content": self.instructions})
        
        # Convert history to chat format, filtering out OpenAI-specific formats
        for msg in history:
            role = msg.get("role")
            content = msg.get("content", "")
            msg_type = msg.get("type")
            
            if msg_type == "function_call":
                # Skip OpenAI-format function calls, they'll be handled differently
                continue
            elif msg_type == "function_call_output":
                # Convert to Groq tool response format
                chat_messages.append({
                    "role": "tool",
                    "content": msg.get("output", ""),
                    "tool_call_id": msg.get("call_id", "")
                })
            elif role in ("user", "assistant", "system"):
                chat_messages.append({"role": role, "content": content})
        
        # Add the new user message
        chat_messages.append({"role": "user", "content": message})
        
        final_response_id = None
        response_text = ""
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                # Use Groq chat completions API
                resp = self.groq.chat.completions.create(
                    model=model,
                    messages=chat_messages,
                    tools=self._get_tools(),
                )
                
                final_response_id = resp.id if hasattr(resp, 'id') else None
                choice = resp.choices[0] if resp.choices else None
                
                if not choice:
                    break
                
                assistant_message = choice.message
                response_text = assistant_message.content or ""
                tool_calls = assistant_message.tool_calls or []
                
                # Add assistant response to history
                if response_text:
                    chat_messages.append({"role": "assistant", "content": response_text})
                elif tool_calls:
                    # If there are tool calls but no text, add assistant message with tool calls
                    chat_messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                            }
                            for tc in tool_calls
                        ]
                    })
                
                # If no tool calls, we're done
                if not tool_calls:
                    break
                
                # Execute tool calls
                for tool_call in tool_calls:
                    call_id = tool_call.id
                    name = tool_call.function.name
                    arguments = tool_call.function.arguments
                    
                    # Execute the tool
                    try:
                        from .sous_chef_tools import handle_sous_chef_tool_call
                        result = handle_sous_chef_tool_call(
                            name=name,
                            arguments=arguments,
                            chef=self.chef,
                            customer=self.customer,
                            lead=self.lead
                        )
                    except Exception as e:
                        logger.error(f"Tool call error: {e}")
                        result = {"status": "error", "message": str(e)}
                    
                    # Add tool result to history (Groq format)
                    chat_messages.append({
                        "role": "tool",
                        "content": json.dumps(result),
                        "tool_call_id": call_id
                    })
                
            except Exception as e:
                logger.error(f"Error in send_message: {e}\n{traceback.format_exc()}")
                return {"status": "error", "message": str(e)}
        
        # Convert chat_messages back to storage format for thread history
        current_history = chat_messages
        
        # Save assistant response
        if response_text:
            self._save_message(thread, 'assistant', response_text)
        
        # Update thread history
        thread.openai_input_history = current_history
        thread.latest_response_id = final_response_id
        thread.save(update_fields=['openai_input_history', 'latest_response_id', 'updated_at'])
        
        return {
            "status": "success",
            "message": response_text or "",
            "response_id": final_response_id,
            "thread_id": thread.id
        }

    def send_structured_message(self, message: str) -> Dict[str, Any]:
        """
        Send a message and get a structured JSON response.
        Uses Groq with tools first, then JSON mode for final response.
        """
        thread = self._get_or_create_thread()
        
        # Build history for chat completions format
        history = thread.openai_input_history or []
        
        # Convert to chat format - use BASE instructions (no JSON format) for Phase 1
        chat_messages = []
        chat_messages.append({"role": "system", "content": self.instructions})
        
        # Add conversation history
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and content:
                chat_messages.append({"role": role, "content": content})
        
        # Add new user message
        chat_messages.append({"role": "user", "content": message})
        
        # Save user message
        self._save_message(thread, 'chef', message)
        
        # Use two-phase approach: tools first, then JSON mode
        return self._send_message_structured_groq(thread, chat_messages, message)

    def _send_message_structured_groq(
        self,
        thread: 'SousChefThread',
        chat_messages: List[Dict],
        message: str
    ) -> Dict[str, Any]:
        """
        Send structured message using Groq with tool support.
        
        Two-phase approach:
        1. First, loop with tools enabled until all tool calls are resolved
        2. Then, make final call with JSON mode for structured output
        
        Special handling for action tools (navigate_to_dashboard_tab, prefill_form):
        These return render_as_action=True and are converted to clickable action blocks.
        """
        try:
            model = _get_groq_model()
            tools = self._get_tools()
            max_iterations = 10
            iteration = 0
            
            # Collect action-type tool results to append as action blocks
            pending_action_blocks = []
            
            # Phase 1: Handle tool calls (tools and JSON mode can't be used together)
            while iteration < max_iterations:
                iteration += 1
                
                # Call with tools enabled (no JSON mode yet)
                completion = self.groq.chat.completions.create(
                    model=model,
                    messages=chat_messages,
                    tools=tools,
                )
                
                choice = completion.choices[0] if completion.choices else None
                if not choice:
                    break
                
                assistant_message = choice.message
                response_text = assistant_message.content or ""
                tool_calls = assistant_message.tool_calls or []
                
                # If no tool calls, we're done with phase 1
                if not tool_calls:
                    # Add any text response to history before phase 2
                    if response_text:
                        chat_messages.append({"role": "assistant", "content": response_text})
                    break
                
                # Add assistant message with tool calls to history
                chat_messages.append({
                    "role": "assistant",
                    "content": response_text or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        }
                        for tc in tool_calls
                    ]
                })
                
                # Execute tool calls
                for tool_call in tool_calls:
                    call_id = tool_call.id
                    name = tool_call.function.name
                    arguments = tool_call.function.arguments
                    
                    try:
                        from .sous_chef_tools import handle_sous_chef_tool_call
                        result = handle_sous_chef_tool_call(
                            name=name,
                            arguments=arguments,
                            chef=self.chef,
                            customer=self.customer,
                            lead=self.lead
                        )
                    except Exception as e:
                        logger.error(f"Tool call error: {e}")
                        result = {"status": "error", "message": str(e)}
                    
                    # Check if this is an action-type result that should be rendered as a button,
                    # a scaffold-type result, or a payment link preview/confirmation
                    if (result.get("render_as_action") or result.get("render_as_scaffold")
                            or result.get("render_as_payment_preview") or result.get("render_as_payment_confirmation")) \
                            and result.get("status") in ("success", "partial_success"):
                        action_block = self._build_action_block(result)
                        if action_block:
                            pending_action_blocks.append(action_block)
                    
                    # Add tool result to history
                    chat_messages.append({
                        "role": "tool",
                        "content": json.dumps(result),
                        "tool_call_id": call_id
                    })
            
            # Phase 2: Get structured JSON response (no tools, JSON mode enabled)
            # Add detailed JSON format instructions for the final call
            json_format_instructions = """Now provide your final response as JSON. You MUST use this exact structure:
{
  "blocks": [
    {"type": "text", "content": "Your paragraph text here"},
    {"type": "table", "headers": ["Col1", "Col2"], "rows": [["val1", "val2"]]},
    {"type": "list", "ordered": false, "items": ["item1", "item2"]}
  ]
}

Use "text" blocks for paragraphs, "table" blocks for tabular data, and "list" blocks for bullet points.
Respond ONLY with valid JSON, no other text."""
            
            json_instruction_msg = {
                "role": "user", 
                "content": json_format_instructions
            }
            messages_for_json = chat_messages + [json_instruction_msg]
            
            completion = self.groq.chat.completions.create(
                model=model,
                messages=messages_for_json,
                response_format={"type": "json_object"},
            )
            
            response_content = completion.choices[0].message.content
            
            # Parse JSON response
            try:
                parsed = json.loads(response_content)
                
                # Handle various malformed responses
                # Case 1: Array wrapper - model returned [{"blocks": [...]}] instead of {"blocks": [...]}
                if isinstance(parsed, list):
                    if len(parsed) > 0 and isinstance(parsed[0], dict) and "blocks" in parsed[0]:
                        parsed = parsed[0]
                    else:
                        # Array of blocks directly - wrap it
                        parsed = {"blocks": parsed}
                
                # Case 2: Missing blocks key
                if not isinstance(parsed, dict) or "blocks" not in parsed:
                    # Wrap in blocks structure if needed
                    parsed = {"blocks": [{"type": "text", "content": response_content}]}
                
                response_json = json.dumps(parsed)
                
                # Extract plain text from blocks for conversation history
                # This prevents the model from seeing JSON in history and mimicking it
                plain_text_parts = []
                for block in parsed.get("blocks", []):
                    if block.get("type") == "text":
                        plain_text_parts.append(block.get("content", ""))
                    elif block.get("type") == "table":
                        # Summarize table as text
                        headers = block.get("headers", [])
                        plain_text_parts.append(f"[Table with columns: {', '.join(headers)}]")
                    elif block.get("type") == "list":
                        items = block.get("items", [])
                        plain_text_parts.append("\n".join(f"• {item}" for item in items[:3]))
                        if len(items) > 3:
                            plain_text_parts.append(f"... and {len(items) - 3} more items")
                
                history_text = "\n\n".join(plain_text_parts) or response_content
                
                # Save plain text to thread history (not JSON)
                chat_messages.append({"role": "assistant", "content": history_text})
                thread.openai_input_history = chat_messages
                thread.save(update_fields=['openai_input_history', 'updated_at'])
                
                # Append any pending action blocks from tool calls
                if pending_action_blocks:
                    if "blocks" not in parsed:
                        parsed["blocks"] = []
                    parsed["blocks"].extend(pending_action_blocks)
                    # Update response_json with the added action blocks
                    response_json = json.dumps(parsed)
                
                # Save structured JSON to database for UI rendering
                self._save_message(thread, 'assistant', response_json)
                
                return {
                    "status": "success",
                    "content": parsed,
                    "thread_id": thread.id
                }
            except json.JSONDecodeError:
                # If JSON parsing fails, wrap as text block
                fallback_content = {"blocks": [{"type": "text", "content": response_content}]}
                response_json = json.dumps(fallback_content)
                
                # Save plain text to history
                chat_messages.append({"role": "assistant", "content": response_content})
                thread.openai_input_history = chat_messages
                thread.save(update_fields=['openai_input_history', 'updated_at'])
                self._save_message(thread, 'assistant', response_json)
                
                return {
                    "status": "success",
                    "content": fallback_content,
                    "thread_id": thread.id
                }
                
        except Exception as e:
            logger.error(f"Error in structured Groq message: {e}\n{traceback.format_exc()}")
            # Return a user-friendly error instead of the raw exception
            fallback_content = {
                "blocks": [
                    {"type": "text", "content": "I'm sorry, I ran into an issue processing your request. Could you try rephrasing your question?"}
                ]
            }
            return {
                "status": "success",  # Return success with fallback content so UI doesn't break
                "content": fallback_content,
                "thread_id": thread.id
            }

    def stream_message(self, message: str) -> Generator[Dict[str, Any], None, None]:
        """Stream a message response."""
        thread = self._get_or_create_thread()
        
        # Build history
        history = thread.openai_input_history or []
        if not history:
            history.append({"role": "system", "content": self.instructions})
        history.append({"role": "user", "content": message})
        
        # Truncate with summarization if needed (preserves context via AI summary)
        history = self._truncate_with_summarization(history, thread)
        
        # Select model
        model = choose_model(
            user_id=self.chef.user_id,
            is_guest=False,
            question=message
        ) or MODEL_PRIMARY
        
        # Save user message
        self._save_message(thread, 'chef', message)
        
        yield from self._process_stream(
            model=model,
            history=history,
            thread=thread
        )

    def _process_stream(
        self,
        model: str,
        history: List[Dict[str, Any]],
        thread: SousChefThread
    ) -> Generator[Dict[str, Any], None, None]:
        """Core streaming logic using Groq's streaming API."""
        # Convert history to Groq chat format
        chat_messages = []
        
        # Add system message with instructions
        chat_messages.append({"role": "system", "content": self.instructions})
        
        # Convert history to chat format
        for msg in history:
            role = msg.get("role")
            content = msg.get("content", "")
            msg_type = msg.get("type")
            
            if msg_type == "function_call":
                continue
            elif msg_type == "function_call_output":
                chat_messages.append({
                    "role": "tool",
                    "content": msg.get("output", ""),
                    "tool_call_id": msg.get("call_id", "")
                })
            elif role in ("user", "assistant", "system"):
                chat_messages.append({"role": role, "content": content})
        
        final_response_id = None
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                stream = self.groq.chat.completions.create(
                    model=model,
                    messages=chat_messages,
                    tools=self._get_tools(),
                    stream=True,
                )
                
                buf = ""
                tool_calls_data: Dict[int, Dict] = {}  # index -> {id, name, arguments}
                
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    
                    choice = chunk.choices[0]
                    delta = choice.delta
                    
                    # Check for response ID
                    if hasattr(chunk, 'id') and chunk.id and not final_response_id:
                        final_response_id = chunk.id
                        yield {"type": "response_id", "id": final_response_id}
                    
                    # Handle text content
                    if delta.content:
                        buf += delta.content
                        yield {"type": "text", "content": delta.content}
                    
                    # Handle tool calls
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_data:
                                tool_calls_data[idx] = {"id": None, "name": None, "arguments": ""}
                            
                            if tc_delta.id:
                                tool_calls_data[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_data[idx]["name"] = tc_delta.function.name
                                    yield {
                                        "type": "response.tool",
                                        "tool_call_id": tool_calls_data[idx].get("id", f"call_{idx}"),
                                        "name": tc_delta.function.name,
                                        "output": None,
                                    }
                                if tc_delta.function.arguments:
                                    tool_calls_data[idx]["arguments"] += tc_delta.function.arguments
                    
                    # Check for finish reason
                    if choice.finish_reason:
                        break
                
                # Process any accumulated text
                if buf:
                    chat_messages.append({"role": "assistant", "content": buf.strip()})
                    yield {
                        "type": "tool_result",
                        "tool_call_id": "render_1",
                        "name": "response.render",
                        "output": {"markdown": buf},
                    }
                
                # If no tool calls, we're done
                if not tool_calls_data:
                    if buf:
                        self._save_message(thread, 'assistant', buf)
                        thread.openai_input_history = chat_messages
                        thread.latest_response_id = final_response_id
                        thread.save(update_fields=['openai_input_history', 'latest_response_id', 'updated_at'])
                    yield {"type": "response.completed"}
                    break
                
                # Add assistant message with tool calls to history
                chat_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc["id"] or f"call_{idx}",
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]}
                        }
                        for idx, tc in sorted(tool_calls_data.items())
                    ]
                })
                
                # Execute tool calls and emit events
                for idx, call in sorted(tool_calls_data.items()):
                    call_id = call["id"] or f"call_{idx}"
                    args_json = call["arguments"]
                    
                    try:
                        args_obj = json.loads(args_json) if args_json else {}
                    except json.JSONDecodeError:
                        args_obj = {}
                    
                    yield {
                        "type": "response.function_call",
                        "name": call["name"],
                        "arguments": args_obj,
                        "call_id": call_id,
                    }
                    
                    try:
                        from .sous_chef_tools import handle_sous_chef_tool_call
                        result = handle_sous_chef_tool_call(
                            name=call["name"],
                            arguments=args_json,
                            chef=self.chef,
                            customer=self.customer,
                            lead=self.lead
                        )
                    except Exception as e:
                        logger.error(f"Tool call error: {e}")
                        result = {"status": "error", "message": str(e)}
                    
                    yield {
                        "type": "tool_result",
                        "tool_call_id": call_id,
                        "name": call["name"],
                        "output": result,
                    }
                    
                    # Add tool result to history
                    chat_messages.append({
                        "role": "tool",
                        "content": _safe_json_dumps(result),
                        "tool_call_id": call_id
                    })
                
                # Reset tool_calls_data for next iteration
                tool_calls_data = {}
                
            except Exception as e:
                logger.error(f"Error in streaming: {e}\n{traceback.format_exc()}")
                yield {"type": "error", "message": str(e)}
                break
        
        # Final save
        if buf:
            thread.openai_input_history = chat_messages
            thread.latest_response_id = final_response_id
            thread.save(update_fields=['openai_input_history', 'latest_response_id', 'updated_at'])

    def _extract_text(self, response) -> str:
        """Extract text content from an OpenAI response."""
        for item in getattr(response, "output", []):
            if getattr(item, 'type', None) == 'message':
                for content in getattr(item, 'content', []):
                    if getattr(content, 'type', None) == 'output_text':
                        return getattr(content, 'text', '')
        return ""

