# 标准服务模板

标准服务模板用于快速声明常见角色的服务配置，通过 `ref: "std:<role>"` 与服务的 `image` 软件类型组合进行解析。

## 解析规则

- 当 `ref` 写作 `std:<role>` 时，解析器会读取服务的 `image`，获取其软件类型（如 `bind`、`unbound`），并将 `std:<role>` 解释为 `<software>:<role>`。
- 若未设置 `image` 或无法识别软件类型，将报错。
- 也可直接写 `<software>:<role>`（如 `bind:auth`、`unbound:recursor`），跳过 `std:` 组合解析。

## 可用模板

内置模板位于资源路径 `resource:/builder/templates`，当前包含：

- `bind`

  - `recursor`：递归解析器，挂载 `bind_recursor_base.conf` 等。
  - `auth`：权威服务器，挂载 `bind_auth_base.conf`。
  - `forwarder`：转发器，挂载 `bind_forwarder_base.conf`。
- `unbound`

  - `recursor`：递归解析器，挂载 `unbound_recursor_base.conf`。
  - `forwarder`：转发器，挂载 `unbound_forwarder_base.conf`。

## 使用示例

```yaml
builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
  root:
    image: "bind"
    ref: "bind:auth"  # 显式写法
```

## 变量占位与挂载

模板中可能包含占位符（如 `${project.inet}`、`${origin}`、`${required}`），在构建流程中会由变量替换器解析。详见[行为 DSL](behavior-dsl.md)与[内置变量](builtins-and-placeholders.md)章节

## 延伸阅读
- [行为 DSL](behavior-dsl.md)
- [内置变量](builtins-and-placeholders.md)
