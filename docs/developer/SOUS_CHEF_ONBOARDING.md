# Developer Directive: Sous Chef Onboarding & Proactive System

## Overview

This document covers two related systems:
1. **Onboarding** - First-time chef experience and progressive feature discovery
2. **Proactive Engine** - Opt-in notifications for birthdays, follow-ups, etc.

**Core Principle:** Nothing is forced. Chefs control their level of engagement.

---

## Data Models (Already Created)

```python
# chefs/models/proactive.py

class ChefProactiveSettings(models.Model):
    chef = OneToOneField(Chef)
    
    # Master switch (OFF by default)
    proactive_enabled = BooleanField(default=False)
    
    # Frequency
    frequency = CharField(choices=[
        'realtime', 'daily', 'weekly', 'manual'
    ], default='manual')
    
    # What to notify about (all default False - opt-in)
    notify_birthdays = BooleanField(default=False)
    notify_anniversaries = BooleanField(default=False)
    notify_followups = BooleanField(default=False)
    notify_todos = BooleanField(default=False)
    notify_seasonal = BooleanField(default=False)
    notify_milestones = BooleanField(default=False)
    
    # Lead time
    occasion_lead_days = IntegerField(default=7)
    followup_threshold_days = IntegerField(default=21)
    
    # Channels
    channel_inapp = BooleanField(default=True)
    channel_email = BooleanField(default=False)
    channel_push = BooleanField(default=False)
    
    # Quiet hours
    quiet_start = TimeField(null=True)
    quiet_end = TimeField(null=True)
    timezone = CharField(default='UTC')


class ChefOnboardingState(models.Model):
    chef = OneToOneField(Chef)
    
    # Setup progress
    welcomed = BooleanField(default=False)
    setup_started = BooleanField(default=False)
    setup_completed = BooleanField(default=False)
    setup_skipped = BooleanField(default=False)
    
    # Personality
    personality_set = BooleanField(default=False)
    personality_choice = CharField()  # 'professional', 'friendly', 'efficient'
    
    # Milestones
    first_dish_added = BooleanField(default=False)
    first_client_added = BooleanField(default=False)
    first_order_completed = BooleanField(default=False)
    first_memory_saved = BooleanField(default=False)
    
    # Progressive tips
    tips_shown = JSONField(default=list)
    tips_dismissed = JSONField(default=list)


class ChefNotification(models.Model):
    chef = ForeignKey(Chef)
    notification_type = CharField()  # birthday, followup, todo, etc.
    title = CharField()
    message = TextField()
    status = CharField()  # pending, sent, read, dismissed
    action_type = CharField()
    action_payload = JSONField()
```

---

## Part 1: Onboarding Flow

### Welcome Moment

When a chef first logs into Chef Hub:

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  🧑‍🍳 Hey, I'm your Sous Chef!                              │
│                                                             │
│  Think of me as your kitchen partner who never forgets     │
│  a detail. I can help you:                                  │
│                                                             │
│  • Remember every client's preferences & allergies          │
│  • Plan menus that work for their households                │
│  • Keep track of what's worked before                       │
│                                                             │
│  Want me to help you set up a few things?                  │
│                                                             │
│  [Let's do it →]              [I'll explore on my own]     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Guided Setup Flow (If "Let's do it")

**Step 1: Name & Specialty**
```jsx
<OnboardingStep step={1} total={4}>
  <h2>What should I call you?</h2>
  <Input 
    placeholder="Chef Marcus" 
    value={nickname}
    onChange={setNickname}
  />
  
  <h2>What's your specialty?</h2>
  <TagSelect 
    options={['Comfort Food', 'Fine Dining', 'Meal Prep', 'Health-Focused', 'International']}
    selected={specialties}
    onChange={setSpecialties}
  />
</OnboardingStep>
```

