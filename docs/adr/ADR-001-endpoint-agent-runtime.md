# ADR-001: Endpoint Agent Runtime and Protocol Boundaries

- Status: Accepted
- Date: 2026-07-16

## Context

Skillify needs an endpoint agent that can execute agent tasks on a user's machine while preserving a clear separation between centralized orchestration and local execution. The architecture must reuse the existing command-line entry point, allow the first provider integration to evolve without coupling the control plane to provider details, and avoid turning local capabilities into unnecessary remote interfaces.

The endpoint-to-control-plane task protocol and the endpoint-to-provider adapter contract evolve at different boundaries and may change on different schedules. Their versions therefore need to be explicit and independent from the first release.

Acceptance also spans two evidence classes. Offline compilation and unit tests can validate deterministic behavior without a real provider or external system, while the G1-G8 execution-plan gates require real-machine evidence in a designated `[test-env]`. This ADR distinguishes those claims so offline evidence cannot be presented as real-environment acceptance.

## Decision

### 1. Extend the existing Python `skillctl`

The endpoint agent will extend the existing Python `skillctl`. Skillify will not create an overlapping CLI and will not change the implementation language for this work.

### 2. Integrate OpenCode first through an isolated Provider Adapter

OpenCode is the first provider. Its integration must sit behind an isolated Provider Adapter so provider-specific process invocation, configuration, events, and failures do not leak into the task protocol or control-plane model.

A Claude Code Provider must not be implemented before the G1 `[test-env]` gate passes. Passing offline compilation or unit tests does not satisfy that prerequisite.

### 3. Keep execution local and make Skillify the control plane

Execution remains on the endpoint. The Skillify server is the control plane: it may assign work and receive status or results through the task protocol, but it does not execute against the endpoint's local environment.

The endpoint initiates outbound connectivity to the server. The architecture must not require inbound ports on the endpoint, and the server must not access, resolve, mount, or otherwise operate on endpoint-local paths.

### 4. Preserve native local tools; use MCP selectively

OpenCode's native file, Shell, Git, and test tools remain native. MCP is preferred for external systems and reusable governed capabilities where a shared interface, authorization boundary, or policy enforcement is valuable. MCP is not the default wrapper for every local tool.

## Protocol Versioning and Compatibility

The two boundaries are versioned independently:

```yaml
task_protocol_version: 1
provider_contract_version: 1
```

`task_protocol_version` governs communication between the endpoint and the Skillify control plane. `provider_contract_version` governs the internal contract between the endpoint runtime and a Provider Adapter. A change to one does not imply a change to the other.

The initial release is v1-only for both protocols. Once a v2 of either protocol exists, an endpoint must support the current version and the immediately previous version of that protocol. For example, an endpoint whose current task protocol is v2 supports task protocol v2 and v1; this rule does not require provider contract v2 to exist or change. Versions older than the immediately previous version are unsupported unless a later ADR explicitly grants an exception.

Connections or adapters with no mutually supported version must fail closed with a clear incompatibility error; they must not silently reinterpret a payload or contract. Compatibility behavior must be covered by offline unit tests, while real endpoint/provider interoperability remains subject to the applicable `[test-env]` gate.

## Security, Privacy, and Trust Boundaries

- The endpoint is the execution and local-data trust boundary. Local paths, source trees, credentials, tool configuration, and process access remain endpoint concerns.
- The Skillify server is trusted as a control plane for task assignment and receipt of intentionally returned status or results. That trust does not grant the server direct access to endpoint filesystems or local paths.
- Connectivity is endpoint-initiated and outbound. No design or deployment may depend on exposing an inbound endpoint port.
- Provider Adapters are inside the endpoint boundary but are isolated from the control-plane protocol. They receive only the context and capabilities required to execute the assigned task.
- Data sent to the control plane or an external system must be explicit and minimized to the task's needs. Local availability does not imply permission to transmit.
- External systems and reusable governed capabilities should be reached through explicit interfaces, with authorization and policy enforced at their boundary; their presence must not weaken the endpoint/control-plane separation.

## Offline and `[test-env]` Boundaries

