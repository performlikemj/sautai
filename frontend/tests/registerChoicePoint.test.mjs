import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const registerPath = resolve('frontend/src/pages/Register.jsx')

function loadRegister() {
  return readFileSync(registerPath, 'utf8')
}

test('Register.jsx has audience toggle (customer/chef buttons)', () => {
  const source = loadRegister()
  assert.match(
    source,
    /looking for a chef|I'm a chef|customer.*chef|chef.*customer/i,
    'Register.jsx should have audience toggle buttons for customer and chef'
  )
})

test('Register.jsx does NOT have auto_meal_plans_enabled in default form state', () => {
  const source = loadRegister()
  // The auto_meal_plans checkbox should not appear as a visible field
  // It may still be in the payload as a default, but the checkbox UI should be removed
  assert.doesNotMatch(
    source,
    /Automatically create weekly meal plans/,
    'Register.jsx should not show auto_meal_plans checkbox (deferred to Profile)'
  )
})

test('Register.jsx default without query params shows customer mode', () => {
  const source = loadRegister()
  // The isChef state should default to false when no query param
  assert.match(
    source,
    /searchParams.*intent.*chef|intent.*===.*'chef'/,
    'Register.jsx should derive chef mode from URL param, defaulting to customer'
  )
})
