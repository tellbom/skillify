# Skillify 官方 Agent SDK 托管与 Web 决策闭环改造任务

请基于当前 Skillify 项目源码，完成 OpenCode、Claude Code 从 TUI/终端模拟控制模式向官方程序化托管模式的改造，并打通：

```text
Skillify Web
→ Skillify API
→ Endpoint skillctl
→ Agent Runtime Host
→ OpenCode / Claude Code
→ 用户决策回到 Web
→ 原 Agent Session 继续
→ 最终 Git 与 Gate 验收
```

本轮先不处理 MCP 配置投影、Forgejo Issue 评论交互、PR 自动创建和人工终端接管。

本轮唯一核心是：

```text
官方 SDK 托管
+ Provider Session 持久化
+ 实时结构化事件
+ Web 用户决策
+ 原会话暂停与恢复
+ Team Worker 非全局阻塞
+ 最终 Gate 独立验收
```

---

# 一、产品目标

当前 OpenCode、Claude Code 不应继续被当成一个需要模拟键盘输入的终端程序。

目标架构应当是：

```text
用户在 Skillify Web 创建代码任务
        ↓
skillctl 准备工作区并启动 Agent Runtime
        ↓
Agent Runtime 通过官方 SDK/Server 创建 Provider Session
        ↓
Agent持续分析、修改和测试
        ↓
结构化事件实时回传 Web
        ↓
Agent需要权限或业务判断
        ↓
当前 Worker进入 waiting_user
        ↓
Web显示决策卡片
        ↓
用户选择或填写意见
        ↓
答案返回原 Provider Session
        ↓
当前 Worker从原位置继续执行
        ↓
其他无依赖 Worker继续运行
        ↓
所有必需 Worker完成
        ↓
skillctl执行最终 Git、测试与 Gate
        ↓
形成可验证的最终状态
```

用户不需要：

* 打开 OpenCode 或 Claude Code 的 TUI；
* 在终端中输入答案；
* 去 Forgejo Issue 评论区回复 Agent；
* 因为一个问题重新启动整个任务；
* 观察原始终端控制字符；
* 理解 Provider内部事件格式。

---

# 二、核心架构边界

请将系统职责明确划分为以下五层。

## 2.1 Skillify Web

负责：

* 展示任务执行时间线；
* 展示 Agent文本输出；
* 展示工具调用；
* 展示 Worker状态；
* 展示权限请求；
* 展示业务问题；
* 收集用户选择；
* 收集自由文本意见；
* 提供拒绝、取消和停止入口；
* 展示最终 Diff、测试和 Gate结果。

Web不负责：

* 直接连接本地 OpenCode端口；
* 直接连接 Claude SDK；
* 向 TUI发送字符；
* 维护 Provider Session；
* 判断代码是否成功交付。

---

## 2.2 Skillify API

负责：

* Task Run状态；
* Worker Run状态；
* Provider Session映射；
* 结构化事件持久化；
* Interaction请求持久化；
* 用户决策持久化；
* Endpoint与Web之间的可靠消息交换；
* SSE或WebSocket浏览器推送；
* 幂等控制；
* 审计记录；
* Team依赖状态；
* Gate结果存储。

API不能只把用户回答暂存在内存中。

---

## 2.3 skillctl

skillctl不参与业务裁决，也不替用户选择答案。

skillctl负责“一头一尾”和运行时监管。

### 一头：任务启动前

负责：

* 领取任务；
* 验证Endpoint；
* 解析工作区别名；
* 准备仓库或worktree；
* 记录baseline commit；
* 创建Worker Runtime Manifest；
* 启动Agent Runtime Host；
* 建立taskRun、worker与Provider Session关系；
* 上传实际启动信息。

### 中间：保持可靠通道

skillctl虽然不作决策，但仍必须：

* 监管Agent Runtime进程；
* 转发结构化事件；
* 领取用户回答；
* 把回答交给正确Provider Session；
* 处理中止、超时、断线和重连；
* 维护本地Session Registry；
* 防止回答串到其他Worker；
* 防止旧回答进入新Session；
* 对运行状态进行心跳和对账。

