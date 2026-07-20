-- Skillify project menu and RBAC management bootstrap for DM8.
-- Idempotent: safe to execute again after deploying new frontend builds.

MERGE INTO "rbac_rule" t
USING (
    SELECT 'skillify' AS "project", m."rule_code", m."permission_code",
           m."parent_rule_code", m."type", m."title", m."name", m."path",
           m."menu_type", m."component", m."extend", m."weigh"
    FROM (
        SELECT 'skills' AS "rule_code", 'menu:skillify.skills' AS "permission_code",
               CAST(NULL AS VARCHAR2(128)) AS "parent_rule_code", 'Menu' AS "type",
               '技能中心' AS "title", 'skills' AS "name", '/' AS "path", 'Tab' AS "menu_type",
               '/src/views/SkillListView.vue' AS "component", CAST(NULL AS VARCHAR2(32)) AS "extend", 100 AS "weigh" FROM dual
        UNION ALL SELECT 'skill-detail', 'menu:skillify.skill-detail', 'skills', 'Menu',
               'Skill 详情', 'skill-detail', '/skills/:namespace/:name', 'Tab',
               '/src/views/SkillDetailView.vue', 'add_rules_only', 99 FROM dual
        UNION ALL SELECT 'my-skills', 'menu:skillify.my-skills', NULL, 'Menu',
               '个人空间', 'my-skills', '/my-skills', 'Tab',
               '/src/views/MySkillsView.vue', NULL, 90 FROM dual
        UNION ALL SELECT 'skillify:upload', 'menu:skillify.upload', NULL, 'Menu',
               '上传技能', 'upload', '/upload', 'Tab',
               '/src/views/UploadView.vue', NULL, 80 FROM dual
        UNION ALL SELECT 'endpoint-tasks', 'menu:skillify.endpoint-tasks', NULL, 'Menu',
               'Endpoint Tasks', 'endpoint-tasks', '/endpoint-tasks', 'Tab',
               '/src/views/EndpointTasksView.vue', NULL, 75 FROM dual
        UNION ALL SELECT 'leaderboard', 'menu:skillify.leaderboard', NULL, 'Menu',
               '排行榜', 'leaderboard', '/leaderboard', 'Tab',
               '/src/views/LeaderboardView.vue', NULL, 70 FROM dual
        UNION ALL SELECT 'auth', 'menu:auth', NULL, 'MenuDir',
               '权限管理', 'auth', '/auth', NULL, NULL, NULL, 20 FROM dual
        UNION ALL SELECT 'auth/admin', 'menu:auth/admin', 'auth', 'Menu',
               '管理员', 'auth-admin', '/auth/admin', 'Tab',
               '/src/views/backend/auth/admin/index.vue', NULL, 19 FROM dual
        UNION ALL SELECT 'auth/group', 'menu:auth/group', 'auth', 'Menu',
               '权限组', 'auth-group', '/auth/group', 'Tab',
               '/src/views/backend/auth/group/index.vue', NULL, 18 FROM dual
        UNION ALL SELECT 'auth/rule', 'menu:auth/rule', 'auth', 'Menu',
               '菜单管理', 'auth-rule', '/auth/rule', 'Tab',
               '/src/views/backend/auth/rule/index.vue', NULL, 17 FROM dual
        UNION ALL SELECT 'auth/apiMap', 'menu:auth/apiMap', 'auth', 'Menu',
               'API 权限映射', 'auth-apimap', '/auth/api-map', 'Tab',
               '/src/views/backend/auth/apiMap/index.vue', NULL, 16 FROM dual
        UNION ALL SELECT 'auth/projectGrant', 'menu:auth/projectGrant', 'auth', 'Menu',
               '项目授权', 'auth-grant', '/auth/project-grant', 'Tab',
               '/src/views/backend/auth/projectGrant/index.vue', NULL, 15 FROM dual
    ) m
) s
ON (t."project" = s."project" AND t."rule_code" = s."rule_code")
WHEN MATCHED THEN UPDATE SET
    t."permission_code" = s."permission_code", t."parent_rule_code" = s."parent_rule_code",
    t."type" = s."type", t."title" = s."title", t."name" = s."name",
    t."path" = s."path", t."icon" = NULL, t."menu_type" = s."menu_type",
    t."url" = NULL, t."component" = s."component", t."extend" = s."extend",
    t."remark" = NULL, t."keepalive" = 0, t."weigh" = s."weigh",
    t."status" = 'Active', t."updated_at" = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (
    "id", "project", "rule_code", "permission_code", "parent_rule_code", "type",
    "title", "name", "path", "icon", "menu_type", "url", "component", "extend",
    "remark", "keepalive", "weigh", "status", "created_at", "updated_at"
) VALUES (
    LOWER(REGEXP_REPLACE(GUID(), '([0-9A-F]{8})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{12})', '\1-\2-\3-\4-\5')),
    s."project", s."rule_code", s."permission_code", s."parent_rule_code", s."type",
    s."title", s."name", s."path", NULL, s."menu_type", NULL, s."component", s."extend",
    NULL, 0, s."weigh", 'Active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

MERGE INTO "rbac_rule" t
USING (
    SELECT 'skillify' AS "project", p."permission_code" AS "rule_code",
           p."permission_code", p."parent_rule_code", 'Button' AS "type",
           p."permission_code" AS "title"
    FROM (
        SELECT 'menu:admin.list' AS "permission_code", 'auth/admin' AS "parent_rule_code" FROM dual
        UNION ALL SELECT 'button:admin.create', 'auth/admin' FROM dual
        UNION ALL SELECT 'button:admin.edit', 'auth/admin' FROM dual
        UNION ALL SELECT 'button:admin.status', 'auth/admin' FROM dual
        UNION ALL SELECT 'button:admin.username', 'auth/admin' FROM dual
        UNION ALL SELECT 'button:admin.delete', 'auth/admin' FROM dual
        UNION ALL SELECT 'menu:group.list', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.create', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.edit', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.rules', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.status', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.member.add', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.member.del', 'auth/group' FROM dual
        UNION ALL SELECT 'button:group.delete', 'auth/group' FROM dual
        UNION ALL SELECT 'auth.group', 'auth/group' FROM dual
        UNION ALL SELECT 'menu:rule.tree', 'auth/rule' FROM dual
        UNION ALL SELECT 'menu:rule.list', 'auth/rule' FROM dual
        UNION ALL SELECT 'button:rule.create', 'auth/rule' FROM dual
        UNION ALL SELECT 'button:rule.edit', 'auth/rule' FROM dual
        UNION ALL SELECT 'button:rule.status', 'auth/rule' FROM dual
        UNION ALL SELECT 'button:rule.weigh', 'auth/rule' FROM dual
        UNION ALL SELECT 'button:rule.delete', 'auth/rule' FROM dual
        UNION ALL SELECT 'menu:apimap.list', 'auth/apiMap' FROM dual
        UNION ALL SELECT 'button:apimap.create', 'auth/apiMap' FROM dual
        UNION ALL SELECT 'button:apimap.edit', 'auth/apiMap' FROM dual
        UNION ALL SELECT 'button:apimap.delete', 'auth/apiMap' FROM dual
        UNION ALL SELECT 'menu:search.audit', 'auth/apiMap' FROM dual
        UNION ALL SELECT 'menu:search.permission', 'auth/apiMap' FROM dual
        UNION ALL SELECT 'button:grant.create', 'auth/projectGrant' FROM dual
        UNION ALL SELECT 'button:grant.delete', 'auth/projectGrant' FROM dual
        UNION ALL SELECT 'button:grant.super', 'auth/projectGrant' FROM dual
    ) p
) s
ON (t."project" = s."project" AND t."rule_code" = s."rule_code")
WHEN MATCHED THEN UPDATE SET
    t."permission_code" = s."permission_code", t."parent_rule_code" = s."parent_rule_code",
    t."type" = s."type", t."title" = s."title", t."name" = s."rule_code",
    t."path" = NULL, t."menu_type" = NULL, t."component" = NULL,
    t."status" = 'Active', t."updated_at" = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (
    "id", "project", "rule_code", "permission_code", "parent_rule_code", "type",
    "title", "name", "path", "icon", "menu_type", "url", "component", "extend",
    "remark", "keepalive", "weigh", "status", "created_at", "updated_at"
) VALUES (
    LOWER(REGEXP_REPLACE(GUID(), '([0-9A-F]{8})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{12})', '\1-\2-\3-\4-\5')),
    s."project", s."rule_code", s."permission_code", s."parent_rule_code", s."type",
    s."title", s."rule_code", NULL, NULL, NULL, NULL, NULL, NULL,
    NULL, 0, 0, 'Active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

MERGE INTO "rbac_api_permission_map" t
USING (
    SELECT 'skillify' AS "project", a."http_method", a."route_pattern",
           a."permission_code", a."action"
    FROM (
        SELECT 'GET' AS "http_method", '/api/admin/list' AS "route_pattern", 'menu:admin.list' AS "permission_code", 'read' AS "action" FROM dual
        UNION ALL SELECT 'POST', '/api/admin', 'button:admin.create', 'create' FROM dual
        UNION ALL SELECT 'PUT', '/api/admin/{userid}', 'button:admin.edit', 'update' FROM dual
        UNION ALL SELECT 'PUT', '/api/admin/{userid}/status', 'button:admin.status', 'update' FROM dual
        UNION ALL SELECT 'PUT', '/api/admin/{userid}/username', 'button:admin.username', 'update' FROM dual
        UNION ALL SELECT 'DELETE', '/api/admin/{userid}', 'button:admin.delete', 'delete' FROM dual
        UNION ALL SELECT 'GET', '/api/group/list', 'menu:group.list', 'read' FROM dual
        UNION ALL SELECT 'POST', '/api/group', 'button:group.create', 'create' FROM dual
        UNION ALL SELECT 'PUT', '/api/group/{groupCode}', 'button:group.edit', 'update' FROM dual
        UNION ALL SELECT 'PUT', '/api/group/{groupCode}/rules', 'button:group.rules', 'update' FROM dual
        UNION ALL SELECT 'PUT', '/api/group/{groupCode}/status', 'button:group.status', 'update' FROM dual
        UNION ALL SELECT 'POST', '/api/group/{groupCode}/members', 'button:group.member.add', 'create' FROM dual
        UNION ALL SELECT 'DELETE', '/api/group/{groupCode}/members/{userid}', 'button:group.member.del', 'delete' FROM dual
        UNION ALL SELECT 'DELETE', '/api/group/{groupCode}', 'button:group.delete', 'delete' FROM dual
        UNION ALL SELECT 'GET', '/api/group/index', 'auth.group', 'read' FROM dual
        UNION ALL SELECT 'GET', '/api/rule/tree', 'menu:rule.tree', 'read' FROM dual
        UNION ALL SELECT 'GET', '/api/rule/list', 'menu:rule.list', 'read' FROM dual
        UNION ALL SELECT 'POST', '/api/rule', 'button:rule.create', 'create' FROM dual
        UNION ALL SELECT 'PUT', '/api/rule/{ruleCode}', 'button:rule.edit', 'update' FROM dual
        UNION ALL SELECT 'PUT', '/api/rule/{ruleCode}/status', 'button:rule.status', 'update' FROM dual
        UNION ALL SELECT 'PUT', '/api/rule/{ruleCode}/weigh', 'button:rule.weigh', 'update' FROM dual
        UNION ALL SELECT 'DELETE', '/api/rule/{ruleCode}', 'button:rule.delete', 'delete' FROM dual
        UNION ALL SELECT 'GET', '/api/api-map/list', 'menu:apimap.list', 'read' FROM dual
        UNION ALL SELECT 'GET', '/api/api-map/records', 'menu:apimap.list', 'read' FROM dual
        UNION ALL SELECT 'POST', '/api/api-map', 'button:apimap.create', 'create' FROM dual
        UNION ALL SELECT 'PUT', '/api/api-map/{id}', 'button:apimap.edit', 'update' FROM dual
        UNION ALL SELECT 'DELETE', '/api/api-map/{id}', 'button:apimap.delete', 'delete' FROM dual
        UNION ALL SELECT 'GET', '/api/search/audit-logs', 'menu:search.audit', 'read' FROM dual
        UNION ALL SELECT 'GET', '/api/search/permission-view', 'menu:search.permission', 'read' FROM dual
        UNION ALL SELECT 'POST', '/api/project-grant', 'button:grant.create', 'create' FROM dual
        UNION ALL SELECT 'DELETE', '/api/project-grant/{userid}', 'button:grant.delete', 'delete' FROM dual
        UNION ALL SELECT 'PUT', '/api/project-grant/{userid}/super', 'button:grant.super', 'update' FROM dual
    ) a
) s
ON (t."project" = s."project" AND t."http_method" = s."http_method" AND t."route_pattern" = s."route_pattern")
WHEN MATCHED THEN UPDATE SET
    t."permission_code" = s."permission_code", t."action" = s."action",
    t."status" = 'Active', t."updated_at" = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (
    "id", "project", "http_method", "route_pattern", "permission_code",
    "action", "status", "created_at", "updated_at"
) VALUES (
    LOWER(REGEXP_REPLACE(GUID(), '([0-9A-F]{8})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{4})([0-9A-F]{12})', '\1-\2-\3-\4-\5')),
    s."project", s."http_method", s."route_pattern", s."permission_code",
    s."action", 'Active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

COMMIT;
