/**
 * SuggestionBadge Component
 * 
 * Visual indicator for the Sous Chef widget when contextual suggestions are available.
 * Shows a pulsing glow effect and badge count.
 */

import React from 'react'

/**
 * SuggestionBadge - Shows suggestion availability on Sous Chef widget
 * 
 * @param {number} count - Number of available suggestions
 * @param {string} priority - 'high', 'medium', or 'low'
 * @param {function} onClick - Callback when badge is clicked
 * @param {boolean} pulsing - Whether to show pulsing animation
 * @param {string} className - Additional CSS classes
 */
export default function SuggestionBadge({
  count = 0,
  priority = 'low',
  onClick,
  pulsing = true,
  className = ''
}) {
  if (count === 0) return null
  
  const displayCount = count > 9 ? '9+' : count
  
  return (
    <div 
      className={`suggestion-badge priority-${priority} ${pulsing ? 'pulsing' : ''} ${className}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      }}
      aria-label={`${count} suggestion${count !== 1 ? 's' : ''} available`}
    >
      <span className="badge-icon">✨</span>
      <span className="badge-count">{displayCount}</span>
      
      {/* Glow ring effect */}
      {pulsing && <div className="glow-ring" />}
      
      <style>{`
        .suggestion-badge {
          position: relative;
          display: flex;
          align-items: center;
          gap: 0.25rem;
          padding: 0.25rem 0.5rem;
          border-radius: 12px;
          font-size: 0.7rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          z-index: 1;
        }
        
        /* Priority colors */
        .suggestion-badge.priority-high {
          background: linear-gradient(135deg, #f59e0b, #d97706);
          color: white;
        }
        
        .suggestion-badge.priority-medium {
          background: linear-gradient(135deg, var(--primary, #7C9070), var(--primary-700, #449d44));
          color: white;
        }
        
        .suggestion-badge.priority-low {
          background: var(--surface-2, #f0f0f0);
          color: var(--text, #333);
          border: 1px solid var(--border, #ddd);
        }
        
        .suggestion-badge:hover {
          transform: scale(1.05);
        }
        
        .suggestion-badge:active {
          transform: scale(0.98);
        }
        
        .badge-icon {
          font-size: 0.8rem;
        }
        
        .badge-count {
          min-width: 1rem;
          text-align: center;
        }
        
        /* Glow ring animation */
        .glow-ring {
          position: absolute;
          inset: -4px;
          border-radius: 20px;
          pointer-events: none;
          z-index: -1;
        }
        
        .suggestion-badge.pulsing.priority-high .glow-ring {
          background: radial-gradient(circle, rgba(245, 158, 11, 0.4) 0%, transparent 70%);
          animation: pulseGlow 2s ease-in-out infinite;
        }
        
        .suggestion-badge.pulsing.priority-medium .glow-ring {
          background: radial-gradient(circle, rgba(124, 144, 112, 0.4) 0%, transparent 70%);
          animation: pulseGlow 2s ease-in-out infinite;
        }
        
        .suggestion-badge.pulsing.priority-low .glow-ring {
          display: none;
        }
        
        @keyframes pulseGlow {
          0%, 100% {
            opacity: 0.6;
            transform: scale(1);
          }
          50% {
            opacity: 1;
            transform: scale(1.1);
          }
        }
        
        /* Badge pop animation on mount */
        .suggestion-badge {
          animation: badgePop 0.3s ease;
        }
        
        @keyframes badgePop {
          0% {
            opacity: 0;
            transform: scale(0.5);
          }
          70% {
            transform: scale(1.1);
          }
          100% {
            opacity: 1;
            transform: scale(1);
          }
        }
      `}</style>
    </div>
  )
}

/**
 * Floating Suggestion Badge - Positioned absolutely relative to parent
 */
export function FloatingSuggestionBadge({
  count = 0,
  priority = 'low',
  onClick,
  position = 'top-right',
  className = ''
}) {
  if (count === 0) return null
  
  const positionStyles = {
    'top-right': { top: '-8px', right: '-8px' },
    'top-left': { top: '-8px', left: '-8px' },
    'bottom-right': { bottom: '-8px', right: '-8px' },
    'bottom-left': { bottom: '-8px', left: '-8px' },
  }
  
  const style = positionStyles[position] || positionStyles['top-right']
  
  return (
    <div className={`floating-badge-wrapper ${className}`} style={{ position: 'absolute', ...style }}>
      <SuggestionBadge
        count={count}
        priority={priority}
        onClick={onClick}
        pulsing={priority !== 'low'}
      />
    </div>
  )
}

/**
 * Mini Suggestion Indicator - Just a dot with glow
 */
export function SuggestionIndicator({
  active = false,
  priority = 'medium',
  onClick,
  className = ''
}) {
  if (!active) return null
  
  return (
    <div 
      className={`suggestion-indicator priority-${priority} ${className}`}
      onClick={onClick}
      role="status"
      aria-label="Suggestions available"
    >
      <style>{`
        .suggestion-indicator {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          cursor: pointer;
          position: relative;
        }
        
        .suggestion-indicator.priority-high {
          background: #f59e0b;
          box-shadow: 0 0 8px rgba(245, 158, 11, 0.6);
          animation: indicatorPulse 1.5s ease-in-out infinite;
        }
        
        .suggestion-indicator.priority-medium {
          background: var(--primary, #7C9070);
          box-shadow: 0 0 8px rgba(124, 144, 112, 0.6);
          animation: indicatorPulse 2s ease-in-out infinite;
        }
        
        .suggestion-indicator.priority-low {
          background: var(--muted, #888);
        }
        
        @keyframes indicatorPulse {
          0%, 100% {
            transform: scale(1);
            opacity: 1;
          }
          50% {
            transform: scale(1.2);
            opacity: 0.8;
          }
        }
      `}</style>
    </div>
  )
}
