import React, { useState, useCallback } from 'react'

const STAR_PATH = 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z'

/**
 * SVG-based star rating component with animations.
 *
 * Props:
 *   value     - Current rating (1-5), supports fractional for read-only (e.g. 3.7)
 *   onChange  - Callback when user clicks a star (omit for read-only display)
 *   size      - Star size in px (default 24)
 *   count     - Number of stars (default 5)
 *   halfStars - Show fractional fills in read-only mode (default false)
 */
export default function StarRating({ value = 0, onChange, size = 24, count = 5, halfStars = false }) {
  const isInteractive = typeof onChange === 'function'
  const [hovered, setHovered] = useState(0)
  const [popIndex, setPopIndex] = useState(null)

  const handleClick = useCallback((i) => {
    if (!isInteractive) return
    onChange(i)
    setPopIndex(i)
    setTimeout(() => setPopIndex(null), 250)
  }, [isInteractive, onChange])

  const displayValue = hovered || value

  const stars = []
  for (let i = 1; i <= count; i++) {
    const filled = i <= Math.floor(displayValue)
    const isFractional = !filled && halfStars && !isInteractive && i === Math.ceil(displayValue) && displayValue % 1 > 0
    const fraction = isFractional ? (displayValue % 1) : 0
    const popping = popIndex === i

    const classes = [
      'star-rating__star',
      filled ? 'star-rating__star--filled' : '',
      popping ? 'star-rating__star--pop' : '',
    ].filter(Boolean).join(' ')

    stars.push(
      <span
        key={i}
        className={classes}
        role={isInteractive ? 'button' : undefined}
        aria-label={isInteractive ? `Rate ${i} star${i > 1 ? 's' : ''}` : undefined}
        tabIndex={isInteractive ? 0 : undefined}
        onClick={isInteractive ? () => handleClick(i) : undefined}
        onMouseEnter={isInteractive ? () => setHovered(i) : undefined}
        onMouseLeave={isInteractive ? () => setHovered(0) : undefined}
        onKeyDown={isInteractive ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleClick(i) } } : undefined}
      >
        {isFractional ? (
          /* Half-star: empty star behind, clipped filled star on top */
          <span style={{ position: 'relative', display: 'inline-flex', width: size, height: size }}>
            <svg viewBox="0 0 24 24" width={size} height={size} style={{ position: 'absolute', top: 0, left: 0 }}>
              <path d={STAR_PATH} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
            <svg viewBox="0 0 24 24" width={size} height={size} style={{ position: 'absolute', top: 0, left: 0, clipPath: `inset(0 ${Math.round((1 - fraction) * 100)}% 0 0)` }} className="star-rating__star--filled">
              <path d={STAR_PATH} fill="currentColor" />
            </svg>
          </span>
        ) : (
          <svg viewBox="0 0 24 24" width={size} height={size}>
            {filled ? (
              <path d={STAR_PATH} fill="currentColor" />
            ) : (
              <path d={STAR_PATH} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            )}
          </svg>
        )}
      </span>
    )
  }

  return (
    <span
      className={`star-rating ${isInteractive ? '' : 'star-rating--readonly'}`}
      aria-label={`Rating: ${value} out of ${count}`}
    >
      {stars}
    </span>
  )
}
