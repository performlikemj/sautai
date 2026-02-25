/**
 * WelcomeModal Component
 *
 * Displays a welcome modal for new chefs introducing the Sous Chef assistant.
 * Offers options to start the onboarding wizard or skip and explore on their own.
 */

import React from 'react'
import { useMarkWelcomed, useStartSetup, useSkipSetup } from '../../hooks/useOnboarding'

export default function WelcomeModal({ isOpen, onClose, onStartSetup }) {
  const markWelcomedMutation = useMarkWelcomed()
  const startSetupMutation = useStartSetup()
  const skipSetupMutation = useSkipSetup()

  if (!isOpen) return null

  const handleStartSetup = async () => {
    try {
      await startSetupMutation.mutateAsync()
      onStartSetup?.()
    } catch (err) {
      console.error('Failed to start setup:', err)
    }
  }

  const handleSkip = async () => {
    try {
      await skipSetupMutation.mutateAsync()
      // Store backup in localStorage
      localStorage.setItem('sous_chef_onboarded', 'true')
      onClose?.()
    } catch (err) {
      console.error('Failed to skip setup:', err)
      // Still close on error - we can retry later
      localStorage.setItem('sous_chef_onboarded', 'true')
      onClose?.()
    }
  }

  const isLoading = startSetupMutation.isPending || skipSetupMutation.isPending

  return (
    <>
      <div className="modal-overlay" onClick={handleSkip} />
      <div className="modal-container welcome-modal">
        <div className="welcome-modal-content">
          {/* Icon */}
          <div className="welcome-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
            </svg>
          </div>

          {/* Title */}
          <h2 className="welcome-title">Hey, I'm your Sous Chef!</h2>

          {/* Description */}
          <p className="welcome-description">
            Think of me as your kitchen partner who never forgets.
          </p>

          {/* Features */}
          <ul className="welcome-features">
            <li>
              <span className="feature-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M20 6L9 17l-5-5"/>
                </svg>
              </span>
              Remember every client's preferences & allergies
            </li>
            <li>
              <span className="feature-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M20 6L9 17l-5-5"/>
                </svg>
              </span>
              Plan menus that work for their households
            </li>
            <li>
              <span className="feature-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M20 6L9 17l-5-5"/>
                </svg>
              </span>
              Keep track of what's worked before
            </li>
          </ul>

          {/* Actions */}
          <div className="welcome-actions">
            <button
              className="btn btn-primary welcome-cta"
              onClick={handleStartSetup}
              disabled={isLoading}
            >
              {startSetupMutation.isPending ? (
                <>
                  <span className="spinner-sm" />
                  Setting up...
                </>
              ) : (
                <>
                  Let's do it
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: '0.5rem' }}>
                    <path d="M5 12h14M12 5l7 7-7 7"/>
                  </svg>
                </>
              )}
            </button>
            <button
              className="btn btn-ghost welcome-skip"
              onClick={handleSkip}
              disabled={isLoading}
            >
              {skipSetupMutation.isPending ? 'Skipping...' : "I'll explore on my own"}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        .welcome-modal {
          max-width: 420px;
          padding: 0;
          border-radius: 16px;
          overflow: hidden;
        }

        .welcome-modal-content {
          padding: 2rem;
          text-align: center;
        }

        .welcome-icon {
          width: 80px;
          height: 80px;
          margin: 0 auto 1.5rem;
          background: linear-gradient(135deg, var(--primary), var(--primary-600, #4a9d4a));
          border-radius: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          box-shadow: 0 4px 20px rgba(124, 144, 112, 0.3);
        }

        .welcome-title {
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--text);
          margin: 0 0 0.75rem;
        }

        .welcome-description {
          font-size: 1rem;
          color: var(--muted);
          margin: 0 0 1.5rem;
          line-height: 1.5;
        }

        .welcome-features {
          list-style: none;
          padding: 0;
          margin: 0 0 2rem;
          text-align: left;
        }

        .welcome-features li {
          display: flex;
          align-items: flex-start;
          gap: 0.75rem;
          padding: 0.5rem 0;
          font-size: 0.95rem;
          color: var(--text);
        }

        .welcome-features .feature-icon {
          flex-shrink: 0;
          width: 20px;
          height: 20px;
          background: var(--success-bg, #d4edda);
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--success, #28a745);
        }

        .welcome-actions {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .welcome-cta {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 0.875rem 1.5rem;
          font-size: 1rem;
          font-weight: 600;
          border-radius: 10px;
        }

        .welcome-skip {
          padding: 0.75rem;
          font-size: 0.9rem;
          color: var(--muted);
        }

        .welcome-skip:hover {
          color: var(--text);
          background: var(--surface-2, #f3f4f6);
        }

        .spinner-sm {
          display: inline-block;
          width: 16px;
          height: 16px;
          border: 2px solid rgba(255, 255, 255, 0.3);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
          margin-right: 0.5rem;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        /* Dark mode */
        [data-theme="dark"] .welcome-modal {
          background: var(--surface);
        }

        [data-theme="dark"] .welcome-features .feature-icon {
          background: rgba(124, 144, 112, 0.2);
        }

        /* Mobile */
        @media (max-width: 480px) {
          .welcome-modal {
            margin: 1rem;
            max-width: calc(100% - 2rem);
          }

          .welcome-modal-content {
            padding: 1.5rem;
          }

          .welcome-icon {
            width: 64px;
            height: 64px;
            border-radius: 16px;
          }

          .welcome-icon svg {
            width: 36px;
            height: 36px;
          }

          .welcome-title {
            font-size: 1.25rem;
          }
        }
      `}</style>
    </>
  )
}
