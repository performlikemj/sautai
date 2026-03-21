import React, { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import StarRating from './StarRating.jsx'
import ConfirmDialog from './ConfirmDialog.jsx'
import {
  getSurveys,
  createSurvey,
  activateSurvey,
  closeSurvey,
  sendSurvey,
  deleteSurvey,
  updateSurvey,
  getSurveyResponses,
  getTemplates,
  createTemplate,
  getStatusLabel,
  SURVEY_STATUSES,
} from '../api/surveyClient.js'
import { api } from '../api'

const QUESTION_TYPE_ICONS = { rating: '\u2605', text: '\u00B6', yes_no: '\u25C9' }

export default function ChefSurveys() {
  const [surveys, setSurveys] = useState([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('')
  const [selected, setSelected] = useState(null)
  const [responsesData, setResponsesData] = useState(null)
  const [showResponses, setShowResponses] = useState(false)

  // Create modal
  const [showCreate, setShowCreate] = useState(false)
  const [events, setEvents] = useState([])
  const [templates, setTemplates] = useState([])
  const [createEventId, setCreateEventId] = useState('')
  const [createTemplateId, setCreateTemplateId] = useState('')
  const [creating, setCreating] = useState(false)

  // Edit questions
  const [editingQuestions, setEditingQuestions] = useState(false)
  const [editQuestions, setEditQuestions] = useState([])

  // Confirm dialog (replaces browser confirm())
  const [confirmState, setConfirmState] = useState({ open: false, title: '', message: '', action: null })

  // Template name modal (replaces browser prompt())
  const [templateModal, setTemplateModal] = useState({ open: false, survey: null, name: '' })

  // Toasts (replaces browser alert())
  const [toasts, setToasts] = useState([])

  const [actionLoading, setActionLoading] = useState('')
  const [error, setError] = useState('')

  const pushToast = (text, tone = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts(prev => [...prev, { id, text, tone, closing: false }])
    setTimeout(() => {
      setToasts(prev => prev.map(t => t.id === id ? { ...t, closing: true } : t))
      setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 260)
    }, 3000)
  }

  const loadSurveys = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getSurveys({ status: statusFilter || undefined })
      setSurveys(data || [])
    } catch (err) {
      console.error('Failed to load surveys:', err)
      setSurveys([])
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { loadSurveys() }, [loadSurveys])

  // Stats computed from loaded surveys
  const stats = {
    total: surveys.length,
    active: surveys.filter(s => s.status === 'active').length,
    responses: surveys.reduce((sum, s) => sum + (s.response_count || 0), 0),
  }

  const loadEvents = async () => {
    try {
      const resp = await api.get('/meals/api/chef-meal-events/', { skipUserId: true, withCredentials: true })
      setEvents(resp?.data?.results || resp?.data || [])
    } catch { setEvents([]) }
  }

  const loadTemplates = async () => {
    try {
      const data = await getTemplates()
      setTemplates(data || [])
    } catch { setTemplates([]) }
  }

  const handleCreate = async () => {
    if (!createEventId) { setError('Please select an event.'); return }
    setCreating(true)
    setError('')
    try {
      const newSurvey = await createSurvey({
        event_id: Number(createEventId),
        template_id: createTemplateId ? Number(createTemplateId) : undefined,
      })
      setShowCreate(false)
      setCreateEventId('')
      setCreateTemplateId('')
      setSelected(newSurvey)
      loadSurveys()
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to create survey.')
    } finally {
      setCreating(false)
    }
  }

  const handleAction = async (action, surveyId) => {
    setActionLoading(action)
    setError('')
    try {
      let result
      if (action === 'activate') result = await activateSurvey(surveyId)
      else if (action === 'close') result = await closeSurvey(surveyId)
      else if (action === 'send') result = await sendSurvey(surveyId)
      else if (action === 'delete') { await deleteSurvey(surveyId); setSelected(null) }

      if (action === 'send' && result?.message) {
        pushToast(result.message, 'success')
      }
      loadSurveys()
      if (result && action !== 'delete') setSelected(result)
    } catch (err) {
      setError(err.response?.data?.error || `Failed to ${action} survey.`)
    } finally {
      setActionLoading('')
    }
  }

  const handleViewResponses = async (surveyId) => {
    try {
      const data = await getSurveyResponses(surveyId)
      setResponsesData(data)
      setShowResponses(true)
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to load responses.')
    }
  }

  const startEditQuestions = (survey) => {
    setEditQuestions(survey.questions.map((q) => ({ ...q })))
    setEditingQuestions(true)
  }

  const handleSaveQuestions = async () => {
    if (!selected) return
    setActionLoading('save')
    try {
      const result = await updateSurvey(selected.id, {
        questions: editQuestions.map((q, i) => ({
          question_text: q.question_text,
          question_type: q.question_type,
          order: i + 1,
          is_required: q.is_required,
          metadata: q.metadata || {},
        })),
      })
      setSelected(result)
      setEditingQuestions(false)
      loadSurveys()
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to save questions.')
    } finally {
      setActionLoading('')
    }
  }

  const handleSaveAsTemplate = async () => {
    const { survey, name } = templateModal
    if (!name.trim()) return
    try {
      await createTemplate({
        title: name.trim(),
        description: survey.description || '',
        is_default: false,
        questions: survey.questions.map((q, i) => ({
          question_text: q.question_text,
          question_type: q.question_type,
          order: i + 1,
          is_required: q.is_required,
          metadata: q.metadata || {},
        })),
      })
      setTemplateModal({ open: false, survey: null, name: '' })
      pushToast('Template saved!', 'success')
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to save template.')
    }
  }

  const copyLink = (url) => {
    navigator.clipboard.writeText(url)
    pushToast('Survey link copied!', 'success')
  }

  // =========================================================================
  return (
    <div>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1rem' }}>
        <h1 style={{ margin: 0 }}>Surveys</h1>
        <button className="btn btn-primary" onClick={() => { setShowCreate(true); loadEvents(); loadTemplates() }}>
          + New Survey
        </button>
      </header>

      {/* Stat Cards */}
      <div className="survey-stats">
        <div className="survey-stat-card">
          <div className="survey-stat-card__value">{stats.total}</div>
          <div className="survey-stat-card__label">Total</div>
        </div>
        <div className="survey-stat-card">
          <div className="survey-stat-card__value">{stats.active}</div>
          <div className="survey-stat-card__label">Active</div>
        </div>
        <div className="survey-stat-card">
          <div className="survey-stat-card__value">{stats.responses}</div>
          <div className="survey-stat-card__label">Responses</div>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {SURVEY_STATUSES.map((s) => (
          <button
            key={s.value}
            onClick={() => setStatusFilter(s.value)}
            className={`survey-chip ${statusFilter === s.value ? 'survey-chip--active' : ''}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="survey-error">{error}</div>}

      {/* Survey List */}
      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {[1, 2, 3].map(i => (
            <div key={i} className="skeleton-pulse" style={{ height: 60, borderRadius: 'var(--radius-lg)' }} />
          ))}
        </div>
      ) : surveys.length === 0 ? (
        <div className="survey-empty">
          <p style={{ margin: 0 }}>No surveys yet. Create one after a Meal Share event!</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {surveys.map((s) => (
            <div
              key={s.id}
              onClick={() => { setSelected(s); setShowResponses(false); setEditingQuestions(false) }}
              className={`survey-list-card ${selected?.id === s.id ? 'survey-list-card--selected' : ''}`}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong>{s.title}</strong>
                  {s.event_info && (
                    <span className="muted" style={{ fontSize: '0.85rem', marginLeft: '0.5rem' }}>
                      {s.event_info.event_date}
                    </span>
                  )}
                </div>
                <span className={`survey-status-badge survey-status-badge--${s.status}`}>
                  {getStatusLabel(s.status)}
                </span>
              </div>
              <div className="muted" style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>
                {s.questions?.length || 0} questions &middot; {s.response_count || 0} responses
                {s.email_send_count > 0 && ` \u00B7 Sent ${s.email_send_count}x`}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Selected Survey Detail */}
      {selected && !showResponses && (
        <div className="survey-detail">
          <h2 style={{ margin: '0 0 0.5rem 0' }}>{selected.title}</h2>
          {selected.description && <p className="muted" style={{ margin: '0 0 1rem 0' }}>{selected.description}</p>}

          {/* Actions */}
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
            {selected.status === 'draft' && (
              <>
                <button className="btn btn-primary" onClick={() => handleAction('activate', selected.id)} disabled={actionLoading === 'activate'}>
                  {actionLoading === 'activate' ? 'Activating\u2026' : 'Activate'}
                </button>
                <button className="btn btn-outline" onClick={() => startEditQuestions(selected)}>Edit Questions</button>
                <button className="btn btn-outline" style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={() => {
                  setConfirmState({ open: true, title: 'Delete Survey', message: 'Delete this draft survey? This cannot be undone.', action: () => handleAction('delete', selected.id) })
                }}>
                  Delete
                </button>
              </>
            )}
            {selected.status === 'active' && (
              <>
                <button className="btn btn-primary" onClick={() => handleAction('send', selected.id)} disabled={actionLoading === 'send'}>
                  {actionLoading === 'send' ? 'Sending\u2026' : 'Send to Attendees'}
                </button>
                <button className="btn btn-outline" onClick={() => copyLink(selected.survey_url)}>Copy Link</button>
                <button className="btn btn-outline" style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={() => handleAction('close', selected.id)}>
                  Close Survey
                </button>
              </>
            )}
            {selected.response_count > 0 && (
              <button className="btn btn-outline" onClick={() => handleViewResponses(selected.id)}>
                View Responses ({selected.response_count})
              </button>
            )}
            <button className="btn btn-outline" onClick={() => setTemplateModal({ open: true, survey: selected, name: selected.title })}>
              Save as Template
            </button>
          </div>

          {/* Survey Link */}
          {selected.status !== 'draft' && (
            <div className="survey-link-box">
              <strong>Survey Link:</strong>{' '}
              <a href={selected.survey_url} target="_blank" rel="noopener noreferrer">{selected.survey_url}</a>
            </div>
          )}

          {/* Questions (read-only) */}
          {!editingQuestions && (
            <div>
              <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem' }}>Questions</h3>
              {selected.questions?.map((q, i) => (
                <div key={q.id} className="survey-q-row">
                  <span className="survey-q-row__num">{i + 1}.</span>
                  <span style={{ flex: 1 }}>{q.question_text}</span>
                  <span className="survey-q-row__type" title={q.question_type}>{QUESTION_TYPE_ICONS[q.question_type] || ''}</span>
                  {q.is_required && <span style={{ color: 'var(--danger)', fontSize: '0.8rem' }}>*</span>}
                </div>
              ))}
            </div>
          )}

          {/* Questions (edit mode) */}
          {editingQuestions && (
            <div>
              <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem' }}>Edit Questions</h3>
              {editQuestions.map((q, i) => (
                <div key={i} className="survey-q-row">
                  <span className="survey-q-row__num">{i + 1}.</span>
                  <input
                    className="input"
                    value={q.question_text}
                    onChange={(e) => {
                      const updated = [...editQuestions]
                      updated[i] = { ...updated[i], question_text: e.target.value }
                      setEditQuestions(updated)
                    }}
                    style={{ flex: 1 }}
                  />
                  <select
                    className="select"
                    value={q.question_type}
                    onChange={(e) => {
                      const updated = [...editQuestions]
                      updated[i] = { ...updated[i], question_type: e.target.value }
                      setEditQuestions(updated)
                    }}
                    style={{ width: 'auto', minWidth: 90 }}
                  >
                    <option value="rating">Rating</option>
                    <option value="text">Text</option>
                    <option value="yes_no">Yes/No</option>
                  </select>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                    <input
                      type="checkbox"
                      checked={q.is_required}
                      onChange={(e) => {
                        const updated = [...editQuestions]
                        updated[i] = { ...updated[i], is_required: e.target.checked }
                        setEditQuestions(updated)
                      }}
                    />
                    Req
                  </label>
                  <button
                    className="btn btn-outline btn-sm"
                    style={{ color: 'var(--danger)', borderColor: 'var(--danger)', padding: '0.2rem 0.5rem' }}
                    onClick={() => setEditQuestions(editQuestions.filter((_, j) => j !== i))}
                  >
                    &times;
                  </button>
                </div>
              ))}
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                <button className="btn btn-outline" onClick={() => setEditQuestions([...editQuestions, { question_text: '', question_type: 'rating', is_required: true, metadata: {} }])}>
                  + Add Question
                </button>
                <button className="btn btn-primary" onClick={handleSaveQuestions} disabled={actionLoading === 'save'}>
                  {actionLoading === 'save' ? 'Saving\u2026' : 'Save'}
                </button>
                <button className="btn btn-outline" onClick={() => setEditingQuestions(false)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Responses View */}
      {showResponses && responsesData && (
        <div className="survey-detail">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h2 style={{ margin: 0 }}>Responses</h2>
            <button className="btn btn-outline btn-sm" onClick={() => setShowResponses(false)}>Back</button>
          </div>

          {/* Aggregate Stats */}
          {responsesData.question_stats && (
            <div style={{ marginBottom: '1.5rem' }}>
              <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem' }}>Summary</h3>
              {responsesData.question_stats.map((stat) => (
                <div key={stat.question_id} className="survey-q-row">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <span>{stat.question_text}</span>
                    <span className="muted" style={{ fontSize: '0.85rem', whiteSpace: 'nowrap', marginLeft: '0.5rem' }}>
                      {stat.question_type === 'rating' && stat.average_rating != null ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                          <StarRating value={stat.average_rating} size={16} halfStars />
                          <span>{stat.average_rating}</span>
                        </span>
                      ) : (
                        `${stat.response_count} response${stat.response_count !== 1 ? 's' : ''}`
                      )}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Individual Responses */}
          <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem' }}>
            Individual Responses ({responsesData.responses?.length || 0})
          </h3>
          {responsesData.responses?.map((resp) => (
            <div key={resp.id} className="survey-list-card" style={{ cursor: 'default', marginBottom: '0.5rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <strong>{resp.customer_name}</strong>
                <span className="muted" style={{ fontSize: '0.8rem' }}>
                  {new Date(resp.submitted_at).toLocaleDateString()}
                </span>
              </div>
              {resp.answers?.map((a) => {
                const q = responsesData.survey?.questions?.find((qq) => qq.id === a.question)
                return (
                  <div key={a.question} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>
                    <span className="muted">{q?.question_text || `Q${a.question}`}: </span>
                    {a.rating_value != null && <StarRating value={a.rating_value} size={14} />}
                    {a.text_value && <span>{a.text_value}</span>}
                    {a.boolean_value != null && <span>{a.boolean_value ? 'Yes' : 'No'}</span>}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}

      {/* Create Survey Modal */}
      {showCreate && (
        <div className="modal-backdrop" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>New Survey</h3>

            <label className="muted" style={{ fontSize: '0.85rem' }}>Event *</label>
            <select className="select" value={createEventId} onChange={(e) => setCreateEventId(e.target.value)}>
              <option value="">Select an event...</option>
              {events.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.meal_name || ev.meal?.name || `Event #${ev.id}`} — {ev.event_date}
                </option>
              ))}
            </select>

            <label className="muted" style={{ fontSize: '0.85rem', marginTop: '0.75rem', display: 'block' }}>Template (optional)</label>
            <select className="select" value={createTemplateId} onChange={(e) => setCreateTemplateId(e.target.value)}>
              <option value="">Auto-generate default</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title} {t.is_default ? '(default)' : ''}
                </option>
              ))}
            </select>

            {error && <div className="survey-error" style={{ marginTop: '0.75rem' }}>{error}</div>}

            <div style={{ marginTop: '1.25rem', display: 'flex', justifyContent: 'flex-end', gap: '.5rem' }}>
              <button className="btn btn-outline" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={creating}>
                {creating ? 'Creating\u2026' : 'Create Survey'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Template Name Modal */}
      {templateModal.open && (
        <div className="modal-backdrop" onClick={() => setTemplateModal({ open: false, survey: null, name: '' })}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Save as Template</h3>
            <label className="muted" style={{ fontSize: '0.85rem' }}>Template name</label>
            <input
              className="input"
              value={templateModal.name}
              onChange={(e) => setTemplateModal(prev => ({ ...prev, name: e.target.value }))}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSaveAsTemplate() }}
              autoFocus
            />
            <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'flex-end', gap: '.5rem' }}>
              <button className="btn btn-outline" onClick={() => setTemplateModal({ open: false, survey: null, name: '' })}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSaveAsTemplate}>Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        confirmLabel="Delete"
        onConfirm={() => { confirmState.action?.(); setConfirmState({ open: false, title: '', message: '', action: null }) }}
        onCancel={() => setConfirmState({ open: false, title: '', message: '', action: null })}
      />

      {/* Toasts */}
      <ToastOverlay toasts={toasts} />
    </div>
  )
}

function ToastOverlay({ toasts }) {
  if (!toasts || toasts.length === 0) return null
  if (typeof document === 'undefined' || !document.body) return null
  return createPortal(
    <div className="toast-container" role="status" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.tone} ${t.closing ? 'closing' : ''}`}>{t.text}</div>
      ))}
    </div>,
    document.body
  )
}