### 一尾：Agent结束后

负责：

* 收集Provider最终结果；
* 检查工作区状态；
* 收集Git Diff；
* 验证Worker commit；
* 运行最终测试；
* 执行integration Gate；
* 保存最终证据；
* 决定进入`awaiting_review`、`succeeded`或`failed`；
* 在完成证据持久化后再清理临时工作区。

skillctl不能退化为：

```text
启动进程
→ 等待退出码
→ 标记成功
```

---

## 2.4 Agent Runtime Host

建议新增独立运行层：

```text
skillify-agent-host
```

推荐使用Node.js/TypeScript实现，因为：

* OpenCode提供官方JS/TS SDK；
* Claude Agent SDK提供TypeScript接口；
* 两个Provider可以使用统一异步事件和Session模型；
* 便于实现长连接、流式消息和运行时权限回调。

架构：

```text
skillctl
  ↓ 本地受控协议
skillify-agent-host
  ├── OpenCodeAdapter
  └── ClaudeCodeAdapter
```

Agent Runtime Host负责：

* 创建Provider实例；
* 创建Provider Session；
* 订阅Provider事件；
* 转换为Skillify统一事件；
* 暂停等待用户回答；
* 将回答回复Provider；
* 中止Provider Session；
* 查询Session状态；
* 输出最终Provider结果；
* 向skillctl报告心跳。

它不负责：

* Git集成门禁；
* Team成功判定；
* 用户权限体系；
* 业务Workflow定义；
* 最终任务归档。

如果不新增独立Node进程，也可以在现有代码中实现等价的Provider Runtime模块，但必须保证官方SDK调用与现有Bridge职责解耦。

---

## 2.5 Gate

Gate是唯一有权确认代码交付成功的模块。

Agent输出：

```text
任务完成
```

Provider Session状态：

```text
idle
```

或者进程退出：

```text
exit code 0
```

均不能单独代表任务成功。

最终状态必须依据：

```text
必需Worker全部达到可交付状态
+ 工作区修改已持久化
+ commit存在
+ integration完成
+ 最终测试通过
+ Gate规则通过
+ 最终证据已保存
```

---

# 三、禁止继续使用TUI作为默认控制协议

完成改造后，默认运行链路禁止依赖：

* PTY模拟用户键盘；
* 固定时间等待Prompt；
* 识别终端提示符；
* 解析ANSI字节判断状态；
* 自动输入“1”完成目录信任；
* 把任务文本写入TUI输入缓冲；
* 通过Ctrl+C字符模拟服务端取消；
* 根据终端是否安静判断任务完成；
* 用户与Shogun同时向终端写入。

允许保留旧Provider作为短期兼容路径，但必须：

* 默认关闭；
* 明确标记为legacy；
* 不能用于新的Web交互闭环；
* 不允许新代码继续依赖其事件格式；
* 有明确删除计划。

---

# 四、OpenCode官方托管方向

OpenCode优先使用：

```text
OpenCode Server
+ @opencode-ai/sdk
+ Session API
+ Event Subscribe
+ Permission Reply
+ Session Abort
+ Session Diff
```

## 4.1 实例模型

每个Worker拥有独立的：

* OpenCode Server实例或隔离Session；
* Provider Session ID；
* 工作目录；
* Worker ID；
* Task Run ID；
* 权限配置；
* Server进程信息；
* Abort控制器。

建议映射：

```text
taskRunId
→ teamRunId
→ workerId
→ provider=openCode
→ serverInstanceId
→ providerSessionId
→ workspace
```

不得通过“当前活跃Session”推测目标Session。

---

## 4.2 OpenCode启动

优先通过SDK创建或连接本地Server。

Server默认只监听：

```text
127.0.0.1
```

不要直接暴露给局域网或浏览器。

Skillify Web不能直接访问OpenCode Server。

只允许：

```text
OpenCode Server
↔ Agent Runtime Host
↔ skillctl
↔ Skillify API
```

每个Server实例应：

