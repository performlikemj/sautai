# sautai iOS App - Project Plan

**Created:** February 4, 2026
**Target:** Chef-first iOS 17+ app with full AI streaming

---

## 1. Project Overview

### Decisions Made
| Decision | Choice |
|----------|--------|
| Primary Focus | Chef-first (dashboard, clients, Sous Chef AI) |
| iOS Version | 17+ (enables SwiftData) |
| AI Streaming | Full token-by-token streaming |
| Design System | 2025 Brand Guide (Earthen Clay palette) |

### Backend Summary
- **Framework:** Django 5.2.11 + Django REST Framework
- **API Endpoints:** 209+ across 11 apps
- **Authentication:** JWT (5-min access / 24-hour refresh tokens)
- **Real-time:** WebSocket messaging via Django Channels
- **AI Integration:** Streaming SSE for Sous Chef assistant

---

## 2. Brand Design System (2025)

### Color Palette

```swift
// Colors.swift
import SwiftUI

extension Color {
    static let sautai = SautaiColors()
}

struct SautaiColors {
    // Primary Palette (2025 Brand Guide)
    let earthenClay = Color(hex: "C96F45")      // Primary - warmth
    let herbGreen = Color(hex: "7B9E72")        // Secondary - renewal
    let softCream = Color(hex: "F8F5EF")        // Background
    let slateTile = Color(hex: "5A5D61")        // Neutral text
    let sunlitApricot = Color(hex: "E9B882")    // Accent
    let clayPotBrown = Color(hex: "8B5E3C")     // Deep accent

    // Logo Colors (constant)
    let logoFlames = Color(hex: "D54930")       // Always red-orange

    // Semantic Colors
    let success = Color(hex: "168516")
    let warning = Color(hex: "B45309")
    let danger = Color(hex: "DC2626")
    let info = Color(hex: "1D4ED8")

    // Dark Mode Variants
    let darkBackground = Color(hex: "1A1A1A")
    let darkSurface = Color(hex: "2D2D2D")
}
```

### Typography

```swift
// Typography.swift
import SwiftUI

enum SautaiFont {
    static func poppins(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .custom("Poppins", size: size).weight(weight)
    }

    static func kalam(_ size: CGFloat) -> Font {
        .custom("Kalam", size: size)  // Handwritten accent
    }

    // Semantic styles
    static let largeTitle = poppins(34, weight: .bold)
    static let title = poppins(28, weight: .semibold)
    static let headline = poppins(17, weight: .semibold)
    static let body = poppins(17)
    static let callout = poppins(16)
    static let caption = poppins(12)
    static let handwritten = kalam(18)  // For quotes, personal touches
}
```

### Design Tokens

```swift
// DesignTokens.swift
enum SautaiDesign {
    static let cornerRadius: CGFloat = 16
    static let cornerRadiusSmall: CGFloat = 8
    static let cornerRadiusLarge: CGFloat = 24

    static let paddingXS: CGFloat = 4
    static let paddingS: CGFloat = 8
    static let paddingM: CGFloat = 16
    static let paddingL: CGFloat = 24
    static let paddingXL: CGFloat = 48  // Brand guide minimum

    static let shadowRadius: CGFloat = 8
    static let shadowOpacity: Double = 0.1

    static let animationDuration: Double = 0.25  // 0.2-0.3s per brand guide
}
```

---

## 3. Technical Architecture

### Project Structure

