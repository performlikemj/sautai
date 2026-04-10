import React, { forwardRef } from 'react'
import { Link } from 'react-router-dom'
import { getHeroCTA } from './chefAvailability'

/**
 * Public chef profile hero — extracted from PublicChef.jsx:1318-1454.
 *
 * Visual differences from the legacy hero:
 *  1. Cover image stays full-bleed but the gradient overlay now darkens the
 *     bottom of the image rather than the entire image, so the photo reads.
 *  2. Avatar overlaps the bottom of the cover, with name + tagline + CTA in
 *     a row beside it (stacks on mobile).
 *  3. Primary CTA is state-aware via getHeroCTA(): "Order now" / "Book a
 *     service" / "Join waitlist" / "Request a quote" depending on chef
 *     availability.
 *  4. Trust badges expand from a single "Verified" pill into individual
 *     icon+label badges (Verified, Background Checked, Food Safety, Insured).
 *
 * Presentational only — connection state, availability state, modal openers,
 * and the IntersectionObserver hookup all stay in PublicChef.jsx.
 */
const ChefHero = forwardRef(function ChefHero(
  {
    chef,
    coverImage,
    cityCountry,
    areaSummary,
    encodedChefSlug,
    authUser,
    viewerOwnChefProfile,
    // Connection state from useConnections in the parent
    connectionAccepted,
    connectionPending,
    canRequestInvitation,
    requestingInvitation,
    onRequestConnection,
    // Availability + modal handlers
    availabilityState,
    onOpenAreasModal,
    onOpenMap,
    onOpenQuoteModal,
  },
  ref,
) {
  if (!chef) return null

  const displayName = chef?.user?.username || 'Chef'
  const tagline =
    chef?.bio || 'Your personal chef for delicious, home-cooked meals'
  const heroCTA = getHeroCTA(chef, availabilityState)

  // The trust badges read from existing chef profile fields.
  const trustBadges = [
    {
      key: 'verified',
      shown: chef?.is_verified,
      icon: 'fa-solid fa-circle-check',
      label: 'Identity verified',
    },
    {
      key: 'background',
      shown: chef?.background_checked,
      icon: 'fa-solid fa-user-shield',
      label: 'Background checked',
    },
    {
      key: 'food-safety',
      shown: chef?.food_handlers_cert,
      icon: 'fa-solid fa-utensils',
      label: 'Food safety certified',
    },
    {
      key: 'insured',
      shown: chef?.insured,
      icon: 'fa-solid fa-shield-halved',
      label: 'Insured',
    },
  ].filter((b) => b.shown)

  function handlePrimaryCTAClick() {
    if (heroCTA.action === 'modal' && heroCTA.target === 'quote-modal') {
      onOpenQuoteModal?.()
      return
    }
    if (heroCTA.action === 'scroll' && typeof document !== 'undefined') {
      const target = document.querySelector(heroCTA.target)
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <section
      id="chef-hero"
      className="chef-hero-v2"
      ref={ref}
      aria-label={`${displayName} hero`}
    >
      <div
        className={`chef-hero-v2__cover${coverImage ? '' : ' chef-hero-v2__cover--no-photo'}`}
        style={
          coverImage ? { backgroundImage: `url(${coverImage})` } : undefined
        }
        aria-hidden
      />

      <div className="chef-hero-v2__content">
        <div className="chef-hero-v2__identity">
          <div className="chef-hero-v2__avatar-wrap">
            {chef.profile_pic_url ? (
              <img
                src={chef.profile_pic_url}
                alt={displayName}
                className="chef-hero-v2__avatar"
              />
            ) : (
              <div className="chef-hero-v2__avatar chef-hero-v2__avatar--placeholder">
                <span>
                  {displayName.slice(0, 1).toUpperCase()}
                </span>
              </div>
            )}
            <ConnectionPlusButton
              viewerOwnChefProfile={viewerOwnChefProfile}
              connectionAccepted={connectionAccepted}
              connectionPending={connectionPending}
              canRequestInvitation={canRequestInvitation}
              requestingInvitation={requestingInvitation}
              authUser={authUser}
              onRequestConnection={onRequestConnection}
            />
          </div>

          <div className="chef-hero-v2__name-block">
            <h1 className="chef-hero-v2__title">{displayName}</h1>
            <p className="chef-hero-v2__tagline">{tagline}</p>

            {(cityCountry || areaSummary?.totalAreas > 0) && (
              <div className="chef-hero-v2__location-row">
                {cityCountry && (
                  <span className="chef-hero-v2__location">
                    <i className="fa-solid fa-location-dot" aria-hidden></i>
                    <strong>{cityCountry}</strong>
                  </span>
                )}
                {areaSummary?.totalAreas > 0 && (
                  <button
                    type="button"
                    className="chef-hero-v2__location-btn"
                    onClick={onOpenAreasModal}
                  >
                    <i
                      className="fa-solid fa-map-location-dot"
                      aria-hidden
                    ></i>
                    Check availability
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="chef-hero-v2__cta-block">
            <button
              type="button"
              className={`btn btn-lg chef-hero-v2__primary-cta ${
                heroCTA.style === 'primary' ? 'btn-primary' : 'btn-outline'
              }`}
              onClick={handlePrimaryCTAClick}
            >
              {heroCTA.label}
              <i
                className="fa-solid fa-arrow-right"
                aria-hidden
                style={{ marginLeft: '.5rem' }}
              ></i>
            </button>

            {connectionAccepted && (
              <Link
                to={`/my-chefs/${chef?.id}`}
                className="chef-hero-v2__hub-link"
              >
                <i className="fa-solid fa-house-user" aria-hidden></i>
                My chef hub
              </Link>
            )}
          </div>
        </div>

        {trustBadges.length > 0 && (
          <ul className="chef-hero-v2__trust-row" aria-label="Trust badges">
            {trustBadges.map((b) => (
              <li key={b.key} className="chef-hero-v2__trust-badge">
                <i className={b.icon} aria-hidden></i>
                <span>{b.label}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="chef-hero-v2__meta-row">
          {chef?.review_summary && (
            <span className="chef-hero-v2__meta-item">
              <i
                className="fa-solid fa-star"
                style={{ color: '#fbbf24' }}
                aria-hidden
              ></i>
              {chef.review_summary}
            </span>
          )}
          {chef?.mehko_active && (
            <span className="chef-hero-v2__meta-item chef-hero-v2__meta-item--mehko">
              <i className="fa-solid fa-house-chimney" aria-hidden></i>
              MEHKO · Home kitchen
            </span>
          )}
          {Array.isArray(chef.photos) && chef.photos.length > 0 && (
            <Link
              to={`/c/${encodedChefSlug}/gallery`}
              className="chef-hero-v2__meta-item chef-hero-v2__meta-link"
            >
              <i className="fa-solid fa-images" aria-hidden></i>
              {chef.photos.length} photos
            </Link>
          )}
          {onOpenMap && (
            <button
              type="button"
              className="chef-hero-v2__meta-item chef-hero-v2__meta-link"
              onClick={onOpenMap}
            >
              <i className="fa-solid fa-map-marker-alt" aria-hidden></i>
              Map
            </button>
          )}
          {chef?.calendly_url && (
            <a
              href={chef.calendly_url}
              target="_blank"
              rel="noopener noreferrer"
              className="chef-hero-v2__meta-item chef-hero-v2__meta-link"
            >
              <i className="fa-regular fa-calendar" aria-hidden></i>
              Consult
            </a>
          )}
        </div>
      </div>
    </section>
  )
})

/**
 * Small overlay button on the avatar that mirrors the existing connection
 * state machine from PublicChef.jsx. Keeps the visual signal but moves the
 * complexity into a self-contained sub-component.
 */
function ConnectionPlusButton({
  viewerOwnChefProfile,
  connectionAccepted,
  connectionPending,
  canRequestInvitation,
  requestingInvitation,
  authUser,
  onRequestConnection,
}) {
  if (viewerOwnChefProfile) return null

  if (connectionAccepted) {
    return (
      <span
        className="chef-hero-v2__connect-btn chef-hero-v2__connect-btn--connected"
        title="Connected"
      >
        <i className="fa-solid fa-check" aria-hidden></i>
      </span>
    )
  }

  if (connectionPending) {
    return (
      <span
        className="chef-hero-v2__connect-btn chef-hero-v2__connect-btn--pending"
        title="Request pending"
      >
        <i className="fa-solid fa-clock" aria-hidden></i>
      </span>
    )
  }

  if (canRequestInvitation) {
    return (
      <button
        type="button"
        className="chef-hero-v2__connect-btn"
        onClick={onRequestConnection}
        disabled={requestingInvitation}
        title="Add this chef"
        aria-label="Add this chef"
      >
        {requestingInvitation ? (
          <span className="chef-hero-v2__connect-spinner" aria-hidden />
        ) : (
          <i className="fa-solid fa-plus" aria-hidden></i>
        )}
      </button>
    )
  }

  if (!authUser) {
    return (
      <button
        type="button"
        className="chef-hero-v2__connect-btn"
        onClick={() => {
          if (typeof window === 'undefined') return
          const next = `${window.location.pathname}${window.location.search}`
          window.location.href = `/login?next=${encodeURIComponent(next)}`
        }}
        title="Sign in to add this chef"
        aria-label="Sign in to add this chef"
      >
        <i className="fa-solid fa-plus" aria-hidden></i>
      </button>
    )
  }

  return null
}

export default ChefHero
