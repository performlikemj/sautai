import React from 'react'

export default function MehkoComplianceSection({ chef, onFileComplaint }) {
  if (!chef?.mehko_active) return null

  const permitNumber = chef.permit_number || 'N/A'
  const permitExpiry = chef.permit_expiry || null
  const permittingAgency = chef.permitting_agency || 'Local Health Department'
  const enforcementAgency = chef.enforcement_agency || null
  const complaintCount = chef.complaint_count ?? null

  return (
    <div className="mehko-compliance-section">
      <div>
        <h2 className="chef-section-title" style={{ marginBottom: '.35rem' }}>
          <i className="fa-solid fa-house-chimney"></i>
          Home Kitchen Operation
        </h2>
        <p className="chef-section-subtitle">
          This chef operates under California's MEHKO (Microenterprise Home Kitchen Operation) permit.
        </p>
      </div>

      <div className="mehko-details-grid">
        <div className="mehko-detail-item">
          <i className="fa-solid fa-id-card"></i>
          <div>
            <div className="mehko-detail-label">Permit Number</div>
            <div className="mehko-detail-value">{permitNumber}</div>
          </div>
        </div>

        <div className="mehko-detail-item">
          <i className="fa-solid fa-building-columns"></i>
          <div>
            <div className="mehko-detail-label">Permitting Agency</div>
            <div className="mehko-detail-value">{permittingAgency}</div>
          </div>
        </div>

        {permitExpiry && (
          <div className="mehko-detail-item">
            <i className="fa-solid fa-calendar-check"></i>
            <div>
              <div className="mehko-detail-label">Valid Until</div>
              <div className="mehko-detail-value">{permitExpiry}</div>
            </div>
          </div>
        )}

        {complaintCount != null && (
          <div className="mehko-detail-item">
            <i className="fa-solid fa-clipboard-list"></i>
            <div>
              <div className="mehko-detail-label">Complaints on File</div>
              <div className="mehko-detail-value">{complaintCount}</div>
            </div>
          </div>
        )}
      </div>

      <div className="mehko-actions">
        {enforcementAgency && (
          <a
            href={`https://www.google.com/search?q=${encodeURIComponent(enforcementAgency + ' food safety')}`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline"
          >
            <i className="fa-solid fa-building-columns" style={{ marginRight: '.4rem' }}></i>
            Contact Enforcement Agency
          </a>
        )}
        <button className="btn btn-outline" onClick={onFileComplaint}>
          <i className="fa-solid fa-file-pen" style={{ marginRight: '.4rem' }}></i>
          File a Food Safety Concern
        </button>
      </div>
    </div>
  )
}
