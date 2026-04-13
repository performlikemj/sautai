import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api'
import { getSeededChefEmoji } from '../utils/emojis.js'
import { HOME_IMAGES } from '../config/homeImages.js'
import { HOME_CONFIG } from '../config/homeConstants.js'
import { trackEvent, EVENTS } from '../utils/analytics.js'
import ServiceAreaPicker from '../components/ServiceAreaPicker.jsx'

// Animated counter hook for trust metrics
function useAnimatedCounter(targetValue, duration = 2000) {
  const [count, setCount] = useState(0)
  const [animationKey, setAnimationKey] = useState(0)
  const ref = useRef(null)

  // Trigger animation when target value changes
  useEffect(() => {
    if (targetValue > 0) {
      setAnimationKey(k => k + 1)
    }
  }, [targetValue])

  useEffect(() => {
    if (targetValue === 0) {
      setCount(0)
      return
    }
    
    let startTime = null
    const animate = (timestamp) => {
      if (!startTime) startTime = timestamp
      const progress = Math.min((timestamp - startTime) / duration, 1)
      setCount(Math.floor(progress * targetValue))
      if (progress < 1) requestAnimationFrame(animate)
    }
    requestAnimationFrame(animate)
  }, [animationKey, targetValue, duration])

  return { count, ref }
}

