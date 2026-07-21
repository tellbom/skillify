-- Persist the Workflow Pack delegation declaration selected when a task is dispatched.

ALTER TABLE endpoint_tasks ADD delegation_mode VARCHAR(16) DEFAULT 'suggested' NOT NULL;
