# Behavior DSL

`behavior` 字段用于以简洁的“行为脚本”描述 DNS 服务如何工作（如转发、根提示、权威区与记录）。系统会根据服务的 DNS 软件类型（`bind` 或 `unbound`）将 DSL 解析并生成对应的配置片段与产物

## 适用位置与解析时机

- 位置：`builds.<service>.behavior`，类型为 `string`，支持多行，每行一条行为
- 解析时机：变量替换完成后进行解析与产物生成。建议在行为中直接使用“服务名”作为目标，避免在行为里嵌入复杂占位符。

## 语法总览

- 通用格式（除 `master` 外）：`<zone> <type> <target1>,<target2>,...`
  - `<zone>`：字符串，如 `"."`（根）、`"com"`、`"example.com"`
  - `<type>`：行为类型（见下表
  - `<target...>`：目标列表，逗号分隔；可为**服务名**或 IP
- `master` 专用格式：`<zone> master <rname> <rtype> [<ttl>] <target1>,<target2>,...`
  - `<zone>`：该行为归属的“区文件键”，用于生成 `db.<zone>` 文件；根区为 `"."`
  - `<rname>`：记录名，可为 `@`（表示当前 zone）、`www`、`ns1` 等、FQDN（以 `.` 结尾）
  - `<rtype>`：记录类型，支持 `A`、`AAAA`、`NS`、`CNAME`、`TXT` 等
  - `[<ttl>]`：可选整型，默认 `3600`
  - `<targets>`：目标列表；`A/AAAA` 目标为 IP（或可解析为 IP 的服务名），`NS/CNAME/TXT` 目标为域名字符串（可含**服务名**以自动生成 Glue）

## 支持的行为类型

- `bind` 与 `unbound` 均支持：
  - `forward`：将某个 `zone` 的查询转发到指定的上游（目标为服务名或 IP）
  - `hint`：为根配置“提示文件”；目标仅支持一个（一般为根服务器服务名）。会自动生成并挂载 hints 文件
  - `stub`：为某个 `zone` 配置 `stub`（上游主服务器列表）
- `master`：聚合并生成权威区文件（`db.<zone>` 或 `db.root`），并写入相应配置（`type master` 或 `auth-zone`）。

## 域名与 FQDN 约定
- 名称归一化规则（应用于 `master` 行为中的 `<rname>`，以及 `NS/CNAME/TXT` 等目标域名）：
  - `@` 表示当前 Zone 的根（apex），例如 `<zone>=com` 时 `@` 展开为 `com`；根区 `"."` 时为 `"."`
  - 以 `.` 结尾的名称视为全称域名（FQDN），保持原样，不再拼接 Zone，例如 `www.`
  - 不以 `.` 结尾的名称视为相对名，将拼接当前 `<zone>`：
    - `<zone>=com`，`www` -> `www.com`
    - `<zone>="."`（根区），`example` -> `example.`
- `NS` 记录的目标若为内部服务名（而非域名字符串），会自动解析为该服务 IP 并生成 Glue 记录；目标为外部域名时，按上述归一化规则处理

## 目标解析与校验

- 目标可写“服务名”或“IP”。服务名会在构建上下文中解析为该服务的 IP；解析失败会报错
- `hint` 仅允许一个目标；多于一个将抛出错误
- `NS` 记录当目标为“内部服务名”时，会自动生成 Glue 记录（为该目标生成一个 `A` 记录并随机化 `ns` 名称前缀以避免冲突）
- 不支持的记录类型或语法错误会抛出“功能不支持/格式无效”错误

## 与占位符的关系

- Behavior DSL 自身不引入占位符语法；但 `behavior` 的字符串也会参与全局变量替换（详见[内置变量与占位符](builtins-and-placeholders.md)）
- 推荐做法：在行为中直接写服务名或明确的 IP；避免在行为内使用 `${services.<name>.ip}` 等占位符以降低耦合

## 示例

```yaml
builds:
  recursor:
    image: bind
    ref: std:recursor
    behavior: |
      . hint root              # BIND/Unbound：根提示，目标为服务名“root”

  root:
    image: bind
    ref: std:auth
    behavior: |
      . master @ NS tld        # 在根区写 NS 记录，目标为服务名“tld”（自动生成 Glue）
      com master www A 1.2.3.4 # 在 com 区写 A 记录
      com master mail A 1.2.3.5

  forwarder:
    image: unbound
    ref: std:forwarder
    behavior: |
      example.com forward recursor,8.8.8.8
      . stub tld               # 对根区配置 stub，目标为内部服务“tld”
```

## 生成产物

- 配置片段：按软件类型分别写入 `named.conf` 或 `unbound.conf` 的相应部分（`forward-zone`/`stub-zone`/`auth-zone`/`type forward|stub|hint|master`）。
- Zone 文件：`master` 行为会汇总所有记录并生成 `db.<zone>`（根区为 `db.root`），同时创建卷挂载与配置条目。
- 根提示：`hint` 行为会生成 `gen_<service>_root.hints` 文件并挂载到容器中相应路径。

## 错误与约束

- 引用了不存在的服务名或无效 IP：抛出 `BehaviorError`。
- 记录类型不支持或语法不合法：抛出 `UnsupportedFeatureError`。
- `hint` 目标数量不为 1：抛出 `BehaviorError`。

## 延伸阅读

- [服务配置](config/builds.md)
- [标准服务模板](build-templates.md)
- [内置变量与占位符](builtins-and-placeholders.md)
