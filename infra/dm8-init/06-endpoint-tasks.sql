-- Skillify endpoint task control-plane tables (Task protocol v1).
-- Apply in the shared Skillify DM8 business schema. SQLite remains the Dev-DoD target.

CREATE TABLE endpoint_bindings (
    endpoint_id       VARCHAR(128) NOT NULL,
    owner_username    VARCHAR(255) NOT NULL,
    label             VARCHAR(128) NOT NULL,
    online            BIT DEFAULT 0 NOT NULL,
    workspace_aliases CLOB NOT NULL,
    last_seen_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_endpoint_bindings PRIMARY KEY (endpoint_id)
);
CREATE INDEX ix_endpoint_bindings_owner ON endpoint_bindings (owner_username);

CREATE TABLE endpoint_tasks (
    task_id          VARCHAR(128) NOT NULL,
    endpoint_id      VARCHAR(128) NOT NULL,
    owner_username   VARCHAR(255) NOT NULL,
    workflow_id      VARCHAR(128) NOT NULL,
    workflow_version VARCHAR(64)  NOT NULL,
    workspace_alias  VARCHAR(64)  NOT NULL,
    inputs            CLOB         NOT NULL,
    envelope_json    CLOB,
    state            VARCHAR(32)  NOT NULL,
    state_version    INT DEFAULT 0 NOT NULL,
    revoked          BIT DEFAULT 0 NOT NULL,
    approval_required BIT DEFAULT 1 NOT NULL,
    issued_at        TIMESTAMP WITH TIME ZONE,
    expires_at       TIMESTAMP WITH TIME ZONE,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_endpoint_tasks PRIMARY KEY (task_id)
);
CREATE INDEX ix_endpoint_tasks_endpoint_state ON endpoint_tasks (endpoint_id, state);

CREATE TABLE endpoint_task_nonces (
    nonce       VARCHAR(128) NOT NULL,
    task_id     VARCHAR(128) NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_endpoint_task_nonces PRIMARY KEY (nonce)
);
CREATE INDEX ix_endpoint_task_nonces_task ON endpoint_task_nonces (task_id);

CREATE TABLE endpoint_task_events (
    id             INT IDENTITY(1, 1) NOT NULL,
    task_id        VARCHAR(128) NOT NULL,
    event_type     VARCHAR(64) NOT NULL,
    occurred_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    summary        VARCHAR(500),
    artifacts      CLOB NOT NULL,
    failure_reason VARCHAR(128),
    CONSTRAINT pk_endpoint_task_events PRIMARY KEY (id)
);
CREATE INDEX ix_endpoint_task_events_task ON endpoint_task_events (task_id);
