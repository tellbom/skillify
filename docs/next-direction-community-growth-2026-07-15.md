# Skillify 下一步改进方向 · 社区拓展分析

> 日期：2026-07-15
> 目的：在内网已出现竞品（Skillhub）的前提下，分析 Skillify 应优先增强哪些能力，
> 以更好服务软件开发人员、并降低非技术人员上手 Skill 的门槛，从而拓展内部社区。
> 方法：结合仓库现状（README/PLAN/TASKS/评审文档）+ 2025–2026 外部生态调研。
> 结论供用户裁决，不含实现级任务清单。

---

## 一、结论先行（TL;DR）

Skillify 的当前定位是对的——**Forgejo 不可变构件 + 每 Skill 独立 venv + 内网离线 + 已复用公司
Keycloak/RBAC**，这套地基是竞品短期抄不走的护城河，不要为对齐任何竞品而牺牲它。

拓展社区的真正杠杆不在"再堆一个企业级注册中心的功能清单"，而在**填平当前生态已经形成
共识、而 Skillify 还是空白的三个能力位**，并且这三个能力恰好把"服务开发者"和"帮非技术
人员上手"两条诉求分别打透：

| 方向 | 服务对象 | 价值 | 成本 | 优先级 |
| --- | --- | --- | --- | --- |
| **A. MCP 连接器纳入平台**（Skill 之外的第二类构件 + 私有子注册中心） | 开发者 | 高·标准对齐·未来护城河 | 中 | **P1** |
| **B. Skill 组合 / 声明式编排**（把预留的 `orchestration` 字段做实） | 开发者 | 高·差异化 | 中 | **P1** |
| **C. 可视化：思维导图 / 依赖图 / 组合图** | 非技术 + 开发者 | 中·上手与理解 | **低** | **P1（快赢）** |
| **D. 引导式创作向导 + 描述优化闭环** | 非技术 | 高·降门槛 | 中（已有地基） | **P1** |
| **E. 上传静态安全扫描 + 评级** | 全体·信任 | 中·信任杠杆 | 中 | P2 |
| **F. 在线可视化 Agent 编排画布** | 开发者 | 高·但风险与成本最高 | **高** | **P3 / 谨慎** |
| **G. 就绪度地基**（部署包、Alembic/DM8、发布可恢复、版本中心、我的 Skill） | 全体 | 前置必做 | 中 | **P0 前置** |

**对你三个想法的直接裁决：**

1. **MCP —— 做，且是最值得做的方向之一**，但要理解它和 Skill 是**互补而非替代**：
   MCP 是"动词/管道"（连接工具），Skill 是"操作手册/剧本"（怎么用工具）。Skillify 现在
   只托管 Skill，把 MCP 服务器也纳入平台，会让开发者把 Skillify 当成"内网唯一的 Agent
   能力入口"，粘性大幅提升。**建议实现 MCP 官方注册中心的私有子注册中心协议**（其 OpenAPI
   明确支持企业内网子注册中心），标准对齐、离线友好。见 §五-A。

2. **代码/技能思维导图 —— 做，定位成"上手与理解的低成本快赢"**，不要当成大工程。
   `markmap` 可以直接把 SKILL.md 渲染成可折叠思维导图（纯前端、无后端往返），`Mermaid`
   可以把 Skill 结构/依赖画成流程图。这是**帮非技术人员看懂一个 Skill 在干什么**的最便宜
   手段。见 §五-C。

3. **在线 Agent 编排 —— 想法有价值，但是三者里风险与成本最高、且部分为时过早**，不建议
   现在就上"从零自研可视化画布"。理由和替代路径见 §五-B / §五-F：先把编排做成**声明式的
   Skill 组合**（后端已有 `dependencies.skills` 和空的 `orchestration` 字段两个抓手），
   再做**只读的组合可视化**，可视化编辑器要么放到最后、要么**嵌入现成自托管引擎**
   （Flowise/Langflow），而不是与成熟 OSS 正面造轮子。