**Step 2: Communication Style**
```jsx
<OnboardingStep step={2} total={4}>
  <h2>How should I communicate with you?</h2>
  
  <PersonalityOption 
    id="professional"
    emoji="👔"
    title="Keep it professional"
    description="Clear, formal, to the point"
    selected={personality === 'professional'}
    onSelect={() => setPersonality('professional')}
  />
  
  <PersonalityOption 
    id="friendly"
    emoji="😊"
    title="Friendly and warm"
    description="Casual, supportive, encouraging"
    selected={personality === 'friendly'}
    onSelect={() => setPersonality('friendly')}
  />
  
  <PersonalityOption 
    id="efficient"
    emoji="⚡"
    title="Short and efficient"
    description="Just the essentials, no fluff"
    selected={personality === 'efficient'}
    onSelect={() => setPersonality('efficient')}
  />
  
  <p className="hint">You can always customize this later</p>
</OnboardingStep>
```

**Step 3: First Dish**
```jsx
<OnboardingStep step={3} total={4}>
  <h2>Add your first signature dish</h2>
  <p>This helps me learn your style</p>
  
  <DishQuickAdd 
    onAdd={(dish) => {
      markMilestone('first_dish_added');
      setFirstDish(dish);
    }}
  />
  
  <button onClick={skip}>Skip for now</button>
</OnboardingStep>
```

**Step 4: First Client (Optional)**
```jsx
<OnboardingStep step={4} total={4}>
  <h2>Got a client in mind?</h2>
  <p>Add them so I can start remembering their preferences</p>
  
  <ClientQuickAdd 
    onAdd={(client) => {
      markMilestone('first_client_added');
      setFirstClient(client);
    }}
  />
  
  <button onClick={complete}>I'll add clients later</button>
</OnboardingStep>
```

**Completion**
```jsx
<OnboardingComplete>
  <h2>You're all set, {nickname}! 🎉</h2>
  
  <Summary>
    <SummaryItem icon="👤" label="You are" value={nickname} />
    <SummaryItem icon="🍳" label="Specialty" value={specialties.join(', ')} />
    <SummaryItem icon="💬" label="Vibe" value={personalityLabels[personality]} />
    {firstDish && <SummaryItem icon="🍽️" label="First dish" value={firstDish.name} />}
    {firstClient && <SummaryItem icon="👥" label="First client" value={firstClient.name} />}
  </Summary>
  
  <p>
    Ask me anything about your clients, or any client you add. 
    I'll keep learning as we work together.
  </p>
  
  <button onClick={goToDashboard}>Start cooking →</button>
</OnboardingComplete>
```

### Personality → Soul Prompt Mapping

```javascript
const PERSONALITY_PROMPTS = {
  professional: `
    Communicate in a professional, clear manner.
    Be respectful and formal.
    Focus on facts and actionable information.
    Keep responses concise and well-organized.
  `,
  friendly: `
    Be warm, friendly, and encouraging.
    Use casual language and occasional emojis.
    Celebrate wins and offer genuine support.
    Remember personal details and bring them up naturally.
  `,
  efficient: `
    Be extremely concise.
    Bullet points over paragraphs.
    No pleasantries or filler.
    Just the essential information.
  `
};

// On personality selection:
async function setPersonality(choice) {
  await api.updateWorkspace({
    soul_prompt: PERSONALITY_PROMPTS[choice]
  });
  await api.updateOnboardingState({
    personality_set: true,
    personality_choice: choice
  });
}
```

---

## Part 2: Progressive Tips

Tips appear contextually as the chef discovers features.

### Tip Definitions

```javascript
const TIPS = [
  {
    id: 'add_first_dish',
    condition: (state) => !state.first_dish_added && state.welcomed,
    message: "Add your first dish so I can learn your style!",
    action: { type: 'navigate', target: 'dishes' },
    position: 'dish_list_empty'
  },
  {
    id: 'add_first_client',
    condition: (state) => state.first_dish_added && !state.first_client_added,
    message: "Ready to add your first client? I'll remember everything about them.",
    action: { type: 'navigate', target: 'clients' },
    position: 'client_list_empty'
  },
  {
    id: 'memory_intro',
    condition: (state) => state.first_client_added && !state.first_memory_saved && state.sous_chef_conversations >= 3,
    message: "Tip: Tell me things about your clients and I'll remember them. Try: 'Remember that the Johnsons love extra garlic'",
    position: 'sous_chef_input'
  },
  {
    id: 'proactive_intro',
    condition: (state) => state.first_order_completed,
    message: "Want me to remind you about client birthdays and follow-ups?",
    action: { type: 'open_settings', target: 'proactive' },
    position: 'notification_bell'
  }
];
```

