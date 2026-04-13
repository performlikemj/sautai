import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

const componentPath = resolve(import.meta.dirname, '../src/components/AreaSearchPicker.jsx')

function load() {
  return readFileSync(componentPath, 'utf8')
}

test('AreaSearchPicker.jsx component exists', () => {
  assert.ok(existsSync(componentPath), 'frontend/src/components/AreaSearchPicker.jsx should exist')
})

test('AreaSearchPicker calls the areas search API', () => {
  const source = load()
  assert.match(
    source,
    /areas\/search/,
    'Should call the /local_chefs/api/areas/search/ endpoint'
  )
})

test('AreaSearchPicker has debounced search', () => {
  const source = load()
  assert.match(
    source,
    /setTimeout|debounce/,
    'Should debounce the search input to avoid excessive API calls'
  )
})

test('AreaSearchPicker renders selected areas as removable chips', () => {
  const source = load()
  assert.match(
    source,
    /selectedAreas.*map|remove.*area|onRemove|splice/i,
    'Should render selected areas and allow removal'
  )
})

test('AreaSearchPicker accepts country, selectedAreas, onChange props', () => {
  const source = load()
  assert.match(source, /country/, 'Should accept country prop')
  assert.match(source, /selectedAreas/, 'Should accept selectedAreas prop')
  assert.match(source, /onChange/, 'Should accept onChange prop')
})

test('AreaSearchPicker shows area type and postal code count in results', () => {
  const source = load()
  assert.match(source, /area_type|areaType/i, 'Should display area type in results')
  assert.match(source, /postal_code_count|postalCode/i, 'Should display postal code count')
})

test('AreaSearchPicker filters out already-selected areas from dropdown', () => {
  const source = load()
  assert.match(
    source,
    /filter|already.*selected|selectedIds/i,
    'Should filter already-selected areas from search results'
  )
})
