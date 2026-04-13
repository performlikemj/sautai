import React, { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function ChefStatus() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [wasApproved, setWasApproved] = useState(false)
  const prevPending = useRef(false)

  const fetchStatus = () => {
    api.get('/chefs/api/check-chef-status/')
      .then(res => {
        const data = res.data
        // Detect transition from pending to approved
        if (prevPending.current && data.is_chef) {
          setWasApproved(true)
        }
        prevPending.current = data.has_pending_request
        setStatus(data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  // Initial fetch + polling every 30 seconds
  useEffect(() => {
    fetchStatus()
    const timer = setTimeout(function poll() {
      fetchStatus()
      setTimeout(poll, 30000)
    }, 30000)
    return () => clearTimeout(timer)
  }, [])

  if (loading) return <div style={{ maxWidth: 520, margin: '2rem auto', textAlign: 'center' }}>Loading...</div>

  // Not applied yet
  if (!status?.is_chef && !status?.has_pending_request) {
    return (
      <div style={{ maxWidth: 520, margin: '2rem auto' }}>
        <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
          <h2>Become a Personal Chef</h2>
          <p className="muted">You haven't submitted a chef application yet.</p>
          <div style={{ marginTop: '1rem' }}>
            <Link to="/profile?applyChef=1" className="btn btn-primary">Apply Now</Link>
          </div>
        </div>
      </div>
    )
  }

  // Approved (chef)
  if (status?.is_chef) {
    return (
      <div style={{ maxWidth: 520, margin: '2rem auto' }}>
        <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
          {wasApproved && <div style={{ fontSize: '3rem', marginBottom: '.5rem' }}>&#127881;</div>}
          <h2>{wasApproved ? 'Congratulations!' : 'You\'re Approved'}</h2>
          <p className="muted">
            {wasApproved
              ? 'Your chef application has just been approved! Time to set up your profile and start serving.'
              : 'Your chef profile is ready. Head to your dashboard to manage your business.'}
          </p>
          <div style={{ marginTop: '1rem' }}>
            <Link to={status.next_step || '/chefs/dashboard'} className="btn btn-primary">Go to Chef Dashboard</Link>
          </div>
        </div>
      </div>
    )
  }

  // Pending review
  return (
    <div style={{ maxWidth: 520, margin: '2rem auto' }}>
      <div className="card" style={{ padding: '2rem' }}>
        <h2>Application Under Review</h2>
        <p className="muted">
          Your chef application is pending approval.
          {status.submitted_at && (
            <> Submitted on {new Date(status.submitted_at).toLocaleDateString()}.</>
          )}
        </p>
        {status.experience_preview && (
          <div style={{ marginTop: '1rem', padding: '.75rem', background: 'var(--surface-2, #f5f5f5)', borderRadius: '8px' }}>
            <div className="muted" style={{ fontSize: '.85em', marginBottom: '.25rem' }}>Your experience</div>
            <div>{status.experience_preview}{status.experience_preview.length >= 100 ? '...' : ''}</div>
          </div>
        )}
        <p className="muted" style={{ marginTop: '1rem' }}>
          We review applications promptly. This page checks for updates automatically.
        </p>
        <div style={{ marginTop: '1rem' }}>
          <Link to="/profile" className="btn btn-outline">Back to Profile</Link>
        </div>
      </div>
    </div>
  )
}
