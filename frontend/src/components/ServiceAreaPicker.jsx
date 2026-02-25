import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { api } from '../api'

// Lazy load Leaflet (same pattern as MapPanel)
function useLeaflet() {
  const [L, setL] = useState(null)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if (window.L) { setL(window.L); return }
        await Promise.all([
          import('leaflet/dist/leaflet.css'),
          import('leaflet')
        ]).then(([_, lib]) => { 
          if (!cancelled) { 
            window.L = lib.default || lib
            setL(window.L) 
          } 
        })
      } catch (e) {
        console.warn('Failed to load Leaflet:', e)
      }
    })()
    return () => { cancelled = true }
  }, [])
  return L
}

// Country center coordinates for initial map view
const COUNTRY_CENTERS = {
  JP: { lat: 36.2048, lng: 138.2529, zoom: 5 },
  US: { lat: 39.8283, lng: -98.5795, zoom: 4 },
  GB: { lat: 55.3781, lng: -3.4360, zoom: 5 },
  CA: { lat: 56.1304, lng: -106.3468, zoom: 4 },
  AU: { lat: -25.2744, lng: 133.7751, zoom: 4 },
  DE: { lat: 51.1657, lng: 10.4515, zoom: 6 },
  FR: { lat: 46.2276, lng: 2.2137, zoom: 6 },
  DEFAULT: { lat: 20, lng: 0, zoom: 2 }
}

/**
 * ServiceAreaPicker - Interactive map for selecting chef service areas
 * 
 * Props:
 *   country: Country code to focus on (e.g., 'JP', 'US')
 *   selectedAreas: Array of { area_id, name, postal_code_count, ... }
 *   onChange: (areas) => void - called when selection changes
 *   readOnly: Boolean - if true, just displays areas without editing
 *   maxHeight: CSS height for the component (default '500px')
 */
// Normalize country to a string code
function normalizeCountry(c) {
  if (!c) return ''
  // Handle string
  if (typeof c === 'string') return c.toUpperCase()
  // Handle django-countries object { code: 'US', name: 'United States' }
  if (typeof c === 'object') {
    return (c.code || c.country_code || c.value || '').toString().toUpperCase()
  }
  return String(c).toUpperCase()
}

