/**
 * MealPlanSlideout Component
 * 
 * Responsive slide-out panel for managing client meal plans.
 * - Desktop: Side panel (60% width)
 * - Tablet: Overlay (85% width)  
 * - Mobile: Full screen modal
 */

import React, { useState, useEffect, useCallback } from 'react'
import MealPlanWeekView from './MealPlanWeekView.jsx'
import MealSlotPicker from './MealSlotPicker.jsx'
import {
  getClientPlans,
  createPlan,
  getPlanDetail,
  updatePlan,
  publishPlan,
  unpublishPlan,
  startMealGeneration,
  addPlanDay,
  addPlanItem,
  deletePlanItem
} from '../api/chefMealPlanClient.js'
import { useSousChefNotifications } from '../contexts/SousChefNotificationContext.jsx'

// Lowercase values match the backend ChefMealPlanItem model
const MEAL_TYPES = ['breakfast', 'lunch', 'dinner', 'snack']
const MEAL_TYPE_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' }

// Helper: Get today's date in YYYY-MM-DD format
function getTodayISO() {
  return new Date().toISOString().slice(0, 10)
}

// Helper: Format date as YYYY-MM-DD
function formatDateISO(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

// Helper: Get start of week (Monday) for a given date
function getStartOfWeek(date) {
  const d = new Date(date)
  const day = d.getDay()
  const diff = (day === 0 ? -6 : 1) - day // Monday as start
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

// Helper: Get default dates for a new meal plan (next Monday → Sunday)
function getDefaultPlanDates() {
  const today = new Date()
  const dayOfWeek = today.getDay() // 0 = Sunday, 6 = Saturday

  // Always start from next Monday
  const daysUntilMonday = dayOfWeek === 0 ? 1 : 8 - dayOfWeek
  const startDate = new Date(today)
  startDate.setDate(today.getDate() + daysUntilMonday)

  // End date is 6 days later (1 week: Mon-Sun)
  const endDate = new Date(startDate)
  endDate.setDate(startDate.getDate() + 6)

  return {
    start_date: formatDateISO(startDate),
    end_date: formatDateISO(endDate)
  }
}

// Helper: Get human-readable context for a date range
function getDateRangeContext(startDate, endDate) {
  const start = new Date(startDate + 'T00:00:00')
  const end = new Date(endDate + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const daysCount = Math.round((end - start) / (1000 * 60 * 60 * 24)) + 1
  const weeksCount = Math.ceil(daysCount / 7)

  const thisWeekStart = getStartOfWeek(today)
  const diffFromThisWeek = Math.round((start - thisWeekStart) / (1000 * 60 * 60 * 24))

  let weekContext = ''
  if (diffFromThisWeek >= 0 && diffFromThisWeek < 7) {
    weekContext = 'Starts this week'
  } else if (diffFromThisWeek >= 7 && diffFromThisWeek < 14) {
    weekContext = 'Starts next week'
  } else if (diffFromThisWeek < 0 && diffFromThisWeek >= -7) {
    weekContext = 'Started last week'
  } else if (diffFromThisWeek < 0) {
    const weeksAgo = Math.abs(Math.floor(diffFromThisWeek / 7))
    weekContext = `Started ${weeksAgo} week${weeksAgo > 1 ? 's' : ''} ago`
  } else {
    const weeksAhead = Math.floor(diffFromThisWeek / 7)
    weekContext = `Starts in ${weeksAhead} week${weeksAhead > 1 ? 's' : ''}`
  }

  return `${weekContext} · ${daysCount} day${daysCount > 1 ? 's' : ''} (${weeksCount} week${weeksCount > 1 ? 's' : ''})`
}

export default function MealPlanSlideout({
  isOpen,
  onClose,
  client,
  onPlanUpdate,
  onNavigateToPrep
}) {
  // Notification context for Sous Chef
  let notifications = null
  try {
    notifications = useSousChefNotifications()
  } catch (e) {
    // Context not available (not wrapped in provider)
  }
  
  const [activeTab, setActiveTab] = useState('week')
  const [plans, setPlans] = useState([])
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [planDetail, setPlanDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [error, setError] = useState(null)
  const [justPublished, setJustPublished] = useState(false)
  
  // Slot picker state
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerSlot, setPickerSlot] = useState(null)
  
  // New plan form
  const [showNewPlanForm, setShowNewPlanForm] = useState(false)
  const [newPlanForm, setNewPlanForm] = useState({
    title: '',
    start_date: '',
    end_date: '',
    notes: ''
  })

  // Edit dates state (for draft plans)
  const [showEditDates, setShowEditDates] = useState(false)
  const [editDatesForm, setEditDatesForm] = useState({ start_date: '', end_date: '' })
  const [editDatesError, setEditDatesError] = useState(null)

  // Week navigation state (lifted from MealPlanWeekView for generation context)
  const [currentWeekIndex, setCurrentWeekIndex] = useState(0)

  // Watch for active jobs completing (in case they started before modal opened)
  useEffect(() => {
    if (notifications?.activeJobs && selectedPlan) {
      const activeJob = notifications.activeJobs.find(j => j.planId === selectedPlan.id)
      if (activeJob) {
        setGenerating(true)
        setGenerationStatus(`Generating... (${activeJob.slotsGenerated || 0}/${activeJob.slotsRequested || '?'} slots)`)
      } else if (generating && !generationStatus.includes('starting')) {
        // Job completed while we were watching
        setGenerating(false)
        setGenerationStatus('')
      }
    }
  }, [notifications?.activeJobs, selectedPlan])
  
  // Load plans when client changes
  useEffect(() => {
    if (isOpen && client) {
      loadPlans()
    }
  }, [isOpen, client])

  // Load plan detail when selected plan changes
  useEffect(() => {
    if (selectedPlan) {
      loadPlanDetail(selectedPlan.id)
    } else {
      setPlanDetail(null)
    }
    // Close edit dates form when switching plans (prevents stale data)
    setShowEditDates(false)
  }, [selectedPlan])

  const loadPlans = async () => {
    if (!client) return
    setLoading(true)
    setError(null)
    try {
      // Keep the full client ID with prefix (e.g., "platform_123" or "contact_456")
      const clientId = String(client.id)
      const data = await getClientPlans(clientId)
      setPlans(data?.plans || [])
      // Smart plan selection: prioritize plans containing today > upcoming > past
      if (data?.plans?.length > 0) {
        const today = new Date()
        today.setHours(0, 0, 0, 0)

        // Categorize plans by relevance
        let containsToday = []
        let upcoming = []
        let past = []

        for (const plan of data.plans) {
          const start = new Date(plan.start_date + 'T00:00:00')
          const end = new Date(plan.end_date + 'T00:00:00')

          if (start <= today && today <= end) {
            containsToday.push(plan)
          } else if (start > today) {
            upcoming.push(plan)
          } else {
            past.push(plan)
          }
        }

        // Sort upcoming by start_date ascending (soonest first)
        upcoming.sort((a, b) => new Date(a.start_date) - new Date(b.start_date))
        // Sort past by end_date descending (most recent first)
        past.sort((a, b) => new Date(b.end_date) - new Date(a.end_date))

        // Priority: contains today > upcoming > past
        // Within each category, prefer drafts
        const selectBest = (plans) => {
          const draft = plans.find(p => p.status === 'draft')
          return draft || plans[0]
        }

        if (containsToday.length > 0) {
          setSelectedPlan(selectBest(containsToday))
        } else if (upcoming.length > 0) {
          setSelectedPlan(selectBest(upcoming))
        } else if (past.length > 0) {
          setSelectedPlan(selectBest(past))
        }
      }
    } catch (err) {
      setError(err.message || 'Failed to load plans')
    } finally {
      setLoading(false)
    }
  }

  const loadPlanDetail = async (planId) => {
    setLoading(true)
    try {
      const data = await getPlanDetail(planId)
      setPlanDetail(data)
    } catch (err) {
      setError(err.message || 'Failed to load plan details')
    } finally {
      setLoading(false)
    }
  }

  const handleCreatePlan = async (e) => {
    e.preventDefault()
    if (!client) return
    
    setLoading(true)
    setError(null)
    try {
      const clientId = String(client.id)
      const newPlan = await createPlan(clientId, newPlanForm)
      setPlans(prev => [newPlan, ...prev])
      setSelectedPlan(newPlan)
      setShowNewPlanForm(false)
      setNewPlanForm({ title: '', start_date: '', end_date: '', notes: '' })
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to create plan')
    } finally {
      setLoading(false)
    }
  }

  const [generationStatus, setGenerationStatus] = useState('')
  
  const handleGenerateMeals = async (mode = 'full_week') => {
    if (!selectedPlan) return

    setGenerating(true)
    setError(null)
    setGenerationStatus('Starting AI generation...')

    try {
      // Start the async generation job with current week context
      const startData = await startMealGeneration(selectedPlan.id, {
        mode,
        week_offset: currentWeekIndex
      })
      
      if (!startData?.job_id) {
        throw new Error('Failed to start generation job')
      }
      
      const clientName = client?.name || client?.first_name || 'Client'
      const planTitle = selectedPlan?.title || 'Meal Plan'
      
      // Track job globally - this continues even if modal closes!
      if (notifications?.trackJob) {
        notifications.trackJob({
          jobId: startData.job_id,
          planId: selectedPlan.id,
          planTitle,
          clientName,
          mode,
          onComplete: (result) => {
            // If modal is still open, update local state
            if (selectedPlan?.id === result.plan_id || selectedPlan?.id) {
              const suggestionsList = result?.suggestions || []
              setSuggestions(suggestionsList)
              setActiveTab('suggestions')
              setGenerating(false)
              setGenerationStatus('')
            }
          }
        })
        
        setGenerationStatus('AI is generating in background - you can close this modal...')
        
        // Show a helpful message that they can leave
        setTimeout(() => {
          if (generating) {
            setGenerationStatus('✓ Generation running. Feel free to close - Sous Chef will notify you when done!')
          }
        }, 3000)
      } else {
        // Fallback if no notification context - show error
        setError('Background tracking not available')
        setGenerating(false)
      }
      
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to start generation')
      setGenerationStatus('')
      setGenerating(false)
    }
  }

  const handleAcceptSuggestion = async (suggestion) => {
    if (!selectedPlan || !planDetail) return

    try {
      // Use actual date if available (new format), fallback to day name matching (legacy)
      let targetDate = suggestion.date
      if (!targetDate) {
        // Fallback: find first matching day name in plan range
        const dayName = suggestion.day
        const dates = getDatesInRange(planDetail.start_date, planDetail.end_date)
        targetDate = dates.find(d => new Date(d).toLocaleDateString('en-US', { weekday: 'long' }) === dayName)
      }

      if (!targetDate) {
        setError(`Could not find ${suggestion.day} in plan date range`)
        return
      }

      // Check if day exists
      let day = planDetail.days?.find(d => d.date === targetDate)
      
      if (!day) {
        // Create the day
        day = await addPlanDay(selectedPlan.id, { date: targetDate })
      }
      
      // Add the item
      await addPlanItem(selectedPlan.id, day.id, {
        meal_type: suggestion.meal_type,
        custom_name: suggestion.name,
        custom_description: suggestion.description,
        servings: 1
      })
      
      // Refresh plan detail
      await loadPlanDetail(selectedPlan.id)
      
      // Remove from suggestions
      setSuggestions(prev => prev.filter(s => 
        !(s.day === suggestion.day && s.meal_type === suggestion.meal_type)
      ))
      
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to add meal')
    }
  }

  const handleSlotClick = useCallback((date, mealType, existingItem, dayId) => {
    setPickerSlot({ date, mealType, existingItem, dayId })
    setPickerOpen(true)
  }, [])

  const handleSlotAssign = async (assignment) => {
    if (!selectedPlan || !pickerSlot) return

    try {
      const { date, mealType, existingItem, dayId } = pickerSlot

      // Delete existing item if any (use dayId directly)
      if (existingItem && dayId) {
        await deletePlanItem(selectedPlan.id, dayId, existingItem.id)
      }

      // Use existing dayId or create a new day
      let targetDayId = dayId
      if (!targetDayId) {
        const newDay = await addPlanDay(selectedPlan.id, { date })
        targetDayId = newDay.id
      }

      // Add new item
      await addPlanItem(selectedPlan.id, targetDayId, {
        meal_type: mealType,
        meal_id: assignment.meal_id,
        custom_name: assignment.custom_name || '',
        custom_description: assignment.custom_description || '',
        servings: assignment.servings || 1
      })

      // Refresh
      await loadPlanDetail(selectedPlan.id)
      setPickerOpen(false)
      setPickerSlot(null)

    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to assign meal')
    }
  }

  const handleSlotRemove = async () => {
    if (!selectedPlan || !pickerSlot?.existingItem) return
    try {
      const { dayId, existingItem } = pickerSlot
      if (!dayId) {
        setError('Cannot remove meal: day information missing')
        return
      }
      await deletePlanItem(selectedPlan.id, dayId, existingItem.id)
      await loadPlanDetail(selectedPlan.id)
      setPickerOpen(false)
      setPickerSlot(null)
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to remove meal')
    }
  }

  const handlePublish = async () => {
    if (!selectedPlan) return
    try {
      await publishPlan(selectedPlan.id)
      await loadPlans()
      setJustPublished(true)
      if (onPlanUpdate) onPlanUpdate()
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to publish plan')
    }
  }

  const handleUnpublish = async () => {
    if (!selectedPlan) return
    try {
      await unpublishPlan(selectedPlan.id)
      await loadPlans()
      await loadPlanDetail(selectedPlan.id)
      if (onPlanUpdate) onPlanUpdate()
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to revert plan to draft')
    }
  }

  // Open edit dates form with current values
  const handleOpenEditDates = () => {
    if (planDetail) {
      setEditDatesForm({
        start_date: planDetail.start_date,
        end_date: planDetail.end_date
      })
      setEditDatesError(null)
      setShowEditDates(true)
    }
  }

  // Save date changes
  const handleSaveDates = async (e) => {
    e.preventDefault()
    if (!selectedPlan) return

    setLoading(true)
    setEditDatesError(null)
    try {
      await updatePlan(selectedPlan.id, {
        start_date: editDatesForm.start_date,
        end_date: editDatesForm.end_date
      })
      await loadPlanDetail(selectedPlan.id)
      await loadPlans()
      setShowEditDates(false)
      if (onPlanUpdate) onPlanUpdate()
    } catch (err) {
      setEditDatesError(err.response?.data?.error || err.message || 'Failed to update dates')
    } finally {
      setLoading(false)
    }
  }

  // Helper to format date range: "Jan 15 - 21, 2025" or "Jan 30 - Feb 5, 2025"
  const formatDateRange = (startDate, endDate) => {
    if (!startDate || !endDate) return ''
    const start = new Date(startDate)
    const end = new Date(endDate)
    const startMonth = start.toLocaleDateString('en-US', { month: 'short' })
    const endMonth = end.toLocaleDateString('en-US', { month: 'short' })
    const startDay = start.getDate()
    const endDay = end.getDate()
    const year = end.getFullYear()

    if (startMonth === endMonth) {
      return `${startMonth} ${startDay} - ${endDay}, ${year}`
    } else {
      return `${startMonth} ${startDay} - ${endMonth} ${endDay}, ${year}`
    }
  }

  if (!isOpen) return null

  const isDraft = selectedPlan?.status === 'draft'

  return (
    <>
      {/* Backdrop */}
      <div className="mps-backdrop" onClick={onClose} />
      
      {/* Panel */}
      <div className="mps-panel">
        {/* Header */}
        <header className="mps-header">
          <div className="mps-header-left">
            <button className="mps-back-btn" onClick={onClose} aria-label="Close">
              ←
            </button>
            <div className="mps-header-text">
              <h2>Meal Plans</h2>
              <span className="mps-client-name">{client?.name}</span>
              {selectedPlan && planDetail && (
                <div className="mps-date-range-row">
                  <span className="mps-date-range">
                    {formatDateRange(planDetail.start_date, planDetail.end_date)}
                  </span>
                  {isDraft && (
                    <button
                      className="mps-btn-icon"
                      onClick={handleOpenEditDates}
                      title="Edit dates"
                      aria-label="Edit dates"
                    >
                      ✏️
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="mps-header-actions">
            {isDraft ? (
              <button
                className="mps-btn mps-btn-primary"
                onClick={handlePublish}
                disabled={loading}
              >
                Publish
              </button>
            ) : selectedPlan?.status === 'published' && (
              <button
                className="mps-btn mps-btn-outline"
                onClick={handleUnpublish}
                disabled={loading}
                title="Revert to draft for editing"
              >
                Edit Plan
              </button>
            )}
          </div>
        </header>

        {/* Plan Selector */}
        <div className="mps-plan-selector">
          <select
            className="mps-select"
            value={selectedPlan?.id || ''}
            onChange={(e) => {
              const plan = plans.find(p => p.id === parseInt(e.target.value))
              setSelectedPlan(plan)
              setJustPublished(false)
            }}
          >
            <option value="">Select a plan...</option>
            {plans.map(plan => (
              <option key={plan.id} value={plan.id}>
                {plan.title || `${plan.start_date} - ${plan.end_date}`}
                {plan.status === 'draft' ? ' (Draft)' : ''}
              </option>
            ))}
          </select>
          <button
            className="mps-btn mps-btn-outline"
            onClick={() => {
              const defaultDates = getDefaultPlanDates()
              setNewPlanForm({
                title: '',
                start_date: defaultDates.start_date,
                end_date: defaultDates.end_date,
                notes: ''
              })
              setShowNewPlanForm(true)
            }}
          >
            + New Plan
          </button>
        </div>

        {/* Edit Dates Form (Draft Plans Only) */}
        {showEditDates && (
          <div className="mps-edit-dates-form">
            <form onSubmit={handleSaveDates}>
              <div className="mps-edit-dates-header">
                <h3>Edit Plan Dates</h3>
                <span className="mps-edit-dates-warning">
                  Changing dates may affect meals outside the new range
                </span>
              </div>
              <div className="mps-form-row mps-form-row-2col">
                <div>
                  <label>Start Date</label>
                  <input
                    type="date"
                    required
                    value={editDatesForm.start_date}
                    onChange={e => setEditDatesForm(f => ({ ...f, start_date: e.target.value }))}
                  />
                </div>
                <div>
                  <label>End Date</label>
                  <input
                    type="date"
                    required
                    value={editDatesForm.end_date}
                    onChange={e => setEditDatesForm(f => ({ ...f, end_date: e.target.value }))}
                  />
                </div>
              </div>
              {editDatesError && (
                <div className="mps-edit-dates-error">{editDatesError}</div>
              )}
              <div className="mps-form-actions">
                <button
                  type="button"
                  className="mps-btn mps-btn-outline"
                  onClick={() => setShowEditDates(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="mps-btn mps-btn-primary" disabled={loading}>
                  {loading ? 'Saving...' : 'Save Dates'}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Publish Success Banner */}
        {justPublished && (
          <div className="mps-publish-success">
            <span>✓ Plan published to {client?.name || 'client'}</span>
            {onNavigateToPrep && (
              <button
                className="mps-btn mps-btn-link"
                onClick={() => {
                  onClose()
                  onNavigateToPrep()
                }}
              >
                Start Prepping →
              </button>
            )}
          </div>
        )}

        {/* New Plan Form */}
        {showNewPlanForm && (
          <div className="mps-new-plan-form">
            <h3>Create New Plan</h3>
            <form onSubmit={handleCreatePlan}>
              <div className="mps-form-row">
                <label>Title (optional)</label>
                <input 
                  type="text"
                  placeholder="e.g., Holiday Week Menu"
                  value={newPlanForm.title}
                  onChange={e => setNewPlanForm(f => ({ ...f, title: e.target.value }))}
                />
              </div>
              <div className="mps-form-row mps-form-row-2col">
                <div>
                  <label>Start Date *</label>
                  <input
                    type="date"
                    required
                    value={newPlanForm.start_date}
                    onChange={e => setNewPlanForm(f => ({ ...f, start_date: e.target.value }))}
                  />
                </div>
                <div>
                  <label>End Date *</label>
                  <input
                    type="date"
                    required
                    value={newPlanForm.end_date}
                    onChange={e => setNewPlanForm(f => ({ ...f, end_date: e.target.value }))}
                  />
                </div>
              </div>

              {/* Date context helper */}
              {newPlanForm.start_date && newPlanForm.end_date && (
                <div className="mps-date-context">
                  {getDateRangeContext(newPlanForm.start_date, newPlanForm.end_date)}
                </div>
              )}

              {/* Past date warning */}
              {newPlanForm.start_date && new Date(newPlanForm.start_date + 'T00:00:00') < new Date(getTodayISO() + 'T00:00:00') && (
                <div className="mps-past-warning">
                  ⚠️ Start date is in the past. Plans typically start today or later.
                </div>
              )}

              <div className="mps-form-row">
                <label>Notes</label>
                <textarea 
                  rows={2}
                  placeholder="Any notes for the client..."
                  value={newPlanForm.notes}
                  onChange={e => setNewPlanForm(f => ({ ...f, notes: e.target.value }))}
                />
              </div>
              <div className="mps-form-actions">
                <button type="button" className="mps-btn mps-btn-outline" onClick={() => setShowNewPlanForm(false)}>
                  Cancel
                </button>
                <button type="submit" className="mps-btn mps-btn-primary" disabled={loading}>
                  {loading ? 'Creating...' : 'Create Plan'}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mps-error">
            {error}
            <button onClick={() => setError(null)}>×</button>
          </div>
        )}

        {/* Tabs */}
        {selectedPlan && (
          <div className="mps-tabs">
            <button 
              className={`mps-tab ${activeTab === 'week' ? 'active' : ''}`}
              onClick={() => setActiveTab('week')}
            >
              Week View
            </button>
            <button 
              className={`mps-tab ${activeTab === 'suggestions' ? 'active' : ''}`}
              onClick={() => setActiveTab('suggestions')}
            >
              AI Suggestions {suggestions.length > 0 && `(${suggestions.length})`}
            </button>
          </div>
        )}

        {/* Content */}
        <div className="mps-content">
          {loading && !planDetail ? (
            <div className="mps-loading">Loading...</div>
          ) : !selectedPlan ? (
            <div className="mps-empty">
              <div className="mps-empty-icon">📅</div>
              <p>No plan selected. Create a new plan or select an existing one.</p>
            </div>
          ) : activeTab === 'week' ? (
            <>
              {/* AI Generate Button */}
              {isDraft && (
                <div className="mps-ai-bar">
                  <button 
                    className="mps-btn mps-btn-ai"
                    onClick={() => handleGenerateMeals('full_week')}
                    disabled={generating}
                  >
                    {generating ? `🔄 ${generationStatus || 'Generating...'}` : '✨ Generate Full Week with AI'}
                  </button>
                  <button 
                    className="mps-btn mps-btn-outline"
                    onClick={() => handleGenerateMeals('fill_empty')}
                    disabled={generating}
                  >
                    Fill Empty Slots
                  </button>
                </div>
              )}
              
              <MealPlanWeekView
                planDetail={planDetail}
                onSlotClick={handleSlotClick}
                readOnly={!isDraft}
                currentWeekIndex={currentWeekIndex}
                onWeekChange={setCurrentWeekIndex}
              />
            </>
          ) : (
            /* Suggestions Tab */
            <div className="mps-suggestions">
              {suggestions.length === 0 ? (
                <div className="mps-empty">
                  <div className="mps-empty-icon">✨</div>
                  <p>No suggestions yet. Click "Generate" to get AI meal ideas.</p>
                  <button 
                    className="mps-btn mps-btn-ai"
                    onClick={() => handleGenerateMeals('full_week')}
                    disabled={generating}
                  >
                    {generating ? 'Generating...' : 'Generate Suggestions'}
                  </button>
                </div>
              ) : (
                <div className="mps-suggestions-list">
                  {suggestions.map((s, idx) => (
                    <div key={idx} className="mps-suggestion-card">
                      <div className="mps-suggestion-header">
                        <span className="mps-suggestion-slot">
                          {s.date ? `${new Date(s.date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} (${s.day})` : s.day} • {s.meal_type}
                        </span>
                        <div className="mps-suggestion-actions">
                          <button 
                            className="mps-btn mps-btn-sm mps-btn-primary"
                            onClick={() => handleAcceptSuggestion(s)}
                          >
                            Accept
                          </button>
                          <button 
                            className="mps-btn mps-btn-sm mps-btn-outline"
                            onClick={() => setSuggestions(prev => prev.filter((_, i) => i !== idx))}
                          >
                            Skip
                          </button>
                        </div>
                      </div>
                      <h4 className="mps-suggestion-name">{s.name}</h4>
                      <p className="mps-suggestion-desc">{s.description}</p>
                      {s.dietary_tags?.length > 0 && (
                        <div className="mps-suggestion-tags">
                          {s.dietary_tags.map((tag, i) => (
                            <span key={i} className="mps-tag">{tag}</span>
                          ))}
                        </div>
                      )}
                      {s.household_notes && (
                        <p className="mps-suggestion-notes">💡 {s.household_notes}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Slot Picker Modal */}
      {pickerOpen && (
        <MealSlotPicker
          isOpen={pickerOpen}
          onClose={() => { setPickerOpen(false); setPickerSlot(null) }}
          slot={pickerSlot}
          existingItem={pickerSlot?.existingItem}
          onAssign={handleSlotAssign}
          onRemove={handleSlotRemove}
          planId={selectedPlan?.id}
          planTitle={selectedPlan?.title || 'Meal Plan'}
          clientName={client?.name || client?.first_name || 'Client'}
          readOnly={!isDraft}
        />
      )}

      <style>{`
        /* Backdrop */
        .mps-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.4);
          z-index: 1000;
          animation: fadeIn 0.2s ease;
        }
        
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        /* Panel - Mobile First (Full Screen) */
        .mps-panel {
          position: fixed;
          top: 0;
          right: 0;
          bottom: 0;
          width: 100%;
          background: var(--bg, #fff);
          z-index: 1001;
          display: flex;
          flex-direction: column;
          animation: slideIn 0.25s ease;
        }
        
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }

        /* Tablet */
        @media (min-width: 768px) {
          .mps-panel {
            width: 85%;
            max-width: 700px;
            box-shadow: -4px 0 24px rgba(27, 58, 45, 0.15);
          }
        }

        /* Desktop */
        @media (min-width: 1024px) {
          .mps-panel {
            width: 60%;
            max-width: 800px;
          }
        }

        /* Header */
        .mps-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 1rem;
          border-bottom: 1px solid var(--border, #e5e7eb);
          background: var(--surface, #fff);
          flex-shrink: 0;
        }

        .mps-header-left {
          display: flex;
          align-items: center;
          gap: 0.75rem;
        }

        .mps-back-btn {
          width: 36px;
          height: 36px;
          border: none;
          background: var(--surface-2, #f3f4f6);
          border-radius: 8px;
          font-size: 1.25rem;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .mps-header-text h2 {
          margin: 0;
          font-size: 1.1rem;
          font-weight: 600;
        }

        .mps-client-name {
          font-size: 0.85rem;
          color: var(--muted, #666);
        }

        /* Date Range Row */
        .mps-date-range-row {
          display: flex;
          align-items: center;
          gap: 0.35rem;
          margin-top: 0.15rem;
        }

        .mps-date-range {
          font-size: 0.8rem;
          color: var(--muted, #666);
        }

        .mps-btn-icon {
          background: none;
          border: none;
          padding: 0.15rem 0.25rem;
          cursor: pointer;
          font-size: 0.8rem;
          opacity: 0.6;
          transition: opacity 0.15s;
        }

        .mps-btn-icon:hover {
          opacity: 1;
        }

        /* Edit Dates Form */
        .mps-edit-dates-form {
          padding: 1rem;
          background: var(--surface-2, #f9fafb);
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .mps-edit-dates-header {
          margin-bottom: 0.75rem;
        }

        .mps-edit-dates-header h3 {
          margin: 0 0 0.25rem 0;
          font-size: 1rem;
        }

        .mps-edit-dates-warning {
          font-size: 0.8rem;
          color: var(--warning, #f0ad4e);
        }

        .mps-edit-dates-error {
          padding: 0.5rem 0.75rem;
          background: var(--danger-bg, #fef2f2);
          color: var(--danger, #dc2626);
          font-size: 0.85rem;
          border-radius: 6px;
          margin-top: 0.5rem;
        }

        /* Plan Selector */
        .mps-plan-selector {
          display: flex;
          gap: 0.5rem;
          padding: 0.75rem 1rem;
          border-bottom: 1px solid var(--border, #e5e7eb);
          flex-wrap: wrap;
        }

        .mps-select {
          flex: 1;
          min-width: 200px;
          padding: 0.5rem 0.75rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 8px;
          background: var(--surface, #fff);
          color: var(--text, #333);
          font-size: 0.9rem;
        }

        .mps-select option {
          background: var(--surface, #fff);
          color: var(--text, #333);
        }

        /* Buttons */
        .mps-btn {
          padding: 0.5rem 1rem;
          border-radius: 8px;
          font-size: 0.9rem;
          font-weight: 500;
          cursor: pointer;
          border: 1px solid transparent;
          transition: all 0.15s;
          white-space: nowrap;
        }

        .mps-btn-sm {
          padding: 0.35rem 0.75rem;
          font-size: 0.8rem;
        }

        .mps-btn-primary {
          background: var(--primary, #7C9070);
          color: white;
          border-color: var(--primary, #7C9070);
        }

        .mps-btn-primary:hover {
          background: var(--primary-700, #4a9d4a);
        }

        .mps-btn-outline {
          background: transparent;
          border-color: var(--border, #ddd);
          color: var(--text, #333);
        }

        .mps-btn-outline:hover {
          background: var(--surface-2, #f3f4f6);
        }

        .mps-btn-ai {
          background: linear-gradient(135deg, var(--primary, #7C9070), var(--primary-700, #4a9d4a));
          color: white;
          border: none;
        }

        .mps-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .mps-btn-link {
          background: none;
          border: none;
          color: var(--primary, #7C9070);
          font-weight: 500;
          cursor: pointer;
          padding: 0;
        }

        .mps-btn-link:hover {
          text-decoration: underline;
        }

        /* Publish Success Banner */
        .mps-publish-success {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          padding: 0.75rem 1rem;
          background: var(--success-bg, #f0fdf4);
          border: 1px solid var(--success, #22c55e);
          border-radius: 8px;
          margin: 0.5rem 1rem;
          font-size: 0.9rem;
          color: var(--success-700, #15803d);
        }

        [data-theme="dark"] .mps-publish-success {
          background: color-mix(in oklab, var(--success, #22c55e) 15%, var(--surface, #1f1f1f));
          color: var(--success-400, #4ade80);
        }

        /* New Plan Form */
        .mps-new-plan-form {
          padding: 1rem;
          background: var(--surface-2, #f9fafb);
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .mps-new-plan-form h3 {
          margin: 0 0 1rem 0;
          font-size: 1rem;
        }

        .mps-form-row {
          margin-bottom: 0.75rem;
        }

        .mps-form-row label {
          display: block;
          font-size: 0.8rem;
          font-weight: 500;
          margin-bottom: 0.25rem;
          color: var(--muted, #666);
        }

        .mps-form-row input,
        .mps-form-row textarea {
          width: 100%;
          padding: 0.5rem 0.75rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 8px;
          font-size: 0.9rem;
        }

        .mps-form-row-2col {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 0.75rem;
        }

        .mps-form-actions {
          display: flex;
          gap: 0.5rem;
          justify-content: flex-end;
          margin-top: 1rem;
        }

        /* Date context helper */
        .mps-date-context {
          font-size: 0.85rem;
          color: var(--muted, #666);
          padding: 0.5rem 0.75rem;
          background: var(--surface-2, #f9fafb);
          border-radius: 6px;
          margin-bottom: 0.75rem;
        }

        /* Past date warning */
        .mps-past-warning {
          font-size: 0.85rem;
          color: var(--warning, #b45309);
          background: var(--warning-bg, rgba(245, 158, 11, 0.12));
          padding: 0.5rem 0.75rem;
          border-radius: 6px;
          margin-bottom: 0.75rem;
        }

        [data-theme="dark"] .mps-date-context {
          background: var(--surface-2);
        }

        [data-theme="dark"] .mps-past-warning {
          color: var(--warning, #fbbf24);
          background: rgba(251, 191, 36, 0.12);
        }

        /* Error */
        .mps-error {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0.75rem 1rem;
          background: var(--danger-bg);
          color: var(--danger);
          font-size: 0.9rem;
        }

        .mps-error button {
          background: none;
          border: none;
          font-size: 1.25rem;
          cursor: pointer;
          color: inherit;
        }

        /* Tabs */
        .mps-tabs {
          display: flex;
          border-bottom: 1px solid var(--border, #e5e7eb);
          flex-shrink: 0;
        }

        .mps-tab {
          flex: 1;
          padding: 0.75rem 1rem;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          font-size: 0.9rem;
          font-weight: 500;
          color: var(--muted, #666);
          cursor: pointer;
          transition: all 0.15s;
        }

        .mps-tab.active {
          color: var(--primary, #7C9070);
          border-bottom-color: var(--primary, #7C9070);
        }

        .mps-tab:hover:not(.active) {
          background: var(--surface-2, #f9fafb);
        }

        /* Content */
        .mps-content {
          flex: 1;
          overflow-y: auto;
          padding: 1rem;
        }

        .mps-loading,
        .mps-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 3rem 1rem;
          text-align: center;
          color: var(--muted, #666);
        }

        .mps-empty-icon {
          font-size: 3rem;
          margin-bottom: 1rem;
          opacity: 0.5;
        }

        /* AI Bar */
        .mps-ai-bar {
          display: flex;
          gap: 0.5rem;
          margin-bottom: 1rem;
          flex-wrap: wrap;
        }

        /* Suggestions */
        .mps-suggestions-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .mps-suggestion-card {
          background: var(--surface, #fff);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 16px;
          padding: 1rem;
        }

        .mps-suggestion-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.5rem;
          flex-wrap: wrap;
          gap: 0.5rem;
        }

        .mps-suggestion-slot {
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--primary, #7C9070);
          background: rgba(124, 144, 112, 0.1);
          padding: 0.25rem 0.5rem;
          border-radius: 4px;
        }

        .mps-suggestion-actions {
          display: flex;
          gap: 0.35rem;
        }

        .mps-suggestion-name {
          margin: 0 0 0.35rem 0;
          font-size: 1rem;
          font-weight: 600;
        }

        .mps-suggestion-desc {
          margin: 0 0 0.5rem 0;
          font-size: 0.9rem;
          color: var(--muted, #666);
          line-height: 1.4;
        }

        .mps-suggestion-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 0.35rem;
          margin-bottom: 0.5rem;
        }

        .mps-tag {
          font-size: 0.75rem;
          padding: 0.2rem 0.5rem;
          background: var(--surface-2, #f3f4f6);
          border-radius: 4px;
          color: var(--muted, #666);
        }

        .mps-suggestion-notes {
          font-size: 0.85rem;
          color: var(--muted, #666);
          margin: 0;
          font-style: italic;
        }
      `}</style>
    </>
  )
}

// Helper to get dates in range
function getDatesInRange(startDate, endDate) {
  const dates = []
  const start = new Date(startDate)
  const end = new Date(endDate)
  
  while (start <= end) {
    dates.push(start.toISOString().split('T')[0])
    start.setDate(start.getDate() + 1)
  }
  
  return dates
}
