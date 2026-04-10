import React from 'react'
import { Link } from 'react-router-dom'
import MealEventCard from './MealEventCard.jsx'

/**
 * Section wrapper for upcoming meal events.
 *
 * Replaces PublicChef.jsx:1645-1755 — the existing "Weekly Menu" section that
 * rendered events as text rows. Handles loading, waitlist (chef on break),
 * empty state with quote CTA, and the populated card grid.
 *
 * All state and handlers are owned by PublicChef.jsx and passed in as props,
 * so this component stays presentational.
 */
export default function MealEventGrid({
  chef,
  events = [],
  authUser,
  servesMyArea,
  // Loading + waitlist gates (parent decides which UI to show)
  loading = false,
  showWaitlist = false,
  waitlist,
  subscribing = false,
  unsubscribing = false,
  onSubscribe,
  onUnsubscribe,
  // Card handlers
  onAddToCart,
  onAddToPlan,
  onAskChef,
  // Empty state handler
  onRequestQuote,
}) {
  return (
    <div className="chef-section" id="featured-menu">
      <div className="chef-section-header">
        <div>
          <h2 className="chef-section-title">
            <i className="fa-solid fa-calendar-week" aria-hidden></i>
            Upcoming Meals
          </h2>
          <p className="chef-section-subtitle">
            Pre-order delicious meals for pickup or delivery
          </p>
        </div>
        {servesMyArea != null && (
          <div
            className={`chef-availability-badge ${
              servesMyArea ? 'available' : 'unavailable'
            }`}
          >
            <i
              className={`fa-solid fa-${
                servesMyArea ? 'circle-check' : 'circle-xmark'
              }`}
              aria-hidden
            ></i>
            {servesMyArea ? 'Available in your area' : 'Outside service area'}
          </div>
        )}
      </div>

      <div className="meal-event-grid-container">
        {loading ? (
          <MealEventGridSkeleton />
        ) : showWaitlist ? (
          <WaitlistCard
            authUser={authUser}
            waitlist={waitlist}
            subscribing={subscribing}
            unsubscribing={unsubscribing}
            onSubscribe={onSubscribe}
            onUnsubscribe={onUnsubscribe}
          />
        ) : events.length === 0 ? (
          <EmptyState authUser={authUser} onRequestQuote={onRequestQuote} />
        ) : (
          <div className="meal-event-grid">
            {events.map((event) => (
              <MealEventCard
                key={event.id}
                event={event}
                chef={chef}
                authUser={authUser}
                servesMyArea={servesMyArea}
                onAddToCart={onAddToCart}
                onAddToPlan={onAddToPlan}
                onAskChef={onAskChef}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function MealEventGridSkeleton() {
  return (
    <div className="meal-event-grid">
      {[0, 1, 2].map((i) => (
        <div key={i} className="meal-event-card meal-event-card--skeleton">
          <div className="meal-event-card__photo meal-event-card__photo--skeleton" />
          <div className="meal-event-card__body">
            <div className="meal-event-card__skeleton-line meal-event-card__skeleton-line--title" />
            <div className="meal-event-card__skeleton-line" />
            <div className="meal-event-card__skeleton-line meal-event-card__skeleton-line--short" />
          </div>
        </div>
      ))}
    </div>
  )
}

function WaitlistCard({
  authUser,
  waitlist,
  subscribing,
  unsubscribing,
  onSubscribe,
  onUnsubscribe,
}) {
  if (!authUser) {
    const next =
      typeof window !== 'undefined'
        ? `${window.location.pathname}${window.location.search}`
        : '/'
    return (
      <div className="card meal-event-waitlist-card" id="waitlist">
        <h4>Get notified</h4>
        <p className="muted">
          Sign in to get notified when this chef starts accepting orders.
        </p>
        <Link
          className="btn btn-primary"
          to={`/login?next=${encodeURIComponent(next)}`}
        >
          Sign in
        </Link>
      </div>
    )
  }

  return (
    <div className="card meal-event-waitlist-card" id="waitlist">
      <h4>Get notified</h4>
      {waitlist?.subscribed ? (
        <>
          <p className="muted">
            You'll be notified when this chef opens orders.
          </p>
          <button
            type="button"
            className="btn btn-outline"
            disabled={unsubscribing}
            onClick={onUnsubscribe}
          >
            {unsubscribing ? 'Unsubscribing…' : 'Unsubscribe'}
          </button>
        </>
      ) : (
        <>
          <p className="muted">
            No upcoming meals yet. Get notified when this chef starts accepting
            orders.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            disabled={subscribing || waitlist?.can_subscribe === false}
            onClick={onSubscribe}
          >
            {subscribing ? 'Subscribing…' : 'Notify me'}
          </button>
        </>
      )}
    </div>
  )
}

function EmptyState({ authUser, onRequestQuote }) {
  return (
    <div className="empty-state-professional">
      <div className="icon" aria-hidden>
        📅
      </div>
      <h3>Menu coming soon</h3>
      <p>
        This chef is preparing new meal offerings. Check back soon or request a
        quote for custom meal preparation services.
      </p>
      <button
        type="button"
        className="btn btn-primary btn-lg"
        onClick={() => {
          if (!authUser && typeof window !== 'undefined') {
            const next = `${window.location.pathname}${window.location.search}`
            window.location.href = `/login?next=${encodeURIComponent(next)}`
            return
          }
          onRequestQuote?.()
        }}
      >
        <i
          className="fa-solid fa-file-invoice"
          style={{ marginRight: '.5rem' }}
          aria-hidden
        ></i>
        Request custom meals
      </button>
    </div>
  )
}