---

## 二、当前定位与护城河（先说清不该动的东西）

从 PLAN/TASKS/评审看，Skillify 已经跑完 M0–M6，并在 C 阶段补了版本中心、收藏/订阅、
我的工作台、统一 build 预览/确认发布、结构化 SKILL.md 编辑设计。核心资产：

- **源/构件分离**：Forgejo = 唯一真相源，客户端从不可变构件（tarball+checksum+manifest）
  安装 —— 可复现、可回滚、可审计。这是"标准化格式"能落地的前提。
- **每 Skill 独立 uv venv + 内网 devpi** —— 离线/隔离场景优于平台化存储。
- **中立目录 + agent 适配层** —— 不被任一 Agent 绑死（claude/opencode/codex/project）。
- **身份与权限外包给公司 Keycloak + .NET RBAC** —— 比自建权限/审核更干净的架构分工。

评审文档已明确：**不追平 Skillhub**。Skillhub 的"完整"大多是面向外网公开注册中心的开销
（43 个 migration / 43 个 Playwright / 15 个 workflow / 自建 RBAC/审核/扫描），内网用户
没有对应价值。下面所有方向都以"不破坏上述护城河"为约束。

---

## 三、市场与竞品格局（2025–2026）

内网竞品（Skillhub）之外，外部生态在过去半年发生了几件对 Skillify 直接相关的事：

- **Agent Skills 成为开放标准**：Anthropic 的 SKILL.md 格式于 2025-10 发布，2025-12-18
  作为开放标准发布在 agentskills.io，已被 Codex、Copilot、Cursor、Gemini CLI 等读取。
  → **Skillify 押注 SKILL.md 是正确的，且这个格式的"跨 Agent 通用"属性在增强**。
- **MCP 官方注册中心**（`registry.modelcontextprotocol.io`，2025-09 预览）是一个
  **元注册中心**：只存指向 npm/PyPI/Docker 包的元数据。其 OpenAPI（v0.1，2025-10 冻结）
  **显式支持私有企业子注册中心** —— 这正是 Skillify 内网场景可以直接对齐的接口。
  2025-12 MCP 与注册中心捐给了 Linux Foundation 的 Agentic AI Foundation。
- **分发模型收敛到"插件市场"**：Claude Code 的 plugin marketplace = 一个带
  `.claude-plugin/marketplace.json` 的 Git 仓库，插件用 `plugin.json` 的 `version` +
  commit SHA 固定。→ **这是最接近 Skillify"私有 npm"目标的现成模型**，值得在内网复刻其
  "manifest + SHA 固定版本"的思路（Skillify 用 Forgejo Release + checksum 已经等价实现）。
- **市场层的差异化能力**（外部各家在卷、但没有绝对赢家，正是 Skillify 的机会位）：
  - **安全评级**：claudskills.com 用 A–F 对照"OWASP Agentic Skills Top 10"，skillstore.io
    扫描 `eval/exec/raw-shell` 模式，Anthropic 官方插件人工审核。
  - **一键安装 / 网关 / 可搜索目录** 已是入门标配（Glama、PulseMCP、mcp.so、Smithery、
    Docker MCP Catalog 的签名镜像+SBOM+来源证明）。
  - **引导式创作**：Anthropic 的 `skill-creator` 用"4 个意图问题 → 访谈 → 生成 → 评测与
    描述优化闭环"，是最值得直接借鉴的产物。
- **可视化编排**：自托管且 MCP 原生的首选是 **Flowise**（Apache-2.0）与 **Langflow**
  （MIT，基于 React Flow，还能把流程反向暴露成 MCP server）。n8n（source-available 许可）
  和 Dify（自定义许可，主打非技术）功能强但许可需注意。**AutoGen 已进入维护/退场，避开。**
- **可视化底座**：node 图用 **React Flow/@xyflow**（事实标准），文本→图用 **Mermaid**，
  SKILL.md→思维导图用 **markmap**，大依赖图用 **Cytoscape.js**。

