/**
 * TelegramConnected Component
 *
 * Shows the interface when Telegram is already connected:
 * - Connected status with username
 * - Notification toggle settings
 * - Quiet hours configuration
 * - Disconnect button with confirmation
 */

import React, { useState, useCallback } from 'react'
import { useUnlinkTelegram, useUpdateTelegramSettings } from '../../hooks/useTelegram'

// Telegram brand color
const TELEGRAM_BLUE = '#0088cc'

/**
 * TelegramConnected - UI for managing a connected Telegram account
 *
 * @param {Object} status - Telegram status object from API
 * @param {string} status.telegram_username - Telegram username
 * @param {string} status.telegram_first_name - Telegram first name
 * @param {string} status.linked_at - ISO timestamp when linked
 * @param {Object} status.settings - Notification settings
 */
export default function TelegramConnected({ status }) {
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false)

  const unlinkMutation = useUnlinkTelegram()
  const updateSettingsMutation = useUpdateTelegramSettings()

  const settings = status?.settings || {}
  const displayName = status?.telegram_username 
    ? `@${status.telegram_username}` 
    : status?.telegram_first_name || 'Unknown'

  const handleSettingToggle = useCallback((field, value) => {
    updateSettingsMutation.mutate({ [field]: value })
  }, [updateSettingsMutation])

  const handleTimeChange = useCallback((field, value) => {
    updateSettingsMutation.mutate({ [field]: value })
  }, [updateSettingsMutation])

  const handleDisconnect = useCallback(async () => {
    try {
      await unlinkMutation.mutateAsync()
      setShowDisconnectConfirm(false)
    } catch (err) {
      // Error handled by mutation
    }
  }, [unlinkMutation])

  const linkedDate = status?.linked_at 
    ? new Date(status.linked_at).toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric' 
      })
    : null

  return (
    <div className="tg-connected">
      {/* Header with connected status */}
      <div className="tg-connected-header">
        <div className="tg-connected-icon">
          <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z"/>
          </svg>
        </div>
        <div className="tg-connected-info">
          <div className="tg-connected-status">
            <span className="tg-status-badge">
              <span className="tg-status-dot" />
              Connected
            </span>
          </div>
          <div className="tg-connected-user">{displayName}</div>
          {linkedDate && (
            <div className="tg-connected-date">Since {linkedDate}</div>
          )}
        </div>
      </div>

      {/* Notification Settings */}
      <div className="tg-settings-section">
        <h4 className="tg-settings-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
          Notifications
        </h4>
        
        <div className="tg-toggle-list">
          <label className="tg-toggle-item">
            <div className="tg-toggle-content">
              <span className="tg-toggle-label">New orders</span>
              <span className="tg-toggle-desc">Get notified when you receive a new order</span>
            </div>
            <input
              type="checkbox"
              className="tg-toggle"
              checked={settings.notify_new_orders ?? true}
              onChange={(e) => handleSettingToggle('notify_new_orders', e.target.checked)}
              disabled={updateSettingsMutation.isPending}
            />
          </label>

          <label className="tg-toggle-item">
            <div className="tg-toggle-content">
              <span className="tg-toggle-label">Order updates</span>
              <span className="tg-toggle-desc">Status changes, cancellations, modifications</span>
            </div>
            <input
              type="checkbox"
              className="tg-toggle"
              checked={settings.notify_order_updates ?? true}
              onChange={(e) => handleSettingToggle('notify_order_updates', e.target.checked)}
              disabled={updateSettingsMutation.isPending}
            />
          </label>

          <label className="tg-toggle-item">
            <div className="tg-toggle-content">
              <span className="tg-toggle-label">Schedule reminders</span>
              <span className="tg-toggle-desc">Upcoming deliveries and prep deadlines</span>
            </div>
            <input
              type="checkbox"
              className="tg-toggle"
              checked={settings.notify_schedule_reminders ?? true}
              onChange={(e) => handleSettingToggle('notify_schedule_reminders', e.target.checked)}
              disabled={updateSettingsMutation.isPending}
            />
          </label>

          <label className="tg-toggle-item">
            <div className="tg-toggle-content">
              <span className="tg-toggle-label">Customer messages</span>
              <span className="tg-toggle-desc">Direct messages from customers</span>
            </div>
            <input
              type="checkbox"
              className="tg-toggle"
              checked={settings.notify_customer_messages ?? false}
              onChange={(e) => handleSettingToggle('notify_customer_messages', e.target.checked)}
              disabled={updateSettingsMutation.isPending}
            />
          </label>
        </div>
      </div>

      {/* Quiet Hours */}
      <div className="tg-settings-section">
        <h4 className="tg-settings-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          Quiet Hours
        </h4>
        
        <label className="tg-toggle-item">
          <div className="tg-toggle-content">
            <span className="tg-toggle-label">Enable quiet hours</span>
            <span className="tg-toggle-desc">Pause notifications during specific times</span>
          </div>
          <input
            type="checkbox"
            className="tg-toggle"
            checked={settings.quiet_hours_enabled ?? true}
            onChange={(e) => handleSettingToggle('quiet_hours_enabled', e.target.checked)}
            disabled={updateSettingsMutation.isPending}
          />
        </label>

        {settings.quiet_hours_enabled && (
          <div className="tg-quiet-times">
            <div className="tg-time-input">
              <label htmlFor="quiet-start">From</label>
              <input
                id="quiet-start"
                type="time"
                value={settings.quiet_hours_start || '22:00'}
                onChange={(e) => handleTimeChange('quiet_hours_start', e.target.value)}
                disabled={updateSettingsMutation.isPending}
              />
            </div>
            <div className="tg-time-input">
              <label htmlFor="quiet-end">To</label>
              <input
                id="quiet-end"
                type="time"
                value={settings.quiet_hours_end || '08:00'}
                onChange={(e) => handleTimeChange('quiet_hours_end', e.target.value)}
                disabled={updateSettingsMutation.isPending}
              />
            </div>
          </div>
        )}
      </div>

      {/* Disconnect Button */}
      <div className="tg-disconnect-section">
        {!showDisconnectConfirm ? (
          <button 
            className="tg-btn tg-btn-danger-outline"
            onClick={() => setShowDisconnectConfirm(true)}
          >
            Disconnect Telegram
          </button>
        ) : (
          <div className="tg-disconnect-confirm">
            <p className="tg-disconnect-warning">
              Are you sure? You won't receive notifications anymore.
            </p>
            <div className="tg-disconnect-actions">
              <button 
                className="tg-btn tg-btn-outline"
                onClick={() => setShowDisconnectConfirm(false)}
                disabled={unlinkMutation.isPending}
              >
                Cancel
              </button>
              <button 
                className="tg-btn tg-btn-danger"
                onClick={handleDisconnect}
                disabled={unlinkMutation.isPending}
              >
                {unlinkMutation.isPending ? 'Disconnecting...' : 'Yes, Disconnect'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Error messages */}
      {updateSettingsMutation.isError && (
        <div className="tg-error">
          Failed to update settings. Please try again.
        </div>
      )}

      {unlinkMutation.isError && (
        <div className="tg-error">
          Failed to disconnect. Please try again.
        </div>
      )}

      <style>{`
        .tg-connected {
          padding: 1.5rem;
          background: var(--surface, #fff);
          border-radius: 16px;
          border: 1px solid var(--border, #e5e5e5);
        }

        /* Header */
        .tg-connected-header {
          display: flex;
          align-items: center;
          gap: 1rem;
          padding-bottom: 1.25rem;
          margin-bottom: 1.25rem;
          border-bottom: 1px solid var(--border, #e5e5e5);
        }

        .tg-connected-icon {
          width: 48px;
          height: 48px;
          border-radius: 16px;
          background: ${TELEGRAM_BLUE};
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .tg-connected-info {
          flex: 1;
        }

        .tg-connected-status {
          margin-bottom: 0.25rem;
        }

        .tg-status-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.375rem;
          font-size: 0.8rem;
          font-weight: 500;
          color: #22c55e;
        }

        .tg-status-dot {
          width: 8px;
          height: 8px;
          background: #22c55e;
          border-radius: 50%;
          animation: tgPulse 2s infinite;
        }

        @keyframes tgPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }

        .tg-connected-user {
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--text, #333);
        }

        .tg-connected-date {
          font-size: 0.8rem;
          color: var(--muted, #888);
          margin-top: 0.125rem;
        }

        /* Settings Sections */
        .tg-settings-section {
          margin-bottom: 1.5rem;
        }

        .tg-settings-title {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin: 0 0 1rem 0;
          font-size: 0.95rem;
          font-weight: 600;
          color: var(--text, #333);
        }

        /* Toggle List */
        .tg-toggle-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .tg-toggle-item {
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

        .tg-toggle-item:hover {
          background: var(--surface-3, #f0f0f0);
        }

        .tg-toggle-content {
          flex: 1;
        }

        .tg-toggle-label {
          display: block;
          font-weight: 500;
          font-size: 0.9rem;
          color: var(--text, #333);
        }

        .tg-toggle-desc {
          display: block;
          font-size: 0.8rem;
          color: var(--muted, #888);
          margin-top: 0.125rem;
        }

        /* Custom Toggle Switch */
        .tg-toggle {
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

        .tg-toggle:checked {
          background: var(--primary, #7C9070);
        }

        .tg-toggle:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .tg-toggle::before {
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

        .tg-toggle:checked::before {
          transform: translateX(20px);
        }

        /* Quiet Hours Times */
        .tg-quiet-times {
          display: flex;
          gap: 1rem;
          margin-top: 0.75rem;
          padding: 0.75rem;
          background: var(--surface-2, #f9fafb);
          border-radius: 8px;
        }

        .tg-time-input {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 0.375rem;
        }

        .tg-time-input label {
          font-size: 0.8rem;
          font-weight: 500;
          color: var(--muted, #888);
        }

        .tg-time-input input {
          padding: 0.5rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 6px;
          font-size: 0.9rem;
          font-family: inherit;
          background: var(--surface, #fff);
          color: var(--text, #333);
        }

        .tg-time-input input:focus {
          outline: none;
          border-color: var(--primary, #7C9070);
        }

        .tg-time-input input:disabled {
          opacity: 0.5;
        }

        /* Disconnect Section */
        .tg-disconnect-section {
          margin-top: 1.5rem;
          padding-top: 1.5rem;
          border-top: 1px solid var(--border, #e5e5e5);
        }

        .tg-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          padding: 0.625rem 1rem;
          border-radius: 8px;
          font-weight: 500;
          font-size: 0.9rem;
          cursor: pointer;
          transition: all 0.15s;
          border: none;
        }

        .tg-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .tg-btn-outline {
          background: transparent;
          border: 1px solid var(--border, #ddd);
          color: var(--text, #333);
        }

        .tg-btn-outline:hover:not(:disabled) {
          border-color: var(--text, #333);
        }

        .tg-btn-danger-outline {
          background: transparent;
          border: 1px solid rgba(220, 53, 69, 0.5);
          color: #dc3545;
        }

        .tg-btn-danger-outline:hover:not(:disabled) {
          background: rgba(220, 53, 69, 0.05);
          border-color: #dc3545;
        }

        .tg-btn-danger {
          background: #dc3545;
          color: white;
        }

        .tg-btn-danger:hover:not(:disabled) {
          background: #c82333;
        }

        .tg-disconnect-confirm {
          text-align: center;
        }

        .tg-disconnect-warning {
          margin: 0 0 1rem 0;
          color: var(--muted, #666);
          font-size: 0.9rem;
        }

        .tg-disconnect-actions {
          display: flex;
          gap: 0.75rem;
          justify-content: center;
        }

        /* Error */
        .tg-error {
          margin-top: 1rem;
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
          .tg-quiet-times {
            flex-direction: column;
          }

          .tg-disconnect-actions {
            flex-direction: column;
          }

          .tg-disconnect-actions .tg-btn {
            width: 100%;
          }
        }
      `}</style>
    </div>
  )
}
