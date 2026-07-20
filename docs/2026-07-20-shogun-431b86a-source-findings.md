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

六项结论均为 **adapter/config-only**：

1. 运行时目录通过上游“入口目录即根目录”的公开布局实现；
2. 团队生命周期通过上游固定 tmux 会话实现，并在 Skillify 显式限制单活；
3. 凭据通过正常 `PATH` 可执行解析和任务专属 Unix Socket launcher 注入；
4. stop/recovery 由 Skillify 适配层基于稳定 `TeamHandle` 实现；
5. workspace 风险由 Skillify admission 约束，不声称上游具备不存在的 worktree；
6. 不需要改动 commit `431b86a`。

因此本轮不触发 `upstream-contribution-or-blocker`。在 S9.1-S9.4 和对应 Linux 集成测试全部通过前，`infra/offline/shogun-manifest.json` 的 `installable` 必须保持 `false`，Team 相关 feature flag 必须保持关闭。
