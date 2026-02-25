/**
 * TelegramConnect Component
 *
 * Shows the interface for connecting a Telegram account:
 * - "Connect Telegram" button (initial state)
 * - QR code + deep link (after clicking)
 * - Expiration warning
 *
 * Polls for connection status while QR code is displayed.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { useGenerateTelegramLink, useInvalidateTelegramStatus } from '../../hooks/useTelegram'

// Telegram brand color
const TELEGRAM_BLUE = '#0088cc'

/**
 * TelegramConnect - UI for connecting a new Telegram account
 *
 * @param {function} onLinked - Callback when account is successfully linked
 */
export default function TelegramConnect({ onLinked }) {
  const [linkData, setLinkData] = useState(null)
  const [timeRemaining, setTimeRemaining] = useState(null)
  const [isExpired, setIsExpired] = useState(false)

  const generateLink = useGenerateTelegramLink()
  const invalidateStatus = useInvalidateTelegramStatus()

  // Calculate time remaining until expiry
  useEffect(() => {
    if (!linkData?.expires_at) return

    const updateTimer = () => {
      const now = new Date()
      const expires = new Date(linkData.expires_at)
      const remaining = Math.max(0, Math.floor((expires - now) / 1000))

      if (remaining <= 0) {
        setIsExpired(true)
        setTimeRemaining(null)
      } else {
        setIsExpired(false)
        const minutes = Math.floor(remaining / 60)
        const seconds = remaining % 60
        setTimeRemaining(`${minutes}:${seconds.toString().padStart(2, '0')}`)
      }
    }

    updateTimer()
    const interval = setInterval(updateTimer, 1000)
    return () => clearInterval(interval)
  }, [linkData?.expires_at])

  // Poll for connection status while QR code is displayed
  useEffect(() => {
    if (!linkData || isExpired) return

    const pollInterval = setInterval(() => {
      invalidateStatus()
    }, 3000) // Check every 3 seconds

    return () => clearInterval(pollInterval)
  }, [linkData, isExpired, invalidateStatus])

  const handleGenerate = useCallback(async () => {
    try {
      const data = await generateLink.mutateAsync()
      setLinkData(data)
      setIsExpired(false)
    } catch (err) {
      // Error handled by mutation
    }
  }, [generateLink])

  const handleRegenerate = useCallback(async () => {
    setLinkData(null)
    setIsExpired(false)
    await handleGenerate()
  }, [handleGenerate])

  return (
    <div className="tg-connect">
      <div className="tg-connect-header">
        <svg className="tg-icon" viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z"/>
        </svg>
        <h3 className="tg-connect-title">Connect Telegram</h3>
      </div>
      
      <p className="tg-connect-desc">
        Get instant notifications for new orders, schedule reminders, and chat with your Sous Chef 
        directly in Telegram.
      </p>

      {!linkData ? (
        <button 
          className="tg-btn tg-btn-primary"
          onClick={handleGenerate}
          disabled={generateLink.isPending}
        >
          {generateLink.isPending ? (
            <>
              <span className="tg-spinner" /> Generating...
            </>
          ) : (
            <>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                <path d="M12 5v14M5 12h14" strokeLinecap="round"/>
              </svg>
              Connect Telegram
            </>
          )}
        </button>
      ) : isExpired ? (
        <div className="tg-expired">
          <p className="tg-expired-text">Link expired</p>
          <button className="tg-btn tg-btn-outline" onClick={handleRegenerate}>
            Generate New Link
          </button>
        </div>
      ) : (
        <div className="tg-qr-section">
          <div className="tg-qr-container">
            <QRCodeSVG 
              value={linkData.deep_link} 
              size={180}
              level="M"
              includeMargin={true}
              bgColor="#ffffff"
              fgColor="#000000"
            />
          </div>
          
          <p className="tg-qr-instruction">
            Scan this QR code with your phone camera
          </p>
          
          <div className="tg-divider">
            <span>or</span>
          </div>
          
          <a 
            href={linkData.deep_link}
            className="tg-btn tg-btn-telegram"
            target="_blank"
            rel="noopener noreferrer"
          >
            <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z"/>
            </svg>
            Open in Telegram
          </a>
          
          <div className="tg-timer">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 6v6l4 2"/>
            </svg>
            <span>Link expires in {timeRemaining}</span>
          </div>
        </div>
      )}

      {generateLink.isError && (
        <div className="tg-error">
          Failed to generate link. Please try again.
        </div>
      )}

      <style>{`
        .tg-connect {
          padding: 1.5rem;
          background: var(--surface, #fff);
          border-radius: 16px;
          border: 1px solid var(--border, #e5e5e5);
        }

        .tg-connect-header {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          margin-bottom: 0.75rem;
        }

        .tg-icon {
          color: ${TELEGRAM_BLUE};
        }

        .tg-connect-title {
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
          color: var(--text, #333);
        }

        .tg-connect-desc {
          margin: 0 0 1.5rem 0;
          color: var(--muted, #666);
          font-size: 0.9rem;
          line-height: 1.5;
        }

        /* Buttons */
        .tg-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          padding: 0.75rem 1.25rem;
          border-radius: 8px;
          font-weight: 500;
          font-size: 0.95rem;
          cursor: pointer;
          transition: all 0.15s;
          border: none;
          text-decoration: none;
        }

        .tg-btn-primary {
          background: var(--primary, #7C9070);
          color: white;
          width: 100%;
        }

        .tg-btn-primary:hover:not(:disabled) {
          background: var(--primary-700, #449d44);
        }

        .tg-btn-primary:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .tg-btn-outline {
          background: transparent;
          border: 1px solid var(--border, #ddd);
          color: var(--text, #333);
        }

        .tg-btn-outline:hover {
          border-color: var(--text, #333);
          background: var(--surface-2, #f9fafb);
        }

        .tg-btn-telegram {
          background: ${TELEGRAM_BLUE};
          color: white;
          width: 100%;
        }

        .tg-btn-telegram:hover {
          background: #006699;
        }

        /* Spinner */
        .tg-spinner {
          width: 16px;
          height: 16px;
          border: 2px solid rgba(255,255,255,0.3);
          border-top-color: white;
          border-radius: 50%;
          animation: tgSpin 0.8s linear infinite;
        }

        @keyframes tgSpin {
          to { transform: rotate(360deg); }
        }

        /* QR Section */
        .tg-qr-section {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 1rem;
        }

        .tg-qr-container {
          padding: 1rem;
          background: white;
          border-radius: 16px;
          box-shadow: 0 4px 12px rgba(27,58,45,0.1);
        }

        .tg-qr-instruction {
          margin: 0;
          color: var(--muted, #666);
          font-size: 0.9rem;
          text-align: center;
        }

        .tg-divider {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 1rem;
          color: var(--muted, #999);
          font-size: 0.85rem;
        }

        .tg-divider::before,
        .tg-divider::after {
          content: '';
          flex: 1;
          height: 1px;
          background: var(--border, #e5e5e5);
        }

        .tg-timer {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: var(--muted, #888);
          font-size: 0.85rem;
          margin-top: 0.5rem;
        }

        /* Expired */
        .tg-expired {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 1rem;
        }

        .tg-expired-text {
          margin: 0;
          color: var(--muted, #888);
          font-size: 0.95rem;
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
      `}</style>
    </div>
  )
}