```
sautai_ios/
├── SautaiApp.swift                    # App entry point
├── Info.plist
│
├── Core/
│   ├── Network/
│   │   ├── APIClient.swift            # URLSession-based networking
│   │   ├── APIEndpoints.swift         # All endpoints mapped
│   │   ├── AuthInterceptor.swift      # JWT token management
│   │   ├── StreamingClient.swift      # SSE for AI responses
│   │   └── WebSocketManager.swift     # Real-time messaging
│   │
│   ├── Auth/
│   │   ├── AuthManager.swift          # Login/logout/token management
│   │   ├── KeychainService.swift      # Secure token storage
│   │   └── BiometricAuth.swift        # Face ID / Touch ID
│   │
│   ├── Models/                        # Codable structs
│   │   ├── User/
│   │   │   ├── User.swift
│   │   │   ├── Address.swift
│   │   │   ├── HouseholdMember.swift
│   │   │   └── UserRole.swift
│   │   ├── Chef/
│   │   │   ├── Chef.swift
│   │   │   ├── ChefPhoto.swift
│   │   │   ├── Lead.swift
│   │   │   └── Client.swift
│   │   ├── Meals/
│   │   │   ├── Meal.swift
│   │   │   ├── MealPlan.swift
│   │   │   ├── Dish.swift
│   │   │   └── Ingredient.swift
│   │   ├── Orders/
│   │   │   ├── Order.swift
│   │   │   └── Cart.swift
│   │   └── Messaging/
│   │       ├── Conversation.swift
│   │       └── Message.swift
│   │
│   ├── Design/
│   │   ├── Colors.swift
│   │   ├── Typography.swift
│   │   ├── DesignTokens.swift
│   │   └── Theme.swift
│   │
│   └── Persistence/
│       ├── SwiftDataManager.swift
│       └── OfflineSyncManager.swift
│
├── Features/
│   ├── Auth/
│   │   ├── LoginView.swift
│   │   ├── RegisterView.swift
│   │   ├── ForgotPasswordView.swift
│   │   └── EmailVerificationView.swift
│   │
│   ├── Onboarding/
│   │   ├── OnboardingFlow.swift
│   │   ├── DietaryPreferencesStep.swift
│   │   └── HouseholdSetupStep.swift
│   │
│   ├── Chef/                          # PRIORITY - Chef-first
│   │   ├── Dashboard/
│   │   │   ├── ChefDashboardView.swift
│   │   │   ├── RevenueStatsCard.swift
│   │   │   └── UpcomingOrdersCard.swift
│   │   ├── Clients/
│   │   │   ├── ClientsListView.swift
│   │   │   ├── ClientDetailView.swift
│   │   │   └── ClientNotesView.swift
│   │   ├── SousChef/                  # AI Assistant
│   │   │   ├── SousChefView.swift
│   │   │   ├── StreamingMessageView.swift
│   │   │   ├── MessageBubble.swift
│   │   │   └── SuggestionCardsView.swift
│   │   ├── MealPlanning/
│   │   │   ├── MealPlansListView.swift
│   │   │   ├── MealPlanEditorView.swift
│   │   │   └── DayPlannerView.swift
│   │   ├── PrepPlanning/
│   │   │   ├── PrepPlansView.swift
│   │   │   └── ShoppingListView.swift
│   │   ├── Leads/
│   │   │   ├── LeadsListView.swift
│   │   │   └── LeadDetailView.swift
│   │   └── Profile/
│   │       ├── ChefProfileView.swift
│   │       └── ServiceAreasView.swift
│   │
│   ├── Customer/                      # PHASE 2
│   │   ├── Dashboard/
│   │   ├── ChefDiscovery/
│   │   ├── MealPlans/
│   │   └── Orders/
│   │
│   ├── Messaging/
│   │   ├── ConversationsListView.swift
│   │   └── ChatView.swift
│   │
│   └── Settings/
│       ├── SettingsView.swift
│       └── ProfileSettingsView.swift
│
├── Components/                        # Reusable UI
│   ├── SautaiButton.swift
│   ├── SautaiCard.swift
│   ├── SautaiTextField.swift
│   ├── LoadingIndicator.swift
│   ├── EmptyStateView.swift
│   └── ErrorView.swift
│
├── Resources/
│   ├── Assets.xcassets/
│   │   ├── Colors/
│   │   ├── AppIcon.appiconset/
│   │   └── Images/
│   ├── Fonts/
│   │   ├── Poppins-Regular.ttf
│   │   ├── Poppins-Medium.ttf
│   │   ├── Poppins-SemiBold.ttf
│   │   ├── Poppins-Bold.ttf
│   │   └── Kalam-Regular.ttf
│   └── Localizable.xcstrings
│
└── Tests/
    ├── NetworkTests/
    ├── AuthTests/
    └── ModelDecodingTests/
```

