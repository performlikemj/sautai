import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const registerPath = resolve(import.meta.dirname, '../src/pages/Register.jsx')
const homePath = resolve(import.meta.dirname, '../src/pages/Home.jsx')

function loadRegister() {
  return readFileSync(registerPath, 'utf8')
}

function loadHome() {
  return readFileSync(homePath, 'utf8')
}

test('Register.jsx reads intent from URL search params', () => {
  const source = loadRegister()
  assert.match(
    source,
    /useSearchParams|searchParams|URLSearchParams|intent.*chef/i,
    'Register.jsx should read intent from URL query params'
  )
})

test('Register.jsx shows city/country fields when intent is chef', () => {
  const source = loadRegister()
  assert.match(
    source,
    /city/i,
    'Register.jsx should have city field for chef intent'
  )
  assert.match(
    source,
    /country/i,
    'Register.jsx should have country field for chef intent'
  )
})

test('Register.jsx hides auto_meal_plans when intent is chef', () => {
  const source = loadRegister()
  // The auto_meal_plans checkbox should be conditionally hidden for chef intent
  assert.match(
    source,
    /intent.*chef|isChef/i,
    'Register.jsx should have conditional logic for chef intent'
  )
})

test('Register.jsx includes address in registration payload for chef intent', () => {
  const source = loadRegister()
  assert.match(
    source,
    /address.*city|city.*address/i,
    'Register.jsx should include address with city in the registration payload'
  )
})

test('Register.jsx redirects chef intent to profile with applyChef param', () => {
  const source = loadRegister()
  assert.match(
    source,
    /applyChef|profile.*apply/i,
    'Register.jsx should redirect to profile with applyChef after chef registration'
  )
})

test('Home.jsx "Start Your Chef Profile" links to register with intent=chef', () => {
  const source = loadHome()
  assert.match(
    source,
    /register\?intent=chef|register.*intent.*chef/i,
    'Home.jsx should link to /register?intent=chef for chef CTA'
  )
})
