# Skillify Shogun Team Runtime · TP-13 解阻断任务清单（task）

> 上游裁决与契约来源：`docs/2026-07-18-skillify-shogun-team-runtime-integration-brief.md`
> 前序任务（已合入）：`docs/2026-07-18-skillify-shogun-team-runtime-task.md`（S1–S5：`implemented / compile_verified / env_verified=pending`）
> 阻断证据来源：`docs/testing/2026-07-17-post-ba3-test-environment-handoff.md` 第 6.4 节 TP-13 结论
> 执行：Codex（主）。目标执行器：**Claude Code + OpenCode（仅此两者）**。上游 Shogun：`v5.2.0` / `431b86a6907dd9ce2a0e9789f1e917ba71d1d184`（MIT），端侧外部 Team Runtime，**不 fork / 不复制源码 / 不改上游文件格式**。
> 每 Task：**依赖 / 文件 / 消费接口 / 产出接口 / 先失败测试 / 最小实现 / 验证命令 / 完成证据 / commit / Gate / 状态三层 / 指导意见**。
> 状态三层：`implemented`（合入）· `dev_verified`（离线门禁过：FakeRuntime + 临时目录）· `env_verified`（[test-env] 真实 bundle/tmux/内网模型销账）。三者独立。**禁**在未真实验证 Shogun/tmux/pane/内网模型时标 `env_verified`。

---

## 0. 目标与范围

**Goal:** 消除 TP-13 手册 6.4 记录的三个真实阻断，使受管 Shogun Team 能在隔离运行目录内被上游真实读取、被 Skillify 正确判定生命周期、并在每个 pane 内安全获得短期模型凭据，最终具备把 `infra/offline/shogun-manifest.json` 的 `installable` 由 `false` 翻转为 `true` 的前置条件。

**当前根因（均已在代码层核对，非文档推断）：**

1. **运行目录未被上游采用（queue/settings 硬编码）。** `config_gen.py` 把隔离配置写到 `run_dir/config/settings.yaml` 与 `run_dir/queue/*`（`src/skillify/agent/shogun/config_gen.py:54-59`），并仅通过环境变量 `SHOGUN_QUEUE_DIR` / `SHOGUN_SETTINGS_FILE` 传递（`config_gen.py:131-136`）；启动时 `cwd=install_root`（`src/skillify/agent/shogun/lifecycle.py:101-104`）。上游 `shutsujin_departure.sh` 及其 `scripts/` 以脚本自身目录（安装根）解析 settings/queue，**不读取这两个环境变量**。结果：真实 Team 读写 `install_root/queue`，而 Provider 只扫描 `run_dir/queue`（`src/skillify/agent/providers/shogun.py:123,141-143`），既收不到事件，也无法多 Team 隔离。

2. **生命周期跟踪 starter PID（starter 建 tmux 后退出）。** `ProcessRuntime.start` 直接 `Popen(entrypoint)` 并返回该进程 PID（`lifecycle.py:34-44`）。上游入口是 **starter**：创建 tmux 会话后立即退出。于是 `queue_states` 的 `while any(process.poll() is None ...)`（`lifecycle.py:66-69`）在启动后立即结束 → `stream_events` 过早终止（`providers/shogun.py:141`）；`terminate(pid)` 杀的是已退出的 starter（`lifecycle.py:46-49,113-121`）；真实清理只能依赖按固定名 `shogun`/`multiagent` 的 `kill-session` + `pkill`（`lifecycle.py:54-64`），无法确认存活、无法跨 Team 区分、无法支持 Bridge 重启后重认（Recovery 门禁）。

