/**
 * Chef Page Components
 *
 * Re-exports the components and helpers used by the public chef profile page
 * (frontend/src/pages/PublicChef.jsx). Components are added as the page
 * redesign rolls out section-by-section.
 */

export {
  computeAvailabilityState,
  getHeroCTA,
  getMealEventBadge,
  formatEventDateChip,
  spotsRemaining,
  AVAILABILITY_STATUS,
  EVENT_STATUS,
  BADGE_TONE,
} from './chefAvailability'

export { default as ChefHero } from './ChefHero.jsx'
export { default as AvailabilityRibbon } from './AvailabilityRibbon.jsx'
export { default as MealEventCard } from './MealEventCard.jsx'
export { default as MealEventGrid } from './MealEventGrid.jsx'
export { default as ServiceOfferingCard } from './ServiceOfferingCard.jsx'
export { default as ChefAboutSection } from './ChefAboutSection.jsx'
export { default as StickyMobileCTA } from './StickyMobileCTA.jsx'
