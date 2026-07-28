-- Skillify-owned RBAC bootstrap for Dameng DM8.
-- Idempotently grants the MVP administrator project-super access and registers
-- the four Vue routes consumed by E:/skillify/web/src/router/dynamicRoutes.js.

MERGE INTO "rbac_project_grant" t
USING (
    SELECT
        '196045' AS "userid",
        'skillify' AS "project",
        1 AS "is_super",
        'skillify-bootstrap' AS "granted_by"
    FROM dual
) s
ON (t."userid" = s."userid" AND t."project" = s."project")
WHEN MATCHED THEN
    UPDATE SET
        t."is_super" = s."is_super",
        t."granted_by" = s."granted_by",
        t."updated_at" = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN
    INSERT ("id", "userid", "project", "is_super", "granted_by", "granted_at", "updated_at")
    VALUES (
        LOWER(REGEXP_REPLACE(
            GUID(),
            '([0-9A-F]{8})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{12})',
            '\1-\2-\3-\4-\5'
        )),
        s."userid", s."project", s."is_super", s."granted_by",
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    );

MERGE INTO "rbac_rule" t
USING (
    SELECT
        'skillify' AS "project",
        r."rule_code",
        r."permission_code",
        r."parent_rule_code",
        r."type",
        r."title",
        r."name",
        r."path",
        r."component",
        r."extend",
        r."weigh"
    FROM (
        SELECT
            'skills' AS "rule_code",
            'menu:skillify.skills' AS "permission_code",
            CAST(NULL AS VARCHAR2(128)) AS "parent_rule_code",
            'Menu' AS "type",
            'Skills' AS "title",
            'skills' AS "name",
            '/' AS "path",
            '/src/views/SkillListView.vue' AS "component",
            '' AS "extend",
            10 AS "weigh"
        FROM dual
        UNION ALL
        SELECT
            'skill-detail',
            'menu:skillify.skill-detail',
            'skills',
            'Menu',
            'Skill detail',
            'skill-detail',
            '/skills/:namespace/:name',
            '/src/views/SkillDetailView.vue',
            'add_rules_only',
            11
        FROM dual
        UNION ALL
        SELECT
            'skillify:upload',
            'menu:skillify.upload',
            CAST(NULL AS VARCHAR2(128)),
            'Menu',
            'Upload',
            'upload',
            '/upload',
            '/src/views/UploadView.vue',
            '',
            20
        FROM dual
        UNION ALL
        SELECT
            'leaderboard',
            'menu:skillify.leaderboard',
            CAST(NULL AS VARCHAR2(128)),
            'Menu',
            'Leaderboard',
            'leaderboard',
            '/leaderboard',
            '/src/views/LeaderboardView.vue',
            '',
            30
        FROM dual
    ) r
) s
ON (t."rule_code" = s."rule_code" AND t."project" = s."project")
WHEN MATCHED THEN
    UPDATE SET
        t."permission_code" = s."permission_code",
        t."parent_rule_code" = s."parent_rule_code",
        t."type" = s."type",
        t."title" = s."title",
        t."name" = s."name",
        t."path" = s."path",
        t."icon" = '',
        t."menu_type" = 'Tab',
        t."url" = NULL,
        t."component" = s."component",
        t."extend" = s."extend",
        t."remark" = '',
        t."keepalive" = 0,
        t."weigh" = s."weigh",
        t."status" = 'Active',
        t."updated_at" = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN
    INSERT (
        "id", "project", "rule_code", "permission_code", "parent_rule_code",
        "type", "title", "name", "path", "icon", "menu_type", "url",
        "component", "extend", "remark", "keepalive", "weigh", "status",
        "created_at", "updated_at"
    )
    VALUES (
        LOWER(REGEXP_REPLACE(
            GUID(),
            '([0-9A-F]{8})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{12})',
            '\1-\2-\3-\4-\5'
        )),
        s."project", s."rule_code", s."permission_code", s."parent_rule_code",
        s."type", s."title", s."name", s."path", '', 'Tab', NULL,
        s."component", s."extend", '', 0, s."weigh", 'Active',
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    );

COMMIT;

SELECT 'project_grant' AS "kind", COUNT(*) AS "row_count"
FROM "rbac_project_grant"
WHERE "userid" = '196045' AND "project" = 'skillify'
UNION ALL
SELECT 'active_rules', COUNT(*)
FROM "rbac_rule"
WHERE "project" = 'skillify' AND "status" = 'Active';