3. **无 pane 凭据注入 broker（短期模型凭据无安全通道）。** `config_gen.py` 只把 `credential_ref`（`scheme://…` 引用）写进 settings（`config_gen.py:44-45,69-73`），从不解析为真实令牌；`ProcessRuntime.start` 用 `env = {**os.environ, **environment}`（`lifecycle.py:37`）整体继承父进程环境。既有 `CredentialBroker.credential(...)`（`src/skillify/credentials/broker.py:42-74`）可由 `credential_ref` + 批准 scope 换取短期令牌，但 **Shogun 路径从未调用它**，也没有把令牌安全送进上游为每个 Agent 启动的 tmux pane 的通道。直接启动会迫使凭据落 YAML/命令行或经共享父环境泄露给全部 pane，违反 brief §8.4 与 G-S4 无秘密不变量。

**范围边界：** 本清单只做上述三项解阻断 + 收敛接线，不新增 formation、不做混合 formation（延后项）、不恢复自研 Team 通讯、不以旧 Workflow Runtime 兜底。

## Global Constraints（每个 Task 隐含继承，值逐字取自 brief 与既有代码）

- **不 fork / 不复制源码：** 禁止把 Shogun 源码复制进 Skillify，禁止 fork 改造为子模块，禁止重实现其 YAML 队列/inotify/tmux 生命周期/Agent 通讯（brief §1、§4.2）。
- **NO-GO 硬规则：** 任一修复若**只能通过修改上游源码实现**，Codex **禁止直接改上游**，必须在 S9.0 findings 中记为 `upstream-contribution-or-blocker` 并停在该 Task，向负责人 escalate（brief §8.3 第 3 条、§11 末段）。
- **无秘密不变量：** settings.yaml / permissions.yaml / 队列 YAML / 事件 / 日志 / 命令行 / `ps` 可见参数中**只能出现 `credential_ref`，禁止明文** Key/Token/Secret/Cookie/连接串/完整环境（brief §7 禁报项、§8.4）。
- **不用 dangerous：** 禁用 `--dangerously-skip-permissions`；`--permission-mode` 非 dangerous（brief §8.1）。
- **平台固定：** `linux-x86_64`；宿主依赖 `tmux/flock/inotifywait/python3/od` +（`opencode`|`claude`）（`src/skillify/agent/shogun/distribution.py:15-17`）。
- **禁 first_setup.sh / 禁运行时公网：** 安装/启动/运行/停止/升级期间无公网下载、更新、通知、遥测（`distribution.py:54-55`、brief §8.5）。
- **DM8 唯一真相源：** Shogun 运行目录不得直接覆盖服务端状态（brief §7.1）。
- **本轮验证分层：** S9.x 的 `dev_verified` 用 FakeRuntime + 临时目录证明编排/清理/脱敏逻辑；`env_verified` 一律移交 [test-env] 用真实 bundle/tmux/内网模型销账。**禁**把 compile-only 或 Fake 结果标为 `env_verified`。

---

## 阶段 S9.0 · 上游源码取证（Owner: Codex，[test-env] 前置）

> 这是 S9.1–S9.3 的共同前置。三项修复都取决于上游 `431b86a` 的真实行为；不先取证就实现会产生歧义与错误接线。取证只读，不改上游。

### S9.0.1 逐问核对 `431b86a` 运行时行为并产出 findings

- **依赖**：无（需 [test-env] 提供已批准离线 bundle）
- **文件**：
  - 创建：`docs/2026-07-20-shogun-431b86a-source-findings.md`（取证结论，唯一交付物）
  - 只读检查：批准 bundle 内 `shutsujin_departure.sh`、`scripts/`（含 `inbox_write.sh`、watcher/supervisor 脚本）、`config/settings.yaml` 模板；bundle 位置见 `infra/offline/shogun-manifest.json` 的 `artifact.intranetUri` / `sourceUrl`