* 使用动态端口或受控端口池；
* 设置认证；
* 绑定当前Worker；
* 记录PID；
* 记录启动时间；
* 有健康检查；
* 有关闭和异常回收机制；
* 防止跨任务复用错误Session。

---

## 4.3 OpenCode事件订阅

通过官方事件订阅持续接收：

* Session创建；
* Session状态；
* Session更新；
* Session错误；
* Session空闲；
* 文本消息；
* 消息增量；
* 工具执行前后；
* 文件编辑；
* Permission requested；
* Permission replied；
* 子Session创建；
* Diff变化。

转换为Skillify统一事件，不把OpenCode原始事件格式直接暴露给Web。

---

## 4.4 OpenCode权限请求

当OpenCode出现需要询问的操作时：

```text
permission.asked
```

必须转换为：

```text
interaction.requested
```

Web允许用户选择：

* 允许本次；
* 当前Session持续允许；
* 拒绝；
* 拒绝并附加原因；
* 取消当前Worker。

用户回答后：

```text
Skillify API
→ skillctl
→ Agent Runtime Host
→ OpenCode Permission Reply API
→ 原Session继续
```

禁止：

* 把回答转换成终端文字；
* 重新向Session发送完整任务Prompt；
* 创建新Session代替原Session；
* 将一次允许错误升级为永久全局允许。

---

## 4.5 OpenCode业务问题

OpenCode提出的业务澄清问题也应转换为统一Interaction。

例如：

```text
登录失败应返回401，还是跳转到登录页面？
```

Web支持：

* 单选；
* 多选；
* 自由文本；
* 选择后补充说明。

回答必须返回原Session上下文。

如果OpenCode官方问题事件与权限事件类型不同，Provider Adapter负责转换，Web不感知差异。

---

## 4.6 OpenCode取消

用户点击“取消Worker”时：

```text
Web
→ API记录cancel_requested
→ skillctl领取
→ Runtime Host调用Session Abort
→ 等待Provider确认
→ Worker变为cancelled
```

不能仅修改数据库状态，而不停止实际Session。

如果Abort失败：

* 标记`cancel_failed`；
* 继续尝试停止Provider进程组；
* 保存失败原因；
* 不允许误报`cancelled`。

---

## 4.7 OpenCode最终结果

Session进入idle不代表成功。

Runtime Host应输出：

* Provider Session ID；
* 最终消息；
* Provider错误；
* Session Diff；
* 文件修改摘要；
* 子Session列表；
* 最后事件序号；
* 是否正常结束；
* 是否被Abort；
* 是否仍有pending interaction。

随后由skillctl执行Git和Gate检查。

---

# 五、Claude Code官方托管方向

Claude Code优先使用：

```text
Claude Agent SDK
```

次选兼容路径：

```text
claude -p
--output-format stream-json
--verbose
--include-partial-messages
```

只有当当前环境无法安全使用Agent SDK时，才允许使用`-p + stream-json`。

不得继续使用交互式TUI作为默认托管方式。

---

## 5.1 Claude Agent SDK模式

优先使用持久的Streaming Input模式，而不是每次创建一次性Prompt。

每个Worker需要保存：

* Provider Session ID；
* SDK Client实例标识；
* Task Run ID；
* Worker ID；
* 工作目录；
* permission mode；
* allowed/disallowed tool策略；
* 当前状态；
* 最后事件序号；
* pending interaction；
* resume信息。

---

## 5.2 Claude权限请求

使用官方运行时权限回调处理用户授权。

链路：

```text
Claude请求工具
→ SDK权限回调
→ Runtime Host创建interaction.requested
→ Skillify API保存
→ Web显示决策卡片
→ 用户回答
→ skillctl转发回答
→ Runtime Host完成权限回调
→ Claude原会话继续
```

权限回调等待期间：

* 当前Worker状态变为`waiting_user`；
* Provider Session保持绑定；
* 其他Worker继续运行；
* 不把当前Worker标记blocked；
* 不结束整个Team；
* 不重新启动Claude任务。

---

## 5.3 Claude业务问题

Claude的用户问题必须进入相同Web交互通道。

