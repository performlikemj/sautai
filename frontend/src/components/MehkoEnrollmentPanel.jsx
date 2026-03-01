import React, { useEffect, useState } from 'react'
import { api, buildErrorMessage } from '../api'

// Mirrors chefs/constants.py MEHKO_APPROVED_COUNTIES + COUNTY_ENFORCEMENT_AGENCIES
const APPROVED_COUNTIES = [
  'Alameda', 'Amador', 'Contra Costa', 'Imperial', 'Lake', 'Los Angeles',
  'Monterey', 'Riverside', 'San Benito', 'San Diego', 'San Mateo',
  'Santa Barbara', 'Santa Clara', 'Santa Cruz', 'Sierra', 'Solano',
  'Sonoma', 'City of Berkeley',
]

const COUNTY_AGENCIES = {
  'Alameda': { name: 'Alameda County Dept. of Environmental Health', url: 'https://deh.acgov.org/operations/home-based-food-business.page' },
  'Amador': { name: 'Amador County Environmental Health', url: 'https://www.amadorgov.org/services/environmental-health' },
  'Contra Costa': { name: 'Contra Costa County Environmental Health', url: 'https://cchealth.org/eh/' },
  'Imperial': { name: 'Imperial County Environmental Health Services', url: 'https://www.imperialcounty.org/publichealth/environmental-health/' },
  'Lake': { name: 'Lake County Environmental Health', url: 'https://www.lakecountyca.gov/Government/Directory/EnvironmentalHealth.htm' },
  'Los Angeles': { name: 'LA County Dept. of Public Health, Environmental Health', url: 'http://publichealth.lacounty.gov/eh/business/microenterprise-home-kitchen-operation.htm' },
  'Monterey': { name: 'Monterey County Environmental Health Bureau', url: 'https://www.co.monterey.ca.us/government/departments-a-h/health/environmental-health' },
  'Riverside': { name: 'Riverside County Dept. of Environmental Health', url: 'https://www.rivcoeh.org/' },
  'San Benito': { name: 'San Benito County Environmental Health', url: 'https://hhsa.cosb.us/environmental-health/' },
  'San Diego': { name: 'San Diego County Dept. of Environmental Health', url: 'https://www.sandiegocounty.gov/deh/' },
  'San Mateo': { name: 'San Mateo County Environmental Health Services', url: 'https://www.smchealth.org/microkitchens-mehko' },
  'Santa Barbara': { name: 'Santa Barbara County Environmental Health Services', url: 'https://www.countyofsb.org/phd/environmentalhealth.sbc' },
  'Santa Clara': { name: 'Santa Clara County Dept. of Environmental Health', url: 'https://www.sccgov.org/sites/deh/Pages/deh.aspx' },
  'Santa Cruz': { name: 'Santa Cruz County Environmental Health', url: 'https://www.santacruzhealth.org/HSADivisions/EnvironmentalHealth.aspx' },
  'Sierra': { name: 'Sierra County Environmental Health', url: 'https://www.sierracounty.ca.gov/' },
  'Solano': { name: 'Solano County Dept. of Resource Management', url: 'https://www.solanocounty.com/depts/rm/environmental_health/default.asp' },
  'Sonoma': { name: 'Sonoma County Permit & Resource Management Dept.', url: 'https://sonomacounty.ca.gov/PRMD/Regulations/Environmental-Health-and-Safety/' },
  'City of Berkeley': { name: 'City of Berkeley Environmental Health', url: 'https://www.cityofberkeley.info/Health_Human_Services/Environmental_Health/' },
}

const REQUIREMENT_LABELS = {
  permit_number: 'Permit number',
  permitting_agency: 'Permitting agency',
  permit_expiry: 'Permit expiry date (must be future)',
  county: 'Approved county',
  mehko_consent: 'MEHKO operator consent',
  food_handlers_cert: 'Food handler certificate (on your profile)',
  insured: 'Liability insurance (on your profile)',
  insurance_expiry: 'Insurance not expired (on your profile)',
}

