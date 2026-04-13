import React, { useState, useEffect, useRef } from 'react'
import { api } from '../api'

/**
 * AreaSearchPicker — Search-as-you-type picker for administrative areas.
 *
 * Props:
 *   country:        Country code (e.g. 'US', 'JP') to scope search
 *   selectedAreas:  Array of { id/area_id, name, postal_code_count, ... }
 *   onChange:        (areas) => void — called when selection changes
 *   typeFilter:     Area type to filter by (e.g. 'city', 'ward', 'district') — optional
 *   singleSelect:   If true, selecting an area replaces the current selection instead of appending
 *   placeholder:    Custom placeholder text for the search input
 */
export default function AreaSearchPicker({ country = '', selectedAreas = [], onChange, typeFilter = '', singleSelect = false, placeholder = '' }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const wrapperRef = useRef(null)

  const inputPlaceholder = placeholder || (singleSelect ? 'Search cities...' : 'Search cities, areas, districts...')

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Debounced search — 300ms after user stops typing
  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    const timer = setTimeout(() => {
      setLoading(true)
      const params = { q: query.trim(), limit: 10 }
      if (country) params.country = country.toUpperCase()
      if (typeFilter) params.type = typeFilter
      api.get('/local_chefs/api/areas/search/', { params })
        .then(res => {
          const items = res.data?.results || []
          // Filter out already-selected areas
          const selectedIds = new Set((selectedAreas || []).map(a => a.area_id || a.id))
          setResults(items.filter(r => !selectedIds.has(r.id)))
          setShowDropdown(true)
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(timer)
  }, [query, country, selectedAreas, typeFilter])

  const addArea = (area) => {
    const normalized = {
      area_id: area.id,
      id: area.id,
      name: area.name,
      name_local: area.name_local || '',
      area_type: area.area_type || '',
      area_type_display: area.area_type_display || area.area_type || '',
      parent_name: area.parent_name || '',
      postal_code_count: area.postal_code_count || 0,
    }
    if (singleSelect) {
      onChange([normalized])
    } else {
      onChange([...selectedAreas, normalized])
    }
    setQuery('')
    setResults([])
    setShowDropdown(false)
  }

  const removeArea = (areaId) => {
    onChange(selectedAreas.filter(a => (a.area_id || a.id) !== areaId))
  }

  return (
    <div ref={wrapperRef} style={{ position: 'relative' }}>
      {/* Search input */}
      <div style={{ position: 'relative' }}>
        <input
          className="input"
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => { if (results.length) setShowDropdown(true) }}
          placeholder={inputPlaceholder}
          autoComplete="off"
          style={{ paddingRight: '2.5rem' }}
        />
        {loading && (
          <div style={{
            position: 'absolute', right: '.75rem', top: '50%', transform: 'translateY(-50%)',
            width: '16px', height: '16px', border: '2px solid var(--border, #d0d0d0)',
            borderTopColor: 'var(--primary, #7C9070)', borderRadius: '50%',
            animation: 'spin .6s linear infinite'
          }} />
        )}
      </div>

      {/* Dropdown results */}
      {showDropdown && results.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
          background: 'var(--surface, #fff)', borderRadius: '8px', marginTop: '4px',
          boxShadow: '0 8px 24px rgba(0,0,0,.12)', maxHeight: '260px', overflowY: 'auto'
        }}>
          {results.map(area => (
            <button
              key={area.id}
              type="button"
              onClick={() => addArea(area)}
              style={{
                display: 'block', width: '100%', textAlign: 'left', padding: '.65rem .85rem',
                border: 'none', background: 'none', cursor: 'pointer',
                borderBottom: '1px solid var(--border, #eee)',
                transition: 'background .15s ease'
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--surface-2, #f5f5f5)'}
              onMouseLeave={e => e.currentTarget.style.background = 'none'}
            >
              <div style={{ fontWeight: 500, fontSize: '.9rem' }}>
                {area.name}
                {area.area_type_display && (
                  <span className="muted" style={{ fontWeight: 400, marginLeft: '.4rem', fontSize: '.8rem' }}>
                    {area.area_type_display}
                  </span>
                )}
              </div>
              <div className="muted" style={{ fontSize: '.8rem', marginTop: '.1rem' }}>
                {area.parent_name && <span>{area.parent_name} · </span>}
                {area.postal_code_count > 0
                  ? `${area.postal_code_count} postal codes`
                  : 'No postal codes yet'}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* No results message */}
      {showDropdown && query.trim().length >= 2 && results.length === 0 && !loading && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
          background: 'var(--surface, #fff)', borderRadius: '8px', marginTop: '4px',
          boxShadow: '0 8px 24px rgba(0,0,0,.12)', padding: '.85rem',
          textAlign: 'center'
        }}>
          <span className="muted">No areas found for "{query}"</span>
        </div>
      )}

      {/* Selected areas as chips */}
      {selectedAreas.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '.4rem', marginTop: '.75rem' }}>
          {selectedAreas.map(area => {
            const id = area.area_id || area.id
            return (
              <span key={id} style={{
                display: 'inline-flex', alignItems: 'center', gap: '.35rem',
                background: 'var(--primary-bg, #e8f0e4)', color: 'var(--primary, #4f6144)',
                padding: '.3rem .65rem', borderRadius: '999px', fontSize: '.85rem', fontWeight: 500
              }}>
                {area.name}
                {area.parent_name && (
                  <span style={{ opacity: .6, fontSize: '.8rem', fontWeight: 400 }}>
                    {area.parent_name}
                  </span>
                )}
                {area.postal_code_count > 0 && (
                  <span style={{ opacity: .7, fontSize: '.75rem', fontWeight: 400 }}>
                    ({area.postal_code_count})
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => removeArea(id)}
                  style={{
                    border: 'none', background: 'none', cursor: 'pointer',
                    padding: '0 0 0 .15rem', fontSize: '1rem', lineHeight: 1,
                    color: 'inherit', opacity: .6
                  }}
                  aria-label={`Remove ${area.name}`}
                >
                  &times;
                </button>
              </span>
            )
          })}
        </div>
      )}

      {/* Spinner keyframe (injected once) */}
      <style>{`@keyframes spin { to { transform: translateY(-50%) rotate(360deg) } }`}</style>
    </div>
  )
}
