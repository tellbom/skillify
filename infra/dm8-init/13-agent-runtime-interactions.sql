-- Official Agent SDK hosting: durable worker/session/event/decision control plane.
CREATE TABLE agent_worker_runs (
    worker_run_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    team_run_id VARCHAR(128),
    worker_id VARCHAR(128) NOT NULL,
    work_package_id VARCHAR(128),
    provider VARCHAR(32) NOT NULL,
    workspace VARCHAR(1000) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    required BIT DEFAULT 1 NOT NULL,
    depends_on CLOB,
    gate_status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    gate_result CLOB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_agent_worker_runs PRIMARY KEY (worker_run_id),
    CONSTRAINT uq_agent_worker_task UNIQUE (task_id, worker_id)
);
CREATE INDEX ix_agent_worker_task ON agent_worker_runs(task_id);
CREATE INDEX ix_agent_worker_team ON agent_worker_runs(team_run_id);

CREATE TABLE provider_sessions (
    session_record_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    team_run_id VARCHAR(128),
    worker_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_session_id VARCHAR(255) NOT NULL,
    runtime_instance_id VARCHAR(128) NOT NULL,
    endpoint_id VARCHAR(128) NOT NULL,
    workspace VARCHAR(1000) NOT NULL,
    status VARCHAR(32) DEFAULT 'starting' NOT NULL,
    last_event_sequence INT DEFAULT 0 NOT NULL,
    resume_metadata CLOB,
    pending_interaction_id VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_provider_sessions PRIMARY KEY (session_record_id),
    CONSTRAINT uq_provider_session UNIQUE (provider, provider_session_id),
    CONSTRAINT uq_provider_session_worker UNIQUE (task_id, worker_id)
);
CREATE INDEX ix_provider_session_task ON provider_sessions(task_id);
CREATE INDEX ix_provider_session_team ON provider_sessions(team_run_id);
CREATE INDEX ix_provider_session_endpoint ON provider_sessions(endpoint_id);

CREATE TABLE agent_runtime_events (
    id BIGINT IDENTITY(1, 1) PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL,
    sequence INT NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    team_run_id VARCHAR(128),
    worker_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_session_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload CLOB,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_agent_runtime_event_id UNIQUE (event_id),
    CONSTRAINT uq_agent_runtime_session_sequence UNIQUE (provider_session_id, sequence)
);
CREATE INDEX ix_agent_runtime_event_task ON agent_runtime_events(task_id);
CREATE INDEX ix_agent_runtime_event_session ON agent_runtime_events(provider_session_id);

CREATE TABLE agent_interactions (
    interaction_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    team_run_id VARCHAR(128),
    worker_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_session_id VARCHAR(255) NOT NULL,
    provider_request_id VARCHAR(255) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description VARCHAR(2000),
    choices CLOB,
    allow_free_text BIT DEFAULT 0 NOT NULL,
    status VARCHAR(32) DEFAULT 'requested' NOT NULL,
    response_choice VARCHAR(255),
    response_answer VARCHAR(4000),
    response_comment VARCHAR(2000),
    response_version INT DEFAULT 0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    responded_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    applied_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_agent_interactions PRIMARY KEY (interaction_id),
    CONSTRAINT uq_agent_interaction_provider_request
        UNIQUE (provider_session_id, provider_request_id)
);
CREATE INDEX ix_agent_interaction_task ON agent_interactions(task_id);
CREATE INDEX ix_agent_interaction_team ON agent_interactions(team_run_id);
COMMIT;
