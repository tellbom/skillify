-- Skillify endpoint task control-plane tables (Task protocol v1).
-- Apply in the shared Skillify DM8 business schema. SQLite remains the Dev-DoD target.

CREATE TABLE endpoint_tasks (
    task_id          VARCHAR(128) NOT NULL,
    endpoint_id      VARCHAR(128) NOT NULL,
    workflow_id      VARCHAR(128) NOT NULL,
    workflow_version VARCHAR(64)  NOT NULL,
    workspace_alias  VARCHAR(64)  NOT NULL,
    envelope_json    CLOB         NOT NULL,
    state            VARCHAR(32)  NOT NULL,
    state_version    INT DEFAULT 0 NOT NULL,
    revoked          BIT DEFAULT 0 NOT NULL,
    issued_at        TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at       TIMESTAMP WITH TIME ZONE NOT NULL,
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
