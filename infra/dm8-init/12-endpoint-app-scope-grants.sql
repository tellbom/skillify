-- T4: auditable, task-scoped endpoint confirmations for App directory expansion/upload.
CREATE TABLE endpoint_task_scope_grants (
    id           INT IDENTITY(1, 1) NOT NULL,
    task_id      VARCHAR(128) NOT NULL,
    endpoint_id  VARCHAR(128) NOT NULL,
    purpose      VARCHAR(32) NOT NULL,
    aliases      CLOB NOT NULL,
    confirmed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_endpoint_task_scope_grants PRIMARY KEY (id),
    CONSTRAINT uq_endpoint_task_scope_grant UNIQUE (task_id, purpose)
);
CREATE INDEX ix_endpoint_scope_task ON endpoint_task_scope_grants (task_id);
CREATE INDEX ix_endpoint_scope_endpoint ON endpoint_task_scope_grants (endpoint_id);
