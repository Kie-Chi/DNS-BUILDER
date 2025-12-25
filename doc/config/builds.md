# 服务配置

用于声明具体服务（容器）的构建与运行参数。配置必须使用 **字典格式**（推荐），每个服务作为顶层 `builds` 的一个键值对
如需动态生成多个相似的服务，请使用 [Auto 自动化脚本](auto.md) 中的 `setup` 阶段

## name**

- 含义：服务唯一名称（即在 `builds` 中的字典键），用于服务引用与内部解析
- 类型与格式：`string`，不可包含冒号（`:`）
- 约束：全局唯一；重复或含冒号会在校验阶段报错

## image

- 必须项（但是可以不显式定义，而从ref中继承）
- 含义：引用某个镜像名，用于确定构建环境与 Dockerfile 生成逻辑
- 类型与格式：`string`
- 可选值

  - 已在 `images` 中定义的内部镜像名
  - 外部镜像名
- 约束：当 `ref` 以 `std:` 前缀使用时，必须提供 `image`
- 推荐阅读

  - [外部镜像配置](external-images.md)
  - [内部镜像配置](images.md)

## ref*

- 可选项
- 含义：服务模板或引用规则。
- 类型与格式：`string`；支持以下形式：

  - `std:<role>`：标准模板，需结合 `image` 的软件类型解析为 `<software>:<role>`。详见[标准服务模板](../rule/build-templates.md)
  - `<software>:<role>`：显式指定软件与角色，例如 `bind:auth`、`unbound:recursor`
  - `<service_name>`：引用同级服务（无冒号）
- 约束：当使用 `std:` 前缀时必须提供 `image`；循环引用或未知引用会报错

## address*

- 可选项
- 含义：容器的固定地址或占位，参与网络规划与变量替换
- 类型与格式：`string`
- 可选值

  - 合法 IPv4 地址
  - **无该属性表示由DNSB分配**
  - **空字符串** 表示不参与DNSB分配，留给Docker自动分配

## behavior*

- 可选项
- 含义：服务行为脚本/DSL，由模板与行为类解析生成具体配置（如 BIND 的 zone 定义）
- 类型与格式：`string`，支持多行文本
- 延伸阅读：详见[Behavior DSL](../rule/behavior-dsl.md)

## mixins*

- 可选项(不推荐使用，行为类似于多继承)
- 含义：附加的模板片段或行为集合，用于在基础模板上叠加配置
- 类型与格式：`string[]`；当前支持 `std:<mixin_name>` 形式
- 约束：不支持自定义非 `std:` 前缀的 mixin

## build*

- 可选项
- 含义：是否参与构建输出
- 类型与默认值：`boolean`，默认 `true`
- 影响：为 `false` 的服务将不会生成产物，也不会分配网络地址

## files*

- 可选项
- 含义：额外文件写入映射，用于在容器构建时生成配置或脚本
- 类型与格式：`dict<string, string>`；键为容器目标路径，值为内容

## volumes*

- 可选项
- 含义：卷挂载，用于映射资源、配置与数据目录
- 类型与格式：`string[]`；
- 磁盘绝对路径不会复制，否则目录或者文件将复制到 `service_name/contents`目录下再进行挂载
- 推荐阅读: [DNSB中的路径支持与文件系统](../rule/paths-and-fs.md)

## cap_add*

- 可选项
- 含义：容器额外能力
- 类型与格式：`string[]`；默认支持值包括 `NET_ADMIN` 等

## mirror*

- 可选项
- 含义：服务级别的镜像源配置，仅对使用内部镜像的服务生效
- 类型与格式：`object`
- 支持字段：同顶层 `mirror` 配置（`apt_mirror`、`pip_index_url`、`npm_registry` 及其别名）
- 优先级：服务级 mirror > 镜像级 mirror > 全局 mirror
- 说明：此配置会与其余 mirror 配置深度合并，用于为特定服务定制镜像源
- 延伸阅读
  - [顶层配置 - mirror](top-level.md#mirror)
  - [内部镜像配置 - mirror](images.md#mirror可选)

## auto*
### setup*
### modify*
### restrict*

利用脚本自动化初始化或者修改配置，详见 [Auto 自动化脚本](auto.md)

## 其它 Compose 字段*

- 可选项
- 未在内置校验中检查，最终会透传到 `docker-compose.yml`
- 示例：`command: "tail -f /dev/null"`

## 校验与约束总览

- 至少需要 `image` 或 `ref` 或 `auto.setup` (ref的对象中需要包含 `image`)之一；都缺失会报错
- `std:` 前缀的模板必须配合 `image` 使用
- 引用同级服务时会进行循环检测；形成环或引用不存在时报错

## 示例

```yaml
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

  tld:
    image: "bind"
    ref: "std:auth"
    behavior: |
      com master example NS sld
```

### 动态生成多个服务

如需批量生成多个相似的服务（如生成 `sld-1`, `sld-2`, `sld-3`），使用 `auto.setup` 阶段：

```yaml
auto:
  setup: |
    for i in range(1, 4):
      name = f"sld-{i}"
      config.setdefault('builds', {})[name] = {
        'image': 'bind',
        'ref': 'std:auth',
        'behavior': f'example.com master www A 1.2.3.{i}'
      }

builds: {}
```

详见 [Auto 自动化脚本](auto.md)

## 延伸阅读
- [配置处理流程](processing-pipeline.md)
- [顶层配置](top-level.md)
- [内部镜像配置](images.md)
- [外部镜像配置](external-images.md)
- [Auto 自动化脚本](auto.md)
- [标准服务模板](../rule/build-templates.md)
- [行为 DSL](../rule/behavior-dsl.md)
- [文件路径与FS](../rule/paths-and-fs.md)
