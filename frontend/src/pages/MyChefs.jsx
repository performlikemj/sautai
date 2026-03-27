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
            {hasChefAccess 
              ? 'Connect with a chef to get personalized meal plans and services.'
              : 'Chefs aren\'t available in your area yet, but you can get ready!'}
          </p>
          {hasChefAccess ? (
            <Link to="/chefs" className="btn btn-primary btn-lg">
              <i className="fa-solid fa-search"></i>
              Find a Chef
            </Link>
          ) : (
            <Link to="/get-ready" className="btn btn-primary btn-lg">
              <i className="fa-solid fa-rocket"></i>
              Get Started
            </Link>
          )}
        </div>
      </div>
    )
  }
  
  // Multiple chefs - show list
  return (
    <div className="page-my-chefs">
      {/* Header */}
      <header className="my-chefs-hero">
        <div className="my-chefs-hero-content">
          <h1 className="my-chefs-title">
            My Chefs
            <span className="my-chefs-count-badge">{connectedChefs.length} {connectedChefs.length === 1 ? 'chef' : 'chefs'}</span>
          </h1>
          <p className="my-chefs-subtitle">
            Your personal chef connections
          </p>
        </div>
      </header>
      
      {/* Chefs Grid */}
      <div className="my-chefs-content">
        <div className="my-chefs-list">
          {connectedChefs.map(chef => (
            <ChefCard key={chef.id} chef={chef} />
          ))}
        </div>
        
        <div className="my-chefs-footer">
          <Link to="/chefs" className="btn btn-outline btn-lg">
            Browse More Chefs
          </Link>
        </div>
      </div>
    </div>
  )
}

/**
 * Chef card component for the list view
 */
function ChefCard({ chef }) {
  const formatLastActivity = (dateStr) => {
    if (!dateStr) return 'No activity yet'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now - date
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    
    if (diffDays === 0) return 'Today'
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays} days ago`
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`
    return `${Math.floor(diffDays / 30)} months ago`
  }
  
  return (
    <Link to={`/my-chefs/${chef.id}`} className="my-chef-card">
      <div className="my-chef-card-header">
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
          <h3 className="my-chef-name">{chef.display_name}</h3>
          {chef.specialty && (
            <p className="my-chef-specialty">{chef.specialty}</p>
          )}
          {chef.rating && (
            <div className="my-chef-rating">
              <div className="stars">
                {[1,2,3,4,5].map(star => (
                  <i 
                    key={star}
                    className={`fa-solid fa-star ${star <= Math.round(chef.rating) ? 'filled' : 'empty'}`}
                  ></i>
                ))}
              </div>
              <span className="rating-value">{chef.rating.toFixed(1)}</span>
            </div>
          )}
        </div>
      </div>
      
      <div className="my-chef-meta">
        <span className="my-chef-activity">Active {formatLastActivity(chef.last_activity)}</span>
      </div>
      <div className="my-chef-arrow">
        <i className="fa-solid fa-chevron-right"></i>
      </div>
    </Link>
  )
}
