import React, { useState } from 'react'
import { api, buildErrorMessage } from '../api'

export default function MehkoComplaintModal({ isOpen, onClose, chef, authUser }) {
  const [complaintText, setComplaintText] = useState('')
  const [incidentDate, setIncidentDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  if (!isOpen) return null

  const enforcementAgency = chef?.enforcement_agency || null
  const charCount = complaintText.length
  const isValid = charCount >= 20 && charCount <= 5000

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (!authUser) return
    if (!isValid) {
      setError('Please provide at least 20 characters describing your concern.')
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        chef_id: chef?.id,
        complaint_text: complaintText.trim()
      }
      if (incidentDate) {
        payload.incident_date = incidentDate
      }

      await api.post('/chefs/api/mehko/complaints/', payload)
      setSuccess(true)
    } catch (err) {
      let message = 'Unable to submit your concern. Please try again.'
      if (err?.response) {
        message = buildErrorMessage(err.response.data, message, err.response.status)
      } else if (err?.message) {
        message = err.message
      }
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    setComplaintText('')
    setIncidentDate('')
    setError('')
    setSuccess(false)
    onClose()
  }

  return (
    <>
      <div className="modal-overlay" onClick={handleClose} />
      <div className="modal-container mehko-complaint-modal">
        <div className="modal-header">
          <h2 className="modal-title">
            <i className="fa-solid fa-file-pen" style={{ marginRight: '.5rem' }}></i>
            File a Food Safety Concern
          </h2>
          <button className="modal-close" onClick={handleClose} aria-label="Close">
            <i className="fa-solid fa-times"></i>
          </button>
        </div>

        <div className="modal-body">
          {!authUser ? (
            <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
              <i className="fa-solid fa-lock" style={{ fontSize: '2rem', color: 'var(--muted)', marginBottom: '1rem', display: 'block' }}></i>
              <p>Please <a href={`/login?next=${encodeURIComponent(typeof window !== 'undefined' ? window.location.pathname : '/')}`}>sign in</a> to file a food safety concern.</p>
            </div>
          ) : success ? (
            <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
              <i className="fa-solid fa-check-circle" style={{ fontSize: '3rem', color: 'var(--primary)', marginBottom: '1rem', display: 'block' }}></i>
              <h3>Concern Submitted</h3>
              <p className="muted" style={{ marginTop: '.5rem' }}>
                Your food safety concern has been recorded and will be reviewed.
              </p>
              {enforcementAgency && (
                <p className="muted" style={{ marginTop: '1rem', fontSize: '0.88rem' }}>
                  You may also contact the enforcement agency directly: <strong>{enforcementAgency}</strong>
                </p>
              )}
              <button className="btn btn-primary" onClick={handleClose} style={{ marginTop: '1.5rem' }}>
                Close
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
              {enforcementAgency && (
                <div className="mehko-enforcement-info">
                  <i className="fa-solid fa-building-columns"></i>
                  <div>
                    <strong>Enforcement Agency:</strong> {enforcementAgency}
                    <br />
                    <span className="muted" style={{ fontSize: '0.82rem' }}>
                      You can also report concerns directly to this agency.
                    </span>
                  </div>
                </div>
              )}

              <div className="form-section">
                <label className="label">Describe your concern *</label>
                <textarea
                  className="textarea"
                  rows={5}
                  value={complaintText}
                  onChange={e => setComplaintText(e.target.value)}
                  placeholder="Please describe the food safety issue you experienced..."
                  maxLength={5000}
                  required
                />
                <div className="mehko-char-count">
                  {charCount} / 5,000 characters {charCount > 0 && charCount < 20 && '(minimum 20)'}
                </div>
              </div>

              <div className="form-section">
                <label className="label">Date of incident (optional)</label>
                <input
                  type="date"
                  className="input"
                  value={incidentDate}
                  onChange={e => setIncidentDate(e.target.value)}
                  max={new Date().toISOString().split('T')[0]}
                />
              </div>

              {error && (
                <div className="form-error" role="alert">
                  <i className="fa-solid fa-exclamation-circle"></i>
                  {error}
                </div>
              )}

              <div className="form-actions">
                <button
                  type="submit"
                  className="btn btn-primary btn-lg"
                  disabled={submitting || !isValid}
                  style={{ width: '100%' }}
                >
                  {submitting ? (
                    <>
                      <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2, marginRight: '.5rem' }}></div>
                      Submitting...
                    </>
                  ) : (
                    <>
                      <i className="fa-solid fa-paper-plane" style={{ marginRight: '.5rem' }}></i>
                      Submit Concern
                    </>
                  )}
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={handleClose}
                  disabled={submitting}
                  style={{ width: '100%' }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </>
  )
}
