# MeHKO Chef Dashboard Demo — Video Recording Guide

## Overview

- **Target audience:** California MeHKO (Microenterprise Home Kitchen Operations) home kitchen chefs
- **Goal:** Show how sautai replaces spreadsheets, separate invoicing tools, and manual compliance tracking
- **Estimated runtime:** ~6 minutes
- **Tone:** Conversational, practical, not salesy

## Pre-Recording Setup

1. Populate demo data:
   ```bash
   python manage.py shell < scripts/populate_mehko_demo_data.py
   ```
2. Start servers:
   ```bash
   python manage.py runserver  # Terminal 1
   cd frontend && npm start     # Terminal 2
   ```
3. Log in as `chef_maria` / `mehkodemo2026`
4. Browser: 1920x1080, light theme, close other tabs
5. Sous Chef widget: dismiss any welcome tooltips before recording

## Narrative Arc

**Opening (0:00-0:30):** The problem — you have your permit, you're cooking incredible food, but tracking compliance, managing clients, and handling payments is scattered across spreadsheets, texts, and Venmo.

**Walkthrough (0:30-5:00):** Dashboard tour showing each feature solves a real pain point.

**Proof (5:00-6:00):** Insights tab showing 90 days of growth — real business momentum, under MeHKO caps.

---

## Walkthrough Scenes

### Scene 1: Today Dashboard (0:30 — 30s)

**What to show:** Click "Today" in the sidebar (should be the default view). Show the quick stats banner: pending orders, unread messages, client requests. Scroll to the upcoming orders section (next 48 hours).

**What to click/hover:** Quick stats banner cards, upcoming order cards.

**Talking points:**
- "This is your command center. Every morning, open this and you know exactly what needs your attention."
- "Upcoming orders, messages from clients, pending requests — all in one place."

**Key pause moment:** Linger on the upcoming orders cards so the viewer can read the order details and timing.

---

### Scene 2: Home Kitchen (1:00 — 30s)

**What to show:** Click "Home Kitchen" in the sidebar. Show MeHKO permit info (permit number, agency, expiry date) and food handler certification status.

**What to click/hover:** Permit details card, certification status badges, insurance section.

**Talking points:**
- "Your MeHKO permit details, food handler cert, insurance — all tracked here."
- "No more digging through emails to find your permit number when a customer asks."
- "Expiry dates are tracked so you get reminded before anything lapses."

**Key pause moment:** Linger on the permit details section showing the permit number and expiry date.

---

### Scene 3: My Profile (1:30 — 20s)

**What to show:** Click "My Profile" in the sidebar. Show bio, profile photo area, banner image. Briefly click into the Photos sub-tab.

**What to click/hover:** Bio text area, Photos sub-tab.

**Talking points:**
- "This is what customers see when they find you on the platform."
- "Your story, your photos, your brand."

**Key pause moment:** Linger on the bio section where the chef's personal story is displayed.

---

### Scene 4: Menu Builder (1:50 — 45s)

**What to show:** Click "Menu Builder" in the sidebar. Start on the Ingredients sub-tab and scroll through culturally diverse ingredients with nutrition data. Switch to the Dishes sub-tab and show a dish like "Black Bean & Sweet Potato Bowl" with auto-calculated nutrition. Switch to the Meals sub-tab and show meals with pricing ($12-$25 range).

**What to click/hover:** Ingredients sub-tab, Dishes sub-tab, a specific dish card to expand nutrition, Meals sub-tab, meal price display.

**Talking points:**
- "Build your menu from ingredients up. Add your tamale masa, your jollof spices, your lumpia wrappers."
- "Nutrition is calculated automatically when you build a dish — calories, protein, fat, carbs."
- "This matters when your clients have diabetes, heart conditions, or specific dietary needs. You can show them exactly what's in their food."

**Key pause moment:** Linger on a dish showing the calculated nutrition breakdown (calories, protein, fat, carbs).

---

### Scene 5: Services & Pricing (2:35 — 30s)

**What to show:** Click "Services" in the sidebar. Show the "Weekly Meal Prep" offering with household-size tiers. Show the "Single Meal Order" offering.

**What to click/hover:** "Weekly Meal Prep" service card, price tier table, "Single Meal Order" card.

**Talking points:**
- "Set up your service offerings with tiered pricing by household size."
- "A family of 5 pays differently than a couple — you set the price once and it just works."

**Key pause moment:** Linger on the price tier table showing the household size ranges and corresponding prices.

---

### Scene 6: Clients (3:05 — 45s)

**What to show:** Click "Clients" in the sidebar. Show the platform customer list with connection statuses. Click into a client to show dietary preferences (Diabetic-Friendly, Low-Sodium). Show household members with their individual dietary needs. Switch to the CRM/leads view to show community referrals.

**What to click/hover:** A client row to expand details, dietary preference tags, household members section, CRM tab or toggle.

**Talking points:**
- "Every client's dietary needs, allergies, and household members — right here."
- "Rosa's husband is diabetic, Mei's mother needs low-sodium. You never have to ask twice."
- "And for people who aren't on the platform yet — your community referrals, farmers market contacts — track them in the CRM."

**Key pause moment:** Linger on the household member dietary details showing individual needs per family member.

---

