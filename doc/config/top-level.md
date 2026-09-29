# 顶层配置

用于声明项目基础信息、网络以及镜像与服务的集合，允许存在未校验的额外字段

## name

- 必须项
- 含义：项目名称，用于生成输出目录、`Docker Compose`项目名称等
- 类型与格式：`string`，建议使用短横线/下划线，避免空格与特殊字符
- 可选值：任意字符串；与其他属性无直接耦合
- 示例：`name: demo`

## inet

- 必须项
- 含义：项目统一 IPv4 子网，决定生成的 Docker 网络段与服务地址规划
- 类型与格式：`IPv4Network`（形如 `10.88.0.0/24`）
- 可选值：合法 IPv4 网段；必须是 **可用于容器网络** 的私有地址段
- 影响范围：用于网络规划与 Compose 网络配置；写入 `networks` 区块
- 示例：`inet: 10.88.0.0/24`

## images*

- 可选项
- 含义：内部镜像定义集合，键为镜像名，值为镜像配置（详情见[内部镜像配置](images.md)）
- 类型与结构：**必须使用字典格式**
- 可选值：要求参见[内部镜像配置](images.md)
- 约束与校验：

  - 镜像名必须 **唯一** 且不可包含 `:`；重复或含冒号将抛出校验错误
  - 当值使用 `ref` 时，不得包含 `software`、`version` 或 `from`；若不使用 `ref`，必须同时提供三者
  - 允许 **内部镜像** 之间的 `ref` 引用；若形成循环依赖或引用不存在，将抛出错误
- 延伸阅读：

  - [内部镜像配置](images.md)

## builds

- 必须项
- 含义：服务构建配置集合，键为服务名，值为服务配置（见[服务配置](builds.md)）
- 类型与结构：**必须使用字典格式**
- 可选值：要求参见[服务配置](builds.md)
- 约束与校验：

  - 至少需要 `image` 或 `ref` 之一；都缺失会报错
  - 当 `ref` 以 `std:` 前缀使用时必须提供 `image`，否则报错
  - 允许同级服务之间的 `ref` 引用；若形成循环依赖或引用不存在，将抛出错误
- 延伸阅读：

  - [服务配置](builds.md)

## include*

- 可选项
- 含义：在预处理阶段合并其他配置文件，可递归处理
- 类型与格式：`string | string[]`；支持相对路径、绝对路径以及 `resource:/` 资源路径
- 行为说明：

  - 每个被包含文件会进行相同的预处理（包括 `images`/`builds` 展开、模板渲染）
  - 多个包含的结果与当前配置将通过深度合并策略合并，当前配置的键优先生效
- 示例：

  ```yaml
  include:
    - resource:/includes/sld.yml
    - ./local-extra.yml
  ```

## auto*
### setup*
### modify*
### restrict*

利用脚本自动化初始化或者修改配置，详见 [Auto 自动化脚本](auto.md)

## mirror*

- 可选项
- 含义：全局镜像源配置，为所有内部镜像提供默认的包管理器镜像源，加速构建
- 类型与格式：`object`
- 支持字段：
  - `apt_mirror`（别名：`apt`、`apt_host`）: 替换 `Ubuntu`/`Debian` 的 `sources.list` 域名，例如 `mirrors.ustc.edu.cn`
  - `pip_index_url`（别名：`pip_index`、`pip`）: 设置 `pip` 的默认 `index-url`，例如 `https://pypi.tuna.tsinghua.edu.cn/simple`
  - `npm_registry`（别名：`npm`、`registry`）: 设置 `npm` 的 `registry`，例如 `https://registry.npmmirror.com`
  - 特殊值 `"auto"`：使用 [chsrc](https://github.com/RubyMetric/chsrc) 自动选择最快的镜像源
- 优先级：全局 mirror 配置优先级最低，会被 `images` 配置中的 `mirror` 覆盖
- 示例：

  ```yaml
  name: demo
  inet: 10.88.0.0/24
  mirror:
    apt: "mirrors.ustc.edu.cn"
    pip: "https://pypi.tuna.tsinghua.edu.cn/simple"
  images:
    bind:
      ref: "bind:9.18.0"
      # 继承全局 mirror 配置
    custom:
      software: bind
      version: "9.18.0"
      from: "ubuntu:20.04"
      mirror:
        apt: "mirrors.tencent.com"  # 覆盖全局配置
  ```

## DNSSEC 工具模式（util_mode / util_image / util_auto_install）

启用 DNSSEC 的构建会预检 `dnssec-signzone`，必要时按需调用 `dnssec-keygen` 等工具。

- `util_mode`：`host`（默认）或 `docker`。`host` 依次查找 `BIND_DNSSEC_KEYGEN`、`BIND_DNSSEC_SIGNZONE`、`BIND_DNSSEC_DSFROMKEY`、`BIND_DNSSEC_CHECKZONE`、PATH 和常见路径；`docker` 默认使用仓库内置的 DNSSEC 工具 Dockerfile 构建临时工具镜像。
- `util_image`：可选，覆盖 `docker` 模式的默认工具镜像，例如 `bind:9.18.4`。设置后 DNSBuilder 只检查该镜像是否已在本地，不会替用户拉取或构建它。
- 默认工具镜像名为 `dnsbuilder/dnssec-tools:9.18.4`，Dockerfile 位于 `src/dnsbuilder/resources/images/dnssec_tools/Dockerfile`，基于明确的 `docker.1ms.run/library/debian:12.11-slim` 安装 `bind9-utils`。默认镜像缺失时，DNSBuilder 会用该本地 Dockerfile 构建；Docker 只会按 Dockerfile 中声明的基础镜像地址使用本地缓存或获取基础镜像。
- `util_auto_install`：默认 `false`；设置为 `true` 才允许按操作系统尝试安装 BIND 工具包。环境变量 `DNSSEC_AUTO_INSTALL=1` 也可显式开启。

工具只用于构建期签名，不会成为 PowerDNS、BIND 或 Unbound 运行时的必要依赖。

## 额外字段*

- 可选项
- 顶层允许存在未列出的附加字段；这些字段不会参与校验，但会 **透传到最终 Compose 输出**
- 注意：为避免与保留键冲突，顶层保留键包括：`name`、`inet`、`images`、`builds`、`include`、`plugins`、`auto`、`mirror`、`vars`、`util_mode`、`util_image`、`util_auto_install`

## 示例

```yaml
name: demo
inet: 10.88.0.0/24
images:
  bind:
    ref: "bind:9.18.0"
builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
    behavior: . hint root
  root:
    image: "bind"
    ref: "std:auth"
    behavior: |
      . master com NS tld
include:
  - resource:/includes/sld.yml
```

## 延伸阅读

- [配置处理流程](processing-pipeline.md)
- [Auto 自动化脚本](auto.md)
- [内部镜像配置](images.md)
- [外部镜像配置](external-images.md)
- [服务配置](builds.md)
- [文件路径与FS](../rule/paths-and-fs.md)
- [合并与覆盖规则](../rule/merge-and-override.md)