### Tip Component

```jsx
const ContextualTip = ({ tipId, position }) => {
  const { state, showTip, dismissTip } = useOnboarding();
  const tip = TIPS.find(t => t.id === tipId);
  
  if (!tip || !showTip(tipId)) return null;
  
  return (
    <TipBubble position={position}>
      <p>{tip.message}</p>
      <TipActions>
        {tip.action && (
          <button onClick={() => handleAction(tip.action)}>
            {tip.action.label || 'Show me'}
          </button>
        )}
        <button onClick={() => dismissTip(tipId)}>Got it</button>
      </TipActions>
    </TipBubble>
  );
};
```

---

## Part 3: Proactive Settings UI

### Settings Panel

```jsx
const ProactiveSettings = () => {
  const { settings, updateSettings } = useProactiveSettings();
  
  return (
    <SettingsPanel title="🔔 Sous Chef Notifications">
      {/* Master switch */}
      <ToggleRow
        label="Enable proactive reminders"
        description="Let Sous Chef reach out about important dates and follow-ups"
        checked={settings.proactive_enabled}
        onChange={(v) => updateSettings({ proactive_enabled: v })}
      />
      
      {settings.proactive_enabled && (
        <>
          <Divider />
          
          {/* What to notify */}
          <Section title="Notify me about">
            <CheckboxRow
              label="Client birthdays"
              checked={settings.notify_birthdays}
              onChange={(v) => updateSettings({ notify_birthdays: v })}
              suffix={
                <Select
                  value={settings.occasion_lead_days}
                  options={[3, 5, 7, 14]}
                  format={(v) => `${v} days ahead`}
                  onChange={(v) => updateSettings({ occasion_lead_days: v })}
                />
              }
            />
            <CheckboxRow
              label="Anniversaries & special dates"
              checked={settings.notify_anniversaries}
              onChange={(v) => updateSettings({ notify_anniversaries: v })}
            />
            <CheckboxRow
              label="Clients I haven't heard from"
              checked={settings.notify_followups}
              onChange={(v) => updateSettings({ notify_followups: v })}
              suffix={
                <Select
                  value={settings.followup_threshold_days}
                  options={[14, 21, 30, 60]}
                  format={(v) => `after ${v} days`}
                  onChange={(v) => updateSettings({ followup_threshold_days: v })}
                />
              }
            />
            <CheckboxRow
              label="My to-do reminders"
              checked={settings.notify_todos}
              onChange={(v) => updateSettings({ notify_todos: v })}
            />
            <CheckboxRow
              label="Seasonal ingredient ideas"
              checked={settings.notify_seasonal}
              onChange={(v) => updateSettings({ notify_seasonal: v })}
            />
            <CheckboxRow
              label="Client milestones"
              description="10th order, anniversaries with you, etc."
              checked={settings.notify_milestones}
              onChange={(v) => updateSettings({ notify_milestones: v })}
            />
          </Section>
          
          <Divider />
          
          {/* Frequency */}
          <Section title="How often">
            <RadioGroup
              value={settings.frequency}
              onChange={(v) => updateSettings({ frequency: v })}
              options={[
                { value: 'realtime', label: 'As things come up' },
                { value: 'daily', label: 'Daily digest (morning)' },
                { value: 'weekly', label: 'Weekly summary (Mondays)' },
              ]}
            />
          </Section>
          
          <Divider />
          
          {/* Channels */}
          <Section title="Where">
            <CheckboxRow
              label="In-app notifications"
              checked={settings.channel_inapp}
              onChange={(v) => updateSettings({ channel_inapp: v })}
            />
            <CheckboxRow
              label="Email"
              checked={settings.channel_email}
              onChange={(v) => updateSettings({ channel_email: v })}
            />
            <CheckboxRow
              label="Push notifications"
              checked={settings.channel_push}
              onChange={(v) => updateSettings({ channel_push: v })}
              disabled={!pushSupported}
            />
          </Section>
          
          <Divider />
          
          {/* Quiet hours */}
          <Section title="Quiet hours">
            <TimeRangeSelect
              start={settings.quiet_start}
              end={settings.quiet_end}
              timezone={settings.timezone}
              onChange={(start, end, tz) => updateSettings({
                quiet_start: start,
                quiet_end: end,
                timezone: tz
              })}
            />
          </Section>
        </>
      )}
    </SettingsPanel>
  );
};
```

