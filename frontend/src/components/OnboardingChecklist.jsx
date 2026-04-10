/**
 * OnboardingChecklist Component
 * 
 * Guides new chefs through the activation process with a clear checklist.
 * Shows progress, highlights next action, and celebrates completion.
 */

import React, { useState, useEffect, useMemo } from 'react'

// Step configuration
const STEPS = [
  {
    id: 'profile',
    title: 'Complete Your Profile',
    description: 'Add bio, experience, and a profile photo',
    tab: 'profile',
    icon: '👤',
    actionLabel: 'Edit Profile'
  },
  {
    id: 'meeting',
    title: 'Schedule Verification Call',
    description: 'Book a quick call with our team',
    tab: null,
    icon: '📅',
    actionLabel: 'Schedule Call',
    isCalendly: true
  },
  {
    id: 'kitchen',
    title: 'Build Your Kitchen',
    description: 'Create at least one meal to offer',
    tab: 'kitchen',
    icon: '🍳',
    actionLabel: 'Create Meal'
  },
  {
    id: 'services',
    title: 'Create a Service',
    description: 'Define an offering with pricing tiers',
    tab: 'services',
    icon: '📋',
    actionLabel: 'Add Service'
  },
  {
    id: 'photos',
    title: 'Add Photos',
    description: 'Upload at least 3 gallery photos',
    tab: 'photos',
    icon: '📸',
    actionLabel: 'Upload Photos'
  },
  {
    id: 'payouts',
    title: 'Set Up Payouts',
    description: 'Connect Stripe to receive payments',
    tab: 'dashboard',
    icon: '💳',
    actionLabel: 'Connect Stripe',
    isStripe: true
  }
]

const STORAGE_KEY = 'chef_onboarding_dismissed'

