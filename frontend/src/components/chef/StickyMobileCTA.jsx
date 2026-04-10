import React from 'react'
import { getHeroCTA } from './chefAvailability'

/**
 * Bottom-pinned mobile CTA bar that appears once the hero scrolls out of view.
 *
 * Hidden on desktop via CSS media query. Visibility is driven by the parent's
 * existing IntersectionObserver (showStickyCTA prop) — same observer that
 * used to drive the legacy sticky mini-widget at PublicChef.jsx:1457-1511.
 *
 * The label/target mirror the hero's primary CTA via getHeroCTA() so we have
 * a single source of truth for what the chef-page-level "next action" is.
 */
export default function StickyMobileCTA({
  chef,
  availabilityState,
  visible,
  onOpenQuoteModal,
}) {
  if (!chef || !visible) return null

  const cta = getHeroCTA(chef, availabilityState)

  function handleClick(e) {
    if (cta.action === 'modal' && cta.target === 'quote-modal') {
      e.preventDefault()
      onOpenQuoteModal?.()
      return
    }
    if (cta.action === 'scroll' && typeof document !== 'undefined') {
      const target = document.querySelector(cta.target)
      if (target) {
        e.preventDefault()
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }

  return (
    <div
      className="sticky-mobile-cta"
      role="region"
      aria-label="Quick actions"
    >
      <a
        href={cta.action === 'scroll' ? cta.target : '#'}
        className={`btn btn-lg sticky-mobile-cta__btn ${
          cta.style === 'primary' ? 'btn-primary' : 'btn-outline'
        }`}
        onClick={handleClick}
      >
        {cta.label}
        <i
          className="fa-solid fa-arrow-right"
          aria-hidden
          style={{ marginLeft: '.5rem' }}
        ></i>
      </a>
    </div>
  )
}
