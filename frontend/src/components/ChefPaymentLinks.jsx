import React, { useState, useEffect, useCallback } from 'react'
import {
  getPaymentLinks,
  getPaymentLinkStats,
  createPaymentLink,
  sendPaymentLink,
  cancelPaymentLink,
  sendEmailVerification,
  formatAmount,
  getStatusColor,
  getStatusLabel,
  PAYMENT_LINK_STATUSES,
} from '../api/paymentLinksClient.js'
import { api } from '../api'

const API_BASE = '/chefs/api/me'

// Media query helper
const useMediaQuery = (query) => {
  const [matches, setMatches] = useState(false)
  useEffect(() => {
    const media = window.matchMedia(query)
    setMatches(media.matches)
    const listener = () => setMatches(media.matches)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [query])
  return matches
}

export default function ChefPaymentLinks() {
  const [paymentLinks, setPaymentLinks] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  
  // Create modal
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [createForm, setCreateForm] = useState({
    amount: '',
    description: '',
    lead_id: '',
    customer_id: '',
    currency: 'usd',
    expires_days: 30,
    internal_notes: '',
  })
  const [clients, setClients] = useState([])
  const [creating, setCreating] = useState(false)
  
  // Filters
  const [statusFilter, setStatusFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  
  // Actions
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  
  const isDesktop = useMediaQuery('(min-width: 900px)')

  const loadPaymentLinks = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (statusFilter) params.status = statusFilter
      if (searchQuery) params.search = searchQuery
      
      const response = await getPaymentLinks(params)
      setPaymentLinks(response?.results || response || [])
    } catch (err) {
      console.error('Failed to load payment links:', err)
      setPaymentLinks([])
    } finally {
      setLoading(false)
    }
  }, [statusFilter, searchQuery])

  const loadStats = useCallback(async () => {
    try {
      const response = await getPaymentLinkStats()
      setStats(response)
    } catch (err) {
      console.error('Failed to load stats:', err)
    }
  }, [])

  const loadClients = useCallback(async () => {
    try {
      const response = await api.get(`${API_BASE}/all-clients/`, {
        skipUserId: true,
        withCredentials: true
      })
      setClients(response.data?.results || [])
    } catch (err) {
      console.error('Failed to load clients:', err)
      setClients([])
    }
  }, [])

  useEffect(() => {
    loadPaymentLinks()
    loadStats()
  }, [loadPaymentLinks, loadStats])

  // Pre-populate create form with chef's default currency when stats load
  useEffect(() => {
    if (stats?.default_currency) {
      setCreateForm(prev => ({ ...prev, currency: stats.default_currency }))
    }
  }, [stats?.default_currency])

  useEffect(() => {
    const timeout = setTimeout(() => loadPaymentLinks(), 300)
    return () => clearTimeout(timeout)
  }, [searchQuery, loadPaymentLinks])

  // Zero-decimal currencies don't use cents
  const ZERO_DECIMAL_CURRENCIES = ['jpy', 'krw', 'vnd', 'bif', 'clp', 'djf', 'gnf', 'kmf', 'mga', 'pyg', 'rwf', 'ugx', 'vuv', 'xaf', 'xof', 'xpf']
  
  const handleCreate = async (e) => {
    e.preventDefault()
    if (!createForm.amount || !createForm.description) {
      alert('Please enter amount and description')
      return
    }
    
    const currency = (createForm.currency || 'usd').toLowerCase()
    const isZeroDecimal = ZERO_DECIMAL_CURRENCIES.includes(currency)
    const amountCents = isZeroDecimal 
      ? Math.round(parseFloat(createForm.amount))
      : Math.round(parseFloat(createForm.amount) * 100)
    
    const minAmount = isZeroDecimal ? 1 : 50
    if (isNaN(amountCents) || amountCents < minAmount) {
      const minDisplay = formatAmount(minAmount, currency)
      alert(`Minimum amount is ${minDisplay}`)
      return
    }
    
    if (!createForm.lead_id && !createForm.customer_id) {
      alert('Please select a client')
      return
    }
    
    setCreating(true)
    try {
      const data = {
        amount_cents: amountCents,
        currency: currency,
        description: createForm.description,
        expires_days: createForm.expires_days,
        internal_notes: createForm.internal_notes,
      }
      
      if (createForm.lead_id) {
        data.lead_id = parseInt(createForm.lead_id)
      } else if (createForm.customer_id) {
        data.customer_id = parseInt(createForm.customer_id)
      }
      
      await createPaymentLink(data)
      setShowCreateModal(false)
      setCreateForm({
        amount: '',
        description: '',
        lead_id: '',
        customer_id: '',
        currency: stats?.default_currency || 'usd',
        expires_days: 30,
        internal_notes: '',
      })
      await loadPaymentLinks()
      await loadStats()
    } catch (err) {
      console.error('Failed to create payment link:', err)
      alert(err.response?.data?.error || 'Failed to create payment link')
    } finally {
      setCreating(false)
    }
  }

  const handleSend = async (link) => {
    if (!link.recipient?.email) {
      alert('No email address available for this client')
      return
    }
    
    if (link.recipient?.type === 'lead' && !link.recipient?.email_verified) {
      const confirmSendVerification = window.confirm(
        'This client\'s email is not verified. Would you like to send a verification email first?'
      )
      if (confirmSendVerification) {
        await handleSendVerification(link.recipient.id)
        return
      }
      return
    }
    
    setSending(true)
    try {
      await sendPaymentLink(link.id)
      await loadPaymentLinks()
      alert(`Payment link sent to ${link.recipient.email}`)
    } catch (err) {
      console.error('Failed to send payment link:', err)
      alert(err.response?.data?.error || 'Failed to send payment link')
    } finally {
      setSending(false)
    }
  }

  const handleCancel = async (link) => {
    if (!window.confirm('Are you sure you want to cancel this payment link?')) {
      return
    }
    
    setCancelling(true)
    try {
      await cancelPaymentLink(link.id)
      await loadPaymentLinks()
      await loadStats()
      setSelected(null)
    } catch (err) {
      console.error('Failed to cancel payment link:', err)
      alert(err.response?.data?.error || 'Failed to cancel payment link')
    } finally {
      setCancelling(false)
    }
  }

  const handleSendVerification = async (leadId) => {
    try {
      await sendEmailVerification(leadId)
      alert('Verification email sent!')
    } catch (err) {
      console.error('Failed to send verification:', err)
      alert(err.response?.data?.error || 'Failed to send verification email')
    }
  }

  const handleCopyLink = (url) => {
    navigator.clipboard.writeText(url)
    alert('Payment link copied to clipboard!')
  }

  const openCreateModal = async () => {
    await loadClients()
    setShowCreateModal(true)
  }

  // Separate clients by type for the dropdown
  const leadClients = clients.filter(c => c.source_type === 'contact')
  const platformClients = clients.filter(c => c.source_type === 'platform')

  // Stats summary cards
  const StatCard = ({ label, value, color }) => (
    <div style={{
      backgroundColor: 'var(--surface, #fff)',
      padding: '16px 20px',
      borderRadius: '8px',
      boxShadow: 'var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.1))',
      textAlign: 'center',
      minWidth: '120px',
      border: '1px solid var(--border, #eee)'
    }}>
      <div style={{ fontSize: '24px', fontWeight: 'bold', color }}>{value}</div>
      <div style={{ fontSize: '13px', color: 'var(--muted, #666)', marginTop: '4px' }}>{label}</div>
    </div>
  )

  // Payment link row
  const PaymentLinkRow = ({ link }) => {
    const isExpired = link.is_expired
    const statusColor = getStatusColor(link.status)
    
    return (
      <div
        onClick={() => setSelected(link)}
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '12px 16px',
          borderBottom: '1px solid var(--border, #eee)',
          cursor: 'pointer',
          backgroundColor: selected?.id === link.id ? 'color-mix(in oklab, var(--surface) 85%, var(--primary) 15%)' : 'var(--surface, #fff)',
          transition: 'background-color 0.15s'
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 500, marginBottom: '4px', color: 'var(--text, #333)' }}>
            {link.recipient?.name || 'Unknown'}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted, #666)', marginBottom: '4px' }}>
            {link.description.length > 50 ? `${link.description.substring(0, 50)}...` : link.description}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--muted, #999)' }}>
            Created {new Date(link.created_at).toLocaleDateString()}
          </div>
        </div>
        <div style={{ textAlign: 'right', marginLeft: '16px' }}>
          <div style={{ fontWeight: 600, fontSize: '16px', color: 'var(--text, #333)' }}>
            {link.amount_display}
          </div>
          <div style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: '12px',
            backgroundColor: `${statusColor}20`,
            color: statusColor,
            fontSize: '11px',
            fontWeight: 500,
            marginTop: '4px'
          }}>
            {getStatusLabel(link.status)}
          </div>
        </div>
      </div>
    )
  }

  // Detail panel
  const DetailPanel = ({ link }) => {
    if (!link) {
      return (
        <div style={{
          padding: '40px',
          textAlign: 'center',
          color: 'var(--muted, #999)'
        }}>
          Select a payment link to view details
        </div>
      )
    }

    const canSend = ['draft', 'pending'].includes(link.status) && !link.is_expired
    const canCancel = ['draft', 'pending'].includes(link.status)
    const statusColor = getStatusColor(link.status)

    return (
      <div style={{ padding: '20px' }}>
        {/* Header */}
        <div style={{ marginBottom: '24px' }}>
          <div style={{
            display: 'inline-block',
            padding: '4px 12px',
            borderRadius: '16px',
            backgroundColor: `${statusColor}20`,
            color: statusColor,
            fontSize: '13px',
            fontWeight: 500,
            marginBottom: '12px'
          }}>
            {getStatusLabel(link.status)}
          </div>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '24px', color: 'var(--text, #333)' }}>{link.amount_display}</h3>
          <p style={{ margin: 0, color: 'var(--muted, #666)' }}>{link.description}</p>
        </div>

        {/* Recipient */}
        <div style={{
          backgroundColor: 'var(--surface-2, #f8f9fa)',
          padding: '16px',
          borderRadius: '8px',
          marginBottom: '20px',
          border: '1px solid var(--border, #eee)'
        }}>
          <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '4px' }}>Recipient</div>
          <div style={{ fontWeight: 500, color: 'var(--text, #333)' }}>{link.recipient?.name || 'Unknown'}</div>
          {link.recipient?.email && (
            <div style={{ fontSize: '14px', color: 'var(--muted, #666)', marginTop: '4px' }}>
              {link.recipient.email}
              {link.recipient.type === 'lead' && (
                <span style={{
                  marginLeft: '8px',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  backgroundColor: link.recipient.email_verified ? 'var(--success-bg)' : 'var(--warning-bg)',
                  color: link.recipient.email_verified ? 'var(--success)' : 'var(--warning)'
                }}>
                  {link.recipient.email_verified ? 'Verified' : 'Not Verified'}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Payment URL */}
        {link.payment_url && (
          <div style={{ marginBottom: '20px' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '8px' }}>Payment Link</div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              backgroundColor: 'var(--surface-2, #f8f9fa)',
              padding: '12px',
              borderRadius: '8px',
              fontSize: '13px',
              wordBreak: 'break-all',
              border: '1px solid var(--border, #eee)'
            }}>
              <span style={{ flex: 1, color: 'var(--link, #007bff)' }}>{link.payment_url}</span>
              <button
                onClick={() => handleCopyLink(link.payment_url)}
                style={{
                  padding: '6px 12px',
                  border: '1px solid var(--border, #ddd)',
                  borderRadius: '4px',
                  backgroundColor: 'var(--surface, #fff)',
                  color: 'var(--text, #333)',
                  cursor: 'pointer',
                  fontSize: '12px',
                  whiteSpace: 'nowrap'
                }}
              >
                Copy
              </button>
            </div>
          </div>
        )}

        {/* Dates */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '16px',
          marginBottom: '20px'
        }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '4px' }}>Created</div>
            <div style={{ fontSize: '14px', color: 'var(--text, #333)' }}>
              {new Date(link.created_at).toLocaleDateString()}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '4px' }}>Expires</div>
            <div style={{
              fontSize: '14px',
              color: link.is_expired ? 'var(--danger)' : 'var(--text, #333)'
            }}>
              {new Date(link.expires_at).toLocaleDateString()}
              {link.is_expired && ' (Expired)'}
            </div>
          </div>
          {link.email_sent_at && (
            <div>
              <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '4px' }}>Last Sent</div>
              <div style={{ fontSize: '14px', color: 'var(--text, #333)' }}>
                {new Date(link.email_sent_at).toLocaleDateString()}
                {link.email_send_count > 1 && ` (${link.email_send_count} times)`}
              </div>
            </div>
          )}
          {link.paid_at && (
            <div>
              <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '4px' }}>Paid</div>
              <div style={{ fontSize: '14px', color: 'var(--success)' }}>
                {new Date(link.paid_at).toLocaleDateString()}
              </div>
            </div>
          )}
        </div>

        {/* Internal Notes */}
        {link.internal_notes && (
          <div style={{ marginBottom: '20px' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted, #666)', marginBottom: '8px' }}>Internal Notes</div>
            <div style={{
              backgroundColor: 'var(--warning-bg)',
              padding: '12px',
              borderRadius: '8px',
              fontSize: '14px',
              borderLeft: '3px solid var(--warning)',
              color: 'var(--text, #333)'
            }}>
              {link.internal_notes}
            </div>
          </div>
        )}

        {/* Actions */}
        <div style={{
          display: 'flex',
          gap: '12px',
          marginTop: '24px',
          paddingTop: '20px',
          borderTop: '1px solid var(--border, #eee)'
        }}>
          {canSend && (
            <button
              onClick={() => handleSend(link)}
              disabled={sending}
              style={{
                flex: 1,
                padding: '12px',
                backgroundColor: 'var(--primary, #7C9070)',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: sending ? 'not-allowed' : 'pointer',
                fontWeight: 500,
                opacity: sending ? 0.7 : 1
              }}
            >
              {sending ? 'Sending...' : link.email_send_count > 0 ? 'Resend Email' : 'Send Email'}
            </button>
          )}
          {canCancel && (
            <button
              onClick={() => handleCancel(link)}
              disabled={cancelling}
              style={{
                padding: '12px 20px',
                backgroundColor: 'var(--surface, #fff)',
                color: 'var(--danger)',
                border: '1px solid var(--danger)',
                borderRadius: '6px',
                cursor: cancelling ? 'not-allowed' : 'pointer',
                fontWeight: 500,
                opacity: cancelling ? 0.7 : 1
              }}
            >
              {cancelling ? 'Cancelling...' : 'Cancel'}
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: isDesktop ? '24px' : '16px' }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '24px'
      }}>
        <h2 style={{ margin: 0, color: 'var(--text, #333)' }}>Payment Links</h2>
        <button
          onClick={openCreateModal}
          style={{
            padding: '10px 20px',
            backgroundColor: 'var(--primary, #7C9070)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <span style={{ fontSize: '18px' }}>+</span>
          Create Payment Link
        </button>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div style={{
          display: 'flex',
          gap: '16px',
          marginBottom: '24px',
          overflowX: 'auto',
          paddingBottom: '8px'
        }}>
          <StatCard label="Total Links" value={stats.total_count || 0} color="var(--text, #333)" />
          <StatCard label="Pending" value={stats.pending_count || 0} color="var(--warning)" />
          <StatCard label="Paid" value={stats.paid_count || 0} color="var(--success)" />
          <StatCard
            label="Pending Amount"
            value={formatAmount(stats.total_pending_amount_cents || 0, stats.currency || 'USD')}
            color="var(--link, #007bff)"
          />
          <StatCard
            label="Collected"
            value={formatAmount(stats.total_paid_amount_cents || 0, stats.currency || 'USD')}
            color="var(--success)"
          />
        </div>
      )}

      {/* Filters */}
      <div style={{
        display: 'flex',
        gap: '12px',
        marginBottom: '20px',
        flexWrap: 'wrap'
      }}>
        <input
          type="text"
          placeholder="Search..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            padding: '8px 12px',
            border: '1px solid var(--border, #ddd)',
            borderRadius: '6px',
            fontSize: '14px',
            minWidth: '200px',
            backgroundColor: 'var(--surface, #fff)',
            color: 'var(--text, #333)'
          }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{
            padding: '8px 12px',
            border: '1px solid var(--border, #ddd)',
            borderRadius: '6px',
            fontSize: '14px',
            backgroundColor: 'var(--surface, #fff)',
            color: 'var(--text, #333)'
          }}
        >
          {PAYMENT_LINK_STATUSES.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>

      {/* Main Content */}
      <div style={{
        display: isDesktop ? 'grid' : 'block',
        gridTemplateColumns: '1fr 400px',
        gap: '24px',
        backgroundColor: 'var(--surface, #fff)',
        borderRadius: '12px',
        boxShadow: 'var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.1))',
        overflow: 'hidden',
        border: '1px solid var(--border, #eee)'
      }}>
        {/* List */}
        <div style={{
          borderRight: isDesktop ? '1px solid var(--border, #eee)' : 'none',
          maxHeight: isDesktop ? '600px' : 'auto',
          overflowY: 'auto'
        }}>
          {loading ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--muted, #999)' }}>
              Loading...
            </div>
          ) : paymentLinks.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--muted, #999)' }}>
              <p>No payment links found</p>
              <p style={{ fontSize: '14px' }}>Create your first payment link to get started</p>
            </div>
          ) : (
            paymentLinks.map(link => (
              <PaymentLinkRow key={link.id} link={link} />
            ))
          )}
        </div>

        {/* Detail Panel */}
        {isDesktop && (
          <DetailPanel link={selected} />
        )}
      </div>

      {/* Mobile Detail Modal */}
      {!isDesktop && selected && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'flex-end',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'var(--surface, #fff)',
            borderTopLeftRadius: '16px',
            borderTopRightRadius: '16px',
            width: '100%',
            maxHeight: '80dvh',
            overflow: 'auto',
            WebkitOverflowScrolling: 'touch',
            paddingBottom: 'max(16px, env(safe-area-inset-bottom))',
            border: '1px solid var(--border, #eee)'
          }}>
            <div style={{
              padding: '16px',
              borderBottom: '1px solid var(--border, #eee)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <h3 style={{ margin: 0, color: 'var(--text, #333)' }}>Payment Link Details</h3>
              <button
                onClick={() => setSelected(null)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '24px',
                  cursor: 'pointer',
                  color: 'var(--muted, #666)'
                }}
              >
                ×
              </button>
            </div>
            <DetailPanel link={selected} />
          </div>
        </div>
      )}

      {/* Create Modal - inline to prevent remounting on state changes */}
      {showCreateModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'var(--surface, #fff)',
            borderRadius: '12px',
            width: '90%',
            maxWidth: '500px',
            maxHeight: '90dvh',
            overflow: 'auto',
            WebkitOverflowScrolling: 'touch',
            border: '1px solid var(--border, #eee)'
          }}>
            <div style={{
              padding: '20px',
              borderBottom: '1px solid var(--border, #eee)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <h3 style={{ margin: 0, color: 'var(--text, #333)' }}>Create Payment Link</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '24px',
                  cursor: 'pointer',
                  color: 'var(--muted, #666)'
                }}
              >
                ×
              </button>
            </div>

            <form onSubmit={handleCreate} style={{ padding: '20px' }}>
              {/* Amount and Currency */}
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '6px', fontWeight: 500, color: 'var(--text, #333)' }}>
                  Amount *
                </label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <select
                    value={createForm.currency}
                    onChange={(e) => setCreateForm({ ...createForm, currency: e.target.value })}
                    style={{
                      padding: '10px 12px',
                      border: '1px solid var(--border, #ddd)',
                      borderRadius: '6px',
                      fontSize: '14px',
                      backgroundColor: 'var(--surface, #fff)',
                      color: 'var(--text, #333)',
                      minWidth: '90px'
                    }}
                  >
                    <option value="usd">USD $</option>
                    <option value="eur">EUR €</option>
                    <option value="gbp">GBP £</option>
                    <option value="jpy">JPY ¥</option>
                    <option value="cad">CAD $</option>
                    <option value="aud">AUD $</option>
                    <option value="chf">CHF</option>
                    <option value="cny">CNY ¥</option>
                    <option value="inr">INR ₹</option>
                    <option value="mxn">MXN $</option>
                    <option value="brl">BRL R$</option>
                    <option value="krw">KRW ₩</option>
                    <option value="sgd">SGD $</option>
                    <option value="hkd">HKD $</option>
                    <option value="nzd">NZD $</option>
                    <option value="sek">SEK kr</option>
                    <option value="nok">NOK kr</option>
                    <option value="dkk">DKK kr</option>
                    <option value="pln">PLN zł</option>
                    <option value="thb">THB ฿</option>
                  </select>
                  <input
                    type="number"
                    step={ZERO_DECIMAL_CURRENCIES.includes(createForm.currency) ? '1' : '0.01'}
                    min={ZERO_DECIMAL_CURRENCIES.includes(createForm.currency) ? '1' : '0.50'}
                    value={createForm.amount}
                    onChange={(e) => setCreateForm({ ...createForm, amount: e.target.value })}
                    placeholder={ZERO_DECIMAL_CURRENCIES.includes(createForm.currency) ? '100' : '0.00'}
                    required
                    style={{
                      flex: 1,
                      padding: '10px 12px',
                      border: '1px solid var(--border, #ddd)',
                      borderRadius: '6px',
                      fontSize: '16px',
                      backgroundColor: 'var(--surface, #fff)',
                      color: 'var(--text, #333)'
                    }}
                  />
                </div>
              </div>

              {/* Description */}
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '6px', fontWeight: 500, color: 'var(--text, #333)' }}>
                  Description *
                </label>
                <input
                  type="text"
                  value={createForm.description}
                  onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                  placeholder="e.g., Weekly meal prep service"
                  required
                  maxLength={500}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    border: '1px solid var(--border, #ddd)',
                    borderRadius: '6px',
                    fontSize: '14px',
                    backgroundColor: 'var(--surface, #fff)',
                    color: 'var(--text, #333)'
                  }}
                />
              </div>

              {/* Client Selection */}
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '6px', fontWeight: 500, color: 'var(--text, #333)' }}>
                  Select Client *
                </label>
                <select
                  value={createForm.lead_id ? `lead_${createForm.lead_id}` : createForm.customer_id ? `customer_${createForm.customer_id}` : ''}
                  onChange={(e) => {
                    const [type, id] = e.target.value.split('_')
                    if (type === 'lead') {
                      setCreateForm({ ...createForm, lead_id: id, customer_id: '' })
                    } else if (type === 'customer') {
                      setCreateForm({ ...createForm, customer_id: id, lead_id: '' })
                    } else {
                      setCreateForm({ ...createForm, lead_id: '', customer_id: '' })
                    }
                  }}
                  required
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    border: '1px solid var(--border, #ddd)',
                    borderRadius: '6px',
                    fontSize: '14px',
                    backgroundColor: 'var(--surface, #fff)',
                    color: 'var(--text, #333)'
                  }}
                >
                  <option value="">Select a client...</option>
                  {leadClients.length > 0 && (
                    <optgroup label="Manual Contacts">
                      {leadClients.map(client => (
                        <option key={`lead_${client.lead_id}`} value={`lead_${client.lead_id}`}>
                          {client.name} {client.email ? `(${client.email})` : '(No email)'}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {platformClients.length > 0 && (
                    <optgroup label="Platform Users">
                      {platformClients.map(client => (
                        <option key={`customer_${client.customer_id}`} value={`customer_${client.customer_id}`}>
                          {client.name} ({client.email})
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>

              {/* Expiration */}
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '6px', fontWeight: 500, color: 'var(--text, #333)' }}>
                  Expires In (days)
                </label>
                <select
                  value={createForm.expires_days}
                  onChange={(e) => setCreateForm({ ...createForm, expires_days: parseInt(e.target.value) })}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    border: '1px solid var(--border, #ddd)',
                    borderRadius: '6px',
                    fontSize: '14px',
                    backgroundColor: 'var(--surface, #fff)',
                    color: 'var(--text, #333)'
                  }}
                >
                  <option value={7}>7 days</option>
                  <option value={14}>14 days</option>
                  <option value={30}>30 days</option>
                  <option value={60}>60 days</option>
                  <option value={90}>90 days</option>
                </select>
              </div>

              {/* Internal Notes */}
              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', marginBottom: '6px', fontWeight: 500, color: 'var(--text, #333)' }}>
                  Internal Notes (optional)
                </label>
                <textarea
                  value={createForm.internal_notes}
                  onChange={(e) => setCreateForm({ ...createForm, internal_notes: e.target.value })}
                  placeholder="Notes for your reference (not shown to client)"
                  rows={3}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    border: '1px solid var(--border, #ddd)',
                    borderRadius: '6px',
                    fontSize: '14px',
                    resize: 'vertical',
                    backgroundColor: 'var(--surface, #fff)',
                    color: 'var(--text, #333)'
                  }}
                />
              </div>

              {/* Submit */}
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    backgroundColor: 'var(--surface-2, #f8f9fa)',
                    color: 'var(--text, #333)',
                    border: '1px solid var(--border, #ddd)',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontWeight: 500
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  style={{
                    flex: 1,
                    padding: '12px',
                    backgroundColor: 'var(--primary, #7C9070)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: creating ? 'not-allowed' : 'pointer',
                    fontWeight: 500,
                    opacity: creating ? 0.7 : 1
                  }}
                >
                  {creating ? 'Creating...' : 'Create Payment Link'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

