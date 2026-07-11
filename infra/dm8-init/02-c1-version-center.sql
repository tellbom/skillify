-- =============================================================================
-- Skillify 业务库 · DM8（达梦）增量脚本 02 · C-1 版本中心（yanked 标记）
-- -----------------------------------------------------------------------------
-- 对应 ORM：src/skillify/index/models.py 的 SkillIndexEntry.yanked。
-- 前置：已执行 01-skillify-schema.sql（skill_index 表已存在）。
--
-- 【与 01 一致的类型/语义提示，适用于本文件新增列】
--   - 布尔列（yanked）→ BIT（0/1），本列不可空，必须带 DEFAULT，历史行统一回填 0（未 yank）。
--   - 若实例被设成 Oracle 兼容模式（COMPATIBLE_MODE 非 0），空串/NULL 语义与 01 头注释描述
--     的风险不适用于本列（BIT 列不涉及空串问题），无需额外处理。
--
-- 【变更说明不落库】release notes / 版本变更说明不新增列存储——改动说明直接从 Forgejo
-- release body 现取（见 src/skillify/publish/forgejo_client.py::Release.body），这里
-- 只新增一个状态位。
-- =============================================================================

ALTER TABLE skill_index ADD COLUMN yanked BIT DEFAULT 0 NOT NULL;

-- 【验证清单】导入后执行以确认结构就绪：
--   SELECT yanked FROM skill_index;              -- 应全部返回 0，且不报错
--   UPDATE skill_index SET yanked = 1 WHERE id = (SELECT MIN(id) FROM skill_index);
--   SELECT yanked FROM skill_index WHERE id = (SELECT MIN(id) FROM skill_index);  -- 应为 1
-- =============================================================================
