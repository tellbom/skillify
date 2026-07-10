# 评审结论：M0 + M1（Opus 4.8）

> 评审对象：Skillify M0（规范与地基）+ M1（CLI 闭环），Sonnet 5 实现。
> 评审人：Opus 4.8（代码逐文件通读 + 跑测试套件）。日期：2026-07-09。
> 性质：Opus / GPT5.5 联合评审的 Opus 侧结论。GPT5.5 结论请追加到 §6。

---

## 0. 总体结论：**通过，可继续开发 M2/M3**

M0 + M1 实现质量高、忠实于 PLAN 已定决策，MVP 范围内的"发布 → 安装 → 本机运行 + 依赖隔离 + agent 投影"闭环成立。**没有阻塞性问题。** 下列 findings 均为次要缺陷 / 设计澄清，可在推进 M2/M3 的同时并行处理（F1 建议先修，F3 已裁决为默认不投影依赖）。

**核实证据**
- `uv run pytest -q` → **88 passed, 2 skipped**（24s）。2 个 skip 正是文档说明的网络依赖用例（`test_installer_python_deps.py` 的真实 devpi 路径、沙箱无法出网），非隐藏失败。
- 逐文件通读了 install/packaging/publish/validator/common 全部核心模块 + spec + schema + 示例。

---

## 1. 逐项验收核对

| 任务 | 状态 | 核实 |
| --- | --- | --- |
| T0.1 spec + schema | ✅ | `spec/*.md` + `*.schema.json`，字段齐全，`additionalProperties:false` 全程封闭，manifestVersion 版本化策略清晰，主动标注新增 `namespace`/`tags` 待评审（§3.1） |
| T0.2 校验器 | ✅ | schema + 语义规则（namespace/name 对目录、runtime↔targets、skill-dep semver）+ 目录布局 + SKILL.md frontmatter，错误以 (path, message) 列表返回 |
| T0.3 infra compose | ⚠️ 结构验证 | YAML 结构/语法测试过；**未在真实 Docker 上起过**（本机无 Docker），见 F6 |
| T1.1 CLI 骨架 | ✅ | init/doctor/validate/publish/install/list/update/remove/search 齐全 |
| T1.1a init | ✅ | prompt/python 两模板，生成物过校验器 |
| T1.1b doctor | ⚠️ 有缺陷 | 逐项 OK/FAIL + hint + 退出码，但检查的 agent 集合有误，见 **F1** |
| T1.2 打包+checksum | ✅ | 可复现 tarball（归零 mtime/uid/gid、mode 规范化）+ sha256 + artifact.json；打包前强制过校验器 |
| T1.3 publish | ✅ | Forgejo REST 客户端，建仓/建 release/传资产，鉴权下载支持私有库 |
| T1.4 install（中立目录） | ✅ | 下载→校验 checksum→安全解压→venv→装依赖→写 lock，落 `~/.skillify/skills/<ns>/<name>` |
| T1.4a 适配层 | ✅ | `agents/*.yaml` 规则 + symlink(posix)/copy(win) 投影；remove 清理投影；未指定 target 时按"声明且本机已装"自动选 |
| T1.5 依赖解析 | ✅ | skill 间递归 + 环检测；python 走 devpi index-url |
| T1.6 示例 skill | ✅ | text/word-frequency（带 python 依赖）、excel/pivot-analysis，走全链路 |

---

## 2. 亮点（值得保留的工程决策）

- **安全解压扎实**：`extract.py:safe_extract` 拒绝符号链接/硬链接、路径逃逸，并叠加 `filter="data"`，防 zip-slip；checksum 校验强制、失败即中止。
- **可复现打包**：`pack.py` 归一化 tarinfo + gzip `mtime=0`，同输入同 checksum，是"版本管理 + 供应链可信"的地基。
- **中立目录为唯一真相源**：安装只写 `~/.skillify`，agent 目录是投影，完全落实 PLAN §4 的解耦决策，没有被 Claude 目录绑死。
- **诚实的自我披露**：opencode 默认目录标注 `unverified`（代码 + spec 双处）、skip 测试写明原因、新增字段主动提请评审——这类"标记而非静默"的做法应继续要求。

---

## 3. Findings（非阻塞，按严重度）

