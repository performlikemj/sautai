/**
 * SousChefChat Component
 *
 * Modern AI chat interface for chefs to interact with the Sous Chef assistant.
 * Features redesigned message bubbles, quick action pills, and improved input.
 */

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { getRandomChefEmoji } from '../utils/emojis.js'
import StructuredContent from './StructuredContent'
import {
  sendStructuredMessage,
  getSousChefHistory,
  newSousChefConversation,
  getFamilyContext
} from '../api/sousChefClient'

export default function SousChefChat({
  familyId,
  familyType,
  familyName,
  chefEmoji: chefEmojiProp,
  initialContext,  // Pre-populated context from notifications
  onContextHandled, // Callback when context has been used
  initialInput,     // Pre-populated input text (from widget expansion)
  externalInputRef, // External ref to access the input element
  onAction          // Callback for action blocks (navigation/prefill)
}) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState(initialInput || '')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [familyContext, setFamilyContext] = useState(null)
  const [showContext, setShowContext] = useState(true)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [pendingPrompt, setPendingPrompt] = useState(null)

  // Use provided emoji or fallback to random for inclusive representation
  const chefEmoji = useMemo(() => chefEmojiProp || getRandomChefEmoji(), [chefEmojiProp])

  const endRef = useRef(null)
  const inputRef = useRef(null)
  const isInitialLoadRef = useRef(true)

  // Track the initial context prePrompt to detect new contexts
  const initialPrePromptRef = useRef(null)

  // Handle initial context from notifications
  useEffect(() => {
    const prePrompt = initialContext?.prePrompt
    if (prePrompt && prePrompt !== initialPrePromptRef.current) {
      initialPrePromptRef.current = prePrompt
      setPendingPrompt(prePrompt)
    }
  }, [initialContext?.prePrompt])

  // Auto-fill pending prompt when a family is selected and history is loaded
  useEffect(() => {
    if (pendingPrompt && familyId && !historyLoading && !isStreaming) {
      const timer = setTimeout(() => {
        setInput(pendingPrompt)
        setPendingPrompt(null)
        initialPrePromptRef.current = null
        if (onContextHandled) {
          onContextHandled()
        }
        if (inputRef.current) {
          inputRef.current.focus()
        }
      }, 500)
      return () => clearTimeout(timer)
    }
  }, [pendingPrompt, familyId, historyLoading, isStreaming, onContextHandled])

  // Determine if we're in general mode (no family selected)
  const isGeneralMode = !familyId

  // Load history and context when family changes (or general mode)
  useEffect(() => {
    let mounted = true

    async function loadData() {
      isInitialLoadRef.current = true
      setHistoryLoading(true)
      setMessages([])
      setFamilyContext(null)
      setError(null)

      try {
        const [historyData, contextData] = await Promise.all([
          getSousChefHistory(familyId || null, familyType || null).catch(() => null),
          getFamilyContext(familyId || null, familyType || null).catch(() => null)
        ])

        if (!mounted) return

        if (historyData?.messages) {
          const formattedMessages = historyData.messages.map((msg, idx) => ({
            id: `hist-${idx}`,
            role: msg.role,
            content: msg.content,
            finalized: true
          }))
          setMessages(formattedMessages)
        }

        if (contextData) {
          setFamilyContext(contextData)
        }
      } catch (err) {
        if (mounted) {
          setError(err.message || 'Failed to load conversation')
        }
      } finally {
        if (mounted) {
          setHistoryLoading(false)
        }
      }
    }

    loadData()
    return () => { mounted = false }
  }, [familyId, familyType])

  // Auto-scroll - use instant on initial load, smooth for new messages
  useEffect(() => {
    if (isInitialLoadRef.current) {
      endRef.current?.scrollIntoView({ behavior: 'instant', block: 'end' })
      const timer = setTimeout(() => {
        isInitialLoadRef.current = false
      }, 500)
      return () => clearTimeout(timer)
    } else {
      endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages])

  // Focus input when not streaming
  useEffect(() => {
    if (!isStreaming && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isStreaming, familyId])

  const handleNewChat = async () => {
    try {
      await newSousChefConversation(familyId, familyType)
      setMessages([])
      setError(null)
    } catch (err) {
      setError(err.message || 'Failed to start new conversation')
    }
  }

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isStreaming) return

    setError(null)
    setInput('')

    // Add user message
    const userMsgId = `user-${Date.now()}`
    setMessages(prev => [...prev, {
      id: userMsgId,
      role: 'chef',
      content: text,
      finalized: true
    }])

    // Add thinking indicator
    const assistantId = `assistant-${Date.now()}`
    setMessages(prev => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      finalized: false,
      isThinking: true
    }])

    setIsStreaming(true)

    try {
      const result = await sendStructuredMessage({
        familyId: familyId || null,
        familyType: familyType || null,
        message: text
      })

      if (result.status === 'success' && result.content) {
        const contentJson = JSON.stringify(result.content)
        setMessages(prev => prev.map(m =>
          m.id === assistantId
            ? { ...m, content: contentJson, finalized: true, isThinking: false }
            : m
        ))
      } else {
        const errorMsg = result.message || 'Something went wrong'
        setError(errorMsg)
        setMessages(prev => prev.map(m =>
          m.id === assistantId
            ? { ...m, content: JSON.stringify({ blocks: [{ type: 'text', content: errorMsg }] }), finalized: true, isThinking: false }
            : m
        ))
      }
    } catch (err) {
      const errorMsg = err.message || 'An error occurred'
      setError(errorMsg)
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, content: JSON.stringify({ blocks: [{ type: 'text', content: 'Sorry, something went wrong. Please try again.' }] }), finalized: true, isThinking: false }
          : m
      ))
    } finally {
      setIsStreaming(false)
    }
  }, [input, isStreaming, familyId, familyType])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Quick action buttons - different for general mode vs family mode
  const quickActions = isGeneralMode ? [
    { icon: '📚', label: 'Platform help', prompt: 'How do I use Chef Hub?' },
    { icon: '💳', label: 'Payment links', prompt: 'How do I send a payment link to a client?' },
    { icon: '🍳', label: 'Kitchen setup', prompt: 'How do I set up my kitchen with ingredients and dishes?' },
    { icon: '📅', label: 'Meal Shares', prompt: 'How do I create meal shares for multiple customers?' }
  ] : [
    { icon: '🍽️', label: 'Menu ideas', prompt: 'What should I make for this family this week?' },
    { icon: '⚠️', label: 'Allergies', prompt: 'What are the critical allergies I need to watch out for?' },
    { icon: '📊', label: 'Orders', prompt: "Show me what I've made for them before." },
    { icon: '👥', label: 'Family', prompt: 'Tell me about each household member and their dietary needs.' }
  ]

  const handleQuickAction = (prompt) => {
    if (isStreaming) return
    setInput(prompt)
    setTimeout(() => {
      handleSend()
    }, 100)
  }

  return (
    <div className="sc-chat">
      {/* Family Context Panel - only show in family mode */}
      {familyContext && !isGeneralMode && (
        <div className={`sc-context ${showContext ? 'sc-context--expanded' : ''}`}>
          <button className="sc-context-toggle" onClick={() => setShowContext(!showContext)}>
            <span className="sc-context-title">
              <span className="sc-context-icon">👨‍👩‍👧‍👦</span>
              {familyContext.family_name}
            </span>
            <svg
              className={`sc-context-chevron ${showContext ? 'sc-context-chevron--open' : ''}`}
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>

          {showContext && (
            <div className="sc-context-body">
              <div className="sc-context-row">
                <span className="sc-context-label">Household:</span>
                <span className="sc-context-value">{familyContext.household_size} members</span>
              </div>

              {familyContext.dietary_restrictions?.length > 0 && (
                <div className="sc-context-row">
                  <span className="sc-context-label">Dietary:</span>
                  <span className="sc-context-tags">
                    {familyContext.dietary_restrictions.map((d, i) => (
                      <span key={i} className="sc-tag sc-tag--diet">{d}</span>
                    ))}
                  </span>
                </div>
              )}

              {familyContext.allergies?.length > 0 && (
                <div className="sc-context-row">
                  <span className="sc-context-label">Allergies:</span>
                  <span className="sc-context-tags">
                    {familyContext.allergies.map((a, i) => (
                      <span key={i} className="sc-tag sc-tag--allergy">⚠️ {a}</span>
                    ))}
                  </span>
                </div>
              )}

              {familyContext.stats?.total_orders > 0 && (
                <div className="sc-context-row">
                  <span className="sc-context-label">History:</span>
                  <span className="sc-context-value">
                    {familyContext.stats.total_orders} orders • ${familyContext.stats.total_spent?.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Chat Header */}
      <div className="sc-chat-header">
        <div className="sc-chat-header-left">
          <span className="sc-chat-avatar">{chefEmoji}</span>
          <div>
            <h3 className="sc-chat-title">Sous Chef</h3>
            <span className="sc-chat-subtitle">
              {isGeneralMode
                ? 'General Assistant'
                : `Helping with ${familyName || 'this family'}`
              }
            </span>
          </div>
        </div>
        <button className="sc-btn sc-btn--outline sc-btn--sm" onClick={handleNewChat} disabled={isStreaming}>
          New Chat
        </button>
      </div>

      {/* Messages */}
      <div className="sc-messages">
        {historyLoading ? (
          <div className="sc-loading">
            <span className="sc-spinner" /> Loading...
          </div>
        ) : messages.length === 0 ? (
          <div className="sc-welcome">
            <div className="sc-welcome-content">
              <span className="sc-welcome-icon">{isGeneralMode ? '💡' : '🍳'}</span>
              <h3>How can I help you today?</h3>
              <p>
                {isGeneralMode
                  ? "I can help with platform questions, SOPs, prep planning, and more. Select a client for personalized meal planning."
                  : "I have full context about this family's dietary needs, allergies, and your history with them."
                }
              </p>

              {/* Quick Action Pills */}
              <div className="sc-quick-actions">
                {quickActions.map((action, idx) => (
                  <button
                    key={idx}
                    className="sc-quick-action"
                    onClick={() => handleQuickAction(action.prompt)}
                    disabled={isStreaming}
                  >
                    <span className="sc-quick-action-icon">{action.icon}</span>
                    <span className="sc-quick-action-label">{action.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <MessageBubble
                key={msg.id}
                role={msg.role}
                content={msg.content}
                onAction={onAction}
                finalized={msg.finalized}
                isThinking={msg.isThinking}
              />
            ))}
          </>
        )}

        {error && (
          <div className="sc-error">
            {error}
          </div>
        )}

        <div ref={endRef} />
      </div>

      {/* Input Area */}
      <div className="sc-composer">
        <div className="sc-composer-input-wrap">
          <textarea
            ref={(el) => {
              inputRef.current = el
              if (externalInputRef) externalInputRef.current = el
            }}
            className="sc-composer-input"
            rows={1}
            placeholder={isGeneralMode ? 'Ask Sous Chef anything...' : `Ask about ${familyName || 'this family'}...`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming || historyLoading}
          />
          <button
            className={`sc-send-btn ${input.trim() ? 'sc-send-btn--visible' : ''}`}
            onClick={handleSend}
            disabled={!input.trim() || isStreaming || historyLoading}
            aria-label="Send message"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
      </div>

      <style>{`
        /* ============================================
           SOUS CHEF CHAT - MODERN UI
           ============================================ */

        .sc-chat {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: var(--sc-surface-2, var(--surface-2, #f9fafb));
          border-radius: 16px;
          overflow: hidden;
          color: var(--text);
        }

        /* ─────────────────────────────────────────────
           CONTEXT PANEL (Collapsible)
           ───────────────────────────────────────────── */
        .sc-context {
          background: var(--sc-surface, var(--surface, #fff));
          border-bottom: 1px solid var(--sc-border, var(--border, #e5e7eb));
        }

        .sc-context-toggle {
          display: flex;
          justify-content: space-between;
          align-items: center;
          width: 100%;
          padding: 10px 14px;
          background: none;
          border: none;
          cursor: pointer;
          text-align: left;
          color: var(--text);
        }

        .sc-context-toggle:hover {
          background: var(--sc-surface-2, var(--surface-2, #f9fafb));
        }

        .sc-context-title {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
          font-size: 0.9rem;
        }

        .sc-context-icon {
          font-size: 1.1rem;
        }

        .sc-context-chevron {
          color: var(--muted);
          transition: transform 0.2s ease;
        }

        .sc-context-chevron--open {
          transform: rotate(180deg);
        }

        .sc-context-body {
          padding: 0 14px 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .sc-context-row {
          display: flex;
          gap: 8px;
          font-size: 0.8rem;
          align-items: flex-start;
        }

        .sc-context-label {
          color: var(--muted);
          min-width: 65px;
          flex-shrink: 0;
        }

        .sc-context-value {
          color: var(--text);
        }

        .sc-context-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
        }

        .sc-tag {
          padding: 2px 8px;
          border-radius: 12px;
          font-size: 0.7rem;
          font-weight: 500;
        }

        .sc-tag--diet {
          background: var(--success-bg);
          color: var(--success);
        }

        .sc-tag--allergy {
          background: var(--danger-bg);
          color: var(--danger);
        }

        /* ─────────────────────────────────────────────
           CHAT HEADER
           ───────────────────────────────────────────── */
        .sc-chat-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 14px 16px;
          background: var(--sc-surface, var(--surface, #fff));
          border-bottom: 1px solid var(--sc-border, var(--border, #e5e7eb));
        }

        .sc-chat-header-left {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .sc-chat-avatar {
          font-size: 1.75rem;
        }

        .sc-chat-title {
          margin: 0;
          font-size: 1rem;
          font-weight: 600;
          color: var(--text);
        }

        .sc-chat-subtitle {
          font-size: 0.75rem;
          color: var(--muted);
        }

        .sc-btn {
          padding: 6px 12px;
          border-radius: 6px;
          font-size: 0.8rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s ease;
          border: none;
        }

        .sc-btn--outline {
          background: transparent;
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          color: var(--text);
        }

        .sc-btn--outline:hover:not(:disabled) {
          border-color: var(--sc-primary, var(--primary, #7C9070));
          color: var(--sc-primary, var(--primary, #7C9070));
        }

        .sc-btn--sm {
          padding: 5px 10px;
          font-size: 0.75rem;
        }

        .sc-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* ─────────────────────────────────────────────
           MESSAGES AREA
           ───────────────────────────────────────────── */
        .sc-messages {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .sc-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          flex: 1;
          color: var(--muted);
          gap: 8px;
        }

        .sc-spinner {
          display: inline-block;
          width: 16px;
          height: 16px;
          border: 2px solid var(--sc-border, var(--border, #e5e7eb));
          border-top-color: var(--sc-primary, var(--primary, #7C9070));
          border-radius: 50%;
          animation: sc-spin 0.8s linear infinite;
        }

        @keyframes sc-spin {
          to { transform: rotate(360deg); }
        }

        /* ─────────────────────────────────────────────
           WELCOME STATE
           ───────────────────────────────────────────── */
        .sc-welcome {
          display: flex;
          align-items: center;
          justify-content: center;
          flex: 1;
        }

        .sc-welcome-content {
          text-align: center;
          max-width: 320px;
          padding: 20px;
        }

        .sc-welcome-icon {
          font-size: 2.5rem;
          display: block;
          margin-bottom: 12px;
        }

        .sc-welcome-content h3 {
          margin: 0 0 8px 0;
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--text);
        }

        .sc-welcome-content p {
          margin: 0;
          font-size: 0.85rem;
          color: var(--muted);
          line-height: 1.5;
        }

        /* ─────────────────────────────────────────────
           QUICK ACTION PILLS (Horizontal Scrollable)
           ───────────────────────────────────────────── */
        .sc-quick-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: center;
          margin-top: 16px;
        }

        .sc-quick-action {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 14px;
          background: var(--sc-surface, var(--surface, #fff));
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          border-radius: 20px;
          cursor: pointer;
          font-size: 0.8rem;
          transition: all 0.15s ease;
          color: var(--text);
        }

        .sc-quick-action:hover:not(:disabled) {
          border-color: var(--sc-primary, var(--primary, #7C9070));
          background: rgba(124, 144, 112, 0.08);
        }

        .sc-quick-action:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .sc-quick-action-icon {
          font-size: 1rem;
        }

        .sc-quick-action-label {
          font-weight: 500;
        }

        /* ─────────────────────────────────────────────
           MESSAGE BUBBLES (Modern Design)
           ───────────────────────────────────────────── */
        .sc-msg {
          display: flex;
        }

        .sc-msg--user {
          justify-content: flex-end;
        }

        .sc-msg--assistant {
          justify-content: flex-start;
        }

        .sc-bubble {
          max-width: min(80%, 700px);
          padding: 12px 16px;
          border-radius: 20px;
          word-wrap: break-word;
          line-height: 1.5;
        }

        .sc-bubble--user {
          background: var(--sc-primary, var(--primary, #7C9070));
          color: white;
          border-bottom-right-radius: 4px;
        }

        .sc-bubble--assistant {
          background: var(--sc-surface, var(--surface, #fff));
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          border-bottom-left-radius: 4px;
          color: var(--text);
        }

        /* Thinking Indicator (Three Dots) */
        .sc-thinking {
          display: flex;
          gap: 4px;
          padding: 4px 0;
        }

        .sc-thinking-dot {
          width: 8px;
          height: 8px;
          background: var(--sc-primary, var(--primary, #7C9070));
          border-radius: 50%;
          animation: sc-thinking-bounce 1.4s infinite ease-in-out both;
        }

        .sc-thinking-dot:nth-child(1) { animation-delay: -0.32s; }
        .sc-thinking-dot:nth-child(2) { animation-delay: -0.16s; }
        .sc-thinking-dot:nth-child(3) { animation-delay: 0s; }

        @keyframes sc-thinking-bounce {
          0%, 80%, 100% {
            transform: scale(0.6);
            opacity: 0.5;
          }
          40% {
            transform: scale(1);
            opacity: 1;
          }
        }

        /* Error Message */
        .sc-error {
          padding: 10px 14px;
          background: var(--danger-bg);
          color: var(--danger);
          border-radius: 8px;
          font-size: 0.85rem;
        }

        /* ─────────────────────────────────────────────
           COMPOSER (Input Area)
           ───────────────────────────────────────────── */
        .sc-composer {
          padding: 12px 16px;
          background: var(--sc-surface, var(--surface, #fff));
          border-top: 1px solid var(--sc-border, var(--border, #e5e7eb));
        }

        .sc-composer-input-wrap {
          display: flex;
          align-items: center;
          gap: 8px;
          background: var(--sc-surface-2, var(--surface-2, #f9fafb));
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          border-radius: 24px;
          padding: 4px 4px 4px 16px;
          transition: border-color 0.15s, box-shadow 0.15s;
        }

        .sc-composer-input-wrap:focus-within {
          border-color: var(--sc-primary, var(--primary, #7C9070));
          box-shadow: 0 0 0 3px rgba(124, 144, 112, 0.12);
        }

        .sc-composer-input {
          flex: 1;
          border: none;
          background: transparent;
          padding: 10px 0;
          font-family: inherit;
          font-size: 0.9rem;
          resize: none;
          outline: none;
          color: var(--text);
          min-height: 24px;
          max-height: 120px;
        }

        .sc-composer-input::placeholder {
          color: var(--muted);
        }

        .sc-composer-input:disabled {
          opacity: 0.6;
        }

        .sc-send-btn {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          border: none;
          background: var(--sc-primary, var(--primary, #7C9070));
          color: white;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          opacity: 0;
          transform: scale(0.8);
          transition: all 0.15s ease;
          flex-shrink: 0;
        }

        .sc-send-btn--visible {
          opacity: 1;
          transform: scale(1);
        }

        .sc-send-btn:hover:not(:disabled) {
          background: var(--sc-primary-hover, var(--primary-700, #4a9d4a));
        }

        .sc-send-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* ─────────────────────────────────────────────
           MARKDOWN CONTENT STYLING
           ───────────────────────────────────────────── */
        .sc-bubble--assistant .markdown-content {
          line-height: 1.6;
          color: var(--text);
          font-size: 0.9rem;
          word-break: break-word;
        }

        .sc-bubble--assistant .markdown-content p {
          color: var(--text);
          margin: 0.75em 0;
        }

        .sc-bubble--assistant .markdown-content p:first-child {
          margin-top: 0;
        }

        .sc-bubble--assistant .markdown-content p:last-child {
          margin-bottom: 0;
        }

        .sc-bubble--assistant .markdown-content h1,
        .sc-bubble--assistant .markdown-content h2,
        .sc-bubble--assistant .markdown-content h3,
        .sc-bubble--assistant .markdown-content h4 {
          color: var(--text);
          font-weight: 600;
          line-height: 1.3;
          margin-top: 1em;
          margin-bottom: 0.5em;
        }

        .sc-bubble--assistant .markdown-content h1:first-child,
        .sc-bubble--assistant .markdown-content h2:first-child,
        .sc-bubble--assistant .markdown-content h3:first-child {
          margin-top: 0;
        }

        .sc-bubble--assistant .markdown-content ul,
        .sc-bubble--assistant .markdown-content ol {
          margin: 0.75em 0;
          padding-left: 1.5em;
          color: var(--text);
        }

        .sc-bubble--assistant .markdown-content li {
          color: var(--text);
          margin: 0.35em 0;
        }

        .sc-bubble--assistant .markdown-content strong {
          color: var(--text);
          font-weight: 700;
        }

        .sc-bubble--assistant .markdown-content code {
          background: var(--sc-surface-2, var(--surface-2, #f3f4f6));
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          padding: 0.15em 0.4em;
          border-radius: 4px;
          font-size: 0.85em;
          font-family: 'SF Mono', Consolas, monospace;
          color: var(--text);
        }

        .sc-bubble--assistant .markdown-content pre {
          background: var(--sc-surface-2, var(--surface-2, #f3f4f6));
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          border-radius: 8px;
          padding: 12px;
          margin: 0.75em 0;
          overflow-x: auto;
        }

        .sc-bubble--assistant .markdown-content pre code {
          background: transparent;
          border: none;
          padding: 0;
          font-size: 0.85em;
        }

        .sc-bubble--assistant .markdown-content blockquote {
          margin: 0.75em 0;
          padding: 0.5em 0 0.5em 1em;
          border-left: 3px solid var(--sc-primary, var(--primary, #7C9070));
          background: rgba(124, 144, 112, 0.06);
          border-radius: 0 6px 6px 0;
          color: var(--muted);
        }

        .sc-bubble--assistant .markdown-content table {
          border-collapse: collapse;
          margin: 0.75em 0;
          font-size: 0.85em;
          width: 100%;
        }

        .sc-bubble--assistant .markdown-content th {
          background: var(--sc-surface-2, var(--surface-2, #f3f4f6));
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          padding: 8px 12px;
          color: var(--text);
          font-weight: 600;
          text-align: left;
        }

        .sc-bubble--assistant .markdown-content td {
          border: 1px solid var(--sc-border, var(--border, #e5e7eb));
          padding: 8px 12px;
          color: var(--text);
        }

        .sc-bubble--assistant .markdown-content > *:first-child {
          margin-top: 0 !important;
        }

        .sc-bubble--assistant .markdown-content > *:last-child {
          margin-bottom: 0 !important;
        }

        /* ─────────────────────────────────────────────
           LARGE SCREEN RESPONSIVE - MESSAGE BUBBLES
           ───────────────────────────────────────────── */

        /* Large screens - allow wider bubbles but cap absolute width */
        @media (min-width: 1600px) {
          .sc-bubble {
            max-width: min(75%, 800px);
          }
        }

        @media (min-width: 1920px) {
          .sc-bubble {
            max-width: min(70%, 900px);
          }
        }

        @media (min-width: 2400px) {
          .sc-bubble {
            max-width: min(65%, 1000px);
          }
        }
      `}</style>
    </div>
  )
}

/**
 * Message bubble component with structured content rendering.
 */
function MessageBubble({ role, content, finalized, isThinking, onAction }) {
  const isUser = role === 'chef'

  return (
    <div className={`sc-msg ${isUser ? 'sc-msg--user' : 'sc-msg--assistant'}`}>
      <div className={`sc-bubble ${isUser ? 'sc-bubble--user' : 'sc-bubble--assistant'} ${!finalized ? 'streaming' : ''}`}>
        {isUser ? (
          <div>{content}</div>
        ) : isThinking ? (
          <div className="sc-thinking">
            <span className="sc-thinking-dot"></span>
            <span className="sc-thinking-dot"></span>
            <span className="sc-thinking-dot"></span>
          </div>
        ) : (
          <StructuredContent content={content} onAction={onAction} />
        )}
      </div>
    </div>
  )
}
