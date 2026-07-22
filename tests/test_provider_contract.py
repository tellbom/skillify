from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skillify.agent.events import (
    PROVIDER_CONTRACT_VERSION,
    TASK_PROTOCOL_VERSION,
    EventType,
    TaskEvent,
    TaskState,
)
from skillify.agent.fake_provider import FakeOutcome, FakeProvider
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec

NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


def _runtime() -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        provider="internal-openai",
        endpoint="https://model.intranet.example/v1",
        model="code-model-1",
        allowed_endpoint_hosts=("model.intranet.example",),
        credential_env_names=("INTERNAL_MODEL_API_KEY",),
    )


def _start(tmp_path: Path) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve()
    workspace.mkdir()
    return ProviderStartSpec(
        workspace=workspace,
        allowed_paths=(workspace,),
        config_dir=tmp_path / "config",
        runtime=_runtime(),
    )


def _provider(outcome: FakeOutcome = FakeOutcome.SUCCEED) -> FakeProvider:
    values = iter(("handle-1", "session-1"))
    return FakeProvider(outcome=outcome, clock=lambda: NOW, id_factory=lambda: next(values))


def test_protocol_versions_are_explicit_and_stable() -> None:
    assert TASK_PROTOCOL_VERSION == 1
    assert PROVIDER_CONTRACT_VERSION == 1
    assert TaskSpec(task_id="task-1", prompt="work").task_protocol_version == 1


@pytest.mark.parametrize("kwargs", [
    {"task_id": "", "prompt": "work"},
    {"task_id": "task", "prompt": ""},
    {"task_id": "task", "prompt": "work", "task_protocol_version": 2},
    {"task_id": "task", "prompt": "work", "timeout_seconds": 0},
])
def test_task_spec_rejects_invalid_ids_protocol_prompt_and_timeout(kwargs) -> None:
    with pytest.raises(ValueError): TaskSpec(**kwargs)


@pytest.mark.parametrize(
    "timeout_seconds",
    [float("nan"), float("inf"), float("-inf"), 0, -1],
)
def test_task_spec_rejects_non_finite_or_non_positive_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        TaskSpec("task", "work", timeout_seconds=timeout_seconds)


def test_runtime_config_is_immutable_validated_and_redacted() -> None:
    config = _runtime()
    assert config.redacted() == {
        "provider": "internal-openai",
        "endpoint_host": "model.intranet.example",
        "model": "code-model-1",
        "credential_env_names": ["INTERNAL_MODEL_API_KEY"],
    }
    with pytest.raises((AttributeError, TypeError)):
        config.model = "changed"
    with pytest.raises(ValueError, match="allowlisted"):
        ModelRuntimeConfig("p", "https://api.openai.com/v1", "m", ("model.intranet.example",), ("API_KEY",))
    with pytest.raises(ValueError, match="credential"):
        ModelRuntimeConfig("p", "https://model.intranet.example/v1", "m", ("model.intranet.example",), ("KEY=value",))


def test_empty_runtime_delegates_model_and_credentials_to_provider_cli() -> None:
    config = ModelRuntimeConfig()
    assert config.is_provider_managed is True
    assert config.redacted() == {"source": "provider"}


@pytest.mark.parametrize("endpoint", [
    "https://model.intranet.example:not-a-port/v1",
    "https://model.intranet.example:99999/v1",
])
def test_runtime_config_rejects_invalid_or_out_of_range_ports(endpoint: str) -> None:
    with pytest.raises(ValueError, match="port"):
        ModelRuntimeConfig(
            "p", endpoint, "m", ("model.intranet.example",), ("API_KEY",),
        )


@pytest.mark.parametrize("field", ["startup_timeout_seconds", "shutdown_timeout_seconds"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 0, -1])
def test_provider_start_spec_rejects_non_finite_or_non_positive_timeouts(
    tmp_path: Path,
    field: str,
    value: float,
) -> None:
    with pytest.raises(ValueError, match="timeout"):
        replace(_start(tmp_path), **{field: value})


