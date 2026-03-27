import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api, stripe } from '../api'
import { createOffering, deleteOffering } from '../api/servicesClient.js'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import { useConnections } from '../hooks/useConnections.js'

import ChefAllClients from '../components/ChefAllClients.jsx'
import ChefPrepPlanning from '../components/ChefPrepPlanning.jsx'
import ChefPaymentLinks from '../components/ChefPaymentLinks.jsx'
import ChefSurveys from '../components/ChefSurveys.jsx'
import SousChefWidget from '../components/SousChefWidget.jsx'
import WelcomeModal from '../components/souschef/WelcomeModal.jsx'
import OnboardingWizard from '../components/souschef/OnboardingWizard.jsx'
import { useOnboardingStatus } from '../hooks/useOnboarding.js'
import ServiceAreaPicker from '../components/ServiceAreaPicker.jsx'
import ServiceAreasModal, { getAreaSummary } from '../components/ServiceAreasModal.jsx'
import ChatPanel from '../components/ChatPanel.jsx'
import AnalyticsDrawer from '../components/AnalyticsDrawer.jsx'
import MealDetailSlideout from '../components/MealDetailSlideout.jsx'
import OnboardingChecklist from '../components/OnboardingChecklist.jsx'
import CalendlyMeetingModal from '../components/CalendlyMeetingModal.jsx'
import NavSection from '../components/NavSection.jsx'
import TodayDashboard from '../components/TodayDashboard.jsx'
import ChefInsightsDashboard from '../components/ChefInsightsDashboard.jsx'
import { SousChefNotificationProvider } from '../contexts/SousChefNotificationContext.jsx'
import { useMessaging } from '../context/MessagingContext.jsx'

// Contextual AI Suggestions
import { ChefContextProvider, useChefContextSafe } from '../contexts/ChefContextContext.jsx'
import { useSuggestions } from '../hooks/useSuggestions.js'
import GhostInput from '../components/GhostInput.jsx'
import GhostTextarea from '../components/GhostTextarea.jsx'
import { SuggestionIndicator } from '../components/SuggestionBadge.jsx'
import ScaffoldPreview from '../components/ScaffoldPreview.jsx'
import { useScaffold } from '../hooks/useScaffold.js'
import { bucketOrderStatus, buildOrderSearchText, filterOrders, paginateOrders } from '../utils/chefOrders.mjs'
import { resolveSousChefNavigation, resolveSousChefPrefillTarget } from '../utils/sousChefNavigation.mjs'
import MehkoEnrollmentPanel from '../components/MehkoEnrollmentPanel.jsx'

function toArray(payload){
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.results)) return payload.results
  if (Array.isArray(payload?.details?.results)) return payload.details.results
  if (Array.isArray(payload?.details)) return payload.details
  if (Array.isArray(payload?.data?.results)) return payload.data.results
  if (Array.isArray(payload?.data)) return payload.data
  if (Array.isArray(payload?.items)) return payload.items
  if (Array.isArray(payload?.events)) return payload.events
  if (Array.isArray(payload?.orders)) return payload.orders
  return []
}

const SERVICE_TYPES = [
  { value: 'home_chef', label: 'In-Home Chef' },
  { value: 'weekly_prep', label: 'Weekly Meal Prep' }
]

const INITIAL_SERVICE_FORM = {
  id: null,
  service_type: 'home_chef',
  title: '',
  description: '',
  default_duration_minutes: '',
  max_travel_miles: '',
  notes: '',
  targetCustomerIds: []
}

const INITIAL_TIER_FORM = {
  id: null,
  offeringId: null,
  household_min: '',
  household_max: '',
  currency: 'usd',
  price: '',
  is_recurring: false,
  recurrence_interval: 'week',
  active: true,
  display_label: ''
}

const SERVICES_ROOT = '/services'

function parseServiceDate(dateStr = '', timeStr = ''){
  if (!dateStr) return null
  try{
    let normalizedTime = timeStr
    if (normalizedTime && normalizedTime.length === 5) normalizedTime += ':00'
    const iso = `${dateStr}T${normalizedTime || '00:00:00'}`
    const dt = new Date(iso)
    if (Number.isNaN(dt.valueOf())) return null
    return dt
  }catch{
    return null
  }
}

function formatServiceSchedule(order = {}){
  const dt = parseServiceDate(order.service_date, order.service_start_time)
  if (dt){
    try{
      const dateFormatter = new Intl.DateTimeFormat(undefined, { month:'short', day:'numeric', year:'numeric' })
      const timeFormatter = new Intl.DateTimeFormat(undefined, { hour:'numeric', minute:'2-digit' })
      const dateLabel = dateFormatter.format(dt)
      const timeLabel = order.service_start_time ? timeFormatter.format(dt) : null
      return timeLabel ? `${dateLabel} · ${timeLabel}` : dateLabel
    }catch{}
  }
  if (order.service_date){
    return order.service_start_time ? `${order.service_date} · ${order.service_start_time}` : order.service_date
  }
  const prefs = order.schedule_preferences
  if (prefs && typeof prefs === 'object'){
    const note = prefs.notes || prefs.preferred_weekday || prefs.preferred_time || ''
    if (note) return String(note)
  }
  return 'Schedule to be arranged'
}

function toCurrencyDisplay(amount, currency = 'USD'){
  if (amount == null) return ''
  let value = amount
  if (typeof value === 'string'){
    const numeric = Number(value)
    if (!Number.isNaN(numeric)) value = numeric
  }
  if (typeof value === 'number' && !Number.isNaN(value)){
    try{
      return new Intl.NumberFormat(undefined, { style:'currency', currency: String(currency||'USD').toUpperCase(), maximumFractionDigits:2 }).format(value)
    }catch{}
    return `$${value.toFixed(2)}`
  }
  return String(amount)
}

function serviceStatusTone(status){
  const normalized = String(status || '').toLowerCase()
  if (['paid','completed','confirmed','active'].includes(normalized)){
    return { label: normalized === 'paid' ? 'Paid' : normalized.charAt(0).toUpperCase()+normalized.slice(1), style: { background:'var(--success-bg)', color:'var(--success)' } }
  }
  if (['awaiting_payment','pending','draft','open'].includes(normalized)){
    return { label: normalized.replace('_',' '), style: { background:'var(--warning-bg)', color:'var(--warning)' } }
  }
  if (['cancelled','canceled','refund_pending','failed'].includes(normalized)){
    return { label: normalized.charAt(0).toUpperCase()+normalized.slice(1).replace('_',' '), style: { background:'var(--danger-bg)', color:'var(--danger)' } }
  }
  return { label: status || 'Unknown', style: { background:'var(--neutral-bg)', color:'var(--neutral)' } }
}

function extractTierLabel(order = {}){
  const tier = order.tier || {}
  return tier.display_label || order.tier_display_label || order.tier_label || order.tier_name || ''
}

function serviceCustomerName(order = {}, detail = null){
  const customer = detail || order.customer_details || order.customer_profile || {}

  const candidate = (...values)=>{
    for (const value of values){
      if (!value) continue
      if (typeof value === 'string'){
        const trimmed = value.trim()
        if (trimmed) return trimmed
      } else if (typeof value === 'number'){
        return String(value)
      } else if (Array.isArray(value)){
        const joined = value.filter(Boolean).map(v=> String(v).trim()).filter(Boolean).join(' ')
        if (joined) return joined
      }
    }
    return ''
  }

  const fullName = candidate(
    order.customer_display_name,
    order.customer_name,
    order.customer_full_name,
    candidate(order.customer_first_name, order.customer_last_name),
    customer.full_name,
    customer.display_name,
    candidate(customer.first_name, customer.last_name)
  )

  const secondary = candidate(
    order.customer_username,
    customer.username,
    order.customer_email,
    customer.email,
    order.customer || order.customer_id || customer.id
  )

  if (fullName && secondary){
    const lowered = fullName.toLowerCase()
    const secondaryStr = String(secondary)
    if (!lowered.includes(secondaryStr.toLowerCase())){
      return `${fullName} (${secondaryStr})`
    }
    return fullName
  }
  if (fullName) return fullName
  if (secondary){
    return typeof secondary === 'number' ? `Customer #${secondary}` : String(secondary)
  }
  return 'Customer'
}

function serviceOfferingTitle(order = {}){
  return order.offering_title || order.offering?.title || order.service_title || 'Service'
}

function parseIsoDate(value){
  if (!value) return null
  const dt = new Date(value)
  if (Number.isNaN(dt.valueOf())) return null
  return dt
}

function formatMealSchedule(order = {}){
  const details = order.meal_event_details || order.event_details || {}
  const dateStr = details.event_date || order.event_date || order.delivery_date || order.scheduled_date || ''
  const timeStr = details.event_time || order.event_time || order.delivery_time || ''
  const dt = parseServiceDate(dateStr, timeStr) || parseIsoDate(details.event_datetime || order.event_datetime || order.scheduled_at || order.created_at || order.created)
  if (dt){
    try{
      const dateFormatter = new Intl.DateTimeFormat(undefined, { month:'short', day:'numeric', year:'numeric' })
      const timeFormatter = new Intl.DateTimeFormat(undefined, { hour:'numeric', minute:'2-digit' })
      const dateLabel = dateFormatter.format(dt)
      const timeLabel = timeStr ? timeFormatter.format(dt) : null
      return timeLabel ? `${dateLabel} · ${timeLabel}` : dateLabel
    }catch{}
  }
  if (dateStr){
    return timeStr ? `${dateStr} · ${timeStr}` : dateStr
  }
  return 'Schedule to be arranged'
}

function mealOrderTitle(order = {}){
  return order.meal_event_details?.meal_name || order.meal_name || order.meal?.name || 'Meal order'
}

function mealOrderCustomerName(order = {}){
  const name = pickFirstString(
    order.customer_display_name,
    order.customer_name,
    joinNames(order.customer_first_name, order.customer_last_name),
    order.customer_username,
    order.customer_email
  )
  if (name) return name
  const fallbackId = order.customer || order.customer_id
  if (fallbackId != null) return `Customer #${fallbackId}`
  return 'Customer'
}

function mealOrderContact(order = {}){
  return pickFirstString(order.customer_email, order.customer_username)
}

function mealOrderPriceLabel(order = {}){
  const amount = order.total_price ?? order.total_value_for_chef ?? order.price ?? order.amount
  if (amount == null || amount === '') return ''
  const currency = order.currency || order.order_currency || 'USD'
  return toCurrencyDisplay(amount, currency)
}

function getServiceOrderTimestamp(order = {}){
  const dt = parseServiceDate(order.service_date, order.service_start_time) || parseIsoDate(order.created_at || order.created)
  return dt ? dt.valueOf() : 0
}

function getMealOrderTimestamp(order = {}){
  const details = order.meal_event_details || order.event_details || {}
  const dt = parseServiceDate(
    details.event_date || order.event_date || order.delivery_date || '',
    details.event_time || order.event_time || order.delivery_time || ''
  ) || parseIsoDate(details.event_datetime || order.event_datetime || order.scheduled_at || order.created_at || order.created)
  return dt ? dt.valueOf() : 0
}


function flattenErrors(errors){
  if (!errors) return []
  if (typeof errors === 'string') return [errors]
  if (Array.isArray(errors)){
    return errors.flatMap(item => flattenErrors(item)).filter(Boolean)
  }
  if (typeof errors === 'object'){
    const entries = Object.entries(errors)
    return entries.flatMap(([key, value]) => {
      const prefix = key && key !== 'non_field_errors' ? `${key}: ` : ''
      return flattenErrors(value).map(msg => `${prefix}${msg}`)
    })
  }
  return [String(errors)]
}

function pickFirstString(...values){
  for (const value of values){
    if (typeof value === 'string'){
      const trimmed = value.trim()
      if (trimmed) return trimmed
    }
  }
  return null
}

function joinNames(first, last){
  const parts = []
  if (typeof first === 'string' && first.trim()) parts.push(first.trim())
  if (typeof last === 'string' && last.trim()) parts.push(last.trim())
  if (parts.length === 0) return null
  return parts.join(' ')
}

function connectionPartnerDetails(connection = {}, viewerRole = 'chef'){
  if (viewerRole === 'chef'){
    return connection.customer || connection.customer_profile || connection.customer_details || connection.customer_user || {}
  }
  return connection.chef || connection.chef_profile || connection.chef_details || connection.chef_user || {}
}

function connectionDisplayName(connection = {}, viewerRole = 'chef'){
  const normalizedRole = viewerRole === 'chef' ? 'chef' : 'customer'
  const partner = connectionPartnerDetails(connection, normalizedRole)
  const nameFromRecord = normalizedRole === 'chef'
    ? pickFirstString(
      connection.customer_display_name,
      connection.customer_full_name,
      connection.customer_name,
      joinNames(connection.customer_first_name, connection.customer_last_name),
      partner.full_name,
      partner.display_name,
      joinNames(partner.first_name, partner.last_name),
      partner.public_name,
      partner.name
    )
    : pickFirstString(
      connection.chef_display_name,
      connection.chef_full_name,
      connection.chef_name,
      joinNames(connection.chef_first_name, connection.chef_last_name),
      partner.full_name,
      partner.display_name,
      joinNames(partner.first_name, partner.last_name),
      partner.public_name,
      partner.name
    )

  if (nameFromRecord) return nameFromRecord

  const usernameFallback = normalizedRole === 'chef'
    ? pickFirstString(connection.customer_username, partner.username, connection.customer_email, partner.email)
    : pickFirstString(connection.chef_username, partner.username, connection.chef_email, partner.email)
  if (usernameFallback) return usernameFallback

  const fallbackId = normalizedRole === 'chef'
    ? (connection.customerId ?? connection.customer_id ?? partner?.id)
    : (connection.chefId ?? connection.chef_id ?? partner?.id)

  if (fallbackId != null){
    return normalizedRole === 'chef' ? `Customer #${fallbackId}` : `Chef #${fallbackId}`
  }
  return 'Connection'
}

function connectionInitiatedCopy(connection = {}){
  if (connection.viewerInitiated) return 'You sent this invitation'
  const role = String(connection?.initiated_by || '').toLowerCase()
  if (role === 'chef') return 'Chef sent the invitation'
  if (role === 'customer') return 'Customer sent the invitation'
  return ''
}

