-- =============================================================================
-- Skillify 业务库 · DM8（达梦）一键初始化脚本（空表起步，无历史数据）
-- -----------------------------------------------------------------------------
-- 对应 ORM：src/skillify/index/models.py 的 5 张业务表。
-- 用途：共享 DM8 上以 Skillify 专用用户/schema 直接导入本脚本即可建表。
--
-- 【执行前提】（由建库/建用户环节保证，本脚本不涉及权限与密码）
--   1. 实例字符集 UTF-8；强烈建议开启“字符长度语义”（建库参数 LENGTH_IN_CHAR=1），
--      否则 VARCHAR(n) 按【字节】计，中文 description/body 会因 3 字节/字而放不下。
--   2. 使用 DM8 【默认 DM 兼容模式】（COMPATIBLE_MODE=0）。若实例被设成 Oracle 兼容模式，
--      空串 '' 会被当成 NULL，与下方 DEFAULT '' NOT NULL 冲突——此时把
--      description/author/release_url 去掉 NOT NULL 或去掉 DEFAULT 即可。
--   3. 以 Skillify 专用用户登录后执行（对象落在该用户同名 schema 下）。
--
-- 【与 PostgreSQL 版的差异，已在列级注释标出】
--   - JSON 列（tags/orchestration）→ CLOB 文本存储（应用侧 SQLAlchemy JSON 序列化）
--   - 布尔列（success）           → BIT（0/1，可空）
--   - 带时区时间戳（*_at）        → TIMESTAMP WITH TIME ZONE
--   - 自增主键（id）              → IDENTITY(1,1)
--   - 保留字风险列（name/version）→ 见文末“保留字回退方案”
-- =============================================================================

-- 可选：若 schema 尚未预置，取消注释（通常由建库账号完成，普通业务用户无权执行）
-- CREATE SCHEMA SKILLIFY;
-- SET SCHEMA SKILLIFY;


-- 1) skill_index —— 检索元数据 / 多版本索引（T2.2）
CREATE TABLE skill_index (
    id            INT           IDENTITY(1, 1) NOT NULL,
    namespace     VARCHAR(64)   NOT NULL,
    name          VARCHAR(64)   NOT NULL,
    version       VARCHAR(64)   NOT NULL,
    description   VARCHAR(500)  DEFAULT '' NOT NULL,
    author        VARCHAR(255)  DEFAULT '' NOT NULL,
    tags          CLOB          NOT NULL,   -- JSON 数组，文本存储
    checksum      VARCHAR(64)   NOT NULL,
    release_url   VARCHAR(1024) DEFAULT '' NOT NULL,
    published_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    orchestration CLOB          NOT NULL,   -- JSON 对象，文本存储
    CONSTRAINT pk_skill_index PRIMARY KEY (id),
    CONSTRAINT uq_skill_index_identity UNIQUE (namespace, name, version)
);
CREATE INDEX ix_skill_index_namespace ON skill_index (namespace);
CREATE INDEX ix_skill_index_name      ON skill_index (name);


-- 2) skill_comments —— 平铺评论（T5.1）
CREATE TABLE skill_comments (
    id         INT           IDENTITY(1, 1) NOT NULL,
    namespace  VARCHAR(64)   NOT NULL,
    name       VARCHAR(64)   NOT NULL,
    author     VARCHAR(255)  NOT NULL,          -- Keycloak preferred_username/sub
    body       VARCHAR(4000) NOT NULL,          -- 需字符长度语义，否则中文长评论放不下
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_comments PRIMARY KEY (id)
);
CREATE INDEX ix_skill_comments_namespace ON skill_comments (namespace);
CREATE INDEX ix_skill_comments_name      ON skill_comments (name);


-- 3) skill_ratings —— 每(用户,skill)一条 1-5 评分，重复评分就地更新（T5.2）
CREATE TABLE skill_ratings (
    id         INT          IDENTITY(1, 1) NOT NULL,
    namespace  VARCHAR(64)  NOT NULL,
    name       VARCHAR(64)  NOT NULL,
    author     VARCHAR(255) NOT NULL,
    score      INT          NOT NULL,           -- 1..5，取值校验在应用层
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_ratings PRIMARY KEY (id),
    CONSTRAINT uq_skill_rating_identity UNIQUE (namespace, name, author)
);
CREATE INDEX ix_skill_ratings_namespace ON skill_ratings (namespace);
CREATE INDEX ix_skill_ratings_name      ON skill_ratings (name);


-- 4) skill_namespace_owners —— Web 上传 namespace 首占用归属（M-C）
CREATE TABLE skill_namespace_owners (
    namespace      VARCHAR(64)  NOT NULL,
    owner_username VARCHAR(255) NOT NULL,       -- 首次上传者 Keycloak preferred_username/sub
    claimed_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_namespace_owners PRIMARY KEY (namespace)
);


-- 5) skill_events —— 安装计数 + client->server 运行上报 stub（T5.2 / T6.2）
CREATE TABLE skill_events (
    id          INT          IDENTITY(1, 1) NOT NULL,
    namespace   VARCHAR(64)  NOT NULL,
    name        VARCHAR(64)  NOT NULL,
    version     VARCHAR(64)  NOT NULL,
    event_type  VARCHAR(16)  NOT NULL,          -- "install" | "run"
    success     BIT,                            -- 布尔，可空（仅 "run" 有意义）
    machine_id  VARCHAR(128),                   -- 可空，客户端自生成的不透明机器标识
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_skill_events PRIMARY KEY (id)
);
CREATE INDEX ix_skill_events_namespace  ON skill_events (namespace);
CREATE INDEX ix_skill_events_name       ON skill_events (name);
CREATE INDEX ix_skill_events_event_type ON skill_events (event_type);


-- =============================================================================
-- 【保留字回退方案】
-- 若上面 CREATE 因 name / version 被 DM8 视为保留字而报错，用双引号包裹这两列，
-- 例如：  "name" VARCHAR(64) NOT NULL,   "version" VARCHAR(64) NOT NULL,
-- 唯一约束与索引也同步改成 "name" / "version"。
-- ⚠️ 一旦加引号，列名将区分大小写并固定为小写；必须让后端 DM8 SQLAlchemy 方言
--    同样以带引号小写形式引用（保持大小写一致），否则运行期会“找不到列”。
-- 建议顺序：先不加引号导入；仅在报保留字错误时再改这两列并同步后端方言配置。
--
-- 【验证清单】导入后执行以确认结构就绪：
--   SELECT COUNT(*) FROM skill_index;            -- 应为 0，且不报错
--   INSERT INTO skill_index(namespace,name,version,tags,checksum,published_at,orchestration)
--     VALUES('demo','hello','0.1.0','[]','x', SYSTIMESTAMP, '{}');
--   SELECT tags, orchestration, published_at FROM skill_index;  -- 往返读取一致
--   DELETE FROM skill_index WHERE namespace='demo';
-- =============================================================================
