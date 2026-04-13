import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const profilePath = resolve('frontend/src/pages/Profile.jsx')

function loadProfile() {
  return readFileSync(profilePath, 'utf8')
}

test('Profile.jsx checks chef application status on mount', () => {
  const source = loadProfile()
  assert.match(
    source,
    /check-chef-status|checkChefStatus|chef.status/i,
    'Profile.jsx should call check-chef-status endpoint'
  )
})

test('Profile.jsx displays pending application status', () => {
  const source = loadProfile()
  assert.match(
    source,
    /pending|under review|submitted/i,
    'Profile.jsx should show pending application status to the user'
  )
})

test('Profile.jsx has character count or minLength validation for bio', () => {
  const source = loadProfile()
  // Should have either character count display or minLength check for bio
  assert.match(
    source,
    /bio.*length|length.*bio|char.*bio|bio.*char|bio.*50|50.*bio/i,
    'Profile.jsx should validate bio length (minimum 50 characters)'
  )
})

test('Profile.jsx has character count or minLength validation for experience', () => {
  const source = loadProfile()
  assert.match(
    source,
    /experience.*length|length.*experience|char.*experience|experience.*char|experience.*20|20.*experience/i,
    'Profile.jsx should validate experience length (minimum 20 characters)'
  )
})

test('Profile.jsx parses field_errors from API response', () => {
  const source = loadProfile()
  assert.match(
    source,
    /field_errors/,
    'Profile.jsx should handle field_errors from API validation response'
  )
})
