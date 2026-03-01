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
                This food is prepared in a <strong>home kitchen</strong> that is inspected and
                permitted by the local environmental health agency. It is <strong>not a commercial
                restaurant</strong>.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                This food facility is a microenterprise home kitchen operation that is{' '}
                <strong>not subject to the same food safety regulations as a commercial restaurant</strong>.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                This MEHKO permit is <strong>non-transferable</strong> and is valid only for the
                permitted chef at their registered home address.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                Orders are for <strong>same-day service only</strong>. Food is prepared and served
                the same day per California law.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                Delivery is by the chef directly. <strong>Third-party delivery services are not
                permitted</strong>, except as a reasonable accommodation for a disability.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                You have the right to view the chef's permit and most recent inspection report
                upon request.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                A <strong>platform service fee</strong> is added to the chef's listed price at
                checkout and is disclosed before payment.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                Daily and weekly meal limits apply as required by California Health and Safety Code.
              </span>
            </li>
            <li>
              <i className="fa-solid fa-check-circle"></i>
              <span>
                You may file a food safety complaint through this platform or directly with the
                local enforcement agency at any time.
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
