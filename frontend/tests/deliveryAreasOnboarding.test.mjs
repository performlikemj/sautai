import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const checklistPath = resolve(import.meta.dirname, '../src/components/OnboardingChecklist.jsx')
const dashboardPath = resolve(import.meta.dirname, '../src/pages/ChefDashboard.jsx')

test('OnboardingChecklist includes a delivery areas step', () => {
  const source = readFileSync(checklistPath, 'utf8')
  assert.match(source, /delivery/i, 'Should have a delivery step in STEPS array')
  assert.match(source, /Delivery Areas|Set Delivery/i, 'Step should be titled "Delivery Areas" or similar')
})

test('ChefDashboard completionState tracks delivery areas', () => {
  const source = readFileSync(dashboardPath, 'utf8')
  assert.match(
    source,
    /delivery.*postal|postal.*delivery|serving_postalcodes.*delivery|delivery.*areaStatus/i,
    'completionState should track whether chef has delivery areas configured'
  )
})

test('ChefDashboard delivery section uses AreaSearchPicker', () => {
  const source = readFileSync(dashboardPath, 'utf8')
  assert.match(source, /import\s+AreaSearchPicker/, 'Should import AreaSearchPicker')
  assert.match(source, /<AreaSearchPicker/, 'Should render AreaSearchPicker in delivery section')
})

test('ChefDashboard delivery section shows approved areas as chips', () => {
  const source = readFileSync(dashboardPath, 'utf8')
  assert.match(
    source,
    /approved_areas.*map|areaStatus.*approved/i,
    'Should display approved areas from areaStatus'
  )
})

test('ChefDashboard delivery section has save/submit action', () => {
  const source = readFileSync(dashboardPath, 'utf8')
  assert.match(
    source,
    /submitAreaRequest|Request.*Area|Save.*Area|Save Changes/i,
    'Should have a submit/save action for delivery areas'
  )
})

test('ChefDashboard delivery section shows postal code summary', () => {
  const source = readFileSync(dashboardPath, 'utf8')
  assert.match(
    source,
    /total_postal_codes|postal.code/i,
    'Should display total postal code count as a summary'
  )
})
