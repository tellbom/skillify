# TP-13 Shogun · 下一步方向评估（供负责人 + GPT 评审）

> 类型：**方向/决策文档**，不是实现计划。目的：在 Codex 代码审查得出 NO-GO 后，把“为什么卡住、卡在哪一层、有哪些出路、各自代价”摆清楚，供负责人和 GPT 拍板。
> 输入证据：
> - 阻断结论：`docs/2026-07-20-shogun-431b86a-source-findings.md`（Codex 对 `431b86a` 只读源码核对）
> - 测试销账：`docs/testing/2026-07-17-post-ba3-test-environment-handoff.md` 第 6.4 节 TP-13
> - 解阻断任务：`docs/2026-07-20-skillify-shogun-team-unblock-task.md`
> - 上游裁决：`docs/2026-07-18-skillify-shogun-team-runtime-integration-brief.md`
> 结论先行：**原始三根因已判定可在 Skillify 适配层解决（不 fork）；真正卡住的是一个新暴露的、更深的上游能力缺口——Worker 级写路径隔离。它决定 Team 能否上线，且它才是本次评审要决策的对象。**

---

## 1. 精确状态快照：什么已解，什么新卡

### 1.1 原始三根因 —— 已判定 config-only 可解，无需改上游

Codex 对 `431b86a` 逐行核对（findings Q1–Q4、Q6），三项原始阻断均落在 Skillify 适配层，**不触发 `upstream-contribution-or-blocker`**：

| 原根因 | 上游事实（行号） | Skillify 侧解法 | 结论 |
|---|---|---|---|
| 运行目录硬编码 | 入口以脚本目录为根（`shutsujin_departure.sh:16-28`），env 只被部分辅助脚本认（`lib/agent_registry.sh:9`、`scripts/slim_yaml.py:56-57`） | 每任务硬链接投影 + 隔离 `HOME`，在任务目录内执行入口 | 适配层可解 |
| 跟踪 starter PID | 入口建 `shogun`/`multiagent` 固定会话后退出，watcher 用 `nohup&`+`disown`（`:551-552,578,893-939`） | `TeamHandle`=会话名+run_dir+started_at，按会话判活 | 适配层可解 |
| pane 凭据注入 | 上游 `env` 会把秘密拼进 pane 命令（`lib/cli_adapter.sh:147-149,288-303`），无秘密文件描述符/管道注入点 | 受控 `PATH` launcher + `0600` Unix Socket 按 pane 取短期凭据 | 适配层可解 |

**含义：** 我为解阻断写的 S9.1/S9.2/S9.3 三条任务在技术上成立，只要继续用 Shogun，这部分适配工作不白做。

### 1.2 新暴露的阻断 —— Worker 级写路径隔离（这才是 NO-GO 的真正原因）

findings 第 101 行“真实 formation 复核补充”给出的是一个**此前未识别、比原三根因更根本**的问题：

- 上游 `scripts/build_instructions.sh` 把**所有 `ashigaruN` 固定映射到同一个 `ashigaru` 权限角色**，且只读取 `read_allow/read_deny/edit_allow/edit_deny` 四个扁平列表。
- Skillify `config_gen.py:78-97,109-118` 生成的是**逐 Worker 的 `read/edit` 结构**——键名和结构都不被该上游脚本采用，等于**当前逐 Worker 权限配置对上游是死配置**。
- 上游**无 `git worktree`**，`auto_merge_short_lived.sh:92-118` 直接操作**共享单一工作树**。
- Claude Code 后端**本身无法强制逐文件写权限**（只有 `--permission-mode`）。

**后果：** brief §12 的 **Workspace 门禁（“Worker 不会互相覆盖文件”）与 Security 门禁的一部分，在批准 commit `431b86a` 上无法由公开配置表达。** 这是 Codex 把它标为 `upstream-contribution-or-blocker`、并要求 `installable` 保持 `false` 的直接原因。

---

## 2. 回答核心问题：卡在哪一层？

> 用户问：当前主要问题点是**端侧系统的权限限制**，还是**此框架代码出现限制**？

都不是。按证据分层定性：

| 层 | 是否是瓶颈 | 依据 |
|---|---|---|
| **端侧操作系统权限** | **否**，反而是可利用的“出路”（见 §3 选项 B） | 银河麒麟本机、单用户单租户、受信内网；OS 具备 UID/ACL/overlay 等隔离手段，只是尚未被用来兜底 |
| **Skillify 框架代码** | **否**，意图正确但被上游忽略 | `config_gen.py` 已生成逐 Worker 权限，问题是上游 `build_instructions.sh` 不采用它，不是 Skillify 写错 |
| **上游 Shogun 框架能力（`431b86a`）** | **是，唯一根因** | 角色折叠为单一 `ashigaru`、无 per-Worker worktree、共享工作树、Claude 无逐文件写权限——公开配置无法表达 Worker 写隔离 |