export default function OnboardingChecklist({
  completionState = {},
  onNavigate,
  onStartStripeOnboarding,
  onOpenCalendly,
  meetingConfig = {},
  isLive = false,
  onGoLive,
  goingLive = false,
  className = ''
}) {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })
  const [collapsed, setCollapsed] = useState(false)
  const [celebrateShown, setCelebrateShown] = useState(false)

  // Compute step completion, filtering out meeting step if not enabled
  const steps = useMemo(() => {
    return STEPS
      .filter(step => {
        // Filter out meeting step if feature is disabled
        if (step.isCalendly && !meetingConfig.feature_enabled) {
          return false
        }
        return true
      })
      .map(step => ({
        ...step,
        complete: Boolean(completionState[step.id])
      }))
  }, [completionState, meetingConfig.feature_enabled])

  const completedCount = steps.filter(s => s.complete).length
  const totalCount = steps.length
  const progressPercent = Math.round((completedCount / totalCount) * 100)
  const isComplete = completedCount === totalCount
  const canGoLive = Boolean(completionState.payouts)

  // Find next incomplete step
  const nextStep = steps.find(s => !s.complete)

  // Show celebration when just completed
  useEffect(() => {
    if (isComplete && !celebrateShown) {
      setCelebrateShown(true)
    }
  }, [isComplete, celebrateShown])

  // Persist dismissal
  const handleDismiss = () => {
    setDismissed(true)
    try {
      localStorage.setItem(STORAGE_KEY, 'true')
    } catch {}
  }

  const handleReset = () => {
    setDismissed(false)
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {}
  }

  const handleStepClick = (step) => {
    if (step.isStripe && onStartStripeOnboarding) {
      onStartStripeOnboarding()
    } else if (step.isCalendly && onOpenCalendly) {
      onOpenCalendly()
    } else if (onNavigate && step.tab) {
      onNavigate(step.tab)
    }
  }

  // Don't show if dismissed (unless incomplete or not yet live)
  if (dismissed && isComplete && isLive) {
    return null
  }

  // Dismissed but can go live — show just the Go Live CTA
  if (dismissed && !isLive && canGoLive) {
    return (
      <div className={`onboarding-complete go-live ${className}`}>
        <div className="complete-header">
          <div className="complete-icon">🚀</div>
          <div className="complete-content">
            <h3>Ready to Go Live!</h3>
            <p>Make your profile visible to customers.</p>
          </div>
        </div>
        <div className="complete-actions">
          <button
            className="btn btn-primary"
            onClick={onGoLive}
            disabled={goingLive}
          >
            {goingLive ? 'Going Live...' : 'Go Live Now'}
          </button>
        </div>
        <style>{completeStyles}</style>
      </div>
    )
  }

  // Collapsed summary bar for returning users
  if (collapsed && !isComplete) {
    return (
      <div className={`onboarding-collapsed ${className}`}>
        <div className="collapsed-content">
          <div className="collapsed-progress">
            <div className="progress-ring">
              <svg viewBox="0 0 36 36">
                <path
                  className="progress-ring-bg"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <path
                  className="progress-ring-fill"
                  strokeDasharray={`${progressPercent}, 100`}
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              </svg>
              <span className="progress-text">{completedCount}/{totalCount}</span>
            </div>
          </div>
          <div className="collapsed-info">
            <span className="collapsed-title">Setup Progress</span>
            {nextStep && (
              <span className="collapsed-next">Next: {nextStep.title}</span>
            )}
          </div>
        </div>
        <div className="collapsed-actions">
          {canGoLive && !isLive && (
            <button
              className="btn btn-sm btn-primary"
              onClick={onGoLive}
              disabled={goingLive}
            >
              {goingLive ? 'Going Live...' : 'Go Live Now'}
            </button>
          )}
          <button
            className="btn btn-sm btn-outline"
            onClick={() => setCollapsed(false)}
          >
            Continue Setup
          </button>
        </div>
        <style>{collapsedStyles}</style>
      </div>
    )
  }

  // Setup complete but not live yet - show Go Live CTA
  if (isComplete && !isLive) {
    return (
      <div className={`onboarding-complete go-live ${className}`}>
        <div className="complete-header">
          <div className="complete-icon">🎉</div>
          <div className="complete-content">
            <h3>You're Ready to Go Live!</h3>
            <p>Your chef profile is fully set up. Click below to make your profile visible to customers.</p>
          </div>
        </div>
        <div className="complete-actions">
          <button
            className="btn btn-primary"
            onClick={onGoLive}
            disabled={goingLive}
          >
            {goingLive ? 'Going Live...' : 'Start Cooking!'}
          </button>
        </div>
        <style>{completeStyles}</style>
      </div>
    )
  }

  // Already live - celebration state
  if (isComplete && isLive) {
    return (
      <div className={`onboarding-complete ${className}`}>
        <div className="complete-header">
          <div className="complete-icon">✅</div>
          <div className="complete-content">
            <h3>You're Live!</h3>
            <p>Customers can now discover and book your services.</p>
          </div>
        </div>
        <div className="complete-actions">
          <button
            className="btn btn-outline btn-sm"
            onClick={handleDismiss}
          >
            Dismiss
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => onNavigate && onNavigate('dashboard')}
          >
            View Dashboard
          </button>
        </div>
        <style>{completeStyles}</style>
      </div>
    )
  }

  // Main checklist view
  return (
    <div className={`onboarding-checklist ${className}`}>
      <div className="checklist-header">
        <div className="header-title">
          <h3>Get Started</h3>
          <p className="muted">Complete these steps to activate your chef profile</p>
        </div>
        <div className="header-actions">
          <button 
            className="collapse-btn"
            onClick={() => setCollapsed(true)}
            aria-label="Collapse checklist"
            title="Minimize"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 15l-6-6-6 6"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="checklist-progress">
        <div className="progress-bar">
          <div 
            className="progress-fill" 
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <div className="progress-label">
          <span>{completedCount} of {totalCount} complete</span>
          <span className="progress-percent">{progressPercent}%</span>
        </div>
      </div>

      {/* Steps list */}
      <div className="checklist-steps">
        {steps.map((step, index) => {
          const isNext = nextStep?.id === step.id
          return (
            <div 
              key={step.id}
              className={`checklist-step ${step.complete ? 'complete' : ''} ${isNext ? 'next' : ''}`}
            >
              <div className="step-indicator">
                {step.complete ? (
                  <div className="step-check">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <path d="M20 6L9 17l-5-5"/>
                    </svg>
                  </div>
                ) : (
                  <div className="step-number">{index + 1}</div>
                )}
              </div>
              <div className="step-content">
                <div className="step-header">
                  <span className="step-icon">{step.icon}</span>
                  <span className="step-title">{step.title}</span>
                </div>
                <p className="step-description">{step.description}</p>
              </div>
              <div className="step-action">
                {!step.complete && (
                  <button
                    className={`btn btn-sm ${isNext ? 'btn-primary' : 'btn-outline'}`}
                    onClick={() => handleStepClick(step)}
                  >
                    {step.actionLabel}
                  </button>
                )}
                {step.complete && (
                  <span className="step-done">Done</span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Show Go Live button once payouts are active, even if other steps remain */}
      {canGoLive && !isLive && (
        <div className="checklist-go-live">
          <button
            className="btn btn-primary"
            onClick={onGoLive}
            disabled={goingLive}
          >
            {goingLive ? 'Going Live...' : 'Go Live Now'}
          </button>
          {!isComplete && (
            <p className="go-live-hint muted">You can finish the remaining steps after going live.</p>
          )}
        </div>
      )}

      <style>{mainStyles}</style>
    </div>
  )
}

const mainStyles = `
  .onboarding-checklist {
    background: var(--surface-2);
    border: 1.5px solid var(--primary);
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
  }

  .checklist-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }

  .header-title h3 {
    margin: 0 0 0.25rem 0;
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--text);
  }

  .header-title .muted {
    margin: 0;
    font-size: 0.9rem;
    color: var(--muted);
  }

  .collapse-btn {
    background: none;
    border: none;
    padding: 0.35rem;
    cursor: pointer;
    color: var(--muted);
    border-radius: 6px;
    transition: all 0.15s ease;
  }

  .collapse-btn:hover {
    background: var(--surface);
    color: var(--text);
  }

  .checklist-progress {
    margin-bottom: 1.25rem;
  }

  .progress-bar {
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), var(--primary-700));
    border-radius: 4px;
    transition: width 0.4s ease;
  }

  .progress-label {
    display: flex;
    justify-content: space-between;
    margin-top: 0.5rem;
    font-size: 0.8rem;
    color: var(--muted);
  }

  .progress-percent {
    font-weight: 600;
    color: var(--primary);
  }

  .checklist-go-live {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    text-align: center;
  }

  .go-live-hint {
    margin-top: 0.5rem;
    font-size: 0.85rem;
  }

  .checklist-steps {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .checklist-step {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    transition: all 0.2s ease;
    color: var(--text);
  }

  .checklist-step.complete {
    background: var(--success-bg);
    border-color: var(--success);
    opacity: 0.85;
  }

  .checklist-step.next {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px var(--success-bg);
  }

  .step-indicator {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .step-number {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--surface-2);
    color: var(--muted);
    font-size: 0.85rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .checklist-step.next .step-number {
    background: var(--primary);
    color: white;
  }

  .step-check {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--primary);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: checkPop 0.3s ease;
  }

  @keyframes checkPop {
    0% { transform: scale(0); }
    50% { transform: scale(1.2); }
    100% { transform: scale(1); }
  }

  .step-content {
    flex: 1;
    min-width: 0;
  }

  .step-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.15rem;
  }

  .step-icon {
    font-size: 1rem;
  }

  .step-title {
    font-weight: 600;
    font-size: 0.95rem;
    color: var(--text);
  }

  .checklist-step.complete .step-title {
    color: var(--muted);
  }

  .step-description {
    margin: 0;
    font-size: 0.8rem;
    color: var(--muted);
    line-height: 1.4;
  }

  .step-action {
    flex-shrink: 0;
  }

  .step-done {
    font-size: 0.8rem;
    color: var(--success);
    font-weight: 500;
  }

  @media (max-width: 640px) {
    .onboarding-checklist {
      padding: 1rem;
    }

    .checklist-step {
      flex-wrap: wrap;
      padding: 0.75rem;
    }

    .step-content {
      flex: 1 1 calc(100% - 40px);
    }

    .step-action {
      flex: 1 1 100%;
      margin-top: 0.5rem;
      margin-left: 36px;
    }
  }
`

const collapsedStyles = `
  .onboarding-collapsed {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    background: var(--surface-2);
    border: 1.5px solid var(--primary);
    border-radius: 12px;
    padding: 0.75rem 1rem;
    margin-bottom: 1.5rem;
  }

  .collapsed-content {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .progress-ring {
    width: 40px;
    height: 40px;
    position: relative;
  }

  .progress-ring svg {
    width: 100%;
    height: 100%;
    transform: rotate(-90deg);
  }

  .progress-ring-bg {
    fill: none;
    stroke: var(--border);
    stroke-width: 3;
  }

  .progress-ring-fill {
    fill: none;
    stroke: var(--primary);
    stroke-width: 3;
    stroke-linecap: round;
    transition: stroke-dasharray 0.4s ease;
  }

  .progress-text {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--text);
  }

  .collapsed-info {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .collapsed-title {
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--text);
  }

  .collapsed-next {
    font-size: 0.8rem;
    color: var(--muted);
  }

  .collapsed-actions {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }

  @media (max-width: 480px) {
    .onboarding-collapsed {
      flex-direction: column;
      align-items: stretch;
      gap: 0.75rem;
    }

    .onboarding-collapsed .btn {
      width: 100%;
    }
  }
`

const completeStyles = `
  .onboarding-complete {
    background: var(--success-bg);
    border: 1.5px solid var(--success);
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
    animation: celebrateFade 0.5s ease;
  }

  .onboarding-complete.go-live {
    background: var(--surface-2);
    border-color: var(--primary);
  }

  @keyframes celebrateFade {
    0% { opacity: 0; transform: translateY(-10px); }
    100% { opacity: 1; transform: translateY(0); }
  }

  .complete-header {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .complete-icon {
    font-size: 2.5rem;
    animation: bounce 0.6s ease;
  }

  @keyframes bounce {
    0%, 100% { transform: translateY(0); }
    40% { transform: translateY(-8px); }
    60% { transform: translateY(-4px); }
  }

  .complete-content h3 {
    margin: 0 0 0.35rem 0;
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--text);
  }

  .complete-content p {
    margin: 0;
    font-size: 0.9rem;
    color: var(--muted);
    line-height: 1.5;
  }

  .complete-actions {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  @media (max-width: 480px) {
    .onboarding-complete {
      padding: 1rem;
    }

    .complete-header {
      flex-direction: column;
      align-items: center;
      text-align: center;
    }

    .complete-actions {
      justify-content: center;
    }
  }
`




