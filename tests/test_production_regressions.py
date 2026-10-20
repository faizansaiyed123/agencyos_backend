from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.errors import BusinessRuleViolation
from app.modules.crm import service as crm_service
from app.modules.crm.deal_states import can_transition, is_terminal
from app.modules.files.service import sanitize_filename
from app.modules.identity import queries as identity_queries
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


def test_deal_mutators_can_participate_in_an_outer_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_accept_proposal_commits_once_after_project_and_deal_work(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDb()
    proposal = SimpleNamespace(
        id="proposal-1",
        status="sent",
        deal_id="deal-1",
        client_id="client-1",
        title="Website",
        accepted_at=None,
    )
    deal = SimpleNamespace(id="deal-1", client_id="client-1", stage="qualified", owner_user_id="user-1")

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
    assert sanitize_filename("../\\secret" + chr(0) + "report.pdf") == "report.pdf"


def test_webhooks_reject_private_ip_literals() -> None:
    with pytest.raises(BusinessRuleViolation):
        validate_endpoint_url("https://127.0.0.1/hook")
    with pytest.raises(BusinessRuleViolation):
        validate_endpoint_url("https://localhost/hook")


def test_app_imports_with_declared_runtime_dependencies() -> None:
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/healthz" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/password/forgot" in paths
    assert "/api/v1/auth/password/reset" in paths
