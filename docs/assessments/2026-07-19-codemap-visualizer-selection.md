# Skillify 人用 Code Map 可视化引擎选型报告

> 评测日期：2026-07-19
> 对应任务：`docs/2026-07-19-skillify-codemap-visualization-task.md`
> 结论：初评为 **G1 NO-GO**；用户于 2026-07-19 明确接受个人非商业使用边界后，GitNexus 以 `personal-noncommercial-only` 条件通过 G1，P2–P5 恢复实施。

## 1. 结论摘要

本轮严格按计划顺序克隆并检查 GitNexus、CodeCompass 和 Emerge 的官方仓库，使用锁定源码进行构建，并在当前开发机能力允许的范围内执行真实扫描与启动验证。

没有候选同时满足以下必要条件：

- 对 Skillify 的 Python、JavaScript/Vue 代码提供符号、调用/依赖和文件行号导航；
- 完全离线、只读、仅展示且不暴露额外 MCP/AI/改码能力；
- 可依法进入 Skillify 的内部离线构件；
- 可在目标 Endpoint 上形成可复现构建和受控运行入口。

初评时没有确定唯一引擎。用户随后明确本项目不做商业推广，仅作为个人开发者辅助用户查看代码，并要求继续试用。基于该产品裁决，GitNexus 成为唯一受限引擎；Agent CodeGraph 及其 MCP 配置仍保持不变。

## 2. 评测方法与边界

- 官方仓库均克隆到 Skillify 仓库外的临时目录：`/tmp/skillify-codemap-eval-20260719`。
- 候选源码、构建产物和样例索引均未加入 Skillify 仓库、submodule 或生产构件。
- 代表性仓库使用 Skillify 的本地 Git 快照，候选只能写入临时副本或独立导出目录。
- 当前机器没有 Chrome、Docker/Podman；涉及真实 Chrome 和 Linux 容器的门槛如实记为未验证，不以推测代替结果。
- 许可证判断以锁定 commit 中的 LICENSE 原文为准。

## 3. G1 对比

| 候选 | 符号/调用/行号 | Skillify 语言覆盖 | 离线与只展示 | 许可证/分发 | 构建与真实运行 | G1 |
|---|---|---|---|---|---|---|
| GitNexus v1.6.9 | 通过真实索引证明图数据能力 | Python、JS/Vue 可索引 | 开发期采用 Endpoint 本机原生页面；完全断网/display-only 加固转测试环境 | 用户已接受个人非商业用途，禁止商业推广或商业分发 | Node 22 构建、索引和 localhost 服务成功 | 条件通过 |
| CodeCompass `096f79c` | C/C++、Python 有调用图设计 | 失败：JS/TS/Vue 没有同等级语义分析 | 完整运行未验证 | GPLv3，若采用需接受相应义务 | Web 依赖安装成功；缺少 Thrift 生成物，完整构建依赖 Linux 工具链 | 淘汰 |
| Emerge 2.0.7 | 失败：Python/JS 输出是文件依赖，不含函数/方法调用与行号定位 | Vue 文件被全部跳过 | 生成的静态页面可离线 | MIT | Python 3.10 环境完成真实扫描 | 淘汰 |

任一硬项失败即出局；未用其他优点抵消硬门槛。

## 4. GitNexus

### 4.1 冻结身份

```text
official_url: https://github.com/abhigyanpatwari/GitNexus.git
remote.origin.url: https://github.com/abhigyanpatwari/GitNexus.git
initial_main_commit: 12600000e36aa890cd5f6daaa7f3293fd2190b18
evaluated_tag: v1.6.9
evaluated_commit: 4227194ad7bdfbedc29a7fe20e09c6737ce0e744
commit_date: 2026-07-04
license: PolyForm Noncommercial License 1.0.0
license_sha256: b3e617e5e5eea01b2e9153156c88706c14899e78b4a5d48b9fc14f4f10115c72
```

锁文件：

