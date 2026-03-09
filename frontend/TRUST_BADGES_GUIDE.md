# Trust Badges Guide

This document explains what each trust badge means on chef profiles and when they appear.

---

## 🛡️ Platform Verified

**What it means:**
- Chef has completed account registration with verified email
- Account is active and in good standing
- Basic profile requirements are met
- Has agreed to platform Terms of Service
- Not suspended or flagged

**When it shows:**
```javascript
chef?.user?.is_email_verified || chef?.is_verified || chef?.user?.is_active
```

**Backend fields to check:**
- `user.is_email_verified` - Email has been verified
- `chef.is_verified` - Chef profile is verified by admin
- `user.is_active` - Account is active (not suspended)

**Visual:** Standard trust badge (white/transparent background)

---

## 🎓 Background Checked

**What it means:**
- Chef has passed identity verification
- Background check completed (criminal record, references)
- Food safety certifications verified
- Employment history confirmed

**When it shows:**
```javascript
chef?.background_checked
```

**Backend field:**
- `chef.background_checked` (boolean)

**Visual:** Green "verified" badge with special highlighting

**Note:** This is a premium trust indicator. Consider requiring:
- Government-issued ID verification
- Food handler's certificate
- Professional references
- Clean background check report

---

## 🛡️ Insured & Licensed

**What it means:**
- Chef has valid liability insurance
- Business license (if required in their area)
- Food service permits up to date
- Insurance covers customer property and food safety

**When it shows:**
```javascript
chef?.insured
```

**Backend fields to track:**
- `chef.insured` (boolean)
- `chef.insurance_provider` (string, optional)
- `chef.insurance_expiry` (date, optional)
- `chef.license_number` (string, optional)
- `chef.license_documents` (file uploads, optional)

**Visual:** Green "verified" badge with special highlighting

**Recommended requirements:**
- General liability insurance ($1M-$2M coverage)
- Proof of business license (if operating as business)
- Food handler's certificate
- Documents uploaded and reviewed by admin

---

## 🔒 Secure Payments

**What it means:**
- All payments processed through Stripe
- PCI-compliant payment handling
- Customer payment data never stored on platform
- Secure checkout process
- Fraud protection enabled

**When it shows:**
```javascript
Always displayed (since all payments use Stripe)
```

**Visual:** Standard trust badge (white/transparent background)

**Note:** This badge is always shown because your entire platform uses Stripe for secure payments.

---

## Badge Display Logic

### All Possible Scenarios:

1. **New Chef (Just Registered)**
   - Shows: Secure Payments
   - Missing: Platform Verified (until email verified)

2. **Basic Verified Chef**
   - Shows: Platform Verified, Secure Payments
   - Missing: Background Checked, Insured

3. **Background Checked Chef**
   - Shows: Platform Verified, Background Checked, Secure Payments
   - Missing: Insured

4. **Fully Verified Chef**
   - Shows: All 4 badges
   - This is the gold standard for trust

### Recommended Badge Hierarchy:

```
Tier 1 (Free): Platform Verified + Secure Payments
Tier 2 ($): Background Checked
Tier 3 ($$): Insured & Licensed
```

---

## Backend Implementation Checklist

### Database Fields Needed:

```python
# In your Chef model
class Chef(models.Model):
    # Platform Verification
    is_verified = models.BooleanField(default=False)  # Admin approved
    verified_at = models.DateTimeField(null=True, blank=True)
    
    # Background Check
    background_checked = models.BooleanField(default=False)
    background_check_date = models.DateField(null=True, blank=True)
    background_check_provider = models.CharField(max_length=100, blank=True)
    
    # Insurance & Licensing
    insured = models.BooleanField(default=False)
    insurance_provider = models.CharField(max_length=200, blank=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)
    insurance_document = models.FileField(upload_to='chef_insurance/', null=True, blank=True)
    
    business_license = models.CharField(max_length=100, blank=True)
    license_state = models.CharField(max_length=50, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    license_document = models.FileField(upload_to='chef_licenses/', null=True, blank=True)
    
    # Food Safety
    food_handlers_cert = models.BooleanField(default=False)
    food_handlers_cert_expiry = models.DateField(null=True, blank=True)
    food_handlers_cert_document = models.FileField(upload_to='food_certs/', null=True, blank=True)
```