---

## 4. API Integration Map

### Phase 1: Core Auth (Week 1-2)

| Endpoint | iOS Method | Priority |
|----------|------------|----------|
| `POST /auth/api/login/` | `AuthManager.login()` | P0 |
| `POST /auth/api/token/refresh/` | `AuthInterceptor.refresh()` | P0 |
| `GET /auth/api/user_details/` | `UserService.fetchProfile()` | P0 |
| `POST /auth/api/register/` | `AuthManager.register()` | P1 |
| `POST /auth/api/switch_role/` | `AuthManager.switchRole()` | P1 |

### Phase 2: Chef Dashboard (Week 3-4)

| Endpoint | iOS Method | Priority |
|----------|------------|----------|
| `GET /chefs/api/me/dashboard/` | `ChefService.fetchDashboard()` | P0 |
| `GET /chefs/api/me/clients/` | `ClientService.fetchClients()` | P0 |
| `GET /chefs/api/me/orders/upcoming/` | `OrderService.fetchUpcoming()` | P0 |
| `GET /chefs/api/me/revenue/` | `RevenueService.fetchStats()` | P1 |

### Phase 3: Sous Chef AI (Week 5-6)

| Endpoint | iOS Method | Priority |
|----------|------------|----------|
| `POST /chefs/api/me/sous-chef/stream/` | `SousChefService.streamMessage()` | P0 |
| `POST /chefs/api/me/sous-chef/new-conversation/` | `SousChefService.startConversation()` | P0 |
| `GET /chefs/api/me/sous-chef/history/...` | `SousChefService.fetchHistory()` | P1 |
| `GET /chefs/api/me/sous-chef/suggest/` | `SousChefService.fetchSuggestions()` | P1 |

### Phase 4: Meal Planning (Week 7-8)

| Endpoint | iOS Method | Priority |
|----------|------------|----------|
| `GET /chefs/api/me/plans/` | `MealPlanService.fetchPlans()` | P0 |
| `POST /chefs/api/me/plans/.../days/` | `MealPlanService.addDay()` | P0 |
| `GET /chefs/api/me/prep-plans/` | `PrepPlanService.fetchPlans()` | P1 |

---

## 5. Data Models

### User Model

```swift
struct User: Codable, Identifiable {
    let id: Int
    let username: String
    let email: String
    var phoneNumber: String?
    var emailConfirmed: Bool
    var preferredLanguage: String
    var timezone: String
    var measurementSystem: MeasurementSystem
    var dietaryPreferences: [DietaryPreference]
    var allergies: [String]
    var customAllergies: [String]
    var householdMemberCount: Int
    var householdMembers: [HouseholdMember]
    var autoMealPlansEnabled: Bool
    var isChef: Bool
    var currentRole: UserRole
    var address: Address?

    enum MeasurementSystem: String, Codable {
        case us = "US"
        case metric = "METRIC"
    }

    enum UserRole: String, Codable {
        case chef
        case customer
    }
}
```

### Chef Dashboard Model

```swift
struct ChefDashboard: Codable {
    let revenue: RevenueStats
    let clients: ClientStats
    let orders: OrderStats
    let topServices: [TopService]
}

struct RevenueStats: Codable {
    let today: Decimal
    let thisWeek: Decimal
    let thisMonth: Decimal
}

struct ClientStats: Codable {
    let total: Int
    let active: Int
    let newThisMonth: Int
}

struct OrderStats: Codable {
    let upcoming: Int
    let pendingConfirmation: Int
    let completedThisMonth: Int
}
```

### Sous Chef Message (Streaming)

```swift
struct SousChefMessage: Identifiable {
    let id: UUID
    var content: String
    let role: MessageRole
    var isStreaming: Bool
    let timestamp: Date

    enum MessageRole: String, Codable {
        case user
        case assistant
    }
}
```

