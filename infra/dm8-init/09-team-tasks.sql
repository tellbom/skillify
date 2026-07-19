-- Expand-only Shogun team runtime metadata. Team remains disabled until test-env gates pass.

ALTER TABLE endpoint_tasks ADD execution_mode VARCHAR(16) DEFAULT 'single' NOT NULL;
ALTER TABLE endpoint_tasks ADD collaboration_runtime VARCHAR(32);
ALTER TABLE endpoint_tasks ADD preferred_cli VARCHAR(32);
ALTER TABLE endpoint_tasks ADD team_policy CLOB;

ALTER TABLE endpoint_task_events ADD worker_id VARCHAR(128);
ALTER TABLE endpoint_task_events ADD work_package_id VARCHAR(128);
ALTER TABLE endpoint_task_events ADD stage VARCHAR(64);

ALTER TABLE endpoint_work_packages ADD depends_on CLOB;
ALTER TABLE endpoint_work_packages ADD read_only BIT DEFAULT 0 NOT NULL;
ALTER TABLE endpoint_work_packages ADD verification CLOB;

CREATE TABLE endpoint_team_tasks (
    task_id VARCHAR(128) NOT NULL,
    execution_mode VARCHAR(16) DEFAULT 'team' NOT NULL,
    collaboration_runtime VARCHAR(32) DEFAULT 'shogun' NOT NULL,
    preferred_cli VARCHAR(32) NOT NULL,
    team_policy CLOB NOT NULL,
    state VARCHAR(32) DEFAULT 'pending' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_endpoint_team_tasks PRIMARY KEY (task_id)
);

CREATE TABLE endpoint_team_worker_events (
    id BIGINT IDENTITY(1, 1) PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    worker_id VARCHAR(128),
    work_package_id VARCHAR(128),
    stage VARCHAR(64),
    summary VARCHAR(500),
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_team_worker_event_id UNIQUE (event_id)
);

CREATE INDEX idx_team_worker_events_task ON endpoint_team_worker_events(task_id);
COMMIT;
