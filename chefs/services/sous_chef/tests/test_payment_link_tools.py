# chefs/services/sous_chef/tests/test_payment_link_tools.py
"""
Tests for Sous Chef payment link tools.

Tests the 3 handler functions:
- _preview_payment_link
- _create_and_send_payment_link
- _check_payment_link_status
"""

import pytest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.utils import timezone

from chefs.models import Chef, ChefPaymentLink
from chef_services.models import ChefCustomerConnection
from crm.models import Lead
from custom_auth.models import CustomUser
from meals.models.commerce import PlatformFeeConfig, StripeConnectAccount
from meals.sous_chef_tools import (
    _preview_payment_link,
    _create_and_send_payment_link,
    _check_payment_link_status,
    FAMILY_REQUIRED_TOOLS,
)
from chefs.services.sous_chef.tools.categories import (
    ToolCategory,
    TOOL_REGISTRY,
    is_tool_allowed,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def test_lead(db, test_user):
    """Lead with verified email, owned by test_user."""
    lead = Lead.objects.create(
        owner=test_user,
        first_name="Sarah",
        last_name="Johnson",
        email="sarah@example.com",
        status="qualified",
    )
    lead.email_verified = True
    lead.save()
    return lead


@pytest.fixture
def unverified_lead(db, test_user):
    """Lead with unverified email."""
    return Lead.objects.create(
        owner=test_user,
        first_name="Bob",
        last_name="Unverified",
        email="bob@example.com",
        status="new",
    )


@pytest.fixture
def no_email_lead(db, test_user):
    """Lead with no email address."""
    return Lead.objects.create(
        owner=test_user,
        first_name="NoEmail",
        last_name="Person",
        email="",
        status="new",
    )


@pytest.fixture
def stripe_account(db, test_chef):
    """Active StripeConnectAccount for the chef."""
    return StripeConnectAccount.objects.create(
        chef=test_chef,
        stripe_account_id="acct_test123",
        is_active=True,
    )


@pytest.fixture
def customer_connection(db, test_chef, test_customer):
    """Accepted ChefCustomerConnection."""
    return ChefCustomerConnection.objects.create(
        chef=test_chef,
        customer=test_customer,
        status=ChefCustomerConnection.STATUS_ACCEPTED,
    )


@pytest.fixture
def platform_fee(db):
    """Active 5% platform fee."""
    return PlatformFeeConfig.objects.create(
        fee_percentage=Decimal("5.00"),
        active=True,
    )


@pytest.fixture
def mock_stripe_account():
    """Mock stripe.Account.retrieve to return a ready account."""
    mock_account = MagicMock()
    mock_account.charges_enabled = True
    mock_account.details_submitted = True
    mock_account.payouts_enabled = True
    with patch("meals.utils.stripe_utils.stripe.Account.retrieve", return_value=mock_account):
        yield mock_account


@pytest.fixture
def mock_stripe_create():
    """Mock all Stripe creation APIs."""
    with patch("chefs.api.payment_links.stripe.Product.create") as mock_product, \
         patch("chefs.api.payment_links.stripe.Price.create") as mock_price, \
         patch("chefs.api.payment_links.stripe.PaymentLink.create") as mock_link:
        mock_product.return_value = MagicMock(id="prod_test123")
        mock_price.return_value = MagicMock(id="price_test123")
        mock_link.return_value = MagicMock(
            id="plink_test123",
            url="https://buy.stripe.com/test123",
        )
        yield {
            "product": mock_product,
            "price": mock_price,
            "link": mock_link,
        }


@pytest.fixture
def mock_send_email():
    """Mock email sending."""
    with patch("chefs.api.payment_links._send_payment_link_email") as mock:
        yield mock


# ─── TestPreviewPaymentLink ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestPreviewPaymentLink:
    """Tests for _preview_payment_link handler."""

    def test_happy_path_customer(self, test_chef, test_customer, stripe_account, mock_stripe_account, platform_fee):
        result = _preview_payment_link(
            {"amount": 75.00, "description": "Weekly meal prep"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        assert result["render_as_payment_preview"] is True
        preview = result["preview"]
        assert preview["amount_cents"] == 7500
        assert preview["recipient_name"] == "John Doe"
        assert preview["recipient_email"] == "customer@example.com"
        assert preview["recipient_type"] == "customer"
        assert preview["description"] == "Weekly meal prep"
        assert preview["email_warning"] is None

    def test_happy_path_lead(self, test_chef, test_lead, stripe_account, mock_stripe_account, platform_fee):
        result = _preview_payment_link(
            {"amount": 50.00, "description": "Catering deposit"},
            test_chef, None, test_lead,
        )
        assert result["status"] == "success"
        assert result["render_as_payment_preview"] is True
        preview = result["preview"]
        assert preview["amount_cents"] == 5000
        assert preview["recipient_name"] == "Sarah Johnson"
        assert preview["recipient_type"] == "lead"

    def test_fee_calculation(self, test_chef, test_customer, stripe_account, mock_stripe_account, platform_fee):
        result = _preview_payment_link(
            {"amount": 100.00, "description": "Test"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        preview = result["preview"]
        # 5% of $100 = $5 fee, chef receives $95
        assert preview["platform_fee_display"] is not None
        assert "5" in preview["platform_fee_display"]
        assert "95" in preview["chef_receives_display"]

    def test_no_family_context(self, test_chef, stripe_account, mock_stripe_account):
        result = _preview_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, None, None,
        )
        assert result["status"] == "error"
        assert "client" in result["message"].lower()

    def test_no_stripe_account(self, test_chef, test_customer):
        """No StripeConnectAccount record → error."""
        result = _preview_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"
        assert "stripe" in result["message"].lower() or "payment" in result["message"].lower()

    def test_below_minimum_amount(self, test_chef, test_customer, stripe_account, mock_stripe_account):
        result = _preview_payment_link(
            {"amount": 0.10, "description": "Too small"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"
        assert "minimum" in result["message"].lower()

    def test_missing_description(self, test_chef, test_customer, stripe_account, mock_stripe_account):
        result = _preview_payment_link(
            {"amount": 50.00, "description": ""},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"
        assert "description" in result["message"].lower()

    def test_zero_decimal_currency_jpy(self, test_chef, test_customer, stripe_account, mock_stripe_account, platform_fee):
        result = _preview_payment_link(
            {"amount": 5000, "description": "Japanese meal", "currency": "jpy"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        preview = result["preview"]
        # JPY is zero-decimal: 5000 yen = 5000 cents (no ×100)
        assert preview["amount_cents"] == 5000
        assert preview["currency"] == "JPY"

    def test_email_warning_no_email(self, test_chef, no_email_lead, stripe_account, mock_stripe_account):
        result = _preview_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, None, no_email_lead,
        )
        assert result["status"] == "success"
        assert result["preview"]["email_warning"] is not None
        assert "email" in result["preview"]["email_warning"].lower()

    def test_email_warning_unverified_lead(self, test_chef, unverified_lead, stripe_account, mock_stripe_account):
        result = _preview_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, None, unverified_lead,
        )
        assert result["status"] == "success"
        assert result["preview"]["email_warning"] is not None
        assert "verif" in result["preview"]["email_warning"].lower()

    def test_missing_amount(self, test_chef, test_customer, stripe_account, mock_stripe_account):
        result = _preview_payment_link(
            {"description": "No amount"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"
        assert "amount" in result["message"].lower()

    def test_expires_days_clamped(self, test_chef, test_customer, stripe_account, mock_stripe_account, platform_fee):
        result = _preview_payment_link(
            {"amount": 50.00, "description": "Test", "expires_days": 200},
            test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        # Clamped to max 90
        assert result["preview"]["expires_days"] == 90


# ─── TestCreateAndSendPaymentLink ───────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAndSendPaymentLink:
    """Tests for _create_and_send_payment_link handler."""

    def test_happy_path_customer(
        self, test_chef, test_customer, stripe_account, mock_stripe_account,
        mock_stripe_create, mock_send_email, customer_connection, platform_fee,
    ):
        result = _create_and_send_payment_link(
            {"amount": 75.00, "description": "Weekly meal prep"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        assert result["render_as_payment_confirmation"] is True
        assert "payment_link" in result
        assert "75" in result["summary"]

        # Verify DB record
        link = ChefPaymentLink.objects.get(chef=test_chef, customer=test_customer)
        assert link.amount_cents == 7500
        assert link.status == ChefPaymentLink.Status.PENDING
        assert link.stripe_payment_link_url == "https://buy.stripe.com/test123"
        assert link.email_send_count >= 1

        # Verify email was sent
        mock_send_email.assert_called_once()

    def test_happy_path_lead(
        self, test_chef, test_lead, stripe_account, mock_stripe_account,
        mock_stripe_create, mock_send_email, platform_fee,
    ):
        result = _create_and_send_payment_link(
            {"amount": 50.00, "description": "Catering deposit"},
            test_chef, None, test_lead,
        )
        assert result["status"] == "success"
        assert result["render_as_payment_confirmation"] is True

        link = ChefPaymentLink.objects.get(chef=test_chef, lead=test_lead)
        assert link.amount_cents == 5000

    def test_no_family_context(self, test_chef):
        result = _create_and_send_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, None, None,
        )
        assert result["status"] == "error"

    def test_no_stripe_account(self, test_chef, test_customer):
        result = _create_and_send_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"

    def test_no_recipient_email(
        self, test_chef, no_email_lead, stripe_account, mock_stripe_account,
    ):
        result = _create_and_send_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, None, no_email_lead,
        )
        assert result["status"] == "error"
        assert "email" in result["message"].lower()

    def test_unverified_lead_email(
        self, test_chef, unverified_lead, stripe_account, mock_stripe_account,
    ):
        result = _create_and_send_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, None, unverified_lead,
        )
        assert result["status"] == "error"
        assert "verif" in result["message"].lower()

    def test_no_customer_connection(
        self, test_chef, test_customer, stripe_account, mock_stripe_account,
    ):
        """Customer without accepted connection → error."""
        result = _create_and_send_payment_link(
            {"amount": 50.00, "description": "Test"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"
        assert "connection" in result["message"].lower()

    def test_stripe_api_failure_cleans_up(
        self, test_chef, test_customer, stripe_account, mock_stripe_account,
        customer_connection, platform_fee,
    ):
        """Stripe failure should delete the DB record."""
        import stripe as stripe_module
        with patch("chefs.api.payment_links.stripe.Product.create") as mock_prod:
            mock_prod.side_effect = stripe_module.error.StripeError("API error")
            result = _create_and_send_payment_link(
                {"amount": 50.00, "description": "Test"},
                test_chef, test_customer, None,
            )
        assert result["status"] == "error"
        assert "stripe" in result["message"].lower()
        # DB record should be cleaned up
        assert ChefPaymentLink.objects.filter(chef=test_chef, customer=test_customer).count() == 0

    def test_email_failure_partial_success(
        self, test_chef, test_customer, stripe_account, mock_stripe_account,
        mock_stripe_create, customer_connection, platform_fee,
    ):
        """Email failure → partial_success, link still exists."""
        with patch("chefs.api.payment_links._send_payment_link_email", side_effect=Exception("SMTP error")):
            result = _create_and_send_payment_link(
                {"amount": 50.00, "description": "Test"},
                test_chef, test_customer, None,
            )
        assert result["status"] == "partial_success"
        assert result.get("warning") is not None
        # Link should still exist
        assert ChefPaymentLink.objects.filter(chef=test_chef, customer=test_customer).exists()

    def test_below_minimum_amount(
        self, test_chef, test_customer, stripe_account, mock_stripe_account,
        customer_connection,
    ):
        result = _create_and_send_payment_link(
            {"amount": 0.10, "description": "Too small"},
            test_chef, test_customer, None,
        )
        assert result["status"] == "error"
        assert "minimum" in result["message"].lower()


# ─── TestCheckPaymentLinkStatus ──────────────────────────────────────────────


@pytest.mark.django_db
class TestCheckPaymentLinkStatus:
    """Tests for _check_payment_link_status handler."""

    def _create_link(self, chef, customer=None, lead=None, status="pending", **kwargs):
        defaults = {
            "chef": chef,
            "customer": customer,
            "lead": lead,
            "amount_cents": 5000,
            "description": "Test payment",
            "status": status,
            "expires_at": timezone.now() + timedelta(days=30),
        }
        defaults.update(kwargs)
        return ChefPaymentLink.objects.create(**defaults)

    def test_returns_existing_links(self, test_chef, test_customer):
        self._create_link(test_chef, customer=test_customer)
        self._create_link(test_chef, customer=test_customer, amount_cents=7500)

        result = _check_payment_link_status(
            {}, test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        assert len(result["payment_links"]) == 2

    def test_status_filter(self, test_chef, test_customer):
        self._create_link(test_chef, customer=test_customer, status="pending")
        self._create_link(test_chef, customer=test_customer, status="paid")

        result = _check_payment_link_status(
            {"status_filter": "paid"}, test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        assert len(result["payment_links"]) == 1
        assert result["payment_links"][0]["status"] == "paid"

    def test_auto_expiry(self, test_chef, test_customer):
        """Pending links with past expires_at should be auto-expired."""
        self._create_link(
            test_chef, customer=test_customer, status="pending",
            expires_at=timezone.now() - timedelta(days=1),
        )

        result = _check_payment_link_status(
            {}, test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        # Link should have been auto-expired
        link = ChefPaymentLink.objects.get(chef=test_chef, customer=test_customer)
        assert link.status == ChefPaymentLink.Status.EXPIRED

    def test_no_links_found(self, test_chef, test_customer):
        result = _check_payment_link_status(
            {}, test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        assert len(result["payment_links"]) == 0
        assert "no payment links" in result["message"].lower()

    def test_no_family_context(self, test_chef):
        result = _check_payment_link_status(
            {}, test_chef, None, None,
        )
        assert result["status"] == "error"

    def test_limit_parameter(self, test_chef, test_customer):
        for _ in range(5):
            self._create_link(test_chef, customer=test_customer)

        result = _check_payment_link_status(
            {"limit": 2}, test_chef, test_customer, None,
        )
        assert result["status"] == "success"
        assert len(result["payment_links"]) == 2

    def test_customer_lead_isolation(self, test_chef, test_customer, test_lead):
        """Customer links shouldn't appear for lead queries and vice versa."""
        self._create_link(test_chef, customer=test_customer)
        self._create_link(test_chef, lead=test_lead)

        customer_result = _check_payment_link_status(
            {}, test_chef, test_customer, None,
        )
        assert len(customer_result["payment_links"]) == 1

        lead_result = _check_payment_link_status(
            {}, test_chef, None, test_lead,
        )
        assert len(lead_result["payment_links"]) == 1


# ─── TestPaymentToolCategories ───────────────────────────────────────────────


class TestPaymentToolCategories:
    """Test category registration and channel access for payment tools."""

    PAYMENT_TOOLS = [
        "preview_payment_link",
        "create_and_send_payment_link",
        "check_payment_link_status",
    ]

    def test_all_registered_as_core(self):
        for tool in self.PAYMENT_TOOLS:
            assert TOOL_REGISTRY.get(tool) == ToolCategory.CORE, \
                f"{tool} should be CORE"

    def test_allowed_on_all_channels(self):
        for tool in self.PAYMENT_TOOLS:
            for channel in ["web", "telegram", "line", "api"]:
                assert is_tool_allowed(tool, channel), \
                    f"{tool} should be allowed on {channel}"

    def test_all_in_family_required(self):
        for tool in self.PAYMENT_TOOLS:
            assert tool in FAMILY_REQUIRED_TOOLS, \
                f"{tool} should be in FAMILY_REQUIRED_TOOLS"


# ─── Integration Tests ────────────────────────────────────────────────────────
# These test the full SousChefService pipeline:
#   prompt → mocked LLM returns tool call → tool dispatched → handler executed → result


@pytest.mark.django_db
class TestPaymentLinkIntegration:
    """
    Integration tests that simulate the agent loop via SousChefService.

    The LLM is mocked to return specific tool calls, but everything else
    runs for real: tool dispatch, handler execution, DB writes, Stripe mocks.
    """

    def _make_groq_tool_response(self, tool_name, arguments_json):
        """Build a mock Groq response that triggers a tool call."""
        tool_response = MagicMock()
        tool_response.choices = [MagicMock()]
        tool_response.choices[0].message.content = ""
        tool_call = MagicMock()
        tool_call.id = "call_payment_test"
        tool_call.function.name = tool_name
        tool_call.function.arguments = arguments_json
        tool_response.choices[0].message.tool_calls = [tool_call]
        return tool_response

    def _make_groq_final_response(self, text):
        """Build a mock Groq final response (no tool calls)."""
        final = MagicMock()
        final.choices = [MagicMock()]
        final.choices[0].message.content = text
        final.choices[0].message.tool_calls = None
        return final

    def test_preview_through_agent_loop(
        self, test_chef, test_customer, stripe_account,
        mock_stripe_account, platform_fee,
    ):
        """
        Prompt → agent calls preview_payment_link → preview returned.

        Verifies the full pipeline: SousChefService → _run_agent_loop →
        execute_tool → _preview_payment_link.
        """
        import json

        tool_resp = self._make_groq_tool_response(
            "preview_payment_link",
            json.dumps({"amount": 75.00, "description": "Weekly meal prep"}),
        )
        final_resp = self._make_groq_final_response(
            "Here's a preview of the $75 payment link for John."
        )

        with patch("groq.Groq") as mock_groq_cls:
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [tool_resp, final_resp]

            from chefs.services.sous_chef.service import SousChefService
            service = SousChefService(
                chef_id=test_chef.id,
                channel="web",
                family_id=test_customer.id,
                family_type="customer",
            )
            result = service.send_message(
                "Can you show me a preview of a $75 payment link for weekly meal prep?"
            )

        assert result["status"] == "success"
        assert "preview" in result["message"].lower() or "$75" in result["message"]

        # Verify Groq was called twice (tool call + final)
        assert mock_client.chat.completions.create.call_count == 2

        # Verify the second call included the tool result in messages
        second_call_messages = mock_client.chat.completions.create.call_args_list[1]
        messages = second_call_messages[1]["messages"]
        tool_result_msg = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_result_msg) == 1

        # The tool result should contain the preview
        tool_result = json.loads(tool_result_msg[0]["content"])
        assert tool_result["status"] == "success"
        assert tool_result["render_as_payment_preview"] is True
        assert tool_result["preview"]["amount_display"] == "$75.00"

    def test_create_payment_link_through_agent_loop(
        self, test_chef, test_customer, stripe_account,
        customer_connection, mock_stripe_account, mock_stripe_create,
        mock_send_email, platform_fee,
    ):
        """
        Prompt → agent calls create_and_send_payment_link → link created + email sent.

        Tests the full creation flow through the service layer, verifying
        DB record creation, Stripe API calls, and email dispatch.
        """
        import json

        tool_resp = self._make_groq_tool_response(
            "create_and_send_payment_link",
            json.dumps({
                "amount": 50.00,
                "description": "Birthday dinner prep",
                "currency": "usd",
            }),
        )
        final_resp = self._make_groq_final_response(
            "I've created and sent a $50 payment link for the birthday dinner."
        )

        with patch("groq.Groq") as mock_groq_cls:
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [tool_resp, final_resp]

            from chefs.services.sous_chef.service import SousChefService
            service = SousChefService(
                chef_id=test_chef.id,
                channel="web",
                family_id=test_customer.id,
                family_type="customer",
            )
            result = service.send_message(
                "Create a $50 payment link for birthday dinner prep"
            )

        assert result["status"] == "success"

        # Verify the tool result passed back to LLM
        second_call = mock_client.chat.completions.create.call_args_list[1]
        messages = second_call[1]["messages"]
        tool_result_msg = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_result_msg) == 1
        tool_result = json.loads(tool_result_msg[0]["content"])
        assert tool_result["status"] == "success"
        assert tool_result["render_as_payment_confirmation"] is True
        assert tool_result["payment_link"]["payment_url"] == "https://buy.stripe.com/test123"

        # Verify DB record was created
        link = ChefPaymentLink.objects.filter(
            chef=test_chef,
            customer=test_customer,
        ).first()
        assert link is not None
        assert link.description == "Birthday dinner prep"
        assert link.amount_cents == 5000  # $50.00 = 5000 cents
        assert link.stripe_payment_link_url == "https://buy.stripe.com/test123"

        # Verify Stripe APIs were called
        mock_stripe_create["product"].assert_called_once()
        mock_stripe_create["price"].assert_called_once()
        mock_stripe_create["link"].assert_called_once()

        # Verify email was sent
        mock_send_email.assert_called_once()

    def test_create_payment_link_on_telegram(
        self, test_chef, test_customer, stripe_account,
        customer_connection, mock_stripe_account, mock_stripe_create,
        mock_send_email, platform_fee,
    ):
        """
        Payment link creation works on Telegram channel too (CORE tool).

        This was a key user requirement — chefs should be able to create
        payment links from messaging channels, not just the web dashboard.
        """
        import json

        tool_resp = self._make_groq_tool_response(
            "create_and_send_payment_link",
            json.dumps({
                "amount": 30.00,
                "description": "Quick lunch order",
            }),
        )
        final_resp = self._make_groq_final_response(
            "Payment link sent! Sarah will receive it via email."
        )

        with patch("groq.Groq") as mock_groq_cls:
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [tool_resp, final_resp]

            from chefs.services.sous_chef.service import SousChefService
            service = SousChefService(
                chef_id=test_chef.id,
                channel="telegram",
                family_id=test_customer.id,
                family_type="customer",
            )
            result = service.send_message(
                "Send John a $30 payment link for the lunch order"
            )

        assert result["status"] == "success"

        # Verify DB record created even on Telegram
        link = ChefPaymentLink.objects.filter(chef=test_chef).first()
        assert link is not None
        assert link.amount_cents == 3000  # $30.00 = 3000 cents

    def test_check_status_through_agent_loop(
        self, test_chef, test_customer, stripe_account,
        mock_stripe_account,
    ):
        """
        Prompt → agent calls check_payment_link_status → results returned.
        """
        import json

        # Create a payment link in DB to query
        ChefPaymentLink.objects.create(
            chef=test_chef,
            customer=test_customer,
            amount_cents=10000,  # $100.00
            currency="usd",
            description="Previous order",
            status="paid",
            stripe_payment_link_id="plink_old",
            stripe_payment_link_url="https://buy.stripe.com/old",
            expires_at=timezone.now() + timedelta(days=30),
        )

        tool_resp = self._make_groq_tool_response(
            "check_payment_link_status",
            json.dumps({}),
        )
        final_resp = self._make_groq_final_response(
            "John has 1 payment link — a $100 one that's been paid."
        )

        with patch("groq.Groq") as mock_groq_cls:
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [tool_resp, final_resp]

            from chefs.services.sous_chef.service import SousChefService
            service = SousChefService(
                chef_id=test_chef.id,
                channel="web",
                family_id=test_customer.id,
                family_type="customer",
            )
            result = service.send_message(
                "What payment links do I have for John?"
            )

        assert result["status"] == "success"

        # Verify the tool result had the link
        second_call = mock_client.chat.completions.create.call_args_list[1]
        messages = second_call[1]["messages"]
        tool_result_msg = [m for m in messages if m.get("role") == "tool"]
        tool_result = json.loads(tool_result_msg[0]["content"])
        assert tool_result["status"] == "success"
        assert len(tool_result["payment_links"]) == 1
        assert tool_result["payment_links"][0]["status"] == "paid"

    def test_preview_then_create_two_turn_flow(
        self, test_chef, test_customer, stripe_account,
        customer_connection, mock_stripe_account, mock_stripe_create,
        mock_send_email, platform_fee,
    ):
        """
        Simulates the natural two-step flow: preview first, then create.

        This tests the pattern where the chef asks the agent to preview,
        reviews the details, then confirms creation.
        """
        import json

        # --- Turn 1: Preview ---
        preview_tool = self._make_groq_tool_response(
            "preview_payment_link",
            json.dumps({"amount": 120.00, "description": "Catering event"}),
        )
        preview_final = self._make_groq_final_response(
            "Here's the preview — $120 for the catering event. Shall I send it?"
        )

        with patch("groq.Groq") as mock_groq_cls:
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [preview_tool, preview_final]

            from chefs.services.sous_chef.service import SousChefService
            service = SousChefService(
                chef_id=test_chef.id,
                channel="web",
                family_id=test_customer.id,
                family_type="customer",
            )
            result1 = service.send_message("Preview a $120 payment link for catering")

        assert result1["status"] == "success"
        # No DB record should exist yet (preview only)
        assert ChefPaymentLink.objects.filter(chef=test_chef).count() == 0

        # --- Turn 2: Create ---
        create_tool = self._make_groq_tool_response(
            "create_and_send_payment_link",
            json.dumps({"amount": 120.00, "description": "Catering event"}),
        )
        create_final = self._make_groq_final_response(
            "Done! The $120 payment link has been sent to John."
        )

        with patch("groq.Groq") as mock_groq_cls:
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [create_tool, create_final]

            service2 = SousChefService(
                chef_id=test_chef.id,
                channel="web",
                family_id=test_customer.id,
                family_type="customer",
            )
            result2 = service2.send_message("Yes, go ahead and send it")

        assert result2["status"] == "success"
        # Now the DB record should exist
        link = ChefPaymentLink.objects.filter(chef=test_chef).first()
        assert link is not None
        assert link.amount_cents == 12000  # $120.00 = 12000 cents
        mock_send_email.assert_called_once()


# ─── Real Stripe Integration Tests ──────────────────────────────────────────
# These tests hit the actual Stripe test API (sk_test_*) to verify payment
# links are genuinely created. Only email sending and LLM calls are mocked.
#
# Run selectively:
#   pytest chefs/services/sous_chef/tests/test_payment_link_tools.py -v -k "RealStripe"

import os
import stripe as stripe_module

skip_no_stripe = pytest.mark.skipif(
    not os.getenv("STRIPE_SECRET_KEY", "").startswith("sk_test_"),
    reason="Real Stripe test key not available",
)

REAL_STRIPE_CONNECT_ACCOUNT = "acct_1QzvYAH5y38eT4Xc"


@pytest.fixture
def real_stripe_chef(db):
    """Chef with the real test Stripe Connect account."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(
        username="stripe_test_chef",
        first_name="Stripe",
        last_name="TestChef",
        email="stripetest@example.com",
        password="testpass123",
    )
    from chefs.models import Chef
    chef = Chef.objects.create(user=user)
    StripeConnectAccount.objects.create(
        chef=chef,
        stripe_account_id=REAL_STRIPE_CONNECT_ACCOUNT,
        is_active=True,
    )
    return chef


@pytest.fixture
def real_stripe_customer(db, real_stripe_chef):
    """Customer with accepted connection to the stripe test chef."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    customer = User.objects.create_user(
        username="stripe_test_customer",
        first_name="Jane",
        last_name="TestCustomer",
        email="janetestcustomer@example.com",
        password="testpass123",
    )
    ChefCustomerConnection.objects.create(
        chef=real_stripe_chef,
        customer=customer,
        status=ChefCustomerConnection.STATUS_ACCEPTED,
    )
    return customer


@pytest.fixture
def real_stripe_fee(db):
    """Active platform fee for real Stripe tests."""
    return PlatformFeeConfig.objects.create(
        fee_percentage=Decimal("5.00"),
        active=True,
    )


def _cleanup_stripe_resources(payment_link_record):
    """Deactivate Stripe test resources after a test."""
    from django.conf import settings
    stripe_module.api_key = settings.STRIPE_SECRET_KEY
    if payment_link_record.stripe_product_id:
        try:
            stripe_module.Product.modify(
                payment_link_record.stripe_product_id, active=False,
            )
        except Exception:
            pass
    if payment_link_record.stripe_payment_link_id:
        try:
            stripe_module.PaymentLink.modify(
                payment_link_record.stripe_payment_link_id, active=False,
            )
        except Exception:
            pass


@skip_no_stripe
@pytest.mark.django_db
class TestPaymentLinkRealStripe:
    """
    Integration tests that hit the real Stripe test API.

    Only _send_payment_link_email and LLM calls are mocked.
    All Stripe API calls (Account.retrieve, Product.create,
    Price.create, PaymentLink.create) are real.
    """

    def test_real_stripe_preview(
        self, real_stripe_chef, real_stripe_customer, real_stripe_fee,
    ):
        """Preview hits stripe.Account.retrieve for real to validate the Connect account."""
        result = _preview_payment_link(
            {"amount": 25.00, "description": "Test preview"},
            real_stripe_chef, real_stripe_customer, None,
        )
        assert result["status"] == "success"
        assert result["render_as_payment_preview"] is True
        preview = result["preview"]
        assert preview["amount_display"] == "$25.00"
        assert preview["amount_cents"] == 2500

    def test_real_stripe_create_payment_link(
        self, real_stripe_chef, real_stripe_customer, real_stripe_fee,
    ):
        """Create a real Stripe payment link — only email is mocked."""
        with patch("chefs.api.payment_links._send_payment_link_email"):
            result = _create_and_send_payment_link(
                {"amount": 10.00, "description": "Real Stripe test"},
                real_stripe_chef, real_stripe_customer, None,
            )

        assert result["status"] == "success"
        assert result["render_as_payment_confirmation"] is True
        assert result["payment_link"]["payment_url"].startswith("https://buy.stripe.com/")

        # Verify DB record has real Stripe IDs
        link = ChefPaymentLink.objects.get(
            chef=real_stripe_chef, customer=real_stripe_customer,
        )
        assert link.stripe_product_id.startswith("prod_")
        assert link.stripe_price_id.startswith("price_")
        assert link.stripe_payment_link_id.startswith("plink_")
        assert link.stripe_payment_link_url.startswith("https://buy.stripe.com/")
        assert link.status == ChefPaymentLink.Status.PENDING

        # Cleanup
        _cleanup_stripe_resources(link)

    def test_real_stripe_full_agent_loop(
        self, real_stripe_chef, real_stripe_customer, real_stripe_fee,
    ):
        """Full agent loop: mocked LLM + real Stripe. Only LLM and email are mocked."""
        import json

        # Mock Groq to return a create_and_send_payment_link tool call
        tool_resp = MagicMock()
        tool_resp.choices = [MagicMock()]
        tool_resp.choices[0].message.content = ""
        tool_call = MagicMock()
        tool_call.id = "call_real_stripe"
        tool_call.function.name = "create_and_send_payment_link"
        tool_call.function.arguments = json.dumps({
            "amount": 15.00,
            "description": "Real agent loop test",
        })
        tool_resp.choices[0].message.tool_calls = [tool_call]

        final_resp = MagicMock()
        final_resp.choices = [MagicMock()]
        final_resp.choices[0].message.content = "Payment link sent!"
        final_resp.choices[0].message.tool_calls = None

        with patch("groq.Groq") as mock_groq_cls, \
             patch("chefs.api.payment_links._send_payment_link_email"):
            mock_client = MagicMock()
            mock_groq_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = [tool_resp, final_resp]

            from chefs.services.sous_chef.service import SousChefService
            service = SousChefService(
                chef_id=real_stripe_chef.id,
                channel="web",
                family_id=real_stripe_customer.id,
                family_type="customer",
            )
            result = service.send_message("Send a $15 payment link for agent loop test")

        assert result["status"] == "success"

        # Verify tool result passed back to LLM contains a real payment URL
        second_call = mock_client.chat.completions.create.call_args_list[1]
        messages = second_call[1]["messages"]
        tool_result_msg = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_result_msg) == 1
        tool_result = json.loads(tool_result_msg[0]["content"])
        assert tool_result["status"] == "success"
        assert tool_result["payment_link"]["payment_url"].startswith("https://buy.stripe.com/")

        # Verify DB record
        link = ChefPaymentLink.objects.get(
            chef=real_stripe_chef, customer=real_stripe_customer,
        )
        assert link.stripe_product_id.startswith("prod_")
        assert link.stripe_payment_link_id.startswith("plink_")

        # Cleanup
        _cleanup_stripe_resources(link)

    def test_real_stripe_check_status_with_real_link(
        self, real_stripe_chef, real_stripe_customer, real_stripe_fee,
    ):
        """Create a real link, then check its status via _check_payment_link_status."""
        # First create a real payment link
        with patch("chefs.api.payment_links._send_payment_link_email"):
            create_result = _create_and_send_payment_link(
                {"amount": 12.00, "description": "Status check test"},
                real_stripe_chef, real_stripe_customer, None,
            )
        assert create_result["status"] == "success"

        # Now check status
        status_result = _check_payment_link_status(
            {}, real_stripe_chef, real_stripe_customer, None,
        )
        assert status_result["status"] == "success"
        assert len(status_result["payment_links"]) >= 1

        found = status_result["payment_links"][0]
        assert found["status"] == "pending"
        assert found["payment_url"].startswith("https://buy.stripe.com/")

        # Cleanup
        link = ChefPaymentLink.objects.get(
            chef=real_stripe_chef, customer=real_stripe_customer,
        )
        _cleanup_stripe_resources(link)
