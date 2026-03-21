import React, { useState, useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import StarRating from '../components/StarRating.jsx'
import { getPublicSurvey, submitPublicSurvey } from '../api/surveyClient.js'

export default function PublicSurvey() {
  const { token } = useParams()
  const [survey, setSurvey] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [answers, setAnswers] = useState({})
  const [respondentEmail, setRespondentEmail] = useState('')
  const [respondentName, setRespondentName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await getPublicSurvey(token)
        setSurvey(data)
        const initial = {}
        data.questions.forEach((q) => {
          if (q.question_type === 'rating') initial[q.id] = null
          else if (q.question_type === 'text') initial[q.id] = ''
          else if (q.question_type === 'yes_no') initial[q.id] = null
        })
        setAnswers(initial)
      } catch (err) {
        setError(err.response?.data?.error || 'Failed to load survey.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [token])

  const progress = useMemo(() => {
    if (!survey?.questions?.length) return 0
    const answered = survey.questions.filter(
      (q) => answers[q.id] !== null && answers[q.id] !== ''
    ).length
    return Math.round((answered / survey.questions.length) * 100)
  }, [answers, survey])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const missing = survey.questions.filter(
      (q) => q.is_required && (answers[q.id] === null || answers[q.id] === '')
    )
    if (missing.length > 0) {
      setError('Please answer all required questions.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const formattedAnswers = survey.questions.map((q) => {
        const answer = { question_id: q.id }
        if (q.question_type === 'rating') answer.rating_value = answers[q.id]
        else if (q.question_type === 'text') answer.text_value = answers[q.id]
        else if (q.question_type === 'yes_no') answer.boolean_value = answers[q.id]
        return answer
      })
      await submitPublicSurvey(token, {
        respondent_email: respondentEmail,
        respondent_name: respondentName,
        answers: formattedAnswers,
      })
      setSubmitted(true)
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to submit. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  /* ── Loading ── */
  if (loading) {
    return (
      <div className="page-survey">
        <div className="survey-card-wrap">
          <div className="survey-body survey-body--full" style={{ padding: '2.5rem 2rem' }}>
            <div className="skeleton-pulse" style={{ height: '1.4rem', width: '65%', marginBottom: '1rem' }} />
            <div className="skeleton-pulse" style={{ height: '1rem', width: '45%', marginBottom: '2rem' }} />
            <div className="skeleton-pulse" style={{ height: '3rem', marginBottom: '1rem' }} />
            <div className="skeleton-pulse" style={{ height: '3rem', marginBottom: '1rem' }} />
            <div className="skeleton-pulse" style={{ height: '3rem', width: '80%' }} />
          </div>
        </div>
      </div>
    )
  }

  /* ── Error (no survey) ── */
  if (!survey && error) {
    return (
      <div className="page-survey">
        <div className="survey-card-wrap">
          <div className="survey-body survey-body--full" style={{ textAlign: 'center', padding: '3rem 2rem' }}>
            <h2 style={{ fontFamily: "'Fraunces', Georgia, serif", margin: '0 0 0.5rem' }}>Survey Unavailable</h2>
            <p className="muted">{error}</p>
          </div>
        </div>
      </div>
    )
  }

  /* ── Success ── */
  if (submitted) {
    return (
      <div className="page-survey">
        <div className="survey-card-wrap">
          <div className="survey-body survey-body--full">
            <div className="survey-success">
              <svg className="survey-success__icon" viewBox="0 0 64 64" fill="none">
                <circle cx="32" cy="32" r="30" stroke="var(--primary)" strokeWidth="3" fill="var(--primary-alpha-08, rgba(124,144,112,0.08))" />
                <path d="M20 33l8 8 16-18" stroke="var(--primary)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
              </svg>
              <h2 className="survey-success__title">Thank You!</h2>
              <p className="survey-success__message">
                Your feedback has been submitted.{survey.chef_name ? ` ${survey.chef_name} appreciates your input!` : ''}
              </p>
            </div>
            <p className="survey-footer">Powered by <strong>sautai</strong></p>
          </div>
        </div>
      </div>
    )
  }

  /* ── Survey Form ── */
  return (
    <div className="page-survey">
      <div className="survey-card-wrap">
        {/* Hero */}
        <div className="survey-hero">
          <h2 className="survey-hero__title">{survey.title}</h2>
          {survey.chef_name && (
            <p className="survey-hero__sub">From <strong>{survey.chef_name}</strong></p>
          )}
          {survey.event_info && (
            <p className="survey-hero__sub">
              {survey.event_info.meal_name}&ensp;&middot;&ensp;{survey.event_info.event_date}
            </p>
          )}
          {survey.description && (
            <p className="survey-hero__sub" style={{ marginTop: '0.5rem', opacity: 0.85 }}>{survey.description}</p>
          )}
        </div>

        {/* Body */}
        <div className="survey-body">
          {/* Progress bar */}
          <div className="survey-progress">
            <div className="survey-progress__fill" style={{ width: `${progress}%` }} />
          </div>

          {error && <div className="survey-error">{error}</div>}

          <form onSubmit={handleSubmit}>
            {/* Respondent info */}
            <div className="survey-respondent-fields">
              <div>
                <label>Your Name <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
                <input
                  className="input"
                  type="text"
                  value={respondentName}
                  onChange={(e) => setRespondentName(e.target.value)}
                  placeholder="Jane Doe"
                />
              </div>
              <div>
                <label>Your Email <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
                <input
                  className="input"
                  type="email"
                  value={respondentEmail}
                  onChange={(e) => setRespondentEmail(e.target.value)}
                  placeholder="jane@example.com"
                />
              </div>
            </div>

            <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '1.25rem 0 1.5rem' }} />

            {/* Questions */}
            {survey.questions.map((q, i) => (
              <div
                key={q.id}
                className="survey-question"
                style={i >= 10 ? { animationDelay: `${i * 0.04}s` } : undefined}
              >
                <label className="survey-question__label">
                  {q.question_text}
                  {q.is_required && <span className="survey-question__required"> *</span>}
                </label>

                {q.question_type === 'rating' && (
                  <StarRating
                    value={answers[q.id] || 0}
                    onChange={(val) => setAnswers((prev) => ({ ...prev, [q.id]: val }))}
                    size={32}
                  />
                )}

                {q.question_type === 'text' && (
                  <textarea
                    className="textarea"
                    value={answers[q.id] || ''}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                    rows={3}
                    placeholder="Your thoughts..."
                  />
                )}

                {q.question_type === 'yes_no' && (
                  <div className="survey-toggle-group">
                    <button
                      type="button"
                      className={`survey-toggle ${answers[q.id] === true ? 'survey-toggle--active' : ''}`}
                      onClick={() => setAnswers((prev) => ({ ...prev, [q.id]: true }))}
                    >
                      Yes
                    </button>
                    <button
                      type="button"
                      className={`survey-toggle ${answers[q.id] === false ? 'survey-toggle--active' : ''}`}
                      onClick={() => setAnswers((prev) => ({ ...prev, [q.id]: false }))}
                    >
                      No
                    </button>
                  </div>
                )}
              </div>
            ))}

            <button type="submit" disabled={submitting} className="btn btn-primary survey-submit">
              {submitting ? 'Submitting...' : 'Submit Feedback'}
            </button>
          </form>

          <p className="survey-footer">Powered by <strong>sautai</strong></p>
        </div>
      </div>
    </div>
  )
}
