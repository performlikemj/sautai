/**
 * ChefInsightsDashboard Component
 *
 * Dedicated analytics and metrics view for chefs showing:
 * - Revenue summary cards (today, week, month)
 * - Time-series charts for revenue, orders, clients
 * - Top services breakdown
 * - Quick stats overview
 * - Revenue breakdown by source (meal vs service)
 */

import React, { useEffect, useState, useMemo } from 'react'
import { api } from '../api'
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

const RANGE_OPTIONS = [
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
  { value: '1y', label: '1y' },
]

const METRIC_CONFIG = {
  revenue: {
    label: 'Revenue',
    format: (value) => {
      if (value && typeof value === 'object') {
        return Object.entries(value)
          .filter(([, v]) => v)
          .map(([cur, v]) => formatCurrencyAmount(v, cur))
          .join(' + ') || '$0.00'
      }
      return `$${(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    },
    color: '#10b981',
    gradientId: 'insightsRevenueGradient',
  },
  orders: {
    label: 'Orders',
    format: (value) => (value || 0).toLocaleString(),
    color: '#6366f1',
    gradientId: 'insightsOrdersGradient',
  },
  clients: {
    label: 'New Clients',
    format: (value) => (value || 0).toLocaleString(),
    color: '#f59e0b',
    gradientId: 'insightsClientsGradient',
  },
}

// Detect dark mode
function useIsDarkMode() {
  const [isDark, setIsDark] = useState(() => {
    if (typeof window === 'undefined') return false
    const htmlDark = document.documentElement.classList.contains('dark')
    const bodyDark = document.body.classList.contains('dark')
    const dataDark = document.documentElement.getAttribute('data-theme') === 'dark'
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
    return htmlDark || bodyDark || dataDark || prefersDark
  })

  useEffect(() => {
    const mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)')
    const handleChange = () => {
      const htmlDark = document.documentElement.classList.contains('dark')
      const bodyDark = document.body.classList.contains('dark')
      const dataDark = document.documentElement.getAttribute('data-theme') === 'dark'
      const prefersDark = mediaQuery?.matches
      setIsDark(htmlDark || bodyDark || dataDark || prefersDark)
    }

    mediaQuery?.addEventListener?.('change', handleChange)
    const observer = new MutationObserver(handleChange)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] })

    return () => {
      mediaQuery?.removeEventListener?.('change', handleChange)
      observer.disconnect()
    }
  }, [])

  return isDark
}

// Zero-decimal currencies (no cents subdivision)
const ZERO_DECIMAL_CURRENCIES = new Set([
  'bif','clp','djf','gnf','jpy','kmf','krw','mga','pyg',
  'rwf','ugx','vnd','vuv','xaf','xof','xpf'
])

// Format a single currency amount
const formatCurrencyAmount = (amount, currency = 'usd') => {
  const cur = currency.toLowerCase()
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    maximumFractionDigits: ZERO_DECIMAL_CURRENCIES.has(cur) ? 0 : 2,
  }).format(amount || 0)
}

// Legacy helper for single USD amounts
const formatCurrency = (amount) => {
  // Support new {currency: amount} dict format
  if (amount && typeof amount === 'object') {
    return Object.entries(amount)
      .filter(([, v]) => v)
      .map(([cur, v]) => formatCurrencyAmount(v, cur))
      .join(' + ') || '$0.00'
  }
  return formatCurrencyAmount(amount, 'usd')
}

// Render revenue by currency as stacked lines
const RevenueByCurrency = ({ byCurrency }) => {
  if (!byCurrency || typeof byCurrency !== 'object') {
    return <span>$0.00</span>
  }
  const entries = Object.entries(byCurrency).filter(([, v]) => v)
  if (entries.length === 0) return <span>$0.00</span>
  if (entries.length === 1) {
    const [cur, amt] = entries[0]
    return <span>{formatCurrencyAmount(amt, cur)}</span>
  }
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      {entries.map(([cur, amt]) => (
        <span key={cur}>{formatCurrencyAmount(amt, cur)}</span>
      ))}
    </span>
  )
}

// Format compact number
const formatCompact = (num) => {
  if (num >= 1000) return `${(num / 1000).toFixed(1)}k`
  return num.toString()
}

export default function ChefInsightsDashboard({
  orders = [],
  serviceOrders = [],
  meals = [],
  dishes = [],
  ingredients = [],
  serviceOfferings = [],
}) {
  const [dashboardData, setDashboardData] = useState(null)
  const [timeSeriesData, setTimeSeriesData] = useState({
    revenue: { data: [], total: 0 },
    orders: { data: [], total: 0 },
    clients: { data: [], total: 0 },
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedRange, setSelectedRange] = useState('30d')
  const [selectedMetric, setSelectedMetric] = useState('revenue')

  const isDarkMode = useIsDarkMode()

  // Theme-aware chart colors
  const chartColors = useMemo(() => ({
    grid: isDarkMode ? '#3d3d5c' : '#e5e7eb',
    axis: isDarkMode ? '#3d3d5c' : '#e5e7eb',
    text: isDarkMode ? '#9ca3af' : '#6b7280',
    tooltipBg: isDarkMode ? '#1a1a2e' : '#ffffff',
    tooltipBorder: isDarkMode ? '#3d3d5c' : '#e5e7eb',
  }), [isDarkMode])

  // Fetch data
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        const [dashboardResp, revenueTS, ordersTS, clientsTS] = await Promise.all([
          api.get('/chefs/api/me/dashboard/').catch(() => ({ data: null })),
          api.get('/chefs/api/analytics/time-series/', { params: { metric: 'revenue', range: selectedRange } }).catch(() => ({ data: { data: [], total: 0 } })),
          api.get('/chefs/api/analytics/time-series/', { params: { metric: 'orders', range: selectedRange } }).catch(() => ({ data: { data: [], total: 0 } })),
          api.get('/chefs/api/analytics/time-series/', { params: { metric: 'clients', range: selectedRange } }).catch(() => ({ data: { data: [], total: 0 } })),
        ])

        setDashboardData(dashboardResp.data)
        // Revenue time-series: backend normalises to settlement currency (USD)
        // via Stripe balance transactions, so sum all currencies into one value
        const revenuePoints = (revenueTS.data?.data || []).map(point => {
          const byCurrency = point.by_currency || {}
          const value = Object.values(byCurrency).reduce((sum, v) => sum + (v || 0), 0)
          return { ...point, value, by_currency: byCurrency }
        })
        setTimeSeriesData({
          revenue: { data: revenuePoints, total: revenueTS.data?.total || 0 },
          orders: { data: ordersTS.data?.data || [], total: ordersTS.data?.total || 0 },
          clients: { data: clientsTS.data?.data || [], total: clientsTS.data?.total || 0 },
        })
      } catch (err) {
        console.error('Failed to fetch insights data:', err)
        setError('Unable to load insights. Please try again.')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [selectedRange])

  // Computed order stats from passed data
  const orderStats = useMemo(() => {
    const mealOrders = orders.filter(o => !['cancelled', 'refunded'].includes(String(o.status || '').toLowerCase()))
    const svcOrders = serviceOrders.filter(o => !['cancelled', 'refunded'].includes(String(o.status || '').toLowerCase()))

    return {
      mealCount: mealOrders.length,
      serviceCount: svcOrders.length,
      totalCount: mealOrders.length + svcOrders.length,
    }
  }, [orders, serviceOrders])

  // Order type breakdown for pie chart
  const orderTypeData = useMemo(() => {
    if (orderStats.totalCount === 0) return []
    return [
      { name: 'Meal Shares', value: orderStats.mealCount, color: '#10b981' },
      { name: 'Services', value: orderStats.serviceCount, color: '#6366f1' },
    ].filter(d => d.value > 0)
  }, [orderStats])

  // Current chart data based on selected metric
  const currentChartData = timeSeriesData[selectedMetric]?.data || []
  const currentConfig = METRIC_CONFIG[selectedMetric]

  // Custom tooltip for charts
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const point = payload[0]?.payload
      // For revenue, show by_currency breakdown in tooltip
      const displayValue = selectedMetric === 'revenue' && point?.by_currency
        ? point.by_currency
        : payload[0].value
      return (
        <div style={{
          background: chartColors.tooltipBg,
          border: `1px solid ${chartColors.tooltipBorder}`,
          borderRadius: 8,
          padding: '8px 12px',
          boxShadow: '0 4px 12px rgba(27,58,45,0.15)',
        }}>
          <div style={{ fontSize: '0.8rem', color: chartColors.text, marginBottom: 4 }}>{label}</div>
          <div style={{ fontSize: '1rem', fontWeight: 600, color: currentConfig.color }}>
            {currentConfig.format(displayValue)}
          </div>
        </div>
      )
    }
    return null
  }

  if (loading) {
    return (
      <div className="insights-dashboard">
        <header className="insights-header">
          <h1>Insights</h1>
          <p className="muted">Loading your business analytics...</p>
        </header>
        <div style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          {[1, 2, 3].map(i => (
            <div key={i} className="card" style={{ height: 100, background: 'var(--surface-2)', animation: 'pulse 1.5s infinite' }} />
          ))}
        </div>
        <style>{styles}</style>
      </div>
    )
  }

  if (error) {
    return (
      <div className="insights-dashboard">
        <header className="insights-header">
          <h1>Insights</h1>
          <p className="muted">{error}</p>
        </header>
        <button className="btn btn-primary" onClick={() => setSelectedRange(selectedRange)}>
          Retry
        </button>
        <style>{styles}</style>
      </div>
    )
  }

  const clients = dashboardData?.clients || {}
  const topServices = dashboardData?.top_services || []

  return (
    <div className="insights-dashboard">
      {/* Header */}
      <header className="insights-header">
        <h1>Insights</h1>
        <p className="muted">Your business performance at a glance</p>
      </header>

      {/* Period Summary Cards */}
      <section className="insights-section">
        <div className="insights-overview-header">
          <h2 className="insights-section-title">Revenue Overview</h2>
          <div className="insights-range-selector">
            {RANGE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                className={`range-btn ${selectedRange === opt.value ? 'active' : ''}`}
                onClick={() => setSelectedRange(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <div className="insights-metric-grid">
          {Object.entries(METRIC_CONFIG).map(([key, cfg]) => {
            const total = timeSeriesData[key]?.total || 0
            const isActive = selectedMetric === key
            return (
              <button
                key={key}
                className={`insights-metric-card${isActive ? ' insights-metric-card--active' : ''}`}
                onClick={() => setSelectedMetric(key)}
                style={isActive ? { borderColor: cfg.color } : {}}
              >
                <div className="metric-label">{cfg.label}</div>
                <div className="metric-value" style={{ color: cfg.color }}>
                  {key === 'revenue'
                    ? <RevenueByCurrency byCurrency={typeof total === 'object' ? total : { usd: total }} />
                    : cfg.format(total)
                  }
                </div>
              </button>
            )
          })}
        </div>
      </section>

      {/* Trends Chart */}
      <section className="insights-section">
        <h2 className="insights-section-title">Trends</h2>

        <div className="insights-chart-container">
          {currentChartData.length === 0 ? (
            <div className="insights-empty-chart">
              <span className="muted">No data for this period</span>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={currentChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={currentConfig.gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={currentConfig.color} stopOpacity={isDarkMode ? 0.4 : 0.3} />
                    <stop offset="95%" stopColor={currentConfig.color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: chartColors.text }}
                  tickLine={false}
                  axisLine={{ stroke: chartColors.axis }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 11, fill: chartColors.text }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={selectedMetric === 'revenue' ? (v) => `$${formatCompact(v)}` : formatCompact}
                  width={50}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={currentConfig.color}
                  strokeWidth={2}
                  fill={`url(#${currentConfig.gradientId})`}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {/* Two Column Layout: Order Breakdown + Top Services */}
      <div className="insights-two-col">
        {/* Order Type Breakdown */}
        <section className="insights-section insights-card">
          <h2 className="insights-section-title">Order Breakdown</h2>
          {orderTypeData.length === 0 ? (
            <div className="insights-empty">
              <span className="muted">No orders yet</span>
            </div>
          ) : (
            <div className="insights-pie-container">
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={orderTypeData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={70}
                    paddingAngle={2}
                    dataKey="value"
                  >
                    {orderTypeData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [value, name]}
                    contentStyle={{
                      background: chartColors.tooltipBg,
                      border: `1px solid ${chartColors.tooltipBorder}`,
                      borderRadius: 8,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="insights-pie-legend">
                {orderTypeData.map((entry, index) => (
                  <div key={index} className="legend-item">
                    <span className="legend-dot" style={{ background: entry.color }} />
                    <span className="legend-label">{entry.name}</span>
                    <span className="legend-value">{entry.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Top Services */}
        <section className="insights-section insights-card">
          <h2 className="insights-section-title">Top Services</h2>
          {topServices.length === 0 ? (
            <div className="insights-empty">
              <span className="muted">No service orders yet</span>
            </div>
          ) : (
            <div className="insights-top-list">
              {topServices.slice(0, 5).map((svc, idx) => (
                <div key={idx} className="top-list-item">
                  <span className="top-list-rank">{idx + 1}</span>
                  <span className="top-list-name">{svc.name || svc.service_name || 'Service'}</span>
                  <span className="top-list-value">{svc.order_count || svc.count || 0} orders</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Client Stats */}
      <section className="insights-section">
        <h2 className="insights-section-title">Client Overview</h2>
        <div className="insights-metric-grid">
          <div className="insights-stat-card">
            <div className="stat-value">{clients.total || 0}</div>
            <div className="stat-label">Total Clients</div>
          </div>
          <div className="insights-stat-card">
            <div className="stat-value">{clients.active || 0}</div>
            <div className="stat-label">Active Clients</div>
          </div>
          <div className="insights-stat-card">
            <div className="stat-value" style={{ color: 'var(--success)' }}>+{clients.new_this_month || 0}</div>
            <div className="stat-label">New This Month</div>
          </div>
        </div>
      </section>

      {/* Quick Stats */}
      <section className="insights-section">
        <h2 className="insights-section-title">Menu at a Glance</h2>
        <div className="insights-quick-stats">
          <div className="quick-stat">
            <div className="quick-stat-value">{meals.length}</div>
            <div className="quick-stat-label">Meals</div>
          </div>
          <div className="quick-stat">
            <div className="quick-stat-value">{dishes.length}</div>
            <div className="quick-stat-label">Dishes</div>
          </div>
          <div className="quick-stat">
            <div className="quick-stat-value">{ingredients.length}</div>
            <div className="quick-stat-label">Ingredients</div>
          </div>
          <div className="quick-stat">
            <div className="quick-stat-value">{serviceOfferings.length}</div>
            <div className="quick-stat-label">Service Offerings</div>
          </div>
        </div>
      </section>

      <style>{styles}</style>
    </div>
  )
}

const styles = `
  .insights-dashboard {
    max-width: 100%;
    color: var(--text);
  }

  .insights-header {
    margin-bottom: 1.5rem;
  }

  .insights-header h1 {
    margin: 0 0 0.25rem 0;
    font-size: 1.75rem;
    font-weight: 700;
  }

  .insights-header .muted {
    margin: 0;
    font-size: 0.95rem;
  }

  .insights-section {
    margin-bottom: 1.5rem;
  }

  .insights-section-title {
    margin: 0 0 0.75rem 0;
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: var(--muted);
  }

  .insights-overview-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }

  .insights-overview-header .insights-section-title {
    margin-bottom: 0;
  }

  .insights-metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.75rem;
  }

  .insights-metric-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1rem;
    text-align: left;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .insights-metric-card:hover {
    border-color: var(--primary);
    background: var(--surface-2);
  }

  .insights-metric-card--active {
    background: var(--surface-2);
  }

  .metric-label {
    font-size: 0.85rem;
    color: var(--muted);
    margin-bottom: 0.25rem;
  }

  .metric-value {
    font-size: 1.5rem;
    font-weight: 700;
  }

  .insights-range-selector {
    display: flex;
    gap: 0.25rem;
    background: var(--surface-2);
    padding: 0.25rem;
    border-radius: 8px;
  }

  .range-btn {
    padding: 0.35rem 0.6rem;
    font-size: 0.8rem;
    font-weight: 500;
    border: 1px solid transparent;
    background: transparent;
    border-radius: 6px;
    cursor: pointer;
    color: var(--muted);
    transition: all 0.15s ease;
  }

  .range-btn:hover {
    color: var(--text);
  }

  .range-btn.active {
    background: var(--surface);
    color: var(--text);
    border-color: var(--border);
  }

  .insights-chart-container {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1rem;
  }

  .insights-empty-chart {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 280px;
  }

  .insights-two-col {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  .insights-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1rem;
    margin-bottom: 0;
  }

  .insights-card .insights-section-title {
    margin-bottom: 0.5rem;
  }

  .insights-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
  }

  .insights-pie-container {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .insights-pie-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    justify-content: center;
    margin-top: 0.5rem;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.85rem;
  }

  .legend-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .legend-label {
    color: var(--muted);
  }

  .legend-value {
    font-weight: 600;
    color: var(--text);
  }

  .insights-top-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .top-list-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border);
  }

  .top-list-item:last-child {
    border-bottom: none;
  }

  .top-list-rank {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--surface-2);
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--muted);
  }

  .top-list-name {
    flex: 1;
    font-weight: 500;
    font-size: 0.9rem;
  }

  .top-list-value {
    font-size: 0.85rem;
    color: var(--muted);
  }

  .insights-stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1rem;
    text-align: center;
  }

  .stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text);
  }

  .stat-label {
    font-size: 0.85rem;
    color: var(--muted);
    margin-top: 0.25rem;
  }

  .insights-quick-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
    gap: 0.75rem;
  }

  .quick-stat {
    background: var(--surface-2);
    border-radius: 10px;
    padding: 1rem;
    text-align: center;
  }

  .quick-stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--primary-700);
  }

  .quick-stat-label {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 0.25rem;
  }

  @media (max-width: 640px) {
    .insights-metric-grid {
      grid-template-columns: 1fr;
    }

    .insights-two-col {
      grid-template-columns: 1fr;
    }
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
`