### API Endpoints Needed:

```python
# GET /chefs/api/public/{chef_id}/
# Returns chef with verification status

# POST /chefs/api/verification/submit-documents/
# Chef uploads insurance/license documents

# POST /admin/chefs/api/{chef_id}/verify-background/
# Admin marks background check as complete

# POST /admin/chefs/api/{chef_id}/approve-insurance/
# Admin approves insurance documentation
```

---

## Admin Verification Workflow

### 1. Platform Verification (Automatic)
```
✅ User registers
✅ Email verification link sent
✅ User clicks verification link
✅ is_email_verified = True
→ "Platform Verified" badge appears
```

### 2. Background Check (Manual/Service)
```
Chef submits:
- ID scan
- Social Security Number (encrypted)
- References

Admin:
- Reviews submission
- Orders background check (Checkr, etc.)
- Receives report
- Marks background_checked = True

→ "Background Checked" badge appears
```

### 3. Insurance & License (Document Review)
```
Chef uploads:
- Insurance certificate
- Business license
- Food handler's certificate

Admin:
- Verifies documents are legitimate
- Checks expiry dates
- Confirms coverage amounts
- Marks insured = True

→ "Insured & Licensed" badge appears
```

---

## Stripe Audit Implications

For Stripe compliance, you should:

1. ✅ **Always show "Secure Payments"** - Demonstrates PCI compliance
2. ✅ **Require "Platform Verified"** - Shows basic vetting
3. ⚠️ **Optional but recommended: Background Checked** - Higher trust
4. ⚠️ **Optional but recommended: Insurance** - Risk mitigation

**Minimum for Stripe:** Platform Verified + Secure Payments  
**Ideal for Stripe:** All 4 badges (shows serious platform)

---

## User-Facing Explanations

When customers click/hover on badges, show:

### Platform Verified
```
"✓ Email verified
✓ Account in good standing
✓ Profile meets quality standards
✓ Agrees to platform policies"
```

### Background Checked
```
"✓ Identity verified
✓ Background check passed
✓ References confirmed
✓ Food safety certified"
```

### Insured & Licensed
```
"✓ Liability insurance active
✓ Business licensed
✓ Coverage: $1M+
✓ Verified by sautai"
```

### Secure Payments
```
"✓ Powered by Stripe
✓ Bank-level encryption
✓ PCI compliant
✓ Fraud protection enabled"
```

---

## Testing Badge Display

### Test 1: New Unverified Chef
```javascript
const chef = {
  user: { is_email_verified: false, is_active: true }
}
// Expected: Only "Secure Payments"
```

### Test 2: Email Verified Chef
```javascript
const chef = {
  user: { is_email_verified: true, is_active: true }
}
// Expected: "Platform Verified" + "Secure Payments"
```

### Test 3: Fully Verified Chef
```javascript
const chef = {
  user: { is_email_verified: true, is_active: true },
  background_checked: true,
  insured: true
}
// Expected: All 4 badges
```

---

## Recommendations

1. **Implement email verification first** - Easy win for "Platform Verified"

2. **Add verification status to Chef model** - Track what's been verified

3. **Create admin verification UI** - Let admins approve/reject documents

4. **Add document upload to chef onboarding** - Streamline verification process

5. **Send expiry reminders** - Alert chefs when insurance/licenses expire

6. **Consider verification tiers:**
   - Free: Platform Verified only
   - Premium ($50/year): Add Background Check
   - Pro ($150/year): All verifications

---

## Summary

**Current Implementation:**
- ✅ Visual badges in place
- ✅ Conditional rendering based on data
- ✅ Responsive design
- ⚠️ Need backend fields to track verification status

**Next Steps:**
1. Add database fields for verification tracking
2. Implement email verification (if not already)
3. Create document upload flow for chefs
4. Build admin verification dashboard
5. Add expiry tracking for time-sensitive credentials

**For Stripe Audit:**
- Minimum viable: Show "Platform Verified" for email-verified chefs
- Ideal: Implement background checks for high-value bookings



