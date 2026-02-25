/**
 * ProactiveSettingsPanel Component
 *
 * Settings panel for Sous Chef proactive notifications.
 * Features:
 * - Master toggle (opt-in by default)
 * - Notification type toggles (birthdays, anniversaries, follow-ups, etc.)
 * - Notification frequency selector (real-time, daily, weekly)
 * - Quiet hours configuration
 *
 * Progressive disclosure: advanced options only shown when relevant features enabled.
 * Follows existing WorkspaceSettings/TelegramConnected patterns.
 */

import React, { useState, useCallback, useEffect, useRef } from 'react'
import {
  useProactiveSettings,
  useUpdateProactiveSettings,
  useEnableProactive,
  useDisableProactive,
} from '../hooks/useProactiveSettings'

// Common timezones for dropdown
const COMMON_TIMEZONES = [
  { value: 'America/New_York', label: 'Eastern Time (ET)' },
  { value: 'America/Chicago', label: 'Central Time (CT)' },
  { value: 'America/Denver', label: 'Mountain Time (MT)' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (PT)' },
  { value: 'America/Phoenix', label: 'Arizona (AZ)' },
  { value: 'America/Anchorage', label: 'Alaska (AK)' },
  { value: 'Pacific/Honolulu', label: 'Hawaii (HI)' },
  { value: 'Europe/London', label: 'London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Paris (CET/CEST)' },
  { value: 'Asia/Tokyo', label: 'Tokyo (JST)' },
  { value: 'Australia/Sydney', label: 'Sydney (AEST)' },
]

// Notification types configuration
const NOTIFICATION_TYPES = [
  {
    id: 'birthdays',
    field: 'notify_birthdays',
    leadDaysField: 'birthday_lead_days',
    emoji: '🎂',
    label: 'Birthdays',
    desc: 'Remind me before client birthdays',
    leadDaysLabel: 'days before',
    defaultLeadDays: 7,
  },
  {
    id: 'anniversaries',
    field: 'notify_anniversaries',
    leadDaysField: 'anniversary_lead_days',
    emoji: '💍',
    label: 'Anniversaries',
    desc: 'Remind me before client anniversaries',
    leadDaysLabel: 'days before',
    defaultLeadDays: 7,
  },
  {
    id: 'followups',
    field: 'notify_followups',
    leadDaysField: 'followup_threshold_days',
    emoji: '👋',
    label: 'Follow-ups',
    desc: 'Suggest reaching out after inactivity',
    leadDaysLabel: 'days inactive',
    defaultLeadDays: 30,
  },
  {
    id: 'todos',
    field: 'notify_todos',
    emoji: '📝',
    label: 'To-do Reminders',
    desc: 'Remind me about saved tasks',
  },
  {
    id: 'seasonal',
    field: 'notify_seasonal',
    emoji: '🌱',
    label: 'Seasonal Suggestions',
    desc: 'Monthly ingredient & menu ideas',
  },
  {
    id: 'milestones',
    field: 'notify_milestones',
    emoji: '🎉',
    label: 'Client Milestones',
    desc: 'Celebrate 5th, 10th, 25th orders',
  },
]

// Frequency options
const FREQUENCY_OPTIONS = [
  { value: 'realtime', label: 'Real-time', desc: 'Immediate notifications' },
  { value: 'daily', label: 'Daily digest', desc: 'Once per day summary' },
  { value: 'weekly', label: 'Weekly digest', desc: 'Once per week summary' },
]

/**
 * ProactiveSettingsPanel - Configure proactive notification preferences
 */
export default function ProactiveSettingsPanel() {
  const { data: settings, isLoading, error: fetchError } = useProactiveSettings()
  const updateMutation = useUpdateProactiveSettings()
  const enableMutation = useEnableProactive()
  const disableMutation = useDisableProactive()

  // Debounce timer ref for lead days
  const debounceRef = useRef(null)

  // Local state for lead days inputs (to avoid API spam while typing)
  const [localLeadDays, setLocalLeadDays] = useState({})

  // Sync local lead days with server data
  useEffect(() => {
    if (settings) {
      setLocalLeadDays({
        birthday_lead_days: settings.birthday_lead_days ?? 7,
        anniversary_lead_days: settings.anniversary_lead_days ?? 7,
        followup_threshold_days: settings.followup_threshold_days ?? 30,
      })
    }
  }, [settings])

  // Handle master toggle
  const handleMasterToggle = useCallback((checked) => {
    if (checked) {
      enableMutation.mutate()
    } else {
      disableMutation.mutate()
    }
  }, [enableMutation, disableMutation])

  // Handle individual notification type toggle
  const handleTypeToggle = useCallback((field, checked) => {
    updateMutation.mutate({ [field]: checked })
  }, [updateMutation])

  // Handle lead days change with debounce
  const handleLeadDaysChange = useCallback((field, value) => {
    const numValue = parseInt(value, 10) || 1
    const clampedValue = Math.max(1, Math.min(365, numValue))

    // Update local state immediately
    setLocalLeadDays(prev => ({ ...prev, [field]: clampedValue }))

    // Debounce API call
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }
    debounceRef.current = setTimeout(() => {
      updateMutation.mutate({ [field]: clampedValue })
    }, 500)
  }, [updateMutation])

  // Handle frequency change
  const handleFrequencyChange = useCallback((value) => {
    updateMutation.mutate({ notification_frequency: value })
  }, [updateMutation])

  // Handle quiet hours toggle
  const handleQuietHoursToggle = useCallback((checked) => {
    updateMutation.mutate({ quiet_hours_enabled: checked })
  }, [updateMutation])

  // Handle quiet hours time change
  const handleTimeChange = useCallback((field, value) => {
    updateMutation.mutate({ [field]: value })
  }, [updateMutation])

  // Handle timezone change
  const handleTimezoneChange = useCallback((value) => {
    updateMutation.mutate({ quiet_hours_timezone: value })
  }, [updateMutation])

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [])

  const isUpdating = updateMutation.isPending || enableMutation.isPending || disableMutation.isPending
  const isEnabled = settings?.enabled ?? false

  if (isLoading) {
    return (
      <div className="ps-loading">
        <div className="ps-loading-spinner" />
        <span>Loading notification settings...</span>

        <style>{`
          .ps-loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1rem;
            padding: 3rem 1.5rem;
            background: var(--surface, #fff);
            border-radius: 16px;
            border: 1px solid var(--border, #e5e5e5);
            color: var(--muted, #888);
            margin-bottom: 1rem;
          }

          .ps-loading-spinner {
            width: 32px;
            height: 32px;
            border: 3px solid var(--border, #e5e5e5);
            border-top-color: var(--primary, #7C9070);
            border-radius: 50%;
            animation: psSpin 0.8s linear infinite;
          }

          @keyframes psSpin {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    )
  }

  if (fetchError) {
    return (
      <div className="ps-error">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="32" height="32">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>Failed to load notification settings</p>

        <style>{`
          .ps-error {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1rem;
            padding: 3rem 1.5rem;
            background: var(--surface, #fff);
            border-radius: 16px;
            border: 1px solid var(--border, #e5e5e5);
            color: var(--muted, #888);
            text-align: center;
            margin-bottom: 1rem;
          }

          .ps-error svg {
            color: #dc3545;
          }

          .ps-error p {
            margin: 0;
          }
        `}</style>
      </div>
    )
  }

  return (
    <div className="ps-container">
      {/* Master Toggle Section */}
      <div className="ps-master">
        <div className="ps-master-icon">🔔</div>
        <div className="ps-master-content">
          <div className="ps-master-header">
            <h3 className="ps-master-title">Proactive Notifications</h3>
            <input
              type="checkbox"
              className="ps-toggle"
              checked={isEnabled}
              onChange={(e) => handleMasterToggle(e.target.checked)}
              disabled={isUpdating}
              aria-label="Enable proactive notifications"
            />
          </div>
          <p className="ps-master-desc">
            Let Sous Chef remind you about birthdays, follow-ups, and opportunities to connect with your clients.
          </p>
        </div>
      </div>

      {/* Expanded Settings (only when enabled) */}
      {isEnabled && (
        <div className="ps-settings">
          {/* Notification Types */}
          <div className="ps-section">
            <h4 className="ps-section-title">What to notify about</h4>
            <div className="ps-type-list">
              {NOTIFICATION_TYPES.map((type) => (
                <div key={type.id} className="ps-type-item">
                  <label className="ps-type-row">
                    <span className="ps-type-emoji">{type.emoji}</span>
                    <div className="ps-type-content">
                      <span className="ps-type-label">{type.label}</span>
                      <span className="ps-type-desc">{type.desc}</span>
                    </div>
                    <input
                      type="checkbox"
                      className="ps-toggle"
                      checked={settings?.[type.field] ?? false}
                      onChange={(e) => handleTypeToggle(type.field, e.target.checked)}
                      disabled={isUpdating}
                      aria-label={`Enable ${type.label} notifications`}
                    />
                  </label>
                  {/* Lead days config (if applicable and enabled) */}
                  {type.leadDaysField && settings?.[type.field] && (
                    <div className="ps-type-config">
                      <span className="ps-config-prefix">Remind me</span>
                      <input
                        type="number"
                        className="ps-lead-days-input"
                        min="1"
                        max="365"
                        value={localLeadDays[type.leadDaysField] ?? type.defaultLeadDays}
                        onChange={(e) => handleLeadDaysChange(type.leadDaysField, e.target.value)}
                        disabled={isUpdating}
                        aria-label={`${type.label} lead days`}
                      />
                      <span className="ps-config-suffix">{type.leadDaysLabel}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Notification Frequency */}
          <div className="ps-section">
            <h4 className="ps-section-title">Notification frequency</h4>
            <div className="ps-frequency-options">
              {FREQUENCY_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className={`ps-freq-option ${settings?.notification_frequency === option.value ? 'selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="notification_frequency"
                    value={option.value}
                    checked={settings?.notification_frequency === option.value}
                    onChange={() => handleFrequencyChange(option.value)}
                    disabled={isUpdating}
                  />
                  <span className="ps-freq-label">{option.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Quiet Hours */}
          <div className="ps-section">
            <h4 className="ps-section-title">Quiet hours</h4>
            <label className="ps-toggle-row">
              <div className="ps-toggle-content">
                <span className="ps-toggle-label">Enable quiet hours</span>
                <span className="ps-toggle-desc">Pause notifications during specific times</span>
              </div>
              <input
                type="checkbox"
                className="ps-toggle"
                checked={settings?.quiet_hours_enabled ?? false}
                onChange={(e) => handleQuietHoursToggle(e.target.checked)}
                disabled={isUpdating}
                aria-label="Enable quiet hours"
              />
            </label>

            {settings?.quiet_hours_enabled && (
              <div className="ps-quiet-config">
                <div className="ps-quiet-times">
                  <div className="ps-time-input">
                    <label htmlFor="ps-quiet-start">From</label>
                    <input
                      id="ps-quiet-start"
                      type="time"
                      value={settings?.quiet_hours_start || '22:00'}
                      onChange={(e) => handleTimeChange('quiet_hours_start', e.target.value)}
                      disabled={isUpdating}
                    />
                  </div>
                  <div className="ps-time-input">
                    <label htmlFor="ps-quiet-end">To</label>
                    <input
                      id="ps-quiet-end"
                      type="time"
                      value={settings?.quiet_hours_end || '08:00'}
                      onChange={(e) => handleTimeChange('quiet_hours_end', e.target.value)}
                      disabled={isUpdating}
                    />
                  </div>
                </div>
                <div className="ps-timezone">
                  <label htmlFor="ps-timezone">Timezone</label>
                  <select
                    id="ps-timezone"
                    value={settings?.quiet_hours_timezone || 'America/New_York'}
                    onChange={(e) => handleTimezoneChange(e.target.value)}
                    disabled={isUpdating}
                  >
                    {COMMON_TIMEZONES.map((tz) => (
                      <option key={tz.value} value={tz.value}>
                        {tz.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Hint when disabled */}
      {!isEnabled && (
        <div className="ps-hint">
          <span className="ps-hint-icon">✨</span>
          <span className="ps-hint-text">
            Enable to configure notification types, frequency, and quiet hours
          </span>
        </div>
      )}

      {/* Error messages */}
      {(updateMutation.isError || enableMutation.isError || disableMutation.isError) && (
        <div className="ps-mutation-error">
          Failed to update settings. Please try again.
        </div>
      )}

      <style>{`
        .ps-container {
          background: var(--surface, #fff);
          border-radius: 16px;
          border: 1px solid var(--border, #e5e5e5);
          margin-bottom: 1rem;
          overflow: hidden;
        }

        /* Master Toggle Section */
        .ps-master {
          display: flex;
          gap: 1rem;
          padding: 1.25rem;
        }

        .ps-master-icon {
          font-size: 1.5rem;
          flex-shrink: 0;
        }

        .ps-master-content {
          flex: 1;
        }

        .ps-master-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          margin-bottom: 0.375rem;
        }

        .ps-master-title {
          margin: 0;
          font-size: 1rem;
          font-weight: 600;
          color: var(--text, #333);
        }

        .ps-master-desc {
          margin: 0;
          font-size: 0.875rem;
          color: var(--muted, #888);
          line-height: 1.4;
        }

        /* Settings Sections */
        .ps-settings {
          border-top: 1px solid var(--border, #e5e5e5);
          animation: psSlideDown 0.25s ease;
        }

        @keyframes psSlideDown {
          from {
            opacity: 0;
            transform: translateY(-10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .ps-section {
          padding: 1.25rem;
          border-bottom: 1px solid var(--border, #e5e5e5);
        }

        .ps-section:last-child {
          border-bottom: none;
        }

        .ps-section-title {
          margin: 0 0 1rem 0;
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--muted, #666);
          text-transform: uppercase;
          letter-spacing: 0.025em;
        }

        /* Notification Type List */
        .ps-type-list {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }

        .ps-type-item {
          background: var(--surface-2, #f9fafb);
          border-radius: 8px;
          overflow: hidden;
        }

        .ps-type-row {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          padding: 0.75rem;
          cursor: pointer;
          transition: background 0.15s;
        }

        .ps-type-row:hover {
          background: var(--surface-3, #f0f0f0);
        }

        .ps-type-emoji {
          font-size: 1.1rem;
          flex-shrink: 0;
        }

        .ps-type-content {
          flex: 1;
          min-width: 0;
        }

        .ps-type-label {
          display: block;
          font-weight: 500;
          font-size: 0.9rem;
          color: var(--text, #333);
        }

        .ps-type-desc {
          display: block;
          font-size: 0.8rem;
          color: var(--muted, #888);
          margin-top: 0.125rem;
        }

        /* Lead Days Config */
        .ps-type-config {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.5rem 0.75rem 0.75rem 2.85rem;
          font-size: 0.85rem;
          color: var(--muted, #666);
        }

        .ps-config-prefix,
        .ps-config-suffix {
          white-space: nowrap;
        }

        .ps-lead-days-input {
          width: 60px;
          padding: 0.375rem 0.5rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 6px;
          font-size: 0.85rem;
          font-family: inherit;
          background: var(--surface, #fff);
          color: var(--text, #333);
          text-align: center;
        }

        .ps-lead-days-input:focus {
          outline: none;
          border-color: var(--primary, #7C9070);
        }

        .ps-lead-days-input:disabled {
          opacity: 0.5;
        }

        /* Frequency Options */
        .ps-frequency-options {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
        }

        .ps-freq-option {
          display: flex;
          align-items: center;
          padding: 0.625rem 1rem;
          background: var(--surface-2, #f9fafb);
          border: 2px solid var(--border, #e5e7eb);
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.15s;
        }

        .ps-freq-option:hover {
          border-color: var(--primary, #7C9070);
        }

        .ps-freq-option.selected {
          border-color: var(--primary, #7C9070);
          background: rgba(124, 144, 112, 0.1);
        }

        .ps-freq-option input {
          position: absolute;
          opacity: 0;
          width: 0;
          height: 0;
        }

        .ps-freq-label {
          font-size: 0.9rem;
          font-weight: 500;
          color: var(--text, #333);
        }

        /* Toggle Row (for quiet hours enable) */
        .ps-toggle-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          padding: 0.75rem;
          background: var(--surface-2, #f9fafb);
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.15s;
        }

        .ps-toggle-row:hover {
          background: var(--surface-3, #f0f0f0);
        }

        .ps-toggle-content {
          flex: 1;
        }

        .ps-toggle-label {
          display: block;
          font-weight: 500;
          font-size: 0.9rem;
          color: var(--text, #333);
        }

        .ps-toggle-desc {
          display: block;
          font-size: 0.8rem;
          color: var(--muted, #888);
          margin-top: 0.125rem;
        }

        /* Quiet Hours Config */
        .ps-quiet-config {
          margin-top: 0.75rem;
          padding: 0.75rem;
          background: var(--surface-2, #f9fafb);
          border-radius: 8px;
        }

        .ps-quiet-times {
          display: flex;
          gap: 1rem;
          margin-bottom: 0.75rem;
        }

        .ps-time-input {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 0.375rem;
        }

        .ps-time-input label {
          font-size: 0.8rem;
          font-weight: 500;
          color: var(--muted, #888);
        }

        .ps-time-input input {
          padding: 0.5rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 6px;
          font-size: 0.9rem;
          font-family: inherit;
          background: var(--surface, #fff);
          color: var(--text, #333);
        }

        .ps-time-input input:focus {
          outline: none;
          border-color: var(--primary, #7C9070);
        }

        .ps-time-input input:disabled {
          opacity: 0.5;
        }

        .ps-timezone {
          display: flex;
          flex-direction: column;
          gap: 0.375rem;
        }

        .ps-timezone label {
          font-size: 0.8rem;
          font-weight: 500;
          color: var(--muted, #888);
        }

        .ps-timezone select {
          padding: 0.5rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 6px;
          font-size: 0.9rem;
          font-family: inherit;
          background: var(--surface, #fff);
          color: var(--text, #333);
          cursor: pointer;
        }

        .ps-timezone select:focus {
          outline: none;
          border-color: var(--primary, #7C9070);
        }

        .ps-timezone select:disabled {
          opacity: 0.5;
        }

        /* Custom Toggle Switch */
        .ps-toggle {
          appearance: none;
          width: 44px;
          height: 24px;
          background: var(--border, #ddd);
          border-radius: 12px;
          position: relative;
          cursor: pointer;
          transition: background 0.2s;
          flex-shrink: 0;
        }

        .ps-toggle:checked {
          background: var(--primary, #7C9070);
        }

        .ps-toggle:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .ps-toggle:focus {
          outline: none;
          box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.2);
        }

        .ps-toggle::before {
          content: '';
          position: absolute;
          width: 20px;
          height: 20px;
          background: white;
          border-radius: 50%;
          top: 2px;
          left: 2px;
          transition: transform 0.2s;
          box-shadow: 0 1px 3px rgba(27,58,45,0.2);
        }

        .ps-toggle:checked::before {
          transform: translateX(20px);
        }

        /* Hint when disabled */
        .ps-hint {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          padding: 1rem;
          border-top: 1px solid var(--border, #e5e5e5);
          background: var(--surface-2, #f9fafb);
          color: var(--muted, #888);
          font-size: 0.875rem;
        }

        .ps-hint-icon {
          font-size: 1rem;
        }

        /* Error Message */
        .ps-mutation-error {
          margin: 1rem;
          margin-top: 0;
          padding: 0.75rem;
          background: rgba(220, 53, 69, 0.1);
          border: 1px solid rgba(220, 53, 69, 0.3);
          border-radius: 8px;
          color: #dc3545;
          font-size: 0.9rem;
          text-align: center;
        }

        /* Responsive */
        @media (max-width: 480px) {
          .ps-master {
            flex-direction: column;
            gap: 0.75rem;
          }

          .ps-master-header {
            flex-direction: row;
          }

          .ps-frequency-options {
            flex-direction: column;
          }

          .ps-freq-option {
            justify-content: center;
          }

          .ps-quiet-times {
            flex-direction: column;
            gap: 0.75rem;
          }

          .ps-type-config {
            flex-wrap: wrap;
            padding-left: 0.75rem;
          }
        }
      `}</style>
    </div>
  )
}
