/**
 * WorkspaceSettings Component
 *
 * Modal component for editing Sous Chef workspace settings.
 * Provides tabs for Profile, Personality (soul_prompt), and Business Rules.
 * 
 * Profile tab features:
 * - Chef nickname (how Sous Chef addresses the chef)
 * - Chef specialties (multi-select)
 * - Custom Sous Chef name
 * 
 * Personality tab features:
 * - Preset selector (Professional, Friendly, Efficient)
 * - Custom mode for freeform editing
 * - Automatic detection of current mode based on soul_prompt content
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useWorkspace, useUpdateWorkspace, useResetWorkspace } from '../hooks/useWorkspace'
import { PERSONALITY_PRESETS, detectPreset } from '../lib/personalityPresets'
import { CHEF_SPECIALTIES } from '../lib/chefSpecialties'
import ProactiveSettingsPanel from './ProactiveSettingsPanel'
import TelegramSettings from './telegram/TelegramSettings'

const MAX_SOUL_PROMPT_LENGTH = 2000
const MAX_BUSINESS_RULES_LENGTH = 2000
const MAX_NICKNAME_LENGTH = 100
const MAX_SOUS_CHEF_NAME_LENGTH = 50

/**
 * WorkspaceSettings - Modal for Sous Chef customization
 *
 * @param {boolean} isOpen - Whether the modal is open
 * @param {function} onClose - Callback to close the modal
 */
