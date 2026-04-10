import React from 'react'
import {
  getMealEventBadge,
  formatEventDateChip,
  spotsRemaining,
  EVENT_STATUS,
  BADGE_TONE,
} from './chefAvailability'

/**
 * Stylized fallback shown when an event's related Meal has no image.
 * Inline SVG keeps it self-contained — no asset import needed.
 */
const PLACEHOLDER_MEAL_IMAGE = (() => {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='640' height='480' viewBox='0 0 640 480'>
  <defs>
    <linearGradient id='g' x1='0' x2='1' y1='0' y2='1'>
      <stop offset='0' stop-color='#eaf5ec'/>
      <stop offset='1' stop-color='#d9efe0'/>
    </linearGradient>
  </defs>
  <rect width='640' height='480' fill='url(#g)'/>
  <g fill='#7C9070'>
    <circle cx='320' cy='240' r='70' fill='none' stroke='#7C9070' stroke-width='8'/>
    <rect x='292' y='220' width='56' height='40' rx='8'/>
  </g>
  <text x='50%' y='80%' dominant-baseline='middle' text-anchor='middle'
        font-family='Inter, Arial, sans-serif' font-size='28' fill='#5c6b5d'>Meal photo</text>
</svg>`
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
})()

function getCoverPhotoUrl(event) {
  const url = event?.meal?.image
  if (typeof url === 'string' && url.length > 0) return url
  return PLACEHOLDER_MEAL_IMAGE
}

function formatPrice(event) {
  const price = Number(event?.current_price ?? event?.base_price)
  if (!Number.isFinite(price) || price <= 0) return null
  // Match the rest of the codebase: USD-prefixed for now (currency is per-chef
  // and we don't have it on the event payload). Keep simple, no Intl rounding
  // surprises.
  return `$${price.toFixed(0)}`
}

/**
 * Photo-forward meal event card.
 *
 * Presentational only — booking, auth redirects, MEHKO gating, cart wiring,
 * and toast handling all live in PublicChef.jsx and are passed in via the
 * `onAddToCart`, `onAddToPlan`, and `onAskChef` callbacks.
 */
export default function MealEventCard({
  event,
  authUser,
  servesMyArea,
  onAddToCart,
  onAddToPlan,
  onAskChef,
}) {
  if (!event) return null

  const badge = getMealEventBadge(event)
  const dateChip = formatEventDateChip(event.event_date)
  const title = event.meal?.name || event.meal_name || 'Meal'
  const description = event.description || event.meal?.description || ''
  const price = formatPrice(event)
  const coverUrl = getCoverPhotoUrl(event)
  const remaining = spotsRemaining(event)

  // Cards for cancelled / sold-out / past events render in a muted state.
  const isUnavailable =
    event.status === EVENT_STATUS.CANCELLED ||
    event.status === EVENT_STATUS.CLOSED ||
    event.status === EVENT_STATUS.COMPLETED ||
    remaining <= 0

  const canOrder = !isUnavailable && Boolean(authUser) && Boolean(servesMyArea)

  // Primary CTA label/state — single source of truth for the main action.
  let primaryLabel = 'Add to cart'
  let primaryDisabled = false
  let primaryHandler = () => onAddToCart?.(event)
  if (isUnavailable) {
    primaryLabel =
      event.status === EVENT_STATUS.CANCELLED ? 'Cancelled' : 'Sold out'
    primaryDisabled = true
    primaryHandler = undefined
  } else if (!authUser) {
    primaryLabel = 'Sign in to order'
    // Let onAddToCart handle the auth redirect — it already does in PublicChef.jsx.
    primaryHandler = () => onAddToCart?.(event)
  } else if (!servesMyArea) {
    primaryLabel = 'Outside service area'
    primaryDisabled = true
    primaryHandler = undefined
  }

  return (
    <article
      className={`meal-event-card${isUnavailable ? ' is-unavailable' : ''}`}
      aria-label={title}
    >
      <div
        className="meal-event-card__photo"
        style={{ backgroundImage: `url(${coverUrl})` }}
        role="img"
        aria-label={`${title} photo`}
      >
        {dateChip && (
          <span className="meal-event-card__date-chip">{dateChip}</span>
        )}
        <span
          className={`meal-event-card__badge meal-event-card__badge--${badge.tone}`}
        >
          {badge.label}
        </span>
      </div>

      <div className="meal-event-card__body">
        <h3 className="meal-event-card__title">{title}</h3>
        {description && (
          <p className="meal-event-card__description">{description}</p>
        )}
        {price && (
          <div className="meal-event-card__price">
            <span className="meal-event-card__price-prefix">from</span>
            <span className="meal-event-card__price-value">{price}</span>
          </div>
        )}

        <div className="meal-event-card__actions">
          <button
            type="button"
            className="btn btn-primary meal-event-card__primary-cta"
            disabled={primaryDisabled}
            onClick={primaryHandler}
          >
            {!primaryDisabled && (
              <i
                className="fa-solid fa-cart-plus"
                style={{ marginRight: '.4rem' }}
                aria-hidden
              />
            )}
            {primaryLabel}
          </button>

          <div className="meal-event-card__secondary-actions">
            {onAskChef && (
              <button
                type="button"
                className="meal-event-card__link"
                onClick={() => onAskChef(event)}
              >
                <i className="fa-solid fa-message" aria-hidden /> Ask chef
              </button>
            )}
            {canOrder && onAddToPlan && (
              <button
                type="button"
                className="meal-event-card__link"
                onClick={() => onAddToPlan(event)}
              >
                <i className="fa-solid fa-calendar-plus" aria-hidden /> Add to
                plan
              </button>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

// Re-export so consumers can access enums/helpers from one place if needed.
export { BADGE_TONE }
