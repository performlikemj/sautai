//
//  ChefDashboardView.swift
//  sautai_ios
//
//  Main dashboard for chef users showing revenue, clients, and orders.
//

import SwiftUI

struct ChefDashboardView: View {
    @State private var dashboard: ChefDashboard?
    @State private var isLoading = true
    @State private var error: Error?

    // Quick action navigation
    @State private var showingAddLead = false
    @State private var showingSousChef = false
    @State private var selectedTab: Int = 0

    var body: some View {
        NavigationStack {
            ScrollView {
                if isLoading {
                    loadingView
                } else if let dashboard = dashboard {
                    dashboardContent(dashboard)
                } else if let error = error {
                    errorView(error)
                }
            }
            .background(Color.sautai.softCream)
            .navigationTitle("Dashboard")
            .refreshable {
                await loadDashboard()
            }
            .sheet(isPresented: $showingAddLead) {
                AddLeadView { _ in
                    // Refresh dashboard after adding lead
                    Task { await loadDashboard() }
                }
            }
            .sheet(isPresented: $showingSousChef) {
                SousChefView()
            }
        }
        .task {
            await loadDashboard()
        }
    }

    // MARK: - Dashboard Content

    @ViewBuilder
    private func dashboardContent(_ dashboard: ChefDashboard) -> some View {
        VStack(spacing: SautaiDesign.spacingL) {
            // Greeting
            greetingSection

            // Revenue Cards
            revenueSection(dashboard.revenue)

            // Quick Stats
            quickStatsSection(dashboard)

            // Top Services
            if !dashboard.topServices.isEmpty {
                topServicesSection(dashboard.topServices)
            }

            // Recent Orders
            if let recentOrders = dashboard.recentOrders, !recentOrders.isEmpty {
                recentOrdersSection(recentOrders)
            }

            // Upcoming Events
            if let upcomingEvents = dashboard.upcomingEvents, !upcomingEvents.isEmpty {
                upcomingEventsSection(upcomingEvents)
            }

            // Quick Actions
            quickActionsSection
        }
        .padding(SautaiDesign.spacing)
    }

    // MARK: - Greeting Section