例如：

```text
Agent需要确认API兼容策略
```

转换为：

```json
{
  "kind": "question",
  "title": "确认API兼容策略",
  "question": "是否必须保持旧字段兼容？",
  "choices": [
    "保持完全兼容",
    "允许breaking change"
  ],
  "allowFreeText": true
}
```

回答后恢复原Claude Session。

---

## 5.4 Claude Session保存与恢复

每个Claude Worker必须保存真实Provider Session ID。

需要支持：

* 同一进程内继续会话；
* Agent Runtime重启后恢复指定Session；
* Endpoint短暂掉线后对账；
* 用户较晚回答时确认Session仍有效；
* Session不可恢复时明确失败；
* 禁止静默创建新Session冒充恢复成功。

需要明确区分：

```text
恢复会话上下文
≠ 恢复文件系统
```

文件修改和Git状态仍由工作区保存，不能仅依赖Claude Session历史。

---

## 5.5 Claude降级路径

如果Agent SDK暂时无法在当前部署条件中稳定运行，可以使用：

```text
claude -p + stream-json
```

降级模式必须满足：

* 不进入目录信任TUI；
* 不模拟键盘；
* 输出结构化JSON；
* 保存Session ID；
* 支持继续或恢复会话；
* 能识别文本、工具调用、错误和最终结果；
* 未授权操作不能静默放开。

如果降级模式无法支持Web动态决策后恢复原调用：

* 必须明确标记该Provider能力为`limited_interaction`；
* 不允许伪造“已支持实时批准”；
* 遇到动态决策时进入可恢复暂停或明确失败；
* 优先继续完成SDK模式。

---

# 六、统一Provider接口

OpenCode和Claude底层不同，但Skillify上层必须使用统一Provider协议。

建议接口：

```text
startSession()
sendPrompt()
subscribeEvents()
respondInteraction()
abortSession()
getSessionState()
getSessionDiff()
resumeSession()
closeSession()
```

建议Provider Adapter：

```text
OpenCodeAdapter
ClaudeAgentSdkAdapter
ClaudeStreamJsonAdapter
```

上层不能出现大量：

```text
if provider == "opencode"
if provider == "claude"
```

Provider差异应收敛在Adapter内部。

---

# 七、Provider Session Registry

新增或完善Session Registry。

每条记录至少包含：

```json
{
  "taskRunId": "run-123",
  "teamRunId": "team-123",
  "workerId": "worker-backend",
  "provider": "opencode",
  "providerSessionId": "session-abc",
  "runtimeInstanceId": "runtime-001",
  "endpointId": "endpoint-01",
  "workspace": "/path/to/worktree",
  "status": "running",
  "lastEventSequence": 81,
  "startedAt": "...",
  "lastSeenAt": "...",
  "endedAt": null,
  "resumeMetadata": {},
  "pendingInteractionId": null
}
```

状态至少包括：

```text
starting
running
waiting_user
resuming
cancelling
cancelled
completed
failed
lost
```

Session Registry必须同时存在：

* Endpoint本地可靠状态；
* Skillify API服务端状态。

二者重连后需要对账。

---

# 八、统一结构化事件协议

禁止让Web分别理解Claude和OpenCode原始事件。

统一事件至少包括：

```text
agent.session.started
agent.output.delta
agent.output.completed
agent.tool.started
agent.tool.completed
agent.file.changed
agent.test.detected
agent.subsession.started
agent.subsession.completed
interaction.requested
interaction.responded
interaction.delivered
interaction.applied
agent.session.waiting_user
agent.session.resumed
agent.session.cancelled
agent.session.completed
agent.session.failed
gate.started
gate.completed
```

每个事件至少携带：

```json
{
  "eventId": "evt-001",
  "sequence": 81,
  "taskRunId": "run-123",
  "teamRunId": "team-123",
  "workerId": "worker-backend",
  "provider": "opencode",
  "providerSessionId": "session-abc",
  "eventType": "agent.tool.started",
  "payload": {},
  "createdAt": "..."
}
```

要求：

