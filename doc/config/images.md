# 内部镜像配置

在 DNSB**内部Dockerfile模板** 基础上，声明基础镜像或继承镜像，决定服务运行环境。支持两种方式：通过 `ref` 引用已有内部镜像，或完整给出基础三元组。

配置必须使用 **字典格式**（推荐），每个镜像作为顶层 `images` 的一个键值对。

与内部镜像对应的还有外部镜像，详情可阅读[外部镜像配置](external-images.md)

## mirror（可选）

- 作用：为内部镜像的模板注入国内或自定义的包管理器镜像源，加速构建
- 类型与格式：`object`
- 支持字段：
  - `apt_mirror`: 替换 `Ubuntu`/`Debian` 的 `sources.list` 域名，例如 `mirrors.ustc.edu.cn`
  - `pip_index_url`: 设置 `pip` 的默认 `index-url`，例如 `https://pypi.tuna.tsinghua.edu.cn/simple`
  - `npm_registry`: 设置 `npm` 的 `registry`，例如 `https://registry.npmmirror.com`

说明：

- 模板会在 `ENV` 后注入镜像配置，且在首次 `apt-get update`、`pip`、`npm install` 前生效
- 未提供的字段将跳过（不影响构建）

示例：

```yaml
images:
  bind-fast:
    software: bind
    version: "9.18.0"
    from: "ubuntu:20.04"
    mirror:
      apt_mirror: "mirrors.ustc.edu.cn"
      pip_index_url: "https://pypi.tuna.tsinghua.edu.cn/simple"

  judas-cn:
    software: judas
    version: "0.0.0"
    from: "debian:10"
    mirror:
      apt_mirror: "mirrors.tencent.com"
      npm_registry: "https://registry.npmmirror.com"
```

## name**

- 含义：镜像唯一名称（即在 `images` 中的字典键），用于服务引用与内部解析
- 类型与格式：`string`，不可包含冒号（`:`）
- 约束：全局唯一；重复或含冒号会在校验阶段报错

## ref

- 含义：引用已有镜像或镜像模板（如 `bind:9.18.0`）
- 类型与格式：`string`；支持 `software:version` 形式或本地镜像名（无冒号时）
- 可选值：
  - 内置软件类型：`bind`、`unbound`、`python`、`judas`（详见资源默认依赖 `resources/images/defaults`）
  - 同文件中的内部镜像名：引用同级定义的镜像（不含冒号）
- 约束：与 `software`、`version`、`from` 互斥；使用 `ref` 时不得提供这三者
- 解析说明：当使用本地镜像名时，将按继承链解析并合并父配置；当使用 `software:version` 时，按对应内部镜像类初始化。

## software

- 含义：软件类型（仅在不使用 `ref` 时）
- 类型与可选值：`string`，常见取值包括 `bind`、`unbound`、`python`、`judas`
- 约束：必须与 `version`、`from` 同时出现；否则校验失败

## version

- 含义：软件版本（仅在不使用 `ref` 时）
- 类型与格式：`string`，如 `9.18.0`、`1.18` 等
- 约束：必须与 `software`、`from` 同时出现

## from

- 含义：基础镜像名称（如 `ubuntu:20.04`）
- 类型与格式：`string`；支持 Docker Hub 镜像名
- 约束：必须与 `software`、`version` 同时出现；并作为内部镜像 Dockerfile 的 `FROM`

## dependency

- 含义：构建期依赖包列表，影响镜像构建阶段安装的依赖
- 类型与格式：`string[]`；如 `build-essential`、`libssl-dev` 等
- 默认值与参考：不同软件类型有各自默认依赖，参见 `resources/images/defaults`

## util

- 含义：运行期工具包列表，如 `dnsutils`、`tcpdump` 等
- 类型与格式：`string[]`；可包含 `python3-xxx` 以自动处理 Python 依赖
- 默认值与参考：不同软件类型有各自默认工具包，参见 `resources/images/defaults`

## 校验与约束总览

- 使用 `ref` 时，不允许出现 `software`、`version` 或 `from` 任一字段
- 不使用 `ref` 时，必须同时提供 `software`、`version` 与 `from`
- 镜像名不可包含冒号，且必须唯一

## 示例

```yaml
images:
  bind:
    ref: "bind:9.18.0"

  bind-fast:
    software: bind
    version: "9.18.0"
    from: "ubuntu:20.04"
    mirror:
      apt_mirror: "mirrors.ustc.edu.cn"

  judas-cn:
    software: judas
    version: "0.0.0"
    from: "debian:10"
    mirror:
      apt_mirror: "mirrors.tencent.com"
      npm_registry: "https://registry.npmmirror.com"
```

## 延伸阅读

- [顶层配置](top-level.md)
- [服务配置](builds.md)
- [合并与覆盖规则](../rule/merge-and-override.md)
