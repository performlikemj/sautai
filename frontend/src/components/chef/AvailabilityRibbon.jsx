import React, { useMemo } from 'react'
import {
  computeAvailabilityState,
  AVAILABILITY_STATUS,
} from './chefAvailability'

/**
 * Sticky availability bar that sits immediately below the hero and pins to
 * the top of the viewport once the hero scrolls out of view.
 *
 * Replaces the legacy desktop-only sticky mini-widget at PublicChef.jsx:1457-1511.
 *
 * State is derived purely from the chef profile + the upcoming events list,
 * so no backend changes are needed. The parent normally computes the state
 * once and passes it in via `availabilityState`; if it doesn't, we fall back
 * to computing it ourselves from `chef` + `upcomingEvents` so the component
 * also works standalone.
 *
 * Props:
 *  - chef: chef profile object
 *  - upcomingEvents: array of meal events (only needed if availabilityState is omitted)
 *  - availabilityState: precomputed state from computeAvailabilityState (preferred)
 *  - onCTAClick: optional escape hatch for non-scroll CTAs
 */
export default function AvailabilityRibbon({
  chef,
  upcomingEvents = [],
  availabilityState,
  onCTAClick,
}) {
  // Prefer the parent's precomputed state. Fall back to computing locally so
  // the component also works in isolation (storybook, ad-hoc embeds, etc.).
  const state = useMemo(() => {
    if (availabilityState) return availabilityState
    return computeAvailabilityState(chef, upcomingEvents)
  }, [availabilityState, chef, upcomingEvents])

  if (!chef) return null

  const tone = ribbonTone(state.status)

  function handleCTAClick(e) {
    if (onCTAClick) {
      onCTAClick(state, e)
      return
    }
    if (state.ctaTarget && typeof document !== 'undefined') {
      const target = document.querySelector(state.ctaTarget)
      if (target) {
        e.preventDefault()
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }

  return (
    <div
      className={`availability-ribbon availability-ribbon--${tone}`}
      role="status"
      aria-live="polite"
    >
      <div className="availability-ribbon__inner">
        <span className="availability-ribbon__icon" aria-hidden>
          <i className={iconForStatus(state.status)}></i>
        </span>
        <span className="availability-ribbon__label">{state.label}</span>
        {state.ctaLabel && state.ctaTarget && (
          <a
            href={state.ctaTarget}
            className="availability-ribbon__cta"
            onClick={handleCTAClick}
          >
            {state.ctaLabel}
            <i
              className="fa-solid fa-arrow-right"
              aria-hidden
              style={{ marginLeft: '.35rem' }}
            ></i>
          </a>
        )}
      </div>
    </div>
  )
}

function ribbonTone(status) {
  switch (status) {
    case AVAILABILITY_STATUS.OPEN:
      return 'open'
    case AVAILABILITY_STATUS.UPCOMING:
      return 'upcoming'
    case AVAILABILITY_STATUS.FULLY_BOOKED:
      return 'fully-booked'
    case AVAILABILITY_STATUS.INACTIVE:
    default:
      return 'inactive'
  }
}

function iconForStatus(status) {
  switch (status) {
    case AVAILABILITY_STATUS.OPEN:
      return 'fa-solid fa-circle-check'
    case AVAILABILITY_STATUS.UPCOMING:
      return 'fa-solid fa-calendar-day'
    case AVAILABILITY_STATUS.FULLY_BOOKED:
      return 'fa-solid fa-circle-exclamation'
    case AVAILABILITY_STATUS.INACTIVE:
    default:
      return 'fa-solid fa-pause'
  }
}