**一句话**：外部生态在"标准（SKILL.md/MCP）已定、分发模型已定、市场层差异化未定"的阶段。
Skillify 的地基已经压在正确的标准上，接下来应抢占"市场层差异化"里对内网最有价值的位置。

---

## 四、两类用户的诉求错位（改进要分别打）

拓展社区失败最常见的原因，是用一套 UI 同时得罪两类人。要把诉求拆开：

| | 软件开发人员 | 非技术人员 |
| --- | --- | --- |
| 想要 | CLI、版本/diff、MCP 连接器、Skill 间组合、源码历史、可复现安装 | 一眼看懂"这 Skill 干嘛/什么时候用"、不写 YAML/Markdown、一键用起来 |
| 卡点 | 编排能力弱、只有 Skill 没有 MCP、Web 上传无 Git 历史 | 面对 frontmatter/manifest 就劝退、不知道装完怎么触发 |
| 对应方向 | A（MCP）、B（组合）、G（版本中心/Git 历史） | C（思维导图）、D（引导式创作）、"复制即用"的触发提示 |

结论：**A/B/G 打开发者，C/D 打非技术**，两条线并行但界面分层（专家模式 vs 引导模式），
Skillify 已有的"结构化 SKILL.md 编辑设计"（`docs/superpowers/specs/...structured-skill-md-editor`）
正是 D 的正确起点，方向无需调整，扩展即可。

---

## 五、改进方向详解

### A. MCP 连接器纳入平台（P1，服务开发者）

**问题**：Skillify 只托管 Skill（剧本），但开发者真正要接的内网工具（数据库、Jira、内部
API、Forgejo 本身）是 MCP server（动词）。现在这些散落各处、无统一发现与安装入口。

**建议**：把 MCP server 作为**第二类一等构件**纳入平台，与 Skill 并列：
1. 让 manifest 支持 `runtime: mcp-server`（现有 schema 已有 `runtime` 枚举，扩展一个值即可），
   或新增独立的 MCP 条目类型，元数据指向内网 npm/PyPI/OCI 包（对齐 MCP 元注册中心思路）。
2. **实现 MCP 官方注册中心 OpenAPI 的私有子注册中心接口**，让内网的 Claude Code/Cursor
   等客户端可以直接把 Skillify 当 MCP 发现源。这是标准对齐、且离线可行的关键一步。
3. Skill 详情页支持声明"本 Skill 依赖哪些 MCP server"，安装 Skill 时提示/联动装 MCP。

**为什么值得**：一旦开发者把内网 MCP 也从 Skillify 装，Skillify 就成了"内网唯一的 Agent
能力入口"，这是比再多几个社区功能都强的粘性。**成本中等**：主要是元数据模型扩展 + 一个
只读发现接口，不需要运行 MCP。

### B. Skill 组合 / 声明式编排（P1，服务开发者，差异化）

**现状**：`orchestration` 字段在 spec/后端/索引里都预留了但为空（`GET /orchestration` 只回
`{}`），`dependencies.skills` 已能递归安装。抓手都在，只差把"组合"变成产品概念。

**建议分三小步，前两步成本低、马上有差异化**：
1. **Skill Bundle / 合集**：允许把多个 Skill 组成一个命名合集（一键安装一组），并把
   `orchestration` 落成**声明式**结构（如"先用 A 产出，再交给 B"的顺序/条件，纯声明、
   由现有 Agent 执行，不自研运行时）。这是"编排"最便宜、最不容易翻车的形态。
2. **组合的只读可视化**（与 C 合流）：把 `dependencies.skills` + `orchestration` 用
   Mermaid/React Flow 画成一张"这个 Skill 会调用谁、按什么顺序"的图，供人看懂，不可编辑。
3. （可选，后置）真正的执行编排 —— 见 §F，建议嵌入现成引擎而非自研。

