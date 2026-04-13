import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, join } from 'node:path'

const SRC_DIR = resolve('frontend/src')

function getAllJsxFiles(dir) {
  const results = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      results.push(...getAllJsxFiles(fullPath))
    } else if (entry.name.endsWith('.jsx')) {
      results.push(fullPath)
    }
  }
  return results
}

test('No JSX files contain "Community Chef" — should use "Personal Chef"', () => {
  const files = getAllJsxFiles(SRC_DIR)
  const violations = []

  for (const filePath of files) {
    const content = readFileSync(filePath, 'utf8')
    if (content.includes('Community Chef')) {
      violations.push(filePath.replace(SRC_DIR + '/', ''))
    }
  }

  assert.equal(
    violations.length,
    0,
    `Found "Community Chef" in: ${violations.join(', ')}. Should be "Personal Chef" instead.`
  )
})

test('Profile.jsx uses "Personal Chef" language', () => {
  const content = readFileSync(resolve(SRC_DIR, 'pages/Profile.jsx'), 'utf8')
  assert.match(
    content,
    /Personal Chef/,
    'Profile.jsx should contain "Personal Chef"'
  )
})

test('Home.jsx uses "Personal Chef" language in chef application modal', () => {
  const content = readFileSync(resolve(SRC_DIR, 'pages/Home.jsx'), 'utf8')
  assert.match(
    content,
    /Personal Chef/,
    'Home.jsx should contain "Personal Chef"'
  )
})
