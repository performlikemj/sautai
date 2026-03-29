import React, { useEffect, useState, useMemo } from 'react'
import { api } from '../api'
import { 
  AreaChart, 
  Area, 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from 'recharts'
import './AnalyticsDrawer.css'

const RANGE_OPTIONS = [
  { value: '7d', label: '7 Days' },
  { value: '30d', label: '30 Days' },
  { value: '90d', label: '90 Days' },
  { value: '1y', label: '1 Year' },
]

// Zero-decimal currencies
const ZERO_DECIMAL_CURRENCIES = new Set([
  'bif','clp','djf','gnf','jpy','kmf','krw','mga','pyg',
  'rwf','ugx','vnd','vuv','xaf','xof','xpf'
])

const formatCurrencyAmount = (amount, currency = 'usd') => {
  const cur = currency.toLowerCase()
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    maximumFractionDigits: ZERO_DECIMAL_CURRENCIES.has(cur) ? 0 : 2,
  }).format(amount || 0)
}

// Format a by_currency dict or a plain number
const formatByCurrency = (value) => {
  if (value && typeof value === 'object') {
    const parts = Object.entries(value)
      .filter(([, v]) => v)
      .map(([cur, v]) => formatCurrencyAmount(v, cur))
    return parts.length ? parts.join(' + ') : '$0.00'
  }
  return `$${Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const METRIC_CONFIG = {
  revenue: {
    label: 'Revenue',
    format: formatByCurrency,
    chartType: 'area',
    color: '#10b981', // emerald
    gradientId: 'revenueGradient',
  },
  orders: {
    label: 'Orders',
    format: (value) => value.toLocaleString(),
    chartType: 'line',
    color: '#6366f1', // indigo
    gradientId: 'ordersGradient',
  },
  clients: {
    label: 'New Clients',
    format: (value) => value.toLocaleString(),
    chartType: 'line',
    color: '#f59e0b', // amber
    gradientId: 'clientsGradient',
  },
}

// Detect dark mode
function useIsDarkMode() {
  const [isDark, setIsDark] = useState(() => {
    if (typeof window === 'undefined') return false
    // Check various dark mode indicators
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
    
    // Also watch for class changes on html/body
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

export default function AnalyticsDrawer({ open, onClose, metric, title }) {
  const [range, setRange] = useState('30d')
  const [data, setData] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const isDarkMode = useIsDarkMode()

  const config = METRIC_CONFIG[metric] || METRIC_CONFIG.revenue
  
  // Theme-aware chart colors
  const chartColors = useMemo(() => ({
    grid: isDarkMode ? '#3d3d5c' : '#e5e7eb',
    axis: isDarkMode ? '#3d3d5c' : '#e5e7eb',
    text: isDarkMode ? '#9ca3af' : '#6b7280',
    tooltipBg: isDarkMode ? '#1a1a2e' : '#ffffff',
    tooltipBorder: isDarkMode ? '#3d3d5c' : '#e5e7eb',
  }), [isDarkMode])

  useEffect(() => {
    if (!open || !metric) return

    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        const resp = await api.get('/chefs/api/analytics/time-series/', {
          params: { metric, range }
        })
        const payload = resp?.data
        let rawData = payload?.data || []
        // For revenue, normalize by_currency into a chart-friendly value
        if (metric === 'revenue') {
          rawData = rawData.map(point => {
            const byCurrency = point.by_currency || {}
            // Use USD value for the chart line (primary currency for charting)
            const usdValue = byCurrency.usd || 0
            return { ...point, value: usdValue, by_currency: byCurrency }
          })
        }
        setData(rawData)
        setTotal(payload?.total || 0)
      } catch (err) {
        console.error('Failed to fetch analytics:', err)
        setError('Unable to load analytics data.')
        setData([])
        setTotal(0)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [open, metric, range])

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [open, onClose])

  // Prevent body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const point = payload[0]?.payload
      const displayValue = metric === 'revenue' && point?.by_currency
        ? point.by_currency
        : point?.value
      return (
        <div className="analytics-tooltip">
          <div className="tooltip-label">{label}</div>
          <div className="tooltip-value" style={{ color: config.color }}>
            {config.format(displayValue)}
          </div>
        </div>
      )
    }
    return null
  }

  const renderChart = () => {
    if (loading) {
      return (
        <div className="chart-loading">
          <div className="chart-skeleton" />
        </div>
      )
    }

    if (error) {
      return (
        <div className="chart-error">
          <i className="fa-solid fa-exclamation-triangle" />
          <span>{error}</span>
          <button className="btn btn-outline btn-sm" onClick={() => setRange(range)}>
            Retry
          </button>
        </div>
      )
    }

    if (data.length === 0) {
      return (
        <div className="chart-empty">
          <i className="fa-solid fa-chart-line" />
          <span>No data for this period</span>
        </div>
      )
    }

    const ChartComponent = config.chartType === 'area' ? AreaChart : LineChart

    return (
      <ResponsiveContainer width="100%" height={250}>
        <ChartComponent data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={config.gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={config.color} stopOpacity={isDarkMode ? 0.4 : 0.3} />
              <stop offset="95%" stopColor={config.color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
          <XAxis 
            dataKey="label" 
            tick={{ fontSize: 12, fill: chartColors.text }}
            tickLine={false}
            axisLine={{ stroke: chartColors.axis }}
            interval="preserveStartEnd"
          />
          <YAxis 
            tick={{ fontSize: 12, fill: chartColors.text }}
            tickLine={false}
            axisLine={false}
            tickFormatter={config.chartType === 'area' ? (v) => `$${v}` : undefined}
          />
          <Tooltip content={<CustomTooltip />} />
          {config.chartType === 'area' ? (
            <Area
              type="monotone"
              dataKey="value"
              stroke={config.color}
              strokeWidth={2}
              fill={`url(#${config.gradientId})`}
            />
          ) : (
            <Line
              type="monotone"
              dataKey="value"
              stroke={config.color}
              strokeWidth={2}
              dot={{ fill: config.color, strokeWidth: 0, r: 3 }}
              activeDot={{ r: 5, strokeWidth: 0 }}
            />
          )}
        </ChartComponent>
      </ResponsiveContainer>
    )
  }

  return (
    <>
      {/* Backdrop */}
      <div 
        className={`analytics-drawer-backdrop ${open ? 'open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      
      {/* Drawer */}
      <div className={`analytics-drawer ${open ? 'open' : ''}`} role="dialog" aria-modal="true">
        {/* Header */}
        <div className="analytics-drawer-header">
          <div className="drawer-title-section">
            <h2 className="drawer-title">{title || config.label}</h2>
            <div className="drawer-total">
              {loading ? (
                <span className="total-skeleton" />
              ) : (
                <span className="total-value">{config.format(total)}</span>
              )}
              <span className="total-label">Total for period</span>
            </div>
          </div>
          <button 
            className="drawer-close-btn" 
            onClick={onClose}
            aria-label="Close"
          >
            <i className="fa-solid fa-xmark" />
          </button>
        </div>

        {/* Range Selector */}
        <div className="analytics-drawer-controls">
          <div className="range-selector">
            {RANGE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                className={`range-btn ${range === opt.value ? 'active' : ''}`}
                onClick={() => setRange(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Scrollable body for chart and footer */}
        <div className="analytics-drawer-body">
          {/* Chart */}
          <div className="analytics-drawer-chart">
            {renderChart()}
          </div>

          {/* Footer with insights */}
          <div className="analytics-drawer-footer">
            <div className="insight-cards">
              <div className="insight-card">
                <div className="insight-label">Period Average</div>
                <div className="insight-value">
                  {loading ? '—' : config.format(data.length > 0 ? total / data.length : 0)}
                </div>
              </div>
              <div className="insight-card">
                <div className="insight-label">Peak Day</div>
                <div className="insight-value">
                  {loading ? '—' : (
                    data.length > 0 
                      ? config.format(Math.max(...data.map(d => d.value)))
                      : config.format(0)
                  )}
                </div>
              </div>
              <div className="insight-card">
                <div className="insight-label">Data Points</div>
                <div className="insight-value">{loading ? '—' : data.length}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}


