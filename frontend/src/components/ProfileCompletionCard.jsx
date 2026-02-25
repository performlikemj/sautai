import React, { useMemo } from 'react'
import { 
  validateChefProfile, 
  getStatusMessage, 
  getRecommendations,
  isStripeAuditReady,
  PROFILE_STATUS 
} from '../utils/chefProfileValidator.js'

/**
 * ProfileCompletionCard
 * 
 * Displays chef profile completion status and recommendations.
 * Shows progress toward meeting minimum requirements and Stripe audit readiness.
 * 
 * Usage:
 * <ProfileCompletionCard chef={chefProfile} />
 */
export default function ProfileCompletionCard({ chef }) {
  const validation = useMemo(() => validateChefProfile(chef), [chef])
  const recommendations = useMemo(() => getRecommendations(validation), [validation])
  const stripeReady = useMemo(() => isStripeAuditReady(chef), [chef])
  
  if (!validation) return null

  const { status, score, isComplete } = validation
  const statusMessage = getStatusMessage(validation)

  // Color scheme based on status
  const getStatusColor = () => {
    if (status === PROFILE_STATUS.EXCELLENT) return 'var(--success)'
    if (status === PROFILE_STATUS.READY) return 'var(--primary)'
    if (status === PROFILE_STATUS.INCOMPLETE) return 'var(--warning)'
    return 'var(--danger)'
  }

  const statusColor = getStatusColor()

  return (
    <div className="card profile-completion-card">
      <div className="profile-completion-header">
        <h3 style={{margin:0}}>
          <i className="fa-solid fa-clipboard-check" style={{marginRight:'.5rem', color:statusColor}}></i>
          Profile Completion
        </h3>
        {isComplete && (
          <span className="badge success" style={{background:'var(--success-bg)', color:'var(--success)', padding:'.25rem .75rem', borderRadius:'6px', fontSize:'.85rem', fontWeight:600}}>
            Ready
          </span>
        )}
      </div>

      {/* Progress Bar */}
      <div className="profile-progress-container" style={{margin:'1rem 0'}}>
        <div className="profile-progress-bar" style={{
          width:'100%',
          height:'24px',
          background:'var(--surface-2)',
          border:'1px solid var(--border)',
          borderRadius:'8px',
          overflow:'hidden',
          position:'relative'
        }}>
          <div 
            className="profile-progress-fill" 
            style={{
              width:`${score}%`,
              height:'100%',
              background: `linear-gradient(90deg, ${statusColor} 0%, ${statusColor}dd 100%)`,
              transition:'width 0.5s ease',
              display:'flex',
              alignItems:'center',
              justifyContent:'flex-end',
              paddingRight:'.5rem',
              color:'white',
              fontSize:'.85rem',
              textShadow:'0 1px 2px rgba(0,0,0,0.3)',
              fontWeight:700
            }}
          >
            {score}%
          </div>
        </div>
        <div className="profile-progress-label" style={{marginTop:'.5rem', fontSize:'.9rem', color:'var(--muted)'}}>
          {statusMessage}
        </div>
      </div>

      {/* Stripe Audit Status */}
      {isComplete && (
        <div className="stripe-audit-status" style={{
          marginTop:'1rem',
          padding:'.75rem',
          background: stripeReady ? 'rgba(124,144,112,0.1)' : 'rgba(245,158,11,0.1)',
          border: `1px solid ${stripeReady ? 'rgba(124,144,112,0.3)' : 'rgba(245,158,11,0.3)'}`,
          borderRadius:'8px',
          display:'flex',
          alignItems:'center',
          gap:'.75rem'
        }}>
          <i 
            className={`fa-solid ${stripeReady ? 'fa-check-circle' : 'fa-info-circle'}`}
            style={{fontSize:'1.5rem', color: stripeReady ? 'var(--success)' : 'var(--warning)'}}
          ></i>
          <div>
            <div style={{fontWeight:600, fontSize:'.95rem', marginBottom:'.25rem'}}>
              {stripeReady ? '✅ Stripe Audit Ready' : '⚠️ Stripe Audit Recommendations'}
            </div>
            <div style={{fontSize:'.85rem', color:'var(--muted)'}}>
              {stripeReady 
                ? 'Your profile meets all requirements for Stripe payment processing approval.'
                : 'Add 5+ gallery photos and 2+ services to maximize Stripe approval chances.'
              }
            </div>
          </div>
        </div>
      )}

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <div className="profile-recommendations" style={{marginTop:'1rem'}}>
          <h4 style={{fontSize:'.95rem', marginBottom:'.75rem', color:'var(--text)'}}>
            <i className="fa-solid fa-list-check" style={{marginRight:'.5rem'}}></i>
            To Complete Your Profile:
          </h4>
          <div style={{display:'flex', flexDirection:'column', gap:'.5rem'}}>
            {recommendations.map(rec => (
              <div 
                key={rec.key} 
                className="recommendation-item"
                style={{
                  display:'flex',
                  gap:'.75rem',
                  padding:'.65rem',
                  background:'var(--surface-2)',
                  border:'1px solid var(--border)',
                  borderRadius:'6px',
                  fontSize:'.9rem'
                }}
              >
                <i className="fa-solid fa-circle" style={{fontSize:'.5rem', marginTop:'.5rem', color:'var(--primary)', flexShrink:0}}></i>
                <div style={{flex:1}}>
                  <div style={{fontWeight:600, marginBottom:'.25rem'}}>{rec.label}</div>
                  <div style={{color:'var(--muted)', fontSize:'.85rem'}}>{rec.description}</div>
                  {rec.current !== undefined && rec.required && (
                    <div style={{marginTop:'.35rem', fontSize:'.8rem', color:'var(--muted)'}}>
                      Current: {rec.current} / Required: {rec.required}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Success State */}
      {isComplete && recommendations.length === 0 && (
        <div style={{marginTop:'1rem', textAlign:'center', padding:'1rem', background:'var(--surface-2)', borderRadius:'8px'}}>
          <i className="fa-solid fa-check-circle" style={{fontSize:'2.5rem', color:'var(--success)', marginBottom:'.5rem'}}></i>
          <div style={{fontWeight:600, fontSize:'1.05rem', marginBottom:'.35rem'}}>Profile Complete!</div>
          <div style={{fontSize:'.9rem', color:'var(--muted)'}}>
            Your profile is ready to accept bookings and looks professional for Stripe compliance.
          </div>
        </div>
      )}
    </div>
  )
}



