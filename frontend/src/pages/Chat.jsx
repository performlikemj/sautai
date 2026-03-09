import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, refreshAccessToken, buildErrorMessage } from '../api'
import { jwtDecode } from 'jwt-decode'
import ResponseView from '../components/ResponseView.jsx'

// Minimal sanitize schema that permits common Markdown + tables
const mdSanitize = {
  tagNames: [
    'p','strong','em','del','a','ul','ol','li','code','pre','blockquote','hr',
    'table','thead','tbody','tr','th','td'
  ],
  attributes: {
    a: ['href','title','target','rel'],
    code: ['className'],
    th: ['align'],
    td: ['align'],
    table: ['className']
  },
  protocols: {
    href: ['http','https','mailto','tel']
  }
}

// Streaming chat UI using Vercel AI SDK's useChat for state, wired to backend SSE
export default function Chat(){
  const [params] = useSearchParams()
  const initialThread = params.get('thread')
  const initialChef = params.get('chef') || ''
  const initialTopic = params.get('topic') || ''
  const initialMealId = params.get('meal_id') || ''
  const initialQuery = params.get('q') || ''
  const [threadId, setThreadId] = useState(initialThread)
  // Standardize continuation id as response_id; seed from thread when present
  const [responseId, setResponseId] = useState(initialThread || null)
  // Persisted guest session id for unauth flows
  const [guestId, setGuestId] = useState(() => localStorage.getItem('guestId') || '')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [aborter, setAborter] = useState(null)
  const useDedup = true
  const [toolEvents, setToolEvents] = useState([]) // {id,name,status,output}
  // Track the current assistant bubble id for this turn so we can scope tool chips
  const [currentTurnId, setCurrentTurnId] = useState(null)

  // Friendly labels for tool names (parity with Streamlit UI)
  const TOOL_NAME_MAP = useMemo(() => ({
    update_chef_meal_order: 'Updating your chef meal order',
    generate_payment_link: 'Generating a payment link',
    determine_items_to_replenish: 'Determining items to replenish',
    set_emergency_supply_goal: 'Setting your emergency supply goal',
    get_user_summary: 'Getting your health summary',
    create_meal_plan: 'Creating your meal plan',
    modify_meal_plan: 'Modifying your meal plan',
    get_meal_plan: 'Fetching your meal plan',
    email_generate_meal_instructions: 'Generating meal instructions for email',
    stream_meal_instructions: 'Streaming meal instructions',
    stream_bulk_prep_instructions: 'Streaming bulk prep instructions',
    get_meal_plan_meals_info: "Getting meal plan's meal information",
    find_related_youtube_videos: 'Finding related YouTube videos',
    get_meal_macro_info: 'Getting meal macro information',
    update_user_settings: 'Updating your user settings',
    get_user_settings: 'Getting your user settings',
    get_current_date: 'Checking the current date',
    list_upcoming_meals: 'Finding your upcoming meals',
    find_nearby_supermarkets: 'Finding nearby supermarkets',
    check_pantry_items: 'Checking your pantry items',
    add_pantry_item: 'Adding item to your pantry',
    list_dietary_preferences: "Checking all of sautai's dietary preferences",
    check_allergy_alert: 'Checking for possible allergens',
    suggest_alternatives: 'Suggesting alternatives meals',
    get_expiring_items: 'Finding expiring items',
    generate_shopping_list: 'Generating your shopping list',
    find_local_chefs: 'Finding local chefs',
    get_chef_details: 'Getting chef details',
    view_chef_meals: 'Viewing chef meals',
    place_chef_meal_order: 'Placing your chef meal order',
    get_order_details: 'Getting order details',
    cancel_order: 'Cancelling your order',
    create_payment_link: 'Creating payment link',
    check_payment_status: 'Checking payment status',
    process_refund: 'Processing refund',
    manage_dietary_preferences: 'Managing dietary preferences',
    check_meal_compatibility: 'Checking meal compatibility',
    adjust_week_shift: 'Adjusting the week view',
    reset_current_week: 'Resetting the week view',
    update_goal: 'Updating your goal',
    get_goal: 'Getting your goal information',
    access_past_orders: 'Accessing past orders',
    guest_search_dishes: 'Searching for dishes',
    guest_search_chefs: 'Searching for chefs',
    guest_get_meal_plan: 'Getting meal plan information',
    guest_search_ingredients: 'Searching ingredients',
    chef_service_areas: 'Checking chef service areas',
  }), [])

  const friendlyToolName = (raw) => {
    if (!raw || typeof raw !== 'string') return 'tool'
    return TOOL_NAME_MAP[raw] || raw.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }

  const endRef = useRef(null)
  const baseURL = useMemo(()=> api?.defaults?.baseURL || '', [])

  // useChat manages messages and input locally (UI-only usage)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState(initialQuery || '')
  const stop = ()=> aborter?.abort()
  const handleInputChange = (e)=> setInput(e.target.value)

  // Load existing history when a thread is specified
  useEffect(()=>{
    let mounted = true
    if (initialThread){
      api.get(`/customer_dashboard/api/thread_detail/${initialThread}/`).then(res => {
        if (!mounted) return
        const raw = res.data.chat_history || []
        raw.sort((a,b)=> new Date(a.created_at) - new Date(b.created_at))
        setMessages(raw.map((m, idx) => ({ id: `hist-${idx}`, role: m.role, content: m.content, finalized: true })))
      }).catch(()=>{})
    }
    return ()=>{ mounted = false }
  }, [initialThread, setMessages])

  // Auto-scroll as new content arrives
  useEffect(()=>{
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isStreaming])

  const newChat = async ()=>{
    stop()
    aborter?.abort()
    setAborter(null)
    // Ask backend to reset conversation so the next SSE ignores any id once
    try{
      const hasToken = Boolean(localStorage.getItem('accessToken'))
      if (hasToken){
        try { await refreshAccessToken() } catch {}
        const token = localStorage.getItem('accessToken') || ''
        await fetch('/customer_dashboard/api/assistant/new-conversation/', {
          method:'POST',
          headers: { 'Content-Type':'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          credentials: 'include'
        })
      } else {
        await fetch('/customer_dashboard/api/assistant/guest-new-conversation/', {
          method:'POST',
          headers: { 'Content-Type':'application/json', 'Accept':'application/json' },
          credentials: 'include'
        })
      }
    }catch{ /* non-fatal; still reset locally */ }

    // Local reset
    setMessages([])
    setThreadId(null)
    setResponseId(null)
    setInput('')
    setError(null)
    setToolEvents([])
  }

  // Ensure we have a guest id for onboarding/guest streaming
  async function ensureGuestId(){
    try{
      const existing = localStorage.getItem('guestId') || guestId
      if (existing) return existing
      const resp = await fetch('/customer_dashboard/api/assistant/onboarding/new-conversation/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'include'
      })
      if (resp.ok){
        let gid = ''
        try{ const data = await resp.json(); gid = data?.guest_id || '' }catch{ /* ignore */ }
        if (!gid){ gid = resp.headers.get('X-Guest-ID') || '' }
        if (gid){ localStorage.setItem('guestId', gid); setGuestId(gid); return gid }
      }
    }catch{ /* best-effort */ }
    return localStorage.getItem('guestId') || guestId || ''
  }

  async function sendMessage(){
    const text = input.trim()
    if (!text || isStreaming) return
    setError(null)
    setInput('')

    // Show user message
    setMessages(prev => [...prev, { id: `u-${Date.now()}`, role: 'user', content: text, finalized: true }])

    // Prepare streaming assistant message placeholder
    const assistantId = `a-${Date.now()}`
    setCurrentTurnId(assistantId)
    // Reset tool chips for this turn
    setToolEvents([])
    setMessages(prev => [...prev, { id: assistantId, role: 'assistant', content: '', finalized: false }])

    const controller = new AbortController()
    setAborter(controller)
    setIsStreaming(true)

    try{
      const hasToken = Boolean(localStorage.getItem('accessToken'))

      // Build body per contract
      const baseBody = { message: text }
      // Include user_id for backend parity with Streamlit (some tools expect it)
      try{
        const t = localStorage.getItem('accessToken')
        if (t){ const claims = jwtDecode(t); const uid = claims?.user_id; if (uid) baseBody.user_id = uid }
      }catch{}
      if (initialChef) baseBody.chef_username = initialChef
      if (initialTopic) baseBody.topic = initialTopic
      if (initialMealId) baseBody.meal_id = initialMealId

      let url = '/customer_dashboard/api/assistant/stream-message/'
      let body = { ...baseBody }
      let token = ''

      if (hasToken){
        // Auth: continuation key is thread_id
        if (responseId) baseBody.thread_id = responseId
        // Proactively refresh access token (handles cookie or refresh-token mode)
        try { await refreshAccessToken() } catch { /* ignore; may not have refresh */ }
        token = localStorage.getItem('accessToken') || ''
      } else {
        // Unauthenticated onboarding/guest flow
        const gid = await ensureGuestId()
        body.guest_id = gid
        // Guest/Onboarding: continuation key is response_id
        if (responseId) body.response_id = responseId
        // Prefer onboarding stream; fallback to guest-stream if unavailable
        url = '/customer_dashboard/api/assistant/onboarding/stream-message/'
      }

      async function doStream(streamUrl){
        const headers = {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        }
        const resp = await fetch(streamUrl, {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
          signal: controller.signal,
          credentials: 'include'
        })
        return resp
      }

      let resp = await doStream(url)

      // If authenticated and unauthorized, try one refresh-and-retry
      if (hasToken && resp.status === 401){
        try { await refreshAccessToken() } catch {}
        token = localStorage.getItem('accessToken') || ''
        resp = await doStream(url)
        if (resp.status === 401){
          try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: 'Please log in to chat.', tone:'error' } })) }catch{}
          throw new Error('Unauthorized')
        }
      }

      // For unauth flow, if onboarding stream not available, fallback to guest-stream
      if (!hasToken && !resp.ok && (resp.status === 404 || resp.status === 405)){
        url = '/customer_dashboard/api/assistant/guest-stream-message/'
        resp = await doStream(url)
      }

      if (!resp.ok){
        throw new Error(`Request failed ${resp.status}`)
      }

      // Capture and persist guest id from headers if provided
      try{
        const gid = resp.headers.get('X-Guest-ID')
        if (gid && gid !== (localStorage.getItem('guestId')||'')){
          localStorage.setItem('guestId', gid)
          setGuestId(gid)
        }
      }catch{ /* ignore */ }

      // Stream and parse SSE
      const reader = resp.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const commitAppend = (delta)=>{
        if (!delta) return
        
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m
          const curr = m.content || ''
          const d = String(delta)
          // Defensive de-dup and idempotent updates
          if (d === curr) return m
          if (d.startsWith(curr)){
            return { ...m, content: d }
          }
          if (curr && (curr.endsWith(d) || curr.includes(d))){
            return m
          }
          if (curr && d.includes(curr)){
            const idx = d.lastIndexOf(curr)
            const suffix = d.slice(idx + curr.length)
            return { ...m, content: curr + suffix }
          }
          return { ...m, content: curr + d }
        }))
      }

      // Finalize-time normalization: only once per table block
      const normalizeMarkdownOnFinalize = (text)=>{
        try{
          const src = String(text||'')
          const lines = src.split('\n')
          const out = []
          let inTable = false
          for (let i=0; i<lines.length; i++){
            const line = lines[i]
            const isTableRow = /^\s*\|.*\|\s*$/.test(line)
            if (isTableRow){
              if (!inTable){
                // starting a new table block
                inTable = true
                if (out.length && out[out.length-1].trim() !== '') out.push('')
                out.push(line)
                const next = lines[i+1] || ''
                const hasSep = /^\s*\|?\s*:?-{3,}\s*(\|\s*:?-{3,}\s*)+\|?\s*$/.test(next)
                if (!hasSep){
                  const cols = line.split('|').filter(Boolean).length
                  if (cols > 1){
                    const sep = '|' + Array(cols).fill(' --- ').join('|') + '|'
                    out.push(sep)
                  }
                }
                continue
              } else {
                out.push(line)
                continue
              }
            } else {
              inTable = false
              out.push(line)
            }
          }
          const normalized = out.join('\n')
          
          return normalized
        }catch{ return String(text||'') }
      }

      const processEvent = (dataLine)=>{
        try{
          const json = JSON.parse(dataLine)
          const t = json?.type
          
          if (t === 'response.created' || t === 'response_id'){
            const rid = json?.id
            if (rid){
              setResponseId(rid)
              if (!threadId) setThreadId(rid)
            }
          } else if (t === 'response.output_text.delta'){
            const delta = json?.delta?.text || ''
            if (delta) commitAppend(delta)
          } else if (t === 'tool_result'){
            const callId = json?.tool_call_id || json?.id || `${json?.name||'tool'}-${assistantId}`
            const name = json?.name
            const output = json?.output
            if (callId || name){
              setToolEvents(prev => {
                // Prefer id match; if missing, match by name within this turn
                let idx = prev.findIndex(x => x.id === callId)
                const next = [...prev]
                if (idx >= 0){
                  next[idx] = { ...next[idx], status:'done', output }
                } else {
                  const byName = next.findIndex(x => x.turnId===assistantId && x.name===friendlyToolName(name||'tool') && x.status==='running')
                  if (byName >= 0){
                    next[byName] = { ...next[byName], id: callId, status:'done', output }
                  } else {
                    next.push({ id: callId, name: friendlyToolName(name || 'tool'), status:'done', output, turnId: assistantId })
                  }
                }
                return next
              })
            }
          } else if (t === 'response.function_call'){
            const name = json?.name
            const callId = json?.call_id || json?.id || `${name||'tool'}-${assistantId}`
            if (name){
              setToolEvents(prev => {
                // Deduplicate by id; if missing, dedupe by name within this turn
                if (prev.some(x => x.id === callId)) return prev
                if (prev.some(x => x.turnId===assistantId && x.name===friendlyToolName(name) && x.status==='running')) return prev
                return [...prev, { id: callId, name: friendlyToolName(name), status:'running', output: null, turnId: assistantId }]
              })
            }
          } else if (t === 'response.tool'){
            const name = json?.name
            if (name && name !== 'response.render'){
              const callId = json?.tool_call_id || json?.id || `${name}-${assistantId}`
              setToolEvents(prev => {
                if (prev.some(x => x.id === callId)) return prev
                if (prev.some(x => x.turnId===assistantId && x.name===friendlyToolName(name) && x.status==='running')) return prev
                return [...prev, { id: callId, name: friendlyToolName(name), status:'running', output: null, turnId: assistantId }]
              })
            }
            if (name === 'response.render'){
              const md = json?.output?.markdown || json?.output?.md || json?.output?.text || ''
              if (md){
                const normalized = normalizeMarkdownOnFinalize(md)
                setMessages(prev => prev.map(m => {
                  if (m.id !== assistantId) return m
                  return { ...m, content: normalized, finalized: true }
                }))
              }
            }
          } else if (t === 'response.completed'){
            // End of turn: mark the assistant message as finalized (Markdown render)
            setMessages(prev => prev.map(m => {
              if (m.id !== assistantId) return m
              const normalized = normalizeMarkdownOnFinalize(m.content)
              return { ...m, finalized: true, content: normalized }
            }))
            // Mark any running tools for this turn as done if backend omitted explicit tool_result
            setToolEvents(prev => prev.map(te => (te.turnId===assistantId && te.status==='running') ? ({ ...te, status:'done' }) : te))
            setCurrentTurnId(null)
          } else if (t === 'error'){
            throw new Error(json?.message || 'Stream error')
          } else if (t === 'text'){
            // Fallback compatibility: some emit simple {type:'text', content}
            const delta = json?.content || ''
            if (delta) commitAppend(delta)
          }
        }catch(e){
          // Ignore malformed lines
        }
      }

      while (true){
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Split by double newlines (SSE event delimiter)
        let idx
        while ((idx = buffer.indexOf('\n\n')) !== -1){
          const chunk = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          const lines = chunk.split('\n')
          for (const line of lines){
            const trimmed = line.trim()
            if (trimmed.startsWith('data: ')){
              const data = trimmed.slice(6)
              if (data) processEvent(data)
            }
          }
        }
      }

      // Finalize Markdown even if the server closed without an explicit completed event
      setMessages(prev => prev.map(m => {
        if (m.id !== assistantId) return m
        if (m.finalized) return m
        const normalized = normalizeMarkdownOnFinalize(m.content)
        return { ...m, finalized: true, content: normalized }
      }))
      setToolEvents(prev => prev.map(te => (te.turnId===assistantId && te.status==='running') ? ({ ...te, status:'done' }) : te))
      setCurrentTurnId(null)
    } catch (e){
      if (e?.name !== 'AbortError'){
        setError(e)
        // Show a global toast, consistent with the rest of the site
        try{
          const msg = typeof e === 'object' ? (e?.message || 'An unexpected error occurred. Please try again.') : String(e)
          window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: msg || 'An unexpected error occurred. Please try again.', tone:'error' } }))
        }catch{}
        // Keep a friendly inline assistant message in this turn
        setMessages(prev => prev.map(m => m.role === 'assistant' && m.content === '' ? ({ ...m, content: 'Sorry, something went wrong. Please try again.' }) : m))
      }
    } finally {
      setIsStreaming(false)
      setAborter(null)
      // Ensure assistant message finalizes to Markdown even on unexpected termination
      setMessages(prev => prev.map(m => {
        if (m.role !== 'assistant') return m
        if (m.finalized) return m
        return { ...m, finalized: true }
      }))
    }
  }

  // Optional: auto-send if q param provided
  useEffect(()=>{
    if (initialQuery && !responseId && messages.length === 0 && !isStreaming){
      // Defer to allow initial render
      const t = setTimeout(()=>{ sendMessage() }, 0)
      return ()=> clearTimeout(t)
    }
  // We intentionally exclude sendMessage from deps to avoid re-trigger
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onKeyDown = (e)=>{
    if (e.key === 'Enter' && !e.shiftKey){
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="page-chat">
      <div className="chat-header">
        <div className="left">
          <h2>Chat with sautai</h2>
          <div className="sub muted">Meal planning, nutrition, and local chef help</div>
        </div>
        <div className="right">
          <button className="btn btn-outline" onClick={newChat}>New chat</button>
        </div>
      </div>

      <div className="chat-surface card">
        <div className="messages" role="log" aria-live="polite">
          {messages.map(m => (
            <MessageBubble key={m.id} role={m.role} content={m.content} finalized={m.finalized} />
          ))}
          {isStreaming && toolEvents.filter(t => t.turnId===currentTurnId).length > 0 && (
            <div className="tool-row" role="status" aria-live="polite">
              {toolEvents.filter(t => t.turnId===currentTurnId).map(t => (
                <span key={t.id} className={`tool-chip ${t.status==='running' ? 'running' : 'done'}`}>
                  <span className="dot" />
                  <span className="tool-label">{t.name}</span>
                </span>
              ))}
            </div>
          )}
          {isStreaming && (
            <div className="typing-row"><span className="dot" /><span className="dot" /><span className="dot" /></div>
          )}
          <div ref={endRef} />
        </div>

        <div className="composer">
          <textarea
            className="textarea"
            rows={1}
            placeholder="Ask anything about meals, nutrition, or chefs…"
            value={input}
            onChange={handleInputChange}
            onKeyDown={onKeyDown}
            disabled={isStreaming}
          />
          <div className="composer-actions">
            {isStreaming ? (
              <button className="btn btn-outline" onClick={()=> aborter?.abort()}>
                Stop
              </button>
            ) : (
              <button className="btn btn-primary" onClick={sendMessage} disabled={!input.trim()}>
                Send
              </button>
            )}
          </div>
        </div>
        {/* Error text moved to global toast for consistency */}
      </div>
    </div>
  )
}

function MessageBubble({ role, content, finalized }){
  const isUser = role === 'user'
  return (
    <div className={`msg-row ${isUser ? 'right' : 'left'}`}>
      <div className={`bubble ${isUser ? 'user' : 'assistant'}`}>
        <div className="bubble-content">
          {isUser || !finalized ? (
            content
          ) : (
            <ResponseView>{content}</ResponseView>
          )}
        </div>
      </div>
    </div>
  )
}
