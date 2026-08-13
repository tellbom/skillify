# 麒麟端侧 Agent Suite DEB

`skillify-agent-suite` 把已经在银河麒麟 V10 SP1 `amd64` 端侧验证通过的以下程序封装为单个安装包：

- CC Switch 3.19.2（含麒麟兼容运行时）
- Claude Code 2.1.179
- OpenCode 1.17.18
- Skillify `skillctl`、Python 3.11、Node 24 与 Agent Host

包内不包含模型 Key、Forgejo Token、Keycloak Token、端点注册信息、工作区配置或任何用户目录下的现有配置。

## 构建

在已经安装并验证以上程序的麒麟端侧，从 Skillify 仓库根目录执行：

```sh
chmod +x scripts/packaging/build-kylin-agent-suite-deb.sh
scripts/packaging/build-kylin-agent-suite-deb.sh
```

输出：

```text
dist/skillify-agent-suite_0.1.0_amd64.deb
dist/skillify-agent-suite_0.1.0_amd64.deb.sha256
```

## 安装与使用

用户双击 `.deb`，由麒麟软件安装器完成安装。系统软件包安装需要管理员认证；这是唯一需要提权的阶段。安装后四个程序都以当前普通用户运行。

首次使用先从应用菜单打开 **CC Switch 模型配置**，完成 Claude Code 的模型配置。终端中可直接运行：

```sh
cc-switch
claude
opencode
skillctl --help
```

Skillify 端点仍由普通用户执行 `skillctl agent init` 生成 `~/.skillctl/settings.json`，再执行 `skillctl agent bridge start`。模型地址和 Key 继续由 CC Switch、Claude Code 或 OpenCode 自身管理，Skillify 安装包不接管这些配置。
