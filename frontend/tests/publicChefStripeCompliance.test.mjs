/**
 * PublicChef Stripe Connect Compliance Tests
 * 
 * These tests verify that the chef profile page contains all elements
 * required for Stripe Connect approval, including:
 * - Verification badges/indicators
 * - Service provider disclosure
 * - Legal policy links (Terms, Privacy, Refund)
 * - Payment security messaging
 * - Business legitimacy indicators
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

const publicChefPath = resolve('src/pages/PublicChef.jsx')
const stylesPath = resolve('src/styles.css')
const chefComponentsDir = resolve('src/components/chef')

function loadPublicChef() {
  return readFileSync(publicChefPath, 'utf8')
}

/** Load PublicChef.jsx + all extracted chef components as one combined source */
function loadPublicChefWithComponents() {
  let combined = readFileSync(publicChefPath, 'utf8')
  try {
    for (const f of readdirSync(chefComponentsDir)) {
      if (f.endsWith('.jsx') || f.endsWith('.js')) {
        combined += '\n' + readFileSync(resolve(chefComponentsDir, f), 'utf8')
      }
    }
  } catch {}
  return combined
}

function loadStyles() {
  return readFileSync(stylesPath, 'utf8')
}

// =============================================================================
// VERIFICATION INDICATORS - Critical for establishing legitimacy
// =============================================================================

test('PublicChef displays verification indicators for verified chefs', () => {
  const source = loadPublicChef()
  // Component uses hero-verified class for verification status
  assert.match(
    source,
    /hero-verified|is_verified|Verified/,
    'Chef profile should display verification status.'
  )
})

test('PublicChef shows Identity Verified in verification tooltip', () => {
  const source = loadPublicChefWithComponents()
  assert.match(
    source,
    /Identity [Vv]erified/,
    'Chef profile should display "Identity Verified" in verification tooltip.'
  )
})

test('PublicChef supports Background Checked indicator', () => {
  const source = loadPublicChefWithComponents()
  assert.match(
    source,
    /Background [Cc]hecked/,
    'Chef profile should support displaying "Background Checked" indicator.'
  )
  assert.match(
    source,
    /background_checked/,
    'Background Checked should be tied to chef.background_checked field.'
  )
})

test('PublicChef supports Insured status indicator', () => {
  const source = loadPublicChefWithComponents()
  assert.match(
    source,
    /Insured/,
    'Chef profile should support displaying insurance status.'
  )
  assert.match(
    source,
    /chef\?\.insured/,
    'Insurance badge should be tied to chef.insured field.'
  )
})

// =============================================================================
// SERVICE PROVIDER DISCLOSURE - Clear business disclosure
// =============================================================================

test('PublicChef includes service provider disclosure section', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /service-provider-disclosure/,
    'Chef profile should include a service-provider-disclosure section.'
  )
})

test('PublicChef service provider disclosure describes the service clearly', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /independent personal chef/i,
    'Disclosure should describe the chef as an independent service provider.'
  )
  assert.match(
    source,
    /Stripe/,
    'Disclosure should mention Stripe for payment processing.'
  )
})

// =============================================================================
// LEGAL POLICY LINKS - Required for Stripe compliance
// =============================================================================

test('PublicChef displays Terms of Service link', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /Terms of Service/,
    'Chef profile should display "Terms of Service" link.'
  )
})

test('PublicChef displays Privacy Policy link', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /Privacy Policy/,
    'Chef profile should display "Privacy Policy" link.'
  )
})

test('PublicChef displays Cancellation & Refund Policy link', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /Cancellation & Refund Policy|Refund Policy/,
    'Chef profile should display cancellation/refund policy link.'
  )
  assert.match(
    source,
    /\/refund-policy/,
    'Refund policy should link to /refund-policy page.'
  )
})

// =============================================================================
// CONTACT & SUPPORT - Required for customer trust
// =============================================================================

test('PublicChef displays platform support contact', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /support@sautai\.com/,
    'Chef profile should display platform support email.'
  )
  assert.match(
    source,
    /mailto:support@sautai\.com/,
    'Support email should be a clickable mailto link.'
  )
})

// =============================================================================
// PAYMENT SECURITY MESSAGING - Stripe approval factor
// =============================================================================

test('PublicChef mentions Stripe for payment security', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /Stripe/i,
    'Payment section should mention Stripe as the payment processor.'
  )
})

test('PublicChef describes secure payment processing', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /securely|secure|PCI/i,
    'Chef profile should describe payments as secure.'
  )
})

test('PublicChef includes Stripe branding', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /fa-brands fa-stripe|fa-stripe/,
    'Payment section should include Stripe icon.'
  )
})

// =============================================================================
// BOOKING FLOW INTEGRATION
// =============================================================================

test('PublicChef has Book Chef Services CTA', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /Book Chef Services?|Book.*Service/i,
    'Chef profile should have a booking call-to-action.'
  )
})

test('PublicChef integrates with cart for service booking', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /addItem|addToCart|useCart/i,
    'Chef profile should integrate with cart context for adding services.'
  )
})

// =============================================================================
// CSS STYLES FOR COMPLIANCE ELEMENTS
// =============================================================================

test('Styles include trust-badges styling', () => {
  const styles = loadStyles()
  assert.match(
    styles,
    /\.trust-badges?\s*\{/,
    'Styles should define trust badge styling.'
  )
})

test('Styles include responsive breakpoints', () => {
  const styles = loadStyles()
  assert.match(
    styles,
    /@media.*max-width.*768px/,
    'Styles should include responsive breakpoints for mobile.'
  )
})

// =============================================================================
// AUTHENTICATION-GATED FEATURES
// =============================================================================

test('PublicChef checks authentication state for actions', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /isAuthenticated|user\s*\?\.|!user/,
    'Chef profile should check authentication state for certain actions.'
  )
})

test('PublicChef redirects unauthenticated users for protected actions', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /navigate\s*\(\s*['"`]\/login|\/login/,
    'Protected actions should redirect to login for unauthenticated users.'
  )
})

// =============================================================================
// SERVICE DESCRIPTION CLARITY
// =============================================================================

test('PublicChef displays chef bio/description', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /chef\.bio|chef\.description|chef\?\.bio/,
    'Chef profile should display the chef bio/description.'
  )
})

test('PublicChef displays chef location', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /chef\.city|chef\.country|location/i,
    'Chef profile should display chef location information.'
  )
})

test('PublicChef displays service area information', () => {
  const source = loadPublicChef()
  assert.match(
    source,
    /Serves|service_area|serves_area/i,
    'Chef profile should indicate service area coverage.'
  )
})
