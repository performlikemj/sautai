/**
 * OnboardingWizard Component
 *
 * Multi-step onboarding wizard for new chefs.
 * Steps:
 * 1. Name & Specialty
 * 2. Communication Style (sets soul_prompt)
 * 3. First Dish (optional)
 * 4. First Client (optional)
 */

import React, { useState } from 'react'
import { useSetPersonality, useCompleteSetup, useSkipSetup } from '../../hooks/useOnboarding'

// Personality prompts mapping
const PERSONALITY_OPTIONS = [
  {
    id: 'professional',
    emoji: '',
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="7" width="20" height="14" rx="2" ry="2"/>
        <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
      </svg>
    ),
    title: 'Keep it professional',
    description: 'Clear, formal, to the point',
  },
  {
    id: 'friendly',
    emoji: '',
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="10"/>
        <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
        <line x1="9" y1="9" x2="9.01" y2="9"/>
        <line x1="15" y1="9" x2="15.01" y2="9"/>
      </svg>
    ),
    title: 'Friendly and warm',
    description: 'Casual, supportive, encouraging',
  },
  {
    id: 'efficient',
    emoji: '',
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
      </svg>
    ),
    title: 'Short and efficient',
    description: 'Just the essentials, no fluff',
  },
]

const SPECIALTY_OPTIONS = [
  'Comfort Food',
  'Fine Dining',
  'Meal Prep',
  'Health-Focused',
  'International',
  'Vegan/Vegetarian',
  'Family Meals',
  'Event Catering',
]