- **消费接口**：`infra/offline/shogun-manifest.json`（`commit=431b86a…`、`bundleRequirements`）；`distribution.py:13-16` 的 `SHOGUN_COMMIT` / `SUPPORTED_PLATFORM`
- **产出接口**：findings 文档必须逐条回答下列问题，每条给出**源码文件名 + 行号 + 关键片段引用**（不得只写结论）：
  - **Q1（路径解析）**：`shutsujin_departure.sh` 与各 `scripts/` 如何定位 settings 与 queue 目录？是否使用 `$SCRIPT_DIR`/`dirname "$0"`/`cd` 到安装根的硬编码相对路径？是否读取任何环境变量（是否包含 `SHOGUN_QUEUE_DIR`/`SHOGUN_SETTINGS_FILE`，还是完全不认）？queue 子目录名（`tasks`/`reports`/`inbox`）与命令文件名 `shogun_to_karo.yaml` 是否与 `contract.py:12-14` 一致。
  - **Q2（进程模型）**：入口脚本创建 tmux 会话后是否立即退出？tmux 会话名是**固定**（如 `shogun`/`multiagent`）还是可配置（可否经 env/参数改名，从而支持多 Team）？创建了哪些长驻进程（supervisor / inbox_watcher / inotify）及其**可 `pkill -f` 的稳定特征串**；这些进程是否 `setsid`/脱离 starter 进程组。
  - **Q3（pane 启动与环境）**：每个 Agent（karo/ashigaru*/gunshi）的 `opencode`/`claude` 进程是如何在 pane 内被启动的（`tmux new-window`/`split-window` 的具体命令）？pane 进程从何处取得环境变量——继承 tmux server 环境、`source` 某个 env 文件、还是命令行传参？是否存在可被 Skillify 控制的、**非“注入任意 shell 文本”**的环境注入点（如 tmux `set-environment`/`update-environment`、bundle 内某个被 `source` 的启动前钩子文件）。
  - **Q4（取消/清理）**：上游是否自带安全停止入口？停止后遗留哪些进程/临时文件（`/tmp/shogun_*` 等），据此校验 `cleanup_processes`（`lifecycle.py:54-64`）覆盖是否完整。
  - **Q5（worktree）**：是否提供 per-Worker worktree 或互斥文件所有权（决定阶段一是否只能靠互斥 allowed_paths）。
  - **Q6（NO-GO 判定）**：对 Q1/Q2/Q3，逐项标注 Skillify 能否**仅通过上游公开配置/环境/目录布局**满足隔离/生命周期/凭据注入；若某项**必须改上游源码**，标 `upstream-contribution-or-blocker` 并明确指出所在文件。
- **先失败测试**：本 Task 无自动化测试（纯源码取证）。完成判据为下方“完成证据”的人工复核清单全部落实。
- **最小实现**：只读检查批准 bundle，逐问填写 findings，附源码行号引用；**不修改任何上游文件**。
- **验证命令**：`python -c "import pathlib,sys; p=pathlib.Path('docs/2026-07-20-shogun-431b86a-source-findings.md'); sys.exit(0 if all(q in p.read_text(encoding='utf-8') for q in ('Q1','Q2','Q3','Q4','Q5','Q6')) else 1)"`（确认六问齐备）
- **完成证据**：findings 六问均有源码文件名+行号+片段；Q6 明确给出每项是 `config-only` 还是 `upstream-contribution-or-blocker`。
- **commit**：`docs(team): record shogun 431b86a runtime source findings`
- **Gate G-S9.0**：findings 未产出前，S9.1–S9.3 不得开始编码。任一 Q6 判为 `upstream-contribution-or-blocker` 时，对应下游 Task 停在设计并 escalate，不得改上游。
- **状态**：implemented / dev_verified(N/A) / env_verified(真实 bundle 源码核对)
- **指导意见**：本 Task 是三修复的事实地基。**禁**用 v5.x README 或本文推断代替真实源码；README 常与实际脚本不符。所有下游实现必须**引用 findings 的行号结论**，而不是本清单的描述。

---

## 阶段 S9.1 · 运行目录隔离（Owner: Codex）

> 消除根因 1：让上游真实读写的目录 == Provider 扫描的目录 == 每任务隔离目录。

### S9.1.1 依据 findings 使上游采用隔离运行目录

