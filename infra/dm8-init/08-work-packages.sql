CREATE TABLE endpoint_work_packages (
    id BIGINT IDENTITY(1, 1) PRIMARY KEY,
    package_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    objective VARCHAR(1000) NOT NULL,
    allowed_paths CLOB NOT NULL,
    dependencies CLOB NOT NULL,
    access VARCHAR(16) NOT NULL,
    recommended_skills CLOB NOT NULL,
    recommended_mcp CLOB NOT NULL,
    acceptance_commands CLOB NOT NULL,
    parallelizable BIT DEFAULT 0 NOT NULL,
    confirmed BIT DEFAULT 0 NOT NULL,
    CONSTRAINT uq_work_package_identity UNIQUE (task_id, package_id)
);

CREATE INDEX idx_work_packages_task ON endpoint_work_packages(task_id);
COMMIT;