### F1 · doctor 检查的 agent 集合有误【建议先修，小改】
`cli/doctor_cmd.py:20` 硬编码 `AGENT_TARGET_DIRS = {claude, codex}`：
- **opencode 是一线主力 target，却没被 doctor 检查**；
- **codex 是 PLAN 里 reserved/未实现的 agent（`agent_defaults.RESERVED_UNIMPLEMENTED_AGENTS`），却被检查**。
- 且此处硬编码，与我们此前约定的"doctor 读 `agents/*.yaml` 动态检查已配置 target"不一致。
**建议**：doctor 改为遍历 `~/.skillify/agents/*.yaml`（或至少把集合改成 `{claude, opencode}`），加新 agent 时无需改 doctor 代码。

### F2 · update 绕过依赖解析【设计缺口，小改】
`cli/install_cmd.py:run_update` 走 `install_skill`（单个）而非 `install_with_dependencies`。若某次更新新增了 `dependencies.skills`，更新时不会拉取新依赖。
**建议**：update 也走 `install_with_dependencies`，保持与 install 一致。

### F3 · skill 依赖是否投影到 agent 目录？【已裁决：默认不投影依赖】
`run_install` 只把**根 skill** 投影到 agent 目录；被依赖的 skill 装进中立目录 + venv，但**不投影**。若 A 依赖 B，且 agent 需要能直接看到 B，则当前 B 对 agent 不可见。
**裁决**：默认按"A 运行时的内部依赖"处理，依赖 skill **不自动投影**到 agent 目录。也就是说，用户安装 A 时，B 会安装到中立目录供 A 使用，但不会出现在 Claude/OpenCode 的技能列表里。

**后续扩展建议**：如确实需要把某个依赖也暴露给 agent，应在 manifest 中增加显式语义（例如 `exposeToAgent: true` 或 `projection: transitive`），由 skill 作者主动声明，避免依赖实现细节污染 agent 技能列表。

### F4 · 菱形依赖重复安装【效率，小】
`install/dependencies.py` 仅用祖先路径做环检测，无"本次已装"全局集合；A→B、A→C、B→D、C→D 时 D 会被下载安装多次。正确性无碍，浪费带宽/时间。
**建议**：加一个本次运行的 visited/installed 集合去重。

### F5 · requires-python 与 tarfile filter 不匹配【可移植性，小】
`pyproject.toml` 声明 `requires-python = ">=3.10"`，但 `safe_extract` 用了 `extractall(..., filter="data")`，该参数仅在 3.10.12+/3.11.4+/3.12+ 存在，早期 3.10/3.11 补丁版会抛 `TypeError`。
**建议**：内网 Linux Python 可控，风险低；仍建议把 `requires-python` 收紧到 `>=3.12`（或对 filter 做版本守卫），避免部署到旧补丁版翻车。

### F6 · 三处环境未真机验证【已知，须在 M2/M3 前收口】
Sonnet 已在 TASKS 顶部披露：① T0.3 compose 未在真实 Docker 起过；② T1.5 `--index-url` 真实 devpi 网络路径未验证（已用 `--find-links` 离线验证同套机制）；③ opencode 目录约定未验证。
**建议**：M2（发布流水线）/M3 依赖真实 Forgejo + devpi，**开工前先把这三项在真机内网各跑通一次**，避免把未验证假设带进下游。

---

## 4. 与 PLAN 决策的一致性核对

- 中立目录 `~/.skillify/`、targets 字段、checksum、per-skill venv + devpi、Linux symlink/Windows copy —— 全部与 PLAN §0/§3/§4 一致。
- spec §3.1 新增 `namespace`（安装路径/CLI 寻址需要）、`tags`（T2.2 索引列需要）——判断合理，属补齐而非冲突，已提请评审，Opus 侧**认可保留**。

---

## 5. 对 Sonnet 5 的放行意见

**可继续开发 M2/M3。** 建议顺序：
1. 先修 **F1**（doctor agent 集合，10 分钟级）。
2. 按 **F3** 裁决保持默认行为：依赖 skill 只安装到中立目录，不自动投影到 agent 目录。
3. **F6** 三项真机验证放在 M2 开工第一步。
4. F2/F4/F5 可并入一次小的加固提交，不阻塞。

---

## 6. GPT5.5 侧结论（Codex 复核，2026-07-09）

> 复核方式：按 `PLAN.md` / `TASKS.md` 的 M0、M1 验收项做代码审查，重点检查 validator、packaging、publish、install、dependency resolver、agent projector、doctor 与 CLI wiring；并重新运行测试套件。

### 6.1 总体结论：**同意放行 M2/M3，但建议先做一次 M1 加固提交**

Codex 侧结论与 Opus 基本一致：M0/M1 的核心闭环已经成立，当前没有发现必须阻塞 M2/M3 开工的缺陷。`uv run pytest -q` 复跑结果为 **88 passed, 2 skipped**，两个 skip 与 TASKS 顶部披露的真实 devpi 网络路径限制一致。

