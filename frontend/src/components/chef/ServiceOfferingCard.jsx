import React from 'react'

/**
 * Visual refresh of the per-offering services card from PublicChef.jsx:1789-2178.
 *
 * Renders one chef service offering with all its tiers as a list. The booking
 * form lives in PublicChef.jsx because it has 14+ state hooks and would be
 * unwieldy to lift out — it's slotted in below the active tier via the
 * `renderBookingForm` render prop.
 *
 * Naming note: the plan filename was `ServiceTierCard.jsx` but each card
 * actually renders an offering with multiple tiers inside, so this name is
 * more accurate. The plan's intent is preserved.
 *
 * Props:
 *  - offering: the service offering object
 *  - bookingActive(tier): predicate — true if this tier's booking form is open
 *  - onAddToCart(tier): handler for the cart button
 *  - onToggleBooking(tier): handler for the Quick Book / Close Form button
 *  - renderBookingForm(tier): render prop returning JSX (or null) for the
 *    inline booking form below the active tier
 */
export default function ServiceOfferingCard({
  offering,
  bookingActive,
  onAddToCart,
  onToggleBooking,
  renderBookingForm,
}) {
  if (!offering) return null

  const tierSummaries = Array.isArray(offering.tier_summary)
    ? offering.tier_summary
        .filter((s) => (typeof s === 'string' ? s.trim() : Boolean(s)))
        .map((s) => (typeof s === 'string' ? s.trim() : String(s)))
    : []

  const tiers = Array.isArray(offering.tiers)
    ? offering.tiers.filter((t) => t && t.hidden !== true && t.soft_deleted !== true)
    : []

  const icon = serviceIconClass(offering.service_type)

  return (
    <article className="service-offering-card">
      <header className="service-offering-card__header">
        <div className="service-offering-card__icon" aria-hidden>
          <i className={icon}></i>
        </div>
        <div className="service-offering-card__heading">
          <h3 className="service-offering-card__title">
            {offering.title || 'Service offering'}
          </h3>
          <p className="service-offering-card__subtype">
            {offering.service_type_label || offering.service_type || 'Service'}
          </p>
        </div>
        {offering.max_travel_miles ? (
          <span className="chip small service-offering-card__travel-chip">
            {offering.max_travel_miles} mi max
          </span>
        ) : null}
      </header>

      {offering.description && (
        <p className="service-offering-card__description">
          {offering.description}
        </p>
      )}

      {tierSummaries.length > 0 && (
        <div className="service-offering-card__summaries">
          <div className="label">Tier overview</div>
          <ul>
            {tierSummaries.map((summary, idx) => (
              <li key={idx}>{summary}</li>
            ))}
          </ul>
        </div>
      )}

      {tiers.length > 0 && (
        <div className="service-offering-card__tiers">
          <div className="label">Tier details</div>
          <div className="service-offering-card__tier-list">
            {tiers.map((tier, idx) => (
              <ServiceTierRow
                key={tier.id || `${offering.id || offering.title}-tier-${idx}`}
                tier={tier}
                offering={offering}
                isActive={Boolean(bookingActive?.(tier))}
                onAddToCart={() => onAddToCart?.(tier)}
                onToggleBooking={() => onToggleBooking?.(tier)}
                bookingFormSlot={renderBookingForm?.(tier)}
              />
            ))}
          </div>
        </div>
      )}
    </article>
  )
}

/**
 * One row inside a ServiceOfferingCard for a single tier (household range +
 * price + recurring chip + action buttons + slot for the active booking form).
 */
function ServiceTierRow({
  tier,
  offering,
  isActive,
  onAddToCart,
  onToggleBooking,
  bookingFormSlot,
}) {
  if (!tier) return null

  const priceCents =
    tier.desired_unit_amount_cents ??
    tier.unit_amount_cents ??
    tier.price_cents
  const price = Number.isFinite(Number(priceCents))
    ? (Number(priceCents) / 100).toFixed(2)
    : null
  const currency = String(
    tier.currency || offering.currency || 'USD',
  ).toUpperCase()
  const isRecurring = Boolean(tier.is_recurring || tier.recurrence_interval)
  const householdMin = tier.household_min ?? tier.household_start ?? null
  const householdMax = tier.household_max ?? tier.household_end ?? null
  const recurrenceLabel = tier.recurrence_interval
    ? String(tier.recurrence_interval).replace(/_/g, ' ')
    : ''
  const recurrenceText = isRecurring
    ? `Recurring${recurrenceLabel ? ` · ${recurrenceLabel}` : ''}`
    : 'One-time'

  const householdLabel =
    householdMin != null && householdMax != null
      ? `${householdMin}–${householdMax} people`
      : householdMin != null
        ? `${householdMin}+ people`
        : 'Household size flexible'

  return (
    <div
      className={`service-tier-row${isActive ? ' service-tier-row--active' : ''}`}
    >
      <div className="service-tier-row__main">
        <div className="service-tier-row__heading">
          <h4 className="service-tier-row__title">
            {tier.display_label || tier.name || 'Tier'}
          </h4>
          <span
            className={`chip small service-tier-row__schedule-chip ${
              isRecurring
                ? 'service-tier-row__schedule-chip--recurring'
                : 'service-tier-row__schedule-chip--once'
            }`}
          >
            {recurrenceText}
          </span>
        </div>
        <div className="service-tier-row__meta">
          <span className="service-tier-row__household">{householdLabel}</span>
          {price && (
            <span className="service-tier-row__price">
              ${price} {currency}
            </span>
          )}
        </div>
        {tier.description && (
          <p className="service-tier-row__description">{tier.description}</p>
        )}
        <ServiceIncludesList offering={offering} tier={tier} />
      </div>

      <div className="service-tier-row__actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={onAddToCart}
          title="Add to cart and fill in details in the cart sidebar"
        >
          <i
            className="fa-solid fa-cart-plus"
            aria-hidden
            style={{ marginRight: '.35rem' }}
          ></i>
          Add to cart
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={onToggleBooking}
          aria-expanded={isActive}
          title="Fill in booking details here and proceed directly to checkout"
        >
          <i
            className="fa-solid fa-bolt"
            aria-hidden
            style={{ marginRight: '.35rem' }}
          ></i>
          {isActive ? 'Close form' : 'Quick book'}
        </button>
      </div>

      {isActive && bookingFormSlot ? (
        <div className="service-tier-row__booking-form">{bookingFormSlot}</div>
      ) : null}
    </div>
  )
}