* sequence在单Worker内单调递增；
* eventId全局唯一；
* API重复收到同一eventId时幂等；
* Endpoint重连后从最后确认sequence补传；
* 事件内容经过脱敏；
* 大文本分片存储；
* Web重连后能够补发历史事件。

---

# 九、Web用户决策模型

## 9.1 Interaction类型

至少支持：

```text
permission
question
plan_confirmation
risk_confirmation
choice
free_text
```

---

## 9.2 Interaction请求模型

建议：

```json
{
  "interactionId": "int-123",
  "taskRunId": "run-123",
  "teamRunId": "team-123",
  "workerId": "worker-backend",
  "provider": "claude",
  "providerSessionId": "session-abc",
  "providerRequestId": "provider-request-001",
  "kind": "permission",
  "title": "允许执行测试命令？",
  "description": "pytest tests/test_auth.py",
  "choices": [
    {
      "id": "allow_once",
      "label": "允许本次"
    },
    {
      "id": "allow_session",
      "label": "本会话允许"
    },
    {
      "id": "deny",
      "label": "拒绝"
    }
  ],
  "allowFreeText": true,
  "status": "pending",
  "createdAt": "...",
  "expiresAt": "..."
}
```

---

## 9.3 Interaction响应

建议API：

```text
POST /api/task-runs/{taskRunId}/interactions/{interactionId}/respond
```

请求：

```json
{
  "choice": "allow_once",
  "answer": null,
  "comment": "仅允许当前测试命令",
  "responseVersion": 1
}
```

自由文本：

```json
{
  "choice": "custom",
  "answer": "保持旧API兼容，同时新增新的错误码字段。",
  "responseVersion": 1
}
```

---

## 9.4 Interaction状态

至少包含：

```text
pending
responded
delivering
delivered
applied
rejected
expired
cancelled
superseded
failed
```

含义：

* `responded`：Web用户已提交；
* `delivered`：Endpoint已收到；
* `applied`：Provider确认回答已进入原Session；
* `expired`：Session已结束或请求超时；
* `superseded`：Provider产生了新请求，旧请求失效。

任务详情页要明确区分：

```text
用户已回答
≠ Agent已经收到
≠ Agent已经继续执行
```

---

# 十、Web界面要求

任务详情页至少增加以下区域。

## 10.1 Worker树

显示：

```text
Team Run
├── backend-worker      running
├── frontend-worker     waiting_user
├── test-worker         completed
└── report-worker       running
```

---

## 10.2 实时时间线

显示结构化内容：

```text
10:21  backend-worker开始分析代码
10:22  正在读取src/auth.py
10:23  准备执行pytest tests/test_auth.py
10:23  等待用户授权
10:24  用户允许本次执行
10:24  Worker继续运行
10:25  测试结果：2 failed, 18 passed
```

默认不显示逐Token思考内容。

---

## 10.3 决策卡片

权限卡片：

```text
backend-worker 请求执行：

pytest tests/test_auth.py

[允许本次] [本会话允许] [拒绝]
```

业务卡片：

```text
需要确认：

登录失败时应返回401还是跳转登录页面？

○ 返回401
○ 跳转登录页面

补充说明：[________________]

[提交决定]
```

方案确认卡片：

```text
Agent计划修改8个文件并调整公共API。

[按方案继续]
[填写修改意见]
[停止Worker]
```

---

## 10.4 任务控制

提供：

* 取消当前Worker；
* 取消整个Team；
* 查看实时事件；
* 查看文件修改；
* 查看测试；
* 查看最终Gate；
* 查看历史Interaction。

本轮不增加可输入终端。

---

# 十一、Team非全局阻塞调度

一个Worker等待用户时，不应冻结整个Team。

示例：

```text
backend-worker：waiting_user
frontend-worker：running
docs-worker：running
test-worker：waiting_dependency
Team：running_with_pending_interactions
```

调度规则：

1. 提出Interaction的Worker暂停；
2. 依赖该Worker输出的节点进入`waiting_dependency`；
3. 无依赖Worker继续运行；
4. Team总体状态保持运行；
5. Web显示存在待处理决策；
6. 用户回答后仅恢复对应Worker；
7. 最终Gate等待所有必需Worker完成。