    private var greetingSection: some View {
        HStack {
            VStack(alignment: .leading, spacing: SautaiDesign.spacingXS) {
                Text(greetingText)
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile.opacity(0.7))

                Text("Ready to cook?")
                    .font(SautaiFont.title2)
                    .foregroundColor(.sautai.slateTile)
            }

            Spacer()

            // Profile avatar placeholder
            Circle()
                .fill(Color.sautai.earthenClay.opacity(0.2))
                .frame(width: SautaiDesign.avatarSizeL, height: SautaiDesign.avatarSizeL)
                .overlay(
                    Image(systemName: "person.fill")
                        .foregroundColor(.sautai.earthenClay)
                )
        }
        .padding(.bottom, SautaiDesign.spacingS)
    }

    private var greetingText: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 0..<12: return "Good morning"
        case 12..<17: return "Good afternoon"
        default: return "Good evening"
        }
    }

    // MARK: - Revenue Section

    private func revenueSection(_ revenue: RevenueStats) -> some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            Text("Revenue")
                .font(SautaiFont.headline)
                .foregroundColor(.sautai.slateTile)

            HStack(spacing: SautaiDesign.spacingM) {
                revenueCard(title: "Today", amount: revenue.today, color: .sautai.earthenClay)
                revenueCard(title: "This Week", amount: revenue.thisWeek, color: .sautai.herbGreen)
                revenueCard(title: "This Month", amount: revenue.thisMonth, color: .sautai.sunlitApricot)
            }
        }
    }

    private func revenueCard(title: String, amount: Decimal, color: Color) -> some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingXS) {
            Text(title)
                .font(SautaiFont.caption)
                .foregroundColor(.sautai.slateTile.opacity(0.7))

            Text(formatCurrency(amount))
                .font(SautaiFont.money)
                .foregroundColor(color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(SautaiDesign.spacing)
        .background(Color.white)
        .cornerRadius(SautaiDesign.cornerRadius)
        .sautaiShadow(SautaiDesign.shadowSubtle)
    }

    private func formatCurrency(_ value: Decimal) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.maximumFractionDigits = 0
        return formatter.string(from: value as NSDecimalNumber) ?? "$0"
    }

    // MARK: - Quick Stats Section

    private func quickStatsSection(_ dashboard: ChefDashboard) -> some View {
        HStack(spacing: SautaiDesign.spacingM) {
            statCard(
                icon: "person.2.fill",
                value: "\(dashboard.clients.total)",
                label: "Clients",
                color: .sautai.herbGreen
            )

            statCard(
                icon: "clock.fill",
                value: "\(dashboard.orders.upcoming)",
                label: "Upcoming",
                color: .sautai.sunlitApricot
            )

            statCard(
                icon: "checkmark.circle.fill",
                value: "\(dashboard.orders.completedThisMonth)",
                label: "Completed",
                color: .sautai.earthenClay
            )
        }
    }

    private func statCard(icon: String, value: String, label: String, color: Color) -> some View {
        VStack(spacing: SautaiDesign.spacingS) {
            Image(systemName: icon)
                .font(.system(size: 24))
                .foregroundColor(color)

            Text(value)
                .font(SautaiFont.title2)
                .foregroundColor(.sautai.slateTile)

            Text(label)
                .font(SautaiFont.caption)
                .foregroundColor(.sautai.slateTile.opacity(0.7))
        }
        .frame(maxWidth: .infinity)
        .padding(SautaiDesign.spacing)
        .background(Color.white)
        .cornerRadius(SautaiDesign.cornerRadius)
        .sautaiShadow(SautaiDesign.shadowSubtle)
    }

    // MARK: - Top Services Section

    private func topServicesSection(_ services: [TopService]) -> some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            Text("Top Services")
                .font(SautaiFont.headline)
                .foregroundColor(.sautai.slateTile)

            VStack(spacing: SautaiDesign.spacingS) {
                ForEach(services.prefix(3)) { service in
                    HStack {
                        Text(service.name)
                            .font(SautaiFont.body)
                            .foregroundColor(.sautai.slateTile)

                        Spacer()

                        Text("\(service.orderCount) orders")
                            .font(SautaiFont.caption)
                            .foregroundColor(.sautai.slateTile.opacity(0.7))
                    }
                    .padding(SautaiDesign.spacing)
                    .background(Color.white)
                    .cornerRadius(SautaiDesign.cornerRadiusS)
                }
            }
        }
    }

    // MARK: - Recent Orders Section

    private func recentOrdersSection(_ orders: [Order]) -> some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            HStack {
                Text("Recent Orders")
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile)

                Spacer()

                NavigationLink("See All") {
                    OrdersListView()
                }
                .font(SautaiFont.caption)
                .foregroundColor(.sautai.earthenClay)
            }

            VStack(spacing: SautaiDesign.spacingS) {
                ForEach(orders.prefix(3)) { order in
                    OrderRowView(order: order)
                }
            }
        }
    }

    // MARK: - Upcoming Events Section

    private func upcomingEventsSection(_ events: [ChefMealEvent]) -> some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            HStack {
                Text("Upcoming Events")
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile)

                Spacer()

                NavigationLink("See All") {
                    MealEventsListView()
                }
                .font(SautaiFont.caption)
                .foregroundColor(.sautai.earthenClay)
            }

            VStack(spacing: SautaiDesign.spacingS) {
                ForEach(events.prefix(3)) { event in
                    EventRowView(event: event)
                }
            }
        }
    }

    // MARK: - Quick Actions Section

    private var quickActionsSection: some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            Text("Quick Actions")
                .font(SautaiFont.headline)
                .foregroundColor(.sautai.slateTile)

            HStack(spacing: SautaiDesign.spacingM) {
                actionButton(icon: "plus.circle.fill", label: "New Lead", color: .sautai.earthenClay) {
                    showingAddLead = true
                }
                actionButton(icon: "bubble.left.and.bubble.right.fill", label: "Sous Chef", color: .sautai.herbGreen) {
                    showingSousChef = true
                }
                actionButton(icon: "person.2.fill", label: "Clients", color: .sautai.sunlitApricot) {
                    // Navigate to Clients tab (index 3)
                    NotificationCenter.default.post(name: .switchToTab, object: 3)
                }
            }
        }
    }

    private func actionButton(icon: String, label: String, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: SautaiDesign.spacingS) {
                Image(systemName: icon)
                    .font(.system(size: 28))
                    .foregroundColor(color)

                Text(label)
                    .font(SautaiFont.caption)
                    .foregroundColor(.sautai.slateTile)
            }
            .frame(maxWidth: .infinity)
            .padding(SautaiDesign.spacing)
            .background(Color.white)
            .cornerRadius(SautaiDesign.cornerRadius)
            .sautaiShadow(SautaiDesign.shadowSubtle)
        }
    }

    // MARK: - Loading View

    private var loadingView: some View {
        VStack(spacing: SautaiDesign.spacingL) {
            ProgressView()
                .scaleEffect(1.5)

            Text("Loading dashboard...")
                .font(SautaiFont.body)
                .foregroundColor(.sautai.slateTile.opacity(0.7))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.top, 100)
    }

    // MARK: - Error View

    private func errorView(_ error: Error) -> some View {
        VStack(spacing: SautaiDesign.spacingL) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48))
                .foregroundColor(.sautai.warning)

            Text("Something went wrong")
                .font(SautaiFont.headline)
                .foregroundColor(.sautai.slateTile)

            Text(error.localizedDescription)
                .font(SautaiFont.body)
                .foregroundColor(.sautai.slateTile.opacity(0.7))
                .multilineTextAlignment(.center)

            Button("Try Again") {
                Task { await loadDashboard() }
            }
            .font(SautaiFont.button)
            .foregroundColor(.white)
            .padding(.horizontal, SautaiDesign.spacingXL)
            .padding(.vertical, SautaiDesign.spacingM)
            .background(Color.sautai.earthenClay)
            .cornerRadius(SautaiDesign.cornerRadius)
        }
        .padding(SautaiDesign.spacingXL)
    }

    // MARK: - Data Loading

    private func loadDashboard() async {
        isLoading = true
        error = nil

        do {
            dashboard = try await APIClient.shared.getChefDashboard()
        } catch {
            self.error = error
        }

        isLoading = false
    }
}

