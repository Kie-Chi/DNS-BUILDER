# 内部镜像配置

在 DNSB**内部Dockerfile模板** 基础上，声明基础镜像或继承镜像，决定服务运行环境。支持两种方式：通过 `ref` 引用已有内部镜像，或完整给出基础三元组

结构上支持三种写法：顶层字典、单键字典列表、显式 `name` 的列表；**列表形式将于预处理阶段展开为字典**

与内部镜像对应的还有外部镜像，详情可阅读[外部镜像配置](external-images.md)

## name

- 含义：镜像唯一名称，用于服务引用与内部解析
- 类型与格式：`string`，不可包含冒号（`:`）。由上层 `images` 字典键提供，值对象通常不包含 `name` 字段
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

  bind-from-source:
    from: "ubuntu:20.04"
    software: "bind"
    version: "9.18.0"
    dependency:
      - build-essential
      - libssl-dev
    util:
      - dnsutils
      - tcpdump
```

### 三种结构写法示例

1) 顶层字典（推荐）

```yaml
images:
  bind:
    ref: "bind:9.18.0"
  unbound:
    software: "unbound"
    version: "1.19.0"
    from: "debian:12"
```

2) 单键字典列表

```yaml
images:
  - bind:
      ref: "bind:9.18.0"
  - unbound:
      software: "unbound"
      version: "1.19.0"
      from: "debian:12"
```

3) 显式 `name` 的列表

```yaml
images:
  - name: bind
    ref: "bind:9.18.0"
  - name: unbound
    software: "unbound"
    version: "1.19.0"
    from: "debian:12"
```

更多关于批量生成的写法与模板展开，详见[推导式语法](rule/comprehension.md)

## 延伸阅读

- [顶层配置](top-level.md)
- [服务配置](builds.md)
- [推导式语法](rule/comprehension.md)
- [合并与覆盖规则](rule/merge-and-override.md)
