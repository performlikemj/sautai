/**
 * TelegramSettings Component
 *
 * Main container for Telegram integration settings.
 * Shows TelegramConnect when not linked, TelegramConnected when linked.
 * Can be used standalone or embedded in a modal/settings page.
 */

import React from 'react'
import { useTelegramStatus } from '../../hooks/useTelegram'
import TelegramConnect from './TelegramConnect'
import TelegramConnected from './TelegramConnected'

/**
 * TelegramSettings - Container for Telegram account management
 */
export default function TelegramSettings() {
  const { data: status, isLoading, error } = useTelegramStatus()

  if (isLoading) {
    return (
      <div className="tg-settings-loading">
        <div className="tg-loading-spinner" />
        <span>Loading Telegram settings...</span>
        
        <style>{`
          .tg-settings-loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1rem;
            padding: 3rem 1.5rem;
            background: var(--surface, #fff);
            border-radius: 12px;
            border: 1px solid var(--border, #e5e5e5);
            color: var(--muted, #888);
          }

          .tg-loading-spinner {
            width: 32px;
            height: 32px;
            border: 3px solid var(--border, #e5e5e5);
            border-top-color: var(--primary, #7C9070);
            border-radius: 50%;
            animation: tgLoadSpin 0.8s linear infinite;
          }

          @keyframes tgLoadSpin {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    )
  }

  if (error) {
    return (
      <div className="tg-settings-error">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="32" height="32">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>Failed to load Telegram settings</p>
        <button 
          className="tg-retry-btn"
          onClick={() => window.location.reload()}
        >
          Try Again
        </button>
        
        <style>{`
          .tg-settings-error {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1rem;
            padding: 3rem 1.5rem;
            background: var(--surface, #fff);
            border-radius: 12px;
            border: 1px solid var(--border, #e5e5e5);
            color: var(--muted, #888);
            text-align: center;
          }

          .tg-settings-error svg {
            color: #dc3545;
          }

          .tg-settings-error p {
            margin: 0;
          }

          .tg-retry-btn {
            padding: 0.5rem 1rem;
            background: var(--primary, #7C9070);
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.15s;
          }

          .tg-retry-btn:hover {
            background: var(--primary-700, #449d44);
          }
        `}</style>
      </div>
    )
  }

  // Show appropriate component based on link status
  return status?.linked ? (
    <TelegramConnected status={status} />
  ) : (
    <TelegramConnect />
  )
}

// Also export sub-components for flexibility
export { default as TelegramConnect } from './TelegramConnect'
export { default as TelegramConnected } from './TelegramConnected'
