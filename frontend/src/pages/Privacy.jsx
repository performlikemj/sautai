import React from 'react'

export default function Privacy() {
  return (
    <div className="policy-page">
      <div className="policy-header">
        <h1>Privacy Policy — sautai</h1>
        <p className="muted">Last updated: 2026-03-09</p>
      </div>

      <div className="policy-content">
        <p>
          This Privacy Policy explains how sautai collects, uses, shares, and protects your information. 
          By using the platform, you agree to these practices. We collect account details, contact 
          information, payment data (processed by Stripe), dietary preferences, and usage data for 
          service delivery and improvement. We never sell personal data and use industry-standard 
          protections like HTTPS and encryption.
        </p>

        <h2>1. Information We Collect</h2>
        
        <h3>Information You Provide</h3>
        <ul>
          <li><strong>Account Information:</strong> Name, email, phone number, password</li>
          <li><strong>Profile Details:</strong> Dietary preferences, allergies, household size, location/postal code</li>
          <li><strong>Booking Information:</strong> Service addresses, special requests, scheduling preferences</li>
          <li><strong>Payment Information:</strong> Credit card details (securely processed through Stripe - we never store full card numbers)</li>
          <li><strong>Communications:</strong> Messages with chefs, reviews, support inquiries</li>
          <li><strong>Chef Information:</strong> For chefs: business details, certifications, photos, menus, service areas</li>
        </ul>

        <h3>Information We Collect Automatically</h3>
        <ul>
          <li><strong>Usage Data:</strong> Pages viewed, features used, search queries, click patterns</li>
          <li><strong>Device Information:</strong> Browser type, operating system, IP address, device identifiers</li>
          <li><strong>Location Data:</strong> Approximate location from IP address (we only collect precise location with your permission)</li>
          <li><strong>Cookies:</strong> Session data, preferences, authentication tokens</li>
        </ul>

        <h2>2. How We Use Your Information</h2>
        <ul>
          <li><strong>Service Delivery:</strong> Connect you with chefs, process bookings, facilitate communication</li>
          <li><strong>Payment Processing:</strong> Process payments securely through Stripe</li>
          <li><strong>Personalization:</strong> Recommend chefs and services based on preferences and location</li>
          <li><strong>Communication:</strong> Send booking confirmations, updates, notifications, and promotional emails (you can opt out)</li>
          <li><strong>Safety & Security:</strong> Verify identities, prevent fraud, enforce Terms of Service</li>
          <li><strong>Improvement:</strong> Analyze usage patterns to improve features and user experience</li>
          <li><strong>Legal Compliance:</strong> Comply with legal obligations, respond to legal requests</li>
        </ul>

        <h2>3. How We Share Your Information</h2>
        
        <h3>With Chefs</h3>
        <p>
          When you book a service, we share necessary information with your chosen chef: your name, 
          contact details, service address, dietary restrictions, and booking details. This enables 
          them to provide the service you requested.
        </p>

        <h3>With Service Providers</h3>
        <ul>
          <li><strong>Stripe:</strong> Payment processing (see <a href="https://stripe.com/privacy" target="_blank" rel="noopener noreferrer">Stripe's Privacy Policy</a>)</li>
          <li><strong>Cloud Hosting:</strong> Secure data storage and platform hosting</li>
          <li><strong>Email Services:</strong> Transactional and marketing emails</li>
          <li><strong>Analytics:</strong> Usage analytics and platform monitoring</li>
        </ul>
        <p>
          These providers are contractually obligated to protect your data and only use it for 
          services provided to sautai.
        </p>

        <h3>For Legal Reasons</h3>
        <p>We may disclose information when required by law, to:</p>
        <ul>
          <li>Comply with legal processes (subpoenas, court orders)</li>
          <li>Protect rights, property, or safety of sautai, users, or the public</li>
          <li>Detect, prevent, or investigate fraud or security issues</li>
          <li>Enforce our Terms of Service</li>
        </ul>

        <h3>Business Transfers</h3>
        <p>
          If sautai is acquired, merged, or sells assets, your information may be transferred to 
          the new entity. We will notify you of any such change.
        </p>

        <h3>We Never Sell Your Data</h3>
        <p>
          We do not sell, rent, or trade your personal information to third parties for their 
          marketing purposes.
        </p>

        <h2>4. Data Security</h2>
        <p>We protect your information using:</p>
        <ul>
          <li><strong>Encryption:</strong> HTTPS/TLS encryption for data in transit</li>
          <li><strong>Secure Storage:</strong> Encrypted databases with restricted access</li>
          <li><strong>Access Controls:</strong> Limited employee access on a need-to-know basis</li>
          <li><strong>Security Monitoring:</strong> Regular security audits and vulnerability assessments</li>
          <li><strong>PCI Compliance:</strong> Stripe handles payment data in PCI-compliant manner</li>
        </ul>
        <p>
          While we implement strong security measures, no system is 100% secure. You're responsible 
          for keeping your password confidential.
        </p>

        <h2>5. Your Privacy Rights</h2>
        
        <h3>Access & Correction</h3>
        <p>You can access and update your account information anytime through your profile settings.</p>

        <h3>Data Deletion</h3>
        <p>
          You can request deletion of your account and personal data by contacting support@sautai.com. 
          We'll delete your data within 30 days, except where we're legally required to retain it 
          (e.g., tax records, dispute resolution).
        </p>

        <h3>Data Export</h3>
        <p>
          You can request a copy of your data in a portable format by contacting support@sautai.com.
        </p>

        <h3>Marketing Opt-Out</h3>
        <p>
          You can unsubscribe from marketing emails using the link in any promotional email. You'll 
          still receive essential transactional emails (booking confirmations, account notifications).
        </p>

        <h3>Cookie Management</h3>
        <p>
          You can control cookies through your browser settings. Note that disabling cookies may 
          limit platform functionality.
        </p>

        <h3>Do Not Track</h3>
        <p>
          We currently don't respond to Do Not Track signals, as there's no industry standard for 
          compliance.
        </p>

        <h2>6. Data Retention</h2>
        <p>We retain your information:</p>
        <ul>
          <li><strong>Account Data:</strong> Until you delete your account, plus 30 days</li>
          <li><strong>Booking Records:</strong> 7 years for tax and legal compliance</li>
          <li><strong>Payment Data:</strong> Stripe retains according to their policies and PCI requirements</li>
          <li><strong>Communications:</strong> Until no longer needed for support or dispute resolution</li>
          <li><strong>Analytics:</strong> Aggregated/anonymized data indefinitely</li>
        </ul>

        <h2>7. Children's Privacy</h2>
        <p>
          The platform is not intended for children under 18. We don't knowingly collect information 
          from children. If we discover we've collected a child's information, we'll delete it promptly.
        </p>

        <h2>8. International Users</h2>
        <p>
          If you're outside the United States, your information may be transferred to and processed 
          in the U.S. By using the platform, you consent to this transfer. We comply with applicable 
          data protection laws, including GDPR where applicable.
        </p>

        <h2>9. California Privacy Rights (CCPA)</h2>
        <p>California residents have additional rights:</p>
        <ul>
          <li><strong>Right to Know:</strong> Request details about data we collect, use, and share</li>
          <li><strong>Right to Delete:</strong> Request deletion of personal information</li>
          <li><strong>Right to Opt-Out:</strong> Opt out of data "sales" (we don't sell data)</li>
          <li><strong>Non-Discrimination:</strong> We won't discriminate for exercising these rights</li>
        </ul>
        <p>To exercise these rights, contact support@sautai.com with "California Privacy Request" in the subject.</p>

        <h2>10. Changes to This Policy</h2>
        <p>
          We may update this Privacy Policy periodically. Material changes will be posted with an 
          updated "Last updated" date. Continued use after changes constitutes acceptance.
        </p>

        <h2>11. Contact Us</h2>
        <p>For privacy questions or to exercise your rights:</p>
        <ul>
          <li><strong>Email:</strong> privacy@sautai.com</li>
          <li><strong>General Support:</strong> support@sautai.com</li>
        </ul>

        <div className="policy-footer">
          <p>
            <strong>For privacy inquiries, contact: support@sautai.com</strong>
          </p>
        </div>
      </div>
    </div>
  )
}


