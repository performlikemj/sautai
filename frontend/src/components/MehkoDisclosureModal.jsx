import React from 'react'

export default function MehkoDisclosureModal({ isOpen, onClose, onAccept, loading }) {
  if (!isOpen) return null

  return (
    <>
      <div className="modal-overlay" onClick={onClose} />
      <div className="modal-container mehko-disclosure-modal">
        <div className="modal-header">
          <h2 className="modal-title">
            <i className="fa-solid fa-house-chimney" style={{ marginRight: '.5rem' }}></i>
            Home Kitchen Disclosure
          </h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            <i className="fa-solid fa-times"></i>
          </button>
        </div>

        <div className="modal-body">
          <p style={{ marginBottom: '0.5rem', color: 'var(--text)' }}>
            This chef operates a <strong>Microenterprise Home Kitchen Operation (MEHKO)</strong> under
            California law. Before placing an order, please review the following:
          </p>

          <ul className="mehko-disclosure-points">
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                This food is prepared in a home kitchen that is inspected and permitted by the local
                environmental health agency.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                This food facility is a cottage food operation or a microenterprise home kitchen
                operation that is not subject to the same food safety regulations as a commercial restaurant.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                You have the right to view the chef's permit and the most recent inspection report
                upon request.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                Daily and weekly meal limits may apply as required by California Health and Safety Code.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                You may file a food safety complaint with the local enforcement agency if you have concerns.
              </span>
            </li>
          </ul>

          <div className="form-actions" style={{ marginTop: '1.5rem' }}>
            <button
              className="btn btn-primary btn-lg"
              onClick={onAccept}
              disabled={loading}
              style={{ width: '100%' }}
            >
              {loading ? (
                <>
                  <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2, marginRight: '.5rem' }}></div>
                  Processing...
                </>
              ) : (
                'I Understand and Accept'
              )}
            </button>
            <button
              className="btn btn-outline"
              onClick={onClose}
              disabled={loading}
              style={{ width: '100%' }}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