---

## Part 4: Notification Display

### Notification Bell

```jsx
const NotificationBell = () => {
  const { notifications, unreadCount, markRead } = useNotifications();
  const [open, setOpen] = useState(false);
  
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger>
        <BellIcon />
        {unreadCount > 0 && <Badge>{unreadCount}</Badge>}
      </PopoverTrigger>
      
      <PopoverContent>
        <NotificationList>
          {notifications.map(n => (
            <NotificationItem
              key={n.id}
              notification={n}
              onRead={() => markRead(n.id)}
              onDismiss={() => dismiss(n.id)}
              onAction={() => handleAction(n)}
            />
          ))}
        </NotificationList>
      </PopoverContent>
    </Popover>
  );
};
```

### Notification Item

```jsx
const NotificationItem = ({ notification, onRead, onDismiss, onAction }) => {
  const icon = NOTIFICATION_ICONS[notification.notification_type];
  
  return (
    <div 
      className={`notification ${notification.status === 'read' ? 'read' : 'unread'}`}
      onClick={onRead}
    >
      <span className="icon">{icon}</span>
      <div className="content">
        <h4>{notification.title}</h4>
        <p>{notification.message}</p>
        <span className="time">{formatRelativeTime(notification.created_at)}</span>
      </div>
      <div className="actions">
        {notification.action_type && (
          <button onClick={onAction}>View</button>
        )}
        <button onClick={onDismiss}>✕</button>
      </div>
    </div>
  );
};

const NOTIFICATION_ICONS = {
  birthday: '🎂',
  anniversary: '💍',
  followup: '👋',
  todo: '📝',
  seasonal: '🌱',
  milestone: '🎉',
  tip: '💡',
  welcome: '👋',
};
```

---

## API Endpoints

### Onboarding

```
GET  /api/chef/onboarding/          # Get onboarding state
POST /api/chef/onboarding/start/    # Mark setup started
POST /api/chef/onboarding/complete/ # Mark setup complete
POST /api/chef/onboarding/skip/     # Mark setup skipped
POST /api/chef/onboarding/milestone/ # Record a milestone
POST /api/chef/onboarding/tip/show/  # Mark tip as shown
POST /api/chef/onboarding/tip/dismiss/ # Dismiss a tip
```

### Proactive Settings

```
GET  /api/chef/proactive/           # Get proactive settings
PUT  /api/chef/proactive/           # Update settings
POST /api/chef/proactive/disable/   # Quick disable (master switch off)
```

### Notifications

```
GET    /api/chef/notifications/           # List notifications
GET    /api/chef/notifications/unread/    # Unread count
POST   /api/chef/notifications/{id}/read/ # Mark as read
POST   /api/chef/notifications/{id}/dismiss/ # Dismiss
DELETE /api/chef/notifications/{id}/      # Delete
```

---

## Celery Beat Schedule

```python
# sautai/celery.py

CELERY_BEAT_SCHEDULE = {
    'proactive-engine': {
        'task': 'chefs.proactive_engine.run_proactive_check',
        'schedule': crontab(minute=0),  # Every hour
    },
}
```

---

## Implementation Priority

1. **Phase 1:** Welcome modal + personality selection
2. **Phase 2:** Guided setup flow (4 steps)
3. **Phase 3:** Proactive settings panel
4. **Phase 4:** Notification bell + display
5. **Phase 5:** Progressive tips system
6. **Phase 6:** Email/push delivery

---

## Testing Checklist

- [ ] New chef sees welcome on first login
- [ ] "Skip" works and remembers
- [ ] Personality choice updates soul_prompt
- [ ] Onboarding state persists across sessions
- [ ] Tips don't repeat after dismissal
- [ ] Proactive defaults to OFF
- [ ] Quiet hours respected
- [ ] Birthday notifications accurate (handle year rollover)
- [ ] Follow-up threshold works correctly
- [ ] Notifications appear in bell
- [ ] Mark as read works
- [ ] Dismiss works