export default function WorkspaceSettings({ isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('profile')
  
  // Profile state
  const [chefNickname, setChefNickname] = useState('')
  const [chefSpecialties, setChefSpecialties] = useState([])
  const [sousChefName, setSousChefName] = useState('')
  
  // Personality state
  const [soulPrompt, setSoulPrompt] = useState('')
  const [selectedPreset, setSelectedPreset] = useState(null)
  const [showCustomEditor, setShowCustomEditor] = useState(false)
  
  // Business rules state
  const [businessRules, setBusinessRules] = useState('')
  
  // UI state
  const [isDirty, setIsDirty] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Fetch workspace data
  const { data: workspace, isLoading, error: fetchError } = useWorkspace({ enabled: isOpen })

  // Mutations
  const updateMutation = useUpdateWorkspace()
  const resetMutation = useResetWorkspace()

  // Sync form state with fetched data
  useEffect(() => {
    if (workspace) {
      // Profile fields
      setChefNickname(workspace.chef_nickname || '')
      setChefSpecialties(workspace.chef_specialties || [])
      setSousChefName(workspace.sous_chef_name || '')
      
      // Personality
      const prompt = workspace.soul_prompt || ''
      setSoulPrompt(prompt)
      const detected = detectPreset(prompt)
      setSelectedPreset(detected)
      setShowCustomEditor(detected === 'custom' || detected === null)
      
      // Business rules
      setBusinessRules(workspace.business_rules || '')
      
      setIsDirty(false)
    }
  }, [workspace])

  // Track dirty state
  useEffect(() => {
    if (workspace) {
      const hasChanges =
        chefNickname !== (workspace.chef_nickname || '') ||
        JSON.stringify(chefSpecialties) !== JSON.stringify(workspace.chef_specialties || []) ||
        sousChefName !== (workspace.sous_chef_name || '') ||
        soulPrompt !== (workspace.soul_prompt || '') ||
        businessRules !== (workspace.business_rules || '')
      setIsDirty(hasChanges)
    }
  }, [chefNickname, chefSpecialties, sousChefName, soulPrompt, businessRules, workspace])

  // Clear success message after delay
  useEffect(() => {
    if (saveSuccess) {
      const timer = setTimeout(() => setSaveSuccess(false), 2000)
      return () => clearTimeout(timer)
    }
  }, [saveSuccess])

  // Handle specialty toggle
  const handleSpecialtyToggle = useCallback((specialtyId) => {
    setChefSpecialties(prev => {
      if (prev.includes(specialtyId)) {
        return prev.filter(id => id !== specialtyId)
      }
      return [...prev, specialtyId]
    })
  }, [])

  // Handle preset selection
  const handlePresetSelect = useCallback((presetId) => {
    if (presetId === 'custom') {
      setSelectedPreset('custom')
      setShowCustomEditor(true)
    } else {
      const preset = PERSONALITY_PRESETS[presetId]
      if (preset) {
        setSoulPrompt(preset.prompt)
        setSelectedPreset(presetId)
        setShowCustomEditor(false)
      }
    }
  }, [])

  // Handle direct textarea edits
  const handleSoulPromptChange = useCallback((e) => {
    const newValue = e.target.value
    setSoulPrompt(newValue)
    
    // Check if the edited text still matches a preset
    const detected = detectPreset(newValue)
    if (detected !== selectedPreset) {
      setSelectedPreset(detected)
    }
  }, [selectedPreset])

  // Toggle custom editor visibility
  const handleToggleCustomEditor = useCallback(() => {
    setShowCustomEditor(prev => !prev)
    if (!showCustomEditor && selectedPreset !== 'custom') {
      setSelectedPreset('custom')
    }
  }, [showCustomEditor, selectedPreset])

  const handleSave = useCallback(async () => {
    const updates = {}

    // Profile updates
    if (chefNickname !== (workspace?.chef_nickname || '')) {
      updates.chef_nickname = chefNickname
    }
    if (JSON.stringify(chefSpecialties) !== JSON.stringify(workspace?.chef_specialties || [])) {
      updates.chef_specialties = chefSpecialties
    }
    if (sousChefName !== (workspace?.sous_chef_name || '')) {
      updates.sous_chef_name = sousChefName
    }
    
    // Personality updates
    if (soulPrompt !== (workspace?.soul_prompt || '')) {
      updates.soul_prompt = soulPrompt
    }
    
    // Business rules updates
    if (businessRules !== (workspace?.business_rules || '')) {
      updates.business_rules = businessRules
    }

    if (Object.keys(updates).length === 0) {
      return
    }

    try {
      await updateMutation.mutateAsync(updates)
      setIsDirty(false)
      setSaveSuccess(true)
    } catch (err) {
      // Error handled by mutation
    }
  }, [chefNickname, chefSpecialties, sousChefName, soulPrompt, businessRules, workspace, updateMutation])

  const handleReset = useCallback(async (field) => {
    try {
      await resetMutation.mutateAsync([field])
      setSaveSuccess(true)
    } catch (err) {
      // Error handled by mutation
    }
  }, [resetMutation])

  const handleClose = useCallback(() => {
    if (isDirty) {
      if (window.confirm('You have unsaved changes. Discard them?')) {
        onClose?.()
      }
    } else {
      onClose?.()
    }
  }, [isDirty, onClose])

  // Compute the current personality mode label for display
  const currentModeLabel = useMemo(() => {
    if (!selectedPreset || selectedPreset === 'custom') {
      return soulPrompt?.trim() ? 'Custom' : 'Not set'
    }
    const preset = PERSONALITY_PRESETS[selectedPreset]
    return preset ? preset.label : 'Custom'
  }, [selectedPreset, soulPrompt])

  if (!isOpen) return null

  const isSaving = updateMutation.isPending || resetMutation.isPending

  return (
    <div className="ws-modal-overlay" onClick={handleClose}>
      <div className="ws-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <header className="ws-header">
          <h2 className="ws-title">Workspace Settings</h2>
          <button className="ws-close-btn" onClick={handleClose} aria-label="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </header>

        {/* Tabs */}
        <nav className="ws-tabs">
          <button
            className={`ws-tab ${activeTab === 'profile' ? 'active' : ''}`}
            onClick={() => setActiveTab('profile')}
          >
            Profile
          </button>
          <button
            className={`ws-tab ${activeTab === 'personality' ? 'active' : ''}`}
            onClick={() => setActiveTab('personality')}
          >
            Personality
          </button>
          <button
            className={`ws-tab ${activeTab === 'rules' ? 'active' : ''}`}
            onClick={() => setActiveTab('rules')}
          >
            Business Rules
          </button>
          <button
            className={`ws-tab ${activeTab === 'notifications' ? 'active' : ''}`}
            onClick={() => setActiveTab('notifications')}
          >
            Notifications
          </button>
        </nav>

        {/* Content */}
        <div className="ws-content">
          {isLoading && (
            <div className="ws-loading">Loading settings...</div>
          )}

          {fetchError && (
            <div className="ws-error">
              Failed to load settings. Please try again.
            </div>
          )}

          {!isLoading && !fetchError && (
            <>
              {/* Profile Tab */}
              {activeTab === 'profile' && (
                <div className="ws-field-group">
                  {/* Chef Nickname */}
                  <div className="ws-field">
                    <label className="ws-label" htmlFor="chef-nickname">
                      What should I call you?
                    </label>
                    <p className="ws-description">
                      Your Sous Chef will use this name when addressing you.
                    </p>
                    <input
                      id="chef-nickname"
                      type="text"
                      className="ws-input"
                      value={chefNickname}
                      onChange={(e) => setChefNickname(e.target.value)}
                      placeholder="Chef Marcus, Marcus, Boss..."
                      maxLength={MAX_NICKNAME_LENGTH}
                    />
                  </div>

                  {/* Specialties */}
                  <div className="ws-field">
                    <label className="ws-label">
                      Your specialties
                    </label>
                    <p className="ws-description">
                      Select what you're known for. This helps Sous Chef make relevant suggestions.
                    </p>
                    <div className="ws-specialty-grid">
                      {CHEF_SPECIALTIES.map((specialty) => (
                        <button
                          key={specialty.id}
                          type="button"
                          className={`ws-specialty-chip ${chefSpecialties.includes(specialty.id) ? 'selected' : ''}`}
                          onClick={() => handleSpecialtyToggle(specialty.id)}
                        >
                          <span className="ws-specialty-emoji">{specialty.emoji}</span>
                          <span className="ws-specialty-label">{specialty.label}</span>
                          {chefSpecialties.includes(specialty.id) && (
                            <span className="ws-specialty-check">✓</span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Sous Chef Name */}
                  <div className="ws-field">
                    <label className="ws-label" htmlFor="sous-chef-name">
                      Assistant name <span className="ws-optional">(optional)</span>
                    </label>
                    <p className="ws-description">
                      Give your AI assistant a custom name, or leave blank for "Sous Chef".
                    </p>
                    <input
                      id="sous-chef-name"
                      type="text"
                      className="ws-input"
                      value={sousChefName}
                      onChange={(e) => setSousChefName(e.target.value)}
                      placeholder="Sous Chef"
                      maxLength={MAX_SOUS_CHEF_NAME_LENGTH}
                    />
                  </div>
                </div>
              )}

              {/* Personality Tab */}
              {activeTab === 'personality' && (
                <div className="ws-field-group">
                  <div className="ws-field-header">
                    <label className="ws-label">
                      Sous Chef Personality
                    </label>
                    <span className="ws-current-mode">
                      Currently: <strong>{currentModeLabel}</strong>
                    </span>
                  </div>
                  <p className="ws-description">
                    Choose how your Sous Chef communicates. Pick a preset or create your own style.
                  </p>

                  {/* Preset Selector */}
                  <div className="ws-preset-grid">
                    {Object.values(PERSONALITY_PRESETS).map((preset) => (
                      <button
                        key={preset.id}
                        className={`ws-preset-card ${selectedPreset === preset.id ? 'selected' : ''}`}
                        onClick={() => handlePresetSelect(preset.id)}
                        type="button"
                      >
                        <span className="ws-preset-emoji">{preset.emoji}</span>
                        <span className="ws-preset-label">{preset.label}</span>
                        <span className="ws-preset-desc">{preset.description}</span>
                        {selectedPreset === preset.id && (
                          <span className="ws-preset-check">✓</span>
                        )}
                      </button>
                    ))}
                    <button
                      className={`ws-preset-card ws-preset-custom ${selectedPreset === 'custom' ? 'selected' : ''}`}
                      onClick={() => handlePresetSelect('custom')}
                      type="button"
                    >
                      <span className="ws-preset-emoji">✏️</span>
                      <span className="ws-preset-label">Custom</span>
                      <span className="ws-preset-desc">Write your own</span>
                      {selectedPreset === 'custom' && (
                        <span className="ws-preset-check">✓</span>
                      )}
                    </button>
                  </div>

                  {/* Custom Editor Toggle */}
                  <button
                    className="ws-toggle-editor"
                    onClick={handleToggleCustomEditor}
                    type="button"
                  >
                    {showCustomEditor ? '▼ Hide editor' : '▶ Edit directly'}
                  </button>

                  {/* Textarea Editor (shown for custom or when toggled) */}
                  {showCustomEditor && (
                    <div className="ws-editor-section">
                      <textarea
                        id="soul-prompt"
                        className="ws-textarea"
                        value={soulPrompt}
                        onChange={handleSoulPromptChange}
                        placeholder="Define how your Sous Chef should communicate..."
                        maxLength={MAX_SOUL_PROMPT_LENGTH}
                        rows={8}
                      />
                      <div className="ws-textarea-footer">
                        <button
                          className="ws-reset-btn"
                          onClick={() => handleReset('soul_prompt')}
                          disabled={isSaving}
                          title="Reset to default"
                          type="button"
                        >
                          Reset to default
                        </button>
                        <span className="ws-char-count">
                          {soulPrompt.length} / {MAX_SOUL_PROMPT_LENGTH}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Business Rules Tab */}
              {activeTab === 'rules' && (
                <div className="ws-field-group">
                  <div className="ws-field-header">
                    <label className="ws-label" htmlFor="business-rules">
                      Business Rules
                    </label>
                    <button
                      className="ws-reset-btn"
                      onClick={() => handleReset('business_rules')}
                      disabled={isSaving}
                      title="Clear rules"
                    >
                      Clear
                    </button>
                  </div>
                  <p className="ws-description">
                    Set operating constraints like hours, pricing policies, service boundaries, and other rules your Sous Chef should follow.
                  </p>
                  <textarea
                    id="business-rules"
                    className="ws-textarea"
                    value={businessRules}
                    onChange={(e) => setBusinessRules(e.target.value)}
                    placeholder="Example:&#10;- Operating hours: 9am-6pm, Monday-Saturday&#10;- No rush orders under 48 hours notice&#10;- Minimum order: $150&#10;- No seafood delivery on Mondays"
                    maxLength={MAX_BUSINESS_RULES_LENGTH}
                    rows={10}
                  />
                  <div className="ws-char-count">
                    {businessRules.length} / {MAX_BUSINESS_RULES_LENGTH}
                  </div>
                </div>
              )}

              {/* Notifications Tab */}
              {activeTab === 'notifications' && (
                <>
                  <ProactiveSettingsPanel />
                  <TelegramSettings />
                </>
              )}
            </>
          )}

          {/* Status Messages */}
          {updateMutation.isError && (
            <div className="ws-error">
              Failed to save changes. Please try again.
            </div>
          )}

          {resetMutation.isError && (
            <div className="ws-error">
              Failed to reset. Please try again.
            </div>
          )}

          {saveSuccess && (
            <div className="ws-success">
              Settings saved successfully!
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="ws-footer">
          <button className="ws-btn ws-btn-outline" onClick={handleClose}>
            Cancel
          </button>
          <button
            className="ws-btn ws-btn-primary"
            onClick={handleSave}
            disabled={!isDirty || isSaving}
          >
            {isSaving ? 'Saving...' : 'Save Changes'}
          </button>
        </footer>

        <style>{`
          .ws-modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1100;
            animation: wsFadeIn 0.2s ease;
          }

          @keyframes wsFadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
          }

          .ws-modal {
            background: var(--surface, #fff);
            border-radius: 16px;
            width: 90%;
            max-width: 560px;
            max-height: 85vh;
            max-height: 85dvh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            animation: wsSlideUp 0.25s ease;
          }

          @keyframes wsSlideUp {
            from {
              opacity: 0;
              transform: translateY(20px);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }

          /* Header */
          .ws-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border, #e5e5e5);
            flex-shrink: 0;
          }

          .ws-title {
            margin: 0;
            font-size: 1.2rem;
            font-weight: 600;
            color: var(--text, #333);
          }

          .ws-close-btn {
            background: none;
            border: none;
            color: var(--muted, #888);
            cursor: pointer;
            padding: 0.25rem;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 6px;
            transition: all 0.15s;
          }

          .ws-close-btn:hover {
            background: var(--surface-2, #f5f5f5);
            color: var(--text, #333);
          }

          /* Tabs */
          .ws-tabs {
            display: flex;
            border-bottom: 1px solid var(--border, #e5e5e5);
            padding: 0 1.25rem;
            flex-shrink: 0;
          }

          .ws-tab {
            padding: 0.875rem 1rem;
            background: none;
            border: none;
            border-bottom: 2px solid transparent;
            color: var(--muted, #888);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
            margin-bottom: -1px;
          }

          .ws-tab:hover {
            color: var(--text, #333);
          }

          .ws-tab.active {
            color: var(--primary, #7C9070);
            border-bottom-color: var(--primary, #7C9070);
          }

          /* Content */
          .ws-content {
            flex: 1;
            overflow-y: auto;
            padding: 1.25rem;
            -webkit-overflow-scrolling: touch;
          }

          .ws-loading {
            text-align: center;
            padding: 2rem;
            color: var(--muted, #888);
          }

          .ws-field-group {
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
          }

          .ws-field {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
          }

          .ws-field-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
          }

          .ws-label {
            font-weight: 600;
            font-size: 1rem;
            color: var(--text, #333);
          }

          .ws-optional {
            font-weight: 400;
            font-size: 0.85rem;
            color: var(--muted, #888);
          }

          .ws-current-mode {
            font-size: 0.85rem;
            color: var(--muted, #888);
          }

          .ws-current-mode strong {
            color: var(--primary, #7C9070);
          }

          .ws-description {
            font-size: 0.875rem;
            color: var(--muted, #888);
            margin: 0;
            line-height: 1.5;
          }

          .ws-input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid var(--border, #ddd);
            border-radius: 10px;
            font-size: 0.95rem;
            font-family: inherit;
            background: var(--surface, #fff);
            color: var(--text, #333);
            transition: border-color 0.15s;
          }

          .ws-input:focus {
            outline: none;
            border-color: var(--primary, #7C9070);
            box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.1);
          }

          .ws-input::placeholder {
            color: var(--muted, #aaa);
          }

          /* Specialty Grid */
          .ws-specialty-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
          }

          .ws-specialty-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.375rem;
            padding: 0.5rem 0.75rem;
            background: var(--surface-2, #f9fafb);
            border: 1.5px solid var(--border, #e5e7eb);
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.15s;
            font-size: 0.85rem;
          }

          .ws-specialty-chip:hover {
            border-color: var(--primary, #7C9070);
            background: rgba(124, 144, 112, 0.05);
          }

          .ws-specialty-chip.selected {
            border-color: var(--primary, #7C9070);
            background: rgba(124, 144, 112, 0.1);
          }

          .ws-specialty-emoji {
            font-size: 1rem;
          }

          .ws-specialty-label {
            color: var(--text, #333);
          }

          .ws-specialty-check {
            width: 16px;
            height: 16px;
            background: var(--primary, #7C9070);
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.65rem;
            font-weight: bold;
            margin-left: 0.25rem;
          }

          .ws-reset-btn {
            background: none;
            border: none;
            color: var(--primary, #7C9070);
            font-size: 0.8rem;
            font-weight: 500;
            cursor: pointer;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            transition: all 0.15s;
          }

          .ws-reset-btn:hover:not(:disabled) {
            background: rgba(124, 144, 112, 0.1);
          }

          .ws-reset-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }

          /* Preset Grid */
          .ws-preset-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.75rem;
            margin-top: 0.5rem;
          }

          .ws-preset-card {
            position: relative;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.375rem;
            padding: 1rem 0.75rem;
            background: var(--surface-2, #f9fafb);
            border: 2px solid var(--border, #e5e7eb);
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.15s;
            text-align: center;
          }

          .ws-preset-card:hover {
            border-color: var(--primary, #7C9070);
            background: rgba(124, 144, 112, 0.05);
          }

          .ws-preset-card.selected {
            border-color: var(--primary, #7C9070);
            background: rgba(124, 144, 112, 0.1);
          }

          .ws-preset-emoji {
            font-size: 1.5rem;
          }

          .ws-preset-label {
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--text, #333);
          }

          .ws-preset-desc {
            font-size: 0.75rem;
            color: var(--muted, #888);
          }

          .ws-preset-check {
            position: absolute;
            top: 8px;
            right: 8px;
            width: 20px;
            height: 20px;
            background: var(--primary, #7C9070);
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.7rem;
            font-weight: bold;
          }

          .ws-preset-custom {
            border-style: dashed;
          }

          /* Toggle Editor Button */
          .ws-toggle-editor {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            background: none;
            border: none;
            color: var(--muted, #888);
            font-size: 0.85rem;
            cursor: pointer;
            padding: 0.5rem 0;
            transition: color 0.15s;
          }

          .ws-toggle-editor:hover {
            color: var(--text, #333);
          }

          /* Editor Section */
          .ws-editor-section {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            animation: wsSlideDown 0.2s ease;
          }

          @keyframes wsSlideDown {
            from {
              opacity: 0;
              transform: translateY(-10px);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }

          .ws-textarea {
            width: 100%;
            padding: 0.875rem;
            border: 1px solid var(--border, #ddd);
            border-radius: 10px;
            font-size: 0.9rem;
            font-family: inherit;
            line-height: 1.5;
            resize: vertical;
            background: var(--surface, #fff);
            color: var(--text, #333);
            transition: border-color 0.15s;
          }

          .ws-textarea:focus {
            outline: none;
            border-color: var(--primary, #7C9070);
            box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.1);
          }

          .ws-textarea::placeholder {
            color: var(--muted, #aaa);
          }

          .ws-textarea-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
          }

          .ws-char-count {
            text-align: right;
            font-size: 0.8rem;
            color: var(--muted, #888);
          }

          /* Messages */
          .ws-error {
            padding: 0.75rem;
            background: rgba(220, 53, 69, 0.1);
            border: 1px solid rgba(220, 53, 69, 0.3);
            border-radius: 8px;
            color: #dc3545;
            font-size: 0.9rem;
            margin-top: 1rem;
          }

          .ws-success {
            padding: 0.75rem;
            background: rgba(124, 144, 112, 0.1);
            border: 1px solid rgba(124, 144, 112, 0.3);
            border-radius: 8px;
            color: var(--primary, #7C9070);
            font-size: 0.9rem;
            margin-top: 1rem;
          }

          /* Footer */
          .ws-footer {
            display: flex;
            justify-content: flex-end;
            gap: 0.75rem;
            padding: 1rem 1.25rem;
            padding-bottom: max(1rem, env(safe-area-inset-bottom));
            border-top: 1px solid var(--border, #e5e5e5);
            flex-shrink: 0;
          }

          .ws-btn {
            padding: 0.625rem 1.25rem;
            border-radius: 8px;
            font-weight: 500;
            font-size: 0.9rem;
            cursor: pointer;
            transition: all 0.15s;
          }

          .ws-btn-outline {
            background: transparent;
            border: 1px solid var(--border, #ddd);
            color: var(--text, #333);
          }

          .ws-btn-outline:hover {
            border-color: var(--text, #333);
          }

          .ws-btn-primary {
            background: var(--primary, #7C9070);
            border: none;
            color: white;
          }

          .ws-btn-primary:hover:not(:disabled) {
            background: var(--primary-700, #449d44);
          }

          .ws-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }

          /* Responsive */
          @media (max-width: 600px) {
            .ws-modal {
              width: 95%;
              max-height: 90vh;
              max-height: 90dvh;
              border-radius: 12px;
            }

            .ws-tabs {
              padding: 0 0.75rem;
            }

            .ws-tab {
              padding: 0.75rem 0.6rem;
              font-size: 0.8rem;
            }

            .ws-content {
              padding: 1rem;
            }

            .ws-preset-grid {
              grid-template-columns: repeat(2, 1fr);
              gap: 0.5rem;
            }

            .ws-preset-card {
              padding: 0.75rem 0.5rem;
            }

            .ws-preset-emoji {
              font-size: 1.25rem;
            }

            .ws-preset-label {
              font-size: 0.8rem;
            }

            .ws-preset-desc {
              font-size: 0.7rem;
            }

            .ws-specialty-chip {
              padding: 0.4rem 0.6rem;
              font-size: 0.8rem;
            }

            .ws-footer {
              padding: 0.875rem 1rem;
            }
          }
        `}</style>
      </div>
    </div>
  )
}

// Re-export presets for use in other components (e.g., onboarding)
export { PERSONALITY_PRESETS, detectPreset } from '../lib/personalityPresets'
export { CHEF_SPECIALTIES } from '../lib/chefSpecialties'
