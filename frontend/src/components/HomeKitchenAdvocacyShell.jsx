import React from 'react'

export default function HomeKitchenAdvocacyShell({ hasAddress, state, onNavigate }) {
  return (
    <div className="mehko-enrollment-panel">
      {/* No-address notice */}
      {!hasAddress && (
        <div className="mehko-status-banner incomplete">
          <i className="fa-solid fa-location-dot"></i>
          <div>
            <strong>Address not set</strong>
            <p>
              Add your address in your{' '}
              <button className="btn-link" onClick={() => onNavigate?.('profile')}>
                Profile
              </button>{' '}
              so we can show you home kitchen information for your state.
            </p>
          </div>
        </div>
      )}

      {/* What is a Home Kitchen Operation? */}
      <div className="mehko-explainer">
        <h3><i className="fa-solid fa-circle-info"></i> What is a Home Kitchen Operation?</h3>
        <p>
          Home kitchen laws allow home cooks to legally prepare and sell meals directly from their
          home kitchens. California pioneered this with <strong>MEHKO (Microenterprise Home Kitchen
          Operations)</strong> under AB 626, and advocacy efforts are underway to bring similar
          laws to other states.
        </p>
        <p style={{ marginTop: '.5rem', fontSize: '.88rem', color: 'var(--muted)' }}>
          When your state passes home kitchen legislation, you'll be able to enroll directly
          through Sautai.
        </p>
      </div>

      {/* Not yet available banner */}
      {hasAddress && (
        <div className="mehko-status-banner pending">
          <i className="fa-solid fa-map-location-dot"></i>
          <div>
            <strong>Not yet available in {state}</strong>
            <p>
              Home kitchen operation laws have not yet been enacted in your state. We're tracking
              legislative progress and will notify you when this changes.
            </p>
          </div>
        </div>
      )}

      {/* Advocacy section */}
      <div className="hk-advocacy-section">
        <h3><i className="fa-solid fa-bullhorn"></i> Bring Home Kitchen Laws to Your State</h3>
        <p style={{ color: 'var(--muted)', margin: '0 0 1rem 0' }}>
          Help expand legal home cooking in your community.
        </p>
        <div className="hk-advocacy-actions">
          <div className="hk-advocacy-card">
            <i className="fa-solid fa-handshake-angle"></i>
            <strong>Get Involved</strong>
            <p>
              Volunteer with the Cook Alliance to help advocate for home cooking legalization in
              your state. Sign up to connect with local organizers and coalition efforts.
            </p>
            <a
              href="https://www.cookalliance.org/volunteer"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-outline"
              style={{ marginTop: '.75rem' }}
            >
              Volunteer with Cook Alliance
            </a>
          </div>
          <div className="hk-advocacy-card">
            <i className="fa-solid fa-bullhorn"></i>
            <strong>Spread the Word</strong>
            <p>
              Share the Cook Alliance's mission with your community. Learn how home kitchen laws
              are changing the food landscape across the country.
            </p>
            <a
              href="https://www.cookalliance.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-outline"
              style={{ marginTop: '.75rem' }}
            >
              Visit Cook Alliance
            </a>
          </div>
        </div>
      </div>

      {/* Cook Alliance link */}
      <div className="mehko-explainer" style={{ textAlign: 'center' }}>
        <p>
          <i className="fa-solid fa-utensils" style={{ marginRight: '.5rem' }}></i>
          Learn more at the{' '}
          <a href="https://www.cookalliance.org/" target="_blank" rel="noopener noreferrer">
            Cook Alliance
          </a>{' '}
          — the leading organization advocating for home cooking legalization across the U.S.
        </p>
      </div>

      {/* Stay Updated teaser */}
      <div className="hk-notify-section">
        <i className="fa-solid fa-bell"></i>
        <div>
          <strong>Stay Updated</strong>
          <p>
            We'll let you know when home kitchen laws are introduced or passed in your state.
            Notification preferences coming soon.
          </p>
        </div>
      </div>
    </div>
  )
}
