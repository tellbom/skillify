# GitNexus Code Map 开发期验证记录

> 日期：2026-07-19
> 引擎：GitNexus `v1.6.9` / `4227194ad7bdfbedc29a7fe20e09c6737ce0e744`
> 许可模式：`personal-noncommercial-only`
> 状态：`implemented=yes / dev_verified=partial / env_verified=no`

## 已完成

- 官方 GitHub 源码归档、commit、LICENSE 和 checksum 已固定。
- 已确认 PolyForm Noncommercial 1.0.0 没有按天到期的试用期限；项目用途限制为个人、研究、实验和无预期商业应用。
- 已提供 Node 22 构建脚本，可从固定源码生成包含 LICENSE 和 npm SBOM 的端侧 runtime 包。
- Launcher 只扫描 Skillify 状态目录中的工作区快照，`.gitnexus` 不写入用户原仓库。
- GitNexus 服务固定监听 `127.0.0.1`；中央 Web 不返回 Endpoint localhost URL。
- `skillctl codemap visualize start/status/open/stop/doctor` 已注册。
- `codemap.visualization.start|stop|open|status` 复用现有 Endpoint Task、租约、Bridge、Outbox 和事件链。
- Codemap Task 由 Bridge 独立分流，不启动 OpenCode、Claude Code、Shogun，不注入 CodeGraph MCP。
- Web Endpoint 工作台增加薄入口，不 iframe、不上传源码、不复制 GitNexus 图谱 UI。

## 开发期命令与结果

```text
.venv/bin/python -m compileall -q src/skillify
结果：通过

.venv/bin/pytest -q tests/test_codemap_visualizer.py tests/test_codegraph_manifest.py \
  tests/test_codegraph_config.py tests/test_task_protocol.py tests/test_task_store_bridge.py \
  tests/test_bridge.py tests/test_task_reporting.py tests/test_web_endpoint_tasks.py \
  tests/test_endpoint_agent_api.py tests/test_task_lease.py tests/test_bridge_runner.py
结果：38 passed, 1 existing warning

cd web && npm test -- tests/endpointTasks.spec.js
结果：4 passed

cd web && npm run type-check
结果：通过

cd web && npm run build
结果：通过；只有既有 dynamic import 和 chunk-size warning
```

上游真实 Spike 已对 Skillify 临时副本完成索引：7,708 nodes、18,875 edges、277 clusters、300 flows，耗时 39.9 秒，索引 118 MiB。

## 尚未在代码环境宣称通过

- 尚未在目标 Linux x64/arm64 生成并批准最终 runtime SHA256、Syft SBOM 和内部构件镜像。
- 尚未通过 rootless container/network namespace 强制断网。
- GitNexus 构建页面仍引用 Google Fonts；断网下的视觉降级和静态资源本地化待测试环境处理。
- 尚未用目标 Chrome 确认最低 major、浏览器打开、关系导航和网络面板。
- 尚未在真实 Server/Bridge/Endpoint 上执行 Web → Task → Bridge → snapshot → scan → Chrome → stop 全链路。
- 上游服务包含 MCP/AI 等能力；当前只限制 Skillify 的入口和凭据环境，系统级 display-only hardening 待集中测试阶段。

因此 G2、G3 和 `env_verified` 保持未通过，不把编译成功误报为上线可用。

## 核心保护

以下核心文件未修改，SHA256 与 P0 基线一致：

```text
f2ca25a62599d0e0f0cc33053bea1413bed118f99fbcadaef409a82419d2cede  src/skillify/agent/codegraph.py
7752ce85c49ef3d805c8209e0c0022327f8d078da3ab071d3a50c8f5b4074aaa  infra/offline/codegraph-manifest.json
d191f710601ec97d0d09a28dbbfb91ebd66e1b6abce4fb3c3ff4ab4fe2196466  src/skillify/agent/opencode_config.py
4232f43de8ae7c57bcb5cbf1190e3d41007198a03621fbb14d8be9513211cfb9  src/skillify/agent/claudecode_config.py
```
