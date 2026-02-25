/**
 * GhostInput Component
 * 
 * Input field with Copilot-style ghost text suggestions.
 * Shows suggested value in lighter text after the current value.
 * Press Tab to accept, Escape to dismiss, or keep typing to overwrite.
 */

import React, { useState, useRef, useEffect, useCallback, forwardRef, useMemo } from 'react'

// Detect touch device
const isTouchDevice = () => {
  if (typeof window === 'undefined') return false
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0
}

/**
 * GhostInput - Input with inline ghost text suggestions
 * 
 * @param {string} value - Current input value
 * @param {function} onChange - Callback when value changes
 * @param {string} ghostValue - Suggested value to show as ghost text
 * @param {function} onAccept - Callback when suggestion is accepted (Tab)
 * @param {function} onDismiss - Callback when suggestion is dismissed (Escape)
 * @param {string} placeholder - Input placeholder text
 * @param {string} className - Additional CSS classes
 * @param {boolean} disabled - Whether input is disabled
 * @param {string} type - Input type (text, number, etc.)
 * @param {object} rest - Other input props
 */
const GhostInput = forwardRef(function GhostInput({
  value = '',
  onChange,
  ghostValue = '',
  onAccept,
  onDismiss,
  placeholder = '',
  className = '',
  disabled = false,
  type = 'text',
  showHint = true,
  ...rest
}, ref) {
  const [isFocused, setIsFocused] = useState(false)
  const [localValue, setLocalValue] = useState(value)
  const inputRef = useRef(null)
  const containerRef = useRef(null)
  
  // Sync local value with prop
  useEffect(() => {
    setLocalValue(value)
  }, [value])
  
  // Combine refs
  useEffect(() => {
    if (ref) {
      if (typeof ref === 'function') {
        ref(inputRef.current)
      } else {
        ref.current = inputRef.current
      }
    }
  }, [ref])
  
  /**
   * Calculate what ghost text to show
   * Only show ghost text that extends beyond current value
   */
  const getDisplayGhostText = useCallback(() => {
    if (!ghostValue || disabled) return ''
    
    const currentVal = String(localValue || '')
    const ghostVal = String(ghostValue)
    
    // If ghost value starts with current value, show the rest
    if (ghostVal.toLowerCase().startsWith(currentVal.toLowerCase()) && ghostVal !== currentVal) {
      return ghostVal.slice(currentVal.length)
    }
    
    // If current value is empty and we have a ghost, show full ghost
    if (!currentVal && ghostVal) {
      return ghostVal
    }
    
    return ''
  }, [localValue, ghostValue, disabled])
  
  const displayGhostText = getDisplayGhostText()
  const hasGhost = !!displayGhostText && isFocused
  const isTouch = useMemo(() => isTouchDevice(), [])
  
  /**
   * Handle accepting the suggestion (shared between Tab key and tap)
   */
  const handleAccept = useCallback((e) => {
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }
    if (!ghostValue) return
    
    setLocalValue(ghostValue)
    
    if (onChange) {
      onChange(ghostValue)
    }
    
    if (onAccept) {
      onAccept(ghostValue)
    }
    
    // Keep focus on the input
    if (inputRef.current) {
      inputRef.current.focus()
    }
  }, [ghostValue, onChange, onAccept])
  
  /**
   * Handle input change
   */
  const handleChange = useCallback((e) => {
    const newValue = e.target.value
    setLocalValue(newValue)
    
    if (onChange) {
      onChange(newValue)
    }
  }, [onChange])
  
  /**
   * Handle key down events
   */
  const handleKeyDown = useCallback((e) => {
    // Tab to accept suggestion
    if (e.key === 'Tab' && hasGhost && ghostValue) {
      handleAccept(e)
      return
    }
    
    // Escape to dismiss suggestion
    if (e.key === 'Escape' && hasGhost) {
      e.preventDefault()
      if (onDismiss) {
        onDismiss()
      }
      return
    }
    
    // Pass through other key events
    if (rest.onKeyDown) {
      rest.onKeyDown(e)
    }
  }, [hasGhost, ghostValue, handleAccept, onDismiss, rest])
  
  /**
   * Handle focus events
   */
  const handleFocus = useCallback((e) => {
    setIsFocused(true)
    if (rest.onFocus) {
      rest.onFocus(e)
    }
  }, [rest])
  
  const handleBlur = useCallback((e) => {
    setIsFocused(false)
    if (rest.onBlur) {
      rest.onBlur(e)
    }
  }, [rest])
  
  return (
    <div className={`ghost-input-container ${className}`} ref={containerRef}>
      <div className="ghost-input-wrapper">
        {/* Ghost text layer (behind input) */}
        {hasGhost && (
          <div className="ghost-text-layer" aria-hidden="true">
            <span className="ghost-current">{localValue}</span>
            <span className="ghost-suggestion">{displayGhostText}</span>
          </div>
        )}
        
        {/* Actual input */}
        <input
          ref={inputRef}
          type={type}
          value={localValue}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={handleFocus}
          onBlur={handleBlur}
          placeholder={!hasGhost ? placeholder : ''}
          disabled={disabled}
          className={`ghost-input ${hasGhost ? 'has-ghost' : ''}`}
          autoComplete="off"
          {...rest}
        />
      </div>
      
      {/* Hint text / Accept button */}
      {hasGhost && showHint && (
        <div className="ghost-hint">
          {isTouch ? (
            <button 
              type="button"
              className="ghost-accept-btn"
              onClick={handleAccept}
              onTouchEnd={handleAccept}
            >
              Tap ↵
            </button>
          ) : (
            <><kbd>Tab</kbd> to accept</>
          )}
        </div>
      )}
      
      <style>{`
        .ghost-input-container {
          position: relative;
          width: 100%;
        }
        
        .ghost-input-wrapper {
          position: relative;
          width: 100%;
        }
        
        /* Ghost text layer */
        .ghost-text-layer {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          pointer-events: none;
          display: flex;
          align-items: center;
          padding: inherit;
          font: inherit;
          white-space: nowrap;
          overflow: hidden;
        }
        
        /* Match input padding - these need to match your form input styles */
        .ghost-text-layer {
          padding: 0.625rem 0.875rem;
        }
        
        .ghost-current {
          color: transparent;
        }
        
        .ghost-suggestion {
          color: var(--muted, #888);
          opacity: 0.6;
        }
        
        /* Input styles */
        .ghost-input {
          width: 100%;
          padding: 0.625rem 0.875rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 8px;
          font-size: 0.95rem;
          background: var(--surface, #fff);
          color: var(--text, #333);
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        
        .ghost-input:focus {
          outline: none;
          border-color: var(--primary, #7C9070);
          box-shadow: 0 0 0 3px var(--primary-alpha, rgba(124, 144, 112, 0.15));
        }
        
        .ghost-input.has-ghost {
          background: transparent;
        }
        
        .ghost-input:disabled {
          opacity: 0.6;
          cursor: not-allowed;
          background: var(--surface-2, #f5f5f5);
        }
        
        .ghost-input::placeholder {
          color: var(--muted, #888);
          opacity: 0.6;
        }
        
        /* Hint */
        .ghost-hint {
          position: absolute;
          bottom: -1.5rem;
          right: 0;
          font-size: 0.7rem;
          color: var(--muted, #888);
          display: flex;
          align-items: center;
          gap: 0.25rem;
          opacity: 0.8;
        }
        
        .ghost-hint kbd {
          background: var(--surface-2, #f0f0f0);
          border: 1px solid var(--border, #ddd);
          border-radius: 3px;
          padding: 0.1rem 0.35rem;
          font-size: 0.65rem;
          font-family: inherit;
        }
        
        /* Mobile accept button - compact pill style */
        .ghost-accept-btn {
          background: var(--surface-2, #f0f0f0);
          border: 1px solid var(--border, #ddd);
          border-radius: 12px;
          padding: 2px 10px;
          font-size: 0.7rem;
          color: var(--muted, #888);
          cursor: pointer;
          touch-action: manipulation;
          transition: background 0.15s, border-color 0.15s, color 0.15s;
          -webkit-tap-highlight-color: transparent;
        }
        
        .ghost-accept-btn:active {
          background: var(--primary, #7C9070);
          border-color: var(--primary, #7C9070);
          color: white;
        }
        
        /* Animation for ghost appearance */
        @keyframes ghostFadeIn {
          from {
            opacity: 0;
          }
          to {
            opacity: 0.6;
          }
        }
        
        .ghost-suggestion {
          animation: ghostFadeIn 0.2s ease;
        }
      `}</style>
    </div>
  )
})

export default GhostInput
