/**
 * SousChefPage Component
 *
 * Full-page view for the Sous Chef AI assistant.
 * Clean, centered layout with back navigation.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import FamilySelector from '../components/FamilySelector.jsx'
import SousChefChat from '../components/SousChefChat.jsx'
import WorkspaceSettings from '../components/WorkspaceSettings.jsx'
import { api } from '../api.js'

export default function SousChefPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()

  // Read initial family from URL params
  const initialFamilyId = searchParams.get('familyId')
  const initialFamilyType = searchParams.get('familyType') || 'customer'
  const initialFamilyName = searchParams.get('familyName')

  // Read draft input from router state (passed from widget expansion)
  const draftInput = location.state?.draftInput || ''

  const [selectedFamily, setSelectedFamily] = useState({
    familyId: initialFamilyId ? parseInt(initialFamilyId, 10) : null,
    familyType: initialFamilyType,
    familyName: initialFamilyName
  })

  const [chefEmoji, setChefEmoji] = useState('🧑‍🍳')
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Load chef's sous chef emoji on mount
  useEffect(() => {
    api.get('/chefs/api/me/chef/profile/').then(res => {
      if (res.data?.sous_chef_emoji) {
        setChefEmoji(res.data.sous_chef_emoji)
      }
    }).catch(() => {})
  }, [])

  const handleFamilySelect = useCallback((family) => {
    setSelectedFamily(family)
    // Update URL params to preserve state on refresh
    const params = new URLSearchParams()
    if (family.familyId) {
      params.set('familyId', family.familyId)
      params.set('familyType', family.familyType)
      if (family.familyName) {
        params.set('familyName', family.familyName)
      }
    }
    navigate(`/chefs/dashboard/sous-chef?${params.toString()}`, { replace: true })
  }, [navigate])

  const handleBack = useCallback(() => {
    navigate('/chefs/dashboard')
  }, [navigate])

  // Handle actions from Sous Chef (navigation, prefill, etc.)
  const handleSousChefAction = useCallback((action) => {
    if (action.action_type === 'navigate') {
      const tab = action.payload?.tab || action.payload?.tab_name
      if (tab) {
        navigate(`/chefs/dashboard?tab=${tab}`)
      }
    }
  }, [navigate])

  return (
    <div className="sc-page">
      {/* Header */}
      <header className="sc-page-header">
        <div className="sc-page-header-content">
          <div className="sc-page-header-left">
            <button className="sc-back-btn" onClick={handleBack} aria-label="Back to Dashboard">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
              <span className="sc-back-label">Dashboard</span>
            </button>
          </div>

          <div className="sc-page-header-center">
            <div className="sc-page-title-group">
              <div className="sc-page-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
                </svg>
              </div>
              <h1 className="sc-page-title">Sous Chef</h1>
              <button
                className="sc-settings-btn"
                onClick={() => setSettingsOpen(true)}
                aria-label="Workspace Settings"
                title="Customize Sous Chef"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                </svg>
              </button>
            </div>
          </div>

          <div className="sc-page-header-right">
            <div className="sc-page-client-selector">
              <FamilySelector
                selectedFamilyId={selectedFamily.familyId}
                selectedFamilyType={selectedFamily.familyType}
                onFamilySelect={handleFamilySelect}
                compact
              />
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="sc-page-main">
        <div className="sc-page-chat-container">
          {/* General mode banner */}
          {!selectedFamily.familyId && (
            <div className="sc-page-banner">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
              </svg>
              <span>
                <strong>General Mode</strong> — Select a client from the dropdown above for personalized assistance.
              </span>
            </div>
          )}

          {/* Chat */}
          <SousChefChat
            familyId={selectedFamily.familyId}
            familyType={selectedFamily.familyType}
            familyName={selectedFamily.familyName || (selectedFamily.familyId ? null : 'General Assistant')}
            chefEmoji={chefEmoji}
            initialInput={draftInput}
            onAction={handleSousChefAction}
          />
        </div>
      </main>

      {/* Workspace Settings Modal */}
      <WorkspaceSettings
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      <style>{`
        /* ============================================
           SOUS CHEF PAGE - FULL PAGE VIEW
           ============================================ */

        .sc-page {
          min-height: calc(100vh - 60px);
          display: flex;
          flex-direction: column;
          background: var(--sc-bg, var(--surface-2, #f5f5f5));
          color: var(--text);
        }

        /* ─────────────────────────────────────────────
           HEADER
           ───────────────────────────────────────────── */
        .sc-page-header {
          background: var(--sc-surface, var(--surface, #fff));
          border-bottom: 1px solid var(--sc-border, var(--border, #e5e7eb));
          position: sticky;
          top: 0;
          z-index: 100;
        }

        .sc-page-header-content {
          max-width: 1200px;
          margin: 0 auto;
          padding: 12px 24px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
        }

        .sc-page-header-left {
          flex: 1;
          display: flex;
          align-items: center;
        }

        .sc-back-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          background: transparent;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          border-radius: 8px;
          color: var(--text);
          font-size: 0.875rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .sc-back-btn:hover {
          background: var(--sc-surface-2, var(--surface-2, #f9fafb));
          border-color: var(--sc-primary, var(--primary, #7C9070));
          color: var(--sc-primary, var(--primary, #7C9070));
        }

        .sc-back-label {
          display: inline;
        }

        .sc-page-header-center {
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .sc-page-title-group {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .sc-page-icon {
          width: 36px;
          height: 36px;
          background: var(--sc-primary, var(--primary, #7C9070));
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
        }

        .sc-page-title {
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
          color: var(--text);
        }

        .sc-settings-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          background: transparent;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          border-radius: 8px;
          color: var(--muted, #888);
          cursor: pointer;
          transition: all 0.15s ease;
          margin-left: 8px;
        }

        .sc-settings-btn:hover {
          background: var(--sc-surface-2, var(--surface-2, #f9fafb));
          border-color: var(--sc-primary, var(--primary, #7C9070));
          color: var(--sc-primary, var(--primary, #7C9070));
        }

        .sc-page-header-right {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: flex-end;
        }

        .sc-page-client-selector {
          min-width: 200px;
          max-width: 280px;
        }

        /* ─────────────────────────────────────────────
           MAIN CONTENT
           ───────────────────────────────────────────── */
        .sc-page-main {
          flex: 1;
          display: flex;
          flex-direction: column;
          padding: 24px;
          min-height: 0;
        }

        .sc-page-chat-container {
          flex: 1;
          display: flex;
          flex-direction: column;
          max-width: 800px;
          width: 100%;
          margin: 0 auto;
          background: var(--sc-surface, var(--surface, #fff));
          border-radius: 20px;
          box-shadow: 0 1px 3px rgba(27, 58, 45, 0.06);
          overflow: hidden;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
        }

        .sc-page-chat-container .sc-chat {
          flex: 1;
          height: 100%;
          border-radius: 0;
        }

        /* Show context panel and chat header in full page mode */
        .sc-page-chat-container .sc-context {
          display: block;
        }

        .sc-page-chat-container .sc-chat-header {
          display: flex;
        }

        /* ─────────────────────────────────────────────
           BANNER
           ───────────────────────────────────────────── */
        .sc-page-banner {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          background: linear-gradient(135deg, rgba(124, 144, 112, 0.08) 0%, rgba(124, 144, 112, 0.04) 100%);
          border-bottom: 1px solid rgba(124, 144, 112, 0.15);
          font-size: 0.875rem;
          color: var(--text);
        }

        .sc-page-banner svg {
          color: var(--sc-primary, var(--primary, #7C9070));
          flex-shrink: 0;
        }

        .sc-page-banner strong {
          color: var(--sc-primary, var(--primary, #7C9070));
        }

        /* ─────────────────────────────────────────────
           RESPONSIVE
           ───────────────────────────────────────────── */
        @media (max-width: 768px) {
          .sc-page-header-content {
            padding: 10px 16px;
            flex-wrap: wrap;
          }

          .sc-page-header-center {
            order: -1;
            width: 100%;
            justify-content: flex-start;
            margin-bottom: 10px;
          }

          .sc-page-header-left {
            flex: 0;
          }

          .sc-back-label {
            display: none;
          }

          .sc-back-btn {
            padding: 8px;
          }

          .sc-page-header-right {
            flex: 1;
          }

          .sc-page-client-selector {
            min-width: 160px;
            max-width: none;
            flex: 1;
          }

          .sc-page-main {
            padding: 16px;
          }

          .sc-page-chat-container {
            border-radius: 16px;
          }

          .sc-page-title {
            font-size: 1.1rem;
          }

          .sc-page-icon {
            width: 32px;
            height: 32px;
          }

          .sc-page-icon svg {
            width: 16px;
            height: 16px;
          }
        }

        @media (max-width: 480px) {
          .sc-page-main {
            padding: 12px;
          }

          .sc-page-chat-container {
            border-radius: 10px;
          }

          .sc-page-banner {
            padding: 10px 12px;
            font-size: 0.8rem;
          }
        }

        /* ─────────────────────────────────────────────
           LARGE SCREEN RESPONSIVE
           ───────────────────────────────────────────── */

        /* Large desktop (1600px+) */
        @media (min-width: 1600px) {
          .sc-page-header-content {
            max-width: 1400px;
          }

          .sc-page-chat-container {
            max-width: 1000px;
          }

          .sc-page-main {
            padding: 28px;
          }
        }

        /* Extra-large screens (1920px+ / 27" monitors) */
        @media (min-width: 1920px) {
          .sc-page-header-content {
            max-width: 1600px;
          }

          .sc-page-chat-container {
            max-width: 1100px;
          }

          .sc-page-main {
            padding: 32px;
          }
        }

        /* Superwide screens (2400px+ / 32" monitors) */
        @media (min-width: 2400px) {
          .sc-page-header-content {
            max-width: 2000px;
          }

          .sc-page-chat-container {
            max-width: 1300px;
          }

          .sc-page-main {
            padding: 40px;
          }
        }

        /* Ultrawide screens (3200px+ / 4K displays) */
        @media (min-width: 3200px) {
          .sc-page-header-content {
            max-width: 2400px;
          }

          .sc-page-chat-container {
            max-width: 1500px;
          }
        }
      `}</style>
    </div>
  )
}
