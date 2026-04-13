import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const profilePath = resolve(import.meta.dirname, '../src/pages/Profile.jsx')
const homePath = resolve(import.meta.dirname, '../src/pages/Home.jsx')

test('Profile.jsx chef application uses a stepped wizard (applyStep state)', () => {
  const source = readFileSync(profilePath, 'utf8')
  assert.match(source, /applyStep/, 'Should use applyStep state for wizard flow')
})

test('Profile.jsx wizard has 3 steps (About You, Your Location, Review)', () => {
  const source = readFileSync(profilePath, 'utf8')
  assert.match(source, /About You/i, 'Should have "About You" step')
  assert.match(source, /Your Location|Where.*Based/i, 'Should have location confirmation step')
  assert.match(source, /Final Touches|Review/i, 'Should have review/submit step')
})

test('Profile.jsx step 3 has editable summary with Edit buttons', () => {
  const source = readFileSync(profilePath, 'utf8')
  assert.match(
    source,
    /Edit.*setApplyStep\(0\)|setApplyStep\(0\).*Edit/i,
    'Step 3 summary should have Edit buttons that navigate back'
  )
})

test('Profile.jsx step 2 confirms location from profile (no postal code selection)', () => {
  const source = readFileSync(profilePath, 'utf8')
  // Step 2 should show the user's city/country, not an area search picker
  assert.match(
    source,
    /city.*country|address.*city|user.*city/i,
    'Step 2 should display the user\'s city from their profile'
  )
  // Should explain delivery areas come after approval
  assert.match(
    source,
    /after approval|delivery areas|dashboard/i,
    'Should explain that delivery areas are configured after approval'
  )
})

test('Profile.jsx submit handler does NOT send selected_area_ids', () => {
  const source = readFileSync(profilePath, 'utf8')
  // The submit handler should not send area IDs at application time
  assert.doesNotMatch(
    source,
    /fd\.append\('selected_area_ids'/,
    'Submit handler should not send selected_area_ids — postal codes are set post-approval'
  )
})

test('Home.jsx imports and uses ServiceAreaPicker in chef modal', () => {
  const source = readFileSync(homePath, 'utf8')
  assert.match(source, /import\s+ServiceAreaPicker/, 'Home.jsx should import ServiceAreaPicker')
  assert.match(source, /<ServiceAreaPicker/, 'Home.jsx should render ServiceAreaPicker')
})