- **依赖**：G-S9.0
- **文件**：
  - 修改：`src/skillify/agent/shogun/config_gen.py`（对齐上游实际路径解析；见下）
  - 修改：`src/skillify/agent/shogun/lifecycle.py:87-111`（`start` 的 `cwd`/入口目录随隔离策略调整）
  - 修改：`src/skillify/agent/providers/shogun.py:78-109,123,141-143`（确保 `create_session` 写入与 `stream_events` 扫描的目录 == 上游真实读写目录）
  - 测试：`tests/test_shogun_config_gen.py`、`tests/test_shogun_provider_contract.py`（新增隔离断言）
- **消费接口**：findings Q1（路径解析结论、queue 子目录/文件名）；`GeneratedShogunConfig`（`config_gen.py:17-24`：`settings_path/permissions_path/queue_dir/command/environment`）
- **产出接口**：`generate_config(...) -> GeneratedShogunConfig`，其中 `queue_dir` 指向**上游按其硬编码规则实际会读写的隔离目录**；`ProcessRuntime.start` 的 `cwd` 与该目录一致，使 `$SCRIPT_DIR`/相对解析落在隔离目录内。签名保持不变，避免波及 S9.2/S9.3。
- **先失败测试**（红）：
  - `test_generated_queue_dir_is_the_dir_upstream_reads`：断言 `generated.queue_dir` 位于传入的 `run_dir` 之内且**不**位于 `install_root` 之内。
  - `test_two_teams_get_disjoint_queue_dirs`：两次 `generate_config(run_dir=A)` / `run_dir=B)` 的 `queue_dir` 无公共父至 `install_root`（即隔离，不共享安装根 queue）。
  - `test_provider_scans_the_written_queue_dir`：`create_session` 写入 `COMMAND_FILE` 的目录与 `stream_events` 传给 `runtime.queue_states` 的目录为同一路径（用 FakeRuntime 断言 `write_snapshot` 目标 == 扫描目标）。
- **最小实现**（按 findings Q1 二选一，**只用上游公开机制**）：
  - 若 Q1 证明上游认 env（`SHOGUN_QUEUE_DIR` 等）：保留现有 env 传递，仅将 `lifecycle.start` 的 `cwd` 改为隔离运行目录并补测试。
  - 若 Q1 证明上游只认 `$SCRIPT_DIR` 相对路径（预期）：改为**每任务隔离实例**——将只读 bundle 以硬链接/只读 overlay 投影进 `run_dir`（不复制源码入库，仅运行期投影），使入口在 `cwd=run_dir` 下以隔离根运行；`generate_config` 把 settings/queue 写到该隔离根下上游实际解析的相对位置。**禁**改上游脚本内容。
- **验证命令**：`uv run pytest tests/test_shogun_config_gen.py tests/test_shogun_provider_contract.py -q`；`python -m compileall src/skillify/agent/shogun`
- **完成证据**：隔离/同目录/多 Team 不共享 install_root queue 三断言绿；无上游文件被修改（`git status` 仅 Skillify 侧文件）。
- **commit**：`fix(team): run shogun in an isolated per-task directory`
- **Gate G-S9.1**：Provider 扫描目录 ≠ 上游真实读写目录，或多 Team 共享安装根 queue，即阻断，不推进 S9.4。
- **状态**：implemented / dev_verified(FakeRuntime + 临时目录) / env_verified(真实 tmux Team 在隔离目录内产事件)
- **指导意见**：隔离策略必须来自 findings 的**实测路径解析**，不得臆测 env 生效。若唯一可行方案是改上游脚本 → 触发 Global Constraints 的 NO-GO，停在此并 escalate。投影 bundle 时保持只读、每任务独立、`stop`/`cancel` 时随运行目录一并清理（复用 `_release` 的 `rmtree`，见 `lifecycle.py:123-128`）。

---

## 阶段 S9.2 · 生命周期真实句柄（Owner: Codex）

> 消除根因 2：以 tmux 会话 + supervisor 进程 + 队列终态判定存活/取消/重认，弃用 starter PID。

### S9.2.1 用 tmux 会话/supervisor 句柄替代 starter PID

