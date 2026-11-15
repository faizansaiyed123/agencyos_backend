from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.errors import BusinessRuleViolation, Forbidden
from app.modules.billing import service as billing_service
from app.modules.billing.invoice_states import settlement
from app.modules.billing.models import CreditNote, PaymentRefund
from app.modules.billing.pdf import render_credit_note_pdf, render_invoice_pdf
from app.modules.crm import service as crm_service
from app.modules.crm.deal_states import can_transition, is_terminal
from app.modules.files.service import sanitize_filename
from app.modules.identity import queries as identity_queries
from app.modules.portal.service import _client_id
from app.modules.proposals import service as proposal_service
from app.platform.webhooks import validate_endpoint_url


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.flushes = 0
        self.added: list[object] = []

    def commit(self) -> None:
        self.commits += 1

    def flush(self) -> None:
        self.flushes += 1

    def add(self, obj: object) -> None:
        self.added.append(obj)


def test_deal_state_machine_has_no_skipping() -> None:
    assert can_transition("lead", "qualified")
    assert not can_transition("lead", "won")
    assert is_terminal("won")
    assert is_terminal("lost")


def test_deal_mutators_can_participate_in_an_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb()
    deal = SimpleNamespace(id="deal-1", stage="qualified", value_amount=100)
    monkeypatch.setattr(crm_service, "set_org_context", lambda *_args: None)
    monkeypatch.setattr(crm_service.queries, "get_deal", lambda *_args: deal)
    monkeypatch.setattr(crm_service, "record_audit", lambda *_args, **_kwargs: None)

    crm_service.set_deal_value(
        db, org_id="org-1", actor_id="user-1", deal_id="deal-1", value_amount=200, commit=False
    )
    crm_service.change_deal_stage(
        db,
        org_id="org-1",
        actor_id="user-1",
        deal_id="deal-1",
        to_stage="proposal_sent",
        lost_reason=None,
        note="advance",
        commit=False,
    )

    assert db.flushes == 2
    assert db.commits == 0