// Featured chef card component - memoized to prevent unnecessary re-renders
const ChefCard = React.memo(function ChefCard({ chef }) {
  const username = chef?.user?.username || 'Chef'
  const profilePic = chef?.profile_pic_url
  const bio = chef?.bio || ''
  const location = chef?.city || chef?.location_city || ''
  const country = chef?.country || ''
  const photoCount = chef?.photos?.length || 0
  // Use chef's chosen emoji, or fall back to a seeded random for consistency
  const chefEmoji = chef?.sous_chef_emoji || getSeededChefEmoji(chef?.id || username)

  const handleClick = () => {
    trackEvent(EVENTS.HOME_CHEF_CARD_CLICKED, { chefId: chef?.id, username })
  }

  return (
    <Link
      to={`/c/${encodeURIComponent(username)}`}
      className="home-chef-card"
      onClick={handleClick}
    >
      <div className="home-chef-avatar">
        {profilePic ? (
          <img src={profilePic} alt={username} loading="lazy" />
        ) : (
          <div className="home-chef-avatar-emoji">
            <span role="img" aria-label="chef">{chefEmoji}</span>
          </div>
        )}
      </div>
      <div className="home-chef-info">
        <h4 className="home-chef-name">{username}</h4>
        {(location || country) && (
          <p className="home-chef-location">
            <i className="fa-solid fa-location-dot"></i>
            {[location, country].filter(Boolean).join(', ')}
          </p>
        )}
        {bio && (
          <p className="home-chef-bio">
            {bio.slice(0, HOME_CONFIG.BIO_MAX_LENGTH)}
            {bio.length > HOME_CONFIG.BIO_MAX_LENGTH ? '...' : ''}
          </p>
        )}
      </div>
      {photoCount > 0 && (
        <div className="home-chef-photos">
          <i className="fa-solid fa-images"></i> {photoCount}
        </div>
      )}
    </Link>
  )
})

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [locationQuery, setLocationQuery] = useState('')
  const [featuredChefs, setFeaturedChefs] = useState([])
  const [loadingChefs, setLoadingChefs] = useState(true)
  const [activeAudience, setActiveAudience] = useState('customer') // 'customer' or 'chef'

  // Application modal state (for logged-in non-chef users)
  const [applyOpen, setApplyOpen] = useState(false)
  const [chefForm, setChefForm] = useState({ experience: '', bio: '', serving_areas: '', selected_areas: [], profile_pic: null })
  const [submitting, setSubmitting] = useState(false)
  const [applyMsg, setApplyMsg] = useState(null)

  // Platform stats from real data
  const [platformStats, setPlatformStats] = useState({ chefCount: 0, cityCount: 0 })

  // Error state for failed chef fetch
  const [chefsError, setChefsError] = useState(null)

  // Animated counters for trust metrics - using real data
  const chefsCounter = useAnimatedCounter(platformStats.chefCount, HOME_CONFIG.CHEF_COUNTER_DURATION)
  const citiesCounter = useAnimatedCounter(platformStats.cityCount, HOME_CONFIG.CITY_COUNTER_DURATION)

  // Fetch featured chefs and derive real stats
  const fetchChefs = useCallback(() => {
    setChefsError(null)
    setLoadingChefs(true)
    api.get('/chefs/api/public/', { params: { page_size: HOME_CONFIG.CHEF_PAGE_SIZE }, skipUserId: true })
      .then(res => {
        const list = Array.isArray(res.data) ? res.data : (res.data?.results || [])

        // Set featured chefs (limited by config)
        setFeaturedChefs(list.slice(0, HOME_CONFIG.FEATURED_CHEFS_LIMIT))

        // Calculate real stats from chef data
        const chefCount = res.data?.count || list.length

        // Count unique cities from chef serving areas
        const cities = new Set()
        list.forEach(chef => {
          const postalCodes = chef?.serving_postalcodes || []
          postalCodes.forEach(pc => {
            const city = pc?.city || ''
            if (city.trim()) cities.add(city.toLowerCase())
          })
          // Also check chef's direct city field
          const chefCity = chef?.city || chef?.location_city || ''
          if (chefCity.trim()) cities.add(chefCity.toLowerCase())
        })

        setPlatformStats({
          chefCount: chefCount,
          cityCount: Math.max(cities.size, 1) // At least 1 if we have chefs
        })
      })
      .catch(() => {
        setChefsError('Unable to load chefs. Please try again.')
      })
      .finally(() => setLoadingChefs(false))
  }, [])

  useEffect(() => {
    fetchChefs()
  }, [fetchChefs])

  const handleLocationSearch = useCallback((e) => {
    e.preventDefault()
    trackEvent(EVENTS.HOME_SEARCH_SUBMITTED, { query: locationQuery.trim() })
    if (locationQuery.trim()) {
      navigate(`/chefs?q=${encodeURIComponent(locationQuery.trim())}`)
    } else {
      navigate('/chefs')
    }
  }, [locationQuery, navigate])

  const handleChefApplication = useCallback(async () => {
    setSubmitting(true)
    setApplyMsg(null)
    try {
      const fd = new FormData()
      fd.append('experience', chefForm.experience)
      fd.append('bio', chefForm.bio)
      fd.append('serving_areas', chefForm.serving_areas)
      if (user?.address?.city) fd.append('city', user.address.city)
      if (user?.address?.country) fd.append('country', user.address.country)
      if (chefForm.profile_pic) fd.append('profile_pic', chefForm.profile_pic)
      if (chefForm.selected_areas?.length) {
        fd.append('selected_area_ids', JSON.stringify(chefForm.selected_areas.map(a => a.area_id || a.id)))
      }

      const resp = await api.post('/chefs/api/submit-chef-request/', fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      const success = resp.status === 200 || resp.status === 201
      trackEvent(EVENTS.HOME_CHEF_APPLICATION_SUBMITTED, { success })
      if (success) {
        setApplyMsg('Application submitted! We\'ll notify you when approved.')
      } else {
        setApplyMsg('Submission failed. Please try again later.')
      }
    } catch (e) {
      trackEvent(EVENTS.HOME_CHEF_APPLICATION_SUBMITTED, { success: false })
      setApplyMsg(e?.response?.data?.error || 'Submission failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }, [chefForm, user?.address?.city, user?.address?.country])

  // Handler for opening chef application modal
  const handleOpenApplyModal = useCallback(() => {
    trackEvent(EVENTS.HOME_CHEF_APPLICATION_STARTED)
    setApplyOpen(true)
  }, [])

  // SEO: Inject structured data for search engines
  useEffect(() => {
    const structuredData = {
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      'name': 'sautai',
      'url': 'https://sautai.com',
      'description': 'Connect with talented local chefs for meal prep, private dinners, cooking classes, and more.',
      'potentialAction': {
        '@type': 'SearchAction',
        'target': 'https://sautai.com/chefs?q={search_term_string}',
        'query-input': 'required name=search_term_string'
      }
    }

    const organizationData = {
      '@context': 'https://schema.org',
      '@type': 'Organization',
      'name': 'sautai',
      'url': 'https://sautai.com',
      'logo': 'https://sautai.com/sautai_logo_new.png',
      'description': 'AI-powered platform connecting food lovers with local personal chefs'
    }

    // Create script elements
    const websiteScript = document.createElement('script')
    websiteScript.type = 'application/ld+json'
    websiteScript.id = 'home-structured-data-website'
    websiteScript.textContent = JSON.stringify(structuredData)

    const orgScript = document.createElement('script')
    orgScript.type = 'application/ld+json'
    orgScript.id = 'home-structured-data-org'
    orgScript.textContent = JSON.stringify(organizationData)

    // Remove existing if present (for hot reload)
    document.getElementById('home-structured-data-website')?.remove()
    document.getElementById('home-structured-data-org')?.remove()

    document.head.appendChild(websiteScript)
    document.head.appendChild(orgScript)

    return () => {
      document.getElementById('home-structured-data-website')?.remove()
      document.getElementById('home-structured-data-org')?.remove()
    }
  }, [])

  return (
    <div className="page-home-v2">
      {/* ============================================ */}
      {/* HERO SECTION - Split Audience Design */}
      {/* ============================================ */}
      <section className="home-hero">
        <div className="home-hero-bg"></div>
        {/* Decorative organic blob shapes */}
        <div className="home-blob home-blob-1"></div>
        <div className="home-blob home-blob-2"></div>
        <div className="home-blob home-blob-3"></div>
        <div className="home-hero-content">
          {/* Audience Toggle */}
          <div className="home-audience-toggle">
            <button
              className={`audience-btn ${activeAudience === 'customer' ? 'active' : ''}`}
              onClick={() => {
                setActiveAudience('customer')
                trackEvent(EVENTS.HOME_AUDIENCE_TOGGLED, { audience: 'customer' })
              }}
            >
              I'm looking for a chef
            </button>
            <button
              className={`audience-btn ${activeAudience === 'chef' ? 'active' : ''}`}
              onClick={() => {
                setActiveAudience('chef')
                trackEvent(EVENTS.HOME_AUDIENCE_TOGGLED, { audience: 'chef' })
              }}
            >
              I'm a chef
            </button>
          </div>

          {/* Customer-focused hero */}
          {activeAudience === 'customer' && (
            <div className="home-hero-main">
              <h1 className="home-hero-title">
                Discover Your Perfect <span className="text-gradient">Personal Chef</span>
              </h1>
              <p className="home-hero-subtitle">
                Fresh, thoughtful meals made by talented local chefs — meal prep, private dinners,
                cooking classes, and so much more. Your kitchen, their craft.
              </p>
              
              {/* Location Search */}
              <form className="home-search-form" onSubmit={handleLocationSearch}>
                <div className="home-search-input-wrap">
                  <i className="fa-solid fa-location-dot"></i>
                  <input
                    type="text"
                    placeholder="Enter your city or postal code..."
                    value={locationQuery}
                    onChange={(e) => setLocationQuery(e.target.value)}
                    className="home-search-input"
                  />
                </div>
                <button type="submit" className="btn btn-primary home-search-btn">
                  Find Chefs
                </button>
              </form>

              <div className="home-hero-links">
                <Link to="/chefs" className="home-hero-link">
                  <i className="fa-solid fa-globe"></i>
                  Browse all chefs
                </Link>
                {!user && (
                  <Link to="/register" className="home-hero-link">
                    <i className="fa-solid fa-user-plus"></i>
                    Create free account
                  </Link>
                )}
              </div>
            </div>
          )}

          {/* Chef-focused hero */}
          {activeAudience === 'chef' && (
            <div className="home-hero-main">
              <h1 className="home-hero-title">
                Grow Your <span className="text-gradient">Culinary Business</span>
              </h1>
              <p className="home-hero-subtitle">
                The home for independent chefs who love what they do. Manage clients, services, and
                bookings with ease — you focus on creating, we handle the rest.
              </p>
              
              <div className="home-hero-actions">
                {!user && (
                  <Link to="/register?intent=chef" className="btn btn-primary btn-lg">
                    Start Your Chef Profile
                  </Link>
                )}
                {user?.is_chef && (
                  <Link to="/chefs/dashboard" className="btn btn-primary btn-lg">
                    Go to Chef Hub
                  </Link>
                )}
                {user && !user?.is_chef && (
                  <button className="btn btn-primary btn-lg" onClick={handleOpenApplyModal}>
                    Apply to Become a Chef
                  </button>
                )}
              </div>

              <div className="home-chef-features">
                <div className="home-chef-feature">
                  <i className="fa-solid fa-users"></i>
                  <span>Client Management</span>
                </div>
                <div className="home-chef-feature">
                  <i className="fa-solid fa-calendar-check"></i>
                  <span>Easy Booking</span>
                </div>
                <div className="home-chef-feature">
                  <i className="fa-solid fa-credit-card"></i>
                  <span>Stripe Payments</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Hero Image */}
        <div className="home-hero-image">
          <img
            src={activeAudience === 'customer' ? HOME_IMAGES.hero.customer : HOME_IMAGES.hero.chef}
            alt={activeAudience === 'customer' ? 'Delicious home-cooked meal' : 'Professional chef at work'}
            loading="lazy"
          />
        </div>
      </section>

      {/* ============================================ */}
      {/* TRUST METRICS BAR */}
      {/* ============================================ */}
      {platformStats.chefCount > 0 && (
        <section className="home-trust-bar" ref={chefsCounter.ref}>
          <div className="home-trust-content">
            <div className="home-trust-item">
              <div className="home-trust-icon">
                <i className="fa-solid fa-hat-chef"></i>
              </div>
              <span className="home-trust-number">{chefsCounter.count}</span>
              <span className="home-trust-label">Active {chefsCounter.count === 1 ? 'Chef' : 'Chefs'}</span>
            </div>
            {platformStats.cityCount > 0 && (
              <div className="home-trust-item">
                <div className="home-trust-icon">
                  <i className="fa-solid fa-location-dot"></i>
                </div>
                <span className="home-trust-number">{citiesCounter.count}</span>
                <span className="home-trust-label">{citiesCounter.count === 1 ? 'City' : 'Cities'}</span>
              </div>
            )}
            <div className="home-trust-item">
              <div className="home-trust-icon">
                <i className="fa-solid fa-shield-halved"></i>
              </div>
              <span className="home-trust-number" style={{ fontSize: '1rem', fontFamily: "'DM Sans', sans-serif" }}>Verified</span>
              <span className="home-trust-label">Trusted Chefs</span>
            </div>
            <div className="home-trust-item">
              <div className="home-trust-icon">
                <i className="fa-brands fa-stripe"></i>
              </div>
              <span className="home-trust-number" style={{ fontSize: '1rem', fontFamily: "'DM Sans', sans-serif" }}>Stripe</span>
              <span className="home-trust-label">Secure Payments</span>
            </div>
          </div>
        </section>
      )}

      {/* ============================================ */}
      {/* FEATURED CHEFS SECTION */}
      {/* ============================================ */}
      <section className="home-section home-featured-chefs">
        <div className="home-section-header">
          <h2 className="home-section-title">Meet Our Chefs</h2>
          <p className="home-section-subtitle">
            Real people, real passion. Talented culinary professionals ready to bring something special to your table.
          </p>
        </div>

        <div className="home-chefs-grid">
          {loadingChefs ? (
            <div className="home-chefs-loading" role="status" aria-live="polite">
              <div className="spinner"></div>
            </div>
          ) : chefsError ? (
            <div className="home-chefs-error" role="status">
              <i className="fa-solid fa-triangle-exclamation"></i>
              <p>{chefsError}</p>
              <button className="btn btn-outline" onClick={fetchChefs}>
                Try Again
              </button>
            </div>
          ) : featuredChefs.length > 0 ? (
            featuredChefs.map(chef => (
              <ChefCard key={chef.id} chef={chef} />
            ))
          ) : (
            <p className="home-chefs-empty" role="status">Chefs are joining every day. Check back soon!</p>
          )}
        </div>

        <div className="home-section-cta">
          <Link to="/chefs" className="btn btn-outline btn-lg">
            <i className="fa-solid fa-utensils"></i>
            View All Chefs
          </Link>
        </div>
      </section>

      {/* ============================================ */}
      {/* SERVICE CATEGORIES */}
      {/* ============================================ */}
      <section className="home-section home-services">
        <div className="home-section-header">
          <h2 className="home-section-title">What Can a Chef Do for You?</h2>
          <p className="home-section-subtitle">
            From weekly meal prep to special occasions, find the perfect service for your table
          </p>
        </div>

        <div className="home-services-grid">
          <Link
            to="/chefs?service=meal-prep"
            className="home-service-card"
            onClick={() => trackEvent(EVENTS.HOME_SERVICE_CARD_CLICKED, { service: 'meal-prep' })}
          >
            <div className="home-service-image">
              <img src={HOME_IMAGES.services.mealPrep} alt="Meal Prep" loading="lazy" />
              <div className="home-service-overlay">
                <span className="home-service-cta">
                  <i className="fa-solid fa-arrow-right"></i>
                  Find Chefs
                </span>
              </div>
            </div>
            <div className="home-service-content">
              <h3>Weekly Meal Prep</h3>
              <p>Healthy, portioned meals ready for your week. Save time and eat better.</p>
            </div>
          </Link>

          <Link
            to="/chefs?service=private-dining"
            className="home-service-card"
            onClick={() => trackEvent(EVENTS.HOME_SERVICE_CARD_CLICKED, { service: 'private-dining' })}
          >
            <div className="home-service-image">
              <img src={HOME_IMAGES.services.privateDining} alt="Private Dining" loading="lazy" />
              <div className="home-service-overlay">
                <span className="home-service-cta">
                  <i className="fa-solid fa-arrow-right"></i>
                  Find Chefs
                </span>
              </div>
            </div>
            <div className="home-service-content">
              <h3>Private Dinners</h3>
              <p>Restaurant-quality dining in your home. Perfect for special occasions.</p>
            </div>
          </Link>

          <Link
            to="/chefs?service=cooking-class"
            className="home-service-card"
            onClick={() => trackEvent(EVENTS.HOME_SERVICE_CARD_CLICKED, { service: 'cooking-class' })}
          >
            <div className="home-service-image">
              <img src={HOME_IMAGES.services.cookingClass} alt="Cooking Class" loading="lazy" />
              <div className="home-service-overlay">
                <span className="home-service-cta">
                  <i className="fa-solid fa-arrow-right"></i>
                  Find Chefs
                </span>
              </div>
            </div>
            <div className="home-service-content">
              <h3>Cooking Classes</h3>
              <p>Learn new techniques and recipes from professional chefs.</p>
            </div>
          </Link>

          <Link
            to="/chefs?service=events"
            className="home-service-card"
            onClick={() => trackEvent(EVENTS.HOME_SERVICE_CARD_CLICKED, { service: 'events' })}
          >
            <div className="home-service-image">
              <img src={HOME_IMAGES.services.events} alt="Events" loading="lazy" />
              <div className="home-service-overlay">
                <span className="home-service-cta">
                  <i className="fa-solid fa-arrow-right"></i>
                  Find Chefs
                </span>
              </div>
            </div>
            <div className="home-service-content">
              <h3>Events & Catering</h3>
              <p>From intimate gatherings to larger celebrations — we've got you covered.</p>
            </div>
          </Link>
        </div>
      </section>

      {/* ============================================ */}
      {/* HOW IT WORKS */}
      {/* ============================================ */}
      <section className="home-section home-how-it-works">
        <div className="home-section-header">
          <h2 className="home-section-title">How It Works</h2>
          <p className="home-section-subtitle">Three easy steps to delicious, homemade meals at your table</p>
        </div>

        <div className="home-steps">
          <div className="home-step">
            <div className="home-step-number">1</div>
            <div className="home-step-icon">
              <i className="fa-solid fa-magnifying-glass"></i>
            </div>
            <h3>Discover</h3>
            <p>Browse talented local chefs, explore their specialties, and find someone who cooks just your style.</p>
          </div>

          <div className="home-step-arrow">
            <i className="fa-solid fa-arrow-right"></i>
          </div>

          <div className="home-step">
            <div className="home-step-number">2</div>
            <div className="home-step-icon">
              <i className="fa-solid fa-handshake"></i>
            </div>
            <h3>Connect</h3>
            <p>Share your preferences, chat about your needs, and book a chef who gets it.</p>
          </div>

          <div className="home-step-arrow">
            <i className="fa-solid fa-arrow-right"></i>
          </div>

          <div className="home-step">
            <div className="home-step-number">3</div>
            <div className="home-step-icon">
              <i className="fa-solid fa-heart"></i>
            </div>
            <h3>Enjoy</h3>
            <p>Sit back, relax, and savor beautiful, personalized meals crafted with care just for you.</p>
          </div>
        </div>
      </section>

      {/* ============================================ */}
      {/* WHY SAUTAI - Value Props instead of fake testimonials */}
      {/* ============================================ */}
      <section className="home-section home-testimonials">
        <div className="home-section-header">
          <h2 className="home-section-title">Why Choose sautai?</h2>
          <p className="home-section-subtitle">
            We are building something thoughtful — a place where food lovers and talented chefs truly connect.
          </p>
        </div>

        <div className="home-testimonials-grid">
          <div className="home-testimonial">
            <div className="home-testimonial-icon">
              <i className="fa-solid fa-user-check"></i>
            </div>
            <h3>Verified Chefs</h3>
            <p>
              Every chef on our platform goes through a verification process. 
              Browse real profiles, see their work, and connect with confidence.
            </p>
          </div>

          <div className="home-testimonial">
            <div className="home-testimonial-icon">
              <i className="fa-solid fa-hand-holding-dollar"></i>
            </div>
            <h3>Fair & Transparent</h3>
            <p>
              Chefs set their own prices. No hidden fees. Secure payments through Stripe 
              protect both chefs and customers.
            </p>
          </div>

          <div className="home-testimonial">
            <div className="home-testimonial-icon">
              <i className="fa-solid fa-users"></i>
            </div>
            <h3>Community First</h3>
            <p>
              We're building a global community of independent chefs and food lovers. 
              Support local talent and discover amazing home-cooked meals.
            </p>
          </div>
        </div>
      </section>

      {/* ============================================ */}
      {/* FINAL CTA */}
      {/* ============================================ */}
      <section className="home-section home-final-cta">
        <div className="home-final-cta-content">
          <h2>Ready to Eat Well, Effortlessly?</h2>
          <p>
            Whether you are craving beautiful home-cooked meals or ready to share your
            culinary talent with the world — your community is waiting.
          </p>
          <div className="home-final-cta-actions">
            <Link to="/chefs" className="btn btn-primary btn-lg">
              <i className="fa-solid fa-search"></i>
              Find a Chef
            </Link>
            {!user && (
              <Link to="/register?intent=chef" className="btn btn-outline btn-lg">
                <i className="fa-solid fa-user-plus"></i>
                Create Chef Profile
              </Link>
            )}
            {user && !user?.is_chef && (
              <button className="btn btn-outline btn-lg" onClick={handleOpenApplyModal}>
                <i className="fa-solid fa-hat-chef"></i>
                Become a Chef
              </button>
            )}
            {user?.is_chef && (
              <Link to="/chefs/dashboard" className="btn btn-outline btn-lg">
                <i className="fa-solid fa-chart-line"></i>
                Chef Dashboard
              </Link>
            )}
          </div>
        </div>
      </section>

      {/* ============================================ */}
      {/* CHEF APPLICATION MODAL */}
      {/* ============================================ */}
      {applyOpen && (
        <>
          <div className="modal-overlay" onClick={() => setApplyOpen(false)} />
          <aside className="right-panel" role="dialog" aria-label="Become a Chef">
            <div className="right-panel-head">
              <div className="slot-title">Become a Personal Chef</div>
              <button className="icon-btn" onClick={() => setApplyOpen(false)}>
                <i className="fa-solid fa-times"></i>
              </button>
            </div>
            <div className="right-panel-body">
              {applyMsg && (
                <div className="card" style={{ marginBottom: '.75rem', padding: '.75rem' }}>
                  {applyMsg}
                </div>
              )}
              <p className="muted">Share your experience and where you can serve. You can complete your profile later.</p>
              
              <div className="label">Experience</div>
              <textarea 
                className="textarea" 
                rows={3} 
                placeholder="Tell us about your culinary background..."
                value={chefForm.experience} 
                onChange={e => setChefForm({ ...chefForm, experience: e.target.value })} 
              />
              
              <div className="label">Bio</div>
              <textarea 
                className="textarea" 
                rows={3} 
                placeholder="What makes your cooking special?"
                value={chefForm.bio} 
                onChange={e => setChefForm({ ...chefForm, bio: e.target.value })} 
              />
              
              <div className="label">Serving areas</div>
              <p className="muted" style={{ fontSize: '0.85em', marginBottom: '0.5rem' }}>
                Select areas where you can serve customers.
              </p>
              <ServiceAreaPicker
                country={(user?.address?.country || '').toUpperCase()}
                selectedAreas={chefForm.selected_areas || []}
                onChange={(areas) => setChefForm({ ...chefForm, selected_areas: areas })}
                maxHeight="350px"
              />
              
              <div className="label">Profile picture (optional)</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '.5rem', flexWrap: 'wrap' }}>
                <input
                  id="homeProfilePic"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  style={{ display: 'none' }}
                  onChange={e => setChefForm({ ...chefForm, profile_pic: e.target.files?.[0] || null })}
                />
                <label htmlFor="homeProfilePic" className="btn btn-outline btn-sm" style={{ cursor: 'pointer' }}>Choose file</label>
                {chefForm.profile_pic && (
                  <>
                    <span className="muted">{chefForm.profile_pic.name}</span>
                    <button
                      type="button"
                      className="file-clear-btn"
                      onClick={() => {
                        setChefForm({ ...chefForm, profile_pic: null })
                        const input = document.getElementById('homeProfilePic')
                        if (input) input.value = ''
                      }}
                      aria-label="Remove file"
                      title="Remove file"
                    >
                      ×
                    </button>
                  </>
                )}
              </div>
              
              <div className="actions-row" style={{ marginTop: '.75rem' }}>
                <button 
                  className="btn btn-primary" 
                  disabled={submitting} 
                  onClick={handleChefApplication}
                >
                  {submitting ? 'Submitting...' : 'Submit Application'}
                </button>
                <button className="btn btn-outline" onClick={() => setApplyOpen(false)}>
                  Cancel
                </button>
              </div>
            </div>
          </aside>
        </>
      )}
    </div>
  )
}