**为什么不一步到位做执行引擎**：内网价值在"让一组 Skill 能被组织和理解"，而不是再造一个
工作流引擎。声明式组合 + 可视化，90% 的用户价值、10% 的成本。

### C. 可视化：思维导图 / 依赖图（P1 快赢，两类用户都受益）

**这是你三个想法里性价比最高的一个，建议尽快做，成本低：**
- **SKILL.md → 思维导图**：用 `markmap`（纯前端）把 SKILL.md 的标题层级渲染成可折叠导图，
  非技术人员不用读 Markdown 就能看懂"这个 Skill 有哪些步骤/注意事项"。与已设计的结构化
  SKILL.md 章节（用途/输入/步骤/输出/注意/示例）天然对应。
- **Skill 依赖/组合图**：用 `Mermaid` 或 `React Flow` 画 `dependencies.skills`、MCP 依赖、
  版本关系，供开发者一眼看清一个 Skill 的"能力图谱"。
- **落点**：Skill 详情页新增一个"图谱/导图" tab，和现有 README/SKILL.md tab 并列。

**为什么快赢**：库都是 MIT、纯前端、无需后端改造，直接吃现有的 manifest 与 SKILL.md 数据。

### D. 引导式创作向导 + 描述优化闭环（P1，服务非技术）

**现状**：已有统一 build 预览/确认发布 API + 结构化 SKILL.md 编辑设计 —— 地基已具备。

**建议在此之上补两件事**：
1. **借鉴 `skill-creator` 的访谈式生成**：用"这个 Skill 让 Agent 会做什么 / 什么时候该触发
   / 输出什么 / 举 2 个例子"四个问题，收集后调用 Claude 生成合法 SKILL.md（无需微调，
   Claude 原生懂 SKILL.md），再走现有 preview→confirm→publish 链路。提供"对话式草拟"和
   "表单填写"两种模式（GPT Builder 模型）。
2. **描述（description）优化闭环**：外部经验里，非技术作者最容易写错的就是 `description`
   —— 它决定 Skill 会不会被触发。把它拆成"做什么 + 什么时候用（触发词）+ 关键词 + 反向
   触发（什么时候不要用）"几个引导字段，配实时字数计数（`name` ≤64、`description` ≤1024、
   第三人称、禁用 anthropic/claude 等），并可给"触发力度"提示（Claude 倾向欠触发，描述要
   适当"主动"）。

**为什么重要**：非技术人员上手失败 90% 卡在"装了不知道怎么触发/写的 Skill 从不被调用"，
这一步直接决定社区能不能从"开发者内部圈"扩到全员。

### E. 上传静态安全扫描 + 评级（P2，信任杠杆）

外部市场层最热的差异化就是安全评级。内网虽然不做外网攻击面，但"敢不敢装别人上传的 Skill"
是社区扩张的信任前提。**建议在上传/发布链路加静态扫描**（扫 `eval/exec/裸 shell/网络外联/
可疑权限声明`，对照 Skill 的 `permissions` 字段），给出 A–F 或红黄绿标签展示在详情页。
成本中等，且能复用已有的 manifest `permissions` 声明做交叉校验。**不做**沙箱运行时评审
（PLAN 已明确无沙箱评审），只做静态提示。

### F. 在线可视化 Agent 编排画布（P3 / 谨慎，你的想法之一）

**为什么降到 P3 而不是否决**：可视化编排确实是"高级感"和开发者留存的强项，但：
- **从零自研 = 与 Flowise/Langflow/n8n 正面造轮子**，这些是几万 star、多年打磨的成熟 OSS。
- Skillify 的 `orchestration` 目前**没有任何运行时**，先做画布等于先建摩天大楼再挖地基。
- 内网真实需求量存疑：先把 §B 的"声明式组合 + 只读可视化"上线，看用户是否真的要"可编辑
  执行画布"，用数据决定，而不是预先押注。