**一句话：这是上游 Shogun 权限模型的能力缺口，不是端侧 OS 限制，也不是 Skillify 代码缺陷。** 端侧 OS 恰恰是可以拿来补上这个缺口的资源之一。

---

## 3. 出路盘点（五个选项，含代价与对既有工作的影响）

> 关键判断：Worker 写隔离“不能由上游配置表达”，不等于“完全不能实现”。上游配置层封死了，但 Skillify **已经要在每个 pane 前面放一个受控 launcher**（为解 Q3 凭据），这个 launcher 层和端侧 OS 层都还没用尽。以下按“改动面从小到大”排列。

### 选项 A · launcher 层为 OpenCode 注入 per-Worker 权限（改动最小，需 spike 验证）

- **做法：** 复用 Q3 已规划的 per-pane `PATH` launcher。launcher 以 pane 身份启动 `opencode` 时，额外为该 Worker 设置**独立 `OPENCODE_CONFIG_DIR` + 独立 `HOME`**，指向只含该 Worker `edit_allow` 路径的 `opencode.json`——**绕过上游折叠的 `ashigaru` 角色，直接用 OpenCode 自身权限系强制写路径**。
- **代码依据（已核对）：** 单 Provider 已这么做——`providers/opencode.py:205-215` 用 `OPENCODE_CONFIG_DIR`/`HOME` 隔离每个 opencode 进程，且 OpenCode 有 `permission.asked`/`MergedPermissions` 权限系（`opencode.py:531`、`opencode_config.py:32,422`）。launcher 天然按 pane 运行、能控子进程环境，与 Q3 同机制。
- **解锁：** 仅**全 OpenCode formation** 的 Workspace 门禁——无需 fork、无需换框架。
- **不解锁：** 全 Claude formation（Claude 无逐文件写权限，仍是残余风险）。
- **对既有工作影响：** 无损，S1–S5 + S9 全部复用。
- **风险/未知（须 spike）：** ① OpenCode 权限是否对越界写**硬拒**而非仅提示；② 上游 `send-keys cd` 到共享根后，per-pane `OPENCODE_CONFIG_DIR` 是否仍生效（cwd 共享但按绝对 `edit_allow` 判定应可）；③ 是否需要 launcher 拦住 opencode 之外的原生 shell 写（shell 越权已是 brief 已裁决的阶段一残余风险）。
- **定位：** **最应优先花 1–2 天 spike 验证的方向**；若成立，全 OpenCode Team 可先上线，Claude 走选项 D。

### 选项 B · 端侧 OS 级强隔离（中等改动，最强保证）

- **做法：** 每个 Worker pane 的 launcher 在 OS 层限制可写范围——per-Worker 不同 UID + 共享工作树上按 ACL 只授该 Worker 的 `allowed_paths`，或 overlayfs/bind-mount 只读挂载他人路径。合并仍由 Integration 角色在完整树上做。
- **解锁：** OpenCode **和** Claude 两种 formation 的 Workspace 门禁（OS 强制，与 CLI 能力无关）。
- **对既有工作影响：** 无损，叠加在 launcher 上。
- **风险/代价：** 工程量最大；共享工作树 + 无 worktree 使“同一 repo、不同路径可写”实现较复杂；需在银河麒麟上验证 ACL/overlay 稳定性；可能与 CodeGraph/构建产物路径冲突。
- **定位：** 若必须让 **Claude formation 也硬隔离**、且不接受残余风险，则这是不 fork 的唯一强解。

### 选项 C · 向上游贡献 per-Worker 角色 / worktree（不 fork 的“正规”解，但受制于上游）

- **做法：** 给 Shogun 提 PR，让 `build_instructions.sh` 支持逐 `ashigaruN` 角色或 per-Worker worktree，合入后重新 pin 一个批准 commit。
- **解锁：** 根因层彻底解决，两种 formation 都干净。
- **风险/代价：** 依赖上游接受与发版节奏，**不可控、周期长**；期间 Team 仍不可上线；重新过许可/供应链/哈希审批。
- **定位：** 可作为**并行的长期项**推进，但不作为解阻断的关键路径（否则 Team 无限期挂起）。

### 选项 D · 缩小阶段一门禁范围（产品裁决，非工程）

