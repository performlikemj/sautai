/**
 * ProactiveHintBanner Component
 * 
 * Displays proactive hints from the Sous Chef as a non-intrusive banner.
 * Appears at the top of the dashboard content area.
 */

import React, { useCallback } from 'react'

/**
 * ProactiveHintBanner - Shows contextual AI suggestions
 * 
 * @param {Object} hint - The hint to display
 * @param {function} onDismiss - Callback when hint is dismissed
 * @param {function} onAccept - Callback when hint action is accepted
 * @param {function} onDontShowAgain - Callback when "don't show again" is clicked
 * @param {string} sousChefEmoji - Emoji for the Sous Chef
 */
export default function ProactiveHintBanner({
  hint,
  onDismiss,
  onAccept,
  onDontShowAgain,
  sousChefEmoji = '🧑‍🍳'
}) {
  if (!hint) return null
  
  const handleAccept = useCallback(() => {
    if (onAccept) {
      onAccept(hint.action)
    }
  }, [hint.action, onAccept])
  
  const handleDismiss = useCallback(() => {
    if (onDismiss) {
      onDismiss()
    }
  }, [onDismiss])
  
  const handleDontShowAgain = useCallback(() => {
    if (onDontShowAgain) {
      onDontShowAgain(hint.id)
    }
  }, [hint.id, onDontShowAgain])
  
  const priorityClass = `priority-${hint.priority || 'medium'}`
  const typeClass = `type-${hint.type || 'tip'}`
  
  return (
    <div className={`proactive-hint-banner ${priorityClass} ${typeClass}`}>
      <div className="hint-icon">
        {sousChefEmoji}
      </div>
      
      <div className="hint-content">
        <p className="hint-message">{hint.message}</p>
        
        <div className="hint-actions">
          {hint.action && (
            <button 
              className="hint-btn primary"
              onClick={handleAccept}
            >
              {hint.action.label || 'Do It'}
            </button>
          )}
          
          <button 
            className="hint-btn secondary"
            onClick={handleDismiss}
          >
            Dismiss
          </button>
          
          <button 
            className="hint-btn text"
            onClick={handleDontShowAgain}
          >
            Don't show again
          </button>
        </div>
      </div>
      
      <button 
        className="hint-close"
        onClick={handleDismiss}
        aria-label="Close hint"
      >
        ✕
      </button>
      
      <style>{`
        .proactive-hint-banner {
          display: flex;
          align-items: flex-start;
          gap: 0.875rem;
          padding: 0.875rem 1rem;
          border-radius: 10px;
          margin-bottom: 1rem;
          position: relative;
          animation: slideDown 0.3s ease;
        }
        
        @keyframes slideDown {
          from {
            opacity: 0;
            transform: translateY(-10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        
        /* Priority styles */
        .proactive-hint-banner.priority-high {
          background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(245, 158, 11, 0.05));
          border: 1px solid rgba(245, 158, 11, 0.3);
        }
        
        .proactive-hint-banner.priority-medium {
          background: linear-gradient(135deg, rgba(124, 144, 112, 0.12), rgba(124, 144, 112, 0.05));
          border: 1px solid rgba(124, 144, 112, 0.25);
        }
        
        .proactive-hint-banner.priority-low {
          background: var(--surface-2, #f5f5f5);
          border: 1px solid var(--border, #e5e5e5);
        }
        
        /* Type styles */
        .proactive-hint-banner.type-milestone .hint-icon {
          background: var(--warning);
        }

        .proactive-hint-banner.type-idle .hint-icon,
        .proactive-hint-banner.type-tip .hint-icon {
          background: linear-gradient(135deg, var(--primary, #7C9070), var(--primary-700, #449d44));
        }

        .proactive-hint-banner.type-error .hint-icon {
          background: var(--danger);
        }
        
        .hint-icon {
          width: 42px;
          height: 42px;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 1.4rem;
          flex-shrink: 0;
        }
        
        .hint-content {
          flex: 1;
          min-width: 0;
        }
        
        .hint-message {
          margin: 0 0 0.625rem 0;
          color: var(--text, #333);
          font-size: 0.95rem;
          line-height: 1.45;
        }
        
        .hint-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          align-items: center;
        }
        
        .hint-btn {
          border: none;
          border-radius: 6px;
          font-size: 0.85rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .hint-btn.primary {
          padding: 0.4rem 0.875rem;
          background: var(--primary, #7C9070);
          color: white;
        }
        
        .hint-btn.primary:hover {
          background: var(--primary-700, #449d44);
        }
        
        .hint-btn.secondary {
          padding: 0.4rem 0.75rem;
          background: var(--surface, #fff);
          color: var(--text, #333);
          border: 1px solid var(--border, #ddd);
        }
        
        .hint-btn.secondary:hover {
          border-color: var(--text, #333);
        }
        
        .hint-btn.text {
          padding: 0.4rem 0.5rem;
          background: none;
          color: var(--muted, #888);
        }
        
        .hint-btn.text:hover {
          color: var(--text, #333);
        }
        
        .hint-close {
          position: absolute;
          top: 0.5rem;
          right: 0.5rem;
          background: none;
          border: none;
          color: var(--muted, #888);
          font-size: 1rem;
          cursor: pointer;
          padding: 0.25rem;
          line-height: 1;
          opacity: 0.6;
        }
        
        .hint-close:hover {
          opacity: 1;
        }
        
        /* Responsive */
        @media (max-width: 480px) {
          .proactive-hint-banner {
            padding: 0.75rem;
            gap: 0.625rem;
          }
          
          .hint-icon {
            width: 36px;
            height: 36px;
            font-size: 1.2rem;
          }
          
          .hint-message {
            font-size: 0.9rem;
          }
          
          .hint-btn {
            font-size: 0.8rem;
          }
        }
      `}</style>
    </div>
  )
}
