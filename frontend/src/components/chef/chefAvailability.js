/**
 * Chef availability + hero CTA helpers.
 *
 * Pure functions used by ChefHero, AvailabilityRibbon, and StickyMobileCTA
 * to derive a single source of truth for the chef's bookable state and the
 * matching primary call-to-action.
 *
 * No backend changes needed — everything is derived from fields already
 * exposed by ChefPublicSerializer and ChefMealEventSerializer.
 */

// MealEvent.status values from meals/models/chef_events.py
export const EVENT_STATUS = {
  SCHEDULED: 'scheduled',
  OPEN: 'open',
  CLOSED: 'closed',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  CANCELLED: 'cancelled',
}

// AvailabilityRibbon visual states
export const AVAILABILITY_STATUS = {
  OPEN: 'open',
  UPCOMING: 'upcoming',
  FULLY_BOOKED: 'fully_booked',
  INACTIVE: 'inactive',
}

// MealEventCard badge tones (drives CSS class + color)
export const BADGE_TONE = {
  LIVE: 'live',
  WARNING: 'warning', // 1-3 spots left, urgency
  INFO: 'info', // many spots left, default available state
  SOLDOUT: 'soldout',
  CANCELLED: 'cancelled',
  UPCOMING: 'upcoming', // event not yet open for ordering
}

const SHORT_DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
})

function formatShortDate(value) {
  if (!value) return ''
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return SHORT_DATE_FORMATTER.format(date)
}

export function spotsRemaining(event) {
  const max = Number(event?.max_orders ?? 0)
  const taken = Number(event?.orders_count ?? 0)
  return Math.max(0, max - taken)
}

function isBookable(event) {
  const status = event?.status
  return (
    (status === EVENT_STATUS.SCHEDULED || status === EVENT_STATUS.OPEN) &&
    spotsRemaining(event) > 0
  )
}

function isFutureEvent(event) {
  if (!event?.event_date) return false
  const eventDate = new Date(event.event_date)
  if (Number.isNaN(eventDate.getTime())) return false
  // Compare date-only — chef is "upcoming" if event hasn't passed yet.
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return eventDate >= today
}

/**
 * Compute the chef's overall booking state from their profile and upcoming events.
 *
 * @param {object|null} chef - Chef profile (must include is_live, is_on_break)
 * @param {Array<object>} upcomingEvents - Array of meal events from the API
 * @returns {{
 *   status: string,
 *   label: string,
 *   ctaLabel?: string,
 *   ctaTarget?: string,
 * }}
 */
export function computeAvailabilityState(chef, upcomingEvents = []) {
  if (!chef || !chef.is_live || chef.is_on_break) {
    return {
      status: AVAILABILITY_STATUS.INACTIVE,
      label: 'Not currently taking bookings',
    }
  }

  const events = Array.isArray(upcomingEvents) ? upcomingEvents : []

  const liveEvent = events.find((e) => e?.status === EVENT_STATUS.IN_PROGRESS)
  if (liveEvent) {
    return {
      status: AVAILABILITY_STATUS.OPEN,
      label: 'Live menu — order now',
      ctaLabel: 'See menu',
      ctaTarget: '#featured-menu',
    }
  }

  if (events.some(isBookable)) {
    return {
      status: AVAILABILITY_STATUS.OPEN,
      label: 'Accepting bookings this week',
      ctaLabel: 'See dates',
      ctaTarget: '#featured-menu',
    }
  }

  const nextEvent = events
    .filter(
      (e) =>
        (e?.status === EVENT_STATUS.SCHEDULED ||
          e?.status === EVENT_STATUS.OPEN) &&
        isFutureEvent(e),
    )
    .sort(
      (a, b) =>
        new Date(a.event_date).getTime() - new Date(b.event_date).getTime(),
    )[0]

  if (nextEvent) {
    return {
      status: AVAILABILITY_STATUS.UPCOMING,
      label: `Next opening: ${formatShortDate(nextEvent.event_date)}`,
      ctaLabel: 'Join waitlist',
      ctaTarget: '#waitlist',
    }
  }

  return {
    status: AVAILABILITY_STATUS.FULLY_BOOKED,
    label: 'Fully booked — join the waitlist',
    ctaLabel: 'Notify me',
    ctaTarget: '#waitlist',
  }
}

/**
 * Derive the primary hero CTA from chef + availability state.
 *
 * Used by both ChefHero (above-the-fold button) and StickyMobileCTA
 * (bottom-pinned bar that appears after hero scrolls out of view).
 *
 * @param {object|null} chef
 * @param {{ status: string }} availabilityState
 * @returns {{
 *   label: string,
 *   action: 'scroll'|'modal',
 *   target: string,
 *   style: 'primary'|'secondary',
 * }}
 */
export function getHeroCTA(chef, availabilityState) {
  const status = availabilityState?.status

  if (status === AVAILABILITY_STATUS.OPEN) {
    return {
      label: 'Order now',
      action: 'scroll',
      target: '#featured-menu',
      style: 'primary',
    }
  }

  if (status === AVAILABILITY_STATUS.UPCOMING) {
    return {
      label: 'Book a service',
      action: 'scroll',
      target: '#service-tiers',
      style: 'primary',
    }
  }

  if (status === AVAILABILITY_STATUS.FULLY_BOOKED) {
    return {
      label: 'Join waitlist',
      action: 'scroll',
      target: '#waitlist',
      style: 'secondary',
    }
  }

  // inactive (or unknown)
  return {
    label: 'Request a quote',
    action: 'modal',
    target: 'quote-modal',
    style: 'secondary',
  }
}

/**
 * Derive the per-card availability badge label + tone for a single meal event.
 * Used by MealEventCard.
 *
 * @param {object} event - Meal event from ChefMealEventSerializer
 * @returns {{ label: string, tone: string }}
 */
export function getMealEventBadge(event) {
  const status = event?.status
  const remaining = spotsRemaining(event)

  if (status === EVENT_STATUS.CANCELLED) {
    return { label: 'Cancelled', tone: BADGE_TONE.CANCELLED }
  }
  if (status === EVENT_STATUS.IN_PROGRESS) {
    return { label: '● Live now', tone: BADGE_TONE.LIVE }
  }
  if (
    status === EVENT_STATUS.CLOSED ||
    status === EVENT_STATUS.COMPLETED ||
    remaining <= 0
  ) {
    return { label: 'Sold out', tone: BADGE_TONE.SOLDOUT }
  }
  if (remaining === 1) {
    return { label: '1 spot left', tone: BADGE_TONE.WARNING }
  }
  if (remaining <= 3) {
    return { label: `${remaining} spots left`, tone: BADGE_TONE.WARNING }
  }
  return { label: `${remaining} spots left`, tone: BADGE_TONE.INFO }
}

/**
 * Format a meal event date as "Apr 12 · Sat" for the date chip.
 *
 * @param {string|Date} value - YYYY-MM-DD string or Date
 * @returns {string}
 */
export function formatEventDateChip(value) {
  if (!value) return ''
  // Treat YYYY-MM-DD as local date so we don't drift across timezones.
  const date =
    typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? new Date(`${value}T00:00:00`)
      : value instanceof Date
        ? value
        : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const month = date.toLocaleString(undefined, { month: 'short' })
  const day = date.getDate()
  const weekday = date.toLocaleString(undefined, { weekday: 'short' })
  return `${month} ${day} · ${weekday}`
}
