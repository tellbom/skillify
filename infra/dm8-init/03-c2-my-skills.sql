-- =============================================================================
-- Skillify 业务库 · DM8（达梦）增量脚本 03 · C-2 我的 Skill（发布任务可见性）
-- -----------------------------------------------------------------------------
-- 对应 ORM：src/skillify/index/models.py 的 SkillPublishJob。
-- 前置：已执行 01-skillify-schema.sql、02-c1-version-center.sql。
--
-- 【与 01 一致的类型/语义提示，适用于本文件新表】
--   - 带时区时间戳（created_at/updated_at）→ TIMESTAMP WITH TIME ZONE。
--   - 自增主键（id）              → IDENTITY(1,1)。
--   - 若实例被设成 Oracle 兼容模式（COMPATIBLE_MODE 非 0），空串会被当成 NULL——本表
--     error_message 本身允许 NULL（无 DEFAULT ''），不受此风险影响；namespace/name/
--     version/initiator/status 均 NOT NULL 且始终由应用层写入非空值，同样不受影响。
--   - 保留字风险列（name/version）→ 沿用 01 文末"保留字回退方案"，如需加引号需同步
--     两列且后端 DM8 SQLAlchemy 方言配置保持大小写一致。
--
-- 【语义】skill_publish_jobs 记录"谁在什么时候尝试发布了哪个 namespace/name/version，
-- 结果如何"——是 Web 上传失败后"我的失败发布"列表的数据来源，不依赖扫描 Forgejo 全量
-- 仓库找 draft release（那样在多 namespace 场景下不可行）。UNIQUE(namespace, name,
-- version, initiator) 意味着同一用户重试同一个版本时更新自己的状态；不同用户的
-- 尝试分别保留，不能覆盖 namespace owner 的发布结果。
-- =============================================================================

CREATE TABLE skill_publish_jobs (
    id            INT           IDENTITY(1, 1) NOT NULL,
    namespace     VARCHAR(64)   NOT NULL,
    name          VARCHAR(64)   NOT NULL,
    version       VARCHAR(64)   NOT NULL,
    initiator     VARCHAR(255)  NOT NULL,       -- 发起人 Keycloak preferred_username/sub
    status        VARCHAR(16)   NOT NULL,       -- "succeeded" | "failed"
    error_message VARCHAR(2000),                -- 可空：仅 failed 时有意义
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_publish_jobs PRIMARY KEY (id),
    CONSTRAINT uq_skill_publish_job_identity UNIQUE (namespace, name, version, initiator)
);
CREATE INDEX ix_skill_publish_jobs_namespace ON skill_publish_jobs (namespace);
CREATE INDEX ix_skill_publish_jobs_name      ON skill_publish_jobs (name);
CREATE INDEX ix_skill_publish_jobs_initiator ON skill_publish_jobs (initiator);

-- 【验证清单】导入后执行以确认结构就绪：
--   SELECT COUNT(*) FROM skill_publish_jobs;      -- 应为 0，且不报错
--   INSERT INTO skill_publish_jobs(namespace,name,version,initiator,status,created_at,updated_at)
--     VALUES('demo','hello','0.1.0','jane','failed', SYSTIMESTAMP, SYSTIMESTAMP);
--   UPDATE skill_publish_jobs SET status='succeeded', error_message=NULL, updated_at=SYSTIMESTAMP
--     WHERE namespace='demo' AND name='hello' AND version='0.1.0';
--   SELECT status, error_message FROM skill_publish_jobs WHERE namespace='demo';  -- 应为 succeeded/NULL，仍只有 1 行
--   DELETE FROM skill_publish_jobs WHERE namespace='demo';
-- =============================================================================
