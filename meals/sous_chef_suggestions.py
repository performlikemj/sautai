# meals/sous_chef_suggestions.py
"""
Sous Chef Contextual Suggestions Engine

Provides intelligent, contextual suggestions based on chef activity.
Uses a hybrid approach: rule-based suggestions (fast, free) and
AI-powered suggestions (for complex scenarios).
"""

import json
import logging
import hashlib
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Count, Q

from chefs.models import Chef

logger = logging.getLogger(__name__)

# Cache timeout for AI suggestions (5 minutes)
AI_SUGGESTION_CACHE_TIMEOUT = 300

# Minimum idle time before triggering AI suggestions (15 seconds in ms)
# Ghost text should appear quickly to feel helpful, not intrusive
AI_IDLE_THRESHOLD_MS = 15 * 1000

# Minimum form completion before offering AI suggestions
MIN_COMPLETION_FOR_AI = 0.2


@dataclass
class Suggestion:
    """A contextual suggestion for the chef."""
    id: str
    type: str  # 'field', 'action', 'tip'
    priority: str  # 'high', 'medium', 'low'
    reason: str
    
    # For field suggestions
    form_type: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None
    
    # For action suggestions
    action: Optional[str] = None  # 'navigate', 'create', 'complete'
    target: Optional[str] = None
    label: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, filtering out None values."""
        result = {}
        for key, val in asdict(self).items():
            if val is not None:
                # Convert field name to camelCase for frontend
                camel_key = self._to_camel_case(key)
                result[camel_key] = val
        return result
    
    @staticmethod
    def _to_camel_case(snake_str: str) -> str:
        components = snake_str.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])


class SuggestionEngine:
    """
    Hybrid suggestion engine that combines rule-based and AI-powered suggestions.
    """
    
    def __init__(self, chef: Chef):
        self.chef = chef
        self._chef_data = None  # Lazy-loaded chef context
    
    def get_suggestions(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get contextual suggestions based on current chef activity.
        
        Args:
            context: Chef activity context from frontend
            
        Returns:
            Dict with 'suggestions' list and overall 'priority'
        """
        suggestions: List[Suggestion] = []
        
        # Extract context values
        current_tab = context.get('currentTab', 'dashboard')
        open_forms = context.get('openForms', [])
        recent_actions = context.get('recentActions', [])
        time_on_screen = context.get('timeOnScreen', 0)
        validation_errors = context.get('validationErrors', [])
        is_idle = context.get('isIdle', False)
        
        # 1. Rule-based suggestions (always run - fast and free)
        rule_suggestions = self._get_rule_based_suggestions(
            current_tab=current_tab,
            open_forms=open_forms,
            recent_actions=recent_actions,
            validation_errors=validation_errors
        )
        suggestions.extend(rule_suggestions)
        
        # 2. AI-powered suggestions (only when appropriate)
        if self._should_call_ai(context):
            ai_suggestions = self._get_ai_suggestions(
                current_tab=current_tab,
                open_forms=open_forms,
                recent_actions=recent_actions
            )
            suggestions.extend(ai_suggestions)
        
        # Deduplicate and sort by priority
        suggestions = self._deduplicate_suggestions(suggestions)
        suggestions = sorted(suggestions, key=lambda s: {'high': 0, 'medium': 1, 'low': 2}[s.priority])
        
        # Limit to top suggestions
        suggestions = suggestions[:5]
        
        # Determine overall priority
        if any(s.priority == 'high' for s in suggestions):
            overall_priority = 'high'
        elif any(s.priority == 'medium' for s in suggestions):
            overall_priority = 'medium'
        else:
            overall_priority = 'low'
        
        return {
            'suggestions': [s.to_dict() for s in suggestions],
            'priority': overall_priority
        }
    
    def _should_call_ai(self, context: Dict[str, Any]) -> bool:
        """Determine if AI suggestions should be generated."""
        open_forms = context.get('openForms', [])
        is_idle = context.get('isIdle', False)
        
        # No open forms = no AI suggestions
        if not open_forms:
            return False
        
        # Check if any form has enough completion to warrant AI help
        has_partial_form = any(
            form.get('completion', 0) >= MIN_COMPLETION_FOR_AI
            for form in open_forms
        )
        
        # Also trigger if form just opened and has at least one field filled
        has_started_form = any(
            form.get('completion', 0) > 0
            for form in open_forms
        )
        
        if not has_partial_form and not has_started_form:
            return False
        
        # Check cache to avoid repeated calls
        cache_key = self._get_ai_cache_key(context)
        if cache.get(cache_key):
            return False
        
        return True
    
    def _get_ai_cache_key(self, context: Dict[str, Any]) -> str:
        """Generate a cache key for AI suggestions based on context."""
        open_forms = context.get('openForms', [])
        # Create a hash of the form types and their fields
        form_data = json.dumps(open_forms, sort_keys=True)
        hash_input = f"{self.chef.id}:{form_data}"
        return f"sous_chef_ai_suggest:{hashlib.md5(hash_input.encode()).hexdigest()}"
    
    def _get_rule_based_suggestions(
        self,
        current_tab: str,
        open_forms: List[Dict],
        recent_actions: List,
        validation_errors: List
    ) -> List[Suggestion]:
        """Generate rule-based suggestions (fast, no API calls)."""
        suggestions = []
        
        # Load chef data for rules
        chef_data = self._get_chef_data()
        
        # =====================================================================
        # Tab-based suggestions (onboarding/setup guidance)
        # =====================================================================
        
        # Dashboard tab - check profile completion
        if current_tab == 'dashboard':
            if chef_data['profile_completion'] < 50:
                suggestions.append(Suggestion(
                    id='complete_profile',
                    type='action',
                    priority='high',
                    reason='Complete your profile to attract more customers',
                    action='navigate',
                    target='profile',
                    label='Complete Your Profile'
                ))
        
        # Kitchen tab - check for dishes
        if current_tab == 'kitchen':
            if chef_data['dish_count'] == 0:
                suggestions.append(Suggestion(
                    id='create_first_dish',
                    type='action',
                    priority='high',
                    reason='Create your first dish to start building meals',
                    action='create',
                    target='dish',
                    label='Create Your First Dish'
                ))
            elif chef_data['dish_count'] > 0 and chef_data['ingredient_count'] == 0:
                suggestions.append(Suggestion(
                    id='add_ingredients',
                    type='tip',
                    priority='medium',
                    reason='Add ingredients to track nutrition and help with prep planning',
                    action='navigate',
                    target='kitchen',
                    label='Add Ingredients'
                ))
        
        # Meals tab - check for meals
        if current_tab == 'meals':
            if chef_data['meal_count'] == 0 and chef_data['dish_count'] > 0:
                suggestions.append(Suggestion(
                    id='create_first_meal',
                    type='action',
                    priority='high',
                    reason='Package your dishes into meals that customers can order',
                    action='create',
                    target='meal',
                    label='Create Your First Meal'
                ))
        
        # Events tab - check for events
        if current_tab == 'events':
            if chef_data['upcoming_event_count'] == 0 and chef_data['meal_count'] > 0:
                suggestions.append(Suggestion(
                    id='schedule_event',
                    type='action',
                    priority='medium',
                    reason='Schedule a meal event to start taking orders',
                    action='create',
                    target='event',
                    label='Schedule a Meal Event'
                ))
        
        # Services tab - check for services
        if current_tab == 'services':
            if chef_data['service_count'] == 0:
                suggestions.append(Suggestion(
                    id='create_service',
                    type='action',
                    priority='high',
                    reason='Set up your services and pricing to accept bookings',
                    action='create',
                    target='service',
                    label='Create Your First Service'
                ))
        
        # =====================================================================
        # Form-based suggestions (help completing forms)
        # =====================================================================
        
        for form in open_forms:
            form_type = form.get('type')
            fields = form.get('fields', {})
            completion = form.get('completion', 0)
            
            # Dish form suggestions
            if form_type == 'dish':
                if not fields.get('name') and completion < 0.3:
                    # Suggest dish name based on chef's style
                    if chef_data['cuisine_types']:
                        cuisine = chef_data['cuisine_types'][0]
                        suggestions.append(Suggestion(
                            id='dish_name_hint',
                            type='tip',
                            priority='low',
                            reason=f'Tip: Include your specialty ({cuisine}) in the dish name for better visibility',
                            form_type='dish',
                            field='name'
                        ))
            
            # Meal form suggestions
            if form_type == 'meal':
                # Suggest meal name if empty and chef has dishes
                if not fields.get('name') and chef_data['dish_count'] > 0:
                    # Generate a name suggestion based on recent dishes
                    recent = chef_data.get('recent_dishes', [])
                    if recent:
                        suggested_name = f"{recent[0]} Meal" if len(recent) == 1 else f"{recent[0]} & {recent[1]} Combo"
                        suggestions.append(Suggestion(
                            id='meal_name_suggestion',
                            type='field',
                            priority='medium',
                            reason=f'Based on your dishes',
                            form_type='meal',
                            field='name',
                            value=suggested_name
                        ))
                
                # Suggest description if name is filled but description is empty
                if fields.get('name') and not fields.get('description'):
                    meal_name = fields.get('name', '')
                    suggestions.append(Suggestion(
                        id='meal_desc_suggestion',
                        type='field',
                        priority='medium',
                        reason='Add a description to help customers',
                        form_type='meal',
                        field='description',
                        value=f"A delicious {meal_name.lower()} featuring our signature dishes, perfect for the whole family."
                    ))
                
                if fields.get('name') and not fields.get('price'):
                    suggestions.append(Suggestion(
                        id='meal_price_hint',
                        type='tip',
                        priority='medium',
                        reason='Set a competitive price based on your dish costs and prep time',
                        form_type='meal',
                        field='price'
                    ))
                
                # If no dishes selected, suggest selecting some
                selected_dishes = fields.get('dishes', [])
                if not selected_dishes and chef_data['dish_count'] > 0:
                    suggestions.append(Suggestion(
                        id='meal_select_dishes',
                        type='tip',
                        priority='high',
                        reason='Select dishes to include in this meal',
                        form_type='meal',
                        field='dishes'
                    ))
            
            # Event form suggestions
            if form_type == 'event':
                if not fields.get('event_date'):
                    suggestions.append(Suggestion(
                        id='event_date_hint',
                        type='tip',
                        priority='medium',
                        reason='Tip: Weekends typically see higher order volume',
                        form_type='event',
                        field='event_date'
                    ))
            
            # Service form suggestions  
            if form_type == 'service':
                if not fields.get('service_type'):
                    suggestions.append(Suggestion(
                        id='service_type_hint',
                        type='tip',
                        priority='medium',
                        reason='Choose a service type that best describes what you offer',
                        form_type='service',
                        field='service_type'
                    ))
        
        # =====================================================================
        # Error-based suggestions
        # =====================================================================
        
        for error in validation_errors:
            error_type = error.get('type')
            error_field = error.get('field')
            
            if error_type == 'required' and error_field:
                suggestions.append(Suggestion(
                    id=f'fix_error_{error_field}',
                    type='tip',
                    priority='high',
                    reason=f'Please fill in the required {error_field.replace("_", " ")} field',
                    form_type=error.get('formType'),
                    field=error_field
                ))
        
        return suggestions
    
    def _get_ai_suggestions(
        self,
        current_tab: str,
        open_forms: List[Dict],
        recent_actions: List
    ) -> List[Suggestion]:
        """Generate AI-powered suggestions for complex scenarios."""
        suggestions = []
        
        # Get chef data for context
        chef_data = self._get_chef_data()
        
        for form in open_forms:
            form_type = form.get('type')
            fields = form.get('fields', {})
            completion = form.get('completion', 0)
            
            # Only suggest for partially filled forms
            if completion < MIN_COMPLETION_FOR_AI:
                continue
            
            # Generate field suggestions using AI
            try:
                ai_suggestions = self._call_ai_for_form(
                    form_type=form_type,
                    fields=fields,
                    chef_data=chef_data
                )
                suggestions.extend(ai_suggestions)
            except Exception as e:
                logger.error(f"AI suggestion error: {e}")
        
        # Mark cache to prevent repeated calls
        cache_key = self._get_ai_cache_key({'openForms': open_forms})
        cache.set(cache_key, True, AI_SUGGESTION_CACHE_TIMEOUT)
        
        return suggestions
    
    def _call_ai_for_form(
        self,
        form_type: str,
        fields: Dict[str, Any],
        chef_data: Dict[str, Any]
    ) -> List[Suggestion]:
        """Call AI to generate form field suggestions."""
        from groq import Groq
        from django.conf import settings
        
        suggestions = []
        
        # Build context for AI
        chef_context = {
            'chef_name': chef_data.get('name', 'Chef'),
            'cuisine_types': chef_data.get('cuisine_types', []),
            'existing_dishes': chef_data.get('recent_dishes', [])[:5],
            'existing_meals': chef_data.get('recent_meals', [])[:5],
        }
        
        # Create prompt based on form type
        prompt = self._build_suggestion_prompt(form_type, fields, chef_context)
        
        try:
            client = Groq(api_key=settings.GROQ_API_KEY)
            
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful culinary assistant. Generate 1-3 specific field suggestions for a chef filling out a form. Return valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            
            for suggestion_data in result.get('suggestions', []):
                field = suggestion_data.get('field')
                value = suggestion_data.get('value')
                reason = suggestion_data.get('reason', 'AI suggestion')
                
                if field and value:
                    suggestions.append(Suggestion(
                        id=f'ai_{form_type}_{field}',
                        type='field',
                        priority='medium',
                        reason=reason,
                        form_type=form_type,
                        field=field,
                        value=value
                    ))
                    
        except Exception as e:
            logger.error(f"AI suggestion call failed: {e}")
        
        return suggestions
    
    def _build_suggestion_prompt(
        self,
        form_type: str,
        fields: Dict[str, Any],
        chef_context: Dict[str, Any]
    ) -> str:
        """Build the AI prompt for form suggestions."""
        
        # Filter out empty fields
        filled_fields = {k: v for k, v in fields.items() if v}
        
        prompt = f"""Help chef {chef_context.get('chef_name', 'this chef')} complete a {form_type} form.

Chef's cuisine style: {', '.join(chef_context.get('cuisine_types', ['various']))}

Current form values:
{json.dumps(filled_fields, indent=2) if filled_fields else 'No fields filled yet'}

"""
        
        if form_type == 'dish':
            prompt += """
Suggest values for unfilled fields like:
- name: Creative, descriptive dish name
- description: Appetizing description highlighting key ingredients

Existing dishes for reference: """ + ', '.join(chef_context.get('existing_dishes', ['none']))
        
        elif form_type == 'meal':
            prompt += """
Suggest values for unfilled fields like:
- name: Clear meal package name
- description: What's included and who it's for
- meal_type: breakfast, lunch, dinner, or snack
- price: Suggested price in dollars (number only)

Existing meals for reference: """ + ', '.join(chef_context.get('existing_meals', ['none']))
        
        elif form_type == 'event':
            prompt += """
Suggest values for unfilled fields like:
- base_price: Suggested starting price
- max_orders: Reasonable maximum order count

Consider the chef's capacity and typical event sizes."""
        
        elif form_type == 'service':
            prompt += """
Suggest values for unfilled fields like:
- title: Professional service title
- description: Clear service description
- service_type: meal_prep, event_dining, cooking_class, or private_chef"""
        
        prompt += """

Return JSON in this exact format:
{
  "suggestions": [
    {"field": "fieldName", "value": "suggested value", "reason": "why this suggestion"}
  ]
}

Only suggest fields that are currently empty. Be specific and helpful."""
        
        return prompt
    
    def _get_chef_data(self) -> Dict[str, Any]:
        """Load and cache chef data for suggestion rules."""
        if self._chef_data is not None:
            return self._chef_data
        
        try:
            from meals.models import Dish, Meal, ChefMealEvent
            from chef_services.models import ChefServiceOffering
            
            chef = self.chef
            now = timezone.now()
            
            # Count entities
            dish_count = Dish.objects.filter(chef=chef).count()
            meal_count = Meal.objects.filter(chef=chef).count()
            ingredient_count = 0  # Will need ingredient model reference
            service_count = ChefServiceOffering.objects.filter(chef=chef, is_active=True).count()
            
            upcoming_events = ChefMealEvent.objects.filter(
                chef=chef,
                event_date__gte=now.date(),
                status='open'
            ).count()
            
            # Get recent items for context
            recent_dishes = list(
                Dish.objects.filter(chef=chef)
                .order_by('-created_at')[:5]
                .values_list('name', flat=True)
            )
            
            recent_meals = list(
                Meal.objects.filter(chef=chef)
                .order_by('-created_at')[:5]
                .values_list('name', flat=True)
            )
            
            # Profile completion estimate - use ONLY fields that exist on Chef model
            profile_fields = [
                chef.bio,
                chef.experience,
                bool(chef.profile_pic),
                chef.serving_postalcodes.exists(),  # Correct field name
            ]
            filled_count = sum(1 for f in profile_fields if f)
            profile_completion = int((filled_count / len(profile_fields)) * 100)
            
            # Cuisine types - field doesn't exist on Chef model, return empty list
            cuisine_types = []
            
            self._chef_data = {
                'name': chef.user.first_name or chef.user.username,
                'dish_count': dish_count,
                'meal_count': meal_count,
                'ingredient_count': ingredient_count,
                'service_count': service_count,
                'upcoming_event_count': upcoming_events,
                'profile_completion': profile_completion,
                'cuisine_types': cuisine_types,
                'recent_dishes': recent_dishes,
                'recent_meals': recent_meals,
            }
            
        except Exception as e:
            logger.error(f"Error loading chef data for suggestions: {e}")
            # Return safe defaults to prevent crashes
            self._chef_data = {
                'name': 'Chef',
                'dish_count': 0,
                'meal_count': 0,
                'ingredient_count': 0,
                'service_count': 0,
                'upcoming_event_count': 0,
                'profile_completion': 0,
                'cuisine_types': [],
                'recent_dishes': [],
                'recent_meals': [],
            }
        
        return self._chef_data
    
    def _deduplicate_suggestions(self, suggestions: List[Suggestion]) -> List[Suggestion]:
        """Remove duplicate suggestions based on ID."""
        seen = set()
        unique = []
        for s in suggestions:
            if s.id not in seen:
                seen.add(s.id)
                unique.append(s)
        return unique