def test_accept_proposal_commits_once_after_project_and_deal_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb()
    proposal = SimpleNamespace(
        id="proposal-1",
        status="sent",
        deal_id="deal-1",
        client_id="client-1",
        title="Website",
        currency="USD",
        accepted_at=None,
    )
    deal = SimpleNamespace(
        id="deal-1",
        client_id="client-1",
        stage="qualified",
        owner_user_id="user-1",
        title="Website",
    )

    monkeypatch.setattr(proposal_service, "set_org_context", lambda *_args: None)
    monkeypatch.setattr(proposal_service.queries, "get_proposal", lambda *_args: proposal)
    monkeypatch.setattr(proposal_service.queries, "compute_total", lambda *_args: 5000)
    monkeypatch.setattr(proposal_service.queries, "list_items", lambda *_args: [])
    monkeypatch.setattr(proposal_service.crm_queries, "get_deal", lambda *_args: deal)
    monkeypatch.setattr(proposal_service, "record_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(proposal_service, "can_transition", lambda *_args: True)
    monkeypatch.setattr(
        proposal_service.projects_service,
        "create_project_from_deal",
        lambda *_args, **_kwargs: (SimpleNamespace(id="project-1"), True),
    )

    calls: list[dict[str, object]] = []

    def set_value(*_args, **kwargs):
        calls.append({"kind": "value", **kwargs})
        return deal

    def change_stage(*_args, **kwargs):
        calls.append({"kind": "stage", **kwargs})
        deal.stage = kwargs["to_stage"]
        return deal

    monkeypatch.setattr(proposal_service.crm_service, "set_deal_value", set_value)
    monkeypatch.setattr(proposal_service.crm_service, "change_deal_stage", change_stage)

    result = proposal_service.accept_proposal(
        db, org_id="org-1", actor_id="user-1", proposal_id="proposal-1"
    )

    assert result is proposal
    assert proposal.status == "accepted"
    assert db.commits == 1
    assert calls and all(call["commit"] is False for call in calls)


def test_refresh_token_lookup_locks_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_states: list[bool] = []

    class Statement:
        def where(self, *_args: object) -> "Statement":
            return self

        def with_for_update(self) -> "Statement":
            lock_states.append(True)
            return self

    monkeypatch.setattr(identity_queries, "set_lookup_key", lambda *_args: None)
    monkeypatch.setattr(identity_queries, "select", lambda *_args: Statement())
    monkeypatch.setattr(identity_queries, "RefreshToken", SimpleNamespace(token_hash="token_hash"))

    db = Mock()
    db.scalar.return_value = "token"
    assert identity_queries.find_refresh_token_by_hash(db, "hash", lock=True) == "token"
    assert lock_states == [True]


def test_filename_sanitization_removes_path_and_control_characters() -> None:
    assert sanitize_filename("../secret" + chr(0) + "/report.pdf") == "report.pdf"


def test_webhooks_reject_private_ip_literals() -> None:
    with pytest.raises(BusinessRuleViolation):
        validate_endpoint_url("https://127.0.0.1/hook")
    with pytest.raises(BusinessRuleViolation):
        validate_endpoint_url("https://localhost/hook")


def test_app_imports_with_declared_runtime_dependencies() -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/healthz" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/password/forgot" in paths
    assert "/api/v1/auth/password/reset" in paths


def test_client_portal_requires_an_explicit_client_link() -> None:
    with pytest.raises(Forbidden):
        _client_id(SimpleNamespace(role="client", client_id=None))


def test_app_exposes_client_portal_routes() -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/portal/overview" in paths
    assert "/api/v1/portal/proposals/{proposal_id}/accept" in paths
    assert "/api/v1/invoices/{invoice_id}/credit-notes" in paths
    assert "/api/v1/invoices/{invoice_id}/payments/{payment_id}/refunds" in paths
    assert "/api/v1/credit-notes/{credit_note_id}/pdf" in paths
    assert "/api/v1/portal/credit-notes" in paths
    assert "/api/v1/portal/credit-notes/{credit_note_id}/pdf" in paths


def test_invoice_pdf_renderer_produces_pdf_bytes() -> None:
    invoice = SimpleNamespace(
        number="INV-2026-0001",
        issue_date=None,
        due_date=None,
        currency="USD",
        status="sent",
        tax_rate_bps=0,
        subtotal_cents=10000,
        tax_cents=0,
        total_cents=10000,
        amount_paid_cents=0,
        amount_refunded_cents=0,
        credit_note_cents=0,
        notes="Test invoice",
    )
    client = SimpleNamespace(name="Acme & Co.", website="https://example.test")
    line = SimpleNamespace(
        description="Design & implementation",
        quantity="1",
        unit_cents=10000,
        amount_cents=10000,
    )
    pdf = render_invoice_pdf(invoice, client, [line])
    assert pdf.startswith(b"%PDF-")



@pytest.mark.parametrize(
    ("paid", "refunded", "credited", "expected"),
    [
        (0, 0, 0, ("sent", 10_000, 0)),
        (4_000, 0, 0, ("partially_paid", 6_000, 0)),
        (10_000, 0, 0, ("paid", 0, 0)),
        (10_000, 3_000, 0, ("partially_paid", 3_000, 0)),
        (3_000, 0, 4_000, ("partially_paid", 3_000, 0)),
        (9_000, 0, 4_000, ("paid", 0, 3_000)),
        (0, 0, 10_000, ("credited", 0, 0)),
        (6_000, 0, 10_000, ("credited", 0, 6_000)),
        (6_000, 6_000, 0, ("sent", 10_000, 0)),
    ],
)
def test_invoice_settlement_separates_cash_refunds_and_credit_notes(
    paid: int,
    refunded: int,
    credited: int,
    expected: tuple[str, int, int],
) -> None:
    assert settlement(
        total_cents=10_000,
        amount_paid_cents=paid,
        amount_refunded_cents=refunded,
        credit_note_cents=credited,
    ) == expected


def test_paid_is_not_terminal_because_a_refund_can_reopen_the_receivable() -> None:
    from app.modules.billing.invoice_states import can_transition, is_final

    assert can_transition("paid", "partially_paid")
    assert not is_final("paid")
    assert is_final("credited")
    assert is_final("void")


def test_issue_credit_note_updates_settlement_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    db = FakeDb()
    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        status="paid",
        total_cents=10_000,
        amount_paid_cents=10_000,
        amount_refunded_cents=0,
        credit_note_cents=2_000,
        paid_at=None,
    )
    monkeypatch.setattr(
        billing_service,
        "get_invoice",
        lambda _db, _org, _id, lock=False: invoice if lock else None,
    )
    monkeypatch.setattr(billing_service, "_next_credit_note_number", lambda *_: "CN-2026-0001")
    monkeypatch.setattr(billing_service, "record_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(billing_service.events, "emit", lambda *_args, **_kwargs: None)

    note = billing_service.issue_credit_note(
        db,
        org_id=invoice.org_id,
        actor_id=uuid.uuid4(),
        invoice_id=invoice.id,
        amount_cents=3_000,
        issued_on=None,
        reason="Service scope reduced",
        commit=False,
    )

    assert isinstance(note, CreditNote)
    assert note.number == "CN-2026-0001"
    assert note.amount_cents == 3_000
    assert invoice.credit_note_cents == 5_000
    assert billing_service.balance(invoice) == 0
    assert billing_service.credit_balance(invoice) == 5_000
    assert invoice.status == "paid"
    assert db.flushes == 1
    assert db.commits == 0


def test_credit_note_cannot_exceed_the_uncredited_invoice_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    db = FakeDb()
    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        status="sent",
        total_cents=10_000,
        amount_paid_cents=0,
        amount_refunded_cents=0,
        credit_note_cents=9_000,
        paid_at=None,
    )
    monkeypatch.setattr(
        billing_service,
        "get_invoice",
        lambda _db, _org, _id, lock=False: invoice if lock else None,
    )
    with pytest.raises(BusinessRuleViolation, match="remaining creditable amount"):
        billing_service.issue_credit_note(
            db,
            org_id=invoice.org_id,
            actor_id=uuid.uuid4(),
            invoice_id=invoice.id,
            amount_cents=1_001,
            issued_on=None,
            reason="Over the remaining credit",
            commit=False,
        )
    assert not db.added
    assert db.flushes == 0


