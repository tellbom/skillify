# 已知问题与修复

1. devpi 6.13 初始化命令无效：修复为 `devpi-init`。
2. dmPython 容器连接报 `-70089`：安装 OpenSSL/libaio 运行库并设置 bundled DPI 的 `LD_LIBRARY_PATH`。
3. DM8 不接受方言生成的 `IS 0`：布尔过滤改为可移植的 `= false()` 表达式。
4. DM8 CLOB JSON 返回字符串：增加显式 JSON 文本序列化类型。
5. external candidate 可重复选择：metadata 记录已选 ID，重复选择返回 400。
6. Compose 未透传固定 Forgejo org：已补 `SKILLIFY_FORGEJO_ORG`。
7. PostgreSQL 16 alpine 与目标机 3.10 内核初始化不兼容：测试服务器 override 为 PostgreSQL 12；升级宿主后应复测 16。
8. DIsql UTF-8 脚本读取及退出码不可靠：部署转换临时副本并检查输出。
9. DM8 初始化 SQL 不可重复执行：尚未改造成迁移/幂等脚本。
10. 工作机到新增端口受上游网络 ACL 拒绝；目标服务器本机及容器网络真实链路正常，需网络管理员放行后再做外部浏览器验收。

