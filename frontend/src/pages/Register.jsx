import React, { useEffect, useState } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { COUNTRIES } from '../utils/geo.js'

const TIMEZONES_FALLBACK = ['UTC','America/New_York','America/Chicago','America/Los_Angeles','Europe/London','Europe/Paris','Asia/Tokyo']
const MEASUREMENT_LABEL = { US: 'US Customary (oz, lb, cups)', METRIC: 'Metric (g, kg, ml, l)' }

export default function Register(){
  const { register } = useAuth()
  const nav = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeAudience, setActiveAudience] = useState(searchParams.get('intent') === 'chef' ? 'chef' : 'customer')
  const isChef = activeAudience === 'chef'

  const browserTz = (()=>{
    try{ return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' }catch{ return 'UTC' }
  })()

  const [form, setForm] = useState({ username:'', email:'', password:'', confirm:'', timezone: browserTz, measurement_system:'METRIC', city:'', country:'' })
  const [timezones, setTimezones] = useState(TIMEZONES_FALLBACK)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(()=>{
    try{
      const iana = (Intl && Intl.supportedValuesOf) ? Intl.supportedValuesOf('timeZone') : []
      if (Array.isArray(iana) && iana.length){
        const sorted = Array.from(new Set(iana)).sort((a,b)=> a.localeCompare(b))
        setTimezones(sorted)
        if (!sorted.includes(form.timezone)) setForm(f=>({...f, timezone:'UTC'}))
      }
    }catch{}
  }, [])

  const set = (k)=>(e)=> setForm({...form, [k]: e.target.value})

  const switchAudience = (audience) => {
    setActiveAudience(audience)
    setSearchParams(audience === 'chef' ? { intent: 'chef' } : {}, { replace: true })
  }

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (form.password !== form.confirm){ setError('Passwords do not match.'); return }
    if ((form.password||'').length < 8){ setError('Password must be at least 8 characters.'); return }
    if (isChef && (!form.city.trim() || !form.country.trim())){
      setError('City and country are required to set up your chef profile.')
      return
    }
    setLoading(true)
    try{
      const body = {
        user: {
          username: form.username,
          email: form.email,
          password: form.password,
          timezone: form.timezone,
          measurement_system: form.measurement_system,
          preferred_language: 'en',
          allergies: [],
          custom_allergies: [],
          dietary_preferences: [],
          custom_dietary_preferences: [],
          household_member_count: 1,
          household_members: []
        }
      }
      // Include address for chef intent (city + country)
      if (isChef && form.city.trim() && form.country.trim()) {
        body.address = { city: form.city.trim(), country: form.country.trim() }
        body.intent = 'chef'
      }
      await register(body)
      // Chef intent → go to profile with chef application open
      if (isChef) {
        nav('/profile?applyChef=1')
      } else {
        nav('/meal-plans')
      }
    }catch(err){
      setError('Registration failed. Try a different username/email.')
    }finally{
      setLoading(false)
    }
  }

  return (
    <div style={{maxWidth:520, margin:'1rem auto'}}>
      {/* Audience toggle — mirrors Home hero pattern */}
      <div className="home-audience-toggle" style={{marginBottom:'1rem'}}>
        <button
          className={`audience-btn ${activeAudience === 'customer' ? 'active' : ''}`}
          onClick={() => switchAudience('customer')}
          type="button"
        >
          I'm looking for a chef
        </button>
        <button
          className={`audience-btn ${activeAudience === 'chef' ? 'active' : ''}`}
          onClick={() => switchAudience('chef')}
          type="button"
        >
          I'm a chef
        </button>
      </div>

      <h2>{isChef ? 'Create your chef account' : 'Create your account'}</h2>
      <div className="muted" style={{marginBottom:'.5rem'}}>
        {isChef
          ? 'Set up your account and we\'ll take you straight to your chef application.'
          : 'We only need the basics to get started. You can add the rest in your profile later.'}
      </div>
      {error && <div className="card" style={{borderColor:'var(--danger, #d9534f)'}}>{error}</div>}
      <form onSubmit={submit}>
        <label className="label" htmlFor="reg-username">Username</label>
        <input className="input" id="reg-username" name="username" autoComplete="username" value={form.username} onChange={set('username')} required />
        <label className="label" htmlFor="reg-email">Email</label>
        <input className="input" id="reg-email" name="email" type="email" autoComplete="email" value={form.email} onChange={set('email')} required />
        <label className="label" htmlFor="reg-password">Password</label>
        <input className="input" id="reg-password" name="password" type="password" autoComplete="new-password" value={form.password} onChange={set('password')} required />
        <label className="label" htmlFor="reg-confirm">Confirm Password</label>
        <input className="input" id="reg-confirm" name="confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={set('confirm')} required />

        {isChef && (
          <>
            <label className="label" htmlFor="reg-city">City</label>
            <input className="input" id="reg-city" name="city" autoComplete="address-level2" placeholder="e.g., Los Angeles" value={form.city} onChange={set('city')} required />
            <label className="label" htmlFor="reg-country">Country</label>
            <select className="select" id="reg-country" name="country" value={form.country} onChange={set('country')} required>
              <option value="">Select country</option>
              {COUNTRIES.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </>
        )}

        <label className="label" htmlFor="reg-timezone">Time Zone</label>
        <select className="select" id="reg-timezone" name="timezone" value={form.timezone} onChange={set('timezone')}>
          {timezones.map(tz => <option key={tz} value={tz}>{tz}</option>)}
        </select>
        <span className="label" style={{marginTop:'.6rem'}}>Units</span>
        <div role="radiogroup" aria-label="Measurement system" style={{display:'flex', gap:'.75rem', alignItems:'center', marginBottom:'.5rem'}}>
          <label className="radio" style={{display:'flex', alignItems:'center', gap:'.35rem'}}>
            <input type="radio" name="measurement_system" checked={(form.measurement_system||'METRIC')==='US'} onChange={()=> setForm({...form, measurement_system:'US'})} />
            <span>{MEASUREMENT_LABEL.US}</span>
          </label>
          <label className="radio" style={{display:'flex', alignItems:'center', gap:'.35rem'}}>
            <input type="radio" name="measurement_system" checked={(form.measurement_system||'METRIC')==='METRIC'} onChange={()=> setForm({...form, measurement_system:'METRIC'})} />
            <span>{MEASUREMENT_LABEL.METRIC}</span>
          </label>
        </div>
        <div style={{marginTop:'.75rem'}}>
          <button className="btn btn-primary" disabled={loading}>{loading?'Creating…':'Create Account'}</button>
          <Link to="/login" className="btn btn-outline" style={{marginLeft:'.5rem'}}>I have an account</Link>
        </div>
      </form>
    </div>
  )
}