- **依赖**：G-S9.0（Q2 会话名与 supervisor 特征串）、G-S9.1（隔离运行目录）
- **文件**：
  - 修改：`src/skillify/agent/shogun/lifecycle.py`：
    - `RuntimeControl` Protocol（`:21-25`）：新增 `is_alive(handle) -> bool`
    - `ProcessRuntime.start`（`:34-44`）：返回**稳定 Team 句柄**而非 starter PID
    - `ProcessRuntime.queue_states`（`:66-69`）：改按会话存活轮询
    - `ProcessRuntime.terminate`/`cleanup_processes`（`:46-64`）：按会话名 + supervisor 停止
    - `ActiveTeam`（`:72-79`）：`pid: int` → `handle: TeamHandle`
    - `ShogunLifecycle.start/cancel/stop/_release`（`:87-128`）：改用句柄
  - 修改：`src/skillify/agent/providers/shogun.py:104-108,141`（`ProviderHandle` 携带稳定句柄；`stream_events` 存活轮询源改为 `runtime.is_alive`）
  - 修改：`src/skillify/agent/shogun/fake_runtime.py`（`start` 返回句柄；新增 `is_alive`）
  - 测试：`tests/test_shogun_lifecycle.py`、`tests/test_shogun_provider_contract.py`
- **消费接口**：findings Q2（tmux 会话名是否可配置、supervisor/watcher 稳定特征串、进程组关系）
- **产出接口**：
  - `TeamHandle`（dataclass，frozen）：`session: str`（每 Team 唯一会话名）、`run_dir: Path`；**可序列化到磁盘**以支持 Bridge 重启重认。
  - `RuntimeControl.start(command, *, cwd, environment) -> TeamHandle`
  - `RuntimeControl.is_alive(handle: TeamHandle) -> bool`（真实实现 = `tmux has-session -t handle.session` 成功）
  - `RuntimeControl.terminate(handle: TeamHandle) -> None`（按会话 + supervisor 停止）
  - `ActiveTeam.handle: TeamHandle`（替换原 `pid` 字段）
- **先失败测试**（红）：
  - `test_start_returns_team_handle_not_starter_pid`：`start` 返回 `TeamHandle`，`session` 非空；`ActiveTeam` 无 `pid` 属性。
  - `test_liveness_follows_session_not_starter`：FakeRuntime 脚本化 starter 立即“退出”但会话 `is_alive=True` 时，`queue_states` 仍持续产出直至队列终态；starter 退出不再提前终止流。
  - `test_cancel_targets_session_and_supervisor`：`cancel` 后 FakeRuntime.actions 含针对**该 Team 会话名**的 kill 与 supervisor pkill，且 `is_alive` 转 False、运行目录清空、guard 释放（复用 `_release`）。
  - `test_handle_roundtrips_for_recovery`：`TeamHandle` 序列化→反序列化后可用于 `is_alive` 查询（Bridge 重启重认前置）。
- **最小实现**：`ProcessRuntime.start` 组装并返回 `TeamHandle`（会话名按 findings：可配置则用 `team-<task_id>`，若上游硬编码则记录并在 `cleanup` 用该固定名 + 单活跃守卫兜底）；`queue_states` 循环条件改为 `is_alive(handle) and 未见终态`；`terminate` 用 `tmux kill-session -t handle.session` + 按特征串 `pkill` supervisor（先杀 supervisor 再杀 watcher，避免 5s 重生，沿用既有顺序注释）。FakeRuntime 提供可脚本化的 `is_alive` 序列。
- **验证命令**：`uv run pytest tests/test_shogun_lifecycle.py tests/test_shogun_provider_contract.py -q`；`python -m compileall src/skillify/agent/shogun`
- **完成证据**：存活跟随会话、cancel 针对本 Team 会话+supervisor 无遗留、句柄可 roundtrip 四断言绿。
- **完成证据（[test-env]）**：真实 tmux 下 starter 退出后 Team 仍被判存活；cancel/stop 后 `tmux ls`、`pgrep -f supervisor`、`/tmp/shogun_*` 均空。
- **commit**：`fix(team): track shogun team by tmux session instead of starter pid`
- **Gate G-S9.2**：存活仍绑 starter、或 cancel 有遗留、或句柄不可持久化（阻断 Recovery），即阻断。
- **状态**：implemented / dev_verified(FakeRuntime) / env_verified(真实 tmux 无残留 + Bridge 重启重认)
- **指导意见**：若 findings Q2 证明会话名硬编码且不可配置 → 多 Team 只能靠单活跃守卫（`active-team.lock`，`providers/shogun.py:60`、`lifecycle.py:90-100`）串行化，须在文档标注为阶段一约束，**不得**改上游改名。Bridge 重启重认的完整实现属于 S9.4 接线，本 Task 只保证句柄可持久化与 `is_alive` 查询可用。

