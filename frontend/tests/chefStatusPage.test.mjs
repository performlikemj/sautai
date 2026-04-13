import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

const appPath = resolve('frontend/src/App.jsx')
const statusPagePath = resolve('frontend/src/pages/ChefStatus.jsx')

test('ChefStatus.jsx page exists', () => {
  assert.ok(
    existsSync(statusPagePath),
    'frontend/src/pages/ChefStatus.jsx should exist'
  )
})

test('App.jsx contains route for /chef-status', () => {
  const source = readFileSync(appPath, 'utf8')
  assert.match(
    source,
    /chef-status/,
    'App.jsx should have a route for /chef-status'
  )
})

test('ChefStatus.jsx has polling logic', () => {
  const source = readFileSync(statusPagePath, 'utf8')
  assert.match(
    source,
    /setTimeout|setInterval|useEffect.*check/i,
    'ChefStatus.jsx should have polling logic to check status periodically'
  )
})

test('ChefStatus.jsx calls check-chef-status endpoint', () => {
  const source = readFileSync(statusPagePath, 'utf8')
  assert.match(
    source,
    /check-chef-status/,
    'ChefStatus.jsx should call the check-chef-status API endpoint'
  )
})

test('ChefStatus.jsx shows different states (pending/approved/not applied)', () => {
  const source = readFileSync(statusPagePath, 'utf8')
  assert.match(source, /pending|under review/i, 'Should show pending state')
  assert.match(source, /approved|congratulations/i, 'Should show approved state')
})

test('App.jsx wraps chef-status in ProtectedRoute', () => {
  const source = readFileSync(appPath, 'utf8')
  // The route should be inside a ProtectedRoute wrapper
  assert.match(
    source,
    /ProtectedRoute.*ChefStatus|chef-status/i,
    'chef-status route should be protected'
  )
})