export default function OnboardingWizard({ isOpen, onClose, onComplete }) {
  const [step, setStep] = useState(1)
  const [formData, setFormData] = useState({
    nickname: '',
    specialties: [],
    personality: '',
    // Step 3 - optional dish
    dishName: '',
    dishDescription: '',
    // Step 4 - optional client
    clientName: '',
    clientEmail: '',
  })
  const [errors, setErrors] = useState({})

  const setPersonalityMutation = useSetPersonality()
  const completeSetupMutation = useCompleteSetup()
  const skipSetupMutation = useSkipSetup()

  if (!isOpen) return null

  const totalSteps = 4

  const toggleSpecialty = (specialty) => {
    setFormData(prev => {
      const current = prev.specialties
      if (current.includes(specialty)) {
        return { ...prev, specialties: current.filter(s => s !== specialty) }
      }
      return { ...prev, specialties: [...current, specialty] }
    })
    setErrors(prev => ({ ...prev, specialties: null }))
  }

  const selectPersonality = (personalityId) => {
    setFormData(prev => ({ ...prev, personality: personalityId }))
    setErrors(prev => ({ ...prev, personality: null }))
  }

  const validateStep = () => {
    const newErrors = {}

    if (step === 1) {
      // Nickname is optional but specialties recommended
      // No strict validation
    }

    if (step === 2) {
      if (!formData.personality) {
        newErrors.personality = 'Please select a communication style'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleNext = async () => {
    if (!validateStep()) return

    // Step 2 - Save personality to backend
    if (step === 2 && formData.personality) {
      try {
        await setPersonalityMutation.mutateAsync(formData.personality)
      } catch (err) {
        console.error('Failed to set personality:', err)
        // Continue anyway - we can set it later
      }
    }

    if (step < totalSteps) {
      setStep(step + 1)
    } else {
      handleComplete()
    }
  }

  const handleBack = () => {
    if (step > 1) {
      setStep(step - 1)
    }
  }

  const handleSkipStep = () => {
    if (step < totalSteps) {
      setStep(step + 1)
    } else {
      handleComplete()
    }
  }

  const handleComplete = async () => {
    try {
      await completeSetupMutation.mutateAsync(formData.personality)
      localStorage.setItem('sous_chef_onboarded', 'true')
      onComplete?.()
    } catch (err) {
      console.error('Failed to complete setup:', err)
      // Still proceed - we tried our best
      localStorage.setItem('sous_chef_onboarded', 'true')
      onComplete?.()
    }
  }

  const handleSkipAll = async () => {
    try {
      await skipSetupMutation.mutateAsync()
      localStorage.setItem('sous_chef_onboarded', 'true')
      onClose?.()
    } catch (err) {
      console.error('Failed to skip setup:', err)
      localStorage.setItem('sous_chef_onboarded', 'true')
      onClose?.()
    }
  }

  const isLoading = setPersonalityMutation.isPending || completeSetupMutation.isPending

  const renderStepContent = () => {
    switch (step) {
      case 1:
        return (
          <div className="wizard-step">
            <h3 className="wizard-step-title">Let's get to know you</h3>
            <p className="wizard-step-description">
              Tell me a bit about yourself so I can help you better.
            </p>

            <div className="form-field">
              <label className="label">What should I call you?</label>
              <input
                type="text"
                className="input"
                placeholder="Your nickname or first name"
                value={formData.nickname}
                onChange={e => setFormData(prev => ({ ...prev, nickname: e.target.value }))}
              />
              <p className="hint">This is how I'll address you in our conversations</p>
            </div>

            <div className="form-field">
              <label className="label">What's your specialty?</label>
              <p className="hint" style={{ marginBottom: '0.75rem' }}>Select all that apply</p>
              <div className="specialty-grid">
                {SPECIALTY_OPTIONS.map(specialty => (
                  <button
                    key={specialty}
                    type="button"
                    className={`specialty-tag ${formData.specialties.includes(specialty) ? 'selected' : ''}`}
                    onClick={() => toggleSpecialty(specialty)}
                  >
                    {formData.specialties.includes(specialty) && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M20 6L9 17l-5-5"/>
                      </svg>
                    )}
                    {specialty}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )

      case 2:
        return (
          <div className="wizard-step">
            <h3 className="wizard-step-title">How should I communicate?</h3>
            <p className="wizard-step-description">
              Choose the style that feels right for you. You can change this anytime.
            </p>

            <div className="personality-options">
              {PERSONALITY_OPTIONS.map(option => (
                <button
                  key={option.id}
                  type="button"
                  className={`personality-option ${formData.personality === option.id ? 'selected' : ''}`}
                  onClick={() => selectPersonality(option.id)}
                >
                  <div className="personality-icon">
                    {option.icon}
                  </div>
                  <div className="personality-content">
                    <span className="personality-title">{option.title}</span>
                    <span className="personality-description">{option.description}</span>
                  </div>
                  {formData.personality === option.id && (
                    <div className="personality-check">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M20 6L9 17l-5-5"/>
                      </svg>
                    </div>
                  )}
                </button>
              ))}
            </div>
            {errors.personality && (
              <p className="error-text">{errors.personality}</p>
            )}
          </div>
        )

      case 3:
        return (
          <div className="wizard-step">
            <h3 className="wizard-step-title">Add your first dish</h3>
            <p className="wizard-step-description">
              What's a signature dish you love making? This helps me understand your style.
            </p>

            <div className="form-field">
              <label className="label">Dish name</label>
              <input
                type="text"
                className="input"
                placeholder="e.g., Grandmother's Lasagna"
                value={formData.dishName}
                onChange={e => setFormData(prev => ({ ...prev, dishName: e.target.value }))}
              />
            </div>

            <div className="form-field">
              <label className="label">Quick description</label>
              <textarea
                className="input"
                placeholder="What makes it special?"
                rows={3}
                value={formData.dishDescription}
                onChange={e => setFormData(prev => ({ ...prev, dishDescription: e.target.value }))}
              />
            </div>

            <p className="hint" style={{ textAlign: 'center', marginTop: '1rem' }}>
              Don't worry - you can add more dishes later from your menu
            </p>
          </div>
        )

      case 4:
        return (
          <div className="wizard-step">
            <h3 className="wizard-step-title">Add your first client</h3>
            <p className="wizard-step-description">
              Have someone in mind? Add them now and I'll remember everything about them.
            </p>

            <div className="form-field">
              <label className="label">Client name</label>
              <input
                type="text"
                className="input"
                placeholder="e.g., The Johnson Family"
                value={formData.clientName}
                onChange={e => setFormData(prev => ({ ...prev, clientName: e.target.value }))}
              />
            </div>

            <div className="form-field">
              <label className="label">Email (optional)</label>
              <input
                type="email"
                className="input"
                placeholder="client@email.com"
                value={formData.clientEmail}
                onChange={e => setFormData(prev => ({ ...prev, clientEmail: e.target.value }))}
              />
              <p className="hint">They'll receive an invite to connect with you</p>
            </div>

            <p className="hint" style={{ textAlign: 'center', marginTop: '1rem' }}>
              You can add clients anytime from the Clients tab
            </p>
          </div>
        )

      default:
        return null
    }
  }

  return (
    <>
      <div className="modal-overlay" />
      <div className="modal-container onboarding-wizard">
        {/* Progress bar */}
        <div className="wizard-progress">
          <div
            className="wizard-progress-bar"
            style={{ width: `${(step / totalSteps) * 100}%` }}
          />
        </div>

        {/* Header */}
        <div className="wizard-header">
          <div className="wizard-step-indicator">
            Step {step} of {totalSteps}
          </div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleSkipAll}
            disabled={isLoading}
          >
            Skip setup
          </button>
        </div>

        {/* Content */}
        <div className="wizard-content">
          {renderStepContent()}
        </div>

        {/* Footer */}
        <div className="wizard-footer">
          {step > 1 && (
            <button
              className="btn btn-ghost"
              onClick={handleBack}
              disabled={isLoading}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
              Back
            </button>
          )}

          <div className="wizard-footer-right">
            {(step === 3 || step === 4) && (
              <button
                className="btn btn-ghost"
                onClick={handleSkipStep}
                disabled={isLoading}
              >
                Skip
              </button>
            )}
            <button
              className="btn btn-primary"
              onClick={handleNext}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <span className="spinner-sm" />
                  Saving...
                </>
              ) : step === totalSteps ? (
                <>
                  Start cooking
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 12h14M12 5l7 7-7 7"/>
                  </svg>
                </>
              ) : (
                <>
                  Continue
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 12h14M12 5l7 7-7 7"/>
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        .onboarding-wizard {
          max-width: 480px;
          padding: 0;
          border-radius: 20px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          max-height: 90vh;
        }

        /* Progress Bar */
        .wizard-progress {
          height: 4px;
          background: var(--border, #e5e7eb);
        }

        .wizard-progress-bar {
          height: 100%;
          background: var(--primary);
          transition: width 0.3s ease;
        }

        /* Header */
        .wizard-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 1.5rem;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .wizard-step-indicator {
          font-size: 0.85rem;
          color: var(--muted);
          font-weight: 500;
        }

        /* Content */
        .wizard-content {
          flex: 1;
          overflow-y: auto;
          padding: 1.5rem;
        }

        .wizard-step {
          animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
          from { opacity: 0; transform: translateX(10px); }
          to { opacity: 1; transform: translateX(0); }
        }

        .wizard-step-title {
          font-size: 1.25rem;
          font-weight: 600;
          color: var(--text);
          margin: 0 0 0.5rem;
        }

        .wizard-step-description {
          font-size: 0.95rem;
          color: var(--muted);
          margin: 0 0 1.5rem;
          line-height: 1.5;
        }

        /* Form Fields */
        .form-field {
          margin-bottom: 1.25rem;
        }

        .form-field .label {
          display: block;
          font-size: 0.9rem;
          font-weight: 500;
          color: var(--text);
          margin-bottom: 0.5rem;
        }

        .form-field .hint {
          font-size: 0.8rem;
          color: var(--muted);
          margin-top: 0.375rem;
        }

        .form-field .input,
        .form-field textarea.input {
          width: 100%;
          padding: 0.75rem;
          font-size: 0.95rem;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
          background: var(--surface);
          color: var(--text);
          transition: border-color 0.15s, box-shadow 0.15s;
        }

        .form-field .input:focus,
        .form-field textarea.input:focus {
          outline: none;
          border-color: var(--primary);
          box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.15);
        }

        /* Specialty Tags */
        .specialty-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }

        .specialty-tag {
          display: inline-flex;
          align-items: center;
          gap: 0.375rem;
          padding: 0.5rem 0.875rem;
          font-size: 0.875rem;
          font-weight: 500;
          color: var(--text);
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 20px;
          cursor: pointer;
          transition: all 0.15s;
        }

        .specialty-tag:hover {
          border-color: var(--primary);
        }

        .specialty-tag.selected {
          background: var(--primary);
          border-color: var(--primary);
          color: white;
        }

        /* Personality Options */
        .personality-options {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .personality-option {
          display: flex;
          align-items: center;
          gap: 1rem;
          padding: 1rem;
          background: var(--surface);
          border: 2px solid var(--border, #e5e7eb);
          border-radius: 16px;
          cursor: pointer;
          transition: all 0.15s;
          text-align: left;
        }

        .personality-option:hover {
          border-color: var(--primary);
        }

        .personality-option.selected {
          border-color: var(--primary);
          background: rgba(124, 144, 112, 0.05);
        }

        .personality-icon {
          width: 48px;
          height: 48px;
          background: var(--surface-2, #f3f4f6);
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--muted);
          flex-shrink: 0;
        }

        .personality-option.selected .personality-icon {
          background: var(--primary);
          color: white;
        }

        .personality-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
        }

        .personality-title {
          font-size: 0.95rem;
          font-weight: 600;
          color: var(--text);
        }

        .personality-description {
          font-size: 0.85rem;
          color: var(--muted);
        }

        .personality-check {
          width: 28px;
          height: 28px;
          background: var(--primary);
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          flex-shrink: 0;
        }

        .error-text {
          color: var(--danger, #ef4444);
          font-size: 0.85rem;
          margin-top: 0.5rem;
        }

        /* Footer */
        .wizard-footer {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 1.5rem;
          border-top: 1px solid var(--border, #e5e7eb);
          background: var(--surface-2, #f9fafb);
        }

        .wizard-footer-right {
          display: flex;
          gap: 0.75rem;
          margin-left: auto;
        }

        .wizard-footer .btn {
          display: inline-flex;
          align-items: center;
          gap: 0.375rem;
        }

        .spinner-sm {
          display: inline-block;
          width: 14px;
          height: 14px;
          border: 2px solid rgba(255, 255, 255, 0.3);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        /* Dark mode */
        [data-theme="dark"] .wizard-header {
          border-color: var(--border);
        }

        [data-theme="dark"] .wizard-footer {
          background: var(--surface);
          border-color: var(--border);
        }

        [data-theme="dark"] .personality-option.selected {
          background: rgba(124, 144, 112, 0.1);
        }

        /* Mobile */
        @media (max-width: 480px) {
          .onboarding-wizard {
            margin: 1rem;
            max-width: calc(100% - 2rem);
            max-height: calc(100vh - 2rem);
          }

          .wizard-content {
            padding: 1rem;
          }

          .wizard-header,
          .wizard-footer {
            padding: 0.875rem 1rem;
          }

          .wizard-step-title {
            font-size: 1.1rem;
          }

          .personality-option {
            padding: 0.875rem;
          }

          .personality-icon {
            width: 40px;
            height: 40px;
          }
        }
      `}</style>
    </>
  )
}
