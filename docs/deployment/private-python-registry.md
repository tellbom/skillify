# 私有 Python 包源验证

devpi 使用 `infra/devpi/Dockerfile` 部署，内部 index 为 `skillify/dev`（无公网 base）。已上传 `skillify-probe==1.0.0` 的 wheel 和 sdist。

验证命令形态：

```sh
pip install --trusted-host devpi \
  --index-url http://devpi:3141/skillify/dev/+simple/ \
  skillify-probe==1.0.0
```

安装后导入输出 `private-registry-ok`。`==9.9.9` 返回无匹配版本并退出 1；指向不可达的本地端口、禁用重试后退出 1。全栈重启后再次安装成功，证明 volume 持久化有效。

构建时发现 devpi 6.13 不支持 `devpi-server --init`，已改为该版本提供的 `devpi-init --serverdir=/data`。

