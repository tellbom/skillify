# Shogun `431b86a` 源码核对结论

日期：2026-07-20  
对象：`multi-agent-shogun` commit `431b86a`  
上游归档：`E:\skillify-artifacts\shogun\v5.2.0\multi-agent-shogun-431b86a-linux-x86_64.tar.gz`  
SHA-256：`04bc3a1115302759bb7f1007d5ae7508641cbe72440e0d5977fe79a8d5edafbe`

本次仅对归档解压出的只读检查副本进行核对；没有修改、复制或 fork 上游源码到 Skillify 仓库。

## 结论摘要

| 问题 | 结论 | TP-13 实现策略 |
|---|---|---|
| Q1 配置与队列目录 | 主入口仍以脚本目录为运行根；两个环境变量只被部分辅助脚本识别 | 每个任务建立硬链接运行时投影，并把 `HOME` 隔离到任务目录 |
| Q2 进程模型 | 启动脚本退出后 tmux 会话和 watcher 继续运行；starter PID 不是团队身份 | 使用可序列化 `TeamHandle`，以 tmux 会话和运行目录识别团队 |
| Q3 pane 凭据注入 | 上游 YAML `env` 会把秘密拼进命令；不满足秘密边界 | 通过受控 `PATH` launcher 和 `0600` Unix Socket 按 pane 注入 |
| Q4 watcher/supervisor | 入口直接后台启动 watcher；未启用仓库内 supervisor；无独立 stop 入口 | 按 `TeamHandle` 关闭 tmux 和运行目录所属后台进程，再清理临时状态 |
| Q5 worker workspace | 未发现 `git worktree`；自动合并脚本操作共享工作树 | 第一阶段继续依赖 Skillify `allowed_paths` 互斥和单活团队约束 |
| Q6 是否要求修改上游 | 否 | 全部在 Skillify 适配层完成，不触发 `upstream-contribution-or-blocker` |

## Q1：入口如何解析 settings、queue 和 inbox