- **做法：** 把 Workspace 门禁对**不可强制**的后端（尤其 Claude）降级为**声明式互斥 + 文档化残余风险**，与已被接受的“Worker 可执行任意 shell（受信内网本机、单租户）”同级处理；或阶段一先只允许 `worker_count=1`（无并行写冲突）。
- **解锁：** 让 Team 在“单租户受信本机、写冲突属正确性风险而非安全越界、Integration 角色兜底合并”的边界内先上线。
- **风险/代价：** 需负责人**明确修订 brief §12 Workspace 门禁定义**并签字接受残余风险；两个 Worker 写同一文件会互相覆盖（correctness/质量风险，非安全泄露）。
- **定位：** 与选项 A/B 组合使用——A/B 覆盖能硬隔离的部分，D 明文承接剩下的残余风险。

### 选项 E · 更换 Team Runtime 框架

- **做法：** 放弃 Shogun，选一个原生支持 per-Worker worktree/逐 Worker 权限的 Team 框架重新评估接入。
- **解锁：** 若新框架原生具备隔离，则根因不复存在。
- **风险/代价：** **最高**——丢弃 S1–S5 契约/事件/Bridge/Web + S9 适配的绝大部分；重新做许可/供应链/离线/Linux/双 formation 全套门禁；新框架同样可能有自己的能力缺口，需重走一遍 findings 式核对。
- **定位：** 仅当 A/B/C/D 组合都被否决、或对 Claude 硬隔离是硬需求且 OS 隔离（B）也不可接受时，才考虑。**不建议作为首选**。

---

## 4. 推荐路径（供评审校正）

**分层组合，而非二选一：**

1. **先做 spike（1–2 天，Owner: Codex）：** 验证选项 A —— per-pane `OPENCODE_CONFIG_DIR`/`HOME` 能否让 OpenCode 对越界写**硬拒**。这是成本最低、影响最大的一步，且直接决定后面怎么走。
2. **A 成立 →** 全 OpenCode formation 走选项 A 硬隔离；全 Claude formation 走选项 D（残余风险文档化，需负责人签字）或选项 B（若要 Claude 也硬隔离）。据此可将 Workspace 门禁拆成 per-formation 判定，先放行 OpenCode Team。
3. **A 不成立 →** 评估选项 B（OS 强隔离）作为不 fork 的统一强解；同时并行推进选项 C（上游 PR）作为长期正规解。
4. **全程保持：** `infra/offline/shogun-manifest.json` 的 `installable=false`、两个 Team 开关关闭，直到选定路径 + 全 formation 门禁闭环（Codex 结论正确，不擅自翻转）。
5. **不做：** 选项 E（更换框架）暂不启动；不 fork 上游；不恢复自研 Team 通讯；不以旧 Workflow Runtime 兜底。

**理由：** 原三根因已可解，沉没成本低；真正的缺口是“写隔离”，而它有 launcher 层（A）和 OS 层（B）两条不 fork 的出路尚未被排除。先用最便宜的 spike 收敛不确定性，再决定是否升级到 B/C 或裁决 D。

---

## 5. 需要负责人 + GPT 拍板的决策点

1. **是否批准先做选项 A 的 spike？**（1–2 天，验证 OpenCode per-pane 权限硬隔离是否成立）
2. **全 Claude formation 的 Workspace 隔离要求：** 接受“声明式互斥 + 文档化残余风险”（选项 D），还是必须 OS 强隔离（选项 B）？——这直接决定 Claude Team 的工程量与时间。
3. **是否允许 Workspace 门禁按 formation 拆分判定**（OpenCode 先放行、Claude 后置），而不是两种 formation 捆绑一起过？
4. **是否并行启动选项 C（向上游提 PR）**作为长期正规解？还是完全靠 Skillify 适配层自足？
5. **阶段一是否接受 `worker_count` 上限收敛**（如先限 2、或极端情况先限 1）以降低写冲突面？
6. **红线确认：** 是否维持“不 fork、不换框架（选项 E 暂不启动）、installable 保持 false 直到全 formation 闭环”？

---

## 6. 附：本次结论与上一版方向的差异

- 上一版解阻断任务（`2026-07-20-...-unblock-task.md`）假设“互斥 allowed_paths”在阶段一即可作为写隔离手段。**本次 findings 推翻了这一隐含假设**：在 `431b86a` 上，逐 Worker 写隔离**不是配置就能表达的**，需要 launcher/OS 层额外机制或上游变更。后续任何解阻断计划都必须以此为前提，不能再把“声明 allowed_paths”等同于“强制写隔离”。