**若确实要做，建议路径**：不自研运行时，而是**嵌入/自托管一个现成引擎**（Flowise Apache-2.0
或 Langflow MIT，二者许可最适合内网，且 MCP 原生、基于 React Flow），把 Skillify 的 Skill/
MCP 作为节点导入。让 Skillify 专注"能力供给与治理"，把"编排执行"交给专业引擎，是更省力、
更不容易翻车的分工。

### G. 就绪度地基（P0 前置，社区拓展的前提）

评审文档（`review-test-production-readiness...`）已列出上线阻断项，这些**不做完，社区拓展
无从谈起**，务必先于 A–F 完成或并行：
- **完整部署包**：一套 Compose 拉起前端 + skillify-web + webhook + Forgejo + DM8/PG + devpi
  （当前 Dockerfile 只起 webhook）。
- **Alembic 基线 + DM8 迁移**：替换 `create_all`，让业务表升级有唯一入口。
- **发布可恢复**：发布步骤状态记录、同版本幂等重试、补传缺失 asset、`skill_index` 全量/按仓
  重建、失败释放 namespace。
- **Web 上传进 Git 历史**：修掉"Web 上传只生成 Release、不 commit 源码"这个与"Git=唯一真相
  源"立论自相矛盾的裂缝（`SKILLIFY_WEB_UPLOAD_GIT_ENABLED` 已有开关，需真实闭环验证）。
- **版本中心 / 我的 Skill 前端**：后端已具备（versions/diff/yank、my/*），前端要把它用起来。
- **修复 21 个 vue-tsc 类型错误 + 打包体积**，并做一次真实 Forgejo/DM8/devpi 端到端闭环。

---

## 六、优先级路线图（分阶段，供裁决）

- **阶段 0（前置·地基）**：G —— 部署包、Alembic/DM8、发布可恢复、Web 上传进 Git、版本中心/
  我的 Skill 前端接入、真实端到端闭环。**不完成不谈拓展。**
- **阶段 1（快赢·两类用户各拿一个）**：
  - C 可视化（SKILL.md 思维导图 + 依赖图）—— 最低成本，先上，立刻改善浏览与理解。
  - D 引导式创作向导 + 描述优化 —— 在已有结构化编辑设计上扩展，降非技术门槛。
- **阶段 2（差异化·护城河加深）**：
  - A MCP 连接器纳入 + 私有子注册中心接口 —— 把 Skillify 变成内网唯一 Agent 能力入口。
  - B Skill 组合（Bundle + 声明式 `orchestration` + 只读组合图）。
- **阶段 3（信任 + 高级感·按数据决定）**：
  - E 静态安全扫描 + 评级。
  - F 编排画布——**先验证需求，再决定"嵌入现成引擎"而非自研**。

---

## 七、明确不做 / 需警惕的事

- **不自研工作流执行引擎**去和 Flowise/Langflow/n8n 竞争；要做编排执行就嵌入现成自托管引擎。
- **不把 Skill 包进 MCP** 当连接器用（会破坏 progressive disclosure，是公认反模式）；
  二者并列托管、各司其职。
- **不抄 Skillhub 的企业治理厚度**（自建 RBAC/审核流/43 migration），身份权限继续外包给
  Keycloak + .NET RBAC。
- **不为对齐任何竞品牺牲** Forgejo 不可变构件 + 每 Skill venv 隔离这两条护城河。
- **不在数据量真正上来前**把内存子串搜索换成 DM8 全文/向量检索（现方案对内网几百个 Skill
  又快又够用）。

---

## 附：一句话给决策者

> 先用**阶段 0**把"能可靠部署、能可靠发布、源码可追溯"补齐（这是社区能长起来的土壤），
> 再用**思维导图 + 引导式创作**把非技术人员拉进来（拓宽用户面），最后用**MCP 纳入 +
> Skill 组合**把开发者牢牢粘住（加深护城河）。你提的三个想法里：思维导图立刻做、MCP 排在
> 差异化阶段做、可视化编排先做"声明式 + 只读图"、真要做执行画布就嵌现成引擎而非自研。
