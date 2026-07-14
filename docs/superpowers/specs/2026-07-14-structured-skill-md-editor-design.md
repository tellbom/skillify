# 结构化 SKILL.md 编辑与作者预填设计

## 目标

让非技术用户无需编写 YAML 或 Markdown 即可完成引导式技能创建，同时保证标准 Skillify zip 与外部 Agent Skill 导入后的已有内容能够正常显示、编辑和再次保存。三种入口均继续使用现有 Build API，不增加后端契约。

## 已选方案

采用前端结构化解析与合成：从后端 `BuildPreview` 读取 `manifest` 和完整 `skillMd`，将常用 Markdown 章节拆分为表单字段；保存时重新生成合法的 YAML frontmatter 与 Markdown 正文。无法识别的自定义章节放入“其他补充内容”，原样保留。

未采用的方案：

- 新增后端结构化 SKILL.md schema：数据模型更统一，但会扩大 API、存储和兼容改造范围。
- 保留原始编辑器并增加表单/源码切换：实现较快，但非技术用户仍可能被 YAML 暴露，且两种编辑状态容易产生覆盖冲突。

## 作者字段

- `UploadView` 使用 `const auth = useAuthStore()` 获取当前用户。
- 引导式创建调用 `createGuidedBuild` 时，将 `auth.rbacInfo?.username` 写入初始 manifest 的 `author`。
- `BuildWorkspace` 加载任意来源 build 后，如果 manifest 作者为空，则使用同一用户名补齐本地草稿。
- 标准 zip 或外部 Agent Skill 已有非空作者时必须保留，不能被当前登录用户覆盖。
- `rbacInfo` 尚未加载或没有 username 时保持空值，由现有缺失字段校验提示用户。

## 结构化 SKILL.md 表单

新增独立组件 `SkillMdForm.vue`，字段为：

1. 技能标题
2. 技能用途与适用场景
3. 输入要求
4. 操作步骤
5. 输出要求
6. 注意事项
7. 使用示例
8. 其他补充内容

`name` 与 `description` 不再要求用户在 SKILL.md 中重复编写 YAML；它们直接取自第二步的 manifest 基础信息，并在保存时自动生成 SKILL.md frontmatter。

## 解析与合成

在 `web/src/lib/skillBuilds.js` 增加纯函数：

- `parseSkillMd(skillMd, manifest)`：移除 frontmatter，将一级标题、已知二级标题和正文映射到结构化字段。
- `composeSkillMd(fields, manifest)`：根据 manifest 的 `name/description` 生成 YAML frontmatter，再按固定顺序生成非空 Markdown 章节。

YAML 字符串使用双引号安全序列化，避免冒号、引号或换行破坏 frontmatter。

解析时识别中英文常见标题别名，例如 `Steps`/`Instructions`/`操作步骤`、`Notes`/`注意事项`、`Example`/`使用示例`。未知标题及其正文不改写，整体进入“其他补充内容”。没有标题的首段正文进入“技能用途与适用场景”。

## 三种来源的数据流

- 引导式创建：初始 author 已预填；空 SKILL.md 展示空结构化表单；用户输入后合成完整 SKILL.md。
- 标准 Skillify zip：仍从上传 API 创建 build；工作区默认进入预览步骤，返回第三步时解析已有 SKILL.md，已有作者不被覆盖。
- 外部 Agent Skill：转换后的 build 仍按原流程加载；检测到的正文解析到结构化字段，未知章节保留，缺失作者使用当前 RBAC 用户预填。

工作区每次从服务端重新加载或处理 409 冲突时，都以服务端最新 `skillMd` 重新解析，避免保留过期的本地结构化状态。

## 保存、预览与错误处理

- 第三步点击“下一步”时，先合成 `skillMdDraft`，再沿用现有 PATCH 请求同时保存 manifest 与 SKILL.md。
- manifest 的 name/description 在第二步改变后，第三步生成的 frontmatter同步更新。
- 第六步继续使用后端返回的 `build.manifestYaml` 和 `build.skillMd`，确保预览展示的是服务端校验后的最终内容。
- 解析失败不能阻止编辑：完整正文进入“其他补充内容”，用户内容不会丢失。
- 保留现有 revision、409 刷新、404 过期和 422 发布校验处理。

## 测试与验收

- 纯函数测试：空内容、标准示例、中英文标题、未知章节、特殊字符 YAML 序列化、解析后重新合成不丢失内容。
- 作者测试：空作者预填；已有字符串作者不覆盖；已有对象作者正常显示；无 RBAC 信息时保持为空。
- 组件测试：三种 `sourceType` 均能显示结构化编辑器并正确回填；保存请求仍发送完整 `skillMd` 字符串。
- 运行 `npm test`、`npm run type-check` 和 `npm run build`。

## 范围边界

- 不修改后端 Build API、validator 或 SKILL.md 文件规范。
- 不提供原始 YAML/Markdown 编辑模式。
- 不尝试理解任意 Markdown 的业务语义；只识别明确标题，其余内容无损保留。
