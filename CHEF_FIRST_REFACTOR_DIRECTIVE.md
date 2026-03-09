# Developer Directive: Chef-First sautai Refactor

_Last updated: November 15, 2025_

## 0. Context & Goal
The existing `neighborhood-united` Django/DRF backend still orbits legacy AI meal-planning flows (SSE meal plans, Instacart helpers, health widgets) even though sautai’s product direction now centers around chefs. We are pivoting to a chef-first experience in which:

- Guests primarily discover chefs, browse their offerings/events, and place bookings.
- Chefs operate a lightweight CRM to configure services, manage calendars, and track client relationships.

This directive is the “North Star” for the backend refactor. It documents the desired end state so we can incrementally land smaller PRs that converge on it.

## 1. Goals & Non-Goals
### 1.1 Goals
1. Promote the chef domain to first-class status: chefs, public profiles, meal events, offerings, bookings, and payments must be coherent and well-documented.
2. Introduce a chef-facing CRM layer that supports leads, stages, timelines, and simple notes.
3. Ship stable APIs aligned with the upcoming sautai frontend routes (`/chef`, `/chef/services`, `/chef/calendar`, `/chef/leads`, `/chefs`, `/c/:chefSlug`, `/orders`).
4. Retain Stripe/payment plumbing but converge on one clear flow for chef events and service bookings.
5. Contain or retire legacy “AI dietician” functionality so it can be flagged off without destabilizing chef features.

### 1.2 Non-Goals
- Replatforming away from Django/DRF.
- Rewriting every Celery task or excising all LLM usage globally.
- Building advanced analytics—only basic counts and sums are expected.

## 2. Target Architecture
### 2.1 Core Apps & Responsibilities
- `custom_auth`: custom users, roles, addresses, timezone/preferences helpers.
- `chefs`: chef profile, gallery, serving areas, waitlist configuration/subscribe endpoints.
- `meals`: chef meal events, event orders, shared `Order` object for anything transacted.
- `services` (NEW/promoted): chef service offerings & tiers (in-home, weekly prep, catering).
- `crm` (NEW): chef leads, stages, and interactions timeline.

### 2.2 Legacy/Secondary Areas
- `meals.meal_plan_*`, Instacart services, and health/metrics widgets remain but are isolated behind flags and clearly documented as legacy.

### 2.3 Responsibility Split Highlights
- `custom_auth`: ensure `UserRole` drives role checks, addresses expose `is_postalcode_served`, and `CustomUser` exposes `is_chef` plus a public display name/slug.
- `chefs`: keep OneToOne link to `CustomUser`, profile metadata, gallery photos, serving postal codes via `ChefPostalCode`, verification flags, and waitlist models.
- `services`: define `ServiceOffering` + `ServiceTier` models (see §3.3) and endpoints to CRUD offerings for a chef.
- `meals`: narrow focus to chef meal events and chef meal orders, while keeping `Order` as the parent payment object shared with service bookings.
- `crm`: encapsulate leads and interactions, with helper logic to auto-create leads when favorites, waitlists, chats, or first orders happen.

## 3. Domain Model Changes
### 3.1 `custom_auth`
1. Treat `UserRole` as the authoritative source of role data (`is_chef`, `current_role`).
2. Ensure `Address` includes `country`, `input_postalcode`, `display_postalcode`, `city`, plus helper `is_postalcode_served()` that references `ChefPostalCode`.
3. Add a convenience property:
```python
def is_chef(self) -> bool:
    try:
        return self.userrole.current_role == 'chef'
    except UserRole.DoesNotExist:
        return False
```
4. Support a “public name” concept (`username` as default slug, with optional `public_display_name`).

### 3.2 `chefs`
- Confirm `Chef` carries `bio`, `experience`, `profile_pic`, `banner_image`, `serving_postalcodes`, verification flags, and gallery relations (`ChefPhoto`).
- Provide public profile payloads with `id`, `username`, `bio`, `experience`, `city`, `country`, `profile_pic_url`, `banner_url`, `serving_postalcodes`, `review_summary`, and `photos_count`.
- Centralize waitlist logic via `ChefWaitlistConfig` and `ChefWaitlistSubscription`, owned by the `chefs` app.