---

## 6. Authentication Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         iOS App                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    POST /auth/api/login/     ┌──────────────────┐ │
│  │  Login   │ ─────────────────────────▶  │ Django Backend   │ │
│  │  View    │ ◀─────────────────────────  │                  │ │
│  └──────────┘   {access, refresh tokens}   └──────────────────┘ │
│       │                                                          │
│       ▼                                                          │
│  ┌──────────────────┐                                           │
│  │ Keychain Storage │                                           │
│  │ - access_token   │ (also in-memory for speed)               │
│  │ - refresh_token  │ (secure storage only)                    │
│  └──────────────────┘                                           │
│       │                                                          │
│       ▼                                                          │
│  ┌──────────────────┐                                           │
│  │ Auth Interceptor │                                           │
│  │ - Injects token  │                                           │
│  │ - Auto-refresh   │ (on 401, before retry)                   │
│  └──────────────────┘                                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

Token Lifecycle:
- Access token: 5 minutes (in-memory + Keychain)
- Refresh token: 24 hours (Keychain only)
- Auto-refresh: Triggered on 401, retries original request
```

---

## 7. Streaming Implementation

### SSE Client for Sous Chef

```swift
class StreamingClient {
    func streamMessage(
        endpoint: String,
        body: Data,
        onChunk: @escaping (String) -> Void,
        onComplete: @escaping () -> Void,
        onError: @escaping (Error) -> Void
    ) async {
        var request = URLRequest(url: URL(string: endpoint)!)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        let (bytes, _) = try await URLSession.shared.bytes(for: request)

        for try await line in bytes.lines {
            if line.hasPrefix("data: ") {
                let chunk = String(line.dropFirst(6))
                await MainActor.run { onChunk(chunk) }
            }
        }

        await MainActor.run { onComplete() }
    }
}
```

---

## 8. Development Phases

### Phase 1: Foundation (Weeks 1-2)
- [ ] Create Xcode project with folder structure
- [ ] Set up design system (colors, fonts, tokens)
- [ ] Implement APIClient with auth interceptor
- [ ] Build login/register flows
- [ ] Set up SwiftData for caching

### Phase 2: Chef Dashboard (Weeks 3-4)
- [ ] Dashboard main view with stats cards
- [ ] Revenue breakdown view
- [ ] Clients list with search
- [ ] Upcoming orders list

### Phase 3: Sous Chef AI (Weeks 5-6)
- [ ] Chat interface with message bubbles
- [ ] SSE streaming integration
- [ ] Conversation history
- [ ] Suggestion cards

### Phase 4: Meal Planning (Weeks 7-8)
- [ ] Meal plans list
- [ ] Plan editor with day view
- [ ] Prep plans and shopping list
- [ ] Client meal suggestions

### Phase 5: Polish & Customer (Weeks 9-12)
- [ ] Customer role screens
- [ ] Push notifications
- [ ] Offline support
- [ ] TestFlight beta

---

## 9. Dependencies

### Required
- **SwiftData** - Local persistence (iOS 17+)
- **Keychain Services** - Secure token storage

### Optional (Evaluate)
- **Poppins Font Bundle** - Custom typography
- **Kalam Font Bundle** - Handwritten accents

### No External Dependencies For
- Networking (native URLSession)
- JSON decoding (native Codable)
- WebSocket (native URLSessionWebSocketTask)

---

## 10. Files to Copy from Django

| Source | Destination | Purpose |
|--------|-------------|---------|
| `frontend/public/sautai_logo_new.svg` | `Assets.xcassets` | App logo (light) |
| `frontend/public/sautai_logo_new_dark.svg` | `Assets.xcassets` | App logo (dark) |
| `frontend/public/sautai_logo_transparent_800.png` | `AppIcon.appiconset` | App icon base |

---

*This plan was generated based on analysis of the Django backend and the sautai Brand Guide 2025 Update.*
