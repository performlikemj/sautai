import React, { useEffect, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { getRandomChefEmoji, getSeededChefEmoji } from '../utils/emojis.js'

/**
 * MyChefs - Client Portal chef list page
 *
 * Shows all connected chefs for the customer, ordered by recent activity.
 * Implements smart redirect: single-chef users skip straight to ChefHub.
 */
export default function MyChefs() {
  const navigate = useNavigate()
  const {
    connectedChefs,
    connectedChefsLoading,
    hasChefConnection,
    singleChef,
    hasChefAccess,
    user
  } = useAuth()

  // Random chef emoji for empty state
  const emptyStateEmoji = useMemo(() => getRandomChefEmoji(), [])

  // Smart redirect: single chef -> skip list, go to hub
  useEffect(() => {
    if (!connectedChefsLoading && singleChef) {
      navigate(`/my-chefs/${singleChef.id}`, { replace: true })
    }
  }, [connectedChefsLoading, singleChef, navigate])

  // Loading state
  if (connectedChefsLoading) {
    return (
      <div className="page-my-chefs">
        <div className="my-chefs-loading">
          <div className="spinner" style={{width: 40, height: 40, borderWidth: 4}} />
          <p>Loading your chefs...</p>
        </div>
      </div>
    )
  }

  // No chefs connected
  if (!hasChefConnection) {
    return (
      <div className="page-my-chefs">
        <div className="my-chefs-empty">
          <div className="empty-illustration">{emptyStateEmoji}</div>
          <h2>No Chefs Connected Yet</h2>
          <p className="empty-description">
            Browse our directory to find personal chefs in your area and start building your culinary team.
          </p>
          {hasChefAccess ? (
            <Link to="/chefs" className="btn btn-primary btn-lg">
              Find a Chef
              <i className="fa-solid fa-arrow-right" style={{marginLeft:'.5rem',fontSize:'.85rem'}}></i>
            </Link>
          ) : (
            <Link to="/get-ready" className="btn btn-primary btn-lg">
              Get Started
              <i className="fa-solid fa-arrow-right" style={{marginLeft:'.5rem',fontSize:'.85rem'}}></i>
            </Link>
          )}
        </div>
      </div>
    )
  }

  // Multiple chefs - show grid
  return (
    <div className="page-my-chefs">
      {/* Header */}
      <header className="my-chefs-hero">
        <div className="my-chefs-hero-content">
          <div className="my-chefs-title-row">
            <h1 className="my-chefs-title">My Chefs</h1>
            <span className="my-chefs-count-badge">{connectedChefs.length} {connectedChefs.length === 1 ? 'chef' : 'chefs'}</span>
          </div>
          <p className="my-chefs-subtitle">
            Your personal chef connections
          </p>
        </div>
      </header>

      {/* Chef Grid */}
      <div className="my-chefs-content">
        <div className="my-chefs-grid">
          {connectedChefs.map(chef => (
            <ChefCard key={chef.id} chef={chef} />
          ))}
        </div>

        {/* Empty State Section (shown below grid as design reference) */}

        {/* Footer Action */}
        <div className="my-chefs-footer">
          <Link to="/chefs" className="btn btn-outline btn-lg my-chefs-browse-btn">
            Browse More Chefs
          </Link>
        </div>
      </div>
    </div>
  )
}

/**
 * Chef card component — horizontal card in a grid
 */
function ChefCard({ chef }) {
  const formatLastActivity = (dateStr) => {
    if (!dateStr) return 'No activity yet'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now - date
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))

    if (diffHours < 1) return 'Just now'
    if (diffHours < 24) return `${diffHours} hours ago`
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays} days ago`
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`
    return `${Math.floor(diffDays / 30)} months ago`
  }

  return (
    <Link to={`/my-chefs/${chef.id}`} className="my-chef-card">
      <div className="my-chef-card-left">
        <div className="my-chef-avatar">
          {chef.photo ? (
            <img src={chef.photo} alt={chef.display_name} className="my-chef-photo" />
          ) : (
            <div className="my-chef-photo-placeholder">
              {getSeededChefEmoji(chef.id)}
            </div>
          )}
          <div className="my-chef-status">
            <i className="fa-solid fa-check"></i>
          </div>
        </div>

        <div className="my-chef-info">
          <span className="my-chef-name">{chef.display_name}</span>
          {chef.specialty && (
            <span className="my-chef-specialty">{chef.specialty}</span>
          )}
          <div className="my-chef-rating">
            <i className="fa-solid fa-star my-chef-star"></i>
            <span className="my-chef-rating-value">{chef.rating ? chef.rating.toFixed(1) : '—'}</span>
            {chef.review_count != null && (
              <span className="my-chef-rating-count">({chef.review_count})</span>
            )}
          </div>
        </div>
      </div>

      <div className="my-chef-card-right">
        <i className="fa-solid fa-chevron-right my-chef-arrow"></i>
        <span className="my-chef-activity">Active {formatLastActivity(chef.last_activity)}</span>
      </div>
    </Link>
  )
}