// MARK: - Event Row View

struct EventRowView: View {
    let event: ChefMealEvent

    var body: some View {
        HStack(spacing: SautaiDesign.spacingM) {
            // Calendar Icon
            VStack(spacing: 2) {
                Text(monthString)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(.sautai.earthenClay)
                Text(dayString)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(.sautai.slateTile)
            }
            .frame(width: 40, height: 40)
            .background(Color.sautai.earthenClay.opacity(0.1))
            .cornerRadius(SautaiDesign.cornerRadiusS)

            // Event Details
            VStack(alignment: .leading, spacing: SautaiDesign.spacingXS) {
                Text(event.title)
                    .font(SautaiFont.body)
                    .foregroundColor(.sautai.slateTile)
                    .lineLimit(1)

                HStack(spacing: SautaiDesign.spacingS) {
                    if let time = event.eventTime {
                        Text(time)
                            .font(SautaiFont.caption)
                            .foregroundColor(.sautai.slateTile.opacity(0.7))
                    }

                    if let available = event.availableServings {
                        Text("•")
                            .foregroundColor(.sautai.slateTile.opacity(0.5))
                        Text("\(available) spots left")
                            .font(SautaiFont.caption)
                            .foregroundColor(available <= 3 ? .sautai.warning : .sautai.slateTile.opacity(0.7))
                    }
                }
            }

            Spacer()

            // Price
            Text(event.displayPrice)
                .font(SautaiFont.caption)
                .foregroundColor(.sautai.herbGreen)
        }
        .padding(SautaiDesign.spacing)
        .background(Color.white)
        .cornerRadius(SautaiDesign.cornerRadiusS)
        .sautaiShadow(SautaiDesign.shadowSubtle)
    }

    private var monthString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM"
        return formatter.string(from: event.eventDate).uppercased()
    }

    private var dayString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "d"
        return formatter.string(from: event.eventDate)
    }
}

// MARK: - Preview

#Preview {
    ChefDashboardView()
}