export default function ServiceAreaPicker({ 
  country = '', 
  selectedAreas = [], 
  onChange,
  readOnly = false,
  maxHeight = '500px'
}) {
  const L = useLeaflet()
  const mapRef = useRef(null)
  const mapObj = useRef(null)
  const markersRef = useRef([])
  
  // Normalize country prop
  const countryCode = useMemo(() => normalizeCountry(country), [country])
  
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [topAreas, setTopAreas] = useState([])
  const [expandedArea, setExpandedArea] = useState(null)
  const [childAreas, setChildAreas] = useState([])
  const [loadingChildren, setLoadingChildren] = useState(false)
  
  // Track selected area IDs for quick lookup
  const selectedIds = useMemo(() => 
    new Set(selectedAreas.map(a => a.area_id || a.id)), 
    [selectedAreas]
  )
  
  // Initialize map
  useEffect(() => {
    if (!L || !mapRef.current) return
    if (mapObj.current) {
      mapObj.current.invalidateSize()
      return
    }
    
    const center = COUNTRY_CENTERS[countryCode] || COUNTRY_CENTERS.DEFAULT
    const map = L.map(mapRef.current).setView([center.lat, center.lng], center.zoom)
    
    // Check if dark mode is active
    const isDarkMode = document.documentElement.classList.contains('dark') ||
                       window.matchMedia('(prefers-color-scheme: dark)').matches ||
                       document.body.getAttribute('data-theme') === 'dark'
    
    // Use CartoDB Dark Matter for dark mode, standard OSM for light
    const tileUrl = isDarkMode
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    
    const attribution = isDarkMode
      ? '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
      : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    
    L.tileLayer(tileUrl, {
      maxZoom: 19,
      attribution
    }).addTo(map)
    
    mapObj.current = map
    
    return () => {
      if (mapObj.current) {
        try { mapObj.current.remove() } catch {}
        mapObj.current = null
      }
    }
  }, [L])
  
  // Update map center when country changes
  useEffect(() => {
    if (!mapObj.current || !countryCode) return
    const center = COUNTRY_CENTERS[countryCode] || COUNTRY_CENTERS.DEFAULT
    mapObj.current.setView([center.lat, center.lng], center.zoom)
  }, [countryCode])
  
  // Load top-level areas when country changes
  useEffect(() => {
    if (!countryCode) {
      setTopAreas([])
      return
    }
    
    setLoading(true)
    api.get(`/local_chefs/api/areas/country/${countryCode}/`)
      .then(res => {
        setTopAreas(res.data?.results || [])
        setError(null)
      })
      .catch(err => {
        console.warn('Failed to load areas:', err)
        setError('Failed to load areas for this country')
        setTopAreas([])
      })
      .finally(() => setLoading(false))
  }, [countryCode])
  
  // Update map markers for selected areas
  useEffect(() => {
    if (!L || !mapObj.current) return
    
    // Clear existing markers
    markersRef.current.forEach(m => mapObj.current.removeLayer(m))
    markersRef.current = []
    
    // Add markers for selected areas
    const bounds = []
    selectedAreas.forEach(area => {
      if (area.latitude && area.longitude) {
        const lat = parseFloat(area.latitude)
        const lng = parseFloat(area.longitude)
        
        const marker = L.circleMarker([lat, lng], {
          radius: 8,
          fillColor: '#7C9070',
          color: '#5A6C52',
          weight: 2,
          fillOpacity: 0.7
        }).addTo(mapObj.current)
        
        marker.bindPopup(`
          <strong>${area.name}</strong>
          ${area.name_local ? `<br/><span style="opacity:0.7">${area.name_local}</span>` : ''}
          <br/><span style="font-size:0.85em">${area.postal_code_count || 0} postal codes</span>
        `)
        
        markersRef.current.push(marker)
        bounds.push([lat, lng])
      }
    })
    
    // Fit bounds if we have markers
    if (bounds.length > 0) {
      try {
        mapObj.current.fitBounds(bounds, { padding: [30, 30], maxZoom: 10 })
      } catch {}
    }
  }, [L, selectedAreas])
  
  // Debounced search
  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults([])
      return
    }
    
    const timer = setTimeout(() => {
      setSearching(true)
      api.get('/local_chefs/api/areas/search/', {
        params: { q: searchQuery, country: countryCode || undefined, limit: 15 }
      })
        .then(res => {
          setSearchResults(res.data?.results || [])
        })
        .catch(err => {
          console.warn('Search failed:', err)
          setSearchResults([])
        })
        .finally(() => setSearching(false))
    }, 300)
    
    return () => clearTimeout(timer)
  }, [searchQuery, countryCode])
  
  // Load children when area is expanded
  const loadChildren = useCallback(async (area) => {
    if (expandedArea === area.id) {
      setExpandedArea(null)
      setChildAreas([])
      return
    }
    
    setExpandedArea(area.id)
    setLoadingChildren(true)
    
    try {
      const res = await api.get(`/local_chefs/api/areas/${area.id}/children/`)
      setChildAreas(res.data?.children || [])
    } catch (err) {
      console.warn('Failed to load children:', err)
      setChildAreas([])
    } finally {
      setLoadingChildren(false)
    }
  }, [expandedArea])
  
  // Add/remove area from selection
  const toggleArea = useCallback((area) => {
    if (readOnly || !onChange) return
    
    const areaId = area.id || area.area_id
    const isSelected = selectedIds.has(areaId)
    
    if (isSelected) {
      onChange(selectedAreas.filter(a => (a.area_id || a.id) !== areaId))
    } else {
      onChange([...selectedAreas, {
        area_id: areaId,
        id: areaId,
        name: area.name,
        name_local: area.name_local || '',
        area_type: area.area_type,
        country: area.country,
        parent_name: area.parent_name || '',
        postal_code_count: area.postal_code_count || 0,
        latitude: area.latitude,
        longitude: area.longitude
      }])
    }
  }, [readOnly, onChange, selectedAreas, selectedIds])
  
  // Pan map to area
  const panToArea = useCallback((area) => {
    if (!mapObj.current || !area.latitude || !area.longitude) return
    mapObj.current.setView(
      [parseFloat(area.latitude), parseFloat(area.longitude)], 
      area.area_type === 'city' || area.area_type === 'ward' ? 11 : 8
    )
  }, [])
  
  // Remove area from selection
  const removeArea = useCallback((areaId) => {
    if (readOnly || !onChange) return
    onChange(selectedAreas.filter(a => (a.area_id || a.id) !== areaId))
  }, [readOnly, onChange, selectedAreas])
  
  const renderAreaItem = (area, isChild = false) => {
    const areaId = area.id || area.area_id
    const isSelected = selectedIds.has(areaId)
    const hasChildren = !isChild && area.area_type !== 'ward' && area.area_type !== 'district'
    
    return (
      <div 
        key={areaId} 
        className={`area-item ${isSelected ? 'selected' : ''} ${isChild ? 'child' : ''}`}
        style={{
          padding: '0.5rem 0.75rem',
          marginBottom: '0.25rem',
          borderRadius: '6px',
          background: isSelected 
            ? 'var(--accent-green-soft, rgba(124, 144, 112, 0.15))' 
            : 'transparent',
          border: isSelected
            ? '1px solid var(--primary)'
            : '1px solid var(--border)',
          marginLeft: isChild ? '1rem' : 0,
          cursor: readOnly ? 'default' : 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          transition: 'all 0.15s ease'
        }}
      >
        {!readOnly && (
          <input 
            type="checkbox" 
            checked={isSelected}
            onChange={() => toggleArea(area)}
            style={{ margin: 0, cursor: 'pointer' }}
          />
        )}
        
        <div style={{ flex: 1, minWidth: 0 }} onClick={() => !readOnly && toggleArea(area)}>
          <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>{area.name}</span>
            {area.name_local && area.name_local !== area.name && (
              <span style={{ opacity: 0.6, fontSize: '0.9em' }}>{area.name_local}</span>
            )}
          </div>
          <div style={{ fontSize: '0.8em', opacity: 0.7, display: 'flex', gap: '0.5rem' }}>
            <span>{area.postal_code_count || 0} postal codes</span>
            {area.parent_name && <span>• {area.parent_name}</span>}
            <span>• {area.area_type_display || area.area_type}</span>
          </div>
        </div>
        
        <div style={{ display: 'flex', gap: '0.25rem' }}>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); panToArea(area) }}
            title="Show on map"
            style={{
              background: 'var(--surface-3)',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              padding: '0.25rem 0.4rem',
              opacity: 0.8,
              fontSize: '0.9rem'
            }}
          >
            🗺️
          </button>
          
          {hasChildren && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); loadChildren(area) }}
              title={expandedArea === areaId ? 'Collapse' : 'Show sub-areas'}
              style={{
                background: 'var(--surface-3)',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                padding: '0.25rem 0.4rem',
                opacity: 0.8,
                fontSize: '0.85rem',
                transform: expandedArea === areaId ? 'rotate(90deg)' : 'none',
                transition: 'transform 0.15s'
              }}
            >
              ▶
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="service-area-picker" style={{ maxHeight, display: 'flex', flexDirection: 'column' }}>
      {/* Search bar */}
      {!readOnly && (
        <div style={{ marginBottom: '0.75rem', position: 'relative' }}>
          <input
            type="text"
            className="input"
            placeholder="Search cities, wards, districts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ width: '100%', paddingRight: '2rem' }}
          />
          {searching && (
            <span style={{ position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)', opacity: 0.5 }}>
              ⏳
            </span>
          )}
          
          {/* Search results dropdown */}
          {searchResults.length > 0 && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              boxShadow: 'var(--shadow-md)',
              zIndex: 1000,
              maxHeight: '300px',
              overflowY: 'auto'
            }}>
              {searchResults.map(area => (
                <div
                  key={area.id}
                  onClick={() => {
                    toggleArea(area)
                    setSearchQuery('')
                    setSearchResults([])
                  }}
                  style={{
                    padding: '0.5rem 0.75rem',
                    cursor: 'pointer',
                    borderBottom: '1px solid var(--border)',
                    background: selectedIds.has(area.id) ? 'rgba(124, 144, 112, 0.15)' : 'transparent'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = selectedIds.has(area.id) ? 'rgba(124, 144, 112, 0.2)' : 'var(--surface-2)'}
                  onMouseLeave={(e) => e.currentTarget.style.background = selectedIds.has(area.id) ? 'rgba(124, 144, 112, 0.15)' : 'transparent'}
                >
                  <div style={{ fontWeight: 500, display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    {selectedIds.has(area.id) && <span>✓</span>}
                    <span>{area.name}</span>
                    {area.name_local && area.name_local !== area.name && (
                      <span style={{ opacity: 0.6, fontSize: '0.9em' }}>{area.name_local}</span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.8em', opacity: 0.7 }}>
                    {area.postal_code_count} codes • {area.parent_name || area.country} • {area.area_type_display || area.area_type}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      
      {error && (
        <div style={{ padding: '0.5rem', background: '#fee', borderRadius: '4px', marginBottom: '0.5rem', color: '#c00' }}>
          {error}
        </div>
      )}
      
      <div style={{ display: 'flex', gap: '0.75rem', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* Left panel: Area browser */}
        <div style={{ 
          width: '45%', 
          overflowY: 'auto', 
          paddingRight: '0.5rem',
          borderRight: '1px solid var(--border)'
        }}>
          {/* Selected areas section */}
          {selectedAreas.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <div style={{ 
                fontWeight: 600, 
                fontSize: '0.85em', 
                textTransform: 'uppercase', 
                letterSpacing: '0.5px',
                opacity: 0.7,
                marginBottom: '0.5rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}>
                <span>Selected Areas</span>
                <span style={{
                  background: 'var(--primary)',
                  color: '#fff',
                  borderRadius: '10px',
                  padding: '0 0.5rem',
                  fontSize: '0.9em'
                }}>
                  {selectedAreas.length}
                </span>
              </div>
              
              {selectedAreas.map(area => (
                <div 
                  key={area.area_id || area.id}
                  style={{
                    padding: '0.5rem 0.75rem',
                    marginBottom: '0.25rem',
                    borderRadius: '6px',
                    background: 'rgba(124, 144, 112, 0.15)',
                    border: '1px solid var(--primary)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem'
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 500 }}>
                      {area.name}
                      {area.name_local && area.name_local !== area.name && (
                        <span style={{ opacity: 0.6, marginLeft: '0.5rem', fontSize: '0.9em' }}>{area.name_local}</span>
                      )}
                    </div>
                    <div style={{ fontSize: '0.8em', opacity: 0.7 }}>
                      {area.postal_code_count || 0} postal codes
                      {area.parent_name && ` • ${area.parent_name}`}
                    </div>
                  </div>
                  
                  <button
                    type="button"
                    onClick={() => panToArea(area)}
                    title="Show on map"
                    style={{
                      background: 'var(--surface-3)',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      padding: '0.25rem 0.4rem',
                      opacity: 0.8
                    }}
                  >
                    🗺️
                  </button>
                  
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => removeArea(area.area_id || area.id)}
                      title="Remove"
                      style={{ 
                        background: 'rgba(200,50,50,0.2)', 
                        border: 'none', 
                        borderRadius: '4px',
                        cursor: 'pointer',
                        color: '#ff6b6b',
                        fontWeight: 'bold',
                        fontSize: '1.1em',
                        padding: '0.1rem 0.4rem'
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          
          {/* Browse areas */}
          {!readOnly && (
            <div>
              <div style={{ 
                fontWeight: 600, 
                fontSize: '0.85em', 
                textTransform: 'uppercase', 
                letterSpacing: '0.5px',
                opacity: 0.7,
                marginBottom: '0.5rem'
              }}>
                {countryCode ? `Browse ${countryCode} Areas` : 'Select a country first'}
              </div>
              
              {loading ? (
                <div style={{ padding: '1rem', textAlign: 'center', opacity: 0.6 }}>Loading...</div>
              ) : topAreas.length === 0 ? (
                <div style={{ padding: '1rem', textAlign: 'center', opacity: 0.6 }}>
                  {countryCode ? 'No areas found. Import data using the management command.' : 'Select a country to browse areas'}
                </div>
              ) : (
                topAreas.map(area => (
                  <React.Fragment key={area.id}>
                    {renderAreaItem(area)}
                    {expandedArea === area.id && (
                      loadingChildren ? (
                        <div style={{ marginLeft: '1rem', padding: '0.5rem', opacity: 0.6 }}>Loading...</div>
                      ) : childAreas.length > 0 ? (
                        childAreas.map(child => renderAreaItem(child, true))
                      ) : (
                        <div style={{ marginLeft: '1rem', padding: '0.5rem', opacity: 0.6, fontSize: '0.9em' }}>
                          No sub-areas found
                        </div>
                      )
                    )}
                  </React.Fragment>
                ))
              )}
            </div>
          )}
        </div>
        
        {/* Right panel: Map */}
        <div style={{ flex: 1, minHeight: '300px', position: 'relative' }}>
          <div 
            ref={mapRef} 
            style={{ 
              height: '100%', 
              width: '100%', 
              borderRadius: '8px',
              overflow: 'hidden'
            }} 
          />
          
          {!L && (
            <div style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'var(--surface-2)',
              borderRadius: '8px'
            }}>
              Loading map...
            </div>
          )}
        </div>
      </div>
      
      {/* Summary */}
      <div style={{ 
        marginTop: '0.75rem', 
        paddingTop: '0.75rem', 
        borderTop: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '0.9em',
        opacity: 0.7
      }}>
        <span>
          {selectedAreas.length} {selectedAreas.length === 1 ? 'area' : 'areas'} selected
        </span>
        <span>
          ~{selectedAreas.reduce((sum, a) => sum + (a.postal_code_count || 0), 0)} postal codes
        </span>
      </div>
    </div>
  )
}

