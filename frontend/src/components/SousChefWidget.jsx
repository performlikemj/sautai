/**
 * SousChefWidget Component
 *
 * Modern chat widget for the Sous Chef AI assistant.
 * Follows 2025 chat UI best practices (Intercom/Drift style).
 * Lives in the bottom-right corner of the chef dashboard.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import FamilySelector from './FamilySelector.jsx'
import SousChefChat from './SousChefChat.jsx'
import WorkspaceSettings from './WorkspaceSettings.jsx'
import SousChefNotificationPanel from './SousChefNotificationPanel.jsx'
import { useSousChefNotifications } from '../contexts/SousChefNotificationContext.jsx'
import { useUnreadCount, useMarkAsRead } from '../hooks/useNotifications'

// Panel size configurations (fixed sizes, no resize)
const PANEL_SIZES = {
  small: { width: 360, height: 480 },
  large: { width: 440, height: 600 },
  xlarge: { width: 520, height: 720 }
}

export default function SousChefWidget({
  onAction,  // Callback for action blocks (navigation/prefill)
}) {
  const navigate = useNavigate()
  const location = useLocation()

  // Hide widget when on the full-page Sous Chef view
  const isOnSousChefPage = location.pathname === '/chefs/dashboard/sous-chef'

  // Notification context (for local/frontend notifications)
  let notifications = null
  try {
    notifications = useSousChefNotifications()
  } catch (e) {
    // Context not available
  }

  // Backend notification count (polls every 30 seconds)
  const { data: backendUnreadCount = 0 } = useUnreadCount({ enabled: true })
  const markReadMutation = useMarkAsRead()

  const [isOpen, setIsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [notifPanelOpen, setNotifPanelOpen] = useState(false)
  const [panelSize, setPanelSize] = useState('small')
  const [screenSize, setScreenSize] = useState('normal')
  const [selectedFamily, setSelectedFamily] = useState({
    familyId: null,
    familyType: 'customer',
    familyName: null
  })
  const [showToast, setShowToast] = useState(false)
  const [toastNotification, setToastNotification] = useState(null)
  const [pendingContext, setPendingContext] = useState(null)

  const widgetRef = useRef(null)
  const prevUnreadCount = useRef(0)
  const chatInputRef = useRef(null)

  // Track if this is the initial mount
  const isInitialMountRef = useRef(true)
  const isMountedRef = useRef(false)

  // Set mounted flag after first render completes
  useEffect(() => {
    isMountedRef.current = true
    return () => { isMountedRef.current = false }
  }, [])

  // Detect screen size for responsive panel sizing
  useEffect(() => {
    const checkScreenSize = () => {
      if (window.innerWidth >= 2400) {
        setScreenSize('ultrawide')
      } else if (window.innerWidth >= 1600) {
        setScreenSize('large')
      } else {
        setScreenSize('normal')
      }
    }

    checkScreenSize()
    window.addEventListener('resize', checkScreenSize)
    return () => window.removeEventListener('resize', checkScreenSize)
  }, [])

  // Watch for new notifications and show toast
  useEffect(() => {
    if (!notifications || !isMountedRef.current) return

    const currentCount = notifications.unreadCount

    // Skip the first render to avoid setState during initial mount cascade
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false
      prevUnreadCount.current = currentCount
      return
    }

    // Defer the state updates to avoid render-phase updates
    const timeoutId = setTimeout(() => {
      if (!isMountedRef.current) return

      const latestUnread = notifications.getLatestUnread()

      // New notification arrived
      if (currentCount > prevUnreadCount.current && latestUnread) {
        setToastNotification(latestUnread)
        setShowToast(true)

        // Auto-hide toast after 8 seconds
        setTimeout(() => {
          if (isMountedRef.current) {
            setShowToast(false)
          }
        }, 8000)
      }

      prevUnreadCount.current = currentCount
    }, 0)

    return () => clearTimeout(timeoutId)
  }, [notifications?.unreadCount])

  // Handle clicking on toast notification
  const handleToastClick = useCallback(() => {
    if (!toastNotification || !notifications) return

    // Store context for Sous Chef
    if (toastNotification.context) {
      setPendingContext(toastNotification.context)
    }

    // Mark as read
    notifications.markAsRead(toastNotification.id)

    // Open widget
    setIsOpen(true)
    setShowToast(false)
  }, [toastNotification, notifications])

  // Handle dismissing toast
  const handleDismissToast = useCallback((e) => {
    e.stopPropagation()
    setShowToast(false)
    if (toastNotification && notifications) {
      notifications.markAsRead(toastNotification.id)
    }
  }, [toastNotification, notifications])

  const handleFamilySelect = useCallback((family) => {
    setSelectedFamily(family)
  }, [])

  const toggleWidget = useCallback(() => {
    setIsOpen(prev => {
      // When opening the widget, mark all notifications as read
      if (!prev && notifications?.markAllAsRead) {
        notifications.markAllAsRead()
      }
      return !prev
    })
  }, [notifications])

  const handleMinimize = useCallback(() => {
    setIsOpen(false)
  }, [])

  const toggleSize = useCallback(() => {
    // On large screens, cycle through three sizes: small -> large -> xlarge -> small
    if (screenSize === 'large' || screenSize === 'ultrawide') {
      setPanelSize(prev => {
        if (prev === 'small') return 'large'
        if (prev === 'large') return 'xlarge'
        return 'small'
      })
    } else {
      // On normal screens, just toggle between small and large
      setPanelSize(prev => prev === 'small' ? 'large' : 'small')
    }
  }, [screenSize])

  // Navigate to full page view
  const navigateToFullPage = useCallback(() => {
    // Capture the current draft input before navigating
    const draftInput = chatInputRef.current?.value || ''

    const params = new URLSearchParams()
    if (selectedFamily.familyId) {
      params.set('familyId', selectedFamily.familyId)
      params.set('familyType', selectedFamily.familyType)
      if (selectedFamily.familyName) {
        params.set('familyName', selectedFamily.familyName)
      }
    }
    const queryString = params.toString()
    // Pass draft input via router state
    navigate(`/chefs/dashboard/sous-chef${queryString ? `?${queryString}` : ''}`, {
      state: { draftInput }
    })
  }, [navigate, selectedFamily])

  // Combine frontend and backend notification counts
  const frontendUnreadCount = notifications?.unreadCount || 0
  const unreadCount = frontendUnreadCount + backendUnreadCount
  const currentSize = PANEL_SIZES[panelSize]

  // Don't render if on the full-page Sous Chef view
  if (isOnSousChefPage) {
    return null
  }

  return (
    <div className="sous-chef-widget" ref={widgetRef}>
      {/* Toast Notification */}
      {showToast && toastNotification && (
        <div className="sc-toast" onClick={handleToastClick} onKeyDown={(e) => e.key === 'Enter' && handleToastClick()} role="alert" tabIndex={0}>
          <div className="sc-toast-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
            </svg>
          </div>
          <div className="sc-toast-content">
            <div className="sc-toast-title">{toastNotification.title}</div>
            <div className="sc-toast-message">{toastNotification.message}</div>
          </div>
          <button
            className="sc-toast-dismiss"
            onClick={handleDismissToast}
            aria-label="Dismiss"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
      )}

      {/* Chat Panel */}
      {isOpen && (
        <div
          className="sc-panel"
          style={{ width: currentSize.width, height: currentSize.height }}
        >
          {/* Panel Header */}
          <div className="sc-header">
            <div className="sc-header-left">
              <div className="sc-header-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
                </svg>
              </div>
              <span className="sc-header-title">Sous Chef</span>
            </div>
            <div className="sc-header-actions">
              {/* Notification Bell */}
              <button
                className="sc-header-btn sc-notif-btn"
                onClick={() => setNotifPanelOpen(!notifPanelOpen)}
                aria-label="Notifications"
                title="Notifications"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                </svg>
                {unreadCount > 0 && (
                  <span className="sc-header-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>
                )}
              </button>
              <button
                className="sc-header-btn"
                onClick={() => setSettingsOpen(true)}
                aria-label="Workspace Settings"
                title="Customize Sous Chef"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                </svg>
              </button>
              <button
                className="sc-header-btn"
                onClick={handleMinimize}
                aria-label="Minimize"
                title="Minimize"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14"/>
                </svg>
              </button>
              <button
                className="sc-header-btn"
                onClick={toggleSize}
                aria-label={panelSize === 'small' ? 'Expand' : 'Shrink'}
                title={panelSize === 'small' ? 'Expand' : 'Shrink'}
              >
                {panelSize === 'small' ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>
                  </svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M4 14h6v6M14 4h6v6M20 10l-7 7M4 14l7-7"/>
                  </svg>
                )}
              </button>
              <button
                className="sc-header-btn"
                onClick={navigateToFullPage}
                aria-label="Open full page"
                title="Open full page"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                  <polyline points="15 3 21 3 21 9"/>
                  <line x1="10" y1="14" x2="21" y2="3"/>
                </svg>
              </button>
              <button
                className="sc-header-btn sc-close-btn"
                onClick={toggleWidget}
                aria-label="Close"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
              </button>
            </div>
          </div>

          {/* Client Selector Dropdown */}
          <div className="sc-client-selector">
            {pendingContext && !selectedFamily.familyId && (
              <div className="sc-context-hint">
                Select <strong>{pendingContext.clientName || 'the client'}</strong> to see the AI suggestion
              </div>
            )}
            <FamilySelector
              selectedFamilyId={selectedFamily.familyId}
              selectedFamilyType={selectedFamily.familyType}
              onFamilySelect={handleFamilySelect}
              className="sc-family-selector"
            />
          </div>

          {/* Chat Area */}
          <div className="sc-chat-area">
            <SousChefChat
              familyId={selectedFamily.familyId}
              familyType={selectedFamily.familyType}
              familyName={selectedFamily.familyName}
              initialContext={pendingContext}
              onContextHandled={() => setPendingContext(null)}
              externalInputRef={chatInputRef}
              onAction={onAction}
            />
          </div>
        </div>
      )}

      {/* Launcher Button */}
      <button
        className={`sc-launcher ${isOpen ? 'sc-launcher--open' : ''}`}
        onClick={toggleWidget}
        aria-label={isOpen ? 'Close Sous Chef' : 'Open Sous Chef'}
        title="Sous Chef Assistant"
      >
        {isOpen ? (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        ) : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            <path d="M12 7v.01M12 11v.01M12 15v.01" strokeLinecap="round"/>
          </svg>
        )}
        {!isOpen && unreadCount > 0 && (
          <span className="sc-launcher-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>
        )}
      </button>

      {/* Workspace Settings Modal */}
      <WorkspaceSettings
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      {/* Notification Panel */}
      <SousChefNotificationPanel
        isOpen={notifPanelOpen}
        onClose={() => setNotifPanelOpen(false)}
        onNotificationClick={(notif) => {
          // Mark as read on backend
          if (notif.id) {
            markReadMutation.mutate(notif.id)
          }
          // Store context and open chat
          if (notif.context) {
            setPendingContext({
              clientName: notif.context?.client_name || notif.context?.clientName,
              familyId: notif.context?.family_id || notif.context?.familyId,
              ...notif.context
            })
          }
          setNotifPanelOpen(false)
          setIsOpen(true)
        }}
      />

      <style>{`
        /* ============================================
           SOUS CHEF WIDGET - MODERN CHAT UI
           ============================================ */

        .sous-chef-widget {
          position: fixed;
          bottom: 24px;
          right: 24px;
          z-index: 1000;
          font-family: inherit;
        }

        /* ─────────────────────────────────────────────
           LAUNCHER BUTTON (Minimal Icon Style)
           ───────────────────────────────────────────── */
        .sc-launcher {
          width: 52px;
          height: 52px;
          border-radius: 50%;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          background: var(--sc-surface, var(--surface, #fff));
          color: var(--sc-primary, var(--primary, #7C9070));
          cursor: pointer;
          box-shadow: var(--sc-shadow, 0 4px 12px rgba(0, 0, 0, 0.1));
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
        }

        .sc-launcher:hover {
          border-color: var(--sc-primary, var(--primary, #7C9070));
          box-shadow: var(--sc-shadow-hover, 0 6px 16px rgba(0, 0, 0, 0.15));
          transform: translateY(-1px);
        }

        .sc-launcher--open {
          background: var(--sc-primary, var(--primary, #7C9070));
          border-color: var(--sc-primary, var(--primary, #7C9070));
          color: white;
        }

        .sc-launcher--open:hover {
          background: var(--sc-primary-hover, var(--primary-700, #4a9d4a));
          border-color: var(--sc-primary-hover, var(--primary-700, #4a9d4a));
        }

        .sc-launcher svg {
          flex-shrink: 0;
        }

        /* Notification Badge */
        .sc-launcher-badge {
          position: absolute;
          top: -4px;
          right: -4px;
          min-width: 18px;
          height: 18px;
          background: var(--danger, #ef4444);
          color: white;
          font-size: 0.65rem;
          font-weight: 600;
          border-radius: 9px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 0 4px;
          animation: sc-badge-pop 0.3s ease;
        }

        @keyframes sc-badge-pop {
          0% { transform: scale(0); }
          50% { transform: scale(1.2); }
          100% { transform: scale(1); }
        }

        /* ─────────────────────────────────────────────
           TOAST NOTIFICATION
           ───────────────────────────────────────────── */
        .sc-toast {
          position: absolute;
          bottom: 64px;
          right: 0;
          width: 300px;
          background: var(--sc-surface, var(--surface, #fff));
          border-radius: 16px;
          box-shadow: 0 4px 20px rgba(27, 58, 45, 0.15);
          display: flex;
          align-items: flex-start;
          padding: 12px;
          gap: 12px;
          cursor: pointer;
          animation: sc-toast-slide 0.3s ease;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          color: var(--text);
        }

        @keyframes sc-toast-slide {
          from {
            opacity: 0;
            transform: translateX(16px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        .sc-toast:hover {
          box-shadow: 0 6px 24px rgba(27, 58, 45, 0.2);
        }

        .sc-toast-icon {
          width: 36px;
          height: 36px;
          background: var(--sc-primary, var(--primary, #7C9070));
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          color: white;
        }

        .sc-toast-content {
          flex: 1;
          min-width: 0;
        }

        .sc-toast-title {
          font-weight: 600;
          font-size: 0.875rem;
          color: var(--text);
          margin-bottom: 2px;
        }

        .sc-toast-message {
          font-size: 0.8rem;
          color: var(--muted);
          line-height: 1.4;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .sc-toast-dismiss {
          background: none;
          border: none;
          color: var(--muted);
          cursor: pointer;
          padding: 4px;
          opacity: 0.6;
          transition: opacity 0.15s;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .sc-toast-dismiss:hover {
          opacity: 1;
        }

        /* ─────────────────────────────────────────────
           CHAT PANEL
           ───────────────────────────────────────────── */
        .sc-panel {
          position: absolute;
          bottom: 64px;
          right: 0;
          background: var(--sc-surface, var(--surface, #fff));
          border-radius: 20px;
          box-shadow: 0 8px 32px rgba(27, 58, 45, 0.15);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          animation: sc-panel-open 0.2s ease-out;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          color: var(--text);
        }

        @keyframes sc-panel-open {
          from {
            opacity: 0;
            transform: scale(0.95) translateY(8px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }

        /* ─────────────────────────────────────────────
           PANEL HEADER (Simplified)
           ───────────────────────────────────────────── */
        .sc-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--sc-border, var(--border, #e5e7eb));
          background: var(--sc-surface, var(--surface, #fff));
        }

        .sc-header-left {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .sc-header-icon {
          width: 32px;
          height: 32px;
          background: var(--sc-primary, var(--primary, #7C9070));
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
        }

        .sc-header-title {
          font-weight: 600;
          font-size: 1rem;
          color: var(--text);
        }

        .sc-header-actions {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .sc-header-btn {
          width: 28px;
          height: 28px;
          border: none;
          background: transparent;
          border-radius: 6px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--muted);
          transition: all 0.15s;
        }

        .sc-header-btn:hover {
          background: var(--sc-surface-2, var(--surface-2, #f3f4f6));
          color: var(--text);
        }

        .sc-close-btn:hover {
          background: rgba(239, 68, 68, 0.1);
          color: var(--danger, #ef4444);
        }

        /* Notification button with badge */
        .sc-notif-btn {
          position: relative;
        }

        .sc-header-badge {
          position: absolute;
          top: -2px;
          right: -2px;
          min-width: 14px;
          height: 14px;
          background: var(--danger, #ef4444);
          color: white;
          font-size: 0.6rem;
          font-weight: 600;
          border-radius: 7px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 0 3px;
          animation: sc-badge-pop 0.3s ease;
        }

        /* ─────────────────────────────────────────────
           CLIENT SELECTOR (Dropdown in header area)
           ───────────────────────────────────────────── */
        .sc-client-selector {
          padding: 8px 12px;
          border-bottom: 1px solid var(--sc-border, var(--border, #e5e7eb));
          background: var(--sc-surface-2, var(--surface-2, #f9fafb));
        }

        .sc-context-hint {
          background: var(--success-bg);
          border: 1px solid var(--success);
          color: var(--text);
          padding: 8px 10px;
          border-radius: 8px;
          font-size: 0.8rem;
          margin-bottom: 8px;
          text-align: center;
        }

        .sc-context-hint strong {
          color: var(--primary);
        }

        .sc-client-selector .family-selector-trigger {
          padding: 0.4rem 0.6rem;
          font-size: 0.85rem;
        }

        .sc-client-selector .family-avatar {
          width: 28px;
          height: 28px;
          font-size: 0.9rem;
        }

        .sc-client-selector .family-name {
          font-size: 0.85rem;
        }

        .sc-client-selector .family-meta {
          font-size: 0.7rem;
        }

        /* ─────────────────────────────────────────────
           CHAT AREA
           ───────────────────────────────────────────── */
        .sc-chat-area {
          flex: 1;
          min-height: 0;
          display: flex;
          flex-direction: column;
        }

        .sc-chat-area .sc-chat {
          height: 100%;
          border-radius: 0;
        }

        /* Hide redundant elements in widget mode - info already in family selector */
        .sc-chat-area .sc-chat-header {
          display: none;
        }

        .sc-chat-area .sc-context {
          display: none;
        }

        .sc-chat-area .sc-messages {
          padding: 12px;
        }

        .sc-chat-area .sc-welcome-content {
          padding: 12px;
        }

        .sc-chat-area .sc-welcome-icon {
          font-size: 1.75rem;
          margin-bottom: 8px;
        }

        .sc-chat-area .sc-welcome-content h3 {
          font-size: 0.9rem;
          margin-bottom: 4px;
        }

        .sc-chat-area .sc-welcome-content p {
          font-size: 0.75rem;
          line-height: 1.4;
        }

        .sc-chat-area .sc-quick-actions {
          margin-top: 10px;
          gap: 6px;
        }

        .sc-chat-area .sc-quick-action {
          padding: 6px 10px;
          font-size: 0.75rem;
        }

        .sc-chat-area .sc-quick-action-icon {
          font-size: 0.85rem;
        }

        .sc-chat-area .sc-bubble {
          padding: 10px 14px;
          max-width: 85%;
          font-size: 0.85rem;
        }

        .sc-chat-area .sc-composer {
          padding: 10px 12px;
        }

        .sc-chat-area .sc-composer-input {
          font-size: 0.85rem;
          padding: 8px 0;
        }

        /* ─────────────────────────────────────────────
           MOBILE STYLES
           ───────────────────────────────────────────── */
        @media (max-width: 480px) {
          .sous-chef-widget {
            bottom: 16px;
            right: 16px;
          }

          .sc-launcher {
            width: 48px;
            height: 48px;
          }

          .sc-panel {
            position: fixed;
            bottom: 0;
            right: 0;
            left: 0;
            width: 100% !important;
            height: calc(100vh - 60px) !important;
            max-height: none;
            border-radius: 20px 20px 0 0;
            animation: sc-panel-slide-up 0.3s ease-out;
          }

          @keyframes sc-panel-slide-up {
            from {
              opacity: 0;
              transform: translateY(100%);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }

          /* Bottom sheet drag handle */
          .sc-header::before {
            content: '';
            position: absolute;
            top: 8px;
            left: 50%;
            transform: translateX(-50%);
            width: 36px;
            height: 4px;
            background: var(--sc-border, var(--border, #e5e7eb));
            border-radius: 2px;
          }

          .sc-header {
            position: relative;
            padding-top: 20px;
          }

          .sc-toast {
            width: calc(100vw - 32px);
            right: 0;
            left: 16px;
            bottom: 72px;
          }
        }

        /* ─────────────────────────────────────────────
           LARGE SCREEN RESPONSIVE
           ───────────────────────────────────────────── */

        /* Large screens - wider widget position and launcher */
        @media (min-width: 1600px) {
          .sous-chef-widget {
            bottom: 28px;
            right: 28px;
          }

          .sc-launcher {
            width: 56px;
            height: 56px;
          }
        }

        @media (min-width: 1920px) {
          .sous-chef-widget {
            bottom: 32px;
            right: 32px;
          }
        }

        /* Allow larger panel heights on tall screens */
        @media (min-height: 900px) {
          .sc-panel {
            max-height: 80vh;
          }
        }

        @media (min-height: 1200px) {
          .sc-panel {
            max-height: 85vh;
          }
        }

        /* ─────────────────────────────────────────────
           DARK MODE ADJUSTMENTS
           ───────────────────────────────────────────── */
        [data-theme="dark"] .sc-launcher {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        [data-theme="dark"] .sc-launcher:hover {
          box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
        }

        [data-theme="dark"] .sc-panel {
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }

        [data-theme="dark"] .sc-toast {
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
      `}</style>
    </div>
  )
}