/**
 * "What's included" + "Not included" lists. Same content as the legacy hardcoded
 * lists at PublicChef.jsx:1862-1924, lifted verbatim so we don't change copy
 * mid-redesign.
 */
function ServiceIncludesList({ offering, tier }) {
  const householdMin = tier?.household_min ?? tier?.household_start ?? null
  const householdMax = tier?.household_max ?? tier?.household_end ?? null
  const isRecurring = Boolean(tier?.is_recurring || tier?.recurrence_interval)
  const householdRange =
    householdMin && householdMax
      ? `${householdMin}-${householdMax}`
      : householdMin || householdMax || 'your'
  const personLabel =
    householdMin === 1 && householdMax === 1 ? 'person' : 'people'
  const type = offering?.service_type

  let included
  if (type === 'home_chef' || type === 'in_house') {
    included = [
      'Professional chef arrives at your home',
      'Menu planning and customization',
      'Grocery shopping with itemized receipts',
      'Fresh cooking in your kitchen',
      `Meal preparation for ${householdRange} ${personLabel}`,
      'Storage containers and labeling',
      'Full kitchen cleanup',
      'Reheating and storage instructions',
    ]
  } else if (type === 'weekly_prep' || type === 'bulk_prep') {
    included = [
      'Customized meal plan consultation',
      'Grocery shopping with receipts provided',
      'Bulk meal preparation',
      `Portioned meals for ${householdRange} ${personLabel}`,
      'Food-safe storage containers',
      'Meal labels with dates and instructions',
      'Kitchen cleanup after prep',
    ]
    if (isRecurring) included.push('Flexible recurring schedule')
  } else if (type === 'event') {
    included = [
      'Custom event menu planning',
      'Ingredient sourcing and procurement',
      'On-site food preparation and setup',
      `Serving for ${householdRange} guests`,
      'Professional presentation and plating',
      'Event cleanup and breakdown',
      'Coordination with event timeline',
    ]
  } else {
    included = [
      'Professional chef service',
      'Menu planning and consultation',
      'Grocery shopping for ingredients',
      'Meal preparation and cooking',
      'Storage containers provided',
      'Kitchen cleanup included',
      'Heating instructions provided',
    ]
  }

  const excluded = [
    'Specialty ingredients over $50 (billed separately)',
    'Kitchen equipment or appliances',
    'Alcohol or beverages (unless specified)',
    'Parking fees or tolls',
  ]
  if (type === 'event') {
    excluded.push(
      'Venue rental or event space',
      'Tableware, linens, or decorations',
      'Wait staff or service personnel',
    )
  }

  return (
    <details className="service-tier-row__includes">
      <summary>What's included &amp; not included</summary>
      <div className="service-tier-row__includes-grid">
        <div className="service-tier-row__includes-block">
          <div className="service-tier-row__includes-heading service-tier-row__includes-heading--positive">
            ✓ Included
          </div>
          <ul>
            {included.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="service-tier-row__includes-block">
          <div className="service-tier-row__includes-heading service-tier-row__includes-heading--negative">
            ✗ Not included
          </div>
          <ul>
            {excluded.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
    </details>
  )
}

function serviceIconClass(type) {
  switch (type) {
    case 'home_chef':
    case 'in_house':
      return 'fa-solid fa-house-user'
    case 'weekly_prep':
      return 'fa-solid fa-box-open'
    case 'bulk_prep':
      return 'fa-solid fa-utensils'
    case 'event':
      return 'fa-solid fa-champagne-glasses'
    default:
      return 'fa-solid fa-concierge-bell'
  }
}