```text
package-lock.json: e4a47cfd0efbd5cdb3b0d5b5a8a6065e931f537034584bb43cac36b3a16592be
gitnexus/package-lock.json: 80c2bd6c7a1bfcb0b6285c102b91443582cf72be9f77f2cff358fd407c208caf
gitnexus-web/package-lock.json: 6e51d9effc1c366f093a5276d35ff73b3c729177614bd8fb8d612afd280b0232
```

### 4.2 构建与运行证据

仓库要求的 Node 版本高于本机默认 Node 20，因此使用临时 Node 22.23.1，严格从 lockfile 安装。`gitnexus-shared`、CLI/core 和 `gitnexus-web` 均构建成功，只有 bundle chunk 和 dynamic import 警告。

真实索引命令：

```bash
node gitnexus/dist/cli/index.js analyze --index-only --skip-skills --skip-agents-md --no-stats
```

对 Skillify 临时副本的结果：

```text
elapsed: 39.9s
nodes: 7,708
edges: 18,875
clusters: 277
flows: 300
index_size: 118 MiB
```

以 `serve --host 127.0.0.1 --port 4747` 启动成功，根页面 HTTP 200，监听地址只有 `127.0.0.1`。

### 4.3 淘汰证据

- LICENSE 是 PolyForm Noncommercial 1.0.0；当前没有可覆盖 Skillify 内部使用和分发场景的商业授权，许可证硬门槛失败。
- 构建后的 `index.html` 仍包含 Google Fonts 的外部 preconnect/stylesheet URL，严格断公网静态资源门槛失败。
- 服务启动日志显示挂载 `/api/mcp`，源码还包含 AI Chat、MCP、Git、Skills/Hooks 等非展示能力。本轮没有找到并实证一个能在构建及运行时彻底关闭这些能力的官方 display-only 模式。
- 当前环境没有 Chrome，因此未给出最低 Chrome major 或真实浏览器网络面板证据。

GitNexus 可保留为功能和交互标杆，但在获得适用商业授权并解决离线资源、display-only 裁剪之前不能成为生产引擎。

## 5. CodeCompass

### 5.1 冻结身份

```text
official_url: https://github.com/Ericsson/CodeCompass.git
remote.origin.url: https://github.com/Ericsson/CodeCompass.git
evaluated_branch: master
evaluated_commit: 096f79ce0e42067fbc56b0b24614ac7ffec1c634
commit_date: 2026-05-05
tag_at_commit: none
license: GNU General Public License v3.0
license_sha256: ee4c2c7086aedbd05fe582046e799fbd32124fe215b6007d10246c537edadddd
webgui-new/package-lock.json: ff6ad28f44661a7409f5fbe666eac3f3626a09b049ac604e8b4cd9b3f0b34c1c
```

官方仓库在评测 commit 没有可用的稳定 tag，因此本报告不虚构版本号。

### 5.2 构建与源码证据

- 新 Web GUI 的 `npm ci` 成功。
- `npm run build` 失败于缺失 `@thrift-generated`；该模块需要先完成 CodeCompass 的 Thrift/backend 生成流程。
- 官方完整构建目标是 Ubuntu 22/24，并依赖 CMake、C/C++ 工具链、LLVM/Clang、ODB、Thrift、Java、Graphviz 等。本机 macOS 且没有 CMake、Docker/Podman，无法声称完整构建和运行通过。
- 源码可确认 C/C++ 与 Python 的调用图和源代码定位能力；JavaScript/TypeScript 只进入通用搜索/MIME 文本处理，没有与 C/C++、Python 等价的语义调用分析插件。

### 5.3 淘汰证据

Skillify 的代表性前端是 Vue/JavaScript。CodeCompass 不能为该部分提供计划要求的函数/方法调用和行号关系，因此核心功能硬门槛失败。完整部署复杂度和 GPLv3 义务无需再作为取舍项推进；若未来重新考虑，仍必须先由用户接受许可证义务并在目标 Linux 环境完成完整验证。

