import React from 'react'

/**
 * Merged About + Experience section. Replaces PublicChef.jsx:1541-1564.
 *
 * The legacy version rendered each card independently in a chef-about-grid.
 * This component keeps the same two-card layout but in a single section
 * wrapper, and surfaces the AI sous-chef differentiator (existing
 * chef.sous_chef_emoji field) as a small inline badge — that data already
 * lives on the model but is currently invisible on the public page.
 *
 * No backend changes needed.
 */
export default function ChefAboutSection({ chef }) {
  if (!chef) return null
  if (!chef.experience && !chef.bio) return null

  const sousChefEmoji = chef.sous_chef_emoji || null

  return (
    <section className="chef-about-section-v2" aria-label="About this chef">
      <div className="chef-about-section-v2__grid">
        {chef.experience && (
          <article className="chef-about-section-v2__card">
            <div className="chef-about-section-v2__icon" aria-hidden>
              <i className="fa-solid fa-award"></i>
            </div>
            <h3 className="chef-about-section-v2__title">Experience</h3>
            <p className="chef-about-section-v2__text">{chef.experience}</p>
          </article>
        )}
        {chef.bio && (
          <article className="chef-about-section-v2__card">
            <div className="chef-about-section-v2__icon" aria-hidden>
              <i className="fa-solid fa-circle-info"></i>
            </div>
            <h3 className="chef-about-section-v2__title">About</h3>
            <p className="chef-about-section-v2__text">{chef.bio}</p>
            {sousChefEmoji && (
              <div
                className="chef-about-section-v2__sous-chef-badge"
                title="This chef uses sautai's AI sous chef to plan and personalize meals"
              >
                <span
                  className="chef-about-section-v2__sous-chef-emoji"
                  aria-hidden
                >
                  {sousChefEmoji}
                </span>
                <span>AI sous chef enabled</span>
              </div>
            )}
          </article>
        )}
      </div>
    </section>
  )
}
