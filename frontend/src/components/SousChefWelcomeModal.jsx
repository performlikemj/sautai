/**
 * SousChefWelcomeModal
 * 
 * First-time welcome modal for new chefs.
 * Shows when ChefOnboardingState.welcomed === false.
 * Has "Don't show this again" option to prevent accidental dismissal
 * while also not being annoying.
 */

import React, { useState, useEffect, useCallback } from 'react'

const API_BASE = '/chefs/api/me/onboarding/'

export default function SousChefWelcomeModal({ onStartSetup, onSkip }) {
  const [visible, setVisible] = useState(false)
  const [loading, setLoading] = useState(true)
  const [dontShowAgain, setDontShowAgain] = useState(false)
  const [onboardingState, setOnboardingState] = useState(null)

  // Check onboarding state on mount
  useEffect(() => {
    const checkOnboarding = async () => {
      try {
        const token = localStorage.getItem('access_token')
        if (!token) {
          setLoading(false)
          return
        }

        const response = await fetch(API_BASE, {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        })

        if (!response.ok) {
          setLoading(false)
          return
        }

        const data = await response.json()
        
        if (data.status === 'success' && data.onboarding) {
          setOnboardingState(data.onboarding)
          
          // Show modal if not welcomed AND not skipped
          if (!data.onboarding.welcomed && !data.onboarding.setup_skipped) {
            setVisible(true)
          }
        }
      } catch (err) {
        console.error('Error checking onboarding state:', err)
      } finally {
        setLoading(false)
      }
    }

    checkOnboarding()
  }, [])

  // Mark as welcomed on backend
  const markWelcomed = useCallback(async () => {
    try {
      const token = localStorage.getItem('access_token')
      if (!token) return

      await fetch(`${API_BASE}welcomed/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })
    } catch (err) {
      console.error('Error marking welcomed:', err)
    }
  }, [])

  // Mark as skipped on backend (for "don't show again")
  const markSkipped = useCallback(async () => {
    try {
      const token = localStorage.getItem('access_token')
      if (!token) return

      await fetch(`${API_BASE}skip/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })
    } catch (err) {
      console.error('Error marking skipped:', err)
    }
  }, [])

  const handleStartSetup = async () => {
    await markWelcomed()
    setVisible(false)
    onStartSetup?.()
  }

  const handleSkip = async () => {
    if (dontShowAgain) {
      await markSkipped()
    } else {
      await markWelcomed()
    }
    setVisible(false)
    onSkip?.()
  }

  const handleClose = async () => {
    // Just close without marking - will show again next time
    // Unless "don't show again" is checked
    if (dontShowAgain) {
      await markSkipped()
    }
    setVisible(false)
  }

  if (loading || !visible) return null

  return (
    <div className="sc-welcome-overlay" onClick={handleClose}>
      <div 
        className="sc-welcome-modal" 
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-title"
      >
        {/* Close button */}
        <button 
          className="sc-welcome-close" 
          onClick={handleClose}
          aria-label="Close"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>

        {/* Icon */}
        <div className="sc-welcome-icon">🧑‍🍳</div>

        {/* Content */}
        <h2 id="welcome-title" className="sc-welcome-title">
          Hey, I'm your Sous Chef!
        </h2>
        
        <p className="sc-welcome-description">
          Think of me as your kitchen partner who never forgets a detail. I can help you:
        </p>

        <ul className="sc-welcome-features">
          <li>
            <span className="feature-icon">🧠</span>
            Remember every client's preferences & allergies
          </li>
          <li>
            <span className="feature-icon">📋</span>
            Plan menus that work for their households
          </li>
          <li>
            <span className="feature-icon">📝</span>
            Keep track of what's worked before
          </li>
        </ul>

        <p className="sc-welcome-cta">
          Want me to help you set up a few things?
        </p>

        {/* Actions */}
        <div className="sc-welcome-actions">
          <button 
            className="sc-welcome-btn sc-welcome-btn--primary"
            onClick={handleStartSetup}
          >
            Let's do it →
          </button>
          <button 
            className="sc-welcome-btn sc-welcome-btn--secondary"
            onClick={handleSkip}
          >
            I'll explore on my own
          </button>
        </div>

        {/* Don't show again checkbox */}
        <label className="sc-welcome-checkbox">
          <input
            type="checkbox"
            checked={dontShowAgain}
            onChange={(e) => setDontShowAgain(e.target.checked)}
          />
          <span>Don't show this again</span>
        </label>

        <style>{`
          .sc-welcome-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
            animation: sc-overlay-fade 0.2s ease;
            padding: 16px;
          }

          @keyframes sc-overlay-fade {
            from { opacity: 0; }
            to { opacity: 1; }
          }

          .sc-welcome-modal {
            background: var(--surface, #fff);
            border-radius: 20px;
            padding: 32px;
            max-width: 480px;
            width: 100%;
            position: relative;
            animation: sc-modal-pop 0.3s ease;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            color: var(--text);
          }

          @keyframes sc-modal-pop {
            from {
              opacity: 0;
              transform: scale(0.9) translateY(20px);
            }
            to {
              opacity: 1;
              transform: scale(1) translateY(0);
            }
          }

          .sc-welcome-close {
            position: absolute;
            top: 16px;
            right: 16px;
            background: none;
            border: none;
            cursor: pointer;
            color: var(--muted);
            padding: 4px;
            border-radius: 6px;
            transition: all 0.15s;
          }

          .sc-welcome-close:hover {
            background: var(--surface-2, #f3f4f6);
            color: var(--text);
          }

          .sc-welcome-icon {
            font-size: 3rem;
            text-align: center;
            margin-bottom: 16px;
          }

          .sc-welcome-title {
            font-size: 1.5rem;
            font-weight: 700;
            text-align: center;
            margin: 0 0 12px 0;
            color: var(--text);
          }

          .sc-welcome-description {
            text-align: center;
            color: var(--muted);
            margin: 0 0 20px 0;
            font-size: 0.95rem;
            line-height: 1.5;
          }

          .sc-welcome-features {
            list-style: none;
            padding: 0;
            margin: 0 0 20px 0;
            display: flex;
            flex-direction: column;
            gap: 12px;
          }

          .sc-welcome-features li {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: var(--surface-2, #f9fafb);
            border-radius: 10px;
            font-size: 0.9rem;
          }

          .feature-icon {
            font-size: 1.25rem;
            flex-shrink: 0;
          }

          .sc-welcome-cta {
            text-align: center;
            font-weight: 500;
            color: var(--text);
            margin: 0 0 20px 0;
          }

          .sc-welcome-actions {
            display: flex;
            flex-direction: column;
            gap: 10px;
          }

          .sc-welcome-btn {
            width: 100%;
            padding: 14px 24px;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s;
            border: none;
          }

          .sc-welcome-btn--primary {
            background: var(--primary, #7C9070);
            color: white;
          }

          .sc-welcome-btn--primary:hover {
            background: var(--primary-700, #4a9d4a);
            transform: translateY(-1px);
          }

          .sc-welcome-btn--secondary {
            background: transparent;
            color: var(--muted);
            border: 1px solid var(--border, #e5e7eb);
          }

          .sc-welcome-btn--secondary:hover {
            background: var(--surface-2, #f9fafb);
            color: var(--text);
          }

          .sc-welcome-checkbox {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 16px;
            font-size: 0.85rem;
            color: var(--muted);
            cursor: pointer;
          }

          .sc-welcome-checkbox input {
            width: 16px;
            height: 16px;
            cursor: pointer;
            accent-color: var(--primary, #7C9070);
          }

          .sc-welcome-checkbox:hover span {
            color: var(--text);
          }

          /* Dark mode */
          [data-theme="dark"] .sc-welcome-modal {
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
          }

          /* Mobile */
          @media (max-width: 480px) {
            .sc-welcome-modal {
              padding: 24px 20px;
              border-radius: 16px;
            }

            .sc-welcome-icon {
              font-size: 2.5rem;
            }

            .sc-welcome-title {
              font-size: 1.25rem;
            }

            .sc-welcome-features li {
              padding: 10px 12px;
              font-size: 0.85rem;
            }
          }
        `}</style>
      </div>
    </div>
  )
}
