import React from 'react'

export default function RefundPolicy() {
  return (
    <div className="policy-page">
      <div className="policy-header">
        <h1>Refund Policy — sautai</h1>
        <p className="muted">Last updated: 2026-03-09</p>
      </div>

      <div className="policy-content">
        <p>
          We want every experience with sautai to be great. Because services reserve a chef's time 
          and perishable ingredients depend on timing and status: This Policy applies to all bookings 
          and meal orders made through the platform.
        </p>

        <h2>Chef Services (in-home cooking & bulk meal prep)</h2>
        
        <h3>Cancellation by Client</h3>
        <div className="refund-tiers">
          <div className="refund-tier">
            <div className="refund-tier-header">
              <strong>48+ hours before service start</strong>
              <span className="refund-badge full">Full Refund</span>
            </div>
            <p>Cancel anytime up to 48 hours before your scheduled service time for a complete refund.</p>
          </div>

          <div className="refund-tier">
            <div className="refund-tier-header">
              <strong>24-48 hours before start</strong>
              <span className="refund-badge partial">50% Refund</span>
            </div>
            <p>
              We understand plans change. Cancel between 24-48 hours before your service for a 50% refund. 
              The chef retains 50% to cover prep time and purchased ingredients.
            </p>
          </div>

          <div className="refund-tier">
            <div className="refund-tier-header">
              <strong>&lt;24 hours, no-show, or access not provided</strong>
              <span className="refund-badge none">No Refund</span>
            </div>
            <p>
              Cancellations within 24 hours of service, no-shows, or failure to provide kitchen access 
              forfeit the full payment. Chef has already prepared and purchased ingredients.
            </p>
          </div>
        </div>

        <h3>Service Issues</h3>
        <p>
          If there's a problem with your chef service (chef doesn't show up, quality issues, safety 
          concerns), contact <strong>support@sautai.com</strong> within 24 hours of the scheduled 
          service time. We'll work with you and the chef to resolve the issue, which may include:
        </p>
        <ul>
          <li>Full or partial refund</li>
          <li>Service credit for future booking</li>
          <li>Rescheduling with the same or different chef</li>
        </ul>
        <p>
          <strong>Important:</strong> Refund requests made more than 24 hours after the service time 
          cannot be guaranteed and will be reviewed case-by-case.
        </p>

        <h3>Cancellation by Chef</h3>
        <p>
          If a chef cancels your confirmed booking, you'll receive an immediate full refund and a 
          $25 service credit toward your next booking (if available within 30 days). We'll also help 
          you find an alternative chef if possible.
        </p>

        <h2>Meal Orders (delivery)</h2>

        <h3>Cancellation Before Prep Begins</h3>
        <div className="refund-tier">
          <div className="refund-tier-header">
            <strong>Before prep begins</strong>
            <span className="refund-badge full">Full Refund</span>
          </div>
          <p>
            Cancel your meal order before the chef begins preparation for a complete refund. 
            Order cutoff times are displayed on each meal event listing.
          </p>
        </div>

        <h3>After Prep Begins / Delivery Day</h3>
        <div className="refund-tier">
          <div className="refund-tier-header">
            <strong>After prep begins / delivery day</strong>
            <span className="refund-badge none">No Refund</span>
          </div>
          <p>
            Once a chef starts preparing your meal or on the day of delivery, the order cannot be 
            refunded. Perishable food has been purchased and prepared specifically for you.
          </p>
        </div>

        <h3>Meal Quality Issues</h3>
        <p>
          If you receive a meal with quality issues (wrong items, spoiled/unsafe food, doesn't match 
          description), contact support@sautai.com immediately with:
        </p>
        <ul>
          <li>Photos of the meal</li>
          <li>Description of the issue</li>
          <li>Your order number</li>
        </ul>
        <p>
          We'll review your case and may provide a full/partial refund, replacement meal, or service 
          credit. Claims must be submitted within 24 hours of delivery/pickup.
        </p>

        <h2>Dietary Restrictions & Allergies</h2>
        <p>
          <strong>Critical:</strong> You are responsible for clearly communicating all allergies and 
          dietary restrictions when booking. If you don't disclose allergies and a meal contains that 
          allergen, you are not eligible for a refund.
        </p>
        <p>
          If you properly disclosed allergies and the meal still contains restricted ingredients, 
          contact support immediately for a full refund. Your safety is our priority.
        </p>

        <h2>Recurring Services</h2>
        <p>
          For recurring/subscription services, you can cancel anytime. Cancellation takes effect 
          after your current billing period ends. No refunds for partial billing periods unless 
          there's a service issue.
        </p>

        <h2>Weather & Emergencies</h2>
        <p>
          In cases of severe weather, natural disasters, or emergencies that prevent service delivery:
        </p>
        <ul>
          <li><strong>Chef cancels:</strong> Full refund</li>
          <li><strong>Client cancels:</strong> Full refund if cancellation occurs before chef has purchased ingredients (typically 24-48 hours before)</li>
          <li><strong>Mutual agreement:</strong> Reschedule to a new date with no penalty</li>
        </ul>

        <h2>Disputes & Special Circumstances</h2>
        <p>
          For chef cancellations or major service issues, contact <strong>support@sautai.com</strong> within 
          24 hours. Include:
        </p>
        <ul>
          <li>Booking/order number</li>
          <li>Detailed description of the issue</li>
          <li>Photos (if applicable)</li>
          <li>Any communication with the chef</li>
        </ul>
        <p>
          We aim to respond within 1 business day. Refunds are processed to your original payment 
          method via Stripe within 5-10 business days.
        </p>

        <h2>Platform Fees</h2>
        <p>
          In most refund scenarios, platform fees are also refunded. In cases of repeated cancellations 
          or policy abuse, we reserve the right to retain service fees.
        </p>

        <h2>Refund Processing</h2>
        <p>
          All approved refunds are processed through Stripe to your original payment method. 
          Processing time:
        </p>
        <ul>
          <li><strong>Stripe processing:</strong> 5-10 business days</li>
          <li><strong>Bank/card processing:</strong> Additional 2-5 business days (varies by institution)</li>
        </ul>
        <p>
          You'll receive an email confirmation when a refund is issued. Check your bank statement 
          using the original transaction amount/date as reference.
        </p>

        <h2>Service Credits</h2>
        <p>
          In some cases, we may offer service credits instead of refunds. Credits:
        </p>
        <ul>
          <li>Are applied to your sautai account</li>
          <li>Can be used for any future booking</li>
          <li>Typically expire after 12 months</li>
          <li>Are non-transferable</li>
        </ul>

        <h2>Contact</h2>
        <p>
          For refund requests, cancellations, or questions about this policy:
        </p>
        <ul>
          <li><strong>Email:</strong> support@sautai.com</li>
          <li><strong>Response time:</strong> Within 24 hours (typically faster)</li>
          <li><strong>Phone:</strong> Available in your account settings for urgent issues</li>
        </ul>

        <div className="policy-footer">
          <p>
            <strong>For chef cancellations or major service issues, contact support@sautai.com within 24 hours.</strong>
          </p>
          <p>
            Refunds are processed to your original payment method via Stripe within 5-10 business days.
          </p>
        </div>
      </div>
    </div>
  )
}