### 3.3 `services` (NEW)
Create a dedicated app with the following models and nested serializers:
```python
class ServiceOffering(models.Model):
    SERVICE_TYPES = [
        ('home_chef', 'In-home chef'),
        ('weekly_prep', 'Weekly meal prep'),
        ('catering', 'Event catering'),
    ]
    chef = models.ForeignKey('chefs.Chef', on_delete=models.CASCADE, related_name='offerings')
    title = models.CharField(max_length=255)
    service_type = models.CharField(max_length=32, choices=SERVICE_TYPES)
    description = models.TextField(blank=True)
    max_travel_miles = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ServiceTier(models.Model):
    offering = models.ForeignKey(ServiceOffering, on_delete=models.CASCADE, related_name='tiers')
    display_label = models.CharField(max_length=255)
    household_min = models.PositiveIntegerField(default=1)
    household_max = models.PositiveIntegerField(null=True, blank=True)
    desired_unit_amount_cents = models.PositiveIntegerField()
    is_recurring = models.BooleanField(default=False)
    recurrence_interval = models.CharField(max_length=32, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    hidden = models.BooleanField(default=False)
    soft_deleted = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
```
APIs:
- `GET /services/offerings/?chef_id=...`
- `POST /services/offerings/`
- `PATCH /services/offerings/:id/`
- `DELETE /services/offerings/:id/` (soft delete or `active=False`)

### 3.4 `meals`
- Separate group meal events (`ChefMealEvent` + `ChefMealOrder`) from service bookings (future `ServiceOrder` in `services`).
- `ChefMealEvent` is the sole source for meal + chef + event timing + pricing + capacity + status.
- `ChefMealOrder` always links parent `Order`, `meal_event`, `customer`, quantity, `price_paid`, and status.
- Reuse `Order` as the parent Stripe object for both meal events and service bookings (via `ServiceOrder`). Stripe metadata should include `order_type` (`chef_meal` vs `service`).
- Centralize creation of `ChefMealOrder` records (`create_chef_meal_orders(order)` helper) and ensure payment flows go through one path.

## 4. CRM Domain (`crm` App)
- Models:
```python
class Lead(models.Model):
    STAGES = [
        ('new', 'New'),
        ('discovery', 'Discovery'),
        ('proposal', 'Proposal'),
        ('booked', 'Booked'),
        ('follow_up', 'Follow-up'),
    ]
    chef = models.ForeignKey('chefs.Chef', on_delete=models.CASCADE, related_name='leads')
    user = models.ForeignKey('custom_auth.CustomUser', null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    stage = models.CharField(max_length=32, choices=STAGES, default='new')
    source = models.CharField(max_length=32)
    last_activity_at = models.DateTimeField(auto_now=True)
    next_action_at = models.DateTimeField(null=True, blank=True)
    next_action_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class LeadInteraction(models.Model):
    TYPES = [
        ('favorite', 'Favorite'),
        ('waitlist', 'Waitlist'),
        ('message', 'Message'),
        ('order', 'Order'),
        ('note', 'Note'),
    ]
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='interactions')
    type = models.CharField(max_length=32, choices=TYPES)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
```
- Provide helper `create_or_update_lead_for_user(chef, user, source, payload=None)` and trigger it from favorites, waitlists, chef messaging, and first-order events.

## 5. API Contracts for sautai Frontend
### 5.1 `/chef` Dashboard (`GET /chef/api/dashboard/`)
Returns chef profile, key stats (upcoming bookings, active leads, active clients, revenue this week/month), upcoming events summary, actionable alerts, and Stripe onboarding state. Alerts should include codes like `NO_SERVING_AREAS` or `STRIPE_INCOMPLETE`.

### 5.2 `/chef/services`
- `GET /services/offerings/?chef_id=me`
- `POST /services/offerings/`
- `PATCH /services/offerings/:id/`
Nested tiers come back in the offering serializer.

### 5.3 `/chef/calendar`
`GET /meals/api/chef-calendar/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` merges meal events and service bookings:
```json
{
  "events": [
    {
      "type": "meal_event",
      "id": 123,
      "title": "Jerk Chicken Plates",
      "date": "2025-11-20",
      "time": "18:00",
      "orders_count": 7,
      "max_orders": 12,
      "status": "open"
    },
    {
      "type": "service_booking",
      "id": 987,
      "title": "Weekly Prep – 2 adults + 1 child",
      "date": "2025-11-21",
      "time": "10:00",
      "status": "confirmed"
    }
  ]
}
```