## 6. Emerge

### 6.1 冻结身份

```text
official_url: https://github.com/glato/emerge.git
remote.origin.url: https://github.com/glato/emerge.git
evaluated_tag: 2.0.7
evaluated_commit: 586ac24a3bd1f678615b4986923f182c4235e4ea
commit_date: 2024-10-26
declared_setup_version: 2.0.0
license: MIT
license_sha256: d5a44674a92f27545f7dba717b78e304d949846c3579296b6237434d3d323afc
requirements.txt: adb48483545e2f7efae300d68459e3006c22cc75200b095637945a677c4021e6
dependency_lockfile: none
```

Tag 2.0.7 与 `setup.py` 声明的 2.0.0 不一致，已作为复现性风险记录。依赖只有未固定版本的 `requirements.txt`。

### 6.2 构建与运行证据

使用 Python 3.10 创建临时环境并安装源码。运行时还暴露了未完整声明的依赖：需要兼容 `pkg_resources` 的 setuptools，并直接依赖 pip 内部模块。

对 Skillify 的 `src/skillify` 和 `web/src` 执行真实扫描成功：

```text
elapsed: 2.23s
peak_rss: 127,864,832 bytes
```

Python 产出文件依赖图和文件系统图。JavaScript 扫描报告 41 个文件被跳过；所有 `.vue` 文件均以 unknown extension 跳过。生成 HTML 使用随包携带的 D3 资源，可本地打开。

### 6.3 淘汰证据

图数据只有文件级依赖和指标，没有函数/方法的 caller/callee、符号定义位置或计划要求的文件行号定位。其官方实现对 Python/JavaScript 也是文件扫描，而非这些语言的符号级调用提取。核心展示能力失败，因此即使 MIT 和轻量离线运行较友好，也不能提交为半成品 Code Map。

## 7. Gate G1 与后续状态

```text
T0.1: implemented / dev_verified
T0.2: implemented / dev_verified
T1.1: implemented / dev_verified
T1.2: implemented / dev_verified（Chrome/Linux 专项未具备环境，且候选已因其他硬项淘汰）
T1.3 / G1: restricted_go（仅限个人非商业用途）
T2.1–T4.3: implemented / dev_verified
T5.1 / G2: partial（代码环境已完成编译和契约验证，真实 Endpoint 终链待测试环境）
T6.1 / G3: pending
```

本次受限通过建立在以下产品决定之上：

1. 用途限定为个人开发、研究、实验和无预期商业应用的辅助代码查看；
2. 不进行商业推广、收费服务或商业构件分发；
3. 如果 Skillify 后续商业化，GitNexus 功能必须停用，直到取得适用商业授权或更换引擎。

PolyForm Noncommercial 1.0.0 没有按天计算的试用到期条款。许可证中的 32 天是首次收到违规通知后的整改期限，不是试用期限。许可证原文和 Required Notice 必须随离线构件保留。

## 8. 恢复实施记录

- 固定版本：GitNexus `v1.6.9` / `4227194ad7bdfbedc29a7fe20e09c6737ce0e744`。
- 固定官方源码归档 SHA256：`468138d074bb1c3bf4c0094a813d426a2146510d13a5f747c51b950a1f877c90`。
- 新增 `infra/offline/gitnexus-visualizer-manifest.json`，明确 `personal-noncommercial-only` 和 `expiresAt: null`。
- 新增离线 runtime 构建脚本；目标 Linux runtime 的最终 SHA256、SBOM复核和内部镜像仍由测试环境产出。
- Launcher 在 Skillify 状态目录创建工作区快照并运行 GitNexus，禁止向用户原工作区写 `.gitnexus`。
- Bridge 使用固定 `codemap.visualization.*` workflow 分流，不调用 Agent Provider，不把 Visualizer 接入 MCP。
- Web 只提供启动、打开、状态和停止动作；GitNexus 原生页面只在 Endpoint 本机 Chrome 打开。