禁止：

* 一个Worker等待用户时停止所有Worker；
* 把`waiting_user`直接标记为`blocked`；
* 因等待用户而结束Provider Session；
* 用户回答后重新创建整个Team任务。

---

# 十二、平台策略与用户决策必须分离

并非所有权限都能交给用户临时放开。

平台硬性拒绝：

* 访问未授权工作区；
* 读取凭据目录；
* 读取受保护环境变量；
* 修改系统目录；
* `sudo`；
* 强制推送；
* 覆盖主分支；
* 删除工作区根目录；
* 终止Skillify自身服务；
* 绕过审计。

这些请求应直接：

```text
policy_denied
```

不能生成“允许”按钮。

只有平台策略允许询问的操作，才进入Web决策。

权限顺序建议：

```text
Platform deny
→ Workflow deny
→ Worker allow
→ User ask
→ Provider执行
```

用户不能覆盖前两层deny。

---

# 十三、断线与恢复

## 13.1 浏览器断线

浏览器关闭或刷新：

* Agent继续运行；
* Interaction保留；
* 事件继续存储；
* 用户重连后补发；
* 不停止Provider Session。

---

## 13.2 Skillify API暂时不可达

Endpoint应：

* 本地缓存事件；
* Provider继续运行；
* pending Interaction进入等待；
* 恢复后按sequence补传；
* 不重复创建Interaction；
* 不重复应用回答。

---

## 13.3 skillctl或Runtime Host重启

重启后：

1. 读取本地Session Registry；
2. 检查Provider进程或Server是否仍存活；
3. 查询Provider Session；
4. 与服务端状态对账；
5. 可以恢复则进入`resuming`；
6. 无法恢复则进入`lost`或`failed`；
7. 不允许静默创建新Session继续旧任务。

---

## 13.4 用户回答过晚

在应用回答前检查：

* Interaction仍为pending/responded；
* Provider Session仍有效；
* providerRequestId仍匹配；
* Worker仍处于waiting_user；
* 回答版本未过期。

不满足条件时返回：

```text
interaction_expired
```

不能把旧回答注入新请求。

---

# 十四、取消语义

明确区分：

```text
关闭浏览器
≠ 取消任务
```

用户点击取消时：

```text
cancel_requested
→ Endpoint领取
→ Provider Abort
→ 等待Provider结束
→ 收集现有Diff和日志
→ worker=cancelled
```

取消Team：

* 停止所有未完成Worker；
* 取消pending Interaction；
* 不进入最终成功Gate；
* 保存已经产生的证据；
* 不把人工取消标记为失败。

---

# 十五、最终Gate

Agent Runtime只提供运行结果，不能确认业务成功。

最终Gate至少检查：

1. 所有必需Worker状态；
2. 不存在pending Interaction；
3. Provider Session均已正常结束；
4. 工作区不存在未归档修改；
5. 每个交付Worker有有效commit；
6. Worker commit进入integration分支；
7. integration分支测试通过；
8. integration commit形成；
9. 目标修改包含在integration commit；
10. Diff、测试和报告已经持久化；
11. 无策略违规；
12. 无未处理冲突。

状态建议：

```text
agent_completed
integration_pending
integration_verifying
gate_failed
awaiting_review
succeeded
cancelled
failed
```

成功必须来自Gate，不来自Agent文本。

---

# 十六、实施阶段

## Phase 0：源码审计与基线

先阅读真实代码，输出：

* 当前OpenCode启动链路；
* 当前Claude启动链路；
* 当前TUI输入位置；
* 当前Provider事件模型；
* Worker状态模型；
* Team调度模型；
* 取消链路；
* Gate链路；
* Web任务详情结构；
* 数据库迁移方式；
* 当前测试基线。

先跑定向测试和全量测试，记录原始结果。

---

## Phase 1：统一协议与数据模型

实现：

