-- Expand-only endpoint task runtime and lease migration.

ALTER TABLE endpoint_tasks ADD runtime VARCHAR(32) DEFAULT 'opencode' NOT NULL;
ALTER TABLE endpoint_tasks ADD lease_owner VARCHAR(128);
ALTER TABLE endpoint_tasks ADD lease_expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE endpoint_tasks ADD heartbeat_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE endpoint_task_events ADD event_id VARCHAR(128);
ALTER TABLE endpoint_task_events ADD test_summary CLOB;
ALTER TABLE endpoint_task_events ADD diff_stats CLOB;
ALTER TABLE endpoint_task_events ADD CONSTRAINT uq_endpoint_task_events_event_id UNIQUE (event_id);

COMMIT;