`shutsujin_departure.sh:16-17` 把入口所在目录设为当前工作目录：

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
```

`shutsujin_departure.sh:21-28` 固定读取 `./config/settings.yaml`。`shutsujin_departure.sh:356-367`、`377-390` 固定备份和创建 `./queue` 下的 `shogun_to_karo.yaml`、`reports`、`tasks`、`inbox`。

Linux 上，`shutsujin_departure.sh:381-386` 会把 inbox 指到当前用户 HOME 下的全局路径：

```bash
INBOX_LINUX_DIR="$HOME/.local/share/multi-agent-shogun/inbox"
mkdir -p "$INBOX_LINUX_DIR"
ln -s "$INBOX_LINUX_DIR" ./queue/inbox
```

`scripts/inbox_write.sh:8,14` 和 `scripts/ntfy_listener.sh:9-14` 同样从脚本目录反推根目录，并直接使用该根目录下的 `queue`/`config`。

`SHOGUN_SETTINGS_FILE` 仅在 `lib/agent_registry.sh:9` 被识别；`SHOGUN_QUEUE_DIR` 仅在 `scripts/slim_yaml.py:56-57` 和 `scripts/slim_yaml.sh:15` 被识别。这两个环境变量不足以重定向主入口和全部后台脚本。

结论：使用上游现有的“脚本目录即运行目录”约定，在每个任务目录建立同文件系统硬链接投影；`config`、`queue`、`logs` 等可变路径只在任务目录创建。执行投影内的入口并设置任务专属 `HOME`，即可隔离 queue 和 Linux inbox。硬链接失败时必须明确失败，不能回退成可变源码复制或共享目录。

## Q2：启动脚本、tmux 和后台进程的生命周期

`shutsujin_departure.sh:551-552` 创建固定的 `shogun` 会话，`578` 附近创建固定的 `multiagent` 会话。没有发现可配置会话名的参数或环境变量。

入口在完成 pane 创建和命令发送后退出；tmux server、pane 内 CLI 和 watcher 不依赖 starter PID 存活。`shutsujin_departure.sh:893-939` 通过 `nohup ... &` 和 `disown` 为 agent 启动 `inbox_watcher.sh`。因此 starter PID 不能作为团队稳定身份。

`shutsujin_departure.sh:339-340` 会在下次启动前关闭固定 tmux 会话。`903-906` 会全局匹配并结束旧 watcher/inotify/fswatch，`1010-1013` 会以相同方式重启 ntfy listener。这也意味着当前上游实现不支持同一 OS 用户下多个团队并行运行。

结论：第一阶段保留 Skillify 的 active-team 单活锁。稳定身份使用：

- `team_id`；
- 固定主会话 `shogun`，并同时检查 `multiagent`；
- `run_dir`；
- `started_at`。

`start()` 只在确认 tmux 会话存在后返回 `TeamHandle`；`inspect()` 通过 tmux 会话而非 PID 判活；`stop()` 关闭两个固定会话并清理该运行目录所属后台进程。

## Q3：CLI pane 创建与秘密边界

`shutsujin_departure.sh:621-662` 创建和标记 pane，并通过 `tmux send-keys` 发送 `cd`。CLI 分别在 `721-723`、`740-742`、`762-764`、`778-780`、`794-796` 通过 `tmux send-keys` 启动。

`lib/cli_adapter.sh:130-154` 支持从 settings YAML 读取 agent `env`，但 `147-149` 会把值渲染为 shell 命令前缀。`lib/cli_adapter.sh:288-303` 对 OpenCode 也会把该前缀放入发送给 tmux 的命令。因此上游 `env` 配置不能承载 API token：它会让秘密进入 YAML、pane 命令和可观察的进程参数。

入口仅在 `shutsujin_departure.sh:596,599` 用 `tmux set-environment` 设置非秘密的 `DISPLAY_MODE`，未发现面向秘密的文件描述符、命名管道或独立 env-file 注入点。

结论：不能把 secret 写入上游 settings。Skillify 在任务目录生成不含秘密的 `opencode`/`claude` launcher，并通过受控 `PATH` 让上游启动该 launcher。launcher 使用 pane 身份连接权限为 `0600` 的任务专属 Unix Socket；服务端按既有 `CredentialBroker` 的引用、auth profile 和 scope 规则获取短期凭据，然后只把它交给目标 CLI 子进程环境。starter 环境只使用显式非秘密白名单，禁止继承宿主 API key。

这使用了上游公开的可执行文件解析行为，没有修改上游源码，也没有通过任意 `send-keys` 输入秘密。

## Q4：watcher、supervisor 和停止语义

`shutsujin_departure.sh:893-939` 是当前生产入口的 watcher 启动路径。仓库中的 `watcher_supervisor.sh:7-8` 也以脚本目录为根，并在循环中管理 watcher；但除测试和 changelog 外未发现主入口调用它。

未发现独立、安全、可按团队句柄调用的 stop 入口。现有停止逻辑主要发生在下一次启动前，并依赖固定会话名和全局进程匹配。

结论：Skillify lifecycle 必须拥有停止和清理语义。单活约束下，它可以关闭固定的 `shogun`/`multiagent` 会话；后台进程优先按 `TeamHandle.run_dir` 的绝对脚本路径匹配，最后清理该团队的 socket、凭据 broker 缓存和临时 watcher 状态。重复 stop 必须幂等。

## Q5：worker workspace 与并发写保护

对 commit `431b86a` 全仓搜索未发现 `git worktree`。`scripts/auto_merge_short_lived.sh:92-118` 对配置的仓库路径检查单个工作树、fetch 并读取当前分支，没有为 worker 创建独立 worktree。

queue/inbox 的文件锁只保护消息文件，并不提供源码 workspace 所有权或写路径隔离。

结论：第一阶段不声称 Shogun 提供 worker 级 workspace 隔离。Skillify 继续以任务 `allowed_paths` 的互斥校验作为入场条件，并因固定 tmux 会话再加单活团队限制。Claude Code 等不能强制执行逐文件权限的后端仍属于可信主机上的剩余风险，不能作为多租户安全边界。

## Q6：config-only 或 upstream-change-required

TP-13 原始三个根因（运行目录、生命周期、pane 凭据）均为 **adapter/config-only**：

1. 运行时目录通过上游“入口目录即根目录”的公开布局实现；
2. 团队生命周期通过上游固定 tmux 会话实现，并在 Skillify 显式限制单活；
3. 凭据通过正常 `PATH` 可执行解析和任务专属 Unix Socket launcher 注入；
4. stop/recovery 由 Skillify 适配层基于稳定 `TeamHandle` 实现；
5. 不需要改动 commit `431b86a`。

2026-07-20 真实 formation 复核补充：上述判断只适用于 TP-13 三个原始根因，不能外推为完整上线批准。上游 `scripts/build_instructions.sh` 把所有 `ashigaruN` 固定映射到同一个 `ashigaru` 权限角色，并只读取 `read_allow/read_deny/edit_allow/edit_deny`；当前 Skillify 生成的逐 Worker `read/edit` 结构不会被该脚本采用。上游也没有 per-Worker worktree。因此，任意 WorkPackage 的逐 Worker 写路径隔离在当前批准 commit 上不能由公开配置表达，完整 Workspace/Security 门禁标记为 `upstream-contribution-or-blocker`。在该阻断解决且全 formation 任务闭环通过前，`infra/offline/shogun-manifest.json` 的 `installable` 必须保持 `false`，Team 相关 feature flag 必须保持关闭。

## Git-Worktree 可行性（2026-07-21，S0 契约冻结）

> 核对环境：`fzq@192.168.124.2` 上 `/home/fzq/.skillify-test/tp13-approved-20260720/install/`（TP-13 已批准 bundle，只读核对，未改动任何上游文件）。配套：`docs/2026-07-20-shogun-team-git-worktree-plan.md` §S0、`docs/2026-07-20-shogun-team-git-worktree-task.md` S0。

**Q1：`lib/cli_adapter.sh:130-154` 是否把 per-agent `env` 渲染进各 pane 命令**

是。`_cli_adapter_get_agent_env_prefix agent_id`（`lib/cli_adapter.sh:130-154`）从 `settings.yaml` 的 `cli.agents.{id}.env` 读取 dict，渲染为 `shlex.quote("KEY=VALUE")` 拼接的字符串。调用点在 `cli_adapter.sh:288`（`agent_env_prefix=$(_cli_adapter_get_agent_env_prefix "$agent_id")`），随后 `:303` 把其拼进最终 opencode 命令前缀：`cmd="${agent_env_prefix}OPENCODE_AGENT_ID=$quoted_agent_id OPENCODE_TUI_CONFIG=$tui_config_path $cmd"`。**该前缀落在 shell 命令行上（会出现在 `ps`/tmux 历史），只适合承载 `SKILLIFY_WORKER_ID`/`SKILLIFY_WORKTREE` 等非密标识，与 plan §3 判断一致，不可承载秘密。**

**Q2：`shutsujin_departure.sh:721-796`（对应本 bundle 约 700-800 行）启动 `opencode`/`claude` 的确切 argv 是否含显式 project/cwd 参数**

不含。三类 agent（karo/ashigaru/gunshi/shogun）命令均经 `build_cli_command "<agent_id>"` 或内联拼出，形如 `claude --model sonnet --effort max $PERMISSION_FLAG` 或（opencode）`--model … --agent <id>`，**均无 `--project`/`--cwd`/显式路径参数**。cwd 完全依赖 pane 的 shell 状态：建 pane 阶段已执行 `tmux send-keys -t "multiagent:agents.${p}" "cd \"$(pwd)\" && export PS1='...' && clear" Enter`（对应本 bundle 605-665 区间），把所有 pane 统一 cd 到脚本调用目录（当前 `run_dir` 根），随后才 `tmux send-keys` 发送 CLI 启动命令。**结论：launcher 在 `execve` 前的 `os.chdir(SKILLIFY_WORKTREE)` 不需要剥离/改写任何上游 argv**——上游命令行本身不带路径参数，chdir 后的 cwd 即生效；但 launcher 必须晚于 pane 既有的 `cd "$(pwd)"`（launcher 由 CLI 可执行文件解析链路触发，天然晚于该 send-keys，时序安全）。

**Q3：`TMUX_PANE`→agent 名的稳定映射，作为身份识别兜底**

存在**两条**独立于 per-agent env 的稳定通道，比 plan 草案假设更强：
1. 上游在建 pane 阶段对每个 pane 执行 `tmux set-option -p -t "multiagent:agents.${p}" @agent_id "${AGENT_IDS[$i]}"`（本 bundle 约 650 行区间，随 `PANE_LABELS`/`AGENT_IDS`/`PANE_COLORS` 循环写入），召唤阶段又写 `tmux set-option -p -t "multiagent:agents.${p}" @agent_cli "$_karo_cli_type"` 等（约 730-796 行）。**pane 级 tmux 用户选项 `@agent_id` 是上游自身已经维护的稳定身份源**，launcher 内可用 `tmux show-options -p -t "$TMUX_PANE" -v @agent_id` 读取，无需自行解析 pane title。
2. 现有 `credentials.py:126`（`_write_launcher`）launcher 已经把 `TMUX_PANE` 上报给凭据 socket（`sock.sendall(json.dumps({"pane": os.environ.get("TMUX_PANE", "")}).encode())`），但服务端 `_serve`（`credentials.py:87-115`）目前**只用它做请求格式校验（`re.fullmatch(r"%[0-9]+", ...)`）和 `SO_PEERCRED`/`peer_cwd` 校验，并未做 pane→worker 差异化应答**——当前所有请求收到相同的 `_resolve(state)` 结果。

**身份通道选定：主 = per-agent 非密 env（`SKILLIFY_WORKER_ID`/`SKILLIFY_WORKTREE`，plan §3/S3）；备 = launcher 内读 `tmux show-options -p -t "$TMUX_PANE" -v @agent_id`（发现 1，比 plan 原设想的 pane title 解析更稳，本轮更新为备用机制）；三备 = 扩展凭据 socket 按 `TMUX_PANE`→worker 映射应答（发现 2，S3 若需要可选实现，本轮不强制）。机制 1 与机制"备用"均可用 → 不触发 S0 失败条件（`upstream-contribution-or-blocker`）。**

**Q4：确认主入口/队列不触发 `auto_merge_short_lived.sh`**

`shutsujin_departure.sh` 主入口与 `lib/cli_adapter.sh`、pane/queue 相关脚本内**无任何对 `auto_merge_short_lived.sh` 的调用**（全仓 grep 排除脚本自身后只有一处引用）。唯一引用点是 `scripts/setup_cron.sh:30`：`0 */6 * * * bash $SCRIPT_DIR/scripts/auto_merge_short_lived.sh >> .../auto_merge_short_lived.log 2>&1`。`setup_cron.sh` 默认 `--print`（只打印，不写 crontab），仅 `--install` 才写入当前用户 crontab；核对主机 `crontab -l` 为空（`no crontab for fzq`），且仓内无任何脚本自动调用 `setup_cron.sh`。**结论：本轮验证环境下未触发，主入口/队列路径确认不触发。风险记录**：若运维此前对某台部署主机执行过 `setup_cron.sh --install`，该主机会有游离于 Shogun formation 之外的定时任务，每 6 小时对共享工作树做一次自动合并，与 worktree 方案的"仅 Integration 唯一合并"假设冲突——**建议 S2/S11 doctor 检查项增加 `crontab -l` 中 `auto_merge_short_lived` 关键字探测，Team 模式下探测到即告警**（记入风险登记，不阻塞 S0 通过）。

**Q5：冻结命名/策略/事件/恢复语义**

按 plan §3/§4/§7/§8 冻结，无需上游改动：分支命名 `skillify/team/<team-id>/{integration,worker/<worker-id>}`；merge 策略默认 `git merge --no-ff`（工作包声明单原子交付时用 cherry-pick）；事件集见 plan §7（`WORKTREE_CREATED`/`WORKER_COMMITTED`/`WORK_PACKAGE_SCOPE_REJECTED`/`INTEGRATION_*`/`REVIEW_REJECTED`/`WORKTREE_CLEANED`）；恢复语义并入现有 `ShogunProvider.recover`（本地核对 `providers/shogun.py:190` `recover`、`:92` `start`、`:265` `stream_events`，行号与 plan §1/§8 引用一致，未漂移）。

**Q6：编排/DB 边界确认**

- 编排边界：本 bundle 未发现独立 Git Scheduler/Queue/Coordinator，也未发现独立 Integration/Reviewer Agent 调度入口；召唤脚本按 formation 固定角色（shogun/karo/ashigaruN/gunshi）逐一起 pane，与 plan §0 的"Integration 由现有主将/家老 pane、Reviewer 由现有军师 pane 承担"假设一致，未发现冲突证据。
- 端侧 DB 边界：本地仓核对 `src/skillify/cli/bridge_cmd.py:54-79`（`HttpBridgeTransport.pull`/`confirm`）只经 `requests` 调用 `{server_url}/api/endpoint/tasks/...` HTTP 接口，无任何 DM 驱动导入；`src/skillify/mcp/db_readonly/connector.py:205-218`（`create_configured_server`）确认连接目标完全由 `SKILLIFY_MCP_DM8_HOST/PORT/USER/PASSWORD/TABLES` 环境变量决定，无硬编码正式库地址。行号与 plan §0 引用一致。

**S0 结论：机制 1（per-agent env 渲染）与机制 3（TMUX_PANE 身份兜底，本轮升级为 `@agent_id` tmux pane option 读取）均可用 → 未触发失败条件，放行进入 S1。** 新增风险项（`auto_merge` 游离 cron）记入 plan §17 风险表，不阻塞。
