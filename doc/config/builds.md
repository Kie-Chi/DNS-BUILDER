# 服务配置（BuildModel）

用于声明具体服务（容器）的构建与运行参数。支持在预处理阶段将列表结构展开为字典

结构上支持三种写法：顶层字典、单键字典列表、显式 `name` 的列表；**列表形式将于预处理阶段展开为字典**

## image

- 含义：引用某个镜像名，用于确定构建环境与 Dockerfile 生成逻辑
- 类型与格式：`string`
- 可选值
  - 已在 `images` 中定义的内部镜像名
  - 外部镜像名
- 约束：当 `ref` 以 `std:` 前缀使用时，必须提供 `image`
- 推荐阅读
  - [外部镜像配置](external-images.md)
  - [内部镜像配置](images.md)

## ref

- 含义：服务模板或引用规则。
- 类型与格式：`string`；支持以下形式：
  - `std:<role>`：标准模板，需结合 `image` 的软件类型解析为 `<software>:<role>`。详见[标准服务模板](../rule/build-templates.md)
  - `<software>:<role>`：显式指定软件与角色，例如 `bind:auth`、`unbound:recursor`
  - `<service_name>`：引用同级服务（无冒号）
- 约束：当使用 `std:` 前缀时必须提供 `image`；循环引用或未知引用会报错

## address

- 含义：容器的固定地址或占位，参与网络规划与变量替换
- 类型与格式：`string`
- 可选值
  - 合法 IPv4 地址
  - **无该属性表示由DNSB分配**
  - **空字符串** 表示不参与DNSB分配，留给Docker自动分配

## behavior

- 含义：服务行为脚本/DSL，由模板与行为类解析生成具体配置（如 BIND 的 zone 定义）
- 类型与格式：`string`，支持多行文本
- 延伸阅读：详见[Behavior DSL](../rule/behavior-dsl.md)

## mixins

- 含义：附加的模板片段或行为集合，用于在基础模板上叠加配置
- 类型与格式：`string[]`；当前支持 `std:<mixin_name>` 形式
- 约束：不支持自定义非 `std:` 前缀的 mixin

## build

- 含义：是否参与构建输出
- 类型与默认值：`boolean`，默认 `true`
- 影响：为 `false` 的服务将不会生成产物，也不会分配网络地址

## files

- 含义：额外文件写入映射，用于在容器构建时生成配置或脚本
- 类型与格式：`dict<string, string>`；键为容器目标路径，值为内容

## volumes

- 含义：卷挂载，用于映射资源、配置与数据目录
- 类型与格式：`string[]`；
- 磁盘绝对路径不会复制，否则目录或者文件将复制到 `service_name/contents`目录下再进行挂载
- 推荐阅读: [DNSB中的路径支持与文件系统](../rule/paths-and-fs.md)

## cap_add

- 含义：容器额外能力
- 类型与格式：`string[]`；默认支持值包括 `NET_ADMIN` 等

## 其它 Compose 字段

- 未在内置校验中检查，最终会透传到 `docker-compose.yml`
- 示例：`command: "tail -f /dev/null"`

## 校验与约束总览

- 至少需要 `image` 或 `ref` 之一；都缺失会报错
- `std:` 前缀的模板必须配合 `image` 使用
- 引用同级服务时会进行循环检测；形成环或引用不存在时报错

## 示例

```yaml
builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
    behavior: . hint root

  - root:
      image: "bind"
      ref: "std:auth"
      behavior: |
        . master com NS tld

  - name: "tld"
    image: "bind"
    ref: "std:auth"
    behavior: |
      com master example NS sld

  - name: "sld-{{ value }}"
    for_each:
      range: [1, 3]
    template:
      image: "bind"
      ref: "std:auth"
      behavior: |
        example.com master www A 1.2.3.{{ value }}
        example.com master mail A 1.2.3.{{ value + 1 }}
```

### 三种结构写法示例

1) 顶层字典（推荐）

```yaml
builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
  root:
    image: "bind"
    ref: "std:auth"

```

2) 单键字典列表

```yaml
builds:
  - recursor:
      image: "bind"
      ref: "std:recursor"
  - root:
      image: "bind"
      ref: "std:auth"
```

3) 显式 `name` 的列表

```yaml
builds:
  - name: recursor
    image: "bind"
    ref: "std:recursor"
  - name: root
    image: "bind"
    ref: "std:auth"
```

更多关于批量生成与模板展开的写法，详见[推导式语法](../rule/comprehension.md)

## 延伸阅读

- [顶层配置](top-level.md)
- [内部镜像配置](images.md)
- [外部镜像配置](external-images.md)
- [标准服务模板](../rule/build-templates.md)
- [行为 DSL](../rule/behavior-dsl.md)
- [文件路径与FS](../rule/paths-and-fs.md)