def test_task_event_defensively_copies_details_and_rejects_sensitive_fields() -> None:
    caller = {"sequence": 1}
    event = TaskEvent(
        task_id="task-1", session_id="session-1", provider="fake",
        provider_version="1.0.0", task_protocol_version=1,
        provider_contract_version=1, timestamp=NOW,
        type=EventType.TASK_ACCEPTED, state=TaskState.QUEUED, details=caller,
    )
    caller["prompt"] = "secret"
    assert dict(event.details) == {"sequence": 1}
    with pytest.raises(TypeError):
        event.details["secret"] = "value"
    with pytest.raises(ValueError, match="event detail"):
        TaskEvent(
            task_id="t", session_id="s", provider="p", provider_version="1",
            task_protocol_version=1, provider_contract_version=1, timestamp=NOW,
            type=EventType.TASK_ACCEPTED, state=TaskState.QUEUED,
            details={"source_code": "print('secret')"},
        )


def test_fake_provider_startup_and_ordered_success(tmp_path: Path) -> None:
    provider = _provider()
    handle = provider.start(_start(tmp_path))
    session = provider.create_session(handle, TaskSpec("task-1", "private prompt"))
    events = list(provider.stream_events(handle, session))
    assert [event.type.value for event in events] == [
        "task.accepted", "plan.ready", "tool.requested", "tool.completed",
        "test.completed", "artifact.created", "task.finished",
    ]
    assert events[-1].state is TaskState.SUCCEEDED
    assert all(event.task_protocol_version == event.provider_contract_version == 1 for event in events)
    assert "private prompt" not in repr(events)


def test_fake_provider_cancellation_finishes_cancelled(tmp_path: Path) -> None:
    provider = _provider()
    handle = provider.start(_start(tmp_path))
    session = provider.create_session(handle, TaskSpec("task-1", "private"))
    assert provider.cancel(handle, session).state is TaskState.CANCELLED
    events = list(provider.stream_events(handle, session))
    assert [(event.type, event.state) for event in events] == [(EventType.TASK_FINISHED, TaskState.CANCELLED)]


@pytest.mark.parametrize(
    ("outcome", "terminal"),
    [(FakeOutcome.FAIL, TaskState.FAILED), (FakeOutcome.BLOCK, TaskState.BLOCKED)],
)
def test_fake_provider_abnormal_outcomes(tmp_path: Path, outcome: FakeOutcome, terminal: TaskState) -> None:
    provider = _provider(outcome)
    handle = provider.start(_start(tmp_path))
    session = provider.create_session(handle, TaskSpec("task-1", "private"))
    events = list(provider.stream_events(handle, session))
    assert events[-1].state is terminal
    assert events[-1].type in {EventType.TASK_BLOCKED, EventType.TASK_FINISHED}


def test_fake_provider_stop_cleans_handles_and_sessions(tmp_path: Path) -> None:
    provider = _provider()
    handle = provider.start(_start(tmp_path))
    provider.create_session(handle, TaskSpec("task-1", "private"))
    assert provider.stop(handle).state is TaskState.SUCCEEDED
    assert provider.live_handle_count == provider.live_session_count == 0
    assert provider.stop(handle).state is TaskState.SUCCEEDED


def test_fake_provider_stop_clears_cancellation_marker_before_id_reuse(tmp_path: Path) -> None:
    values = iter(("handle-1", "session-reused", "handle-2", "session-reused"))
    provider = FakeProvider(clock=lambda: NOW, id_factory=lambda: next(values))
    start_spec = _start(tmp_path)

    first_handle = provider.start(start_spec)
    first_session = provider.create_session(first_handle, TaskSpec("task-1", "private"))
    provider.cancel(first_handle, first_session)
    provider.stop(first_handle)

    second_handle = provider.start(start_spec)
    second_session = provider.create_session(second_handle, TaskSpec("task-2", "private"))
    events = list(provider.stream_events(second_handle, second_session))

    assert second_session.session_id == first_session.session_id
    assert events[-1].state is TaskState.SUCCEEDED