Offline compile checks and unit tests are Dev-DoD. They must not require a real OpenCode installation, live network service, credentials, or another external system. External-system and provider interactions in this test class require dependency injection and Fakes.

G1-G8 real-machine gates are `[test-env]` gates. Evidence for such a gate must come from its required real environment and cannot be replaced by Fakes or offline unit results.

In particular, this ADR does not claim G1 real OpenCode/Linux acceptance. It records the architecture and evidence boundaries only. It also does not, by itself, approve or complete any OSS or security artifact, including licensing, disclosure, supply-chain, or threat-model work.

## Consequences

### Positive

- Users get one CLI surface and the project retains its existing Python implementation investment.
- The control-plane/task protocol remains independent of OpenCode-specific behavior, making provider evolution and testing more contained.
- Endpoint-initiated connectivity avoids an inbound endpoint attack surface and supports machines that cannot accept inbound connections.
- Local tools retain their native semantics and performance, while MCP is reserved for boundaries where governance or reuse justifies it.
- Independent protocol versions make compatibility claims precise and allow either boundary to evolve without unnecessary coordinated upgrades.
- Dev-DoD can run deterministically offline, while `[test-env]` gates preserve credible evidence for real integrations.

### Costs and Constraints

- The endpoint must maintain version negotiation and, after a v2 exists, compatibility code for two versions of each independently evolving protocol.
- Provider Adapter isolation adds an interface and translation layer that must be maintained and tested.
- Outbound-only operation requires the control plane to deliver work over endpoint-initiated sessions rather than direct server callbacks.
- Any feature that needs local data must execute locally or receive an explicit, minimized result; server-side convenience cannot bypass the trust boundary.
- Additional providers are sequenced behind demonstrated OpenCode viability at G1 `[test-env]`, delaying parallel provider implementation.

## Rejected Alternatives

### Create a second endpoint CLI or change implementation language

Rejected because it would overlap `skillctl`, fragment installation and user workflows, and duplicate runtime concerns without a demonstrated need.

### Put OpenCode details directly in the task protocol

Rejected because it would couple the Skillify control plane and endpoint task model to one provider, making protocol evolution and future provider support harder.

### Implement Claude Code in parallel before G1

Rejected because it would expand the provider surface before the first real OpenCode/Linux path has passed its `[test-env]` gate and would obscure whether the abstraction is grounded in working evidence.

### Execute on the server or let the server access endpoint paths

Rejected because it breaks the local execution and privacy boundary, gives server-side components capabilities over local state, and makes endpoint-local path semantics part of the control plane.

### Require inbound endpoint ports

Rejected because it increases deployment friction and attack surface and is incompatible with the endpoint-initiated connectivity decision.

### Wrap every local tool with MCP

Rejected because it would replace native file, Shell, Git, and test behavior with extra indirection where no external-system or governed-capability boundary requires it.

### Treat offline tests as real-machine acceptance

Rejected because Fakes and deterministic unit tests demonstrate Dev-DoD, not the behavior of real OpenCode, Linux, credentials, networks, or external systems.

### Use a single shared version for both protocol boundaries

Rejected because the control-plane task protocol and Provider Adapter contract have different consumers and evolution schedules; one version would force unrelated upgrades or make compatibility claims ambiguous.

## Supersession and Change Process

This ADR is normative until superseded by a later accepted ADR. A change to any of the four architecture decisions, either protocol's versioning or compatibility policy, the security/privacy boundary, or the offline/`[test-env]` evidence boundary requires a new ADR that:

1. identifies this ADR as superseded in whole or in specified parts;
2. states the rationale, migration and rollback implications, and affected trust boundaries;
3. versions `task_protocol_version` and `provider_contract_version` separately, incrementing only the boundary whose incompatible contract changes;
4. defines compatibility and negotiation behavior for rollout, including the current-plus-immediately-previous support window once v2 exists; and
5. identifies the Dev-DoD and `[test-env]` evidence required before the change is accepted for release.

Editorial clarifications that do not change behavior or obligations may update this ADR in place. Such edits must not be used to introduce a new architectural decision, weaken a trust boundary, or claim a gate has passed.
