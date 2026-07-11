-- =============================================================================
-- Skillify 业务库 · DM8（达梦）增量脚本 04 · C-5 社区（Star / 订阅 / 评论回复与软删）
-- -----------------------------------------------------------------------------
-- 对应 ORM：src/skillify/index/models.py 的 SkillStar、SkillSubscription、
-- SkillComment（新增 parent_id / deleted 两列）。
-- 前置：已执行 01-skillify-schema.sql、02-c1-version-center.sql、03-c2-my-skills.sql。
--
-- 【与 01 一致的类型/语义提示，适用于本文件新表/新列】
--   - 带时区时间戳（created_at）      → TIMESTAMP WITH TIME ZONE。
--   - 自增主键（id）                  → IDENTITY(1,1)。
--   - 布尔列（deleted）               → BIT（0/1），不可空，必须带 DEFAULT，历史行统一
--     回填 0（未删除）。
--   - 保留字风险列（name）            → 沿用 01 文末"保留字回退方案"，如需加引号需同步
--     后端 DM8 SQLAlchemy 方言配置保持大小写一致。
--   - 若实例被设成 Oracle 兼容模式（COMPATIBLE_MODE 非 0），空串会被当成 NULL——本文件
--     所有 NOT NULL 列均无空串 DEFAULT（''），不受此风险影响。
--
-- 【无外键约束】parent_id 是 skill_comments 对自身的自引用（NULL=顶层评论），本文件
-- 沿用 skill_comments 现有的"不加外键"约定（01 头注释已说明整份 schema 都不用外键），
-- parent 合法性（同一 (namespace, name) 下）完全在应用层校验
-- （见 src/skillify/index/comments.py::add_comment）。
-- =============================================================================


-- 6) skill_stars —— 存在即已 star，一 (namespace, name, author) 一行（C-5）
CREATE TABLE skill_stars (
    id         INT           IDENTITY(1, 1) NOT NULL,
    namespace  VARCHAR(64)   NOT NULL,
    name       VARCHAR(64)   NOT NULL,
    author     VARCHAR(255)  NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_stars PRIMARY KEY (id),
    CONSTRAINT uq_skill_star_identity UNIQUE (namespace, name, author)
);
CREATE INDEX ix_skill_stars_namespace ON skill_stars (namespace);
CREATE INDEX ix_skill_stars_name      ON skill_stars (name);


-- 7) skill_subscriptions —— 存在即已订阅新版本，结构同 skill_stars（C-5）
CREATE TABLE skill_subscriptions (
    id         INT           IDENTITY(1, 1) NOT NULL,
    namespace  VARCHAR(64)   NOT NULL,
    name       VARCHAR(64)   NOT NULL,
    author     VARCHAR(255)  NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_subscriptions PRIMARY KEY (id),
    CONSTRAINT uq_skill_subscription_identity UNIQUE (namespace, name, author)
);
CREATE INDEX ix_skill_subscriptions_namespace ON skill_subscriptions (namespace);
CREATE INDEX ix_skill_subscriptions_name      ON skill_subscriptions (name);


-- 8) skill_comments 增列 —— 回复（parent_id，自引用，无外键）+ 软删（deleted）（C-5）
ALTER TABLE skill_comments ADD COLUMN parent_id INT;
ALTER TABLE skill_comments ADD COLUMN deleted BIT DEFAULT 0 NOT NULL;

-- 【验证清单】导入后执行以确认结构就绪：
--   SELECT COUNT(*) FROM skill_stars;             -- 应为 0，且不报错
--   INSERT INTO skill_stars(namespace,name,author,created_at)
--     VALUES('demo','hello','jane', SYSTIMESTAMP);
--   SELECT COUNT(*) FROM skill_stars WHERE namespace='demo';  -- 应为 1
--   DELETE FROM skill_stars WHERE namespace='demo';
--
--   SELECT COUNT(*) FROM skill_subscriptions;     -- 应为 0，且不报错
--   INSERT INTO skill_subscriptions(namespace,name,author,created_at)
--     VALUES('demo','hello','jane', SYSTIMESTAMP);
--   DELETE FROM skill_subscriptions WHERE namespace='demo';
--
--   SELECT parent_id, deleted FROM skill_comments;  -- 历史行应为 NULL / 0，且不报错
--   INSERT INTO skill_comments(namespace,name,author,body,created_at)
--     VALUES('demo','hello','jane','top-level comment', SYSTIMESTAMP);
--   INSERT INTO skill_comments(namespace,name,author,body,created_at,parent_id)
--     VALUES('demo','hello','bob','a reply',
--            SYSTIMESTAMP, (SELECT MIN(id) FROM skill_comments WHERE namespace='demo'));
--   UPDATE skill_comments SET deleted = 1 WHERE namespace='demo' AND author='jane';
--   SELECT id, parent_id, deleted FROM skill_comments WHERE namespace='demo';  -- 2 行，
--     软删行 deleted=1，回复行 parent_id 指向被软删的顶层评论 id（树结构仍完整）
--   DELETE FROM skill_comments WHERE namespace='demo';
-- =============================================================================
