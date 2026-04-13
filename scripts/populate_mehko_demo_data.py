#!/usr/bin/env python3
"""
Populate demo data for a MeHKO chef dashboard demo video.

Creates a complete MeHKO-compliant chef (Chef Maria) with culturally diverse
meals, clients with health-related dietary needs, 90 days of order history
showing business growth, payment links, surveys, and prep planning data.

Run with:
    python manage.py shell < scripts/populate_mehko_demo_data.py

Idempotent — safe to re-run. All demo users prefixed with "mehko_demo_".
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from chef_services.models import (
    ChefCustomerConnection,
    ChefServiceOffering,
    ChefServiceOrder,
    ChefServicePriceTier,
)
from chefs.models import Chef, ChefPaymentLink, MehkoConfig
from chefs.resource_planning.models import ChefPrepPlan, ChefPrepPlanItem, RecipeIngredient
from crm.models import Lead, LeadHouseholdMember
from custom_auth.models import CustomUser, HouseholdMember, UserRole
from meals.models import (
    ChefMealEvent,
    ChefMealOrder,
    DietaryPreference,
    Dish,
    Ingredient,
    Meal,
    Order,
)
from surveys.models import (
    EventSurvey,
    EventSurveyQuestion,
    QuestionResponse,
    SurveyQuestion,
    SurveyResponse,
    SurveyTemplate,
)

# ── Configuration ────────────────────────────────────────────────────────────

CHEF_USERNAME = "chef_maria"
CHEF_PASSWORD = "mehkodemo2026"
DAYS_OF_DATA = 90

# ── Demo customer identities (diverse LA County demographics) ────────────────

DEMO_CUSTOMERS = [
    ("mehko_demo_rosa", "Rosa", "Martinez", "mehko_rosa@demo.local"),
    ("mehko_demo_james", "James", "Washington", "mehko_james@demo.local"),
    ("mehko_demo_mei", "Mei", "Chen", "mehko_mei@demo.local"),
    ("mehko_demo_patricia", "Patricia", "Okafor", "mehko_patricia@demo.local"),
    ("mehko_demo_carlos", "Carlos", "Reyes", "mehko_carlos@demo.local"),
    ("mehko_demo_sarah", "Sarah", "Kim", "mehko_sarah@demo.local"),
    ("mehko_demo_david", "David", "Nguyen", "mehko_david@demo.local"),
    ("mehko_demo_fatima", "Fatima", "Hassan", "mehko_fatima@demo.local"),
    ("mehko_demo_tom", "Tom", "Bradley", "mehko_tom@demo.local"),
    ("mehko_demo_ana", "Ana", "Delgado", "mehko_ana@demo.local"),
]

# ── CRM Leads (off-platform community contacts) ─────────────────────────────

CRM_LEADS = [
    {
        "first_name": "Elena",
        "last_name": "Morales",
        "email": "elena.morales@demo.local",
        "phone": "(213) 555-0142",
        "source": "referral",
        "status": "qualified",
        "notes": "Referred by Rosa. Needs diabetic meals for husband. Family of 4.",
        "dietary_preferences": ["Diabetic-Friendly", "Low-Sodium"],
        "household_size": 4,
        "budget_cents": 50000,
        "is_priority": True,
    },
    {
        "first_name": "Marcus",
        "last_name": "Brown",
        "email": "marcus.brown@demo.local",
        "phone": "(323) 555-0198",
        "source": "event",
        "status": "contacted",
        "notes": "Met at East LA farmers market. Interested in weekly meal prep.",
        "dietary_preferences": ["High-Protein"],
        "household_size": 2,
        "budget_cents": 30000,
    },
    {
        "first_name": "Linda",
        "last_name": "Tran",
        "email": "linda.tran@demo.local",
        "phone": "(626) 555-0167",
        "source": "referral",
        "status": "new",
        "notes": "Church group referral. Family of 5, looking for weekly service.",
        "dietary_preferences": ["Everything"],
        "household_size": 5,
        "budget_cents": 70000,
    },
    {
        "first_name": "Robert",
        "last_name": "Jackson",
        "email": "robert.jackson@demo.local",
        "phone": "(310) 555-0134",
        "source": "outbound",
        "status": "contacted",
        "notes": "Picked up flyer at community center. Low-sodium needs for heart condition.",
        "dietary_preferences": ["Low-Sodium", "Low-Calorie"],
        "household_size": 1,
        "budget_cents": 25000,
    },
    {
        "first_name": "Priya",
        "last_name": "Sharma",
        "email": "priya.sharma@demo.local",
        "phone": "(818) 555-0156",
        "source": "referral",
        "status": "won",
        "notes": "Converted to platform customer. Vegetarian family, weekly prep client.",
        "dietary_preferences": ["Vegetarian"],
        "household_size": 3,
        "budget_cents": 45000,
    },
]

# ── Ingredients with nutrition data ──────────────────────────────────────────

INGREDIENTS_DATA = [
    # name, calories, fat, carbs, protein
    ("Masa Harina", 360, 3.5, 76, 9),
    ("Pork Shoulder", 250, 18, 0, 22),
    ("Black Beans", 130, 0.5, 23, 8.5),
    ("Plantains", 120, 0.4, 31, 1.3),
    ("Jasmine Rice", 130, 0.3, 28, 2.7),
    ("Scotch Bonnet Pepper", 18, 0.4, 3.5, 0.7),
    ("Tomato Paste", 80, 0.5, 18, 4),
    ("Chicken Thighs", 210, 12, 0, 24),
    ("Ground Turkey (lean)", 170, 8, 0, 21),
    ("Lumpia Wrappers", 80, 0.5, 17, 2),
    ("Cauliflower", 25, 0.3, 5, 2),
    ("Sweet Potato", 100, 0, 24, 1.6),
    ("Cilantro", 1, 0, 0.1, 0.1),
    ("Lime Juice", 8, 0, 2.6, 0.1),
    ("Olive Oil", 120, 14, 0, 0),
    ("Yellow Onion", 40, 0.1, 9, 1),
    ("Garlic", 5, 0, 1, 0.2),
    ("Corn Husks", 0, 0, 0, 0),
    ("Empanada Dough", 280, 12, 38, 5),
    ("Ground Beef (90/10)", 200, 11, 0, 23),
    ("Brown Rice", 110, 0.9, 23, 2.6),
    ("Quinoa", 120, 1.9, 21, 4.4),
    ("Spinach", 7, 0.1, 1.1, 0.9),
    ("Salmon Fillet", 210, 13, 0, 22),
    ("Avocado", 160, 15, 8.5, 2),
]

# ── Dishes: name → list of ingredient names ──────────────────────────────────

DISHES_DATA = [
    ("Abuela's Pork Tamales", ["Masa Harina", "Pork Shoulder", "Corn Husks", "Yellow Onion", "Garlic"]),
    ("Black Bean & Sweet Potato Bowl", ["Black Beans", "Sweet Potato", "Brown Rice", "Cilantro", "Lime Juice"]),
    ("Chicken Jollof Rice", ["Jasmine Rice", "Chicken Thighs", "Tomato Paste", "Scotch Bonnet Pepper", "Yellow Onion"]),
    ("Turkey Empanadas", ["Empanada Dough", "Ground Turkey (lean)", "Yellow Onion", "Garlic", "Cilantro"]),
    ("Lumpia Shanghai", ["Lumpia Wrappers", "Ground Beef (90/10)", "Yellow Onion", "Garlic"]),
    ("Plantain Maduros", ["Plantains", "Olive Oil"]),
    ("Cauliflower Rice Stir-Fry", ["Cauliflower", "Chicken Thighs", "Garlic", "Olive Oil"]),
    ("Salmon with Quinoa & Spinach", ["Salmon Fillet", "Quinoa", "Spinach", "Olive Oil", "Garlic"]),
    ("Chicken Pozole Verde", ["Chicken Thighs", "Corn Husks", "Lime Juice", "Cilantro", "Yellow Onion"]),
    ("Avocado Black Bean Salad", ["Avocado", "Black Beans", "Cilantro", "Lime Juice", "Yellow Onion"]),
]

# ── Recipe ingredients for prep planning (dish_name → ingredients w/ details) ─

RECIPE_INGREDIENTS_DATA = {
    "Abuela's Pork Tamales": [
        ("Masa Harina", 4, "lbs", 180, "pantry"),
        ("Pork Shoulder", 6, "lbs", 5, "refrigerated"),
        ("Corn Husks", 2, "packs", 365, "pantry"),
        ("Yellow Onion", 2, "lbs", 14, "counter"),
        ("Garlic", 0.5, "lbs", 21, "counter"),
    ],
    "Black Bean & Sweet Potato Bowl": [
        ("Black Beans (dried)", 3, "lbs", 365, "pantry"),
        ("Sweet Potato", 4, "lbs", 14, "counter"),
        ("Brown Rice", 3, "lbs", 180, "pantry"),
        ("Cilantro", 2, "bunches", 7, "refrigerated"),
        ("Lime Juice", 0.5, "cups", 30, "refrigerated"),
    ],
    "Chicken Jollof Rice": [
        ("Jasmine Rice", 4, "lbs", 365, "pantry"),
        ("Chicken Thighs", 5, "lbs", 3, "refrigerated"),
        ("Tomato Paste", 2, "cans", 180, "pantry"),
        ("Scotch Bonnet Pepper", 0.25, "lbs", 7, "refrigerated"),
        ("Yellow Onion", 2, "lbs", 14, "counter"),
    ],
    "Salmon with Quinoa & Spinach": [
        ("Salmon Fillet", 4, "lbs", 2, "refrigerated"),
        ("Quinoa", 2, "lbs", 365, "pantry"),
        ("Spinach", 1, "lbs", 5, "refrigerated"),
        ("Olive Oil", 0.5, "cups", 365, "pantry"),
        ("Garlic", 0.25, "lbs", 21, "counter"),
    ],
    "Cauliflower Rice Stir-Fry": [
        ("Cauliflower", 4, "heads", 7, "refrigerated"),
        ("Chicken Thighs", 4, "lbs", 3, "refrigerated"),
        ("Garlic", 0.25, "lbs", 21, "counter"),
        ("Olive Oil", 0.5, "cups", 365, "pantry"),
    ],
}

# ── Meals: name, meal_type, price, description, dish_names, dietary_pref_names

MEALS_DATA = [
    (
        "Tamale Tuesday Special",
        "Dinner",
        Decimal("15.00"),
        "Abuela's handmade pork tamales with a side of sweet plantain maduros. A taste of home.",
        ["Abuela's Pork Tamales", "Plantain Maduros"],
        ["Everything"],
    ),
    (
        "Heart-Healthy Salmon Plate",
        "Dinner",
        Decimal("22.00"),
        "Pan-seared salmon over fluffy quinoa with sauteed spinach. Rich in omega-3s.",
        ["Salmon with Quinoa & Spinach"],
        ["Low-Sodium", "High-Protein", "Gluten-Free"],
    ),
    (
        "Diabetic-Friendly Power Bowl",
        "Lunch",
        Decimal("14.00"),
        "Fiber-rich black beans and sweet potato over brown rice. Low glycemic, high flavor.",
        ["Black Bean & Sweet Potato Bowl"],
        ["Diabetic-Friendly", "Vegetarian", "Gluten-Free"],
    ),
    (
        "Filipino Comfort Pack",
        "Dinner",
        Decimal("16.00"),
        "Crispy lumpia Shanghai — a family favorite packed with savory ground beef.",
        ["Lumpia Shanghai"],
        ["Everything"],
    ),
    (
        "West African Feast",
        "Dinner",
        Decimal("18.00"),
        "Smoky chicken jollof rice with sweet plantain maduros on the side.",
        ["Chicken Jollof Rice", "Plantain Maduros"],
        ["Gluten-Free"],
    ),
    (
        "Empanada Family Pack",
        "Dinner",
        Decimal("20.00"),
        "Hand-folded turkey empanadas with fresh avocado black bean salad.",
        ["Turkey Empanadas", "Avocado Black Bean Salad"],
        ["Low-Sodium"],
    ),
    (
        "Pozole Weekend Special",
        "Lunch",
        Decimal("16.00"),
        "Traditional chicken pozole verde — warming, comforting, and made from scratch.",
        ["Chicken Pozole Verde"],
        ["Gluten-Free", "Dairy-Free"],
    ),
    (
        "Low-Carb Power Plate",
        "Lunch",
        Decimal("17.00"),
        "Cauliflower rice stir-fry with chicken thighs. High protein, low carb.",
        ["Cauliflower Rice Stir-Fry"],
        ["Diabetic-Friendly", "Low-Calorie", "Keto", "Gluten-Free"],
    ),
]

# ── Household members for platform customers ─────────────────────────────────
# customer_username → list of (name, age, diet_pref_names, allergies, notes)

HOUSEHOLD_MEMBERS_DATA = {
    "mehko_demo_rosa": [
        ("Miguel Martinez", 62, ["Diabetic-Friendly", "Low-Sodium"], ["None"], "Rosa's husband. Type 2 diabetes, watches sodium."),
        ("Sofia Martinez", 28, ["Vegetarian"], ["Soy"], "Rosa's daughter. Vegetarian since college."),
    ],
    "mehko_demo_james": [
        ("Denise Washington", 55, ["High-Protein", "Gluten-Free"], ["Gluten"], "James's wife. Celiac disease."),
        ("Marcus Washington Jr.", 12, ["Everything"], ["Peanuts"], "James's son. Peanut allergy."),
    ],
    "mehko_demo_mei": [
        ("Li Chen", 78, ["Low-Sodium", "Diabetic-Friendly"], ["Shellfish"], "Mei's mother. Heart condition, monitors sodium."),
    ],
    "mehko_demo_fatima": [
        ("Omar Hassan", 45, ["Halal"], ["None"], "Fatima's husband."),
        ("Amira Hassan", 8, ["Halal"], ["Milk"], "Fatima's daughter. Lactose intolerant."),
    ],
    "mehko_demo_carlos": [
        ("Maria Reyes", 34, ["Everything"], ["Tree nuts"], "Carlos's wife."),
    ],
}

# ── Lead household members ───────────────────────────────────────────────────

LEAD_HOUSEHOLD_MEMBERS = {
    "Elena Morales": [
        ("Hector Morales", "spouse", 65, ["Diabetic-Friendly", "Low-Sodium"], ["None"]),
        ("Isabella Morales", "child", 14, ["Everything"], ["Peanuts"]),
        ("Marco Morales", "child", 10, ["Everything"], ["None"]),
    ],
    "Linda Tran": [
        ("Minh Tran", "spouse", 48, ["Everything"], ["Shellfish"]),
        ("An Tran", "child", 16, ["Everything"], ["None"]),
        ("Linh Tran", "child", 12, ["Everything"], ["None"]),
        ("Bao Tran", "parent", 75, ["Low-Sodium", "Diabetic-Friendly"], ["None"]),
    ],
}

# ── Survey template questions ────────────────────────────────────────────────

SURVEY_QUESTIONS = [
    ("How would you rate the overall meal quality?", "rating", True),
    ("Was the meal ready on time?", "yes_no", True),
    ("How likely are you to order again? (1 = unlikely, 5 = definitely)", "rating", True),
    ("Any dietary needs we should know about for next time?", "text", False),
    ("Would you recommend us to a friend or neighbor?", "yes_no", True),
]

# ── Sample survey text responses ─────────────────────────────────────────────

SURVEY_TEXT_RESPONSES = [
    "Everything was delicious! My husband especially loved the tamales.",
    "Would love a spicier option next time. Otherwise perfect.",
    "The salmon was cooked perfectly. Very fresh ingredients.",
    "No changes needed — we look forward to every order!",
    "My mother really enjoyed the low-sodium options. Thank you for being so thoughtful.",
    "Can you do a vegan version of the jollof rice? Would love that.",
    "Portions were generous. The whole family was happy.",
    "The empanadas were a hit at our dinner party. Everyone asked for your info!",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════════════════════


def create_mehko_chef():
    """Create Chef Maria — a MeHKO-compliant home kitchen operator in LA County."""
    now = timezone.now()

    user, created = CustomUser.objects.get_or_create(
        username=CHEF_USERNAME,
        defaults={
            "first_name": "Maria",
            "last_name": "Gonzalez",
            "email": "chef.maria@demo.local",
            "is_active": True,
        },
    )
    if created:
        user.set_password(CHEF_PASSWORD)
        user.save()
        print(f"  Created user: {CHEF_USERNAME}")
    else:
        print(f"  User already exists: {CHEF_USERNAME}")

    # Ensure UserRole exists with chef flag
    role, _ = UserRole.objects.get_or_create(
        user=user,
        defaults={"is_chef": True, "current_role": "chef"},
    )
    if not role.is_chef:
        role.is_chef = True
        role.current_role = "chef"
        role.save()

    today = date.today()

    chef, chef_created = Chef.objects.update_or_create(
        user=user,
        defaults={
            "bio": (
                "Home kitchen chef based in East Los Angeles, specializing in "
                "culturally diverse, medically tailored meals. I draw from Latin American, "
                "West African, and Filipino traditions to create food that's both nourishing "
                "and full of flavor. Whether you need diabetic-friendly meal prep or a "
                "family-sized tamale order, my kitchen is here for you."
            ),
            "experience": (
                "15 years of home cooking for family and community. MeHKO-permitted "
                "since 2025. Certified food handler. Specializing in medically tailored "
                "meals for clients with dietary restrictions."
            ),
            "is_verified": True,
            "is_live": True,
            "is_on_break": False,
            "default_currency": "usd",
            # MeHKO compliance fields
            "permit_number": "MEHKO-LA-2025-4821",
            "permitting_agency": "LA County Department of Public Health, Environmental Health",
            "permit_expiry": today + timedelta(days=300),
            "county": "Los Angeles",
            "mehko_consent": True,
            "mehko_consent_at": now - timedelta(days=180),
            "mehko_consent_ip": "192.168.1.1",
            "mehko_active": True,
            # Food handler cert
            "food_handlers_cert": True,
            "food_handlers_cert_number": "FH-CA-2024-88712",
            "food_handlers_cert_expiry": today + timedelta(days=540),
            "food_handlers_cert_verified_at": now - timedelta(days=180),
            # Insurance
            "insured": True,
            "insurance_expiry": today + timedelta(days=240),
            "background_checked": True,
            # Calendly
            "calendly_url": "https://calendly.com/chef-maria-demo/consultation",
            # Sous Chef preferences
            "sous_chef_suggestions_enabled": True,
            "sous_chef_suggestion_frequency": "sometimes",
        },
    )
    action = "Created" if chef_created else "Updated"
    print(f"  {action} Chef: {user.get_full_name()} (MeHKO active)")
    return chef


def create_mehko_config():
    """Ensure a MehkoConfig record exists with statutory defaults."""
    config, created = MehkoConfig.objects.get_or_create(
        effective_date=date.today() - timedelta(days=365),
        defaults={
            "daily_meal_cap": 30,
            "weekly_meal_cap": 90,
            "annual_revenue_cap": 100_000,
            "notes": "AB 1325 baseline. Demo data.",
        },
    )
    action = "Created" if created else "Already exists"
    print(f"  {action}: MehkoConfig (30/90/$100k)")
    return config


def create_ingredients(chef):
    """Create culturally diverse ingredients with nutrition data."""
    ingredients = {}
    created_count = 0
    for name, cal, fat, carb, protein in INGREDIENTS_DATA:
        ing, created = Ingredient.objects.get_or_create(
            chef=chef,
            name=name,
            defaults={
                "calories": cal,
                "fat": Decimal(str(fat)),
                "carbohydrates": Decimal(str(carb)),
                "protein": Decimal(str(protein)),
                "is_custom": True,
            },
        )
        ingredients[name] = ing
        if created:
            created_count += 1
    print(f"  Created {created_count} ingredients ({len(INGREDIENTS_DATA)} total)")
    return ingredients


def create_dishes(chef, ingredients):
    """Create dishes from ingredients and add recipe ingredients for prep planning."""
    dishes = {}
    created_count = 0

    for dish_name, ingredient_names in DISHES_DATA:
        # Avoid get_or_create — Dish.save() override conflicts with force_insert=True
        try:
            dish = Dish.objects.get(chef=chef, name=dish_name)
        except Dish.DoesNotExist:
            dish = Dish(chef=chef, name=dish_name)
            dish.save()  # First save establishes PK
            # Set ingredient M2M
            dish_ingredients = [ingredients[n] for n in ingredient_names if n in ingredients]
            dish.ingredients.set(dish_ingredients)
            # Recalculate nutrition from ingredients and save again
            dish.update_nutritional_info()
            dish.save()
            created_count += 1

        dishes[dish_name] = dish

    # Create RecipeIngredient records for prep planning
    recipe_count = 0
    for dish_name, recipe_items in RECIPE_INGREDIENTS_DATA.items():
        if dish_name not in dishes:
            continue
        dish = dishes[dish_name]
        for ri_name, qty, unit, shelf_life, storage in recipe_items:
            _, ri_created = RecipeIngredient.objects.get_or_create(
                dish=dish,
                name=ri_name,
                defaults={
                    "quantity": Decimal(str(qty)),
                    "unit": unit,
                    "shelf_life_days": shelf_life,
                    "storage_type": storage,
                    "shelf_life_updated_at": timezone.now(),
                },
            )
            if ri_created:
                recipe_count += 1

    print(f"  Created {created_count} dishes, {recipe_count} recipe ingredients")
    return dishes


def create_meals(chef, dishes):
    """Create meals with pricing and dietary preference tags."""
    meals = []
    created_count = 0

    for name, meal_type, price, description, dish_names, pref_names in MEALS_DATA:
        # Meal.save() requires image for chef-created meals, and unique constraint
        # on (chef, start_date, meal_type) requires varied start_dates.
        # Use try/get first, then manual insert to bypass save() validation.
        try:
            meal = Meal.objects.get(chef=chef, name=name)
        except Meal.DoesNotExist:
            # Use a unique start_date per meal to satisfy unique constraint
            start_date = date.today() - timedelta(days=DAYS_OF_DATA + created_count)
            # Insert directly to bypass Meal.save() image validation
            meal = Meal(
                chef=chef,
                creator=chef.user,
                name=name,
                meal_type=meal_type,
                price=price,
                description=description,
                start_date=start_date,
            )
            # Use Model.save_base() to skip custom save() validation
            super(Meal, meal).save()

            # Set dishes
            meal_dishes = [dishes[dn] for dn in dish_names if dn in dishes]
            meal.dishes.set(meal_dishes)

            # Set dietary preferences
            prefs = []
            for pname in pref_names:
                pref, _ = DietaryPreference.objects.get_or_create(name=pname)
                prefs.append(pref)
            meal.dietary_preferences.set(prefs)
            created_count += 1

        meals.append(meal)

    print(f"  Created {created_count} meals ({len(MEALS_DATA)} total)")
    return meals


def create_service_offerings(chef):
    """Create Weekly Meal Prep and Single Meal Order offerings with price tiers."""
    offerings = []

    offering_configs = [
        {
            "service_type": "weekly_prep",
            "title": "Weekly Meal Prep",
            "description": (
                "Healthy, home-cooked meals prepared for your entire week. "
                "Customized to your household's dietary needs."
            ),
            "duration": 180,
            "tiers": [
                (1, 2, 6500, "1-2 people", True, "week"),
                (3, 4, 11000, "3-4 people", True, "week"),
                (5, None, 15000, "5+ people", True, "week"),
            ],
        },
        {
            "service_type": "home_chef",
            "title": "Single Meal Order",
            "description": (
                "Order a single meal for pickup or delivery. "
                "Perfect for special occasions or trying something new."
            ),
            "duration": 60,
            "tiers": [
                (1, 2, 3000, "1-2 people", False, None),
                (3, 4, 5000, "3-4 people", False, None),
                (5, None, 7000, "5+ people", False, None),
            ],
        },
    ]

    for config in offering_configs:
        offering, created = ChefServiceOffering.objects.get_or_create(
            chef=chef,
            title=config["title"],
            defaults={
                "service_type": config["service_type"],
                "description": config["description"],
                "active": True,
                "default_duration_minutes": config["duration"],
                "max_travel_miles": 10,
            },
        )
        if created:
            for hmin, hmax, cents, label, recurring, interval in config["tiers"]:
                ChefServicePriceTier.objects.create(
                    offering=offering,
                    household_min=hmin,
                    household_max=hmax,
                    desired_unit_amount_cents=cents,
                    currency="usd",
                    display_label=label,
                    active=True,
                    is_recurring=recurring,
                    recurrence_interval=interval,
                )
            print(f"  Created offering: {config['title']} with {len(config['tiers'])} tiers")
        else:
            print(f"  Offering already exists: {config['title']}")

        offerings.append(offering)

    return offerings


def create_demo_customers(chef):
    """Create platform customers with accepted connections."""
    customers = []

    for username, first_name, last_name, email in DEMO_CUSTOMERS:
        user, created = CustomUser.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "is_active": True,
            },
        )
        if created:
            user.set_password("demo123")
            user.save()

        # Connection with varied join dates
        days_ago = random.randint(5, 80)
        ChefCustomerConnection.objects.update_or_create(
            chef=chef,
            customer=user,
            defaults={
                "status": ChefCustomerConnection.STATUS_ACCEPTED,
                "initiated_by": random.choice([
                    ChefCustomerConnection.INITIATED_BY_CUSTOMER,
                    ChefCustomerConnection.INITIATED_BY_CHEF,
                ]),
                "responded_at": timezone.now() - timedelta(days=days_ago),
            },
        )
        customers.append(user)

    print(f"  Created/updated {len(customers)} customers with connections")
    return customers


def create_crm_leads(chef):
    """Create CRM leads representing community referrals."""
    leads = []

    for lead_data in CRM_LEADS:
        lead, created = Lead.objects.get_or_create(
            owner=chef.user,
            first_name=lead_data["first_name"],
            last_name=lead_data["last_name"],
            defaults={
                "email": lead_data["email"],
                "phone": lead_data.get("phone", ""),
                "source": lead_data["source"],
                "status": lead_data["status"],
                "notes": lead_data["notes"],
                "dietary_preferences": lead_data.get("dietary_preferences", []),
                "household_size": lead_data.get("household_size", 1),
                "budget_cents": lead_data.get("budget_cents"),
                "is_priority": lead_data.get("is_priority", False),
            },
        )
        if created:
            # Backdate created_at for realism
            days_ago = random.randint(10, 60)
            Lead.objects.filter(pk=lead.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago),
                last_interaction_at=timezone.now() - timedelta(days=random.randint(1, days_ago)),
            )
        leads.append(lead)

    print(f"  Created {sum(1 for _ in leads)} CRM leads")
    return leads


def create_household_members(customers, leads):
    """Create household members for platform customers and CRM leads."""
    customer_count = 0
    lead_count = 0

    # Platform customer household members
    customer_map = {c.username: c for c in customers}
    for username, members_data in HOUSEHOLD_MEMBERS_DATA.items():
        user = customer_map.get(username)
        if not user:
            continue
        for name, age, pref_names, allergies, notes in members_data:
            member, created = HouseholdMember.objects.get_or_create(
                user=user,
                name=name,
                defaults={
                    "age": age,
                    "allergies": allergies,
                    "notes": notes,
                },
            )
            if created:
                # Set dietary preferences (M2M to DietaryPreference)
                prefs = []
                for pname in pref_names:
                    pref, _ = DietaryPreference.objects.get_or_create(name=pname)
                    prefs.append(pref)
                member.dietary_preferences.set(prefs)
                customer_count += 1

    # CRM lead household members
    lead_map = {f"{l.first_name} {l.last_name}": l for l in leads}
    for lead_name, members_data in LEAD_HOUSEHOLD_MEMBERS.items():
        lead = lead_map.get(lead_name)
        if not lead:
            continue
        for name, relationship, age, diet_prefs, allergies in members_data:
            _, created = LeadHouseholdMember.objects.get_or_create(
                lead=lead,
                name=name,
                defaults={
                    "relationship": relationship,
                    "age": age,
                    "dietary_preferences": diet_prefs,
                    "allergies": allergies,
                },
            )
            if created:
                lead_count += 1

    print(f"  Created {customer_count} customer household members, {lead_count} lead household members")


def create_service_orders(chef, customers, offerings):
    """Create 90 days of service orders with a growth curve."""
    now = timezone.now()
    orders_created = 0
    total_revenue_cents = 0

    # Growth curve: orders per week over 13 weeks
    weekly_targets = [2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15]

    for week_num in range(13):
        week_start = now - timedelta(days=(13 - week_num) * 7)
        target_orders = weekly_targets[week_num]

        for order_idx in range(target_orders):
            customer = random.choice(customers)
            offering = random.choice(offerings)

            tier = offering.tiers.filter(active=True).first()
            if not tier:
                continue

            # Distribute orders across the week
            day_offset = random.randint(0, 6)
            order_date = week_start + timedelta(days=day_offset)
            service_date = (order_date + timedelta(days=random.randint(2, 5))).date()

            # Status based on age
            days_old = (now - order_date).days
            if days_old > 7:
                status = random.choices(
                    ["completed", "completed", "completed", "confirmed"],
                    weights=[5, 3, 2, 1],
                )[0]
            elif days_old > 2:
                status = random.choice(["confirmed", "confirmed", "completed"])
            else:
                status = random.choice(["awaiting_payment", "confirmed"])

            household_size = random.randint(
                tier.household_min, tier.household_max or 6
            )

            # Vary charged amount slightly around the tier price
            base_cents = tier.desired_unit_amount_cents
            charged_cents = int(base_cents * random.uniform(0.95, 1.05))

            try:
                # Django's save() does NOT call clean() automatically,
                # so historical data bypasses 24-hour notice validation.
                order = ChefServiceOrder.objects.create(
                    customer=customer,
                    chef=chef,
                    offering=offering,
                    tier=tier,
                    household_size=household_size,
                    service_date=service_date,
                    service_start_time=time(hour=random.randint(10, 18)),
                    delivery_method=random.choice(["self_delivery", "customer_pickup"]),
                    charged_amount_cents=charged_cents,
                    status=status,
                )
                # Backdate created_at
                ChefServiceOrder.objects.filter(pk=order.pk).update(created_at=order_date)
                orders_created += 1
                if status in ("completed", "confirmed"):
                    total_revenue_cents += charged_cents
            except Exception:
                pass  # Skip validation errors or duplicates

    revenue_dollars = total_revenue_cents / 100
    print(f"  Created {orders_created} service orders (~${revenue_dollars:,.0f} revenue)")
    return orders_created


def create_meal_events_and_orders(chef, customers, meals):
    """Create meal share events with dynamic pricing and customer orders."""
    from django.db.models.signals import post_save
    from meals.signals import push_order_event

    # Temporarily disconnect the order notification signal to avoid
    # async DB access that closes the connection during bulk inserts.
    post_save.disconnect(push_order_event, sender=ChefMealOrder)

    now = timezone.now()
    events_created = 0
    orders_created = 0

    if not meals:
        post_save.connect(push_order_event, sender=ChefMealOrder)
        print("  No meals available — skipping meal events")
        return 0, 0

    # Create ~15 events spread over 90 days
    for event_idx in range(15):
        days_ago = DAYS_OF_DATA - (event_idx * 6)  # roughly every 6 days
        if days_ago < 0:
            days_ago = 0

        meal = meals[event_idx % len(meals)]
        event_date = (now - timedelta(days=days_ago)).date()
        event_time = time(hour=random.choice([17, 18, 19]))

        # Status based on date
        if days_ago > 3:
            event_status = "completed"
        elif days_ago > 0:
            event_status = "closed"
        else:
            event_status = "open"

        base_price = Decimal(str(random.randint(15, 25)))
        min_price = base_price - Decimal("8.00")

        # Check for existing event to avoid unique constraint violation
        existing = ChefMealEvent.objects.filter(
            chef=chef, meal=meal, event_date=event_date, event_time=event_time, status=event_status
        ).exists()
        if existing:
            continue

        event = ChefMealEvent(
            chef=chef,
            meal=meal,
            event_date=event_date,
            event_time=event_time,
            order_cutoff_time=timezone.make_aware(
                datetime.combine(event_date - timedelta(days=1), time(hour=18))
            ),
            max_orders=random.randint(10, 20),
            min_orders=2,
            base_price=base_price,
            current_price=base_price,  # Will be set on save
            min_price=min_price,
            status=event_status,
            description=meal.description,
        )
        event.save()
        events_created += 1

        # Create orders — more orders for recent events (growth curve)
        if days_ago > 60:
            num_orders = random.randint(2, 3)
        elif days_ago > 30:
            num_orders = random.randint(3, 5)
        else:
            num_orders = random.randint(4, 7)

        event_customers = random.sample(customers, min(num_orders, len(customers)))
        current_price = base_price

        for cust_idx, customer in enumerate(event_customers):
            # Dynamic pricing: decrease 5% of (base-min) per order after first
            if cust_idx > 0:
                discount = Decimal("0.05") * (base_price - min_price)
                current_price = max(min_price, current_price - discount)

            quantity = random.randint(1, 2)
            price_paid = current_price * quantity

            if event_status == "completed":
                order_status = random.choice(["completed", "completed", "confirmed"])
            elif event_status == "closed":
                order_status = "confirmed"
            else:
                order_status = random.choice(["placed", "confirmed"])

            # Create parent Order
            order_obj = Order.objects.create(
                customer=customer,
                status="Completed" if order_status == "completed" else "Placed",
            )

            ChefMealOrder.objects.create(
                order=order_obj,
                meal_event=event,
                customer=customer,
                quantity=quantity,
                unit_price=current_price,
                price_paid=price_paid,
                status=order_status,
            )

            # Backdate
            order_date = timezone.make_aware(
                datetime.combine(
                    event_date - timedelta(days=random.randint(1, 3)),
                    time(hour=random.randint(8, 20)),
                )
            )
            Order.objects.filter(pk=order_obj.pk).update(order_date=order_date)
            orders_created += 1

        # Update event with final price and count
        event.orders_count = len(event_customers)
        event.current_price = current_price
        event.save(update_fields=["orders_count", "current_price"])

    # Reconnect the signal
    post_save.connect(push_order_event, sender=ChefMealOrder)

    print(f"  Created {events_created} meal events with {orders_created} orders")
    return events_created, orders_created


def create_payment_links(chef, customers, leads):
    """Create payment links with varied statuses."""
    now = timezone.now()
    created_count = 0

    descriptions = [
        "Weekly Meal Prep — Week of {date}",
        "Tamale Tuesday Family Pack",
        "Heart-Healthy Salmon Plate x4",
        "Empanada Party Platter",
        "Diabetic-Friendly Weekly Box",
        "Jollof Rice Catering — Community Event",
        "Custom Meal Prep — 2 Weeks",
        "Filipino Comfort Pack x3",
        "Pozole Weekend Special — Family Size",
        "Low-Carb Power Plates — 5 Meals",
    ]

    link_configs = [
        # (status, amount_cents, days_ago, is_customer)
        ("paid", 6500, 45, True),
        ("paid", 11000, 38, True),
        ("paid", 15000, 30, False),
        ("paid", 6500, 22, True),
        ("paid", 5000, 15, True),
        ("pending", 11000, 5, True),
        ("pending", 6500, 3, False),
        ("pending", 7000, 1, True),
        ("draft", 15000, 0, False),
    ]

    for idx, (status, amount_cents, days_ago, is_customer) in enumerate(link_configs):
        created_at = now - timedelta(days=days_ago)
        desc = descriptions[idx % len(descriptions)]
        if "{date}" in desc:
            desc = desc.format(date=(now - timedelta(days=days_ago - 3)).strftime("%B %d"))

        # Pick recipient
        customer = None
        lead = None
        email = ""
        if is_customer and customers:
            customer = random.choice(customers)
            email = customer.email
        elif leads:
            lead = random.choice(leads)
            email = lead.email

        defaults = {
            "amount_cents": amount_cents,
            "currency": "usd",
            "description": desc,
            "status": status,
            "recipient_email": email,
            "expires_at": created_at + timedelta(days=7),
            "customer": customer,
            "lead": lead,
        }

        if status == "paid":
            defaults["paid_at"] = created_at + timedelta(days=random.randint(0, 2))
            defaults["paid_amount_cents"] = amount_cents
            defaults["email_sent_at"] = created_at
            defaults["email_send_count"] = 1
        elif status == "pending":
            defaults["email_sent_at"] = created_at
            defaults["email_send_count"] = random.randint(1, 2)

        # Use description + chef as a loose dedup key
        existing = ChefPaymentLink.objects.filter(
            chef=chef, description=desc
        ).exists()
        if not existing:
            link = ChefPaymentLink.objects.create(chef=chef, **defaults)
            # Backdate created_at
            ChefPaymentLink.objects.filter(pk=link.pk).update(created_at=created_at)
            created_count += 1

    print(f"  Created {created_count} payment links")


def create_survey_data(chef, meals):
    """Create survey template, event surveys, and responses."""
    # 1. Create template
    template, t_created = SurveyTemplate.objects.get_or_create(
        chef=chef,
        title="Post-Meal Feedback",
        defaults={
            "description": "Quick feedback survey sent after meal share events.",
            "is_default": True,
        },
    )

    # 2. Create template questions
    for idx, (text, qtype, required) in enumerate(SURVEY_QUESTIONS):
        SurveyQuestion.objects.get_or_create(
            template=template,
            order=idx + 1,
            defaults={
                "question_text": text,
                "question_type": qtype,
                "is_required": required,
            },
        )

    # 3. Create event surveys for completed meal events
    completed_events = ChefMealEvent.objects.filter(
        chef=chef, status="completed"
    ).order_by("-event_date")[:5]

    surveys_created = 0
    responses_created = 0

    for event in completed_events:
        survey, s_created = EventSurvey.objects.get_or_create(
            chef=chef,
            event=event,
            defaults={
                "template": template,
                "title": f"Feedback: {event.meal.name} — {event.event_date}",
                "description": "We'd love to hear your thoughts!",
                "status": "closed" if event.event_date < date.today() - timedelta(days=7) else "active",
            },
        )
        if not s_created:
            continue
        surveys_created += 1

        # Copy questions to event survey
        eq_objects = []
        for idx, (text, qtype, required) in enumerate(SURVEY_QUESTIONS):
            eq = EventSurveyQuestion.objects.create(
                survey=survey,
                question_text=text,
                question_type=qtype,
                order=idx + 1,
                is_required=required,
            )
            eq_objects.append(eq)

        # 4. Create responses from event attendees
        event_orders = event.orders.select_related("customer").all()
        for meal_order in event_orders[:5]:  # cap at 5 responses per survey
            response = SurveyResponse.objects.create(
                survey=survey,
                customer=meal_order.customer,
                respondent_email=meal_order.customer.email,
                respondent_name=meal_order.customer.get_full_name(),
            )
            responses_created += 1

            # Answer each question
            for eq in eq_objects:
                if eq.question_type == "rating":
                    QuestionResponse.objects.create(
                        response=response,
                        question=eq,
                        rating_value=random.choices([4, 5, 5, 5, 3], weights=[3, 5, 4, 3, 1])[0],
                    )
                elif eq.question_type == "yes_no":
                    QuestionResponse.objects.create(
                        response=response,
                        question=eq,
                        boolean_value=random.choices([True, True, True, False], weights=[8, 3, 2, 1])[0],
                    )
                elif eq.question_type == "text":
                    # Only ~60% of respondents fill in optional text
                    if random.random() < 0.6:
                        QuestionResponse.objects.create(
                            response=response,
                            question=eq,
                            text_value=random.choice(SURVEY_TEXT_RESPONSES),
                        )

    print(f"  Created {surveys_created} event surveys with {responses_created} responses")


def create_prep_plans(chef, dishes):
    """Create prep plans with shopping list items and timing badges."""
    today = date.today()
    plans_created = 0

    plan_configs = [
        # (start_offset, end_offset, status, label)
        (-14, -8, "completed", "last 2 weeks"),
        (-3, 4, "in_progress", "current week"),
        (5, 11, "draft", "next week"),
    ]

    for start_off, end_off, status, label in plan_configs:
        start = today + timedelta(days=start_off)
        end = today + timedelta(days=end_off)

        plan, created = ChefPrepPlan.objects.get_or_create(
            chef=chef,
            plan_start_date=start,
            plan_end_date=end,
            defaults={
                "status": status,
                "total_meals": random.randint(8, 15),
                "total_servings": random.randint(25, 50),
                "unique_ingredients": random.randint(12, 20),
                "shopping_list": {"generated": True},
                "batch_suggestions": {"suggestions": ["Batch cook rice and beans together"]},
            },
        )
        if not created:
            continue
        plans_created += 1

        # Create prep plan items from recipe ingredients
        item_count = 0
        for dish_name, recipe_items in RECIPE_INGREDIENTS_DATA.items():
            if dish_name not in dishes:
                continue
            for ri_name, qty, unit, shelf_life, storage in recipe_items:
                # Scale quantity for the plan
                scaled_qty = Decimal(str(qty)) * Decimal(str(random.uniform(1.5, 3.0))).quantize(Decimal("0.01"))

                earliest = start + timedelta(days=random.randint(0, 2))
                latest = end - timedelta(days=random.randint(0, 2))

                # Calculate timing
                if shelf_life >= 30:
                    timing = "optimal"
                    purchase_date = start - timedelta(days=2)
                elif shelf_life >= 7:
                    timing = "optimal"
                    purchase_date = earliest - timedelta(days=min(3, shelf_life - 2))
                elif shelf_life >= 4:
                    timing = "tight"
                    purchase_date = earliest - timedelta(days=1)
                else:
                    timing = "problematic"
                    purchase_date = earliest

                # Only create unique items per plan
                _, item_created = ChefPrepPlanItem.objects.get_or_create(
                    prep_plan=plan,
                    ingredient_name=ri_name,
                    defaults={
                        "total_quantity": scaled_qty,
                        "unit": unit,
                        "shelf_life_days": shelf_life,
                        "storage_type": storage,
                        "earliest_use_date": earliest,
                        "latest_use_date": latest,
                        "suggested_purchase_date": purchase_date,
                        "timing_status": timing,
                        "timing_notes": f"Shelf life: {shelf_life} days ({storage})",
                        "meals_using": [{"meal": dish_name, "date": str(earliest)}],
                        "is_purchased": status == "completed",
                    },
                )
                if item_created:
                    item_count += 1

        # Update unique ingredients count
        plan.unique_ingredients = plan.items.count()
        plan.save(update_fields=["unique_ingredients"])

    print(f"  Created {plans_created} prep plans with items")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    print("\n" + "=" * 60)
    print("Populating MeHKO Demo Data for Chef Maria")
    print("=" * 60 + "\n")

    with transaction.atomic():
        print("1. Creating MeHKO chef profile...")
        chef = create_mehko_chef()

        print("\n2. Creating MeHKO config...")
        create_mehko_config()

        print("\n3. Creating ingredients...")
        ingredients = create_ingredients(chef)

        print("\n4. Creating dishes...")
        dishes = create_dishes(chef, ingredients)

        print("\n5. Creating meals...")
        meals = create_meals(chef, dishes)

        print("\n6. Creating service offerings...")
        offerings = create_service_offerings(chef)

        print("\n7. Creating demo customers...")
        customers = create_demo_customers(chef)

        print("\n8. Creating CRM leads...")
        leads = create_crm_leads(chef)

        print("\n9. Creating household members...")
        create_household_members(customers, leads)

        print("\n10. Creating service orders (90 days)...")
        create_service_orders(chef, customers, offerings)

        print("\n11. Creating meal events and orders...")
        create_meal_events_and_orders(chef, customers, meals)

        print("\n12. Creating payment links...")
        create_payment_links(chef, customers, leads)

        print("\n13. Creating survey data...")
        create_survey_data(chef, meals)

        print("\n14. Creating prep plans...")
        create_prep_plans(chef, dishes)

    print("\n" + "=" * 60)
    print("MeHKO demo data population complete!")
    print(f"Log in as: {CHEF_USERNAME} / {CHEF_PASSWORD}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
else:
    # When run via: python manage.py shell < scripts/populate_mehko_demo_data.py
    main()