export default function MehkoEnrollmentPanel({ onNavigate }) {
  const [status, setStatus] = useState(null)       // API data
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [form, setForm] = useState({
    permit_number: '',
    county: '',
    permitting_agency: '',
    permit_expiry: '',
    mehko_consent: false,
  })

  useEffect(() => {
    api.get('/chefs/api/mehko/')
      .then(res => {
        const d = res.data
        setStatus(d)
        setForm({
          permit_number: d.permit_number || '',
          county: d.county || '',
          permitting_agency: d.permitting_agency || '',
          permit_expiry: d.permit_expiry || '',
          mehko_consent: d.mehko_consent || false,
        })
      })
      .catch(() => setError('Unable to load MEHKO status. Please refresh.'))
      .finally(() => setLoading(false))
  }, [])

  // Auto-fill agency when county changes
  function handleCountyChange(county) {
    const agency = COUNTY_AGENCIES[county]?.name || ''
    setForm(f => ({ ...f, county, permitting_agency: agency }))
  }

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const res = await api.patch('/chefs/api/mehko/', form)
      setStatus(res.data)
      if (res.data.mehko_active) {
        setSuccess('🎉 Your MEHKO listing is now active! Customers can find you in the directory.')
      } else {
        setSuccess('Saved. Complete the remaining requirements below to activate your listing.')
      }
    } catch (err) {
      let msg = 'Unable to save. Please check your entries and try again.'
      if (err?.response) msg = buildErrorMessage(err.response.data, msg, err.response.status)
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  const missing = status?.missing_requirements || []
  const isActive = status?.mehko_active === true
  const agency = form.county ? COUNTY_AGENCIES[form.county] : null
  const profileMissing = missing.filter(r => ['food_handlers_cert', 'insured', 'insurance_expiry'].includes(r))
  const formMissing = missing.filter(r => !['food_handlers_cert', 'insured', 'insurance_expiry'].includes(r))

  if (loading) {
    return (
      <div className="mehko-panel-loading">
        <div className="spinner" />
        <p>Loading MEHKO status…</p>
      </div>
    )
  }

  return (
    <div className="mehko-enrollment-panel">
      {/* Status banner */}
      <div className={`mehko-status-banner ${isActive ? 'active' : missing.length === 0 ? 'pending' : 'incomplete'}`}>
        <i className={`fa-solid ${isActive ? 'fa-circle-check' : 'fa-house-chimney'}`}></i>
        <div>
          <strong>{isActive ? 'MEHKO listing active' : status?.permit_number ? 'Application in progress' : 'Not enrolled'}</strong>
          <p>
            {isActive
              ? 'Your home kitchen is verified and visible to customers as a MEHKO · Home Kitchen chef.'
              : 'Complete all requirements below to activate your MEHKO listing on Sautai.'}
          </p>
        </div>
      </div>

      {/* What is MEHKO */}
      {!isActive && (
        <div className="mehko-explainer">
          <h3><i className="fa-solid fa-circle-info"></i> What is MEHKO?</h3>
          <p>
            A <strong>Microenterprise Home Kitchen Operation (MEHKO)</strong> lets you legally sell
            home-cooked meals directly from your permitted home kitchen in California. You must hold
            a valid permit from your county health department before enrolling.
          </p>
          <p style={{ marginTop: '.5rem', fontSize: '.88rem', color: 'var(--muted)' }}>
            MEHKO chefs appear with a special badge in the directory and can only offer same-day,
            chef-delivered orders (no third-party delivery, no catering).
          </p>
        </div>
      )}

      {/* Requirements checklist */}
      <div className="mehko-checklist">
        <h3>Requirements</h3>
        <ul>
          {Object.entries(REQUIREMENT_LABELS).map(([key, label]) => {
            const done = !missing.includes(key)
            return (
              <li key={key} className={`mehko-req-item ${done ? 'done' : 'missing'}`}>
                <i className={`fa-solid ${done ? 'fa-circle-check' : 'fa-circle-xmark'}`}></i>
                <span>{label}</span>
                {['food_handlers_cert', 'insured', 'insurance_expiry'].includes(key) && !done && (
                  <button
                    className="btn-link"
                    onClick={() => onNavigate?.('profile')}
                    style={{ marginLeft: '.5rem', fontSize: '.82rem' }}
                  >
                    Update in Profile →
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      </div>

      {profileMissing.length > 0 && (
        <div className="mehko-profile-notice">
          <i className="fa-solid fa-circle-exclamation"></i>
          <span>
            Some requirements (food handler cert, insurance) are set on your{' '}
            <button className="btn-link" onClick={() => onNavigate?.('profile')}>Profile tab</button>.
            Complete those first, then return here.
          </span>
        </div>
      )}

      {/* Enrollment form */}
      <form className="mehko-form" onSubmit={handleSave}>
        <h3>Permit Details</h3>

        <div className="form-group">
          <label className="label" htmlFor="mehko-county">County *</label>
          <select
            id="mehko-county"
            className="input"
            value={form.county}
            onChange={e => handleCountyChange(e.target.value)}
            required
          >
            <option value="">Select your county…</option>
            {APPROVED_COUNTIES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <p className="field-hint">Only California counties that have opted into AB 626 are listed.</p>
          {agency && (
            <p className="field-hint" style={{ marginTop: '.25rem' }}>
              Permitting agency:{' '}
              <a href={agency.url} target="_blank" rel="noopener noreferrer">{agency.name}</a>
            </p>
          )}
        </div>

        <div className="form-group">
          <label className="label" htmlFor="mehko-permit">Permit Number *</label>
          <input
            id="mehko-permit"
            className="input"
            type="text"
            value={form.permit_number}
            onChange={e => setForm(f => ({ ...f, permit_number: e.target.value }))}
            placeholder="e.g. MEH-2024-001234"
            required
          />
          <p className="field-hint">As shown on your permit issued by your county health department.</p>
        </div>

        <div className="form-group">
          <label className="label" htmlFor="mehko-agency">Permitting Agency *</label>
          <input
            id="mehko-agency"
            className="input"
            type="text"
            value={form.permitting_agency}
            onChange={e => setForm(f => ({ ...f, permitting_agency: e.target.value }))}
            placeholder="e.g. Los Angeles County Environmental Health"
            required
          />
        </div>

        <div className="form-group">
          <label className="label" htmlFor="mehko-expiry">Permit Expiry Date *</label>
          <input
            id="mehko-expiry"
            className="input"
            type="date"
            value={form.permit_expiry}
            onChange={e => setForm(f => ({ ...f, permit_expiry: e.target.value }))}
            min={new Date().toISOString().split('T')[0]}
            required
          />
        </div>

        {/* Consent — only shown if not yet given (immutable once accepted) */}
        {!status?.mehko_consent && (
          <div className="mehko-consent-block">
            <h3>Operator Agreement</h3>
            <div className="mehko-consent-text">
              <p>By checking this box, I confirm that:</p>
              <ul>
                <li>I hold a valid MEHKO permit issued by my county health department.</li>
                <li>I understand this registration is <strong>non-transferable</strong> and valid only at my permitted address.</li>
                <li>I will only offer same-day orders — food prepared and served the same day.</li>
                <li>I will not use third-party delivery services (except as a disability accommodation).</li>
                <li>I will not market my services as "catering" or operate beyond the 30 meals/day and 90 meals/week limits.</li>
                <li>I understand Sautai may report my information to my county enforcement agency if required by law.</li>
              </ul>
            </div>
            <label className="mehko-consent-checkbox">
              <input
                type="checkbox"
                checked={form.mehko_consent}
                onChange={e => setForm(f => ({ ...f, mehko_consent: e.target.checked }))}
              />
              <span>I agree to the MEHKO Operator Agreement and California food safety requirements.</span>
            </label>
          </div>
        )}

        {status?.mehko_consent && (
          <p className="mehko-consent-confirmed">
            <i className="fa-solid fa-circle-check"></i>
            Operator agreement accepted on {status.mehko_consent_at
              ? new Date(status.mehko_consent_at).toLocaleDateString()
              : 'file'}.
          </p>
        )}

        {error && (
          <div className="form-error" role="alert">
            <i className="fa-solid fa-exclamation-circle"></i> {error}
          </div>
        )}
        {success && (
          <div className="form-success" role="status">
            <i className="fa-solid fa-circle-check"></i> {success}
          </div>
        )}

        <div className="form-actions">
          <button
            type="submit"
            className="btn btn-primary btn-lg"
            disabled={saving || (!form.mehko_consent && !status?.mehko_consent)}
          >
            {saving ? (
              <><div className="spinner" style={{ width: 16, height: 16, borderWidth: 2, marginRight: '.5rem' }}></div>Saving…</>
            ) : isActive ? 'Update Permit Details' : 'Save & Activate'}
          </button>
        </div>
      </form>
    </div>
  )
}