建议在进入 M2/M3 前先合并一个小的 hardening patch：修 F1、F2、F4、F5，并补上 C1/C2 的校验与测试。这样可以避免把“本地 MVP 能跑通”的假设带进真实 Forgejo/devpi 环境。

### 6.2 认可 Opus Findings

- **F1 doctor agent 集合错误：认可，建议先修。** `doctor_cmd.py` 仍硬编码 claude/codex，而实现的一线 target 是 claude/opencode；彻底方案应读取 `~/.skillify/agents/*.yaml` 或复用 agent defaults 的 presence/rule 逻辑。
- **F2 update 绕过依赖解析：认可。** `run_update` 直接调用 `install_skill`，如果新版新增 skill 依赖，update 不会递归安装。
- **F3 依赖 skill 是否投影：已由用户裁决，默认不投影依赖。** 依赖 skill 作为根 skill 的内部运行依赖安装到中立目录；除非未来 manifest 增加显式暴露语义，否则不自动进入 agent 技能列表。
- **F4 菱形依赖重复安装：认可。** 正确性问题不大，但 M2 后真实构件下载会放大时间/带宽浪费。
- **F5 Python 版本声明与 tarfile filter：认可。** 要么收紧到 Python >=3.12，要么对 `tar.extractall(filter="data")` 做兼容分支。
- **F6 真机验证缺口：认可。** Docker compose、真实 devpi index-url、opencode 目录约定必须在 M2/M3 前收口。

### 6.3 Codex 额外 Findings

#### C1 · installer 解包后未复验 manifest 与请求/Release 元数据一致【建议重要修复】

`installer.install_skill` 在 checksum 通过后直接解压并读取 `skill.yaml`，但没有验证：
- 解出的 `manifest.namespace/name` 是否等于 CLI 请求的 `namespace/name`；
- 解出的 `manifest.version` 是否等于解析到的 Release 版本；
- 解出的目录是否仍通过 `validate_skill_dir`。

当前 `pack_skill` 会在正常 publish 流程前校验，因此“全员只用 skillctl publish”时风险较低；但真实 Forgejo 环境允许人工 Release/资产操作，且 installer 是最终供应链边界。若 `excel/pivot-analysis@v1.0.0` 的 Release 资产里实际放了 `other/ns@9.9.9` 的内容，installer 仍会写入 `~/.skillify/skills/excel/pivot-analysis`，lock 也记录成 `excel/pivot-analysis@1.0.0`，造成内容、lock、Release 三者不一致。

**建议**：安装端在 `safe_extract` 后调用 validator，并显式比较 manifest 的 namespace/name/version 与解析结果；不一致直接失败并清理目标目录。

#### C2 · resolver 选择 Release 资产过宽【建议与 C1 一起修】

`resolve_release_artifact` 使用第一个 `*.tar.gz` 和第一个 `*.sha256` 资产，没有要求二者 basename 匹配，也没有要求资产名匹配 `namespace-name-version`。真实 Release 一旦存在多个 tarball/checksum，可能下载 A tarball + B checksum，或选择错误资产。

**建议**：解析时按 packager 产物命名精确匹配，例如 `<namespace>-<repo>-<version>.tar.gz` 与同 basename 的 `.sha256`；同时优先读取 `.artifact.json` 里的 metadata/sha256 进行交叉校验。

### 6.4 建议进入 M2/M3 前的最小处理顺序

1. 修 **F1**：doctor 动态读取 agent 配置，至少改成 claude/opencode，并移除 codex 检查。
2. 修 **F2/F4**：update 走 `install_with_dependencies`；依赖安装增加本轮 visited/installed 去重。
3. 修 **C1/C2**：安装端复验 manifest；Release 资产按 basename 精确匹配。
4. 处理 **F5**：收紧 Python 版本或兼容旧 patch 版。
5. 做 **F6**：在真实 Docker/Linux 环境跑 compose、Forgejo publish/install、devpi `--index-url`、opencode 投影验证。

### 6.5 Codex 放行意见

**可继续 M2/M3，但不建议把当前 M1 视为“生产可用基线”。** 更准确的状态是：MVP 闭环通过，测试覆盖良好，适合进入下一阶段；同时需要在真实基础设施接入前完成上述加固，尤其是 installer 的 manifest/asset 复验。

### 待用户/联合裁决的开放项
- doctor 是否统一改为"读 `agents/*.yaml` 动态检查"（F1 的彻底版）。
