# 顶层配置

用于声明项目基础信息、网络以及镜像与服务的集合，允许存在未校验的额外字段


## name

- 含义：项目名称，用于生成输出目录、`Docker Compose`项目名称等
- 类型与格式：`string`，建议使用短横线/下划线，避免空格与特殊字符
- 可选值：任意字符串；与其他属性无直接耦合
- 示例：`name: demo`

## inet

- 含义：项目统一 IPv4 子网，决定生成的 Docker 网络段与服务地址规划
- 类型与格式：`IPv4Network`（形如 `10.88.0.0/24`）
- 可选值：合法 IPv4 网段；必须是 **可用于容器网络** 的私有地址段
- 影响范围：用于网络规划与 Compose 网络配置；写入 `networks` 区块
- 示例：`inet: 10.88.0.0/24`

## images

- 含义：内部镜像定义集合，键为镜像名，值为镜像配置（详情见[内部镜像配置](images.md)）
- 类型与结构：以字典为主；列表形式在预处理阶段展开为字典（支持单键字典与显式 `name`）。
- 可选值：要求参见[内部镜像配置](images.md)
- 约束与校验：
  - 镜像名必须 **唯一** 且不可包含 `:`；重复或含冒号将抛出校验错误
  - 当值使用 `ref` 时，不得包含 `software`、`version` 或 `from`；若不使用 `ref`，必须同时提供三者
  - 允许 **内部镜像** 之间的 `ref` 引用；若形成循环依赖或引用不存在，将抛出错误
- 延伸阅读：
  - 结构与格式（三种写法与示例）：[内部镜像配置](images.md)
  - 推导式语法（批量生成 `images`）：[推导式语法](../rule/comprehension.md)

## builds

- 含义：服务构建配置集合，键为服务名，值为服务配置（见[服务配置](builds.md)）
- 类型与结构：以字典为主；列表形式在预处理阶段展开为字典（支持单键字典与显式 `name`）。
- 可选值：要求参见[服务配置](builds.md)
- 约束与校验：
  - 至少需要 `image` 或 `ref` 之一；都缺失会报错
  - 当 `ref` 以 `std:` 前缀使用时必须提供 `image`，否则报错
  - 允许同级服务之间的 `ref` 引用；若形成循环依赖或引用不存在，将抛出错误
- 延伸阅读：
  - 结构与格式（三种写法与示例）：[服务配置](builds.md)
  - 推导式语法（批量生成 `builds`）：[推导式语法](../rule/comprehension.md)

## include

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

## 额外字段

- 顶层允许存在未列出的附加字段；这些字段不会参与校验，但会 **透传到最终 Compose 输出**
- 注意：为避免与保留键冲突，顶层保留键包括：`name`、`inet`、`images`、`builds`、`include`

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

- [内部镜像配置](images.md)
- [服务配置](builds.md)
- [文件路径与FS](../rule/paths-and-fs.md)
- [合并与覆盖规则](../rule/merge-and-override.md)