### 5.4 `/chef/leads`
- `GET /crm/api/leads/?stage=new`
- `GET /crm/api/leads/:id/`
- `PATCH /crm/api/leads/:id/`
All endpoints enforce chef ownership (`request.user.is_chef`).

### 5.5 Public Chef Directory
- `GET /chefs/api/public/` (list)
- `GET /chefs/api/public/:id/`
- `GET /chefs/api/public/by-username/:username/` (for `/c/:slug` and gallery routes)
Payloads mirror the public profile contract from §3.2.

### 5.6 User Orders (`/orders`)
`GET /meals/api/my-orders/` returns grouped order summaries:
```json
{
  "orders": [
    {
      "id": 1,
      "created_at": "2025-11-20T12:34:56Z",
      "total_amount": 8000,
      "currency": "JPY",
      "is_paid": true,
      "status": "completed",
      "type": "chef_meal",
      "items": [
        {
          "label": "Jerk Chicken Plates – 2 servings",
          "event_date": "2025-11-22",
          "chef": "ChefEmiri"
        }
      ]
    },
    {
      "id": 2,
      "created_at": "2025-11-19T10:00:00Z",
      "total_amount": 24000,
      "is_paid": false,
      "status": "placed",
      "type": "service",
      "items": [
        {
          "label": "Weekly Prep (4 dinners)",
          "service_date": "2025-11-23",
          "chef": "ChefEmiri"
        }
      ]
    }
  ]
}
```
Follow-on endpoint `GET /meals/api/my-orders/:order_id/` can be added later for detail views.

## 6. Migration & Rollout Plan
1. **Phase 0 – Code Audit**: catalog all meal-plan/Instacart/health endpoints & tasks, add `@deprecated` notes and a `LEGACY_MEAL_PLAN = True` flag where applicable.
2. **Phase 1 – New Apps**: scaffold `services` and `crm`, register them in `INSTALLED_APPS`, add initial migrations.
3. **Phase 2 – Chef Domain Cleanup**: move public directory + waitlist endpoints fully under `chefs`, expose `/chefs/api/public/*` routes.
4. **Phase 3 – Calendar & Orders**: implement merged chef calendar endpoint and user `/meals/api/my-orders/` view; keep Stripe webhooks consistent.
5. **Phase 4 – CRM Automations**: wire `create_or_update_lead_for_user` into favorites, waitlists, chef messaging, and order creation; ship DRF serializers + endpoints for leads/interactions.
6. **Phase 5 – Feature Flag Legacy Experiences**: add `SOUTAI_MEAL_PLAN_UI_ENABLED` (or similar) to fully hide `/meal-plans` flows when false while keeping underlying models/tasks available.

## 7. Legacy “Diet App” Cleanup Checklist
- Tag all meal-plan SSE endpoints (`api_generate_meal_plan`, `api_stream_meal_plan_generation`, `api_meal_plan_status`, `api_update_meals_with_prompt`) with `LEGACY_MEAL_PLAN` and note deprecation in docstrings.
- Isolate Instacart integration modules; ensure no new chef code calls them directly.
- Move health metrics widgets and quick-health endpoints behind the same feature flag so chef-first flows never depend on them.
- Document any Celery tasks that exclusively serve legacy flows and ensure they can be turned off separately from chef-related queues.

## 8. Implementation Guidelines
- Keep non-trivial business logic inside service modules (`services/service_logic.py`, `crm/service.py`, `meals/order_service.py`) instead of views.
- Every new endpoint ships with serializers + role-aware permissions (`request.user.is_chef` for chef surfaces, customer auth for `/orders`).
- Stripe/order endpoints should support an `idempotency_key` passed in the request body (avoid header reliance for browsers).
- For each new feature/bugfix, write failing tests first (`pytest` for backend) before implementing changes.
- Coordinate with the sautai React frontend (`/Users/michaeljones/Documents/Projects/Web Development/sautai/sautai-react-frontend`), noting that it will also evolve to this chef-first direction.