---

## 阶段 S9.3 · pane 凭据注入 broker（Owner: Codex）

> 消除根因 3：用既有 `CredentialBroker` 解析 `credential_ref` 为短期令牌，经不落盘、不上命令行、不进共享父环境的通道注入每个 pane，并绑定 Team 生命周期清理。

### S9.3.1 每 pane 短期凭据注入与生命周期绑定

- **依赖**：G-S9.0（Q3 pane 启动/环境注入点）、G-S9.1（隔离运行目录）、G-S9.2（Team 句柄用于清理）
- **文件**：
  - 创建：`src/skillify/agent/shogun/credentials.py`（pane 凭据注入器：ref→token 解析 + 通道写入 + 清理）
  - 修改：`src/skillify/agent/shogun/config_gen.py:131-140`（`environment` 只放非秘密 + 注入通道位置引用，仍**不含明文**）
  - 修改：`src/skillify/agent/providers/shogun.py:78-109,156-170`（`start` 时经 broker 解析并布置通道；`cancel`/`stop` 时清理并 `broker.clear`）
  - 修改：`src/skillify/agent/shogun/lifecycle.py:113-128`（`_release` 追加销毁临时凭据通道）
  - 测试：`tests/test_shogun_permissions.py`（无秘密快照断言强化）、新增 `tests/test_shogun_credentials.py`
- **消费接口**：
  - `CredentialBroker.credential(auth_profile, credential_ref, approved_scopes) -> AccessCredential`（`src/skillify/credentials/broker.py:42-74`）；`AccessCredential.expires_at/audience/scopes`；`CredentialBroker.clear(reason)`（`broker.py:76-79`）
  - `ProviderStartSpec.credential_refs: dict[str,str]`（`src/skillify/agent/provider.py:77`）、`spec.runtime.credential_env_names`（既有单 Provider 注入模式见 `src/skillify/agent/providers/opencode.py:205-219`）
  - findings Q3（pane 取环境的真实机制）
- **产出接口**：
  - `class PaneCredentialInjector` —— `prepare(refs, *, broker, run_dir) -> InjectionChannel`（解析每个 `ENV_NAME→scheme://ref` 为短期令牌并写入不落盘通道）、`destroy(channel) -> None`（幂等清理）。
  - `InjectionChannel`（dataclass，frozen）：仅含通道**位置引用**（如 `0600` 临时文件路径 / tmux 环境名 / FIFO 路径），**不含令牌值**。
  - 通道机制由 findings Q3 决定，且必须满足：不写入 settings/permissions/队列 YAML、不出现在命令行/`ps`/事件/日志；优先级：tmux `set-environment`（若 pane 继承 tmux server 环境）> bundle 内被 `source` 的 `0600` env 文件（读后即删）> 命名管道；**禁**用 `send-keys` 注入 shell 文本（brief §5.2）。