* Provider Adapter接口；
* Provider Session Registry；
* Agent Event模型；
* Interaction模型；
* Interaction响应API；
* Worker新状态；
* Team聚合状态；
* 数据库迁移；
* API序列化。

这一阶段先用Fake Provider跑通。

---

## Phase 2：OpenCode官方接入

实现：

* OpenCode Server生命周期；
* 官方SDK客户端；
* Session创建；
* Event订阅；
* Permission转发；
* 用户回复；
* Abort；
* Diff；
* Session结束；
* Session Registry。

删除或旁路默认TUI控制。

---

## Phase 3：Claude Agent SDK接入

实现：

* Claude Agent SDK Adapter；
* Streaming Input；
* 权限回调；
* 用户问题；
* Session ID；
* Resume；
* Abort；
* 结构化消息；
* 最终结果。

保留`-p + stream-json`作为明确降级Provider。

---

## Phase 4：Web决策界面

实现：

* Worker树；
* 实时时间线；
* 权限卡片；
* 问题卡片；
* 自由文本；
* Interaction状态；
* 重复提交保护；
* 过期提示；
* Worker取消；
* Team取消。

---

## Phase 5：Team非阻塞调度

实现：

* 单Worker `waiting_user`；
* 无依赖Worker继续；
* 依赖节点等待；
* 回答后恢复指定Worker；
* Team状态聚合；
* 最终Gate等待必需节点。

---

## Phase 6：恢复与对账

实现：

* 浏览器重连；
* Endpoint断线；
* Event Outbox；
* Interaction幂等；
* Session恢复；
* Runtime Host重启；
* Provider Session丢失；
* 旧回答过期。

---

## Phase 7：最终Gate接线

确保：

```text
Provider完成
≠ Task成功
```

将最终状态统一收口到现有或新Gate。

---

# 十七、自动化测试

## 17.1 Provider协议测试

* 两个Provider都实现统一接口；
* Provider原始事件被正确转换；
* Session ID正确保存；
* Worker A事件不会进入Worker B；
* 事件sequence正确；
* 重复事件幂等。

---

## 17.2 Interaction测试

* 权限请求生成Interaction；
* 业务问题生成Interaction；
* 用户选择正确保存；
* 自由文本正确保存；
* 回答送达正确Worker；
* Provider确认后状态进入applied；
* 重复回答被拒绝；
* 过期回答被拒绝；
* 旧providerRequestId不能注入新Session；
* 用户拒绝时Provider收到拒绝原因。

---

## 17.3 OpenCode真实测试

至少验证：

1. 官方Server成功启动；
2. SDK成功连接；
3. Session创建成功；
4. 实时事件可订阅；
5. OpenCode提出权限请求；
6. Web模拟用户允许本次；
7. 原Session继续；
8. Session Diff可读取；
9. Abort能够停止Session；
10. Server退出后状态正确。

---

## 17.4 Claude真实测试

至少验证：

1. Agent SDK成功启动；
2. Streaming Input正常；
3. Session ID可获得；
4. Claude提出工具权限；
5. Web模拟回答；
6. 原会话继续；
7. Claude提出业务问题；
8. 自由文本回到原会话；
9. Session能够resume；
10. 取消后正确结束。

同时测试`-p + stream-json`降级模式，并明确其交互能力边界。

---

## 17.5 Team调度测试

创建至少三个Worker：

```text
Worker A：提出用户问题
Worker B：持续执行
Worker C：依赖A
```

验证：

* A进入waiting_user；
* B继续执行；
* C进入waiting_dependency；
* Team保持running_with_pending_interactions；
* 用户回答后仅A恢复；
* A完成后C继续；
* 最终Gate等待A、B、C；
* 不会重启整个Team。

---

## 17.6 断线测试

* Web断线后Agent继续；
* Web重连后补发事件；
* API短暂不可用时Endpoint缓存；
* Event重复上传幂等；
* 用户回答后Endpoint暂时掉线；
* 重连后只应用一次；
* Runtime Host重启后Session对账；
* Session无法恢复时明确失败。

---

## 17.7 Gate测试

