//
//  ClientsListView.swift
//  sautai_ios
//
//  List of chef's clients with search and filtering.
//

import SwiftUI

struct ClientsListView: View {
    @State private var clients: [Client] = []
    @State private var searchText = ""
    @State private var isLoading = true
    @State private var error: Error?
    @State private var showingAddLeadSheet = false

    var filteredClients: [Client] {
        if searchText.isEmpty {
            return clients
        }
        return clients.filter { client in
            client.displayName.localizedCaseInsensitiveContains(searchText) ||
            (client.email?.localizedCaseInsensitiveContains(searchText) ?? false) ||
            (client.username?.localizedCaseInsensitiveContains(searchText) ?? false)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    loadingView
                } else if clients.isEmpty {
                    emptyView
                } else {
                    clientsList
                }
            }
            .background(Color.sautai.softCream)
            .navigationTitle("Clients")
            .searchable(text: $searchText, prompt: "Search clients")
            .refreshable {
                await loadClients()
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        showingAddLeadSheet = true
                    } label: {
                        Image(systemName: "person.badge.plus")
                            .foregroundColor(.sautai.earthenClay)
                    }
                }
            }
            .sheet(isPresented: $showingAddLeadSheet) {
                AddLeadView { _ in
                    // Lead added - they'll become a client when they convert
                }
            }
        }
        .task {
            await loadClients()
        }
    }

    // MARK: - Clients List

    private var clientsList: some View {
        List {
            ForEach(filteredClients) { client in
                NavigationLink {
                    ClientDetailView(client: client)
                } label: {
                    ClientRowView(client: client)
                }
                .listRowBackground(Color.white)
                .listRowSeparator(.hidden)
                .listRowInsets(EdgeInsets(
                    top: SautaiDesign.spacingS,
                    leading: SautaiDesign.spacing,
                    bottom: SautaiDesign.spacingS,
                    trailing: SautaiDesign.spacing
                ))
            }
        }
        .listStyle(.plain)
    }

    // MARK: - Loading View

    private var loadingView: some View {
        VStack(spacing: SautaiDesign.spacingL) {
            ProgressView()
            Text("Loading clients...")
                .font(SautaiFont.body)
                .foregroundColor(.sautai.slateTile.opacity(0.7))
        }
    }

    // MARK: - Empty View

    private var emptyView: some View {
        VStack(spacing: SautaiDesign.spacingL) {
            Image(systemName: "person.2.slash")
                .font(.system(size: 48))
                .foregroundColor(.sautai.slateTile.opacity(0.5))

            Text("No clients yet")
                .font(SautaiFont.headline)
                .foregroundColor(.sautai.slateTile)

            Text("Clients appear here once leads convert to paying customers. Start by adding leads to your pipeline.")
                .font(SautaiFont.body)
                .foregroundColor(.sautai.slateTile.opacity(0.7))
                .multilineTextAlignment(.center)

            Button {
                showingAddLeadSheet = true
            } label: {
                Label("Add Lead", systemImage: "person.badge.plus")
                    .font(SautaiFont.button)
                    .foregroundColor(.white)
                    .padding(.horizontal, SautaiDesign.spacingXL)
                    .padding(.vertical, SautaiDesign.spacingM)
                    .background(Color.sautai.earthenClay)
                    .cornerRadius(SautaiDesign.cornerRadius)
            }

            NavigationLink {
                LeadsListView()
            } label: {
                Text("View Leads")
                    .font(SautaiFont.button)
                    .foregroundColor(.sautai.earthenClay)
            }
        }
        .padding(SautaiDesign.spacingXL)
    }

    // MARK: - Data Loading

    private func loadClients() async {
        isLoading = true
        do {
            let response = try await APIClient.shared.getClients()
            clients = response.results
        } catch {
            self.error = error
        }
        isLoading = false
    }
}

// MARK: - Client Row View

struct ClientRowView: View {
    let client: Client

    var body: some View {
        HStack(spacing: SautaiDesign.spacingM) {
            // Avatar
            Circle()
                .fill(Color.sautai.herbGreen.opacity(0.2))
                .frame(width: SautaiDesign.avatarSize, height: SautaiDesign.avatarSize)
                .overlay(
                    Text(client.initials)
                        .font(SautaiFont.caption)
                        .fontWeight(.semibold)
                        .foregroundColor(.sautai.herbGreen)
                )

            // Info
            VStack(alignment: .leading, spacing: SautaiDesign.spacingXXS) {
                Text(client.displayName)
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile)

                if let email = client.email {
                    Text(email)
                        .font(SautaiFont.caption)
                        .foregroundColor(.sautai.slateTile.opacity(0.7))
                }
            }

            Spacer()

            // Order count
            if let orders = client.totalOrders, orders > 0 {
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(orders)")
                        .font(SautaiFont.headline)
                        .foregroundColor(.sautai.earthenClay)
                    Text("orders")
                        .font(SautaiFont.caption2)
                        .foregroundColor(.sautai.slateTile.opacity(0.5))
                }
            }
        }
        .padding(SautaiDesign.spacing)
        .background(Color.white)
        .cornerRadius(SautaiDesign.cornerRadius)
        .sautaiShadow(SautaiDesign.shadowSubtle)
    }
}