### Scene 7: Meal Shares (3:50 — 30s)

**What to show:** Click "Services" then the Meal Shares sub-tab. Show upcoming and past meal share events. Point out the dynamic pricing (base price to current price as orders increase).

**What to click/hover:** Meal Shares sub-tab, an upcoming event card, the price display showing the drop.

**Talking points:**
- "Meal Shares are community meal events. You pick a meal, set a date, and neighbors can order."
- "The more people order, the lower the price goes for everyone. It's group buying for home-cooked food."

**Key pause moment:** Linger on a meal event showing the price drop from accumulated orders.

---

### Scene 8: Orders (4:20 — 20s)

**What to show:** Click "Orders" in the sidebar. Show the unified order view with both service orders and meal share orders. Use the search/filter controls to show specific statuses.

**What to click/hover:** Status filter dropdown, search bar, an individual order row.

**Talking points:**
- "All your orders in one view — weekly prep clients and meal share customers together."
- "Filter by status, search by name. No more scrolling through texts."

**Key pause moment:** Linger on the order list showing a mix of service orders and meal share orders.

---

### Scene 9: Payment Links (4:40 — 30s)

**What to show:** Click "Payment Links" in the sidebar. Show the list with paid/pending/draft statuses. Point out the stats summary (total value sent, completed).

**What to click/hover:** Status badges (paid, pending, draft), stats summary area, an individual payment link row.

**Talking points:**
- "Create a payment link, send it by email. That's it. No Venmo, no cash, no chasing people."
- "Stripe handles the payment. You see exactly what's been paid and what's pending."

**Key pause moment:** Linger on a paid payment link showing the amount and confirmation status.

---

### Scene 10: Prep Planning (5:10 — 30s)

**What to show:** Click "Prep Planning" in the sidebar. Show the shopping list grouped by purchase date. Point out timing badges: "optimal" (pantry items), "tight" (refrigerated), "problematic" (fresh fish).

**What to click/hover:** Shopping list date groups, timing badges, individual ingredient rows with shelf life info.

**Talking points:**
- "Smart shopping lists that know shelf life. Masa harina? Buy it anytime — it's pantry."
- "Salmon? The system knows it only lasts 2 days. It tells you to buy it the day before you cook."
- "No more throwing away food because you bought it too early."

**Key pause moment:** Linger on a "problematic" or "tight" timing badge item to let the viewer read the shelf life reasoning.

---

### Scene 11: Insights (5:40 — 45s)

**What to show:** Click "Insights" in the sidebar. Show the revenue chart over 90 days (select 90d range) — should show an upward trend. Show the order breakdown (meal vs service pie chart). Show new clients trend. Show top services.

**What to click/hover:** 90-day range selector, revenue chart, order breakdown pie chart, new clients trend line, top services list.

**Talking points:**
- "Three months of running your kitchen through sautai. Look at that growth."
- "Revenue trending up, new clients coming in, and you can see exactly which services are driving your business."
- "Most importantly — you're well under your MeHKO annual cap. You know exactly how much room you have."

**Key pause moment:** Linger on the revenue trend chart showing growth over the 90-day period.

---

### Scene 12: Surveys (6:25 — 20s)

**What to show:** Click "Surveys" in the sidebar. Show a completed survey with response analytics (star ratings).

**What to click/hover:** A completed survey row, star rating breakdown, individual response entries.

**Talking points:**
- "After every meal share, send a quick survey. See what people loved, what to improve."
- "4.7 stars average — that's the kind of feedback that builds word of mouth."

**Key pause moment:** Linger on the survey results showing star averages and response counts.

---

### Scene 13: Sous Chef AI (6:45 — 30s)

**What to show:** Click the Sous Chef widget (bottom-right floating button). Show the AI chat interface.

**What to click/hover:** Floating Sous Chef button, chat input field, any example prompts displayed.

**Talking points:**
- "And when you need help — 'What can I make for a diabetic client this week?' or 'Do I have enough capacity for 5 more Friday orders?'"
- "Your AI sous chef knows your menu, your clients, and your schedule."

**Key pause moment:** Linger on the chat interface open and visible, letting the viewer absorb the AI assistant concept.

---

### Scene 14: Closing (7:15 — 15s)

**What to show:** Navigate back to the Today dashboard.

**What to click/hover:** "Today" in the sidebar.

**Talking points:**
- "This is sautai. Your home kitchen business — organized, compliant, and growing."
- "If you're interested, [call to action — schedule a demo, sign up, etc.]"

---

## Post-Recording Tips

- **Edit out loading spinners** — trim any network delays in post-production
- **Add zoom callouts** for small details like nutrition numbers or timing badges
- **Background music** — something warm and kitchen-adjacent, low volume
- **Captions** — add subtitles for accessibility and since many people watch videos muted
- **Thumbnail** — use the Insights chart showing growth, or the Today dashboard

## Key Messages to Reinforce Throughout

1. **Compliance is automatic** — no spreadsheets, no manual tracking
2. **You know your clients** — dietary needs, household members, allergies
3. **Payments are simple** — Stripe links, no Venmo or cash
4. **Your business is growing** — real analytics, visible trends
5. **Community-driven** — meal shares, group pricing, customer feedback
6. **AI-powered** — Sous Chef helps with planning and client management
