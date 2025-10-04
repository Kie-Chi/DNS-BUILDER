# 内置变量与占位符

本文档系统性介绍 DNSBuilder 中可用于替换的内置变量与占位符、解析规则与错误处理

## 适用范围

- 所有字符串字段都会参与变量替换，包括但不限于：`builds.*` 下的 `behavior`、`volumes`、`files` 内容、`container_name`、`command`、`environment` 等

## 变量来源与上下文

替换器为每个服务构建一份“变量上下文”，包含：

- 项目级：`project.*`（如 `project.name`、`project.inet`）
- 当前服务级：`name`、`ip`/`address` 及镜像相关属性 `image.*`（如 `software`、`version`、`name`）
- 跨服务级：`services.<service>.*`（可引用其他服务的 `ip` 与 `image.*` 等属性）
- 环境级：`env.<NAME>[:<default>]`（从进程环境读取；可选默认值）

注意：内置保留占位符（如 `${required}`、`${origin}`）不会被替换为具体值；它们参与校验与路径语义，详见下节

## 占位符

- 保留占位符（不会被替换器解析为具体值）：
  - `${required}`：标记该值为必填。如果最终仍保留该占位符，将在校验阶段报错
  - `${origin}`：表示不进行路径存在性/合法性检查，仅用于“来源路径”跳过校验（如 `${origin}./<service_name>/contents:/data`）；不要用于目标路径或非路径字段

## 变量

- 项目级变量：
  - `${project.name}`：项目名称
  - `${project.inet}`：项目子网字符串（如 `10.88.0.0/24`）
- 服务级变量：
  - `${name}`：当前服务名
  - `${ip}` 或 `${address}`：当前服务的 IP 地址（同义）
  - 其他 **服务可用属性** 也可类似引用
- 跨服务引用：
  - `${services.<service>.ip}`：引用指定服务的 IP 地址。若服务未构建或不存在，将报错
  - `${services.<service>.image.<prop>}`：引用指定服务所用镜像的属性；常用属性包括 `software`、`version`、`name`。若服务未配置 `image` 或属性不存在，将报错
  - 其他 **服务可用属性** 也可类似引用
- 环境变量：
  - `${env.<NAME>[:<default>]}`：读取进程环境变量；支持提供默认值（当未设置时生效）。无默认值且未设置时会报错。

## 解析规则与递归替换

- 替换器会为每个服务构建变量映射（包括当前服务与项目级变量）
- 字符串内使用正则匹配 `${...}` 形式的占位，并进行最多 10 次递归替换（用于支持嵌套变量）
- 未识别或解析失败的变量会替换为字符串 `none` 并记录警告日志；如提供了默认值（fallback），则使用默认值

### 示例

```yaml
builds:
  traffic:
    ref: monitor:traffic
    environment:
      - "ANAME=${env.ANAME:example.com}"
      - "RNAME=${env.RNAME:recursor}"
      - "RECURSOR=${services.${environment.RNAME}.ip}"
      - "SOFTWARE=${services.${environment.RNAME}.image.software}"
```

说明：

- 若未显式设置 `ANAME`/`RNAME`，将使用默认值；随后 `RECURSOR`/`SOFTWARE` 会基于前两者递归替换并解析。
- 替换器最多递归 10 层；过深或循环引用将记录警告。

### 别名与通用 fallback 语法

- 变量键支持别名规范化，常用别名包括：`address→ip`、`svc/srv/s→services`、`img→image`、`proj→project`、`reference→ref`、`caps/cap→cap_add`、`vols→volumes`、`stack→software`、`ver→version`。例如 `${svc.recursor.ip}` 等价于 `${services.recursor.ip}`。
- 除环境变量外，所有变量均支持通用默认值语法：`${<path>:<default>}`。当 `<path>` 无法解析时使用 `<default>`，否则返回 `none` 并记录警告。

## 错误与校验

- `${required}` 未被实际值替换：
  - 在服务校验阶段会检测该占位符是否仍存在；存在则抛出错误（如 `BuildDefinitionError` 或 `VolumeError`）
  - 该变量的值必须要被覆盖，覆盖详情参考相关配置章节
- 引用不存在的服务或属性：
  - `${services.<service>.ip}` 或 `${services.<service>.image.<prop>}` 在替换阶段解析失败时会返回 `none` 并记录警告；若后续行为/校验依赖该值，则会在对应阶段抛出错误
- 环境变量缺失且无默认值：在替换阶段返回 `none` 并记录警告；提供默认值时使用默认值
- 变量解析为复杂类型（dict/list）：抛出 `BuildError`，因为字符串替换仅接受标量

### 实践建议

- 为避免 YAML 类型歧义，请为可能包含冒号或空格的值加引号，例如 `container_name: "${project.name}-grafana"`。
- `${origin}` 仅用于标记“来源路径”并跳过存在性校验与复制；不要用于目标路径或非路径字段。
- `${required}` 适合放在卷源（`src`）或必须的文件路径上；校验器会在构建阶段拒绝未替换的占位符。
- 只在字符串字段中使用占位符；对于列表或字典，需将值以字符串形式表达后再替换。
- Windows 路径请使用正斜杠或进行适当转义，避免被 YAML 或 URI 解析误判。

## 示例

```yaml
builds:
  cadvisor:
    ref: monitor:cadvisor
    container_name: ${project.name}-cadvisor

  diy-auth:
    image: judas
    command: ["node", "judasdns.js"]
    volumes:
      - ${required}:/usr/src/judasdns/config.json  # include或者ref继承后必填，如未提供将报错

  bind-root:
    image: bind
    behavior: |
      . hint root
      . forward ${services.recursor.ip}  # 跨服务引用 IP
```

## 延伸阅读

- [服务配置](../config/builds.md)
- [标准服务模板](build-templates.md)
- [文件路径与FS](paths-and-fs.md)
- [行为DSL](behavior-dsl.md)
