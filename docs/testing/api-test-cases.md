# 后端 API 用例摘要

真实环境自动化共 26 项，全部通过：认证 4、guided 9、native 4、external 6、搜索 1、其他 2。关键状态码符合契约：无/坏 token 401，跨用户对象 404，危险路径 400，旧 revision/重复发布/重复版本 409，未确认及无候选 422，重复 candidate selection 400。

标准 zip、guided、external 最终均调用 `/api/skill-builds/{id}/publish`。发布后通过 Forgejo API 枚举仓库、tag、Release 和资产，并下载 tarball/sha256 重算校验；5 个 Release 全部匹配。通过 DIsql 核验索引与发布任务。

未通过客户端执行 `skillctl install`。