- **先失败测试**（红）：
  - `test_refs_resolved_via_broker`：给定 `{"ANTHROPIC_API_KEY": "vault://model/deepseek"}` 与 fake broker，`prepare` 调用 `broker.credential` 并把令牌写入通道；通道位置存在，令牌值不出现在任何生成的 YAML 文本中。
  - `test_no_secret_in_any_generated_artifact`：读取 `settings.yaml`/`opencode-permissions.yaml`/`environment` dict/命令行 tuple，断言无令牌明文、无 `KEY/TOKEN/SECRET/COOKIE` 命名的明文值（强化 `config_gen.py:50-51` 既有校验到运行期）。
  - `test_env_dict_carries_no_plaintext_secret`：`GeneratedShogunConfig.environment` 只含 `SHOGUN_*` 与非秘密 public env + 通道位置引用，不含真实令牌。
  - `test_destroy_is_idempotent_and_clears_broker`：`destroy` 两次不报错、通道文件消失；`cancel`/`stop` 路径触发 `broker.clear` 且 audit 记录 `credential.cleared`。
  - `test_expired_token_refreshed`：令牌 `expires_at` 临近时再次 `prepare` 触发 broker 重新签发（复用 broker 30s 刷新窗口，`broker.py:56-57`）。
- **最小实现**：`PaneCredentialInjector.prepare` 遍历 `credential_refs`，对每个 ref 调 `broker.credential`（auth_profile/scope 由 spec 传入），把 `ENV_NAME=token` 写入 findings 选定的不落盘通道（`0600`，位于隔离 `run_dir`）；`config_gen` 生成的 pane 启动仅引用通道位置，不含值；`ShogunProvider.start` 调 `prepare` 并把 `InjectionChannel` 存入 `_RuntimeState`；`cancel`/`stop` 调 `destroy` + `broker.clear("team-stopped")`；`_release` 兜底删除通道文件。
- **验证命令**：`uv run pytest tests/test_shogun_credentials.py tests/test_shogun_permissions.py -q`；`python -m compileall src/skillify/agent/shogun`
- **完成证据**：ref→broker 解析、四类无秘密快照、幂等清理+broker.clear、令牌刷新五断言绿。
- **完成证据（[test-env]）**：真实内网模型端点下，各 pane 的 `opencode`/`claude` 能用注入令牌完成调用；`ps -ef`、pane 历史、`/proc/<pid>/environ` 之外的所有落盘文件、事件与日志均无明文令牌；stop 后通道文件与令牌清零。
- **commit**：`feat(team): inject short-lived per-pane model credentials via broker`
- **Gate G-S9.3**：任一生成文件/命令行/事件/日志含明文秘密，或停止后凭据残留，即阻断（与 G-S4 无秘密不变量一致）。
- **状态**：implemented / dev_verified(fake broker + 临时通道) / env_verified(真实内网模型 + 无秘密审计)
- **指导意见**：注入通道必须是**固定、受控**机制，不是“任意 shell 文本注入”（brief §5.2）。若 findings Q3 证明上游 pane 无任何可控环境注入点、只能改脚本 → NO-GO，停在此并 escalate。`credential_env_names`（模型 Key 的目标环境名）来自 `spec.runtime`，`scheme://ref` 来自 `spec.credential_refs`；二者的映射与 scope 审批沿用 broker 契约，**禁**在 Adapter 内自造第二套凭据存储。

---

## 阶段 S9.4 · 收敛、Recovery 接线与门禁复跑（Owner: Codex + [test-env]）

### S9.4.1 Bridge 重启重认 + installable 前置 + formation 门禁复跑

- **依赖**：G-S9.1、G-S9.2、G-S9.3
- **文件**：
  - 修改：`src/skillify/cli/bridge_cmd.py`（team claim 后持久化 `TeamHandle` 到隔离运行目录；重启时读回并 `is_alive` 决定续报或安全终止）
  - 修改：`infra/offline/shogun-manifest.json:8`（`installable` 由 `false` → `true` 的**前置条件达成**后，由 [test-env] 负责人在全门禁过后翻转；本 Task 只做代码前置，不擅自翻转）
  - 修改：`tests/test_shogun_smoke.py`（S6/S7 formation 用例，[test-env] 解除 skip）
  - 更新：`docs/testing/2026-shogun-team-e2e-checklist.md`（对应 Lifecycle/Security/Recovery/Workspace 项挂接 S9.1–S9.3 证据）
