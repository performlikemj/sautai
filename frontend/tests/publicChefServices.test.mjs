import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

const publicChefPath = resolve('src/pages/PublicChef.jsx')
const chefComponentsDir = resolve('src/components/chef')

function loadSource(){
  return readFileSync(publicChefPath, 'utf8')
}

/** Load PublicChef.jsx + all extracted chef components as one combined source */
function loadSourceWithComponents(){
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

test('PublicChef calls services endpoint with viewer postal code when available', () => {
  const source = loadSource()
  assert.match(
    source,
    /api\.get\('\/services\/offerings\/'[\s\S]*postal_code/,
    'Expected PublicChef to request /services/offerings/ with a postal_code parameter.'
  )
})

test('PublicChef surfaces out-of-area messaging for services', () => {
  const source = loadSource()
  assert.match(
    source,
    /services aren't available in your area yet\./,
    'Expected a customer-facing message when services are outside the viewer\'s area.'
  )
})

test('PublicChef exposes a CTA so guests can book a chef service tier', () => {
  const source = loadSourceWithComponents()
  assert.match(
    source,
    /Add to Cart|Quick Book|Book this service tier|Add to cart|Quick book/i,
    'Expected a visible button that invites the guest to book a service tier.'
  )
})

test('PublicChef creates chef service orders before starting checkout', () => {
  const source = loadSource()
  assert.match(
    source,
    /api\.post\(`\/services\/orders\//,
    'Expected PublicChef to create chef service orders via POST /services/orders/.'
  )
  assert.match(
    source,
    /\/services\/orders\/\$\{[^}]+\}\/checkout/,
    'Expected PublicChef to request a checkout session for the created order.'
  )
})

test('PublicChef labels whether a service tier is recurring', () => {
  const source = loadSourceWithComponents()
  assert.match(
    source,
    /tier-recurring-chip|tier-once-chip|schedule-chip--recurring|schedule-chip--once|Recurring|One-time/,
    'Expected a prominent visual badge indicating recurring vs. one-time tier.'
  )
})

test('PublicChef renders start time as a half-hour dropdown', () => {
  const source = loadSource()
  assert.match(
    source,
    /<select[^>]*serviceStartTime/,
    'Expected a select element for choosing service start time.'
  )
  assert.match(
    source,
    /<option[^>]*value=\{time\}/,
    'Start time select should map option values to the half-hour list.'
  )
})

test('PublicChef routes gallery clicks to the dedicated gallery page', () => {
  const source = loadSource()
  assert.match(
    source,
    /useNavigate\(/,
    'Expected PublicChef to use the router navigate hook for gallery routing.'
  )
  assert.match(
    source,
    /navigate\(.*\/c\/\$\{[^}]+\}\/gallery\?photo=\$\{[^}]+\}/,
    'Expected PublicChef to navigate to the chef gallery page with a selected photo parameter.'
  )
})

test('PublicChef logs serializer payload from the id-based fetch', () => {
  const source = loadSource()
  assert.ok(source.includes("[PublicChef] serializer /chefs/"), 'Expected PublicChef to log the serializer output for the ID-based fetch.')
})