def test_refund_locks_and_recalculates_the_original_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    from unittest.mock import Mock

    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        status="paid",
        total_cents=10_000,
        amount_paid_cents=10_000,
        amount_refunded_cents=0,
        credit_note_cents=0,
        paid_at=None,
    )
    payment = SimpleNamespace(
        id=uuid.uuid4(),
        amount_cents=10_000,
        method="card",
    )
    db = Mock()
    db.scalar.side_effect = [payment, 2_500]
    monkeypatch.setattr(
        billing_service,
        "get_invoice",
        lambda _db, _org, _id, lock=False: invoice if lock else None,
    )
    monkeypatch.setattr(billing_service, "record_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(billing_service.events, "emit", lambda *_args, **_kwargs: None)

    refund = billing_service.record_refund(
        db,
        org_id=invoice.org_id,
        actor_id=uuid.uuid4(),
        invoice_id=invoice.id,
        payment_id=payment.id,
        amount_cents=3_000,
        refunded_on=None,
        method=None,
        reference="processor-refund-1",
        reason="Customer cancellation",
        commit=False,
    )

    assert isinstance(refund, PaymentRefund)
    assert refund.method == "card"
    assert refund.amount_cents == 3_000
    assert invoice.amount_refunded_cents == 3_000
    assert invoice.status == "partially_paid"
    assert invoice.paid_at is None
    assert billing_service.balance(invoice) == 3_000
    assert db.scalar.call_count == 2
    locked_payment_query = db.scalar.call_args_list[0].args[0]
    assert locked_payment_query._for_update_arg is not None
    db.commit.assert_not_called()


def test_refund_cannot_exceed_the_unrefunded_amount_of_its_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    from unittest.mock import Mock

    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        status="partially_paid",
        total_cents=10_000,
        amount_paid_cents=10_000,
        amount_refunded_cents=9_500,
        credit_note_cents=0,
        paid_at=None,
    )
    payment = SimpleNamespace(id=uuid.uuid4(), amount_cents=10_000, method="bank_transfer")
    db = Mock()
    db.scalar.side_effect = [payment, 9_500]
    monkeypatch.setattr(
        billing_service,
        "get_invoice",
        lambda _db, _org, _id, lock=False: invoice if lock else None,
    )

    with pytest.raises(BusinessRuleViolation, match="remaining refundable amount"):
        billing_service.record_refund(
            db,
            org_id=invoice.org_id,
            actor_id=uuid.uuid4(),
            invoice_id=invoice.id,
            payment_id=payment.id,
            amount_cents=501,
            refunded_on=None,
            method=None,
            reference=None,
            reason="Attempted excess refund",
            commit=False,
        )
    db.add.assert_not_called()
    db.flush.assert_not_called()


def test_credit_note_pdf_renderer_produces_pdf_bytes() -> None:
    from datetime import date
    import uuid

    credit_note = SimpleNamespace(
        id=uuid.uuid4(),
        number="CN-2026-0001",
        amount_cents=2_500,
        issued_on=date(2026, 11, 15),
        reason="Reduced delivery scope & fees",
    )
    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        number="INV-2026-0001",
        total_cents=10_000,
        amount_paid_cents=10_000,
        amount_refunded_cents=0,
        credit_note_cents=2_500,
        currency="USD",
    )
    client = SimpleNamespace(name="Acme & Co.")
    assert render_credit_note_pdf(credit_note, invoice, client).startswith(b"%PDF-")


def test_billing_model_metadata_contains_immutable_tenant_ledgers() -> None:
    from app.models import Base

    assert "credit_note_counters" in Base.metadata.tables
    assert "credit_notes" in Base.metadata.tables
    assert "payment_refunds" in Base.metadata.tables
    payment_constraints = Base.metadata.tables["payments"].constraints
    assert any(
        getattr(constraint, "name", None) == "uq_payments_org_id_id"
        for constraint in payment_constraints
    )
