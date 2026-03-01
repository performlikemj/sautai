"""Tests for MEHKO/IFSI compliance models (Phase 1)."""
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from chefs.models import Chef, ChefVerificationDocument, MehkoComplaint

User = get_user_model()


class ChefMehkoFieldsTest(TestCase):
    """Test MEHKO fields on Chef model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testchef", email="chef@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(
            user=self.user,
            experience="5 years home cooking",
            bio="Test chef",
        )

    def test_mehko_fields_default_blank(self):
        """New chefs should have blank MEHKO fields."""
        self.assertEqual(self.chef.permit_number, "")
        self.assertEqual(self.chef.permitting_agency, "")
        self.assertIsNone(self.chef.permit_expiry)
        self.assertEqual(self.chef.county, "")
        self.assertFalse(self.chef.mehko_consent)
        self.assertFalse(self.chef.mehko_active)

    def test_mehko_fields_save_and_retrieve(self):
        """MEHKO fields should persist correctly."""
        self.chef.permit_number = "MEHKO-2026-001"
        self.chef.permitting_agency = "Alameda County DEH"
        self.chef.permit_expiry = timezone.now().date() + timedelta(days=365)
        self.chef.county = "Alameda"
        self.chef.mehko_consent = True
        self.chef.mehko_active = True
        self.chef.save()

        chef = Chef.objects.get(pk=self.chef.pk)
        self.assertEqual(chef.permit_number, "MEHKO-2026-001")
        self.assertEqual(chef.permitting_agency, "Alameda County DEH")
        self.assertEqual(chef.county, "Alameda")
        self.assertTrue(chef.mehko_consent)
        self.assertTrue(chef.mehko_active)

    def test_mehko_active_independent_of_other_fields(self):
        """mehko_active is a manual flag, not auto-computed (for Phase 1)."""
        # Can be set True even without permit — enforcement is Phase 2
        self.chef.mehko_active = True
        self.chef.save()
        self.assertTrue(Chef.objects.get(pk=self.chef.pk).mehko_active)


class ChefVerificationDocumentPermitTest(TestCase):
    """Test permit doc type on ChefVerificationDocument."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testchef2", email="chef2@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.user)

    def test_permit_doc_type_allowed(self):
        """Should accept 'permit' as a valid doc_type."""
        doc = ChefVerificationDocument.objects.create(
            chef=self.chef,
            doc_type="permit",
            file="chefs/verification_docs/test_permit.pdf",
        )
        self.assertEqual(doc.doc_type, "permit")
        self.assertEqual(doc.get_doc_type_display(), "MEHKO Permit")


class MehkoComplaintTest(TestCase):
    """Test MehkoComplaint model."""

    def setUp(self):
        self.chef_user = User.objects.create_user(
            username="complainchef", email="cc@test.com", password="testpass123"
        )
        self.chef = Chef.objects.create(user=self.chef_user)
        self.customer = User.objects.create_user(
            username="customer1", email="c1@test.com", password="testpass123"
        )

    def test_create_complaint(self):
        """Basic complaint creation."""
        complaint = MehkoComplaint.objects.create(
            chef=self.chef,
            complainant=self.customer,
            complaint_text="Food was not prepared same day as stated.",
        )
        self.assertEqual(complaint.chef, self.chef)
        self.assertEqual(complaint.complainant, self.customer)
        self.assertFalse(complaint.is_significant)
        self.assertFalse(complaint.reported_to_agency)
        self.assertFalse(complaint.resolved)
        self.assertIsNotNone(complaint.submitted_at)

    def test_anonymous_complaint(self):
        """Complaints can be filed without a logged-in user."""
        complaint = MehkoComplaint.objects.create(
            chef=self.chef,
            complainant=None,
            complaint_text="Observed unsanitary conditions.",
        )
        self.assertIsNone(complaint.complainant)

    def test_complaints_in_window(self):
        """Count complaints in a rolling 12-month window."""
        # Create 3 recent complaints
        for i in range(3):
            MehkoComplaint.objects.create(
                chef=self.chef,
                complaint_text=f"Complaint {i+1}",
            )

        # Create 1 old complaint (13 months ago)
        old = MehkoComplaint.objects.create(
            chef=self.chef,
            complaint_text="Old complaint",
        )
        MehkoComplaint.objects.filter(pk=old.pk).update(
            submitted_at=timezone.now() - timedelta(days=400)
        )

        self.assertEqual(MehkoComplaint.complaints_in_window(self.chef), 3)

    def test_threshold_not_reached(self):
        """Below 3 complaints should not trigger threshold."""
        MehkoComplaint.objects.create(
            chef=self.chef, complaint_text="Complaint 1"
        )
        MehkoComplaint.objects.create(
            chef=self.chef, complaint_text="Complaint 2"
        )
        self.assertFalse(MehkoComplaint.threshold_reached(self.chef))

    def test_threshold_reached(self):
        """3+ distinct complainants in calendar year should trigger threshold."""
        for i in range(3):
            user = User.objects.create_user(
                username=f"comp_thr{i}", email=f"thr{i}@test.com", password="testpass123"
            )
            MehkoComplaint.objects.create(
                chef=self.chef, complainant=user, complaint_text=f"Complaint {i+1}"
            )
        self.assertTrue(MehkoComplaint.threshold_reached(self.chef))

    def test_str_representation(self):
        """String representation should be readable."""
        complaint = MehkoComplaint.objects.create(
            chef=self.chef, complaint_text="Test"
        )
        self.assertIn("MehkoComplaint", str(complaint))
        self.assertIn(str(self.chef.pk), str(complaint))

    def test_ordering(self):
        """Complaints should be ordered newest first."""
        c1 = MehkoComplaint.objects.create(
            chef=self.chef, complaint_text="First"
        )
        c2 = MehkoComplaint.objects.create(
            chef=self.chef, complaint_text="Second"
        )
        complaints = list(MehkoComplaint.objects.filter(chef=self.chef))
        self.assertEqual(complaints[0].pk, c2.pk)
        self.assertEqual(complaints[1].pk, c1.pk)