function formatConnectionStatus(status){
  const normalized = String(status || '').toLowerCase()
  if (!normalized) return 'Unknown'
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function FileSelect({ label, accept, onChange }){
  const inputRef = useRef(null)
  const [fileName, setFileName] = useState('')

  const handleClear = () => {
    setFileName('')
    if (inputRef.current) inputRef.current.value = ''
    onChange && onChange(null)
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{display:'none'}}
        onChange={(e)=>{
          const f = (e.target.files||[])[0] || null
          setFileName(f ? f.name : '')
          onChange && onChange(f)
        }}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: '.5rem', flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-outline btn-sm" onClick={()=> inputRef.current?.click()}>{label}</button>
        {fileName && (
          <>
            <span className="muted">{fileName}</span>
            <button
              type="button"
              className="file-clear-btn"
              onClick={handleClear}
              aria-label="Remove file"
              title="Remove file"
            >
              ×
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// Icon components (inline SVG)
const DashboardIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
const ProfileIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
const PhotosIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
const KitchenIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2v0a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg>
const ClientsIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
const ServicesIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
const ConnectionsIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="6" r="3"/><circle cx="19" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="M5 9v3a4 4 0 0 0 4 4h2"/><path d="M19 9v3a4 4 0 0 1-4 4h-2"/></svg>
const MealSharesIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
const OrdersIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M9 14l2 2 4-4"/></svg>
const MealsIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>
const PrepPlanIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="m9 14 2 2 4-4"/></svg>
const PaymentLinksIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/><path d="M7 15h4"/><path d="M15 15h2"/></svg>
const SurveysIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
const MessagesIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
const InsightsIcon = ()=> <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>

/**
 * ChefMessagesSection - Messages tab for chef dashboard
 */
function ChefMessagesSection() {
  const { conversations, conversationsLoading, fetchConversations, totalUnread } = useMessaging()
  const [chatOpen, setChatOpen] = useState(false)
  const [selectedConversation, setSelectedConversation] = useState(null)
  
  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])
  
  const handleOpenChat = (conversation) => {
    setSelectedConversation(conversation)
    setChatOpen(true)
  }
  
  const formatTime = (dateStr) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    const now = new Date()
    const isToday = date.toDateString() === now.toDateString()
    const yesterday = new Date(now)
    yesterday.setDate(yesterday.getDate() - 1)
    const isYesterday = date.toDateString() === yesterday.toDateString()
    
    if (isToday) {
      return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    }
    if (isYesterday) {
      return 'Yesterday'
    }
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
  
  return (
    <div>
      <header style={{marginBottom:'1.5rem', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
        <div>
          <h1 style={{margin:'0 0 .25rem 0'}}>Messages</h1>
          <p className="muted" style={{margin:0}}>Chat with your connected clients</p>
        </div>
        {totalUnread > 0 && (
          <span className="badge badge-primary">{totalUnread} unread</span>
        )}
      </header>
      
      <div className="card">
        {conversationsLoading && (
          <div style={{display:'flex', alignItems:'center', justifyContent:'center', padding:'3rem'}}>
            <div className="spinner" style={{width: 32, height: 32}} />
          </div>
        )}
        
        {!conversationsLoading && conversations.length === 0 && (
          <div className="chef-empty-state" style={{padding:'3rem', textAlign:'center'}}>
            <MessagesIcon />
            <p style={{margin:'1rem 0 0', fontWeight:600}}>No conversations yet</p>
            <p className="muted" style={{margin:'.5rem 0 0'}}>Messages from your clients will appear here</p>
          </div>
        )}
        
        {!conversationsLoading && conversations.length > 0 && (
          <div className="conversations-list">
            {conversations.map(conv => (
              <button
                key={conv.id}
                className="conversation-item"
                onClick={() => handleOpenChat(conv)}
              >
                <div className="conversation-avatar">
                  {conv.customer_photo ? (
                    <img src={conv.customer_photo} alt="" />
                  ) : (
                    <div className="conversation-avatar-placeholder">
                      <i className="fa-solid fa-user"></i>
                    </div>
                  )}
                </div>
                <div className="conversation-info">
                  <div className="conversation-header">
                    <span className="conversation-name">{conv.customer_name}</span>
                    <span className="conversation-time">{formatTime(conv.last_message_at)}</span>
                  </div>
                  <div className="conversation-preview">
                    {conv.last_message_preview || 'Start a conversation'}
                  </div>
                </div>
                {conv.unread_count > 0 && (
                  <span className="conversation-unread">{conv.unread_count}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
      
      {/* Chat Panel */}
      <ChatPanel
        isOpen={chatOpen}
        onClose={() => {
          setChatOpen(false)
          setSelectedConversation(null)
          fetchConversations() // Refresh after closing
        }}
        conversationId={selectedConversation?.id}
        recipientName={selectedConversation?.customer_name}
        recipientPhoto={selectedConversation?.customer_photo}
        onSwitchConversation={(newConvId, name, photo) => {
          // Find the conversation in our local list or create a minimal object
          const conv = conversations?.find(c => c.id === newConvId)
          setSelectedConversation(conv || { id: newConvId, customer_name: name, customer_photo: photo })
        }}
      />
    </div>
  )
}

function ChefDashboardContent(){
  const location = useLocation()
  const [tab, setTab] = useState(() => location.state?.tab || 'today')
  const [notice, setNotice] = useState(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  
  // Sub-tab state for merged tabs
  const [profileSubTab, setProfileSubTab] = useState('info') // 'info' | 'photos'
  const [menuSubTab, setMenuSubTab] = useState('ingredients') // 'ingredients' | 'dishes' | 'meals'
  const [servicesSubTab, setServicesSubTab] = useState('services') // 'services' | 'meal-shares'
  
  // Messaging for unread badge
  const { totalUnread } = useMessaging()
  
  // Analytics drawer state
  const [analyticsDrawer, setAnalyticsDrawer] = useState({ open: false, metric: null, title: '' })
  const openAnalyticsDrawer = (metric, title) => setAnalyticsDrawer({ open: true, metric, title })
  const closeAnalyticsDrawer = () => setAnalyticsDrawer(prev => ({ ...prev, open: false }))
  
  // Handle navigation state changes (e.g., clicking messages icon from navbar)
  useEffect(() => {
    if (location.state?.tab && location.state.tab !== tab) {
      setTab(location.state.tab)
    }
  }, [location.state?.tab])

  // Stripe Connect status
  const [payouts, setPayouts] = useState({ loading: true, has_account:false, is_active:false, needs_onboarding:false, account_id:null, continue_onboarding_url:null, disabled_reason:null, diagnostic:null })
  const [onboardingBusy, setOnboardingBusy] = useState(false)

  // Chef profile
  const [chef, setChef] = useState(null)
  const [profileForm, setProfileForm] = useState({ experience:'', bio:'', profile_pic:null, banner_image:null, calendly_url:'' })
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileInit, setProfileInit] = useState(false)
  const [initialLoadDone, setInitialLoadDone] = useState(false)
  const [bannerUpdating, setBannerUpdating] = useState(false)
  const [bannerJustUpdated, setBannerJustUpdated] = useState(false)
  const [profilePicPreview, setProfilePicPreview] = useState(null)
  const [bannerPreview, setBannerPreview] = useState(null)
  // Break state
  const [isOnBreak, setIsOnBreak] = useState(false)
  const [breakBusy, setBreakBusy] = useState(false)
  const [breakReason, setBreakReason] = useState('')
  // Go Live state
  const [goingLive, setGoingLive] = useState(false)

  // Verification meeting state (Calendly)
  const [meetingConfig, setMeetingConfig] = useState({
    loading: true,
    feature_enabled: false,
    is_required: false,
    calendly_url: null,
    meeting_title: null,
    meeting_description: null,
    status: 'not_scheduled',
    scheduled_at: null,
    completed_at: null,
    is_complete: false
  })
  const [calendlyModalOpen, setCalendlyModalOpen] = useState(false)

  // Service area management
  const [areaStatus, setAreaStatus] = useState(null) // { approved_areas, pending_requests, etc. }
  const [areaStatusLoading, setAreaStatusLoading] = useState(false)
  const [showAreaPicker, setShowAreaPicker] = useState(false)
  const [newAreaSelection, setNewAreaSelection] = useState([])
  const [areaRequestNotes, setAreaRequestNotes] = useState('')
  const [submittingAreaRequest, setSubmittingAreaRequest] = useState(false)
  const [areasModalOpen, setAreasModalOpen] = useState(false)

  // Chef photos
  const [photoForm, setPhotoForm] = useState({ image:null, title:'', caption:'', is_featured:false })
  const [photoUploading, setPhotoUploading] = useState(false)

  // Ingredients
  const [ingredients, setIngredients] = useState([])
  const [ingForm, setIngForm] = useState({ name:'', calories:'', fat:'', carbohydrates:'', protein:'' })
  const [ingLoading, setIngLoading] = useState(false)
  const [ingredientSearch, setIngredientSearch] = useState('')
  const [showAllIngredients, setShowAllIngredients] = useState(false)
  const INGREDIENT_INITIAL_LIMIT = 12
  const duplicateIngredient = useMemo(()=>{
    const a = String(ingForm.name||'').trim().toLowerCase()
    if (!a) return false
    return ingredients.some(i => String(i?.name||'').trim().toLowerCase() === a)
  }, [ingredients, ingForm.name])
  const areaSummary = useMemo(() => getAreaSummary(chef?.serving_postalcodes), [chef])
  const previewLocation = useMemo(() => {
    if (!areaSummary) return ''
    const city = areaSummary.primaryCity || ''
    const country = areaSummary.countryName || ''
    if (city && country) return `${city}, ${country}`
    return city || country || ''
  }, [areaSummary])

  // Dishes
  const [dishes, setDishes] = useState([])
  const [dishForm, setDishForm] = useState({ name:'', featured:false, ingredient_ids:[] })
  const [dishFilter, setDishFilter] = useState('')
  
  // UI state for create panels
  const [showIngredientForm, setShowIngredientForm] = useState(false)
  const [showDishForm, setShowDishForm] = useState(false)
  const [showMealForm, setShowMealForm] = useState(false)
  const [showEventForm, setShowEventForm] = useState(false)
  const [showServiceForm, setShowServiceForm] = useState(false)

  // Sous Chef action state - for navigation and form prefill
  const [pendingPrefill, setPendingPrefill] = useState(null)

  // Meals
  const [meals, setMeals] = useState([])
  const [mealForm, setMealForm] = useState({ name:'', description:'', meal_type:'Dinner', price:'', start_date:'', dishes:[], dietary_preferences:[] })
  const [mealSaving, setMealSaving] = useState(false)
  const [selectedMeal, setSelectedMeal] = useState(null)
  const [mealSlideoutOpen, setMealSlideoutOpen] = useState(false)

  // Events
  const [events, setEvents] = useState([])
  const [eventForm, setEventForm] = useState({ meal:null, event_date:'', event_time:'18:00', order_cutoff_date:'', order_cutoff_time:'12:00', base_price:'', min_price:'', max_orders:10, min_orders:1, description:'', special_instructions:'' })
  const [showPastEvents, setShowPastEvents] = useState(false)

  // Orders
  const [orders, setOrders] = useState([])
  const [serviceOrders, setServiceOrders] = useState([])
  const [serviceOrdersLoading, setServiceOrdersLoading] = useState(false)
  const [serviceCustomerDetails, setServiceCustomerDetails] = useState({})
  const serviceCustomerPending = useRef(new Set())
  const [focusedOrderId, setFocusedOrderId] = useState(null)
  const orderRefs = useRef({})
  const [orderQuery, setOrderQuery] = useState('')
  const [orderTypeFilter, setOrderTypeFilter] = useState('all')
  const [orderStatusFilter, setOrderStatusFilter] = useState('all')
  const [orderSort, setOrderSort] = useState('newest')
  const [orderPage, setOrderPage] = useState(1)
  const [orderPageSize, setOrderPageSize] = useState(6)

  const {
    connections,
    pendingConnections,
    acceptedConnections,
    declinedConnections,
    endedConnections,
    respondToConnection,
    refetchConnections,
    isLoading: connectionsLoading,
    requestError: connectionRequestError,
    respondError: connectionRespondError,
    respondStatus
  } = useConnections('chef')
  const [connectionActionId, setConnectionActionId] = useState(null)
  const connectionMutating = respondStatus === 'pending'

  // ═══════════════════════════════════════════════════════════════════════════════
  // Contextual AI Suggestions (Sous Chef)
  // ═══════════════════════════════════════════════════════════════════════════════
  
  const chefContext = useChefContextSafe()
  const { 
    suggestions, 
    priority: suggestionPriority, 
    hasSuggestions,
    fetchSuggestions,
    getSuggestionForField,
    acceptSuggestion,
    dismissSuggestion
  } = useSuggestions({ enabled: true })

  // Scaffold state for meal creation
  const {
    scaffold,
    isGenerating: isScaffoldGenerating,
    isExecuting: isScaffoldExecuting,
    isFetchingIngredients,
    includeIngredients,
    generateScaffold,
    toggleIngredients,
    updateScaffold,
    executeScaffold,
    clearScaffold
  } = useScaffold()
  const [showScaffoldPreview, setShowScaffoldPreview] = useState(false)

  // ═══════════════════════════════════════════════════════════════════════════════
  // Sous Chef Onboarding
  // ═══════════════════════════════════════════════════════════════════════════════

  const {
    shouldShowWelcome,
    shouldShowSetup,
    isSetupComplete,
    isLoading: onboardingLoading
  } = useOnboardingStatus({ enabled: !!chef })

  const [showWelcomeModal, setShowWelcomeModal] = useState(false)
  const [showOnboardingWizard, setShowOnboardingWizard] = useState(false)

  // Check if we should show onboarding modals
  useEffect(() => {
    // Skip if no chef or still loading or already onboarded via localStorage
    if (!chef || onboardingLoading) return
    if (localStorage.getItem('sous_chef_onboarded') === 'true') return

    // Show welcome modal if not welcomed
    if (shouldShowWelcome && !showWelcomeModal && !showOnboardingWizard) {
      setShowWelcomeModal(true)
    }
    // Show wizard if welcomed but setup not complete
    else if (shouldShowSetup && !showOnboardingWizard && !showWelcomeModal) {
      setShowOnboardingWizard(true)
    }
  }, [chef, onboardingLoading, shouldShowWelcome, shouldShowSetup, showWelcomeModal, showOnboardingWizard])

  const handleStartOnboarding = () => {
    setShowWelcomeModal(false)
    setShowOnboardingWizard(true)
  }

  const handleOnboardingComplete = () => {
    setShowOnboardingWizard(false)
    // Show a success notice
    setNotice('Setup complete! Sous Chef is ready to help.')
    setTimeout(() => setNotice(null), 4000)
  }

  const handleOnboardingClose = () => {
    setShowWelcomeModal(false)
    setShowOnboardingWizard(false)
  }

  // Track tab changes for context
  useEffect(() => {
    if (chefContext) {
      chefContext.setTab(tab)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])  // Don't include chefContext - it changes on every state update
  
  // Track form open/close for context AND fetch suggestions immediately
  useEffect(() => {
    if (!chefContext) return
    
    if (showDishForm) {
      chefContext.openForm('dish', dishForm)
      // Fetch suggestions immediately when form opens
      fetchSuggestions({
        currentTab: tab,
        openForms: [{ type: 'dish', fields: dishForm, completion: 0.1 }],
        recentActions: [],
        isIdle: false
      })
    } else {
      chefContext.closeForm('dish')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showDishForm, tab])  // Don't include chefContext
  
  useEffect(() => {
    if (!chefContext) return
    
    if (showMealForm) {
      chefContext.openForm('meal', mealForm)
      // Fetch suggestions immediately when form opens
      fetchSuggestions({
        currentTab: tab,
        openForms: [{ type: 'meal', fields: mealForm, completion: 0.1 }],
        recentActions: [],
        isIdle: false
      })
    } else {
      chefContext.closeForm('meal')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showMealForm, tab])  // Don't include chefContext
  
  // Also fetch suggestions when meal form values change significantly
  useEffect(() => {
    if (!showMealForm || !chefContext) return
    
    // Only fetch if we have some data filled in
    if (mealForm.name || mealForm.description) {
      const timeoutId = setTimeout(() => {
        fetchSuggestions({
          currentTab: tab,
          openForms: [{ type: 'meal', fields: mealForm, completion: 0.3 }],
          recentActions: [],
          isIdle: false
        })
      }, 800)  // Small delay to avoid spamming
      return () => clearTimeout(timeoutId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mealForm.name, mealForm.description, showMealForm, tab])  // Don't include chefContext
  
  useEffect(() => {
    if (!chefContext) return
    
    if (showEventForm) {
      chefContext.openForm('event', eventForm)
      fetchSuggestions({
        currentTab: tab,
        openForms: [{ type: 'event', fields: eventForm, completion: 0.1 }],
        recentActions: [],
        isIdle: false
      })
    } else {
      chefContext.closeForm('event')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showEventForm, tab])  // Don't include chefContext
  
  useEffect(() => {
    if (!chefContext) return
    
    if (showServiceForm) {
      chefContext.openForm('service', serviceForm)
      fetchSuggestions({
        currentTab: tab,
        openForms: [{ type: 'service', fields: serviceForm, completion: 0.1 }],
        recentActions: [],
        isIdle: false
      })
    } else {
      chefContext.closeForm('service')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showServiceForm, tab])  // Don't include chefContext
  // Get ghost values for forms
  const dishNameGhost = getSuggestionForField('dish', 'name')?.value || ''
  const mealNameGhost = getSuggestionForField('meal', 'name')?.value || ''
  const mealDescGhost = getSuggestionForField('meal', 'description')?.value || ''
  const serviceNameGhost = getSuggestionForField('service', 'title')?.value || ''
  const serviceDescGhost = getSuggestionForField('service', 'description')?.value || ''
  
  // Debug: Log when ghost values change
  useEffect(() => {
    if (mealNameGhost || mealDescGhost) {
      console.log('[SousChef] Ghost values available:', { mealNameGhost, mealDescGhost })
    }
  }, [mealNameGhost, mealDescGhost])

  // Chef services
  const [serviceOfferings, setServiceOfferings] = useState([])
  const [serviceLoading, setServiceLoading] = useState(false)
  const [serviceForm, setServiceForm] = useState(()=>({ ...INITIAL_SERVICE_FORM }))
  const [serviceSaving, setServiceSaving] = useState(false)
  const [serviceErrors, setServiceErrors] = useState(null)
  const [tierForm, setTierForm] = useState(()=>({ ...INITIAL_TIER_FORM }))
  const [tierSaving, setTierSaving] = useState(false)
  const [tierErrors, setTierErrors] = useState(null)
  const [deleteOfferingId, setDeleteOfferingId] = useState(null)
  const [deleteOfferingBusy, setDeleteOfferingBusy] = useState(false)
  const [editFormGlowKey, setEditFormGlowKey] = useState(0)
  const serviceErrorMessages = useMemo(()=> flattenErrors(serviceErrors), [serviceErrors])
  const tierErrorMessages = useMemo(()=> flattenErrors(tierErrors), [tierErrors])
  const tierSummaryExamples = useMemo(()=>{
    const summaries = []
    if (!Array.isArray(serviceOfferings)) return summaries
    for (const offering of serviceOfferings){
      const tierSummaries = Array.isArray(offering?.tier_summary) ? offering.tier_summary : []
      for (const summary of tierSummaries){
        const text = typeof summary === 'string' ? summary.trim() : String(summary || '').trim()
        if (!text) continue
        if (summaries.length < 4 && !summaries.includes(text)){
          summaries.push(text)
        }
        if (summaries.length >= 4){
          return summaries
        }
      }
    }
    return summaries
  }, [serviceOfferings])

  const todayISO = useMemo(()=> new Date().toISOString().slice(0,10), [])

  const acceptedCustomerOptions = useMemo(()=>{
    return acceptedConnections
      .map(connection => {
        const id = connection?.customerId ?? connection?.customer_id
        if (id == null) return null
        return { value: String(id), label: connectionDisplayName(connection, 'chef') }
      })
      .filter(Boolean)
  }, [acceptedConnections])

  // ═══════════════════════════════════════════════════════════════════════════════
  // Onboarding Checklist Completion State
  // ═══════════════════════════════════════════════════════════════════════════════
  const onboardingCompletionState = useMemo(() => ({
    profile: Boolean(chef?.bio && chef?.profile_pic_url),
    meeting: !meetingConfig.feature_enabled || !meetingConfig.is_required || meetingConfig.is_complete,
    kitchen: meals.length > 0 || dishes.length > 0,
    services: serviceOfferings.length > 0,
    photos: (chef?.photos?.length || 0) >= 3,
    payouts: payouts.is_active
  }), [chef, meals, dishes, serviceOfferings, payouts.is_active, meetingConfig])

  const isOnboardingComplete = useMemo(() => {
    return Object.values(onboardingCompletionState).every(Boolean)
  }, [onboardingCompletionState])

  const loadIngredients = async ()=>{
    setIngLoading(true)
    try{
      const resp = await api.get('/meals/api/ingredients/', { params: { chef_ingredients: 'true' } })
      setIngredients(toArray(resp.data))
    }catch{ setIngredients([]) } finally { setIngLoading(false) }
  }

  // Filtered and paginated ingredients for Kitchen tab
  const filteredIngredients = useMemo(() => {
    if (!ingredientSearch.trim()) return ingredients
    const q = ingredientSearch.toLowerCase()
    return ingredients.filter(i => i.name?.toLowerCase().includes(q))
  }, [ingredients, ingredientSearch])

  const displayedIngredients = useMemo(() => {
    if (showAllIngredients || ingredientSearch.trim()) return filteredIngredients
    return filteredIngredients.slice(0, INGREDIENT_INITIAL_LIMIT)
  }, [filteredIngredients, showAllIngredients, ingredientSearch])

  const hasMoreIngredients = filteredIngredients.length > INGREDIENT_INITIAL_LIMIT 
    && !showAllIngredients && !ingredientSearch.trim()

  const toggleMealDish = (dishId)=>{
    const id = String(dishId)
    setMealForm(prev => {
      const has = prev.dishes.includes(id)
      const nextDishes = has ? prev.dishes.filter(x => x !== id) : [...prev.dishes, id]
      return { ...prev, dishes: nextDishes }
    })
  }

  const renderDishChecklist = (idPrefix = 'dish')=>{
    if (!Array.isArray(dishes) || dishes.length === 0){
      return <div className="muted">No dishes yet.</div>
    }
    const trimmed = dishFilter.trim().toLowerCase()
    const filtered = trimmed ? dishes.filter(d => String(d.name || '').toLowerCase().includes(trimmed)) : dishes
    return (
      <div>
        <input
          type="search"
          value={dishFilter}
          onChange={e => setDishFilter(e.target.value)}
          placeholder="Filter dishes…"
          aria-label="Filter dishes"
          className="input"
          style={{marginTop:'.25rem', marginBottom:'.35rem'}}
        />
        <div className="dish-checklist" role="group" aria-label="Select dishes" style={{display:'flex', flexDirection:'column', gap:'.35rem', maxHeight:'220px', overflowY:'auto', paddingRight:'.25rem'}}>
          {filtered.map(d => {
            const dishId = String(d.id)
            const inputId = `${idPrefix}-${dishId}`
            return (
              <label key={dishId} htmlFor={inputId} style={{display:'flex', alignItems:'center', gap:'.4rem'}}>
                <input
                  id={inputId}
                  type="checkbox"
                  checked={mealForm.dishes.includes(dishId)}
                  onChange={()=> toggleMealDish(dishId)}
                />
                <span>{d.name}</span>
              </label>
            )
          })}
        </div>
        {filtered.length === 0 && <div className="muted" style={{marginTop:'.35rem'}}>No dishes match your filter.</div>}
      </div>
    )
  }

  async function loadStripeStatus(){
    try{
      const resp = await stripe.getStatus()
      const data = resp?.data || {}
      setPayouts({ loading:false, ...data })
    }catch(e){
      setPayouts(prev => ({ ...(prev || {}), loading:false }))
    }
  }

  const loadChefProfile = async (retries = 2)=>{
    try{
      const resp = await api.get('/chefs/api/me/chef/profile/', { skipUserId: true })
      const data = resp.data || null
      setChef(data)
      setIsOnBreak(Boolean(data?.is_on_break))
      setProfileForm({ experience: data?.experience || '', bio: data?.bio || '', profile_pic: null, banner_image: null, calendly_url: data?.calendly_url || '' })
    }catch(e){
      const status = e?.response?.status
      // Handle token/role propagation races: retry once after nudging user_details
      if ((status === 401 || status === 403) && retries > 0){
        try{ await api.get('/auth/api/user_details/', { skipUserId: true }) }catch{}
        await new Promise(r => setTimeout(r, 400))
        return loadChefProfile(retries - 1)
      }
      if (status === 403){ setNotice('You are not in Chef mode. Switch role to Chef to manage your profile.') }
      else if (status === 404){ setNotice('Chef profile not found. Your account may not be approved yet.') }
      setChef(null)
    } finally {
      setProfileInit(true)
    }
  }

  // Handle Sous Chef action blocks (navigation and form prefill)
  const handleSousChefAction = useCallback((action) => {
    if (action.action_type === 'navigate') {
      // Navigate to the specified tab (including sub-tabs)
      const target = resolveSousChefNavigation(action.payload || {})
      if (target.tab) setTab(target.tab)
      if (target.menuSubTab) setMenuSubTab(target.menuSubTab)
      if (target.servicesSubTab) setServicesSubTab(target.servicesSubTab)
      if (target.profileSubTab) setProfileSubTab(target.profileSubTab)
      const noticeLabel = target.label || action?.payload?.tab
      if (noticeLabel) {
        setNotice(`Navigated to ${noticeLabel}`)
      }
      setTimeout(() => setNotice(null), 3000)
    } 
    else if (action.action_type === 'prefill') {
      // Navigate to the appropriate tab first (including sub-tabs)
      const target = resolveSousChefPrefillTarget(action.payload || {})
      if (target.tab) setTab(target.tab)
      if (target.menuSubTab) setMenuSubTab(target.menuSubTab)
      if (target.servicesSubTab) setServicesSubTab(target.servicesSubTab)
      if (target.profileSubTab) setProfileSubTab(target.profileSubTab)
      
      // Store prefill data to be consumed by the effect below
      setPendingPrefill(action.payload)
    }
  }, [])

  // Effect to handle pending prefill data - opens form and populates fields
  useEffect(() => {
    if (!pendingPrefill) return
    
    const { form_type, fields } = pendingPrefill
    
    // Small delay to ensure we're on the right tab first
    const timer = setTimeout(() => {
      switch (form_type) {
        case 'ingredient':
          setIngForm({
            name: fields.name || '',
            calories: fields.calories || '',
            fat: fields.fat || '',
            carbohydrates: fields.carbohydrates || '',
            protein: fields.protein || ''
          })
          setShowIngredientForm(true)
          break
          
        case 'dish':
          setDishForm({
            name: fields.name || '',
            featured: fields.featured || false,
            ingredient_ids: fields.ingredient_ids || []
          })
          setShowDishForm(true)
          break
          
        case 'meal':
          setMealForm({
            name: fields.name || '',
            description: fields.description || '',
            meal_type: fields.meal_type || 'Dinner',
            price: fields.price || '',
            start_date: fields.start_date || '',
            dishes: fields.dishes || [],
            dietary_preferences: fields.dietary_preferences || []
          })
          setShowMealForm(true)
          break
          
        case 'event':
          setEventForm(prev => ({
            ...prev,
            event_date: fields.event_date || '',
            event_time: fields.event_time || '18:00',
            base_price: fields.base_price || '',
            max_orders: fields.max_orders || 10,
            description: fields.description || '',
            special_instructions: fields.special_instructions || ''
          }))
          setShowEventForm(true)
          break
          
        case 'service':
          setServiceForm(prev => ({
            ...prev,
            title: fields.title || '',
            description: fields.description || '',
            service_type: fields.service_type || 'home_chef',
            default_duration_minutes: fields.default_duration_minutes || '',
            notes: fields.notes || ''
          }))
          setShowServiceForm(true)
          break
      }
      
      // Clear the pending prefill
      setPendingPrefill(null)
      
      // Show success notice
      const formLabel = form_type?.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'item'
      setNotice(`Form pre-filled for new ${formLabel}`)
      setTimeout(() => setNotice(null), 3000)
    }, 100)
    
    return () => clearTimeout(timer)
  }, [pendingPrefill])

  // Load service area status
  const loadAreaStatus = useCallback(async () => {
    setAreaStatusLoading(true)
    try {
      const resp = await api.get('/local_chefs/api/chef/area-status/')
      setAreaStatus(resp.data || null)
    } catch (e) {
      console.warn('Failed to load area status:', e)
      setAreaStatus(null)
    } finally {
      setAreaStatusLoading(false)
    }
  }, [])

  // Submit new area request
  const submitAreaRequest = useCallback(async () => {
    if (submittingAreaRequest || newAreaSelection.length === 0) return
    
    setSubmittingAreaRequest(true)
    try {
      const areaIds = newAreaSelection.map(a => a.area_id || a.id)
      await api.post('/local_chefs/api/chef/area-requests/', {
        area_ids: areaIds,
        notes: areaRequestNotes
      })
      
      // Reset form and reload status
      setNewAreaSelection([])
      setAreaRequestNotes('')
      setShowAreaPicker(false)
      await loadAreaStatus()
      
      window.dispatchEvent(new CustomEvent('global-toast', { 
        detail: { text: 'Area request submitted! An admin will review it soon.', tone: 'success' } 
      }))
    } catch (e) {
      const msg = e?.response?.data?.error || 'Failed to submit request'
      window.dispatchEvent(new CustomEvent('global-toast', { 
        detail: { text: msg, tone: 'error' } 
      }))
    } finally {
      setSubmittingAreaRequest(false)
    }
  }, [submittingAreaRequest, newAreaSelection, areaRequestNotes, loadAreaStatus])

  // Cancel pending request
  const cancelAreaRequest = useCallback(async (requestId) => {
    if (!window.confirm('Cancel this area request?')) return
    
    try {
      await api.delete(`/local_chefs/api/chef/area-requests/${requestId}/cancel/`)
      await loadAreaStatus()
      window.dispatchEvent(new CustomEvent('global-toast', { 
        detail: { text: 'Request cancelled', tone: 'success' } 
      }))
    } catch (e) {
      window.dispatchEvent(new CustomEvent('global-toast', { 
        detail: { text: 'Failed to cancel request', tone: 'error' } 
      }))
    }
  }, [loadAreaStatus])

  const toggleBreak = async (nextState)=>{
    if (breakBusy) return
    // Confirm enabling
    if (nextState && !window.confirm('This will cancel upcoming meal shares and refund paid orders. Continue?')){
      return
    }
    setBreakBusy(true)
    try{
      const payload = nextState ? { is_on_break: true, reason: breakReason || 'Chef is going on break' } : { is_on_break: false }
      const resp = await api.post('/chefs/api/me/chef/break/', payload, { timeout: 60000 })
      const data = resp?.data || {}
      setIsOnBreak(Boolean(data?.is_on_break))
      if (nextState){
        const cancelled = Number(data?.cancelled_events||0)
        const refunded = Number(data?.refunds_processed||0)
        const failed = Number(data?.refunds_failed||0)
        const hasErrors = Array.isArray(data?.errors) && data.errors.length>0
        const summary = `You're now on break. Cancelled ${cancelled} meal shares; refunds processed ${refunded}.`
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: summary, tone: failed>0||hasErrors?'error':'success' } })) }catch{}
      } else {
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: `Break disabled. You can create new meal shares now.`, tone:'success' } })) }catch{}
      }
      // Refresh profile in background
      loadChefProfile()
    }catch(e){
      const status = e?.response?.status
      if (status === 403){
        const ok = window.confirm('You are not in Chef mode. Switch role to Chef?')
        if (ok){ try{ await switchToChef() }catch{} }
      } else {
        try{
          const { buildErrorMessage } = await import('../api')
          const msg = buildErrorMessage(e?.response?.data, 'Unable to update break status', status)
          window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
        }catch{
          window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: 'Unable to update break status', tone:'error' } }))
        }
      }
    } finally { setBreakBusy(false) }
  }

  const switchToChef = async ()=>{
    try{ await api.post('/auth/api/switch_role/', { role:'chef' }); setNotice(null); await loadChefProfile() }catch{ setNotice('Unable to switch role to Chef.') }
  }

  const handleGoLive = async () => {
    if (goingLive) return
    setGoingLive(true)
    try {
      await api.post('/chefs/api/me/chef/live/', { is_live: true })
      // Refresh chef data to get updated is_live status
      await loadChefProfile()
      try {
        window.dispatchEvent(new CustomEvent('global-toast', {
          detail: { text: 'Congratulations! Your profile is now live!', tone: 'success' }
        }))
      } catch {}
    } catch (e) {
      const errorData = e?.response?.data || {}
      const message = errorData.message || 'Failed to go live. Please try again.'
      try {
        window.dispatchEvent(new CustomEvent('global-toast', {
          detail: { text: message, tone: 'error' }
        }))
      } catch {}
    } finally {
      setGoingLive(false)
    }
  }

  const loadDishes = async ()=>{
    try{ const resp = await api.get('/meals/api/dishes/', { params: { chef_dishes:'true' } }); setDishes(toArray(resp.data)) }catch{ setDishes([]) }
  }

  const loadMeals = async ()=>{
    try{ const resp = await api.get('/meals/api/meals/'); setMeals(toArray(resp.data)) }catch{ setMeals([]) }
  }

  const loadEvents = async ()=>{
    try{ 
      const resp = await api.get('/meals/api/chef-meal-events/', { params: { my_events:'true' } }); 
      const list = toArray(resp.data)
      setEvents(list) 
    }catch(e){ console.warn('[ChefDashboard] Load my events failed', { status: e?.response?.status, data: e?.response?.data }); setEvents([]) }
  }

  const loadOrders = async ()=>{
    try{ const resp = await api.get('/meals/api/chef-meal-orders/', { params: { as_chef: 'true' } }); setOrders(toArray(resp.data)) }catch{ setOrders([]) }
  }

  const loadServiceOrders = async ()=>{
    setServiceOrdersLoading(true)
    try{
      const resp = await api.get(`${SERVICES_ROOT}/my/orders/`)
      setServiceOrders(toArray(resp.data))
    }catch{
      setServiceOrders([])
    }finally{
      setServiceOrdersLoading(false)
    }
  }

  useEffect(()=>{
    if (!Array.isArray(serviceOrders) || serviceOrders.length === 0) return
    const ids = Array.from(new Set(serviceOrders.map(o => o?.customer).filter(id => id != null)))
    const missing = ids.filter(id => !(id in serviceCustomerDetails) && !serviceCustomerPending.current.has(id))
    if (missing.length === 0) return
    let cancelled = false
    const fetchDetails = async ()=>{
      await Promise.all(missing.map(async id => {
        serviceCustomerPending.current.add(id)
        try{
          const resp = await api.get('/auth/api/user_details/', { params: { user_id: id }, skipUserId: true })
          if (!cancelled){
            setServiceCustomerDetails(prev => ({ ...prev, [id]: resp?.data || null }))
          }
        }catch{
          if (!cancelled){
            setServiceCustomerDetails(prev => ({ ...prev, [id]: null }))
          }
        }finally{
          serviceCustomerPending.current.delete(id)
        }
      }))
    }
    fetchDetails()
    return ()=>{ cancelled = true }
  }, [serviceOrders, serviceCustomerDetails])

  // Auto-scroll to focused order and clear highlight after delay
  useEffect(()=>{
    if (!focusedOrderId) return
    // Wait for tab change and render
    const scrollTimer = setTimeout(()=>{
      const el = orderRefs.current[focusedOrderId]
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 100)
    // Clear highlight after 2.5 seconds
    const clearTimer = setTimeout(()=>{
      setFocusedOrderId(null)
    }, 2500)
    return ()=>{ clearTimeout(scrollTimer); clearTimeout(clearTimer) }
  }, [focusedOrderId])

  useEffect(()=>{
    setOrderPage(1)
  }, [orderQuery, orderTypeFilter, orderStatusFilter, orderPageSize])

  const loadServiceOfferings = async ()=>{
    setServiceLoading(true)
    try{
      const resp = await api.get(`${SERVICES_ROOT}/my/offerings/`)
      setServiceOfferings(toArray(resp.data))
    }catch{
      setServiceOfferings([])
    } finally {
      setServiceLoading(false)
    }
  }

  const loadMeetingStatus = async () => {
    try {
      const response = await api.get('/chefs/api/me/verification-meeting/')
      setMeetingConfig({ ...response.data, loading: false })
    } catch {
      setMeetingConfig(prev => ({ ...prev, loading: false, feature_enabled: false }))
    }
  }

  const loadAll = async ()=>{
    setNotice(null)
    try{ await api.get('/auth/api/user_details/') }catch{}
    const tasks = [loadChefProfile(), loadAreaStatus(), loadIngredients(), loadDishes(), loadMeals(), loadEvents(), loadOrders(), loadServiceOrders(), loadStripeStatus(), loadServiceOfferings(), loadMeetingStatus()]
    await Promise.all(tasks.map(p => p.catch(()=>undefined)))
  }

  // Derive upcoming vs past events
  const upcomingEvents = useMemo(()=>{
    const now = Date.now()
    const items = Array.isArray(events) ? events.slice() : []
    const toTs = (e)=>{
      const cutoff = e?.order_cutoff_time ? Date.parse(e.order_cutoff_time) : null
      if (cutoff != null && !Number.isNaN(cutoff)) return cutoff
      const date = e?.event_date || ''
      let time = e?.event_time || '00:00'
      if (typeof time === 'string' && time.length === 5) time = time + ':00'
      const dt = Date.parse(`${date}T${time}`)
      return Number.isNaN(dt) ? 0 : dt
    }
    return items.filter(e => toTs(e) >= now).sort((a,b)=> toTs(a) - toTs(b))
  }, [events])

  const pastEvents = useMemo(()=>{
    const now = Date.now()
    const items = Array.isArray(events) ? events.slice() : []
    const toTs = (e)=>{
      const cutoff = e?.order_cutoff_time ? Date.parse(e.order_cutoff_time) : null
      if (cutoff != null && !Number.isNaN(cutoff)) return cutoff
      const date = e?.event_date || ''
      let time = e?.event_time || '00:00'
      if (typeof time === 'string' && time.length === 5) time = time + ':00'
      const dt = Date.parse(`${date}T${time}`)
      return Number.isNaN(dt) ? 0 : dt
    }
    return items.filter(e => toTs(e) < now).sort((a,b)=> toTs(b) - toTs(a))
  }, [events])

  // Preview URLs for unsaved uploads
  useEffect(()=>{
    let url
    if (profileForm.profile_pic){ try{ url = URL.createObjectURL(profileForm.profile_pic); setProfilePicPreview(url) }catch{}
    } else { setProfilePicPreview(null) }
    return ()=>{ if (url) URL.revokeObjectURL(url) }
  }, [profileForm.profile_pic])

  useEffect(()=>{
    let url
    if (profileForm.banner_image){ try{ url = URL.createObjectURL(profileForm.banner_image); setBannerPreview(url) }catch{}
    } else { setBannerPreview(null) }
    return ()=>{ if (url) URL.revokeObjectURL(url) }
  }, [profileForm.banner_image])

  useEffect(()=>{ loadAll().finally(()=> setInitialLoadDone(true)) }, [])

  // Meeting status is now loaded as part of loadAll() above

  // Set page title with chef name
  useEffect(() => {
    const chefName = chef?.user?.username || 'Dashboard'
    document.title = `sautai — Chef ${chefName}`
  }, [chef?.user?.username])

  useEffect(()=>{
    // Poll while onboarding is incomplete
    if (!payouts || payouts.loading) return
    if (payouts.is_active) return
    const id = setInterval(()=>{ loadStripeStatus().catch(()=>{}) }, 7000)
    return ()=> clearInterval(id)
  }, [payouts.loading, payouts.is_active])

  const startOrContinueOnboarding = async ()=>{
    setOnboardingBusy(true)
    try{
      const resp = await stripe.createOrContinue()
      const url = resp?.data?.url
      if (url){ window.location.href = url; return }
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'No onboarding URL returned', tone:'error' } })) }catch{}
    }catch(e){
      try{
        const { buildErrorMessage } = await import('../api')
        const msg = buildErrorMessage(e?.response?.data, 'Unable to start onboarding', e?.response?.status)
        window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
      }catch{}
    }finally{ setOnboardingBusy(false) }
  }

  const regenerateOnboarding = async ()=>{
    setOnboardingBusy(true)
    try{
      const resp = await stripe.regenerate()
      const url = resp?.data?.onboarding_url
      if (url){ window.location.href = url; return }
      await loadStripeStatus()
    }catch{ } finally { setOnboardingBusy(false) }
  }

  const fixRestrictedAccount = async ()=>{
    setOnboardingBusy(true)
    try{
      const resp = await stripe.fixRestricted()
      const url = resp?.data?.onboarding_url
      await loadStripeStatus()
      if (url){ window.location.href = url }
    }catch(e){
      try{
        const { buildErrorMessage } = await import('../api')
        const msg = buildErrorMessage(e?.response?.data, 'Unable to fix account', e?.response?.status)
        window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
      }catch{}
    } finally { setOnboardingBusy(false) }
  }

  // Actions
  const createIngredient = async (e)=>{
    e.preventDefault()
    try{
      const payload = { ...ingForm, calories:Number(ingForm.calories||0), fat:Number(ingForm.fat||0), carbohydrates:Number(ingForm.carbohydrates||0), protein:Number(ingForm.protein||0) }
      const resp = await api.post('/meals/api/chef/ingredients/', payload)
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: (resp?.data?.message || 'Ingredient created successfully'), tone:'success' } })) }catch{}
      setIngForm({ name:'', calories:'', fat:'', carbohydrates:'', protein:'' })
      loadIngredients()
    }catch(e){ console.error('createIngredient failed', e); }
  }

  const deleteIngredient = async (id)=>{ try{ await api.delete(`/meals/api/chef/ingredients/${id}/delete/`); loadIngredients() }catch{} }

  const createDish = async (e)=>{
    e.preventDefault()
    try{
      const payload = { name:dishForm.name, featured:Boolean(dishForm.featured), ingredients: (dishForm.ingredient_ids||[]).map(x=> Number(x)) }
      const resp = await api.post('/meals/api/create-chef-dish/', payload)
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: (resp?.data?.message || 'Dish created successfully'), tone:'success' } })) }catch{}
      setDishForm({ name:'', featured:false, ingredient_ids:[] }); loadDishes()
    }catch(e){ console.error('createDish failed', e); }
  }

  const deleteDish = async (id)=>{ try{ await api.delete(`/meals/api/dishes/${id}/delete/`); loadDishes() }catch{} }

  const createMeal = async (e)=>{
    e.preventDefault()
    if (mealSaving) return
    setMealSaving(true)
    const startedAt = Date.now()
    const trimmedName = String(mealForm.name || '').trim()
    const trimmedDescription = String(mealForm.description || '').trim()
    const fieldErrors = []
    if (!trimmedName) fieldErrors.push('Enter a meal name before saving.')
    if (!trimmedDescription) fieldErrors.push('Add a brief description for your meal.')
    const priceValue = Number(mealForm.price || 0)
    if (!Number.isFinite(priceValue) || priceValue <= 0) fieldErrors.push('Set a meal price greater than zero.')
    if (!Array.isArray(mealForm.dishes) || mealForm.dishes.length === 0) fieldErrors.push('Choose at least one dish to include.')
    if (fieldErrors.length > 0){
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: fieldErrors[0], tone:'error' } })) }catch{}
      setMealSaving(false)
      return
    }
    try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'Creating meal…', tone:'info' } })) }catch{}
    try{
      const payload = { ...mealForm, price: Number(mealForm.price||0), start_date: mealForm.start_date || todayISO, dishes: (mealForm.dishes||[]).map(x=> Number(x)) }
      const resp = await api.post('/meals/api/chef/meals/', payload)
      const message = resp?.data?.message || 'Meal created successfully'
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: message, tone:'success' } })) }catch{}
      setMealForm({ name:'', description:'', meal_type:'Dinner', price:'', start_date:'', dishes:[], dietary_preferences:[] })
      await loadMeals()
    }catch(err){
      console.error('createMeal failed', err)
      try{
        const { buildErrorMessage } = await import('../api')
        const msg = buildErrorMessage(err?.response?.data, 'Failed to create meal', err?.response?.status)
        window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
      }catch{
        const msg = err?.response?.data?.error || err?.response?.data?.detail || 'Failed to create meal'
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } })) }catch{}
      }
    } finally {
      const elapsed = Date.now() - startedAt
      if (elapsed < 350){
        await new Promise(resolve => setTimeout(resolve, 350 - elapsed))
      }
      setMealSaving(false)
    }
  }

  const deleteMeal = async (id)=>{ try{ await api.delete(`/meals/api/chef/meals/${id}/`); loadMeals() }catch{} }

  const createEvent = async (e)=>{
    e.preventDefault()
    try{
      const cutoff = `${eventForm.order_cutoff_date||eventForm.event_date} ${eventForm.order_cutoff_time}`
      const payload = {
        meal: eventForm.meal ? Number(eventForm.meal) : null,
        event_date: eventForm.event_date,
        event_time: eventForm.event_time,
        order_cutoff_time: cutoff,
        base_price: Number(eventForm.base_price||0),
        min_price: Number(eventForm.min_price||0),
        max_orders: Number(eventForm.max_orders||0),
        min_orders: Number(eventForm.min_orders||0),
        description: eventForm.description,
        special_instructions: eventForm.special_instructions
      }
      const resp = await api.post('/meals/api/chef-meal-events/', payload)
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: (resp?.data?.message || 'Meal share created successfully'), tone:'success' } })) }catch{}
      setEventForm({ meal:null, event_date:'', event_time:'18:00', order_cutoff_date:'', order_cutoff_time:'12:00', base_price:'', min_price:'', max_orders:10, min_orders:1, description:'', special_instructions:'' })
      loadEvents()
    }catch(e){
      console.error('createEvent failed', e)
      try{
        const { buildErrorMessage } = await import('../api')
        const msg = buildErrorMessage(e?.response?.data, 'Failed to create meal share', e?.response?.status)
        window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
      }catch{}
    }
  }

  const duplicateMealShare = async (eventToDuplicate) => {
    if (!eventToDuplicate?.id) return
    try {
      // Pre-fill the form with values from the meal share to duplicate
      const tomorrow = new Date()
      tomorrow.setDate(tomorrow.getDate() + 1)
      const tomorrowISO = tomorrow.toISOString().split('T')[0]
      
      setEventForm({
        meal: eventToDuplicate.meal?.id || eventToDuplicate.meal_id || null,
        event_date: tomorrowISO,
        event_time: eventToDuplicate.event_time || '18:00',
        order_cutoff_date: tomorrowISO,
        order_cutoff_time: '12:00',
        base_price: eventToDuplicate.base_price || '',
        min_price: eventToDuplicate.min_price || '',
        max_orders: eventToDuplicate.max_orders || 10,
        min_orders: eventToDuplicate.min_orders || 1,
        description: eventToDuplicate.description || '',
        special_instructions: eventToDuplicate.special_instructions || ''
      })
      
      // Switch to meal shares sub-tab and scroll to form
      setServicesSubTab('meal-shares')
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: 'Form pre-filled. Adjust date/time and submit.', tone:'info' } })) }catch{}
    } catch(e) {
      console.error('duplicateMealShare failed', e)
      try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: 'Failed to duplicate meal share', tone:'error' } })) }catch{}
    }
  }

  const toServiceTypeLabel = (value)=>{
    const found = SERVICE_TYPES.find(t => t.value === value)
    return found ? found.label : (value || '')
  }

  const resetServiceForm = ()=>{
    setServiceForm(()=>({ ...INITIAL_SERVICE_FORM }))
    setServiceErrors(null)
  }

  const editServiceOffering = (offering)=>{
    if (!offering) return
    const targetIds = Array.isArray(offering?.target_customer_ids)
      ? offering.target_customer_ids
      : Array.isArray(offering?.target_customers)
        ? offering.target_customers.map(t => t?.id ?? t?.customer_id ?? t)
        : []
    setServiceForm({
      id: offering.id || null,
      service_type: offering.service_type || 'home_chef',
      title: offering.title || '',
      description: offering.description || '',
      default_duration_minutes: offering.default_duration_minutes != null ? String(offering.default_duration_minutes) : '',
      max_travel_miles: offering.max_travel_miles != null ? String(offering.max_travel_miles) : '',
      notes: offering.notes || '',
      targetCustomerIds: Array.isArray(targetIds) ? targetIds.filter(id => id != null).map(String) : []
    })
    setServiceErrors(null)
    setEditFormGlowKey(k => k + 1)
  }

  const handleConnectionAction = async (connectionId, action)=>{
    if (!connectionId || !action) return
    setConnectionActionId(connectionId)
    try{
      await respondToConnection({ connectionId, action })
      await refetchConnections()
      const message = action === 'accept'
        ? 'Connection accepted'
        : action === 'decline'
          ? 'Connection declined'
          : 'Connection ended'
      try{
        window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: message, tone:'success' } }))
      }catch{}
    }catch(error){
      console.error('update connection failed', error)
      const msg = error?.response?.data?.detail || 'Unable to update the connection. Please try again.'
      try{
        window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
      }catch{}
    } finally {
      setConnectionActionId(null)
    }
  }

  const submitServiceOffering = async (e)=>{
    e.preventDefault()
    if (serviceSaving) return
    setServiceSaving(true)
    setServiceErrors(null)
    const toNumber = (val)=>{
      if (val === '' || val == null) return null
      const num = Number(val)
      return Number.isFinite(num) ? num : null
    }
    const targetIds = Array.isArray(serviceForm.targetCustomerIds)
      ? serviceForm.targetCustomerIds
        .map(id => {
          if (id == null) return null
          const numeric = Number(id)
          return Number.isNaN(numeric) ? String(id) : numeric
        })
        .filter(id => id != null && String(id).trim() !== '')
      : []
    const payload = {
      service_type: serviceForm.service_type || 'home_chef',
      title: serviceForm.title || '',
      description: serviceForm.description || '',
      default_duration_minutes: toNumber(serviceForm.default_duration_minutes),
      max_travel_miles: toNumber(serviceForm.max_travel_miles),
      notes: serviceForm.notes || ''
    }
    try{
      if (serviceForm.id){
        await api.patch(`${SERVICES_ROOT}/offerings/${serviceForm.id}/`, {
          ...payload,
          target_customer_ids: targetIds
        })
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'Service offering updated', tone:'success' } })) }catch{}
      }else{
        await createOffering({ ...payload, targetCustomerIds: targetIds })
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'Service offering created', tone:'success' } })) }catch{}
      }
      resetServiceForm()
      await loadServiceOfferings()
    }catch(err){
      const data = err?.response?.data || null
      setServiceErrors(data || { detail:'Unable to save offering' })
    } finally {
      setServiceSaving(false)
    }
  }

  const handleDeleteOffering = async () => {
    if (!deleteOfferingId) return
    setDeleteOfferingBusy(true)
    try {
      await deleteOffering(deleteOfferingId)
      if (serviceForm.id === deleteOfferingId) {
        resetServiceForm()
      }
      await loadServiceOfferings()
      window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: 'Service deleted successfully', tone: 'success' } }))
    } catch (e) {
      const msg = e?.response?.data?.error || 'Unable to delete this service. It may have associated orders.'
      window.dispatchEvent(new CustomEvent('global-toast', { detail: { text: msg, tone: 'error' } }))
    } finally {
      setDeleteOfferingBusy(false)
      setDeleteOfferingId(null)
    }
  }

  const resetTierForm = ()=>{
    setTierForm(()=>({ ...INITIAL_TIER_FORM }))
    setTierErrors(null)
  }

  const startTierForm = (offering, tier = null)=>{
    if (!offering) return
    if (tier){
      setTierForm({
        id: tier.id || null,
        offeringId: offering.id || null,
        household_min: tier.household_min != null ? String(tier.household_min) : '',
        household_max: tier.household_max != null ? String(tier.household_max) : '',
        currency: tier.currency || 'usd',
        price: tier.desired_unit_amount_cents != null ? String((Number(tier.desired_unit_amount_cents)||0)/100) : '',
        is_recurring: Boolean(tier.is_recurring),
        recurrence_interval: tier.recurrence_interval || 'week',
        active: Boolean(tier.active),
        display_label: tier.display_label || ''
      })
    } else {
      setTierForm({ ...INITIAL_TIER_FORM, offeringId: offering.id || null })
    }
    setTierErrors(null)
  }

  const submitTierForm = async (e)=>{
    e.preventDefault()
    if (tierSaving || !tierForm.offeringId) return
    setTierSaving(true)
    setTierErrors(null)
    const toNumber = (val)=>{
      if (val === '' || val == null) return null
      const num = Number(val)
      return Number.isFinite(num) ? num : null
    }
    const parsedPrice = tierForm.price === '' || tierForm.price == null ? null : Number(tierForm.price)
    const priceCents = parsedPrice == null ? null : (Number.isFinite(parsedPrice) ? Math.round(parsedPrice*100) : null)
    const payload = {
      household_min: toNumber(tierForm.household_min),
      household_max: toNumber(tierForm.household_max),
      currency: tierForm.currency || 'usd',
      desired_unit_amount_cents: priceCents,
      is_recurring: Boolean(tierForm.is_recurring),
      recurrence_interval: tierForm.is_recurring ? (tierForm.recurrence_interval || 'week') : null,
      active: Boolean(tierForm.active),
      display_label: tierForm.display_label || ''
    }
    try{
      if (tierForm.id){
        await api.patch(`${SERVICES_ROOT}/tiers/${tierForm.id}/`, payload)
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'Tier updated', tone:'success' } })) }catch{}
      } else {
        await api.post(`${SERVICES_ROOT}/offerings/${tierForm.offeringId}/tiers/`, payload)
        try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'Tier created', tone:'success' } })) }catch{}
      }
      resetTierForm()
      await loadServiceOfferings()
    }catch(err){
      const data = err?.response?.data || null
      setTierErrors(data || { detail:'Unable to save tier' })
    } finally {
      setTierSaving(false)
    }
  }

  const NavItem = ({ value, label, icon: Icon, badge })=> (
    <button 
      className={`chef-nav-item ${tab===value?'active':''}`} 
      onClick={()=> setTab(value)}
      aria-current={tab===value?'page':undefined}
      title={sidebarCollapsed ? label : undefined}
      style={{ position: 'relative' }}
    >
      <Icon />
      {!sidebarCollapsed && <span>{label}</span>}
      {badge > 0 && (
        <span className="chef-nav-badge" style={{
          position: 'absolute',
          top: sidebarCollapsed ? '2px' : '50%',
          right: sidebarCollapsed ? '2px' : '8px',
          transform: sidebarCollapsed ? 'none' : 'translateY(-50%)',
          background: 'var(--warning)',
          color: 'white',
          fontSize: '0.65rem',
          fontWeight: 700,
          minWidth: '18px',
          height: '18px',
          borderRadius: '9px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 5px',
          boxShadow: '0 2px 4px var(--warning-bg)'
        }}>
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  )

  const SectionHeader = ({ title, subtitle, onAdd, addLabel, showAdd = true })=> (
    <header className="chef-section-header">
      <div className="chef-section-header-text">
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {showAdd && onAdd && (
        <button className="btn btn-primary chef-add-btn" onClick={onAdd}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          <span>{addLabel || 'Add'}</span>
        </button>
      )}
    </header>
  )

  const orderTypeOptions = useMemo(() => ([
    { value: 'all', label: 'All orders' },
    { value: 'service', label: 'Service orders' },
    { value: 'meal', label: 'Meal orders' }
  ]), [])

  const orderStatusOptions = useMemo(() => ([
    { value: 'all', label: 'All statuses' },
    { value: 'active', label: 'Active' },
    { value: 'pending', label: 'Pending' },
    { value: 'completed', label: 'Completed' },
    { value: 'cancelled', label: 'Cancelled' },
    { value: 'other', label: 'Other' }
  ]), [])

  const orderSortOptions = useMemo(() => ([
    { value: 'newest', label: 'Newest first' },
    { value: 'oldest', label: 'Oldest first' }
  ]), [])

  const orderPageSizeOptions = useMemo(() => ([6, 12, 24]), [])

  const unifiedOrders = useMemo(() => {
    const serviceRows = (serviceOrders || []).map((order, index) => {
      const orderId = order.id || order.order_id || `service-${index}`
      const detail = serviceCustomerDetails?.[order.customer] || serviceCustomerDetails?.[String(order.customer)] || null
      const customerName = serviceCustomerName(order, detail)
      const contactLine = detail?.email || order.customer_email || detail?.username || order.customer_username || ''
      const tierLabel = extractTierLabel(order)
      const title = serviceOfferingTitle(order)
      const scheduleLabel = formatServiceSchedule(order)
      const priceLabel = order.price_summary || order.total_display || toCurrencyDisplay(order.total_value_for_chef, order.currency || order.order_currency)
      const recurringLabel = order.is_subscription ? 'Recurring billing' : ''
      const statusRaw = order.status || 'unknown'
      const statusMeta = serviceStatusTone(statusRaw)
      const searchText = buildOrderSearchText({
        customerName,
        contact: contactLine,
        title: tierLabel ? `${title} ${tierLabel}` : title,
        status: statusRaw,
        type: 'service',
        notes: order.special_requests,
        schedule: scheduleLabel,
        priceLabel
      })
      return {
        id: String(orderId),
        displayId: `service-${orderId}`,
        type: 'service',
        typeLabel: 'Service',
        status: statusRaw,
        statusBucket: bucketOrderStatus(statusRaw),
        statusLabel: statusMeta.label,
        statusStyle: statusMeta.style,
        customerName,
        contactLine,
        title,
        subtitle: tierLabel,
        scheduleLabel,
        priceLabel,
        recurringLabel,
        notes: order.special_requests,
        timestamp: getServiceOrderTimestamp(order),
        searchText,
        raw: order
      }
    })

    const mealRows = (orders || []).map((order, index) => {
      const orderId = order.id || order.order_id || order.order?.id || order.order || `meal-${index}`
      const customerName = mealOrderCustomerName(order)
      const contactLine = mealOrderContact(order)
      const title = mealOrderTitle(order)
      const scheduleLabel = formatMealSchedule(order)
      const priceLabel = mealOrderPriceLabel(order)
      const quantityLabel = order.quantity ? `Qty ${order.quantity}` : ''
      const statusRaw = order.status || order.payment_status || 'pending'
      const statusMeta = serviceStatusTone(statusRaw)
      const searchText = buildOrderSearchText({
        customerName,
        contact: contactLine,
        title,
        status: statusRaw,
        type: 'meal',
        schedule: scheduleLabel,
        priceLabel
      })
      return {
        id: String(orderId),
        displayId: `meal-${orderId}`,
        type: 'meal',
        typeLabel: 'Meal',
        status: statusRaw,
        statusBucket: bucketOrderStatus(statusRaw),
        statusLabel: statusMeta.label,
        statusStyle: statusMeta.style,
        customerName,
        contactLine,
        title,
        subtitle: quantityLabel,
        scheduleLabel,
        priceLabel,
        recurringLabel: '',
        notes: order.special_instructions || order.notes || '',
        timestamp: getMealOrderTimestamp(order),
        searchText,
        raw: order
      }
    })

    return [...serviceRows, ...mealRows]
  }, [serviceOrders, orders, serviceCustomerDetails])

  const filteredOrders = useMemo(() => (
    filterOrders(unifiedOrders, {
      query: orderQuery,
      type: orderTypeFilter,
      statusBucket: orderStatusFilter
    })
  ), [unifiedOrders, orderQuery, orderTypeFilter, orderStatusFilter])

  const sortedOrders = useMemo(() => {
    const rows = [...filteredOrders]
    rows.sort((a, b) => (
      orderSort === 'oldest'
        ? (a.timestamp || 0) - (b.timestamp || 0)
        : (b.timestamp || 0) - (a.timestamp || 0)
    ))
    return rows
  }, [filteredOrders, orderSort])

  const orderPagination = useMemo(() => (
    paginateOrders(sortedOrders, { page: orderPage, pageSize: orderPageSize })
  ), [sortedOrders, orderPage, orderPageSize])

  useEffect(() => {
    if (orderPage !== orderPagination.page) {
      setOrderPage(orderPagination.page)
    }
  }, [orderPagination.page, orderPage])

  const orderStartIndex = orderPagination.items.length
    ? ((orderPagination.page - 1) * orderPagination.pageSize) + 1
    : 0
  const orderEndIndex = orderPagination.items.length
    ? orderStartIndex + orderPagination.items.length - 1
    : 0
  const hasOrderFilters = Boolean(orderQuery.trim() || orderTypeFilter !== 'all' || orderStatusFilter !== 'all')
  const isOrdersLoading = serviceOrdersLoading && (serviceOrders?.length || 0) === 0 && (orders?.length || 0) === 0

  return (
    <div className={`chef-dashboard-layout ${sidebarCollapsed?'sidebar-collapsed':''}`}>
      {/* Sidebar Navigation */}
      <aside className={`chef-sidebar ${sidebarCollapsed?'collapsed':''}`}>
        <div className="chef-sidebar-header">
          <h2 style={{margin:0, fontSize:'1.25rem'}}>Chef Hub</h2>
          <button 
            className="btn btn-outline btn-sm chef-sidebar-toggle" 
            onClick={()=> setSidebarCollapsed(!sidebarCollapsed)}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? '→' : '←'}
          </button>
        </div>
        <nav className="chef-nav" role="navigation" aria-label="Chef dashboard sections">
          {/* Primary Actions - Always visible */}
          <div className="nav-primary-items">
            <NavItem value="today" label="Today" icon={DashboardIcon} />
            <NavItem value="insights" label="Insights" icon={InsightsIcon} />
            <NavItem value="profile" label="My Profile" icon={ProfileIcon} />
            <NavItem value="compliance" label="Home Kitchen" icon={() => <i className="fa-solid fa-house-chimney" />} />
          </div>

          {/* Your Menu - Menu Builder, Services, Payment Links */}
          <NavSection id="menu" title="Your Menu" sidebarCollapsed={sidebarCollapsed}>
            <NavItem value="menu" label="Menu Builder" icon={KitchenIcon} />
            <NavItem value="services" label="Services" icon={ServicesIcon} />
            <NavItem value="payments" label="Payment Links" icon={PaymentLinksIcon} />
          </NavSection>

          {/* Operations - Orders, Clients, Prep, Messages (show for active chefs) */}
          {isOnboardingComplete && (
            <NavSection id="operations" title="Operations" sidebarCollapsed={sidebarCollapsed}>
              <NavItem value="orders" label="Orders" icon={OrdersIcon} />
              <NavItem value="clients" label="Clients" icon={ClientsIcon} badge={pendingConnections?.length || 0} />
              <NavItem value="prep" label="Prep Planning" icon={PrepPlanIcon} />
              <NavItem value="messages" label="Messages" icon={MessagesIcon} badge={totalUnread || 0} />
              <NavItem value="surveys" label="Surveys" icon={SurveysIcon} />
            </NavSection>
          )}
        </nav>
      </aside>

      {/* Main Content */}
      <main className="chef-main-content">
        {notice && <div className="card" style={{borderColor:'#f0d000', marginBottom:'1rem'}}>{notice}</div>}

      {/* Content Sections */}
      {/* Today - Smart Dashboard */}
      {tab==='today' && (
        <div>
          {/* Onboarding Checklist - Show prominently when incomplete or not yet live */}
          {initialLoadDone && (!isOnboardingComplete || !chef?.is_live) && (
            <OnboardingChecklist
              completionState={onboardingCompletionState}
              onNavigate={(targetTab) => setTab(targetTab)}
              onStartStripeOnboarding={startOrContinueOnboarding}
              onOpenCalendly={() => setCalendlyModalOpen(true)}
              meetingConfig={meetingConfig}
              isLive={chef?.is_live}
              onGoLive={handleGoLive}
              goingLive={goingLive}
            />
          )}

          {initialLoadDone ? (
          <TodayDashboard
            orders={orders}
            serviceOrders={serviceOrders}
            events={events}
            pendingConnections={pendingConnections}
            unreadMessageCount={totalUnread || 0}
            onNavigate={(targetTab) => setTab(targetTab)}
            onViewOrder={(order) => {
              setFocusedOrderId(order.id)
              setTab('orders')
            }}
            isOnboardingComplete={isOnboardingComplete}
            onboardingCompletionState={onboardingCompletionState}
            meetingConfig={meetingConfig}
            isOnBreak={isOnBreak}
            breakBusy={breakBusy}
            breakReason={breakReason}
            onBreakReasonChange={setBreakReason}
            onToggleBreak={toggleBreak}
          />
          ) : (
          <div className="today-dashboard">
            <div className="today-header">
              <div className="today-greeting">
                <h1>Today</h1>
                <p className="muted">Loading your dashboard...</p>
              </div>
            </div>
          </div>
          )}
        </div>
      )}

      {/* Insights - Business Analytics */}
      {tab==='insights' && (
        <ChefInsightsDashboard
          orders={orders}
          serviceOrders={serviceOrders}
          meals={meals}
          dishes={dishes}
          ingredients={ingredients}
          serviceOfferings={serviceOfferings}
          onOpenAnalyticsDrawer={openAnalyticsDrawer}
        />
      )}

      {/* Legacy Dashboard redirect - now redirects to Today */}
      {tab==='dashboard' && (
        <div style={{textAlign:'center', padding:'2rem'}}>
          <p className="muted">The Dashboard has been redesigned as "Today".</p>
          <button className="btn btn-primary" onClick={() => setTab('today')}>
            Go to Today
          </button>
        </div>
      )}

      {/* Full Dashboard with metrics (accessible via direct state) */}
      {tab==='metrics' && (
        <div>
          <header style={{marginBottom:'1.5rem'}}>
            <h1 style={{margin:'0 0 .25rem 0'}}>Metrics</h1>
            <p className="muted">Your business overview and key metrics</p>
          </header>

          {/* Onboarding Checklist - Show prominently when incomplete or not yet live */}
          {initialLoadDone && (!isOnboardingComplete || !chef?.is_live) && (
            <OnboardingChecklist
              completionState={onboardingCompletionState}
              onNavigate={(targetTab) => setTab(targetTab)}
              onStartStripeOnboarding={startOrContinueOnboarding}
              onOpenCalendly={() => setCalendlyModalOpen(true)}
              meetingConfig={meetingConfig}
              isLive={chef?.is_live}
              onGoLive={handleGoLive}
              goingLive={goingLive}
            />
          )}

          {/* Stripe Payouts Status - Only show standalone card when onboarding checklist is complete */}
          {isOnboardingComplete && (
            payouts.loading ? (
              <div className="card" style={{marginBottom:'1.5rem', background:'var(--surface-2)'}}>
                <div style={{display:'flex', alignItems:'center', gap:'.75rem'}}>
                  <div style={{width:40, height:40, borderRadius:8, background:'var(--surface)', display:'flex', alignItems:'center', justifyContent:'center'}}>
                    <i className="fa-brands fa-stripe" style={{fontSize:20, opacity:.5}}></i>
                  </div>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:600, marginBottom:'.15rem'}}>Payouts</div>
                    <div className="muted" style={{fontSize:'.9rem'}}>Checking Stripe status…</div>
                  </div>
                  <button className="btn btn-outline btn-sm" disabled={onboardingBusy} onClick={loadStripeStatus}>
                    <i className="fa-solid fa-rotate-right" style={{fontSize:14}}></i>
                  </button>
                </div>
              </div>
            ) : payouts.is_active ? (
              <div className="card" style={{marginBottom:'1.5rem', background:'linear-gradient(135deg, rgba(52,211,153,.1), rgba(16,185,129,.05))', borderColor:'rgba(16,185,129,.3)'}}>
                <div style={{display:'flex', alignItems:'center', gap:'.75rem'}}>
                  <div style={{width:40, height:40, borderRadius:8, background:'rgba(16,185,129,.15)', display:'flex', alignItems:'center', justifyContent:'center'}}>
                    <i className="fa-solid fa-circle-check" style={{fontSize:20, color:'var(--success)'}}></i>
                  </div>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:600, marginBottom:'.15rem', display:'flex', alignItems:'center', gap:'.5rem'}}>
                      Stripe Payouts Active
                      <i className="fa-brands fa-stripe" style={{fontSize:18, opacity:.6}}></i>
                    </div>
                    <div className="muted" style={{fontSize:'.9rem'}}>You're ready to receive payments</div>
                  </div>
                  <button className="btn btn-outline btn-sm" disabled={onboardingBusy} onClick={loadStripeStatus} title="Refresh status">
                    <i className="fa-solid fa-rotate-right" style={{fontSize:14}}></i>
                  </button>
                </div>
              </div>
            ) : (
              <div className="card" style={{marginBottom:'1.5rem', borderColor:'#f0a000', background:'rgba(240,160,0,.08)'}}>
                <div style={{display:'flex', alignItems:'flex-start', gap:'.75rem'}}>
                  <div style={{width:40, height:40, borderRadius:8, background:'rgba(240,160,0,.15)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0}}>
                    <i className="fa-solid fa-triangle-exclamation" style={{fontSize:20, color:'#f0a000'}}></i>
                  </div>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:600, marginBottom:'.25rem'}}>Payouts Setup Required</div>
                    <div className="muted" style={{fontSize:'.9rem', marginBottom:'.5rem'}}>Complete Stripe onboarding to receive payments and unlock all features.</div>
                    {payouts?.disabled_reason && (
                      <div className="muted" style={{fontSize:'.85rem', marginBottom:'.5rem'}}>
                        <strong>Reason:</strong> {payouts.disabled_reason}
                      </div>
                    )}
                    <div style={{display:'flex', flexWrap:'wrap', gap:'.5rem', marginTop:'.75rem'}}>
                      <button className="btn btn-primary btn-sm" disabled={onboardingBusy} onClick={startOrContinueOnboarding}>
                        <i className="fa-brands fa-stripe" style={{fontSize:14, marginRight:'.35rem'}}></i>
                        {onboardingBusy?'Opening…':(payouts.has_account?'Continue Setup':'Set Up Payouts')}
                      </button>
                      <button className="btn btn-outline btn-sm" disabled={onboardingBusy} onClick={regenerateOnboarding}>
                        <i className="fa-solid fa-link" style={{fontSize:12, marginRight:'.35rem'}}></i>
                        New Link
                      </button>
                      <button className="btn btn-outline btn-sm" disabled={onboardingBusy} onClick={loadStripeStatus}>
                        <i className="fa-solid fa-rotate-right" style={{fontSize:12, marginRight:'.35rem'}}></i>
                        Refresh
                      </button>
                      {payouts.disabled_reason && (
                        <button className="btn btn-outline btn-sm" disabled={onboardingBusy} onClick={fixRestrictedAccount}>
                          <i className="fa-solid fa-wrench" style={{fontSize:12, marginRight:'.35rem'}}></i>
                          Fix Account
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          )}

          {/* Key Metrics Cards */}
          <div className="chef-metrics-grid">
            <div 
              className="chef-metric-card clickable" 
              onClick={() => openAnalyticsDrawer('revenue', 'Revenue')}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && openAnalyticsDrawer('revenue', 'Revenue')}
            >
              <div className="metric-label">Total Revenue</div>
              <div className="metric-value">
                {toCurrencyDisplay(
                  [...serviceOrders, ...orders]
                    .filter(o => ['confirmed', 'completed', 'paid'].includes(String(o.status || '').toLowerCase()))
                    .reduce((sum, o)=> sum + (Number(o.total_value_for_chef)||0), 0),
                  'USD'
                )}
              </div>
              <div className="metric-change positive">
                <i className="fa-solid fa-chart-line" style={{marginRight:'.35rem', opacity:.7}} />
                Click to view trends
              </div>
            </div>
            <div 
              className="chef-metric-card clickable"
              onClick={() => openAnalyticsDrawer('clients', 'New Clients')}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && openAnalyticsDrawer('clients', 'New Clients')}
            >
              <div className="metric-label">Active Families</div>
              <div className="metric-value">
                {new Set([...serviceOrders, ...orders].map(o=> o.customer).filter(Boolean)).size}
              </div>
              <div className="metric-change positive">
                <i className="fa-solid fa-chart-line" style={{marginRight:'.35rem', opacity:.7}} />
                Click to view trends
              </div>
            </div>
            <div 
              className="chef-metric-card clickable"
              onClick={() => openAnalyticsDrawer('orders', 'Orders')}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && openAnalyticsDrawer('orders', 'Orders')}
            >
              <div className="metric-label">Service Orders</div>
              <div className="metric-value">{serviceOrders.length}</div>
              <div className="metric-change">{serviceOrdersLoading ? 'Loading...' : `${serviceOrders.filter(o=> ['confirmed','completed'].includes(String(o.status||'').toLowerCase())).length} confirmed`}</div>
            </div>
            <div className="chef-metric-card">
              <div className="metric-label">Meal Orders</div>
              <div className="metric-value">{orders.length}</div>
              <div className="metric-change">{orders.filter(o=> ['paid','completed'].includes(String(o.status||'').toLowerCase())).length} completed</div>
            </div>
          </div>

          {/* Quick Actions & Upcoming */}
          <div className="grid grid-2" style={{marginTop:'1.5rem'}}>
            <div className="card">
              <h3 style={{marginTop:0}}>Upcoming Meal Shares</h3>
              <div style={{maxHeight: 300, overflowY:'auto'}}>
                {upcomingEvents.length===0 ? (
                  <div className="muted">No upcoming meal shares.</div>
                ) : (
                  <div style={{display:'flex', flexDirection:'column', gap:'.5rem'}}>
                    {upcomingEvents.slice(0,5).map(e => (
                      <div key={e.id} className="card" style={{padding:'.6rem', background:'var(--surface-2)'}}>
                        <div style={{fontWeight:700}}>{e.meal?.name || e.meal_name || 'Meal'}</div>
                        <div className="muted" style={{fontSize:'.85rem', marginTop:'.15rem'}}>
                          {e.event_date} at {e.event_time}
                        </div>
                        <div className="muted" style={{fontSize:'.85rem'}}>
                          Orders: {e.orders_count || 0} / {e.max_orders || 0}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <h3 style={{marginTop:0}}>Recent Service Orders</h3>
              <div style={{maxHeight: 300, overflowY:'auto'}}>
                {serviceOrders.length===0 ? (
                  <div className="muted">No service orders yet.</div>
                ) : (
                  <div style={{display:'flex', flexDirection:'column', gap:'.5rem'}}>
                    {serviceOrders.slice(0,5).map(order => {
                      const statusMeta = serviceStatusTone(order.status)
                      const detail = serviceCustomerDetails?.[order.customer] || null
                      const displayName = serviceCustomerName(order, detail)
                      const orderId = order.id || order.order_id
                      return (
                        <div
                          key={orderId}
                          className="card clickable-order-card"
                          style={{padding:'.6rem', background:'var(--surface-2)', cursor:'pointer', transition:'background 0.15s ease, transform 0.15s ease'}}
                          onClick={()=>{ setFocusedOrderId(orderId); setTab('orders') }}
                          onKeyDown={(e)=> e.key === 'Enter' && (setFocusedOrderId(orderId), setTab('orders'))}
                          role="button"
                          tabIndex={0}
                          aria-label={`View order from ${displayName}`}
                        >
                          <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:'.5rem'}}>
                            <div style={{fontWeight:700, fontSize:'.9rem'}}>{displayName}</div>
                            <span className="chip" style={{...statusMeta.style, fontSize:'.7rem', padding:'.1rem .4rem'}}>{statusMeta.label}</span>
                          </div>
                          <div className="muted" style={{fontSize:'.85rem', marginTop:'.15rem'}}>
                            {serviceOfferingTitle(order)}
                          </div>
                          <div className="muted" style={{fontSize:'.85rem'}}>
                            {formatServiceSchedule(order)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="card" style={{marginTop:'1.5rem', background:'linear-gradient(135deg, var(--surface-2), var(--surface))'}}>
            <h3 style={{marginTop:0}}>Quick Stats</h3>
            <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(140px, 1fr))', gap:'1rem'}}>
              <div>
                <div className="muted" style={{fontSize:'.85rem'}}>Total Meals</div>
                <div style={{fontSize:'1.5rem', fontWeight:700, color:'var(--primary-700)'}}>{meals.length}</div>
              </div>
              <div>
                <div className="muted" style={{fontSize:'.85rem'}}>Dishes</div>
                <div style={{fontSize:'1.5rem', fontWeight:700, color:'var(--primary-700)'}}>{dishes.length}</div>
              </div>
              <div>
                <div className="muted" style={{fontSize:'.85rem'}}>Ingredients</div>
                <div style={{fontSize:'1.5rem', fontWeight:700, color:'var(--primary-700)'}}>{ingredients.length}</div>
              </div>
              <div>
                <div className="muted" style={{fontSize:'.85rem'}}>Service Offerings</div>
                <div style={{fontSize:'1.5rem', fontWeight:700, color:'var(--primary-700)'}}>{serviceOfferings.length}</div>
              </div>
            </div>
          </div>

          {/* Break Mode Banner */}
          <div className="card" style={{marginTop:'1.5rem', background:'var(--surface-2)'}}>
            <div style={{display:'flex', flexWrap:'wrap', gap:'1.4rem', alignItems:'flex-start'}}>
              <div style={{flex:'1 1 260px'}}>
                <h3 style={{marginTop:0}}>Need a breather?</h3>
                <p className="muted" style={{marginTop:'.35rem'}}>
                  Turning on break pauses new bookings, cancels upcoming events, and issues refunds automatically.
                  Use it whenever you need to step back, focus on personal matters, or simply recharge.
                </p>
                <p className="muted" style={{marginTop:'.35rem'}}>
                  A rested chef creates the best experiences. Pause with confidence and come back when you're ready—your guests will understand.
                </p>
              </div>
              <div style={{flex:'1 1 240px', maxWidth:360}}>
                <div style={{display:'flex', alignItems:'center', gap:'.6rem'}}>
                  <span style={{fontWeight:700}}>Break status</span>
                  <label style={{display:'inline-flex', alignItems:'center', gap:'.35rem'}}>
                    <input type="checkbox" checked={isOnBreak} disabled={breakBusy} onChange={e=> toggleBreak(e.target.checked)} />
                    <span>{isOnBreak ? 'On' : 'Off'}</span>
                  </label>
                  {breakBusy && <span className="spinner" aria-hidden />}
                </div>
                <input
                  className="input"
                  style={{marginTop:'.7rem'}}
                  placeholder="Optional note for your guests"
                  value={breakReason}
                  disabled={breakBusy}
                  onChange={e=> setBreakReason(e.target.value)}
                />
                <div className="muted" style={{fontSize:'.85rem', marginTop:'.45rem'}}>
                  We display this note on your profile so people know when to expect you back.
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab==='clients' && (
        <div>
          <SectionHeader title="Client Connections" subtitle="Manage invitations, active clients, and history." showAdd={false} />
          <div className="sr-only">
            <span>Accept</span>
            <span>Decline</span>
            <span>End</span>
          </div>
          <ChefAllClients onNavigateToPrep={() => setTab('prep')} />
        </div>
      )}

      {tab==='messages' && <ChefMessagesSection />}

      {tab==='payments' && <ChefPaymentLinks />}

      {tab==='surveys' && <ChefSurveys />}

      {tab==='prep' && <ChefPrepPlanning onNavigateToClients={() => setTab('clients')} />}

      {tab==='profile' && (
        <div>
          {/* My Profile - Sub-tab Navigation */}
          <header style={{marginBottom:'1rem'}}>
            <h1 style={{margin:'0 0 .5rem 0'}}>My Profile</h1>
            <div className="sub-tab-nav">
              <button 
                className={`sub-tab ${profileSubTab === 'info' ? 'active' : ''}`}
                onClick={() => setProfileSubTab('info')}
              >
                Profile Info
              </button>
              <button 
                className={`sub-tab ${profileSubTab === 'photos' ? 'active' : ''}`}
                onClick={() => setProfileSubTab('photos')}
              >
                Photos {chef?.photos?.length > 0 && <span className="sub-tab-badge">{chef.photos.length}</span>}
              </button>
            </div>
          </header>

          {/* Profile Info Sub-tab */}
          {profileSubTab === 'info' && (
          <div className="grid grid-2">
          <div className="card">
            <h3>Chef profile</h3>
            {!profileInit && <div className="muted" style={{marginBottom:'.35rem'}}>Loading…</div>}
            {chef?.profile_pic_url && (
              <div style={{marginBottom:'.5rem'}}>
                <img src={chef.profile_pic_url} alt="Profile" style={{height:72, width:72, objectFit:'cover', borderRadius:'999px', border:'1px solid var(--border)'}} />
              </div>
            )}
            <div className="label">Experience</div>
            <textarea className="textarea" rows={3} value={profileForm.experience} onChange={e=> setProfileForm(f=>({ ...f, experience:e.target.value }))} placeholder="Share your culinary experience…" />
            <div className="label">Bio</div>
            <textarea className="textarea" rows={3} value={profileForm.bio} onChange={e=> setProfileForm(f=>({ ...f, bio:e.target.value }))} placeholder="Tell customers about your style and specialties…" />
            <div className="label">Profile picture</div>
            <FileSelect label="Choose file" accept="image/*" onChange={(f)=> setProfileForm(p=>({ ...p, profile_pic: f }))} />
            {!profileForm.profile_pic && chef?.profile_pic_url && (
              <div className="muted" style={{marginTop:'.25rem'}}>Current: {(()=>{ try{ const u=new URL(chef.profile_pic_url); return decodeURIComponent(u.pathname.split('/').pop()||''); }catch{ const parts=String(chef.profile_pic_url).split('/'); return decodeURIComponent(parts[parts.length-1]||''); } })()}</div>
            )}
            <div className="label" style={{marginTop:'.6rem'}}>Banner image</div>
            <FileSelect label="Choose file" accept="image/*" onChange={(f)=> setProfileForm(p=>({ ...p, banner_image: f }))} />
            {!profileForm.banner_image && chef?.banner_url && (
              <div className="muted" style={{marginTop:'.25rem'}}>Current: {(()=>{ try{ const u=new URL(chef.banner_url); return decodeURIComponent(u.pathname.split('/').pop()||''); }catch{ const parts=String(chef.banner_url).split('/'); return decodeURIComponent(parts[parts.length-1]||''); } })()}</div>
            )}
            {bannerUpdating && (
              <div className="updating-banner" style={{marginTop:'.4rem'}}>
                <span className="spinner" aria-hidden /> Uploading banner…
              </div>
            )}
            {bannerJustUpdated && (
              <div style={{marginTop:'.4rem'}}>
                <span className="updated-chip">Banner updated</span>
              </div>
            )}
            <div className="label" style={{marginTop:'.6rem'}}>Calendly Booking Link</div>
            <input 
              type="url" 
              className="input"
              placeholder="https://calendly.com/yourname/consultation"
              value={profileForm.calendly_url}
              onChange={e => setProfileForm(f => ({ ...f, calendly_url: e.target.value }))}
            />
            <div className="muted" style={{marginTop:'.25rem'}}>
              Let customers book a consultation or tasting session with you
            </div>
            <div style={{marginTop:'.6rem'}}>
              <button className="btn btn-primary" disabled={profileSaving} onClick={async ()=>{
                setProfileSaving(true)
                try{
                  const hasBanner = Boolean(profileForm.banner_image)
                  if (profileForm.profile_pic || hasBanner){
                    if (hasBanner) setBannerUpdating(true)
                    const fd = new FormData(); fd.append('experience', profileForm.experience||''); fd.append('bio', profileForm.bio||''); fd.append('calendly_url', profileForm.calendly_url||''); if (profileForm.profile_pic) fd.append('profile_pic', profileForm.profile_pic); if (profileForm.banner_image) fd.append('banner_image', profileForm.banner_image)
                    await api.patch('/chefs/api/me/chef/profile/update/', fd, { headers: { 'Content-Type':'multipart/form-data' } })
                  } else {
                    await api.patch('/chefs/api/me/chef/profile/update/', { experience: profileForm.experience, bio: profileForm.bio, calendly_url: profileForm.calendly_url || null })
                  }
                  await loadChefProfile()
                  if (hasBanner){
                    setBannerJustUpdated(true)
                    try{ window.dispatchEvent(new CustomEvent('global-toast', { detail: { text:'Banner updated', tone:'success' } })) }catch{}
                    setTimeout(()=> setBannerJustUpdated(false), 2200)
                  }
                }catch(e){ console.error('update profile failed', e) }
                finally {
                  setProfileSaving(false)
                  if (bannerUpdating) setBannerUpdating(false)
                  setProfileForm(p=>({ ...p, banner_image: null }))
                }
              }}>{profileSaving?'Saving…':'Save changes'}</button>
            </div>
          </div>
          
          {/* Service Areas Management */}
          <div className="card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <h3 style={{ margin: 0 }}>Service Areas</h3>
              <button 
                className="btn btn-outline btn-sm" 
                onClick={() => { setShowAreaPicker(!showAreaPicker); setNewAreaSelection([]) }}
              >
                {showAreaPicker ? 'Cancel' : '+ Request New Areas'}
              </button>
            </div>
            
            {areaStatusLoading ? (
              <div className="muted">Loading service areas...</div>
            ) : areaStatus ? (
              <>
                {/* Current approved areas */}
                {(areaStatus.approved_areas?.length > 0 || areaStatus.ungrouped_postal_codes?.length > 0) ? (
                  <div style={{ marginBottom: '1rem' }}>
                    <div style={{ fontSize: '0.85em', fontWeight: 600, textTransform: 'uppercase', opacity: 0.6, marginBottom: '0.5rem' }}>
                      Approved Service Areas ({areaStatus.total_postal_codes} postal codes)
                    </div>
                    
                    {/* Areas grouped by admin region */}
                    {areaStatus.approved_areas?.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        {areaStatus.approved_areas.map(area => (
                          <span 
                            key={area.area_id} 
                            style={{
                              background: 'var(--accent-green-soft, rgba(124, 144, 112, 0.15))',
                              border: '1px solid var(--accent-green, #7C9070)',
                              borderRadius: '6px',
                              padding: '0.35rem 0.75rem',
                              fontSize: '0.9em'
                            }}
                          >
                            {area.name}
                            {area.name_local && area.name_local !== area.name && (
                              <span style={{ opacity: 0.6, marginLeft: '0.35rem' }}>{area.name_local}</span>
                            )}
                            <span style={{ opacity: 0.5, marginLeft: '0.35rem' }}>({area.postal_code_count})</span>
                          </span>
                        ))}
                      </div>
                    )}
                    
                    {/* Individual postal codes not linked to an admin area */}
                    {areaStatus.ungrouped_postal_codes?.length > 0 && (
                      <div>
                        <div style={{ fontSize: '0.8em', opacity: 0.6, marginBottom: '0.35rem' }}>
                          Individual postal codes:
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                          {areaStatus.ungrouped_postal_codes.map(pc => (
                            <span 
                              key={pc.id} 
                              style={{
                                background: 'var(--bg-muted, #f5f5f5)',
                                border: '1px solid var(--border, #ddd)',
                                borderRadius: '4px',
                                padding: '0.25rem 0.5rem',
                                fontSize: '0.85em'
                              }}
                            >
                              {pc.code}
                              {pc.place_name && <span style={{ opacity: 0.6, marginLeft: '0.25rem' }}>({pc.place_name})</span>}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="muted" style={{ marginBottom: '1rem' }}>
                    No approved service areas yet. Request areas below.
                  </div>
                )}
                
                {/* Pending requests */}
                {areaStatus.pending_requests?.length > 0 && (
                  <div style={{ 
                    marginBottom: '1rem', 
                    padding: '0.75rem', 
                    background: 'rgba(255, 193, 7, 0.15)', 
                    borderRadius: '6px', 
                    border: '1px solid rgba(255, 193, 7, 0.4)' 
                  }}>
                    <div style={{ fontSize: '0.85em', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-warning, #ffc107)' }}>
                      ⏳ Pending Requests
                    </div>
                    {areaStatus.pending_requests.map(req => (
                      <div key={req.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <div>
                          <span style={{ color: 'var(--text, inherit)' }}>{req.areas.map(a => a.name).join(', ') || 'Individual codes'}</span>
                          <span style={{ marginLeft: '0.5rem', opacity: 0.7 }}>({req.total_codes_requested} codes)</span>
                        </div>
                        <button 
                          className="btn btn-outline btn-sm" 
                          onClick={() => cancelAreaRequest(req.id)}
                          style={{ color: '#ff6b6b', borderColor: '#ff6b6b' }}
                        >
                          Cancel
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                
                {/* Request new areas form */}
                {showAreaPicker && (
                  <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                    <div style={{ fontSize: '0.85em', fontWeight: 600, textTransform: 'uppercase', opacity: 0.6, marginBottom: '0.5rem' }}>
                      Request Additional Areas
                    </div>
                    <p className="muted" style={{ fontSize: '0.85em', marginBottom: '0.75rem' }}>
                      Select areas you want to serve. Your request will be reviewed by an admin.
                      You'll keep your existing approved areas while the request is pending.
                    </p>
                    
                    <ServiceAreaPicker
                      country={
                        // Try multiple sources for country code
                        areaStatus?.approved_areas?.[0]?.country ||
                        areaStatus?.ungrouped_postal_codes?.[0]?.country ||
                        chef?.serving_postalcodes?.[0]?.country ||
                        'US'
                      }
                      selectedAreas={newAreaSelection}
                      onChange={setNewAreaSelection}
                      maxHeight="400px"
                    />
                    
                    <div style={{ marginTop: '0.75rem' }}>
                      <div className="label">Notes (optional)</div>
                      <textarea 
                        className="textarea" 
                        rows={2} 
                        value={areaRequestNotes}
                        onChange={e => setAreaRequestNotes(e.target.value)}
                        placeholder="Why do you want to serve these areas?"
                      />
                    </div>
                    
                    <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                      <button 
                        className="btn btn-primary"
                        disabled={submittingAreaRequest || newAreaSelection.length === 0}
                        onClick={submitAreaRequest}
                      >
                        {submittingAreaRequest ? 'Submitting...' : `Request ${newAreaSelection.length} Area${newAreaSelection.length !== 1 ? 's' : ''}`}
                      </button>
                      <button 
                        className="btn btn-outline"
                        onClick={() => { setShowAreaPicker(false); setNewAreaSelection([]) }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
                
                {/* Recent history */}
                {areaStatus.request_history?.length > 0 && !showAreaPicker && (
                  <details style={{ marginTop: '1rem' }}>
                    <summary style={{ cursor: 'pointer', fontSize: '0.85em', opacity: 0.7 }}>
                      Recent request history
                    </summary>
                    <div style={{ marginTop: '0.5rem' }}>
                      {areaStatus.request_history.map(req => {
                        const statusColors = {
                          approved: { bg: 'rgba(124, 144, 112, 0.2)', color: '#7C9070' },
                          rejected: { bg: 'rgba(217, 83, 79, 0.2)', color: '#d9534f' },
                          partially_approved: { bg: 'rgba(91, 192, 222, 0.2)', color: '#5bc0de' },
                        }
                        const style = statusColors[req.status] || { bg: 'var(--neutral-bg)', color: 'inherit' }

                        return (
                          <div key={req.id} style={{
                            padding: '0.5rem',
                            marginBottom: '0.35rem',
                            borderRadius: 'var(--radius-sm)',
                            background: 'var(--surface-2)',
                            border: '1px solid var(--border)',
                            fontSize: '0.9em'
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span>
                                {req.areas_count} area{req.areas_count !== 1 ? 's' : ''} requested
                                <span style={{ marginLeft: '0.5rem', opacity: 0.6 }}>
                                  {new Date(req.created_at).toLocaleDateString()}
                                </span>
                              </span>
                              <span style={{ 
                                padding: '2px 8px', 
                                borderRadius: '3px',
                                fontSize: '0.85em',
                                background: style.bg,
                                color: style.color
                              }}>
                                {req.status_display || req.status}
                              </span>
                            </div>
                            
                            {/* Show approval details for partial approvals */}
                            {req.status === 'partially_approved' && req.approval_summary && (
                              <div style={{ marginTop: '0.5rem', fontSize: '0.85em' }}>
                                <div style={{ color: '#7C9070' }}>
                                  ✅ Approved: {req.approval_summary.approved_areas} areas ({req.approval_summary.approved_codes} codes)
                                </div>
                                <div style={{ color: '#d9534f' }}>
                                  ❌ Rejected: {req.approval_summary.rejected_areas} areas ({req.approval_summary.rejected_codes} codes)
                                </div>
                                {req.approved_areas?.length > 0 && (
                                  <div style={{ marginTop: '0.25rem', opacity: 0.8 }}>
                                    <span style={{ fontWeight: 500 }}>Approved:</span> {req.approved_areas.map(a => a.name).join(', ')}
                                  </div>
                                )}
                                {req.rejected_areas?.length > 0 && (
                                  <div style={{ opacity: 0.6 }}>
                                    <span style={{ fontWeight: 500 }}>Not approved:</span> {req.rejected_areas.map(a => a.name).join(', ')}
                                  </div>
                                )}
                              </div>
                            )}
                            
                            {/* Show admin notes if any */}
                            {req.admin_notes && (
                              <div style={{ marginTop: '0.35rem', fontSize: '0.85em', opacity: 0.7, fontStyle: 'italic' }}>
                                "{req.admin_notes}"
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </details>
                )}
              </>
            ) : (
              <div className="muted">Unable to load service areas</div>
            )}
          </div>
          
          <div className="card">
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between'}}>
              <h3 style={{margin:0}}>Public preview</h3>
              {chef?.user?.username && (
                <Link className="btn btn-outline" to={`/c/${encodeURIComponent(chef.user.username)}`} target="_blank" rel="noreferrer">View public profile ↗</Link>
              )}
            </div>
            {chef ? (
              <div className="page-public-chef" style={{marginTop:'.5rem'}}>
                {/* Banner */}
                {(()=>{
                  const banner = bannerPreview || chef.banner_url
                  if (!banner) return null
                  return (
                    <div className={`cover has-bg`} style={{ backgroundImage:`linear-gradient(180deg, rgba(0,0,0,.35), rgba(0,0,0,.35)), url(${banner})` }}>
                      <div className="cover-inner">
                        <div className="cover-center">
                          <div className="eyebrow inv">Chef Profile</div>
                          <h1 className="title inv">{chef?.user?.username || 'Chef'}</h1>
                          {(previewLocation || areaSummary.totalAreas > 0) && (
                            <div className="chef-hero-location-row">
                              {previewLocation && (
                                <div className="chef-hero-location">
                                  <i className="fa-solid fa-location-dot"></i>
                                  <span><strong>{previewLocation}</strong></span>
                                </div>
                              )}
                              {areaSummary.totalAreas > 0 && (
                                <button
                                  className="chef-hero-availability-btn"
                                  onClick={() => setAreasModalOpen(true)}
                                >
                                  <i className="fa-solid fa-map-location-dot"></i>
                                  <span>Check Availability</span>
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })()}
                {/* Identity row */}
                <div className="profile-card card" style={{marginTop: bannerPreview||chef.banner_url?'-20px':'0'}}>
                  <div className="profile-card-inner">
                    <div className="avatar-wrap">
                      { (profilePicPreview || chef.profile_pic_url) && (
                        <img className="avatar-xl" src={profilePicPreview || chef.profile_pic_url} alt="Profile" />
                      )}
                    </div>
                    <div className="profile-main">
                      <h2 style={{margin:'0 0 .25rem 0'}}>{chef?.user?.username || 'Chef'}</h2>
                      {chef?.review_summary && <div className="muted" style={{marginBottom:'.35rem'}}>{chef.review_summary}</div>}
                    </div>
                  </div>
                </div>
                {/* Experience / About */}
                {(profileForm.experience || profileForm.bio || chef.experience || chef.bio) && (
                  <div className="grid grid-2 section">
                    <div className="card">
                      <h3>Experience</h3>
                      <div>{profileForm.experience || chef.experience || '—'}</div>
                    </div>
                    <div className="card">
                      <h3>About</h3>
                      <div>{profileForm.bio || chef.bio || '—'}</div>
                    </div>
                  </div>
                )}
                {/* Gallery thumbnails */}
                {Array.isArray(chef.photos) && chef.photos.length>0 && (
                  <div className="section">
                    <h3 className="sig-title" style={{textAlign:'left'}}>Gallery</h3>
                    <div className="thumb-grid">
                      {chef.photos.slice(0,6).map(p => (
                        <div key={p.id} className="thumb-card"><div className="thumb-img-wrap"><img src={p.image_url} alt={p.title||'Photo'} /></div></div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (<div className="muted">No profile loaded.</div>)}
            <ServiceAreasModal
              open={areasModalOpen}
              onClose={() => setAreasModalOpen(false)}
              areas={chef?.serving_postalcodes || []}
              chefName={chef?.user?.username || 'Chef'}
            />
          </div>
        </div>
          )}

          {/* Photos Sub-tab */}
          {profileSubTab === 'photos' && (
        <div className="grid grid-2">
          <div className="card" data-testid="photo-upload-card">
            <h3>Upload photo</h3>
            <div className="label">Image</div>
            <FileSelect label="Choose file" accept="image/jpeg,image/png,image/webp" onChange={(f)=> setPhotoForm(p=>({ ...p, image: f }))} />
            <div className="label">Title</div>
            <input
              className="input"
              data-testid="photo-title"
              name="photo-title"
              aria-label="Photo title"
              value={photoForm.title}
              onChange={e=> setPhotoForm(f=>({ ...f, title:e.target.value }))}
            />
            <div className="label">Caption</div>
            <input
              className="input"
              data-testid="photo-caption"
              name="photo-caption"
              aria-label="Photo caption"
              value={photoForm.caption}
              onChange={e=> setPhotoForm(f=>({ ...f, caption:e.target.value }))}
            />
            <div style={{marginTop:'.35rem'}}>
              <label style={{display:'inline-flex', alignItems:'center', gap:'.35rem'}}>
                <input type="checkbox" checked={photoForm.is_featured} onChange={e=> setPhotoForm(f=>({ ...f, is_featured:e.target.checked }))} />
                <span>Featured</span>
              </label>
            </div>
            <div style={{marginTop:'.6rem'}}>
              <button className="btn btn-primary" disabled={photoUploading || !photoForm.image} onClick={async ()=>{
                setPhotoUploading(true)
                try{
                  const f = photoForm.image
                  const mime = (f && f.type) ? f.type.toLowerCase() : ''
                  const name = (f && f.name) ? f.name.toLowerCase() : ''
                  const isHeic = mime.includes('heic') || mime.includes('heif') || name.endsWith('.heic') || name.endsWith('.heif')
                  if (isHeic){
                    try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'HEIC images are not supported. Please upload JPG, PNG, or WEBP.', tone:'error' } })) }catch{}
                    setPhotoUploading(false)
                    return
                  }
                  const fd = new FormData(); fd.append('image', f); if (photoForm.title) fd.append('title', photoForm.title); if (photoForm.caption) fd.append('caption', photoForm.caption); if (photoForm.is_featured) fd.append('is_featured','true')
                  // Let axios set the multipart boundary automatically
                  await api.post('/chefs/api/me/chef/photos/', fd)
                  setPhotoForm({ image:null, title:'', caption:'', is_featured:false })
                  await loadChefProfile()
                  try{ window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text:'Photo uploaded', tone:'success' } })) }catch{}
                }catch(e){
                  // Build a richer message (HTML safe) using the global helper
                  try{
                    const { buildErrorMessage } = await import('../api')
                    const msg = buildErrorMessage(e?.response?.data, 'Failed to upload photo', e?.response?.status)
                    window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
                  }catch{
                    const msg = e?.response?.data?.error || e?.response?.data?.detail || 'Failed to upload photo'
                    window.dispatchEvent(new CustomEvent('global-toast', { detail:{ text: msg, tone:'error' } }))
                  }
                } finally { setPhotoUploading(false) }
              }}>{photoUploading?'Uploading…':'Upload'}</button>
            </div>
          </div>
          <div className="card">
            <h3>Your gallery</h3>
            {!chef?.photos || chef.photos.length===0 ? <div className="muted">No photos yet.</div> : (
              <div className="thumb-grid">
                {chef.photos.map(p => (
                  <div key={p.id} className="card thumb-card" style={{padding:'.5rem'}}>
                    <div className="thumb-img-wrap"><img src={p.image_url} alt={p.title||'Photo'} /></div>
                    <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:'.35rem'}}>
                      <div style={{fontWeight:700}}>{p.title || 'Untitled'}</div>
                      {p.is_featured && <span className="chip">Featured</span>}
                    </div>
                    {p.caption && <div className="muted" style={{marginTop:'.15rem'}}>{p.caption}</div>}
                   <div style={{marginTop:'.4rem'}}>
                      <button className="btn btn-outline btn-sm" onClick={async ()=>{ try{ await api.delete(`/chefs/api/me/chef/photos/${p.id}/`); await loadChefProfile() }catch(e){ console.error('delete photo failed', e) } }}>Delete</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
          )}
        </div>
      )}

      {tab==='compliance' && (
        <div>
          <header style={{ marginBottom: '1.5rem' }}>
            <h1 style={{ margin: '0 0 .25rem 0' }}>Home Kitchen</h1>
            <p style={{ color: 'var(--muted)', margin: 0 }}>
              Set up and manage your home kitchen operation on Sautai.
            </p>
          </header>
          <MehkoEnrollmentPanel onNavigate={setTab} />
        </div>
      )}

      {/* Legacy photos tab - redirect to profile/photos */}
      {tab==='photos' && (
        <div style={{textAlign:'center', padding:'2rem'}}>
          <p className="muted">Photos have moved to the Profile tab.</p>
          <button className="btn btn-primary" onClick={() => { setTab('profile'); setProfileSubTab('photos'); }}>
            Go to Profile → Photos
          </button>
        </div>
      )}


      {/* Menu Builder - merged Kitchen + Meals */}
      {tab==='menu' && (
        <div>
          {/* Menu Builder - Sub-tab Navigation */}
          <header style={{marginBottom:'1rem'}}>
            <h1 style={{margin:'0 0 .5rem 0'}}>Menu Builder</h1>
            <div className="sub-tab-nav">
              <button 
                className={`sub-tab ${menuSubTab === 'ingredients' ? 'active' : ''}`}
                onClick={() => setMenuSubTab('ingredients')}
              >
                Ingredients {ingredients.length > 0 && <span className="sub-tab-badge">{ingredients.length}</span>}
              </button>
              <button 
                className={`sub-tab ${menuSubTab === 'dishes' ? 'active' : ''}`}
                onClick={() => setMenuSubTab('dishes')}
              >
                Dishes {dishes.length > 0 && <span className="sub-tab-badge">{dishes.length}</span>}
              </button>
              <button 
                className={`sub-tab ${menuSubTab === 'meals' ? 'active' : ''}`}
                onClick={() => setMenuSubTab('meals')}
              >
                Meals {meals.length > 0 && <span className="sub-tab-badge">{meals.length}</span>}
              </button>
            </div>
          </header>

          {/* Ingredients Sub-tab */}
          {menuSubTab === 'ingredients' && (
          <div className="chef-kitchen-section">
            <div className="chef-kitchen-section-header">
              <div>
                <h2 className="chef-kitchen-section-title">
                  <i className="fa-solid fa-carrot" style={{fontSize:'20px'}}></i>
                  Ingredients
                  <span className="chef-count-badge">{ingredients.length}</span>
                </h2>
                <p className="muted" style={{marginTop:'.25rem', fontSize:'.9rem'}}>Building blocks for your dishes</p>
              </div>
              <button className="btn btn-primary btn-sm" onClick={()=> setShowIngredientForm(!showIngredientForm)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                {showIngredientForm ? 'Cancel' : 'Add'}
              </button>
            </div>

            {/* Search bar for ingredients - shown when there are many */}
            {ingredients.length > INGREDIENT_INITIAL_LIMIT && (
              <div style={{ marginBottom: '1rem' }}>
                <input
                  type="text"
                  className="input"
                  placeholder="Search ingredients..."
                  value={ingredientSearch}
                  onChange={e => {
                    setIngredientSearch(e.target.value)
                    setShowAllIngredients(false)
                  }}
                  style={{ maxWidth: '300px' }}
                />
              </div>
            )}

            {showIngredientForm && (
              <div className="card chef-create-card" style={{marginBottom:'1rem', marginTop:'.75rem'}}>
                <h3 style={{marginTop:0}}>Create ingredient</h3>
                <form onSubmit={createIngredient}>
                  <div className="label">Name</div>
                  <input className="input" value={ingForm.name} onChange={e=> setIngForm(f=>({ ...f, name:e.target.value }))} required placeholder="e.g., Chicken Breast" />
                  {duplicateIngredient && <div className="muted" style={{marginTop:'.25rem'}}>Ingredient already exists.</div>}
                  <div className="grid" style={{gridTemplateColumns:'repeat(auto-fit, minmax(100px, 1fr))', gap:'.5rem', marginTop:'.5rem'}}>
                    {['calories','fat','carbohydrates','protein'].map(k => (
                      <div key={k}>
                        <div className="label" style={{textTransform:'capitalize'}}>{k.replace('_',' ')}</div>
                        <input className="input" type="number" step="0.1" value={ingForm[k]} onChange={e=> setIngForm(f=>({ ...f, [k]: e.target.value }))} placeholder="0" />
                      </div>
                    ))}
                  </div>
                  {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to add ingredients.</div>}
                  <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem'}}>
                    <button className="btn btn-primary" disabled={!payouts.is_active || ingLoading || duplicateIngredient}>
                      {ingLoading?'Saving…':'Add Ingredient'}
                    </button>
                    <button type="button" className="btn btn-outline" onClick={()=> setShowIngredientForm(false)}>Cancel</button>
                  </div>
                </form>
              </div>
            )}

            {ingredients.length === 0 ? (
              <div className="chef-empty-state chef-empty-state-compact">
                <p>No ingredients yet. Click "Add" to create your first ingredient.</p>
              </div>
            ) : filteredIngredients.length === 0 ? (
              <div className="chef-empty-state chef-empty-state-compact">
                <p>No ingredients match "{ingredientSearch}"</p>
                <button 
                  className="btn btn-outline btn-sm" 
                  onClick={() => setIngredientSearch('')}
                  style={{ marginTop: '.5rem' }}
                >
                  Clear search
                </button>
              </div>
            ) : (
              <>
                <div className="chef-items-grid">
                  {displayedIngredients.map(i => (
                    <div key={i.id} className="chef-item-card chef-item-card-compact">
                      <div className="chef-item-info">
                        <div className="chef-item-name">{i.name}</div>
                        <div className="chef-item-meta">{Number(i.calories||0).toFixed(0)} cal</div>
                      </div>
                      <button className="btn btn-outline btn-sm" onClick={()=> deleteIngredient(i.id)}>×</button>
                    </div>
                  ))}
                </div>

                {/* Show more / Show less toggle */}
                {hasMoreIngredients && (
                  <button 
                    className="btn btn-outline" 
                    onClick={() => setShowAllIngredients(true)}
                    style={{ marginTop: '1rem', width: '100%' }}
                  >
                    Show all {filteredIngredients.length} ingredients
                  </button>
                )}
                {showAllIngredients && filteredIngredients.length > INGREDIENT_INITIAL_LIMIT && !ingredientSearch.trim() && (
                  <button 
                    className="btn btn-outline" 
                    onClick={() => setShowAllIngredients(false)}
                    style={{ marginTop: '1rem', width: '100%' }}
                  >
                    Show less
                  </button>
                )}
              </>
            )}
          </div>
          )}

          {/* Dishes Sub-tab */}
          {menuSubTab === 'dishes' && (
          <div className="chef-kitchen-section">
            <div className="chef-kitchen-section-header">
              <div>
                <h2 className="chef-kitchen-section-title">
                  <i className="fa-solid fa-bowl-food" style={{fontSize:'20px'}}></i>
                  Dishes
                  <span className="chef-count-badge">{dishes.length}</span>
                </h2>
                <p className="muted" style={{marginTop:'.25rem', fontSize:'.9rem'}}>Combinations of ingredients</p>
              </div>
              <button className="btn btn-primary btn-sm" onClick={()=> setShowDishForm(!showDishForm)} disabled={ingredients.length===0}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                {showDishForm ? 'Cancel' : 'Add'}
              </button>
            </div>

            {showDishForm && (
              <div className="card chef-create-card" style={{marginBottom:'1rem', marginTop:'.75rem'}}>
                <h3 style={{marginTop:0}}>Create dish</h3>
                <form onSubmit={createDish}>
                  <div className="label">Name</div>
                  <GhostInput
                    className="input"
                    value={dishForm.name}
                    onChange={val => setDishForm(f=>({ ...f, name: val }))}
                    ghostValue={dishNameGhost}
                    onAccept={(val) => {
                      setDishForm(f=>({ ...f, name: val }))
                      acceptSuggestion('ai_dish_name')
                    }}
                    onDismiss={() => dismissSuggestion('ai_dish_name')}
                    required
                    placeholder="e.g., Grilled Salmon"
                  />
                  <div className="label">Ingredients</div>
                  <select className="select" multiple value={dishForm.ingredient_ids} onChange={e=> {
                    const opts = Array.from(e.target.selectedOptions).map(o=>o.value); setDishForm(f=>({ ...f, ingredient_ids: opts }))
                  }} style={{minHeight:120}}>
                    {ingredients.map(i => <option key={i.id} value={String(i.id)}>{i.name}</option>)}
                  </select>
                  {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to create dishes.</div>}
                  <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem'}}>
                    <button className="btn btn-primary" disabled={!payouts.is_active}>Create Dish</button>
                    <button type="button" className="btn btn-outline" onClick={()=> setShowDishForm(false)}>Cancel</button>
                  </div>
                </form>
              </div>
            )}

            {dishes.length===0 ? (
              <div className="chef-empty-state chef-empty-state-compact">
                <p>{ingredients.length===0 ? 'Add ingredients first, then create dishes.' : 'No dishes yet. Click "Add" to create your first dish.'}</p>
              </div>
            ) : (
              <div className="chef-items-grid">
                {dishes.map(d => (
                  <div key={d.id} className="chef-item-card chef-item-card-compact">
                    <div className="chef-item-info">
                      <div className="chef-item-name">{d.name}</div>
                      {d.ingredients && d.ingredients.length>0 && (
                        <div className="chef-item-meta">{d.ingredients.length} ingredient{d.ingredients.length!==1?'s':''}</div>
                      )}
                    </div>
                    <button className="btn btn-outline btn-sm" onClick={()=> deleteDish(d.id)}>×</button>
                  </div>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Meals Sub-tab */}
          {menuSubTab === 'meals' && (
          <div className="chef-kitchen-section">
            <div className="chef-kitchen-section-header">
              <div>
                <h2 className="chef-kitchen-section-title">
                  <i className="fa-solid fa-utensils" style={{fontSize:'20px'}}></i>
                  Meals
                  <span className="chef-count-badge">{meals.length}</span>
                </h2>
                <p className="muted" style={{marginTop:'.25rem', fontSize:'.9rem'}}>Complete meals made from dishes</p>
              </div>
              <button className="btn btn-primary btn-sm" onClick={()=> setShowMealForm(!showMealForm)} disabled={dishes.length===0}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                {showMealForm ? 'Cancel' : 'Add'}
              </button>
            </div>

            {showMealForm && (
              <div className="card chef-create-card" style={{marginBottom:'1rem', marginTop:'.75rem'}}>
                <h3 style={{marginTop:0}}>Create meal</h3>
                <form onSubmit={createMeal} aria-busy={mealSaving}>
                  <div className="label">Name</div>
                  <div style={{display:'flex', gap:'8px', alignItems:'center'}}>
                    <GhostInput
                      className="input"
                      style={{flex:1}}
                      value={mealForm.name}
                      onChange={val => setMealForm(f=>({ ...f, name: val }))}
                      ghostValue={mealNameGhost}
                      onAccept={(val) => {
                        setMealForm(f=>({ ...f, name: val }))
                        acceptSuggestion('ai_meal_name')
                      }}
                      onDismiss={() => dismissSuggestion('ai_meal_name')}
                      required
                      placeholder="e.g., Sunday Family Dinner"
                    />
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={async () => {
                        if (!mealForm.name?.trim()) {
                          setNotice('Enter a meal name first to scaffold')
                          setTimeout(() => setNotice(null), 3000)
                          return
                        }
                        const result = await generateScaffold(mealForm.name, {
                          mealType: mealForm.meal_type || 'Dinner'
                        })
                        if (result) setShowScaffoldPreview(true)
                      }}
                      disabled={isScaffoldGenerating || !mealForm.name?.trim()}
                      title="Generate dishes and ingredients with AI"
                      style={{whiteSpace:'nowrap'}}
                    >
                      {isScaffoldGenerating ? '...' : '✨ Scaffold'}
                    </button>
                  </div>
                  <div className="label">Description</div>
                  <GhostTextarea
                    className="textarea"
                    rows={2}
                    value={mealForm.description}
                    onChange={val => setMealForm(f=>({ ...f, description: val }))}
                    ghostValue={mealDescGhost}
                    onAccept={(val) => {
                      setMealForm(f=>({ ...f, description: val }))
                      acceptSuggestion('ai_meal_description')
                    }}
                    onDismiss={() => dismissSuggestion('ai_meal_description')}
                    placeholder="Describe this meal..."
                  />
                  <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem', marginTop:'.5rem'}}>
                    <div>
                      <div className="label">Meal type</div>
                      <select className="select" value={mealForm.meal_type} onChange={e=> setMealForm(f=>({ ...f, meal_type:e.target.value }))}>
                        {['Breakfast','Lunch','Dinner'].map(x=> <option key={x} value={x}>{x}</option>)}
                      </select>
                    </div>
                    <div>
                      <div className="label">Price (USD)</div>
                      <input className="input" type="number" min="1" step="0.5" value={mealForm.price} onChange={e=> setMealForm(f=>({ ...f, price:e.target.value }))} required />
                    </div>
                  </div>
                  <div className="label" style={{marginTop:'.5rem'}}>Dishes</div>
                  {renderDishChecklist('meal-dish')}
                  {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to create meals.</div>}
                  <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem'}}>
                    <button className="btn btn-primary" disabled={!payouts.is_active || mealSaving}>{mealSaving ? 'Saving…' : 'Create Meal'}</button>
                    <button type="button" className="btn btn-outline" onClick={()=> setShowMealForm(false)}>Cancel</button>
                  </div>
                </form>
              </div>
            )}

            {meals.length===0 ? (
              <div className="chef-empty-state chef-empty-state-compact">
                <p>{dishes.length===0 ? 'Add dishes first, then create meals.' : 'No meals yet. Click "Add" to create your first meal.'}</p>
              </div>
            ) : (
              <div className="chef-items-list">
                {meals.map(m => (
                  <div 
                    key={m.id} 
                    className="chef-item-card chef-item-card-clickable"
                    onClick={() => { setSelectedMeal(m); setMealSlideoutOpen(true) }}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="chef-item-info">
                      <div className="chef-item-name">{m.name}</div>
                      <div className="chef-item-meta">
                        {m.meal_type} • {toCurrencyDisplay(m.price, 'USD')}
                        {m.description && ` • ${m.description.slice(0,60)}${m.description.length>60?'...':''}`}
                      </div>
                    </div>
                    <div className="chef-item-actions" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="view-details-hint" style={{ fontSize: '0.8rem', color: 'var(--text-muted, #6b7280)' }}>View →</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          )}
        </div>
      )}

      {/* Legacy kitchen tab - redirect to menu */}
      {tab==='kitchen' && (
        <div style={{textAlign:'center', padding:'2rem'}}>
          <p className="muted">Kitchen has been renamed to Menu Builder.</p>
          <button className="btn btn-primary" onClick={() => setTab('menu')}>
            Go to Menu Builder
          </button>
        </div>
      )}

      {/* Keep old tabs hidden for backward compatibility but not in nav */}
      {tab==='ingredients' && (
        <div>
          <SectionHeader 
            title="Ingredients" 
            subtitle="Manage your ingredient library for dishes and meals"
            onAdd={()=> setShowIngredientForm(!showIngredientForm)}
            addLabel={showIngredientForm ? 'Cancel' : 'Add Ingredient'}
          />

          {showIngredientForm && (
            <div className="card chef-create-card" style={{marginBottom:'1rem'}}>
              <h3 style={{marginTop:0}}>Create ingredient</h3>
              <form onSubmit={createIngredient}>
                <div className="label">Name</div>
                <input className="input" value={ingForm.name} onChange={e=> setIngForm(f=>({ ...f, name:e.target.value }))} required />
                {duplicateIngredient && <div className="muted" style={{marginTop:'.25rem'}}>Ingredient already exists.</div>}
                <div className="grid" style={{gridTemplateColumns:'repeat(auto-fit, minmax(100px, 1fr))', gap:'.5rem', marginTop:'.5rem'}}>
                  {['calories','fat','carbohydrates','protein'].map(k => (
                    <div key={k}>
                      <div className="label" style={{textTransform:'capitalize'}}>{k.replace('_',' ')}</div>
                      <input className="input" type="number" step="0.1" value={ingForm[k]} onChange={e=> setIngForm(f=>({ ...f, [k]: e.target.value }))} />
                    </div>
                  ))}
                </div>
                {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to add ingredients.</div>}
                <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem'}}>
                  <button className="btn btn-primary" disabled={!payouts.is_active || ingLoading || duplicateIngredient}>
                    {ingLoading?'Saving…':'Add Ingredient'}
                  </button>
                  <button type="button" className="btn btn-outline" onClick={()=> setShowIngredientForm(false)}>Cancel</button>
                </div>
              </form>
            </div>
          )}

          <div className="card">
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'1rem'}}>
              <h3 style={{margin:0}}>Your ingredients ({ingredients.length})</h3>
            </div>
            {ingredients.length===0 ? (
              <div className="chef-empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.3">
                  <path d="M18 8h1a4 4 0 0 1 0 8h-1M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/>
                  <line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/>
                </svg>
                <p>No ingredients yet. Click "Add Ingredient" to get started.</p>
              </div>
            ) : (
              <div className="chef-items-list">
                {ingredients.map(i => (
                  <div key={i.id} className="chef-item-card">
                    <div className="chef-item-info">
                      <div className="chef-item-name">{i.name}</div>
                      <div className="chef-item-meta">{Number(i.calories||0).toFixed(0)} cal • {Number(i.protein||0).toFixed(1)}g protein • {Number(i.carbohydrates||0).toFixed(1)}g carbs • {Number(i.fat||0).toFixed(1)}g fat</div>
                    </div>
                    <button className="btn btn-outline btn-sm" onClick={()=> deleteIngredient(i.id)}>Delete</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab==='dishes' && (
        <div>
          <SectionHeader 
            title="Dishes" 
            subtitle="Create dishes from your ingredients"
            onAdd={()=> setShowDishForm(!showDishForm)}
            addLabel={showDishForm ? 'Cancel' : 'Add Dish'}
          />

          {showDishForm && (
            <div className="card chef-create-card" style={{marginBottom:'1rem'}}>
              <h3 style={{marginTop:0}}>Create dish</h3>
              <form onSubmit={createDish}>
                <div className="label">Name</div>
                <input className="input" value={dishForm.name} onChange={e=> setDishForm(f=>({ ...f, name:e.target.value }))} required placeholder="e.g., Grilled Salmon" />
                <div className="label">Ingredients</div>
                {ingredients.length === 0 ? (
                  <div className="muted">No ingredients available. Create ingredients first.</div>
                ) : (
                  <select className="select" multiple value={dishForm.ingredient_ids} onChange={e=> {
                    const opts = Array.from(e.target.selectedOptions).map(o=>o.value); setDishForm(f=>({ ...f, ingredient_ids: opts }))
                  }} style={{minHeight:120}}>
                    {ingredients.map(i => <option key={i.id} value={String(i.id)}>{i.name}</option>)}
                  </select>
                )}
                {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to create dishes.</div>}
                <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem'}}>
                  <button className="btn btn-primary" disabled={!payouts.is_active || ingredients.length === 0}>Create Dish</button>
                  <button type="button" className="btn btn-outline" onClick={()=> setShowDishForm(false)}>Cancel</button>
                </div>
              </form>
            </div>
          )}

          <div className="card">
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'1rem'}}>
              <h3 style={{margin:0}}>Your dishes ({dishes.length})</h3>
            </div>
            {dishes.length===0 ? (
              <div className="chef-empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.3">
                  <circle cx="12" cy="12" r="10"/><path d="M12 6v12M6 12h12"/>
                </svg>
                <p>No dishes yet. Click "Add Dish" to get started.</p>
              </div>
            ) : (
              <div className="chef-items-list">
                {dishes.map(d => (
                  <div key={d.id} className="chef-item-card">
                    <div className="chef-item-info">
                      <div className="chef-item-name">{d.name}</div>
                      {d.ingredients && d.ingredients.length>0 && (
                        <div className="chef-item-meta">
                          {d.ingredients.map(x=>x.name||x).slice(0,5).join(', ')}{d.ingredients.length>5?', …':''}
                        </div>
                      )}
                    </div>
                    <button className="btn btn-outline btn-sm" onClick={()=> deleteDish(d.id)}>Delete</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab==='meals' && (
        <div>
      <SectionHeader 
        title="Meals" 
        subtitle="Create complete meals from your dishes"
        onAdd={()=> setShowMealForm(!showMealForm)}
        addLabel={showMealForm ? 'Cancel' : 'Add Meal'}
      />

      {!showMealForm && (
        <div style={{display:'flex', justifyContent:'flex-end', marginBottom:'1rem'}}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={mealSaving}
            onClick={()=> setShowMealForm(true)}
          >
            {mealSaving ? 'Saving…' : 'Create'}
          </button>
        </div>
      )}

      {showMealForm && (
        <div className="card chef-create-card" style={{marginBottom:'1rem'}}>
          <h3 style={{marginTop:0}}>Create meal</h3>
          <form onSubmit={createMeal} aria-busy={mealSaving}>
            <div className="label">Name</div>
            <div style={{display:'flex', gap:'8px', alignItems:'center'}}>
              <GhostInput
                className="input"
                style={{flex:1}}
                value={mealForm.name}
                onChange={val => setMealForm(f=>({ ...f, name: val }))}
                ghostValue={mealNameGhost}
                onAccept={(val) => {
                  setMealForm(f=>({ ...f, name: val }))
                  acceptSuggestion('ai_meal_name')
                }}
                onDismiss={() => dismissSuggestion('ai_meal_name')}
                required
                placeholder="e.g., Sunday Family Dinner"
              />
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={async () => {
                  if (!mealForm.name?.trim()) {
                    setNotice('Enter a meal name first to scaffold')
                    setTimeout(() => setNotice(null), 3000)
                    return
                  }
                  const result = await generateScaffold(mealForm.name, {
                    mealType: mealForm.meal_type || 'Dinner'
                  })
                  if (result) setShowScaffoldPreview(true)
                }}
                disabled={isScaffoldGenerating || !mealForm.name?.trim()}
                title="Generate dishes and ingredients with AI"
                style={{whiteSpace:'nowrap'}}
              >
                {isScaffoldGenerating ? '...' : '✨ Scaffold'}
              </button>
            </div>
            <div className="label">Description</div>
                <GhostTextarea
                  className="textarea"
                  rows={2}
                  value={mealForm.description}
                  onChange={val => setMealForm(f=>({ ...f, description: val }))}
                  ghostValue={mealDescGhost}
                  onAccept={(val) => {
                    setMealForm(f=>({ ...f, description: val }))
                    acceptSuggestion('ai_meal_description')
                  }}
                  onDismiss={() => dismissSuggestion('ai_meal_description')}
                  placeholder="Describe this meal..."
                />
                <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem', marginTop:'.5rem'}}>
                  <div>
                    <div className="label">Meal type</div>
                    <select className="select" value={mealForm.meal_type} onChange={e=> setMealForm(f=>({ ...f, meal_type:e.target.value }))}>
                      {['Breakfast','Lunch','Dinner'].map(x=> <option key={x} value={x}>{x}</option>)}
                    </select>
                  </div>
                  <div>
                    <div className="label">Price (USD)</div>
                    <input className="input" type="number" min="1" step="0.5" value={mealForm.price} onChange={e=> setMealForm(f=>({ ...f, price:e.target.value }))} required />
                  </div>
                </div>
                <div className="label" style={{marginTop:'.5rem'}}>Dishes</div>
                {renderDishChecklist('meal-dish')}
                {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to create meals.</div>}
                <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem'}}>
                  <button className="btn btn-primary" disabled={!payouts.is_active || mealSaving}>{mealSaving ? 'Saving…' : 'Create Meal'}</button>
                  <button type="button" className="btn btn-outline" onClick={()=> setShowMealForm(false)}>Cancel</button>
                </div>
              </form>
            </div>
          )}

          <div className="card">
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'1rem'}}>
              <h3 style={{margin:0}}>Your meals ({meals.length})</h3>
            </div>
            {meals.length===0 ? (
              <div className="chef-empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.3">
                  <path d="M17 21v-2a1 1 0 0 1-1-1v-1a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1a1 1 0 0 1-1 1v2M7 21v-2a1 1 0 0 1-1-1v-1a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1a1 1 0 0 1-1 1v2M12 11V6M12 6a4 4 0 1 0 0-8"/>
                </svg>
                <p>No meals yet. Click "Add Meal" to get started.</p>
              </div>
            ) : (
              <div className="chef-items-list">
                {meals.map(m => (
                  <div 
                    key={m.id} 
                    className="chef-item-card chef-item-card-clickable"
                    onClick={() => { setSelectedMeal(m); setMealSlideoutOpen(true) }}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="chef-item-info">
                      <div className="chef-item-name">{m.name}</div>
                      <div className="chef-item-meta">
                        {m.meal_type} • {toCurrencyDisplay(m.price, 'USD')}
                        {m.description && ` • ${m.description.slice(0,60)}${m.description.length>60?'...':''}`}
                      </div>
                    </div>
                    <div className="chef-item-actions" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="view-details-hint" style={{ fontSize: '0.8rem', color: 'var(--text-muted, #6b7280)' }}>View →</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab==='services' && (
        <div>
          {/* Services - Sub-tab Navigation */}
          <header style={{marginBottom:'1rem'}}>
            <h1 style={{margin:'0 0 .5rem 0'}}>Services</h1>
            <div className="sub-tab-nav">
              <button 
                className={`sub-tab ${servicesSubTab === 'services' ? 'active' : ''}`}
                onClick={() => setServicesSubTab('services')}
              >
                Offerings {serviceOfferings.length > 0 && <span className="sub-tab-badge">{serviceOfferings.length}</span>}
              </button>
              <button 
                className={`sub-tab ${servicesSubTab === 'meal-shares' ? 'active' : ''}`}
                onClick={() => setServicesSubTab('meal-shares')}
              >
                Meal Shares {events.length > 0 && <span className="sub-tab-badge">{events.length}</span>}
              </button>
            </div>
          </header>

          {/* Service Offerings Sub-tab */}
          {servicesSubTab === 'services' && (
        <div className="grid grid-2">
          <div key={serviceForm.id ? `edit-form-${editFormGlowKey}` : 'create-form'} className={`card${serviceForm.id ? ' edit-form-glow' : ''}`}>
            <h3 style={{marginTop:0}}>{serviceForm.id ? 'Edit service offering' : 'Create service offering'}</h3>
            <form onSubmit={submitServiceOffering}>
              <div className="label">Service type</div>
              <select className="select" value={serviceForm.service_type} onChange={e=> setServiceForm(f=>({ ...f, service_type: e.target.value }))}>
                {SERVICE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <div className="label">Title</div>
              <input className="input" value={serviceForm.title} onChange={e=> setServiceForm(f=>({ ...f, title:e.target.value }))} required />
              <div className="label">Description</div>
              <textarea className="textarea" rows={3} value={serviceForm.description} onChange={e=> setServiceForm(f=>({ ...f, description:e.target.value }))} placeholder="What does this service include?" />
              <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem'}}>
                <div>
                  <div className="label">Default duration (minutes)</div>
                  <input className="input" type="number" min="30" step="15" value={serviceForm.default_duration_minutes} onChange={e=> setServiceForm(f=>({ ...f, default_duration_minutes: e.target.value }))} />
                </div>
                <div>
                  <div className="label">Max travel miles</div>
                  <input className="input" type="number" min="0" step="1" value={serviceForm.max_travel_miles} onChange={e=> setServiceForm(f=>({ ...f, max_travel_miles: e.target.value }))} />
                </div>
              </div>
              <div className="label">Notes</div>
              <textarea className="textarea" rows={2} value={serviceForm.notes} onChange={e=> setServiceForm(f=>({ ...f, notes:e.target.value }))} placeholder="Special requirements, supplies, etc." />
              <div className="label">Target customers (optional)</div>
              {acceptedCustomerOptions.length === 0 ? (
                <div className="muted" style={{fontSize:'.85rem'}}>
                  You do not have accepted connections yet. Leave this multiselect empty to publish a public offering.
                </div>
              ) : (
                <div style={{display:'flex', flexDirection:'column', gap:'.5rem'}}>
                  {/* Selected customers as chips */}
                  {serviceForm.targetCustomerIds.length > 0 && (
                    <div style={{display:'flex', flexWrap:'wrap', gap:'.35rem'}}>
                      {serviceForm.targetCustomerIds.map(id => {
                        const option = acceptedCustomerOptions.find(o => o.value === id)
                        if (!option) return null
                        return (
                          <span key={id} className="chip" style={{display:'inline-flex', alignItems:'center', gap:'.35rem', paddingRight:'.35rem'}}>
                            {option.label}
                            <button
                              type="button"
                              onClick={() => setServiceForm(f => ({ ...f, targetCustomerIds: f.targetCustomerIds.filter(cid => cid !== id) }))}
                              style={{
                                background:'none',
                                border:'none',
                                cursor:'pointer',
                                padding:'0',
                                marginLeft:'.1rem',
                                lineHeight:'1',
                                fontSize:'1.1rem',
                                color:'inherit',
                                opacity:'.7',
                                borderRadius:'50%',
                                width:'18px',
                                height:'18px',
                                display:'flex',
                                alignItems:'center',
                                justifyContent:'center'
                              }}
                              onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                              onMouseLeave={e => e.currentTarget.style.opacity = '.7'}
                              aria-label={`Remove ${option.label}`}
                            >
                              ×
                            </button>
                          </span>
                        )
                      })}
                    </div>
                  )}
                  {/* Dropdown to add customers */}
                  {(() => {
                    const unselected = acceptedCustomerOptions.filter(o => !serviceForm.targetCustomerIds.includes(o.value))
                    if (unselected.length === 0) return null
                    return (
                      <select
                        className="select"
                        value=""
                        onChange={e => {
                          if (!e.target.value) return
                          setServiceForm(f => ({ ...f, targetCustomerIds: [...f.targetCustomerIds, e.target.value] }))
                        }}
                      >
                        <option value="">Add a customer…</option>
                        {unselected.map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    )
                  })()}
                  {serviceForm.targetCustomerIds.length > 0 && acceptedCustomerOptions.filter(o => !serviceForm.targetCustomerIds.includes(o.value)).length === 0 && (
                    <div className="muted" style={{fontSize:'.85rem'}}>All accepted customers selected.</div>
                  )}
                </div>
              )}
              <p className="muted" style={{margin:'0.35rem 0 0', fontSize:'.82rem'}}>
                Use the multiselect to target accepted customers. Leave it blank to keep the service visible to everyone.
              </p>
              {serviceErrorMessages.length>0 && (
                <div style={{marginTop:'.5rem', color:'#b00020'}}>
                  <ul style={{margin:0, paddingLeft:'1rem'}}>
                    {serviceErrorMessages.map((msg, idx)=>(<li key={idx}>{msg}</li>))}
                  </ul>
                </div>
              )}
              {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to publish services.</div>}
              <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem', flexWrap:'wrap'}}>
                <button className="btn btn-primary" disabled={serviceSaving || !payouts.is_active}>{serviceSaving ? 'Saving…' : (serviceForm.id ? 'Save changes' : 'Create offering')}</button>
                {serviceForm.id && (
                  <button type="button" className="btn btn-outline" onClick={resetServiceForm} disabled={serviceSaving}>Cancel edit</button>
                )}
              </div>
            </form>
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:'1rem'}}>
            <div className="card" style={{background:'var(--surface-1)', padding:'1rem', display:'flex', flexDirection:'column', gap:'.6rem'}}>
              <h3 style={{margin:'0'}}>Service tier basics</h3>
              <p className="muted" style={{margin:0, fontSize:'.9rem'}}>
                Service tiers bundle household size, price, and billing frequency so guests can spot the right fit.
              </p>
              {tierSummaryExamples.length > 0 ? (
                <div>
                  <div className="label" style={{marginTop:0}}>Examples from your offerings</div>
                  <ul style={{margin:'.35rem 0 0', paddingLeft:'1.1rem', display:'flex', flexDirection:'column', gap:'.25rem', fontSize:'.9rem'}}>
                    {tierSummaryExamples.map((summary, index) => (
                      <li key={index}>{summary}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="muted" style={{fontSize:'.85rem'}}>Add tiers to see quick examples of how pricing appears to guests.</div>
              )}
              <p className="muted" style={{margin:0, fontSize:'.85rem'}}>
                Household range defines who each tier covers, and recurring options handle weekly or monthly plans.
              </p>
              <p className="muted" style={{margin:0, fontSize:'.85rem'}}>
                Stripe sync runs automatically once you save a tier—check the status chips below if something looks off.
              </p>
            </div>
            <div className="card">
              <h3>Your services</h3>
              {serviceLoading ? (
                <div className="muted">Loading…</div>
              ) : serviceOfferings.length===0 ? (
                <div className="muted">No services yet.</div>
              ) : (
                <div style={{display:'flex', flexDirection:'column', gap:'.75rem'}}>
                  {serviceOfferings.map(offering => {
                    const tiers = Array.isArray(offering.tiers) ? offering.tiers : []
                    const tierSummaries = Array.isArray(offering?.tier_summary)
                      ? offering.tier_summary.reduce((acc, summary) => {
                          const text = typeof summary === 'string' ? summary.trim() : String(summary || '').trim()
                          if (text) acc.push(text)
                          return acc
                        }, [])
                      : []
                    const isEditingTier = tierForm.offeringId === offering.id
                    const serviceTypeLabel = offering.service_type_label || toServiceTypeLabel(offering.service_type)
                    return (
                      <div key={offering.id} className={`card service-card-clickable${serviceForm.id === offering.id ? ' service-card-editing' : ''}`} style={{padding:'.75rem'}} onClick={() => editServiceOffering(offering)}>
                      <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:'.75rem', flexWrap:'wrap'}}>
                        <div>
                          <h4 style={{margin:'0 0 .25rem 0'}}>{offering.title || 'Untitled service'}</h4>
                          <div className="muted" style={{marginBottom:'.25rem'}}>{serviceTypeLabel}</div>
                          <div className="muted" style={{fontSize:'.85rem'}}>
                            {offering.default_duration_minutes ? `${offering.default_duration_minutes} min · ` : ''}
                            {offering.max_travel_miles ? `${offering.max_travel_miles} mi radius` : 'Travel radius not set'}
                          </div>
                        </div>
                        <div style={{display:'flex', flexDirection:'column', gap:'.35rem'}}>
                          <span className="chip" style={{background: offering.active ? 'var(--gradient-brand)' : '#ddd', color: offering.active ? '#fff' : '#333'}}>{offering.active ? 'Active' : 'Inactive'}</span>
                          <button className="btn btn-outline btn-sm" type="button" onClick={e => { e.stopPropagation(); editServiceOffering(offering) }}>Edit</button>
                          <button className="btn btn-outline btn-sm" type="button" onClick={e => { e.stopPropagation(); setDeleteOfferingId(offering.id) }} style={{color: 'var(--danger)', borderColor: 'color-mix(in oklab, var(--danger) 30%, var(--border))'}}>Delete</button>
                        </div>
                      </div>
                      {offering.description && <div style={{marginTop:'.35rem'}}>{offering.description}</div>}
                      {offering.notes && <div className="muted" style={{marginTop:'.35rem'}}>{offering.notes}</div>}
                      {tierSummaries.length > 0 && (
                        <div style={{marginTop:'.65rem'}}>
                          <div className="label" style={{marginTop:0}}>Tier overview</div>
                          <ul style={{margin:'.3rem 0 0', paddingLeft:'1.1rem', display:'flex', flexDirection:'column', gap:'.25rem', fontSize:'.9rem'}}>
                            {tierSummaries.map((summary, idx) => (
                              <li key={idx}>{summary}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <div style={{marginTop:'.75rem'}}>
                        <div className="label" style={{marginTop:0}}>Tiers</div>
                        {tiers.length===0 ? (
                          <div className="muted">No tiers yet.</div>
                        ) : (
                          <div style={{display:'flex', flexDirection:'column', gap:'.5rem'}}>
                            {tiers.map(tier => {
                              const priceDollars = tier.desired_unit_amount_cents != null ? (Number(tier.desired_unit_amount_cents)/100).toFixed(2) : '0.00'
                              const syncError = tier.last_price_sync_error || tier.price_sync_error || tier.sync_error || tier.price_sync_message || tier.last_error || ''
                              const rawStatus = String(tier.price_sync_status || tier.price_sync_state || '').toLowerCase()
                              let syncLabel = 'Stripe sync pending'
                              let syncChipStyle = { background: 'rgba(60,100,200,.15)', color: '#1b3a72' }
                              if (['success', 'synced', 'complete', 'completed'].includes(rawStatus)){
                                syncLabel = 'Stripe sync successful'
                                syncChipStyle = { background: 'rgba(24,180,24,.15)', color: '#168516' }
                              } else if (['error', 'failed', 'failure'].includes(rawStatus)){
                                syncLabel = 'Stripe sync failed'
                                syncChipStyle = { background: 'rgba(200,40,40,.15)', color: '#a11919' }
                              } else if (['processing', 'pending', 'queued', 'running', 'updating'].includes(rawStatus) || !rawStatus){
                                syncLabel = 'Stripe sync pending'
                                syncChipStyle = { background: 'rgba(60,100,200,.15)', color: '#1b3a72' }
                              } else {
                                syncLabel = `Stripe sync ${rawStatus}`
                                syncChipStyle = { background: 'rgba(60,100,200,.15)', color: '#1b3a72' }
                              }
                              const syncAt = tier.price_synced_at ? new Date(tier.price_synced_at) : null
                              const syncText = syncAt && !Number.isNaN(syncAt.valueOf()) ? syncAt.toLocaleString() : (tier.price_synced_at || '')
                              return (
                                <div key={tier.id} className="card" style={{padding:'.5rem'}}>
                                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:'.5rem'}}>
                                    <div>
                                      <strong>{tier.display_label || `${tier.household_min || 0}${tier.household_max ? `-${tier.household_max}` : '+'} people`}</strong>
                                      <div className="muted" style={{fontSize:'.85rem'}}>
                                        ${priceDollars} {tier.currency ? tier.currency.toUpperCase() : ''}{tier.is_recurring ? ` · Recurring ${tier.recurrence_interval || ''}` : ''}
                                      </div>
                                      <div className="muted" style={{fontSize:'.8rem'}}>
                                        Range: {tier.household_min || 0}{tier.household_max ? `-${tier.household_max}` : '+'}
                                      </div>
                                      <div style={{marginTop:'.25rem'}}>
                                        <span className="chip" style={syncChipStyle}>{syncLabel}</span>
                                        {!tier.active && <span className="chip" style={{marginLeft:'.35rem'}}>Inactive</span>}
                                      </div>
                                      {syncError && <div style={{marginTop:'.25rem', color:'#a11919', fontSize:'.85rem'}}>{syncError}</div>}
                                      {syncText && <div className="muted" style={{marginTop:'.25rem', fontSize:'.75rem'}}>Last synced: {syncText}</div>}
                                    </div>
                                    <button className="btn btn-outline btn-sm" type="button" onClick={e => { e.stopPropagation(); startTierForm(offering, tier) }}>Edit</button>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )}
                        <div style={{marginTop:'.5rem'}}>
                          <button className="btn btn-outline btn-sm" type="button" onClick={e => { e.stopPropagation(); startTierForm(offering) }}>Add tier</button>
                        </div>
                      </div>
                      {isEditingTier && (
                        <form onSubmit={submitTierForm} onClick={e => e.stopPropagation()} style={{marginTop:'.75rem', padding:'.75rem', border:'1px solid var(--border)', borderRadius:'8px', background:'rgba(0,0,0,.02)'}}>
                          <h4 style={{margin:'0 0 .5rem 0'}}>{tierForm.id ? 'Edit tier' : 'Create tier'}</h4>
                          <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem'}}>
                            <div>
                              <div className="label">Household min</div>
                              <input className="input" type="number" min="1" step="1" value={tierForm.household_min} onChange={e=> setTierForm(f=>({ ...f, household_min: e.target.value }))} />
                            </div>
                            <div>
                              <div className="label">Household max</div>
                              <input className="input" type="number" min="1" step="1" value={tierForm.household_max} onChange={e=> setTierForm(f=>({ ...f, household_max: e.target.value }))} placeholder="Unlimited" />
                            </div>
                          </div>
                          <div className="muted" style={{marginTop:'.35rem', fontSize:'.85rem'}}>
                            Household range defines how many people each tier covers.
                          </div>
                          <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem'}}>
                            <div>
                              <div className="label">Currency</div>
                              <input className="input" value={tierForm.currency} onChange={e=> setTierForm(f=>({ ...f, currency: e.target.value.toLowerCase() }))} />
                            </div>
                            <div>
                              <div className="label">Price</div>
                              <input className="input" type="number" min="0.5" step="0.5" value={tierForm.price} onChange={e=> setTierForm(f=>({ ...f, price: e.target.value }))} required />
                            </div>
                          </div>
                          <div style={{marginTop:'.35rem'}}>
                            <label style={{display:'inline-flex', alignItems:'center', gap:'.35rem'}}>
                              <input type="checkbox" checked={tierForm.is_recurring} onChange={e=> setTierForm(f=>({ ...f, is_recurring: e.target.checked }))} />
                              <span>Recurring</span>
                            </label>
                          </div>
                          <div className="muted" style={{marginTop:'.25rem', fontSize:'.85rem'}}>
                            Recurring tiers automatically handle future invoices.
                          </div>
                          {tierForm.is_recurring && (
                            <div style={{marginTop:'.35rem'}}>
                              <div className="label">Recurrence interval</div>
                              <select className="select" value={tierForm.recurrence_interval} onChange={e=> setTierForm(f=>({ ...f, recurrence_interval: e.target.value }))}>
                                <option value="week">Week</option>
                                <option value="month">Month</option>
                              </select>
                            </div>
                          )}
                          <div style={{marginTop:'.35rem'}}>
                            <label style={{display:'inline-flex', alignItems:'center', gap:'.35rem'}}>
                              <input type="checkbox" checked={tierForm.active} onChange={e=> setTierForm(f=>({ ...f, active: e.target.checked }))} />
                              <span>Active</span>
                            </label>
                          </div>
                          <div className="label">Display label</div>
                          <input className="input" value={tierForm.display_label} onChange={e=> setTierForm(f=>({ ...f, display_label: e.target.value }))} placeholder="Optional label shown to customers" />
                          <div className="muted" style={{marginTop:'.35rem', fontSize:'.85rem'}}>
                            Stripe creates or updates prices after you save a tier.
                          </div>
                          {tierErrorMessages.length>0 && (
                            <div style={{marginTop:'.5rem', color:'#b00020'}}>
                              <ul style={{margin:0, paddingLeft:'1rem'}}>
                                {tierErrorMessages.map((msg, idx)=>(<li key={idx}>{msg}</li>))}
                              </ul>
                            </div>
                          )}
                          {!payouts.is_active && <div className="muted" style={{marginTop:'.5rem'}}>Complete payouts setup to activate tiers.</div>}
                          <div style={{marginTop:'.75rem', display:'flex', gap:'.5rem', flexWrap:'wrap'}}>
                            <button className="btn btn-primary" disabled={tierSaving || !payouts.is_active}>{tierSaving ? 'Saving…' : (tierForm.id ? 'Save tier' : 'Create tier')}</button>
                            <button type="button" className="btn btn-outline" onClick={resetTierForm} disabled={tierSaving}>Cancel</button>
                          </div>
                        </form>
                      )}
                    </div>
                  )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
          )}

          <ConfirmDialog
            open={deleteOfferingId !== null}
            title="Delete Service"
            message="Are you sure you want to delete this service? This will also delete all pricing tiers. This action cannot be undone."
            confirmLabel="Delete"
            cancelLabel="Cancel"
            onConfirm={handleDeleteOffering}
            onCancel={() => setDeleteOfferingId(null)}
            busy={deleteOfferingBusy}
          />

          {/* Meal Shares Sub-tab */}
          {servicesSubTab === 'meal-shares' && (
        <div className="grid grid-2">
          <div className="card">
            <h3>Create Meal Share</h3>
            <form onSubmit={createEvent}>
              <div className="label">Meal</div>
              <select className="select" value={eventForm.meal||''} onChange={e=> setEventForm(f=>({ ...f, meal: e.target.value }))}>
                <option value="">Select meal…</option>
                {meals.map(m => <option key={m.id} value={String(m.id)}>{m.name}</option>)}
              </select>
              <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem', marginTop:'.35rem'}}>
                <div>
                  <div className="label">Event date</div>
                  <input className="input" type="date" value={eventForm.event_date} min={todayISO} onChange={e=> setEventForm(f=>({ ...f, event_date:e.target.value, order_cutoff_date:e.target.value }))} />
                </div>
                <div>
                  <div className="label">Event time</div>
                  <input className="input" type="time" value={eventForm.event_time} onChange={e=> setEventForm(f=>({ ...f, event_time:e.target.value }))} />
                </div>
              </div>
              <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem'}}>
                <div>
                  <div className="label">Cutoff date</div>
                  <input className="input" type="date" value={eventForm.order_cutoff_date} min={todayISO} onChange={e=> setEventForm(f=>({ ...f, order_cutoff_date:e.target.value }))} />
                </div>
                <div>
                  <div className="label">Cutoff time</div>
                  <input className="input" type="time" value={eventForm.order_cutoff_time} onChange={e=> setEventForm(f=>({ ...f, order_cutoff_time:e.target.value }))} />
                </div>
              </div>
              <div className="grid" style={{gridTemplateColumns:'repeat(3, 1fr)', gap:'.5rem'}}>
                <div>
                  <div className="label">Base price</div>
                  <input className="input" type="number" step="0.5" value={eventForm.base_price} onChange={e=> setEventForm(f=>({ ...f, base_price:e.target.value }))} />
                </div>
                <div>
                  <div className="label">Min price</div>
                  <input className="input" type="number" step="0.5" value={eventForm.min_price} onChange={e=> setEventForm(f=>({ ...f, min_price:e.target.value }))} />
                </div>
                <div>
                  <div className="label">Max orders</div>
                  <input className="input" type="number" min="1" step="1" value={eventForm.max_orders} onChange={e=> setEventForm(f=>({ ...f, max_orders:e.target.value }))} />
                </div>
              </div>
              <div className="grid" style={{gridTemplateColumns:'1fr 1fr', gap:'.5rem'}}>
                <div>
                  <div className="label">Min orders</div>
                  <input className="input" type="number" min="1" step="1" value={eventForm.min_orders} onChange={e=> setEventForm(f=>({ ...f, min_orders:e.target.value }))} />
                </div>
                <div>
                  <div className="label">Description</div>
                  <input className="input" value={eventForm.description} onChange={e=> setEventForm(f=>({ ...f, description:e.target.value }))} />
                </div>
              </div>
              <div className="label">Special instructions (optional)</div>
              <textarea className="textarea" value={eventForm.special_instructions} onChange={e=> setEventForm(f=>({ ...f, special_instructions:e.target.value }))} />
              {!payouts.is_active && <div className="muted" style={{marginTop:'.35rem'}}>Complete payouts setup to create meal shares.</div>}
              <div style={{marginTop:'.6rem'}}><button className="btn btn-primary" disabled={!payouts.is_active}>Create Meal Share</button></div>
            </form>
          </div>
          <div className="card">
            <h3>Your Meal Shares</h3>
            {upcomingEvents.length===0 && pastEvents.length===0 ? (
              <div className="muted">No meal shares yet.</div>
            ) : (
              <>
                <div>
                  <div className="label" style={{marginTop:0}}>Upcoming</div>
                  {upcomingEvents.length===0 ? <div className="muted">None</div> : (
                    <ul style={{listStyle:'none', padding:0, margin:0}}>
                      {upcomingEvents.map(e => (
                        <li key={e.id} style={{display:'flex', justifyContent:'space-between', alignItems:'center', padding:'.35rem 0', borderBottom:'1px solid var(--border)'}}>
                          <span><strong>{e.meal?.name || e.meal_name || 'Meal'}</strong> — {e.event_date} {e.event_time} ({e.orders_count || 0}/{e.max_orders || 0})</span>
                          <button 
                            className="btn btn-outline btn-xs" 
                            type="button" 
                            onClick={() => duplicateMealShare(e)}
                            title="Duplicate this meal share"
                          >
                            Duplicate
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {pastEvents.length>0 && (
                  <div style={{marginTop:'.6rem'}}>
                    <div className="label">Past</div>
                    {!showPastEvents && (
                      <button className="btn btn-outline btn-sm" type="button" onClick={()=> setShowPastEvents(true)}>Show past</button>
                    )}
                    {showPastEvents && (
                      <>
                        <div style={{maxHeight: 320, overflowY:'auto', marginTop:'.35rem'}}>
                          <ul style={{listStyle:'none', padding:0, margin:0}}>
                            {pastEvents.map(e => (
                              <li key={e.id} style={{display:'flex', justifyContent:'space-between', alignItems:'center', padding:'.35rem 0', borderBottom:'1px solid var(--border)'}}>
                                <span><span className="muted">{e.event_date} {e.event_time}</span> — <strong>{e.meal?.name || e.meal_name || 'Meal'}</strong></span>
                                <button 
                                  className="btn btn-outline btn-xs" 
                                  type="button" 
                                  onClick={() => duplicateMealShare(e)}
                                  title="Duplicate this meal share"
                                >
                                  Duplicate
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div style={{marginTop:'.25rem'}}>
                          <button className="btn btn-outline btn-sm" type="button" onClick={()=> setShowPastEvents(false)}>Hide past</button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
          )}
        </div>
      )}

      {/* Legacy events tab - redirect to services/meal-shares */}
      {tab==='events' && (
        <div style={{textAlign:'center', padding:'2rem'}}>
          <p className="muted">Meal Shares have moved to the Services tab.</p>
          <button className="btn btn-primary" onClick={() => { setTab('services'); setServicesSubTab('meal-shares'); }}>
            Go to Services → Meal Shares
          </button>
        </div>
      )}

      {tab==='orders' && (
        <div style={{display:'flex', flexDirection:'column', gap:'1rem'}}>
          <div className="card">
            <div className="chef-orders-header">
              <div>
                <h3 style={{margin:0}}>Orders</h3>
                <div className="muted" style={{marginTop:'.25rem'}}>Service and meal orders in one unified view.</div>
              </div>
              <div className="chef-orders-count" role="status" aria-live="polite">
                {isOrdersLoading ? 'Loading orders…' : `${filteredOrders.length} result${filteredOrders.length === 1 ? '' : 's'}`}
              </div>
            </div>

            <div className="chef-orders-toolbar" role="region" aria-label="Order filters">
              <div className="filter-group">
                <label className="label" htmlFor="chef-orders-search">Search</label>
                <input
                  id="chef-orders-search"
                  type="search"
                  className="input"
                  value={orderQuery}
                  onChange={e => setOrderQuery(e.target.value)}
                  placeholder="Search customer, meal, status…"
                />
              </div>
              <div className="filter-group">
                <label className="label" htmlFor="chef-orders-type">Type</label>
                <select
                  id="chef-orders-type"
                  className="select"
                  value={orderTypeFilter}
                  onChange={e => setOrderTypeFilter(e.target.value)}
                >
                  {orderTypeOptions.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div className="filter-group">
                <label className="label" htmlFor="chef-orders-status">Status</label>
                <select
                  id="chef-orders-status"
                  className="select"
                  value={orderStatusFilter}
                  onChange={e => setOrderStatusFilter(e.target.value)}
                >
                  {orderStatusOptions.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div className="filter-group">
                <label className="label" htmlFor="chef-orders-sort">Sort</label>
                <select
                  id="chef-orders-sort"
                  className="select"
                  value={orderSort}
                  onChange={e => setOrderSort(e.target.value)}
                >
                  {orderSortOptions.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div className="filter-actions">
                {hasOrderFilters && (
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => { setOrderQuery(''); setOrderTypeFilter('all'); setOrderStatusFilter('all') }}
                  >
                    Clear filters
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  onClick={() => { loadOrders(); loadServiceOrders() }}
                >
                  Refresh
                </button>
              </div>
            </div>
          </div>

          <div className="card">
            {isOrdersLoading ? (
              <div className="muted">Loading orders…</div>
            ) : orderPagination.items.length === 0 ? (
              <div className="chef-orders-empty">
                <div className="muted">{hasOrderFilters ? 'No orders match these filters.' : 'No orders yet.'}</div>
                {hasOrderFilters && (
                  <button
                    type="button"
                    className="btn btn-link"
                    onClick={() => { setOrderQuery(''); setOrderTypeFilter('all'); setOrderStatusFilter('all') }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            ) : (
              <div className="chef-orders-list">
                {orderPagination.items.map(order => {
                  const isFocused = order.type === 'service' && String(focusedOrderId || '') === String(order.id)
                  return (
                    <div
                      key={order.displayId}
                      ref={el => { if (order.type === 'service') orderRefs.current[order.id] = el }}
                      className={`chef-order-card${isFocused ? ' order-card-focused' : ''}`}
                    >
                      <div className="chef-order-header">
                        <div>
                          <div className="chef-order-customer">{order.customerName}</div>
                          {order.contactLine && (
                            <div className="muted chef-order-contact">{order.contactLine}</div>
                          )}
                        </div>
                        <div className="chef-order-badges">
                          <span className="chip small soft">{order.typeLabel}</span>
                          <span className="chip small" style={order.statusStyle}>{order.statusLabel}</span>
                        </div>
                      </div>
                      <div className="muted chef-order-title">{order.title}{order.subtitle ? ` · ${order.subtitle}` : ''}</div>
                      <div className="muted chef-order-schedule">{order.scheduleLabel}</div>
                      {(order.priceLabel || order.recurringLabel) && (
                        <div className="chef-order-meta">
                          {order.priceLabel && (
                            <span className="chip small soft" style={{background:'rgba(124,144,112,.12)', color:'#1f7a3d'}}>
                              {order.priceLabel}
                            </span>
                          )}
                          {order.recurringLabel && (
                            <span className="chip small soft" style={{background:'rgba(60,100,200,.12)', color:'#1b3a72'}}>
                              {order.recurringLabel}
                            </span>
                          )}
                        </div>
                      )}
                      {order.notes && (
                        <div className="muted chef-order-notes">
                          <strong style={{fontWeight:600, color:'var(--text)'}}>Notes:</strong> {order.notes}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {!isOrdersLoading && orderPagination.items.length > 0 && (
              <div className="chef-orders-pagination" role="navigation" aria-label="Orders pagination">
                <div className="chef-orders-pagination-info">
                  <span className="muted">Showing {orderStartIndex}-{orderEndIndex} of {sortedOrders.length}</span>
                </div>
                <div className="chef-orders-pagination-controls">
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => setOrderPage(page => Math.max(1, page - 1))}
                    disabled={orderPagination.page <= 1}
                  >
                    Previous
                  </button>
                  <span className="muted">Page {orderPagination.page} of {orderPagination.totalPages}</span>
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => setOrderPage(page => Math.min(orderPagination.totalPages, page + 1))}
                    disabled={orderPagination.page >= orderPagination.totalPages}
                  >
                    Next
                  </button>
                </div>
                <div className="chef-orders-pagination-size">
                  <label className="label" htmlFor="chef-orders-page-size">Per page</label>
                  <select
                    id="chef-orders-page-size"
                    className="select"
                    value={orderPageSize}
                    onChange={e => setOrderPageSize(Number(e.target.value))}
                  >
                    {orderPageSizeOptions.map(size => (
                      <option key={size} value={size}>{size}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      </main>

      {/* Floating Sous Chef Widget - always visible */}
      {chef && (
        <SousChefWidget
          sousChefEmoji={chef.sous_chef_emoji || '🧑‍🍳'}
          onEmojiChange={(emoji) => {
            setChef(prev => prev ? { ...prev, sous_chef_emoji: emoji } : prev)
          }}
          onAction={handleSousChefAction}
          suggestionCount={suggestions.length}
          suggestionPriority={suggestionPriority}
        />
      )}

      {/* Sous Chef Onboarding Modals */}
      <WelcomeModal
        isOpen={showWelcomeModal}
        onClose={handleOnboardingClose}
        onStartSetup={handleStartOnboarding}
      />
      <OnboardingWizard
        isOpen={showOnboardingWizard}
        onClose={handleOnboardingClose}
        onComplete={handleOnboardingComplete}
      />

      {/* Analytics Drawer */}
      {/* Scaffold Preview Modal */}
      {showScaffoldPreview && scaffold && (
        <div className="scaffold-modal-overlay" onClick={() => setShowScaffoldPreview(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <ScaffoldPreview
              scaffold={scaffold}
              onUpdate={updateScaffold}
              includeIngredients={includeIngredients}
              onToggleIngredients={toggleIngredients}
              isFetchingIngredients={isFetchingIngredients}
              onExecute={async () => {
                const result = await executeScaffold()
                if (result && result.status === 'success') {
                  setShowScaffoldPreview(false)
                  
                  // Use form_prefill to update the meal form
                  const prefill = result.form_prefill || {}
                  // Convert dish IDs to strings to match checkbox comparison
                  const dishIds = (prefill.dish_ids || result.created?.dishes?.map(d => d.id) || [])
                    .map(id => String(id))
                  
                  setMealForm(f => ({
                    ...f,
                    name: prefill.name || f.name,
                    description: prefill.description || f.description,
                    meal_type: prefill.meal_type || f.meal_type,
                    // Merge new dish IDs with any existing selections
                    dishes: [...new Set([...(f.dishes || []), ...dishIds])]
                  }))
                  
                  // Refresh dishes list so the new dishes appear in the picker
                  loadDishes()
                  
                  // Also refresh ingredients if any were created
                  if (result.summary?.ingredients > 0) {
                    loadIngredients()
                  }
                  
                  // Show success message
                  const newDishes = result.summary?.dishes || 0
                  const newIngredients = result.summary?.ingredients || 0
                  const totalDishes = dishIds.length
                  let message = ''
                  if (newDishes > 0 || newIngredients > 0) {
                    const parts = []
                    if (newDishes > 0) parts.push(`${newDishes} dish${newDishes !== 1 ? 'es' : ''}`)
                    if (newIngredients > 0) parts.push(`${newIngredients} ingredient${newIngredients !== 1 ? 's' : ''}`)
                    message = `Created ${parts.join(' and ')}`
                  }
                  if (totalDishes > newDishes) {
                    message += message ? ` (${totalDishes} total selected)` : `${totalDishes} dish${totalDishes !== 1 ? 'es' : ''} selected`
                  }
                  message += '. Complete the form to create your meal!'
                  
                  setNotice(message)
                  setTimeout(() => setNotice(null), 5000)
                }
              }}
              onCancel={() => {
                setShowScaffoldPreview(false)
                clearScaffold()
              }}
              isExecuting={isScaffoldExecuting}
            />
          </div>
        </div>
      )}

      <AnalyticsDrawer
        open={analyticsDrawer.open}
        onClose={closeAnalyticsDrawer}
        metric={analyticsDrawer.metric}
        title={analyticsDrawer.title}
      />

      {/* Meal Detail Slideout */}
      <MealDetailSlideout
        open={mealSlideoutOpen}
        onClose={() => { setMealSlideoutOpen(false); setSelectedMeal(null) }}
        meal={selectedMeal}
        dishes={dishes}
        onSave={(updatedMeal) => {
          // Update the meal in local state
          setMeals(prev => prev.map(m => m.id === updatedMeal.id ? { ...m, ...updatedMeal } : m))
          loadMeals() // Refresh from server
        }}
        onDelete={(mealId) => {
          // Remove the meal from local state
          setMeals(prev => prev.filter(m => m.id !== mealId))
        }}
      />

      {/* Calendly Verification Meeting Modal */}
      <CalendlyMeetingModal
        isOpen={calendlyModalOpen}
        onClose={() => setCalendlyModalOpen(false)}
        onScheduled={() => {
          setMeetingConfig(prev => ({ ...prev, status: 'scheduled' }))
        }}
        meetingConfig={meetingConfig}
      />
    </div>
  )
}

/**
 * ChefDashboard Wrapper
 * Provides context for the dashboard content.
 */
export default function ChefDashboard() {
  return (
    <ChefContextProvider>
      <SousChefNotificationProvider>
        <ChefDashboardContent />
      </SousChefNotificationProvider>
    </ChefContextProvider>
  )
}