- **消费接口**：`TeamHandle`（S9.2）持久化格式；`RuntimeControl.is_alive`（S9.2）
- **产出接口**：Bridge 重启后：`is_alive(handle)=True` → 继续读隔离 `run_dir/queue` 上报（幂等，按 event_id）；`False` → 安全终止 + 清理，不重复执行任务。
- **先失败测试**（红）：
  - `test_bridge_reidentifies_existing_team_after_restart`：写入持久化 `TeamHandle`，模拟重启，`is_alive=True` 时继续上报且不重复 `create_session`。
  - `test_bridge_safe_terminate_when_team_dead`：`is_alive=False` 时执行清理并标记安全终止，无重复执行。
- **最小实现**：Bridge team 分支在隔离运行目录落 `team-handle.json`；重启入口读回并按 `is_alive` 分流；上报走既有 Outbox 幂等路径。
- **验证命令**：`uv run pytest tests/test_shogun_lifecycle.py tests/test_shogun_provider_contract.py -q`；前端不涉及则跳过 web 验证
- **完成证据**：重认续报 / 安全终止两断言绿。
- **完成证据（[test-env]）**：brief §12 全门禁（License/Offline/Linux/OpenCode/Claude Code/Lifecycle/Security/Events/Workspace/Concurrency/Recovery）复跑通过 + 集中系统级 hardening 完成后，负责人方可翻转 `installable=true` 并置 `SKILLIFY_SHOGUN_TEAM_ENABLED` / `SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED`。
- **commit**：`feat(team): reidentify shogun team on bridge restart`
- **Gate G-S9.4**：Recovery 门禁未过、或任一 S9.1–S9.3 门禁回退，`team` 保持不可用，两个开关保持关闭。
- **状态**：implemented / dev_verified / env_verified([test-env] 全门禁销账)
- **指导意见**：`installable` 与两个开关的翻转是 [test-env] 负责人动作，**Codex 只交付达成前置的代码**，不得为通过而擅自置真或开开关（handoff 6.4 与 brief §12）。失败时只禁用 `team`，`single/delegated` 不受影响，**不恢复自研 Team 通讯，不以旧 Workflow Runtime 兜底**。

---

## 依赖图与门禁

```
S9.0（上游取证 · findings）
  ├─> S9.1（运行目录隔离）      ─┐
  ├─> S9.2（tmux 句柄替代 PID） ─┼─> S9.4（Recovery 接线 + 门禁复跑 + installable 前置）
  └─> S9.3（pane 凭据注入）     ─┘
```

- **安全不变量（dev_verified 硬门禁，任一破坏即阻断）：** 无 dangerous；凭据不落 YAML/日志/命令行/事件；隔离运行目录不被跨 Team 共享；单活跃守卫有效；cancel/stop 后 tmux/supervisor/临时目录/临时凭据全清；Adapter 不改上游队列伪造完成；不 fork/不改上游源码。
- **NO-GO 升级点：** S9.0 Q6 或 S9.1/S9.3 指导意见触发时，停在该 Task，产出 escalate 记录，不改上游。
- **上线门禁：** brief §12 全门禁 + 集中 hardening 全过，且 `env_verified` 由 [test-env] 销账后，`team` 方可由负责人启用；在此之前 `single/delegated` 继续可用，两个 Team 开关保持关闭。

## 交付给 [test-env] 的前置清单（据 handoff 6.4）

- 已批准离线 bundle（`431b86a`，SHA256 见 `infra/offline/shogun-manifest.json`）+ 预建 `.venv` + settings 模板；宿主已备 tmux/flock/inotifywait/python3/od。
- 内网模型端点（OpenCode / Claude Code 各自可达）与其锁定版本记录。
- Credential Broker 可签发的短期模型凭据 `credential_ref` 与批准 scope（供 S9.3 真实注入）。
- 单 Endpoint、受信内网本机范围（Worker 可执行 shell 为阶段一已裁决接受的残余风险）。
