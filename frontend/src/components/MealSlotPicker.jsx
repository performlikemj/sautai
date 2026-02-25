/**
 * MealSlotPicker Component
 * 
 * Modal for selecting what meal to assign to a slot.
 * Options:
 * 1. Pick from chef's composed meals (multi-dish)
 * 2. Pick from chef's saved single items
 * 3. Generate AI suggestion for this slot
 * 4. Compose meal on-the-fly from dishes
 * 5. Enter custom meal name
 */

import React, { useState, useEffect } from 'react'
import { getChefDishes, getChefComposedMeals, startMealGeneration } from '../api/chefMealPlanClient.js'
import { useSousChefNotifications } from '../contexts/SousChefNotificationContext.jsx'

// Helper to format meal type for display
const MEAL_TYPE_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' }
const formatMealType = (type) => MEAL_TYPE_LABELS[type] || type

export default function MealSlotPicker({
  isOpen,
  onClose,
  slot,
  existingItem,
  onAssign,
  onRemove,
  planId,
  planTitle = 'Meal Plan',
  clientName = 'Client',
  chefDishes = [], // All chef dishes for compose mode
  readOnly = false // When true, only allow viewing (no edit actions)
}) {
  // Notification context for global job tracking
  let notifications = null
  try {
    notifications = useSousChefNotifications()
  } catch (e) {
    // Context not available
  }
  
  const [tab, setTab] = useState('meals')
  const [mode, setMode] = useState('pick') // 'view' or 'pick'
  const [composedMeals, setComposedMeals] = useState([])
  const [singleItems, setSingleItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [generating, setGenerating] = useState(false)
  const [aiSuggestion, setAiSuggestion] = useState(null)
  
  // Compose mode state
  const [composeSelectedDishes, setComposeSelectedDishes] = useState([])
  const [composeName, setComposeName] = useState('')
  const [composeDescription, setComposeDescription] = useState('')
  const [availableDishes, setAvailableDishes] = useState([])
  
  const [customForm, setCustomForm] = useState({
    name: '',
    description: '',
    servings: 1
  })

  // Load data on open
  useEffect(() => {
    if (isOpen && slot) {
      // Set mode based on whether slot has existing item
      setMode(existingItem ? 'view' : 'pick')
      loadMeals()
      loadAvailableDishes()
      setAiSuggestion(null)
      setCustomForm({ name: '', description: '', servings: 1 })
      setComposeSelectedDishes([])
      setComposeName('')
      setComposeDescription('')
    }
  }, [isOpen, slot, existingItem])

  const loadMeals = async () => {
    setLoading(true)
    try {
      // Load composed meals (multi-dish) and single items in parallel
      const [composedRes, singleRes] = await Promise.all([
        getChefComposedMeals({ 
          meal_type: slot?.mealType,
          search: search || undefined 
        }),
        getChefDishes({ 
          meal_type: slot?.mealType,
          search: search || undefined,
          include_dishes: true
        })
      ])
      
      setComposedMeals(composedRes?.dishes?.filter(m => m.is_composed) || [])
      setSingleItems(singleRes?.dishes?.filter(m => !m.is_composed) || [])
    } catch (err) {
      console.error('Failed to load meals:', err)
    } finally {
      setLoading(false)
    }
  }

  const loadAvailableDishes = async () => {
    try {
      // Get all meals (which represent dishes in the kitchen)
      const data = await getChefDishes({ limit: 100, include_dishes: true })
      setAvailableDishes(data?.dishes || [])
    } catch (err) {
      console.error('Failed to load available dishes:', err)
    }
  }

  // Debounced search
  useEffect(() => {
    if (!isOpen || tab === 'compose') return
    const timer = setTimeout(() => {
      loadMeals()
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const handleSelectMeal = (meal) => {
    onAssign({
      meal_id: meal.id,
      custom_name: '',
      custom_description: '',
      servings: customForm.servings || 1,
      is_composed: meal.is_composed,
      dishes: meal.dishes // Pass dish info for display
    })
  }

  const [aiError, setAiError] = useState(null)
  const [aiStatus, setAiStatus] = useState('')
  
  const handleGenerateAI = async () => {
    if (!planId || !slot) return
    
    setGenerating(true)
    setAiSuggestion(null)
    setAiError(null)
    setAiStatus('Starting generation...')
    
    const dayName = new Date(slot.date).toLocaleDateString('en-US', { weekday: 'long' })
    
    try {
      // Start async generation
      const startData = await startMealGeneration(planId, {
        mode: 'single_slot',
        day: dayName,
        meal_type: slot.mealType
      })
      
      if (!startData?.job_id) {
        throw new Error('Failed to start generation')
      }
      
      // Use global tracking so generation continues even if modal closes
      if (notifications?.trackJob) {
        notifications.trackJob({
          jobId: startData.job_id,
          planId,
          planTitle,
          clientName,
          mode: 'single_slot',
          slot: { day: dayName, meal_type: slot.mealType },
          onComplete: (result) => {
            // If this picker is still open, update local state
            if (result?.suggestions?.length > 0) {
              setAiSuggestion(result.suggestions[0])
              setGenerating(false)
              setAiStatus('')
            }
          }
        })
        
        setAiStatus('Generating... Sous Chef will notify you when ready!')
      } else {
        // Fallback without global tracking
        setAiError('Background tracking not available')
        setGenerating(false)
      }
    } catch (err) {
      console.error('AI generation failed:', err)
      setAiError(err.message || 'Generation failed. Please try again.')
      setGenerating(false)
      setAiStatus('')
    }
  }

  const handleAcceptAI = () => {
    if (!aiSuggestion) return
    onAssign({
      meal_id: null,
      custom_name: aiSuggestion.name,
      custom_description: aiSuggestion.description,
      servings: customForm.servings || 1
    })
  }

  // Compose mode handlers
  const handleToggleDish = (dish) => {
    setComposeSelectedDishes(prev => {
      const exists = prev.find(d => d.id === dish.id)
      if (exists) {
        return prev.filter(d => d.id !== dish.id)
      }
      return [...prev, dish]
    })
  }

  const handleComposeSubmit = (e) => {
    e.preventDefault()
    if (composeSelectedDishes.length === 0) return
    
    // Create a composed meal on-the-fly
    const composedName = composeName.trim() || composeSelectedDishes.map(d => d.name).join(' + ')
    
    onAssign({
      meal_id: null,
      custom_name: composedName,
      custom_description: composeDescription || composeSelectedDishes.map(d => d.name).join(', '),
      servings: customForm.servings || 1,
      composed_dishes: composeSelectedDishes.map(d => ({
        id: d.id,
        name: d.name
      }))
    })
  }

  const handleCustomSubmit = (e) => {
    e.preventDefault()
    if (!customForm.name.trim()) return
    
    onAssign({
      meal_id: null,
      custom_name: customForm.name,
      custom_description: customForm.description,
      servings: customForm.servings || 1
    })
  }

  if (!isOpen || !slot) return null

  const dayName = new Date(slot.date).toLocaleDateString('en-US', { weekday: 'long' })
  const dateDisplay = new Date(slot.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  return (
    <>
      <div className="msp-backdrop" onClick={onClose} />
      <div className="msp-modal">
        <header className="msp-header">
          <button className="msp-back-btn" onClick={onClose} aria-label="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
          </button>
          <div className="msp-header-text">
            <h3>{mode === 'view' ? 'View Meal' : (existingItem ? 'Replace Meal' : 'Add Meal')}</h3>
            <span className="msp-slot-info">{dayName} {dateDisplay} • {formatMealType(slot.mealType)}</span>
          </div>
        </header>

        {/* View Mode - Show existing meal details */}
        {mode === 'view' && existingItem && (
          <div className="msp-view-mode">
            <div className="msp-existing-meal">
              <h4>{existingItem.name || existingItem.custom_name || 'Unnamed Meal'}</h4>
              {(existingItem.description || existingItem.custom_description) && (
                <p className="msp-existing-desc">{existingItem.description || existingItem.custom_description}</p>
              )}
              {existingItem.dishes?.length > 0 && (
                <div className="msp-dishes-view">
                  <span className="msp-dishes-label">Dishes:</span>
                  {existingItem.dishes.map((d, i) => (
                    <span key={i} className="msp-dish-chip">{d.name}</span>
                  ))}
                </div>
              )}
              {existingItem.servings && existingItem.servings > 1 && (
                <p className="msp-servings-info">Servings: {existingItem.servings}</p>
              )}
              {existingItem.notes && (
                <p className="msp-notes-info">Notes: {existingItem.notes}</p>
              )}
            </div>
            <div className="msp-view-actions">
              {readOnly ? (
                <button className="msp-btn msp-btn-outline msp-btn-full" onClick={onClose}>
                  Close
                </button>
              ) : (
                <>
                  <button className="msp-btn msp-btn-primary" onClick={() => setMode('pick')}>
                    Replace Meal
                  </button>
                  <button className="msp-btn msp-btn-danger-outline" onClick={onRemove}>
                    Remove from Plan
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {/* Tabs - Only shown in pick mode */}
        {mode === 'pick' && (
        <div className="msp-tabs">
          <button
            className={`msp-tab ${tab === 'meals' ? 'active' : ''}`}
            onClick={() => setTab('meals')}
          >
            My Meals
          </button>
          <button
            className={`msp-tab ${tab === 'compose' ? 'active' : ''}`}
            onClick={() => setTab('compose')}
          >
            Compose
          </button>
          <button
            className={`msp-tab ${tab === 'ai' ? 'active' : ''}`}
            onClick={() => setTab('ai')}
          >
            AI
          </button>
          <button
            className={`msp-tab ${tab === 'custom' ? 'active' : ''}`}
            onClick={() => setTab('custom')}
          >
            Quick Add
          </button>
        </div>
        )}

        {/* Content - Only shown in pick mode */}
        {mode === 'pick' && (
        <div className="msp-content">
          {tab === 'meals' && (
            <div className="msp-meals">
              <div className="msp-search">
                <input 
                  type="text"
                  placeholder="Search your meals..."
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
              
              {loading ? (
                <div className="msp-loading">Loading meals...</div>
              ) : (composedMeals.length === 0 && singleItems.length === 0) ? (
                <div className="msp-empty">
                  <p>No meals found{search ? ' matching your search' : ''}.</p>
                  <p className="msp-hint">Create meals in Kitchen, or use Compose/AI tabs.</p>
                </div>
              ) : (
                <div className="msp-meals-sections">
                  {/* Composed Meals Section */}
                  {composedMeals.length > 0 && (
                    <div className="msp-section">
                      <h4 className="msp-section-title">
                        🍽️ Composed Meals
                        <span className="msp-section-badge">{composedMeals.length}</span>
                      </h4>
                      <div className="msp-dishes-list">
                        {composedMeals.map(meal => (
                          <button 
                            key={meal.id}
                            className="msp-dish-card msp-composed"
                            onClick={() => handleSelectMeal(meal)}
                          >
                            <div className="msp-dish-info">
                              <span className="msp-dish-name">{meal.name}</span>
                              {meal.dishes?.length > 0 && (
                                <span className="msp-dish-components">
                                  {meal.dishes.map(d => d.name).join(' • ')}
                                </span>
                              )}
                              {meal.description && (
                                <span className="msp-dish-desc">{meal.description}</span>
                              )}
                            </div>
                            <div className="msp-dish-meta">
                              <span className="msp-dish-count">{meal.dish_count} dishes</span>
                              <span className="msp-dish-arrow">→</span>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Single Items Section */}
                  {singleItems.length > 0 && (
                    <div className="msp-section">
                      <h4 className="msp-section-title">
                        🥘 Single Items
                        <span className="msp-section-badge">{singleItems.length}</span>
                      </h4>
                      <div className="msp-dishes-list">
                        {singleItems.map(item => (
                          <button 
                            key={item.id}
                            className="msp-dish-card"
                            onClick={() => handleSelectMeal(item)}
                          >
                            <div className="msp-dish-info">
                              <span className="msp-dish-name">{item.name}</span>
                              {item.description && (
                                <span className="msp-dish-desc">{item.description}</span>
                              )}
                              {item.dietary_preferences?.length > 0 && (
                                <div className="msp-dish-tags">
                                  {item.dietary_preferences.slice(0, 3).map((tag, i) => (
                                    <span key={i} className="msp-tag">{tag}</span>
                                  ))}
                                </div>
                              )}
                            </div>
                            <span className="msp-dish-arrow">→</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {tab === 'compose' && (
            <div className="msp-compose">
              <p className="msp-compose-hint">
                Build a meal by selecting multiple dishes from your menu.
              </p>
              
              {/* Selected dishes */}
              {composeSelectedDishes.length > 0 && (
                <div className="msp-compose-selected">
                  <label>Selected dishes ({composeSelectedDishes.length}):</label>
                  <div className="msp-compose-chips">
                    {composeSelectedDishes.map(dish => (
                      <span key={dish.id} className="msp-compose-chip">
                        {dish.name}
                        <button onClick={() => handleToggleDish(dish)}>×</button>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Available dishes to add */}
              <div className="msp-compose-available">
                <label>Add dishes to meal:</label>
                <div className="msp-compose-grid">
                  {availableDishes.map(dish => {
                    const isSelected = composeSelectedDishes.some(d => d.id === dish.id)
                    return (
                      <button
                        key={dish.id}
                        className={`msp-compose-option ${isSelected ? 'selected' : ''}`}
                        onClick={() => handleToggleDish(dish)}
                      >
                        <span className="msp-compose-check">{isSelected ? '✓' : '+'}</span>
                        <span>{dish.name}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Meal name (optional) - show form when 1+ dishes selected */}
              {composeSelectedDishes.length >= 1 && (
                <form onSubmit={handleComposeSubmit} className="msp-compose-form">
                  <div className="msp-form-row">
                    <label>Meal Name (optional)</label>
                    <input
                      type="text"
                      placeholder={composeSelectedDishes.map(d => d.name).join(' + ')}
                      value={composeName}
                      onChange={e => setComposeName(e.target.value)}
                    />
                  </div>
                  <button
                    type="submit"
                    className="msp-btn msp-btn-primary msp-btn-full"
                  >
                    Add to Plan
                  </button>
                </form>
              )}
            </div>
          )}

          {tab === 'ai' && (
            <div className="msp-ai">
              {aiError && (
                <div className="msp-ai-error">
                  ⚠️ {aiError}
                </div>
              )}
              {!aiSuggestion ? (
                <div className="msp-ai-prompt">
                  <div className="msp-ai-icon">✨</div>
                  <p>Generate an AI meal suggestion tailored to this family's dietary needs.</p>
                  {aiStatus && (
                    <div className="msp-ai-status">
                      {aiStatus}
                    </div>
                  )}
                  <button 
                    className="msp-btn msp-btn-ai"
                    onClick={handleGenerateAI}
                    disabled={generating}
                  >
                    {generating ? '🔄 Generating...' : 'Generate Suggestion'}
                  </button>
                  {generating && (
                    <p className="msp-ai-hint">
                      You can close this and Sous Chef will notify you when done!
                    </p>
                  )}
                </div>
              ) : (
                <div className="msp-ai-result">
                  <div className="msp-suggestion-card">
                    <h4>{aiSuggestion.name}</h4>
                    <p className="msp-suggestion-desc">{aiSuggestion.description}</p>
                    {aiSuggestion.dietary_tags?.length > 0 && (
                      <div className="msp-dish-tags">
                        {aiSuggestion.dietary_tags.map((tag, i) => (
                          <span key={i} className="msp-tag">{tag}</span>
                        ))}
                      </div>
                    )}
                    {aiSuggestion.household_notes && (
                      <p className="msp-household-note">💡 {aiSuggestion.household_notes}</p>
                    )}
                  </div>
                  <div className="msp-ai-actions">
                    <button 
                      className="msp-btn msp-btn-primary"
                      onClick={handleAcceptAI}
                    >
                      Use This Meal
                    </button>
                    <button 
                      className="msp-btn msp-btn-outline"
                      onClick={handleGenerateAI}
                      disabled={generating}
                    >
                      {generating ? 'Generating...' : 'Try Another'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'custom' && (
            <div className="msp-custom">
              <form onSubmit={handleCustomSubmit}>
                <div className="msp-form-row">
                  <label>Meal Name *</label>
                  <input 
                    type="text"
                    placeholder="e.g., Grilled Salmon with Vegetables"
                    value={customForm.name}
                    onChange={e => setCustomForm(f => ({ ...f, name: e.target.value }))}
                    required
                  />
                </div>
                <div className="msp-form-row">
                  <label>Description</label>
                  <textarea 
                    rows={3}
                    placeholder="Brief description..."
                    value={customForm.description}
                    onChange={e => setCustomForm(f => ({ ...f, description: e.target.value }))}
                  />
                </div>
                <div className="msp-form-row">
                  <label>Servings</label>
                  <input 
                    type="number"
                    min={1}
                    value={customForm.servings}
                    onChange={e => setCustomForm(f => ({ ...f, servings: parseInt(e.target.value) || 1 }))}
                  />
                </div>
                <button 
                  type="submit" 
                  className="msp-btn msp-btn-primary msp-btn-full"
                  disabled={!customForm.name.trim()}
                >
                  Add to Plan
                </button>
              </form>
            </div>
          )}
        </div>
        )}
      </div>

      <style>{`
        .msp-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.5);
          z-index: 2000;
        }

        /* Slideout panel - slides from right */
        .msp-modal {
          position: fixed;
          top: 0;
          right: 0;
          bottom: 0;
          width: 100%;
          z-index: 2001;
          background: var(--surface, #fff);
          display: flex;
          flex-direction: column;
          animation: mspSlideIn 0.25s ease;
          box-shadow: -4px 0 24px rgba(27,58,45,0.15);
        }

        @keyframes mspSlideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }

        /* Tablet: 85% width, max 600px */
        @media (min-width: 640px) {
          .msp-modal {
            width: 85%;
            max-width: 600px;
            border-radius: 20px 0 0 20px;
          }
        }

        /* Desktop: 50% width, max 560px */
        @media (min-width: 1024px) {
          .msp-modal {
            width: 50%;
            max-width: 560px;
          }
        }

        .msp-header {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          padding: 1rem 1.25rem;
          border-bottom: 1px solid var(--border, #e5e7eb);
          background: var(--surface, #fff);
          flex-shrink: 0;
        }

        .msp-back-btn {
          width: 40px;
          height: 40px;
          border: none;
          background: var(--surface-2, #f3f4f6);
          border-radius: 10px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--text, #333);
          transition: background 0.15s;
          flex-shrink: 0;
        }

        .msp-back-btn:hover {
          background: var(--border, #e5e7eb);
        }

        .msp-header-text {
          display: flex;
          flex-direction: column;
          gap: 0.15rem;
        }

        .msp-header-text h3 {
          margin: 0;
          font-size: 1.15rem;
          font-weight: 600;
        }

        .msp-slot-info {
          font-size: 0.9rem;
          color: var(--muted, #666);
        }

        .msp-tabs {
          display: flex;
          border-bottom: 1px solid var(--border, #e5e7eb);
          flex-shrink: 0;
          padding: 0 0.5rem;
        }

        .msp-tab {
          flex: 1;
          padding: 1rem 0.75rem;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          font-size: 0.9rem;
          font-weight: 500;
          color: var(--muted, #666);
          cursor: pointer;
          white-space: nowrap;
          transition: all 0.15s;
        }

        .msp-tab:hover:not(.active) {
          background: var(--surface-2, #f9fafb);
          color: var(--text, #333);
        }

        .msp-tab.active {
          color: var(--primary, #7C9070);
          border-bottom-color: var(--primary, #7C9070);
        }

        @media (min-width: 640px) {
          .msp-tab {
            font-size: 0.95rem;
            padding: 1rem 1rem;
          }
        }

        .msp-content {
          flex: 1;
          overflow-y: auto;
          padding: 1.25rem;
          padding-bottom: max(1.25rem, env(safe-area-inset-bottom));
          -webkit-overflow-scrolling: touch;
        }

        @media (min-width: 640px) {
          .msp-content {
            padding: 1.5rem;
            padding-bottom: max(1.5rem, env(safe-area-inset-bottom));
          }
        }

        /* Meals Tab */
        .msp-search {
          margin-bottom: 1.25rem;
        }

        .msp-search input {
          width: 100%;
          padding: 0.85rem 1rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 10px;
          background: var(--surface, #fff);
          color: var(--text, #333);
          font-size: 0.95rem;
          caret-color: var(--primary, #7C9070);
          transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
        }

        .msp-search input::placeholder {
          color: var(--muted, #666);
        }

        .msp-search input:focus {
          outline: none;
          border-color: color-mix(in oklab, var(--primary, #7C9070) 55%, var(--border, #ddd));
          box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.16);
          background: var(--surface, #fff);
        }

        .msp-loading,
        .msp-empty {
          text-align: center;
          padding: 2rem 1rem;
          color: var(--muted, #666);
        }

        .msp-hint {
          font-size: 0.85rem;
          opacity: 0.8;
        }

        .msp-meals-sections {
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
        }

        .msp-section {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .msp-section-title {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.95rem;
          font-weight: 600;
          margin: 0;
          padding-left: 0.25rem;
          color: var(--text, #333);
        }

        .msp-section-badge {
          background: var(--surface-2, #f3f4f6);
          color: var(--muted, #666);
          font-size: 0.75rem;
          font-weight: 500;
          padding: 0.15rem 0.6rem;
          border-radius: 99px;
        }

        .msp-dishes-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .msp-dish-card {
          display: flex;
          align-items: center;
          justify-content: space-between;
          width: 100%;
          padding: 1rem 1.25rem;
          background: var(--surface, #fff);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 16px;
          cursor: pointer;
          text-align: left;
          transition: all 0.15s;
          gap: 0.75rem;
        }

        .msp-dish-card:hover {
          border-color: var(--primary, #7C9070);
          background: var(--surface-2, #f9fafb);
        }

        .msp-dish-card.msp-composed {
          border-left: 3px solid var(--primary, #7C9070);
        }

        .msp-dish-components {
          font-size: 0.8rem;
          color: var(--primary-700, #4a9d4a);
          font-weight: 500;
        }

        .msp-dish-meta {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }

        .msp-dish-count {
          font-size: 0.75rem;
          color: var(--muted, #888);
          background: var(--surface-2, #f3f4f6);
          padding: 0.2rem 0.5rem;
          border-radius: 4px;
        }

        .msp-dish-info {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
          flex: 1;
          min-width: 0;
        }

        .msp-dish-name {
          font-weight: 500;
          color: var(--text, #333);
        }

        .msp-dish-desc {
          font-size: 0.8rem;
          color: var(--muted, #666);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .msp-dish-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 0.25rem;
          margin-top: 0.25rem;
        }

        .msp-tag {
          font-size: 0.7rem;
          padding: 0.15rem 0.4rem;
          background: var(--surface-2, #f3f4f6);
          border-radius: 4px;
          color: var(--muted, #666);
        }

        .msp-dish-arrow {
          font-size: 1.25rem;
          color: var(--muted, #ccc);
          margin-left: 0.5rem;
        }

        /* AI Tab */
        .msp-ai-error {
          background: color-mix(in oklab, var(--surface, #fff) 90%, #dc2626 10%);
          border: 1px solid color-mix(in oklab, var(--border, #e5e7eb) 50%, #dc2626 50%);
          color: color-mix(in oklab, #dc2626 75%, var(--text, #333) 25%);
          padding: 0.75rem 1rem;
          border-radius: 8px;
          margin-bottom: 1rem;
          font-size: 0.9rem;
        }

        .msp-ai-prompt {
          text-align: center;
          padding: 3rem 1.5rem;
        }

        .msp-ai-icon {
          font-size: 4rem;
          margin-bottom: 1.5rem;
        }

        .msp-ai-prompt p {
          color: var(--muted, #666);
          margin-bottom: 1.75rem;
          font-size: 1rem;
          line-height: 1.5;
        }

        .msp-ai-status {
          font-size: 0.9rem;
          color: var(--primary, #7C9070);
          margin-bottom: 1rem;
          padding: 0.5rem 1rem;
          background: rgba(124, 144, 112, 0.1);
          border-radius: 8px;
        }

        .msp-ai-hint {
          font-size: 0.85rem;
          color: var(--muted, #888);
          margin-top: 0.75rem;
          font-style: italic;
        }

        .msp-ai-result {
          display: flex;
          flex-direction: column;
          gap: 1.25rem;
        }

        .msp-suggestion-card {
          padding: 1.25rem 1.5rem;
          background: var(--surface-2, #f9fafb);
          border-radius: 16px;
        }

        .msp-suggestion-card h4 {
          margin: 0 0 0.75rem 0;
          font-size: 1.1rem;
        }

        .msp-suggestion-desc {
          font-size: 0.95rem;
          color: var(--muted, #666);
          margin: 0 0 0.75rem 0;
          line-height: 1.5;
        }

        .msp-household-note {
          font-size: 0.85rem;
          color: var(--muted, #666);
          font-style: italic;
          margin: 0.5rem 0 0 0;
        }

        .msp-ai-actions {
          display: flex;
          gap: 0.5rem;
        }

        .msp-ai-actions .msp-btn {
          flex: 1;
        }

        /* Compose Tab */
        .msp-compose {
          display: flex;
          flex-direction: column;
          gap: 1.25rem;
          background: var(--surface, #fff);
          border-radius: 16px;
        }

        .msp-compose-hint {
          text-align: center;
          color: var(--muted, #666);
          font-size: 0.95rem;
          margin: 0;
          padding: 0.5rem;
        }

        .msp-compose-selected {
          background: var(--primary-50, #f0fdf4);
          border: 1px solid var(--primary-200, #bbf7d0);
          border-radius: 10px;
          padding: 0.75rem;
        }

        .msp-compose-selected label {
          display: block;
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--primary-700, #4a9d4a);
          margin-bottom: 0.5rem;
        }

        .msp-compose-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }

        .msp-compose-chip {
          display: inline-flex;
          align-items: center;
          gap: 0.35rem;
          background: var(--surface, #fff);
          border: 1px solid var(--primary, #7C9070);
          color: var(--primary-700, #4a9d4a);
          padding: 0.3rem 0.6rem;
          border-radius: 99px;
          font-size: 0.8rem;
          font-weight: 500;
        }

        .msp-compose-chip button {
          background: none;
          border: none;
          color: var(--primary-700, #4a9d4a);
          cursor: pointer;
          padding: 0;
          font-size: 1rem;
          line-height: 1;
        }

        .msp-compose-available {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }

        .msp-compose-available label {
          font-size: 0.85rem;
          font-weight: 500;
          color: var(--muted, #666);
        }

        .msp-compose-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
          gap: 0.75rem;
          max-height: 280px;
          overflow-y: auto;
          padding: 0.5rem;
        }

        .msp-compose-option {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.75rem 1rem;
          border: 1px solid color-mix(in oklab, var(--border, #e5e7eb) 70%, var(--primary, #7C9070) 30%);
          border-radius: 10px;
          background: var(--surface-2, #f3f4f6);
          color: var(--text, #333);
          cursor: pointer;
          font-size: 0.9rem;
          text-align: left;
          transition: all 0.15s;
          box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
        }

        .msp-compose-option:hover {
          border-color: var(--primary, #7C9070);
          background: color-mix(in oklab, var(--surface-2, #f3f4f6) 70%, var(--primary, #7C9070) 30%);
        }

        .msp-compose-option.selected {
          background: color-mix(in oklab, var(--primary, #7C9070) 22%, var(--surface, #fff));
          border-color: var(--primary, #7C9070);
          color: var(--text, #1a1f1a);
          box-shadow: 0 0 0 1px color-mix(in oklab, var(--primary, #7C9070) 60%, transparent);
        }

        .msp-compose-check {
          font-size: 0.9rem;
          width: 1.1rem;
          text-align: center;
        }

        .msp-compose-form {
          margin-top: 0.5rem;
          padding-top: 1rem;
          border-top: 1px solid var(--border, #e5e7eb);
        }

        .msp-compose-hint-more {
          text-align: center;
          color: var(--muted, #999);
          font-size: 0.85rem;
          padding: 1rem;
        }

        /* Custom Tab */
        .msp-form-row {
          margin-bottom: 1.25rem;
        }

        .msp-form-row label {
          display: block;
          font-size: 0.9rem;
          font-weight: 500;
          margin-bottom: 0.5rem;
          color: var(--text, #333);
        }

        .msp-form-row input,
        .msp-form-row textarea {
          width: 100%;
          padding: 0.85rem 1rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 10px;
          font-size: 0.95rem;
          background: var(--surface, #fff);
          color: var(--text, #333);
          transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
        }

        .msp-form-row textarea {
          min-height: 100px;
          resize: vertical;
        }

        .msp-form-row input::placeholder,
        .msp-form-row textarea::placeholder {
          color: var(--muted, #666);
        }

        .msp-form-row input:focus,
        .msp-form-row textarea:focus {
          outline: none;
          border-color: color-mix(in oklab, var(--primary, #7C9070) 55%, var(--border, #ddd));
          box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.16);
          background: var(--surface, #fff);
        }

        /* Buttons */
        .msp-btn {
          padding: 0.85rem 1.5rem;
          border-radius: 10px;
          font-size: 0.95rem;
          font-weight: 500;
          cursor: pointer;
          border: 1px solid transparent;
          transition: all 0.15s;
        }

        .msp-btn-full {
          width: 100%;
        }

        .msp-btn-primary {
          background: var(--primary, #7C9070);
          color: white;
        }

        .msp-btn-primary:hover {
          background: var(--primary-700, #4a9d4a);
        }

        .msp-btn-outline {
          background: transparent;
          border-color: var(--border, #ddd);
          color: var(--text, #333);
        }

        .msp-btn-ai {
          background: linear-gradient(135deg, var(--primary, #7C9070), var(--primary-700, #4a9d4a));
          color: white;
        }

        .msp-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .msp-btn-danger-outline {
          background: transparent;
          border-color: var(--danger, #dc2626);
          color: var(--danger, #dc2626);
        }

        .msp-btn-danger-outline:hover {
          background: var(--danger-bg, rgba(220, 38, 38, 0.1));
        }

        /* View Mode Styles */
        .msp-view-mode {
          flex: 1;
          display: flex;
          flex-direction: column;
          padding: 1.5rem;
          gap: 1.5rem;
        }

        .msp-existing-meal {
          flex: 1;
          background: var(--surface-2, #f9fafb);
          border-radius: 16px;
          padding: 1.5rem;
        }

        .msp-existing-meal h4 {
          margin: 0 0 0.75rem 0;
          font-size: 1.25rem;
          font-weight: 600;
          color: var(--text, #333);
        }

        .msp-existing-desc {
          font-size: 0.95rem;
          color: var(--muted, #666);
          line-height: 1.5;
          margin: 0 0 1rem 0;
        }

        .msp-dishes-view {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 0.5rem;
          margin-top: 1rem;
        }

        .msp-dishes-label {
          font-size: 0.85rem;
          font-weight: 500;
          color: var(--muted, #666);
        }

        .msp-dish-chip {
          display: inline-block;
          padding: 0.35rem 0.75rem;
          background: var(--surface, #fff);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 99px;
          font-size: 0.85rem;
          color: var(--text, #333);
        }

        .msp-servings-info,
        .msp-notes-info {
          font-size: 0.9rem;
          color: var(--muted, #666);
          margin: 0.75rem 0 0 0;
        }

        .msp-notes-info {
          font-style: italic;
        }

        .msp-view-actions {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        @media (min-width: 480px) {
          .msp-view-actions {
            flex-direction: row;
          }

          .msp-view-actions .msp-btn {
            flex: 1;
          }
        }

        /* Dark mode overrides for Compose tab */
        [data-theme="dark"] .msp-compose-selected {
          background: color-mix(in oklab, var(--primary, #7C9070) 15%, var(--surface, #1f1f1f));
          border-color: color-mix(in oklab, var(--primary, #7C9070) 40%, transparent);
        }

        [data-theme="dark"] .msp-compose-selected label {
          color: var(--primary-400, #86efac);
        }

        [data-theme="dark"] .msp-compose-chip {
          background: var(--surface-2, #2a2a2a);
          border-color: var(--primary, #7C9070);
          color: var(--primary-400, #86efac);
        }

        [data-theme="dark"] .msp-compose-chip button {
          color: var(--primary-400, #86efac);
        }

        [data-theme="dark"] .msp-compose-option {
          background: var(--surface-2, #2a2a2a);
          border-color: var(--border, #3a3a3a);
          color: var(--text, #e5e5e5);
        }

        [data-theme="dark"] .msp-compose-option:hover {
          background: color-mix(in oklab, var(--surface-2, #2a2a2a) 70%, var(--primary, #7C9070) 30%);
          border-color: var(--primary, #7C9070);
        }

        [data-theme="dark"] .msp-compose-option.selected {
          background: color-mix(in oklab, var(--primary, #7C9070) 25%, var(--surface-2, #2a2a2a));
          border-color: var(--primary, #7C9070);
          color: var(--text, #e5e5e5);
        }
      `}</style>
    </>
  )
}
