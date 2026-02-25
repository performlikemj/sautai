/**
 * SousChefSettings Component
 * 
 * Settings panel for Sous Chef contextual suggestion preferences.
 * Accessible from the Sous Chef widget header.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

/**
 * SousChefSettings - Manages AI suggestion preferences
 * 
 * @param {boolean} isOpen - Whether the settings panel is open
 * @param {function} onClose - Callback to close the panel
 * @param {object} initialSettings - Initial settings from chef profile
 * @param {function} onSave - Callback when settings are saved
 */
export default function SousChefSettings({
  isOpen,
  onClose,
  initialSettings = {},
  onSave
}) {
  const [settings, setSettings] = useState({
    sous_chef_suggestions_enabled: true,
    sous_chef_suggestion_frequency: 'sometimes',
    dismissed_suggestion_types: []
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  
  // Sync initial settings
  useEffect(() => {
    if (initialSettings) {
      setSettings(prev => ({
        ...prev,
        sous_chef_suggestions_enabled: initialSettings.sous_chef_suggestions_enabled ?? true,
        sous_chef_suggestion_frequency: initialSettings.sous_chef_suggestion_frequency || 'sometimes',
        dismissed_suggestion_types: initialSettings.dismissed_suggestion_types || []
      }))
    }
  }, [initialSettings])
  
  /**
   * Save settings to backend
   */
  const handleSave = useCallback(async () => {
    setSaving(true)
    setError(null)
    setSuccess(false)
    
    try {
      await api.patch('/chefs/api/me/chef/profile/update/', {
        sous_chef_suggestions_enabled: settings.sous_chef_suggestions_enabled,
        sous_chef_suggestion_frequency: settings.sous_chef_suggestion_frequency,
        dismissed_suggestion_types: settings.dismissed_suggestion_types
      })
      
      setSuccess(true)
      
      if (onSave) {
        onSave(settings)
      }
      
      // Auto-close after success
      setTimeout(() => {
        onClose?.()
      }, 1000)
      
    } catch (err) {
      console.error('Failed to save Sous Chef settings:', err)
      setError(err.response?.data?.message || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }, [settings, onSave, onClose])
  
  /**
   * Toggle suggestions enabled
   */
  const toggleEnabled = useCallback(() => {
    setSettings(prev => ({
      ...prev,
      sous_chef_suggestions_enabled: !prev.sous_chef_suggestions_enabled
    }))
  }, [])
  
  /**
   * Change frequency
   */
  const setFrequency = useCallback((frequency) => {
    setSettings(prev => ({
      ...prev,
      sous_chef_suggestion_frequency: frequency
    }))
  }, [])
  
  /**
   * Re-enable a dismissed suggestion type
   */
  const reenableSuggestionType = useCallback((type) => {
    setSettings(prev => ({
      ...prev,
      dismissed_suggestion_types: prev.dismissed_suggestion_types.filter(t => t !== type)
    }))
  }, [])
  
  /**
   * Clear all dismissed suggestions
   */
  const clearAllDismissed = useCallback(() => {
    setSettings(prev => ({
      ...prev,
      dismissed_suggestion_types: []
    }))
  }, [])
  
  if (!isOpen) return null
  
  const frequencyOptions = [
    { value: 'often', label: 'Often', description: 'Show suggestions frequently as you work' },
    { value: 'sometimes', label: 'Sometimes', description: 'Show suggestions when you seem stuck (recommended)' },
    { value: 'rarely', label: 'Rarely', description: 'Only show high-priority suggestions' }
  ]
  
  // Format dismissed type for display
  const formatSuggestionType = (type) => {
    return type
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase())
  }
  
  return (
    <div className="sous-chef-settings-overlay" onClick={onClose}>
      <div className="sous-chef-settings-panel" onClick={e => e.stopPropagation()}>
        <header className="settings-header">
          <h3>Sous Chef Settings</h3>
          <button className="close-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        
        <div className="settings-content">
          {/* Enable/Disable Toggle */}
          <div className="setting-group">
            <div className="setting-row toggle-row">
              <div className="setting-info">
                <div className="setting-label">Contextual Suggestions</div>
                <div className="setting-description">
                  Get AI-powered suggestions as you fill out forms
                </div>
              </div>
              <button
                className={`toggle-btn ${settings.sous_chef_suggestions_enabled ? 'active' : ''}`}
                onClick={toggleEnabled}
                aria-pressed={settings.sous_chef_suggestions_enabled}
              >
                <span className="toggle-track">
                  <span className="toggle-thumb" />
                </span>
              </button>
            </div>
          </div>
          
          {/* Frequency Selection */}
          {settings.sous_chef_suggestions_enabled && (
            <div className="setting-group">
              <div className="setting-label">Suggestion Frequency</div>
              <div className="frequency-options">
                {frequencyOptions.map(option => (
                  <label
                    key={option.value}
                    className={`frequency-option ${settings.sous_chef_suggestion_frequency === option.value ? 'selected' : ''}`}
                  >
                    <input
                      type="radio"
                      name="frequency"
                      value={option.value}
                      checked={settings.sous_chef_suggestion_frequency === option.value}
                      onChange={() => setFrequency(option.value)}
                    />
                    <div className="option-content">
                      <span className="option-label">{option.label}</span>
                      <span className="option-description">{option.description}</span>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
          
          {/* Dismissed Suggestions */}
          {settings.dismissed_suggestion_types.length > 0 && (
            <div className="setting-group">
              <div className="setting-row">
                <div className="setting-label">Dismissed Suggestions</div>
                <button 
                  className="btn btn-sm btn-outline"
                  onClick={clearAllDismissed}
                >
                  Re-enable All
                </button>
              </div>
              <div className="dismissed-list">
                {settings.dismissed_suggestion_types.map(type => (
                  <div key={type} className="dismissed-item">
                    <span>{formatSuggestionType(type)}</span>
                    <button
                      className="reenable-btn"
                      onClick={() => reenableSuggestionType(type)}
                      title="Re-enable this suggestion"
                    >
                      ↻
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Error/Success Messages */}
          {error && (
            <div className="settings-error">
              {error}
            </div>
          )}
          
          {success && (
            <div className="settings-success">
              Settings saved!
            </div>
          )}
        </div>
        
        <footer className="settings-footer">
          <button className="btn btn-outline" onClick={onClose}>
            Cancel
          </button>
          <button 
            className="btn btn-primary" 
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </footer>
      </div>
      
      <style>{`
        .sous-chef-settings-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1100;
          animation: fadeIn 0.2s ease;
        }
        
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        
        .sous-chef-settings-panel {
          background: var(--surface, #fff);
          border-radius: 16px;
          width: 90%;
          max-width: 420px;
          max-height: 80vh;
          max-height: 80dvh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
          animation: slideUp 0.25s ease;
        }
        
        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        
        .settings-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 1rem 1.25rem;
          border-bottom: 1px solid var(--border, #e5e5e5);
        }
        
        .settings-header h3 {
          margin: 0;
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--text, #333);
        }
        
        .settings-header .close-btn {
          background: none;
          border: none;
          font-size: 1.25rem;
          color: var(--muted, #888);
          cursor: pointer;
          padding: 0.25rem;
          line-height: 1;
        }
        
        .settings-header .close-btn:hover {
          color: var(--text, #333);
        }
        
        .settings-content {
          flex: 1;
          overflow-y: auto;
          padding: 1.25rem;
          -webkit-overflow-scrolling: touch;
        }
        
        .setting-group {
          margin-bottom: 1.5rem;
        }
        
        .setting-group:last-child {
          margin-bottom: 0;
        }
        
        .setting-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
        }
        
        .toggle-row {
          padding: 0.75rem;
          background: var(--surface-2, #f5f5f5);
          border-radius: 10px;
        }
        
        .setting-info {
          flex: 1;
        }
        
        .setting-label {
          font-weight: 600;
          font-size: 0.95rem;
          color: var(--text, #333);
          margin-bottom: 0.25rem;
        }
        
        .setting-description {
          font-size: 0.85rem;
          color: var(--muted, #888);
        }
        
        /* Toggle Button */
        .toggle-btn {
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
        }
        
        .toggle-track {
          display: block;
          width: 44px;
          height: 24px;
          background: var(--border, #ddd);
          border-radius: 12px;
          position: relative;
          transition: background 0.2s;
        }
        
        .toggle-btn.active .toggle-track {
          background: var(--primary, #7C9070);
        }
        
        .toggle-thumb {
          position: absolute;
          top: 2px;
          left: 2px;
          width: 20px;
          height: 20px;
          background: white;
          border-radius: 50%;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
          transition: transform 0.2s;
        }
        
        .toggle-btn.active .toggle-thumb {
          transform: translateX(20px);
        }
        
        /* Frequency Options */
        .frequency-options {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          margin-top: 0.75rem;
        }
        
        .frequency-option {
          display: flex;
          align-items: flex-start;
          gap: 0.75rem;
          padding: 0.75rem;
          border: 1px solid var(--border, #ddd);
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .frequency-option:hover {
          border-color: var(--primary, #7C9070);
          background: rgba(124, 144, 112, 0.05);
        }
        
        .frequency-option.selected {
          border-color: var(--primary, #7C9070);
          background: rgba(124, 144, 112, 0.1);
        }
        
        .frequency-option input {
          margin-top: 0.2rem;
        }
        
        .option-content {
          display: flex;
          flex-direction: column;
          gap: 0.125rem;
        }
        
        .option-label {
          font-weight: 500;
          color: var(--text, #333);
        }
        
        .option-description {
          font-size: 0.8rem;
          color: var(--muted, #888);
        }
        
        /* Dismissed List */
        .dismissed-list {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          margin-top: 0.75rem;
        }
        
        .dismissed-item {
          display: flex;
          align-items: center;
          gap: 0.35rem;
          padding: 0.35rem 0.5rem;
          background: var(--surface-2, #f0f0f0);
          border-radius: 6px;
          font-size: 0.85rem;
        }
        
        .reenable-btn {
          background: none;
          border: none;
          cursor: pointer;
          color: var(--primary, #7C9070);
          font-size: 0.9rem;
          padding: 0 0.2rem;
        }
        
        .reenable-btn:hover {
          color: var(--primary-700, #449d44);
        }
        
        /* Messages */
        .settings-error {
          padding: 0.75rem;
          background: rgba(220, 53, 69, 0.1);
          border: 1px solid rgba(220, 53, 69, 0.3);
          border-radius: 8px;
          color: #dc3545;
          font-size: 0.9rem;
          margin-top: 1rem;
        }
        
        .settings-success {
          padding: 0.75rem;
          background: rgba(124, 144, 112, 0.1);
          border: 1px solid rgba(124, 144, 112, 0.3);
          border-radius: 8px;
          color: var(--primary, #7C9070);
          font-size: 0.9rem;
          margin-top: 1rem;
        }
        
        /* Footer */
        .settings-footer {
          display: flex;
          justify-content: flex-end;
          gap: 0.75rem;
          padding: 1rem 1.25rem;
          padding-bottom: max(1rem, env(safe-area-inset-bottom));
          border-top: 1px solid var(--border, #e5e5e5);
          flex-shrink: 0;
        }
        
        .settings-footer .btn {
          padding: 0.5rem 1rem;
          border-radius: 8px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .settings-footer .btn-outline {
          background: transparent;
          border: 1px solid var(--border, #ddd);
          color: var(--text, #333);
        }
        
        .settings-footer .btn-outline:hover {
          border-color: var(--text, #333);
        }
        
        .settings-footer .btn-primary {
          background: var(--primary, #7C9070);
          border: none;
          color: white;
        }
        
        .settings-footer .btn-primary:hover {
          background: var(--primary-700, #449d44);
        }
        
        .settings-footer .btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
      `}</style>
    </div>
  )
}