* Agent说完成但无commit，Gate失败；
* Provider正常退出但测试失败，Gate失败；
* 有pending Interaction时不能成功；
* 某必需Worker未完成时不能成功；
* integration commit缺失时不能成功；
* Gate通过后才进入awaiting_review或succeeded。

---

# 十八、真实页面闭环验收

至少完成两条真实链路。

## 链路A：OpenCode

```text
Web创建任务
→ Endpoint启动OpenCode官方Server
→ 创建Session
→ Web看到实时输出
→ OpenCode请求执行命令
→ Web显示权限卡片
→ 用户允许本次
→ 原Session继续
→ 修改代码
→ 测试
→ Agent结束
→ Gate验收
```

## 链路B：Claude Code

```text
Web创建任务
→ Endpoint启动Claude Agent SDK
→ 创建Session
→ Web看到实时输出
→ Claude提出业务问题
→ Web显示选项和自由文本
→ 用户提交意见
→ 原Claude Session继续
→ 修改代码
→ 测试
→ Agent结束
→ Gate验收
```

真实验收必须证明：

* 没有打开TUI；
* 没有模拟按键；
* 没有把问题写到Issue评论；
* 用户回答进入原Session；
* 一个Worker等待时其他Worker继续；
* 最终成功由Gate决定。

---

# 十九、范围限制

本轮不做：

* MCP配置重构；
* Forgejo Issue交互；
* 自动PR；
* 自动关闭Issue；
* 可输入Web终端；
* PTY重连；
* 人工接管；
* 任意Prompt聊天框；
* 多用户共同操作同一Agent；
* 浏览器直接连接端侧Provider；
* 大规模重写现有Workflow业务模型。

本轮允许做：

* 必要的数据库迁移；
* Provider Runtime抽象；
* Agent Runtime Host；
* API和Web交互；
* 状态机扩展；
* Gate接线；
* 旧TUI Provider兼容层。

---

# 二十、交付报告

完成后输出完整报告。

## 20.1 源码改动

列出：

* 修改文件；
* 新增模块；
* 数据库迁移；
* Provider Adapter；
* Runtime Host；
* Session Registry；
* Interaction模型；
* API接口；
* Web组件；
* Team调度；
* Gate修改。

## 20.2 官方接入方式

明确回答：

1. OpenCode是否已使用官方Server/SDK？
2. 是否使用事件订阅？
3. 是否能回复Permission？
4. 是否能Abort Session？
5. 是否保存Session ID？
6. Claude是否已使用Agent SDK？
7. 若使用降级路径，具体原因是什么？
8. Claude用户问题是否能回到Web？
9. 用户回答是否进入原Session？
10. 是否彻底移除默认TUI模拟输入？

## 20.3 测试结果

分别报告：

* 模型层测试；
* API测试；
* Web测试；
* OpenCode真实测试；
* Claude真实测试；
* Team非阻塞测试；
* 断线恢复测试；
* Gate测试；
* Linux全量回归结果。

Mock测试和真实Provider测试必须分开报告。

## 20.4 证据

提供：

* 真实Task Run ID；
* Worker ID；
* Provider Session ID；
* Interaction ID；
* 事件时间线；
* 用户决策；
* Provider恢复事件；
* Git commit；
* Gate结果；
* 最终代码提交。

## 20.5 最终裁决

必须明确回答：

1. 用户能否完全在Skillify Web中完成Agent裁决？
2. 是否不再依赖Issue评论完成中间交互？
3. 是否不再依赖TUI字节流和模拟按键？
4. OpenCode是否从原Session继续？
5. Claude是否从原Session继续？
6. 一个Worker等待用户时，其他Worker是否继续？
7. Endpoint断线后事件和回答是否能够可靠恢复？
8. Agent输出成功但Gate失败时，任务是否会被阻止成功？
9. 是否仍存在Session串用或回答串用风险？
10. 是否达到真实可部署状态？

发现问题时直接修复并继续测试，不要只输出设计评审。

只有在官方Provider接入、Web交互闭环、Session持久化、Team非阻塞调度和最终Gate全部完成真实验证后，才能给出完成结论。
