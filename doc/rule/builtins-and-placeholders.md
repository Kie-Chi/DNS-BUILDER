# 内置变量与占位符

本文档系统性介绍 DNSBuilder 中可用于替换的内置变量与占位符、解析规则与错误处理

## 适用范围

- 所有字符串字段都会参与变量替换，包括但不限于：`builds.*` 下的 `behavior`、`volumes`、`files` 内容、`container_name`、`command`、`environment` 等。

## 可用占位符与变量

- 保留占位符（不会被替换器解析为具体值）：

  - `${required}`：标记该值为必填。如果最终仍保留该占位符，将在校验阶段报错。
  - `${origin}`：表示不进行路径存在性、合法性检查，主要用于卷挂载路径（如 `${origin}./<service>/contents:/data`）。
- 项目级变量：

  - `${project.name}`：项目名称。
  - `${project.inet}`：项目子网字符串（如 `10.88.0.0/24`）。
- 服务级变量：

  - `${name}`：当前服务名。
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
- 字符串内使用正则匹配 `${...}` 形式的占位，并进行最多 5 次递归替换（用于支持嵌套变量）
- 未识别的变量会被保留为原样并记录警告日志

## 错误与校验

- `${required}` 未被实际值替换：
  - 在服务校验阶段会检测该占位符是否仍存在；存在则抛出错误（如 `BuildDefinitionError` 或 `VolumeError`）
  - 该变量的值必须要被覆盖，覆盖详情参考[]
- 引用不存在的服务或属性：
  - `${services.<service>.ip}` 或 `${services.<service>.image.<prop>}` 解析失败时会抛出 `ReferenceNotFoundError`
- 环境变量缺失且无默认值：抛出 `BuildError`
- 变量解析为复杂类型（dict/list）：抛出 `BuildError`，因为字符串替换仅接受标量

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

- [服务配置](config/builds.md)
- [标准服务模板](build-templates.md)
- [文件路径与FS](paths-and-fs.md)
- [行为DSL](behavior-dsl.md)