// MARK: - Client Detail View

struct ClientDetailView: View {
    let client: Client

    @State private var notes: [ClientNote] = []
    @State private var isLoadingNotes = true
    @State private var showingAddNote = false
    @State private var showingSousChef = false
    @State private var receipts: [ExpenseReceipt] = []
    @State private var receiptTotals: ReceiptTotals?
    @State private var isLoadingReceipts = true

    var body: some View {
        ScrollView {
            VStack(spacing: SautaiDesign.spacingL) {
                // Header Card
                headerCard

                // Quick Actions
                quickActionsRow

                // Stats
                statsRow

                // Connection Info
                connectionInfoSection

                // Notes Section
                notesSection

                // Receipts Section
                receiptsSection
            }
            .padding(SautaiDesign.spacing)
        }
        .background(Color.sautai.softCream)
        .navigationTitle("Client Details")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    if let email = client.email {
                        Button {
                            sendEmail(email)
                        } label: {
                            Label("Email", systemImage: "envelope")
                        }
                    }

                    Button {
                        showingAddNote = true
                    } label: {
                        Label("Add Note", systemImage: "note.text.badge.plus")
                    }

                    Button {
                        showingSousChef = true
                    } label: {
                        Label("Ask Sous Chef", systemImage: "sparkles")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                        .foregroundColor(.sautai.earthenClay)
                }
            }
        }
        .sheet(isPresented: $showingAddNote) {
            AddClientNoteView(clientId: client.id) { newNote in
                notes.insert(newNote, at: 0)
            }
        }
        .sheet(isPresented: $showingSousChef) {
            SousChefView()
        }
        .task {
            await loadNotes()
            await loadReceipts()
        }
    }

    // MARK: - Header Card

    private var headerCard: some View {
        VStack(spacing: SautaiDesign.spacingM) {
            Circle()
                .fill(Color.sautai.herbGreen.opacity(0.2))
                .frame(width: 80, height: 80)
                .overlay(
                    Text(client.initials)
                        .font(SautaiFont.title)
                        .foregroundColor(.sautai.herbGreen)
                )

            Text(client.displayName)
                .font(SautaiFont.title2)
                .foregroundColor(.sautai.slateTile)

            if let email = client.email {
                Button {
                    sendEmail(email)
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "envelope.fill")
                            .font(.system(size: 12))
                        Text(email)
                    }
                    .font(SautaiFont.body)
                    .foregroundColor(.sautai.earthenClay)
                }
            }

            if let since = client.connectedSince {
                Text("Client since \(since.formatted(date: .abbreviated, time: .omitted))")
                    .font(SautaiFont.caption)
                    .foregroundColor(.sautai.slateTile.opacity(0.6))
            }
        }
        .frame(maxWidth: .infinity)
        .padding(SautaiDesign.spacingL)
        .background(Color.white)
        .cornerRadius(SautaiDesign.cornerRadius)
        .sautaiShadow(SautaiDesign.shadowSubtle)
    }

    // MARK: - Quick Actions

    private var quickActionsRow: some View {
        HStack(spacing: SautaiDesign.spacingM) {
            if let email = client.email {
                actionButton(icon: "envelope.fill", label: "Email") {
                    sendEmail(email)
                }
            }

            actionButton(icon: "note.text.badge.plus", label: "Note") {
                showingAddNote = true
            }

            actionButton(icon: "sparkles", label: "Sous Chef") {
                showingSousChef = true
            }
        }
    }

    private func actionButton(icon: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: SautaiDesign.spacingXS) {
                Image(systemName: icon)
                    .font(.system(size: 20))
                    .foregroundColor(.sautai.earthenClay)
                Text(label)
                    .font(SautaiFont.caption)
                    .foregroundColor(.sautai.slateTile)
            }
            .frame(maxWidth: .infinity)
            .padding(SautaiDesign.spacingM)
            .background(Color.white)
            .cornerRadius(SautaiDesign.cornerRadius)
        }
    }

    // MARK: - Stats Row

    private var statsRow: some View {
        HStack(spacing: SautaiDesign.spacingM) {
            statItem(value: "\(client.totalOrders ?? 0)", label: "Orders")
            statItem(value: client.totalSpentDisplay ?? "$0", label: "Total Spent")
        }
    }

    private func statItem(value: String, label: String) -> some View {
        VStack(spacing: SautaiDesign.spacingXS) {
            Text(value)
                .font(SautaiFont.title2)
                .foregroundColor(.sautai.earthenClay)
            Text(label)
                .font(SautaiFont.caption)
                .foregroundColor(.sautai.slateTile.opacity(0.7))
        }
        .frame(maxWidth: .infinity)
        .padding(SautaiDesign.spacing)
        .background(Color.white)
        .cornerRadius(SautaiDesign.cornerRadius)
    }

    // MARK: - Connection Info Section

    @ViewBuilder
    private var connectionInfoSection: some View {
        if let status = client.connectionStatus {
            VStack(alignment: .leading, spacing: SautaiDesign.spacingS) {
                Text("Connection")
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile)

                HStack {
                    Circle()
                        .fill(status == "active" ? Color.sautai.success : Color.sautai.slateTile.opacity(0.3))
                        .frame(width: 8, height: 8)

                    Text(status.capitalized)
                        .font(SautaiFont.body)
                        .foregroundColor(.sautai.slateTile)

                    Spacer()

                    if let username = client.username {
                        Text("@\(username)")
                            .font(SautaiFont.caption)
                            .foregroundColor(.sautai.slateTile.opacity(0.6))
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(SautaiDesign.spacing)
            .background(Color.white)
            .cornerRadius(SautaiDesign.cornerRadius)
        }
    }

    // MARK: - Notes Section

    private var notesSection: some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            HStack {
                Text("Notes")
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile)

                Spacer()

                Button {
                    showingAddNote = true
                } label: {
                    Label("Add", systemImage: "plus")
                        .font(SautaiFont.buttonSmall)
                        .foregroundColor(.sautai.earthenClay)
                }
            }

            if isLoadingNotes {
                ProgressView()
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding()
            } else if notes.isEmpty {
                Text("No notes yet. Add notes to keep track of preferences, dietary needs, or conversation history.")
                    .font(SautaiFont.body)
                    .foregroundColor(.sautai.slateTile.opacity(0.6))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(SautaiDesign.spacing)
                    .background(Color.white)
                    .cornerRadius(SautaiDesign.cornerRadius)
            } else {
                VStack(spacing: 0) {
                    ForEach(notes) { note in
                        noteRow(note)
                        if note.id != notes.last?.id {
                            Divider()
                                .padding(.horizontal, SautaiDesign.spacing)
                        }
                    }
                }
                .background(Color.white)
                .cornerRadius(SautaiDesign.cornerRadius)
            }
        }
    }

    private func noteRow(_ note: ClientNote) -> some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingXS) {
            Text(note.content)
                .font(SautaiFont.body)
                .foregroundColor(.sautai.slateTile)

            HStack {
                if let author = note.authorName {
                    Text(author)
                        .font(SautaiFont.caption2)
                        .foregroundColor(.sautai.slateTile.opacity(0.5))
                }

                Spacer()

                if let date = note.createdAt {
                    Text(formatDate(date))
                        .font(SautaiFont.caption2)
                        .foregroundColor(.sautai.slateTile.opacity(0.5))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(SautaiDesign.spacing)
    }

    // MARK: - Receipts Section

    private var receiptsSection: some View {
        VStack(alignment: .leading, spacing: SautaiDesign.spacingM) {
            HStack {
                Text("Receipts")
                    .font(SautaiFont.headline)
                    .foregroundColor(.sautai.slateTile)

                Spacer()

                if let totals = receiptTotals {
                    Text(totals.totalDisplay)
                        .font(SautaiFont.caption)
                        .foregroundColor(.sautai.earthenClay)
                }
            }

            if isLoadingReceipts {
                ProgressView()
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding()
            } else if receipts.isEmpty {
                Text("No receipts for this client yet.")
                    .font(SautaiFont.body)
                    .foregroundColor(.sautai.slateTile.opacity(0.6))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(SautaiDesign.spacing)
                    .background(Color.white)
                    .cornerRadius(SautaiDesign.cornerRadius)
            } else {
                // Totals summary
                if let totals = receiptTotals {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Total")
                                .font(SautaiFont.caption2)
                                .foregroundColor(.sautai.slateTile.opacity(0.6))
                            Text(totals.totalDisplay)
                                .font(SautaiFont.headline)
                                .foregroundColor(.sautai.slateTile)
                        }

                        Spacer()

                        VStack(alignment: .center, spacing: 2) {
                            Text("Reimbursed")
                                .font(SautaiFont.caption2)
                                .foregroundColor(.sautai.slateTile.opacity(0.6))
                            Text(totals.reimbursedDisplay)
                                .font(SautaiFont.headline)
                                .foregroundColor(.sautai.success)
                        }

                        Spacer()

                        VStack(alignment: .trailing, spacing: 2) {
                            Text("Pending")
                                .font(SautaiFont.caption2)
                                .foregroundColor(.sautai.slateTile.opacity(0.6))
                            Text(totals.pendingDisplay)
                                .font(SautaiFont.headline)
                                .foregroundColor(.sautai.warning)
                        }
                    }
                    .padding(SautaiDesign.spacing)
                    .background(Color.white)
                    .cornerRadius(SautaiDesign.cornerRadius)
                }

                // Receipt list
                VStack(spacing: 0) {
                    ForEach(receipts) { receipt in
                        receiptRow(receipt)
                        if receipt.id != receipts.last?.id {
                            Divider()
                                .padding(.horizontal, SautaiDesign.spacing)
                        }
                    }
                }
                .background(Color.white)
                .cornerRadius(SautaiDesign.cornerRadius)
            }
        }
    }

    private func receiptRow(_ receipt: ExpenseReceipt) -> some View {
        HStack(spacing: SautaiDesign.spacingM) {
            // Category icon
            Image(systemName: receiptIcon(for: receipt.category))
                .font(.system(size: 20))
                .foregroundColor(.sautai.earthenClay)
                .frame(width: 32)

            // Details
            VStack(alignment: .leading, spacing: 2) {
                Text(receipt.merchantName ?? receipt.categoryDisplay ?? "Receipt")
                    .font(SautaiFont.body)
                    .foregroundColor(.sautai.slateTile)

                HStack(spacing: SautaiDesign.spacingS) {
                    if let status = receipt.statusDisplay {
                        Text(status)
                            .font(SautaiFont.caption2)
                            .foregroundColor(receiptStatusColor(receipt.status))
                    }

                    if let date = receipt.purchaseDate {
                        Text("•")
                            .foregroundColor(.sautai.slateTile.opacity(0.3))
                        Text(date.formatted(date: .abbreviated, time: .omitted))
                            .font(SautaiFont.caption2)
                            .foregroundColor(.sautai.slateTile.opacity(0.6))
                    }
                }
            }

            Spacer()

            // Amount
            Text(receipt.displayAmount)
                .font(SautaiFont.headline)
                .foregroundColor(.sautai.slateTile)
        }
        .padding(SautaiDesign.spacing)
    }

    private func receiptIcon(for category: String?) -> String {
        switch category {
        case "ingredients": return "carrot.fill"
        case "supplies": return "shippingbox.fill"
        case "equipment": return "frying.pan.fill"
        default: return "receipt"
        }
    }

    private func receiptStatusColor(_ status: String?) -> Color {
        switch status {
        case "uploaded": return .sautai.warning
        case "reviewed": return .sautai.info
        case "reimbursed": return .sautai.success
        case "rejected": return .sautai.danger
        default: return .sautai.slateTile.opacity(0.6)
        }
    }

    // MARK: - Helpers

    private func formatDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    private func loadNotes() async {
        isLoadingNotes = true
        do {
            notes = try await APIClient.shared.getClientNotes(clientId: client.id)
        } catch {
            // Notes might not exist yet, which is fine
        }
        isLoadingNotes = false
    }

    private func loadReceipts() async {
        isLoadingReceipts = true
        do {
            let response = try await APIClient.shared.getClientReceipts(clientId: client.id)
            receipts = response.receipts
            receiptTotals = response.totals
        } catch {
            // Receipts might not exist yet, which is fine
        }
        isLoadingReceipts = false
    }

    private func sendEmail(_ email: String) {
        if let url = URL(string: "mailto:\(email)") {
            UIApplication.shared.open(url)
        }
    }
}

// MARK: - Add Client Note View

struct AddClientNoteView: View {
    @Environment(\.dismiss) var dismiss
    let clientId: Int
    let onAdd: (ClientNote) -> Void

    @State private var content = ""
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Note") {
                    TextField("What do you want to remember about this client?", text: $content, axis: .vertical)
                        .lineLimit(4...10)
                }

                if let error = errorMessage {
                    Section {
                        Text(error)
                            .foregroundColor(.sautai.danger)
                            .font(SautaiFont.caption)
                    }
                }
            }
            .navigationTitle("Add Note")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saveNote()
                    }
                    .disabled(content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isLoading)
                }
            }
        }
    }

    private func saveNote() {
        isLoading = true
        errorMessage = nil

        Task {
            do {
                let newNote = try await APIClient.shared.addClientNote(
                    clientId: clientId,
                    content: content.trimmingCharacters(in: .whitespacesAndNewlines)
                )
                await MainActor.run {
                    onAdd(newNote)
                    dismiss()
                }
            } catch {
                await MainActor.run {
                    errorMessage = error.localizedDescription
                    isLoading = false
                }
            }
        }
    }
}

// MARK: - Preview

#Preview {
    ClientsListView()
}
