# 配置接口与构建时序

将片段合并到主配置的同名映射中。使用字典定义 `images` 和 `builds`，共享角色通过 `include` 与 `ref` 组合。根委派骨架见 [../assets/basic/main.yml](../assets/basic/main.yml)。

## 1. 镜像、角色和记录

dnsb 输入使用 `name/inet/images/builds`，服务定义放在 `builds`；构建输出才是 Compose 的 `services/networks`。先检查这些输入字段，再运行构建。以下单区配置建立 `resolver → auth`，供后续片段组合：

```yaml
name: teaching
inet: 10.88.0.0/24
images:
  auth-image:
    ref: bind:9.18.4
  resolver-image:
    ref: unbound:1.19.0
  tool-image:
    ref: python:3.12.0
builds:
  auth:
    image: auth-image
    ref: std:auth
    behavior: example.com master www A 192.0.2.10
  resolver:
    image: resolver-image
    ref: std:recursor
    behavior: example.com stub auth
  client:
    image: tool-image
    command: tail -f /dev/null
    environment:
      RESOLVER: ${srv.resolver.ip}
```

- 用固定版本的 `ref`，或 `software/version/from` 三元组定义内部镜像。为 `std:<role>` 提供可识别软件类型的 `image`。
- 将 PowerDNS Authoritative 写为 `pdns_auth`，PowerDNS Recursor 写为 `pdns_recursor`；分别配置权威与递归角色。
- 使用本地 Dockerfile 目录配置其他软件、编译补丁或额外依赖；按镜像实际 entrypoint 设置 `command`。
- 省略 `address` 以自动分配 IPv4；设置固定地址时检查网段、网关和地址唯一性。`address: ""` 跳过静态分配，适用于另行配置网络的服务。
- 将触发名称、节点数量、响应模式等数据放入 `vars`。额外顶层字段会透传给 Compose，适合 `networks`、`volumes` 等 Compose 字段。

### Behavior DSL

`master` 格式为 `<zone> master <owner> <type> [ttl] <targets>`；其他行为使用 `<zone> <kind> <target1>,<target2>`。

| 写法 | 生成内容 |
| --- | --- |
| `. hint root` | 指向一个根服务的 hints 文件 |
| `. forward upstream` | 指向上游递归器的转发配置 |
| `example.com stub auth` | 指向该区权威的 stub 配置 |
| `com master example NS auth` | 父区委派，以及 `auth.servers.net.` 的地址记录 |
| `example.com master www A 300 192.0.2.10` | TTL 为 300 的 A 记录 |
| `example.com master alias CNAME www.example.com.` | 指向完整名称的 CNAME |

使用末尾点表示 FQDN，使用 `@` 表示区 apex，其余名称相对于所在 zone 展开。`NS <service>` 自动生成 `<service>.servers.net.` 与 A；显式 NS FQDN 只生成 NS，地址数据另行配置。详见 [topology.md](topology.md#delegation)。

为精确 TXT 内容、DNSSEC RR、特殊标签字节或 TTL=0 使用原始 zone/RR 文件、hook 或动态端点。当前 `MasterBehavior` 对普通字符串目标执行名称展开，`ZoneGenerator.generate` 对 TTL=0 省略 TTL 文本；在最终文件和报文中检查所需值。

## 2. 文件注入与配置 Section

以下片段为解析器增加日志，并挂载项目自己的查询脚本：

```yaml
builds:
  resolver:
    image: resolver-image
    ref: std:recursor
    files:
      /usr/local/etc/unbound/observability.conf.server: |
        use-syslog: no
        log-queries: yes
        log-replies: yes
        verbosity: 3
  client:
    image: tool-image
    command: tail -f /dev/null
    volumes:
      - resource/probe.py:/usr/local/bin/probe.py:ro
    environment:
      RESOLVER: ${srv.resolver.ip}
```

| 配置方式 | 用法 |
| --- | --- |
| `files: {容器路径: 文本}` | 生成内容文件并挂载；从 Compose 查询 hash 命名的实际源文件 |
| `*.conf.server` / `*.conf.options` | 分别注入 Unbound `server:` / BIND `options {}` |
| `volumes` 的相对源路径 | 将项目资源复制到服务 `contents/`，形成构建快照 |
| `volumes` 的绝对源路径 | 挂载该宿主路径，适用于明确使用宿主文件的实验 |
| `mounts` | 将 Compose 挂载透传，适用于普通应用配置或共享运行目录 |
| `resource:/configs/...` | 读取工具内置资源 |
| `resource/probe.py` | 读取实验目录中的脚本 |
| `temp:/` / `key:/` | 在构建 hooks 中读写临时 zone 与签名材料 |

将 nginx 等普通应用配置挂到 `*.config` 等后缀并传入应用的 `-c` 参数，或使用 `mounts`；`*.conf` 会进入 DNS 配置组装。通过生成的主配置检查 include 和 Section 的最终位置。

hook 文件操作使用 `fs.read_text(DNSBPath(...))`、`fs.write_text(...)` 或 `workdir / 'resource' / ...`。`${origin}` 标记直接使用的来源路径；`${required}` 标记待填写字段。用已分配的地址检查结果处理替换器产生的 `none` 和未解析占位符。

## 3. 按输入状态选择阶段

以 `src/dnsbuilder/builder/build.py` 的 `Builder.run` 为入口：

| 阶段 | 执行动作 | 此时可用的数据 |
| --- | --- | --- |
| include 预处理 | 合并公共镜像、角色和配置 | 主配置与 include 内容 |
| 全局 `auto.setup` | 创建服务、填写 ref、生成行为和占位符 | 原始配置、全局 vars |
| 服务 `auto.setup` | 生成本服务的行为、模板和资源 | 当前服务已有字段 |
| ref → IP → 变量替换 | 展开模板、分配地址、解析字符串 | `${srv.*.ip}`、软件类型与版本 |
| 拓扑映射 → `auto.modify` | 修改最终字段，序列化地址表 | 已展开、已替换的服务配置 |
| `dnssec.hooks.pre` | 修改将参与首签的数据 | 当前区 `db.<zone>.unsigned` |
| 首签 → barrier → `mid` | 调整父区的 DS 输入或待重签数据 | 全部区的 key/DS、`zone_graph` |
| 子到父重签 → `post` | 修改最终签名 RRset | 最终 `db.<zone>`、`zone_graph` |
| 挂载复制 → `auto.restrict` | 检查生成结果，赋值 `result = 'PASS'` | 配置与已复制文件 |
| Compose 写出 → `auto.post` | 检查 Compose、导出地址与记录清单 | `output_dir` |

全局 setup/modify 脚本先于对应服务脚本执行；全局列表串行，各服务可并行。将共享拓扑生成放在全局脚本，将服务文件生成放在局部脚本。

组合多个片段时，将同阶段 `auto` 操作合成一个脚本或有序脚本列表：先创建节点，再检查具名关系，再准备地址占位符。跨脚本共享的数据写入 `config['vars']`；需要复用的函数放入项目模块或同一脚本。DNSSEC 的同阶段 hooks 合成一段脚本文本。检查合并结果，保留前一片段需要执行的操作。

模板的 setup 在 ref 展开前执行。批量创建实例时，直接填写行为，或将 setup 脚本及其 vars 显式放到实例上。modify 使用已经展开的字段和值；新服务、ref、include 和待替换占位符在更早阶段生成。

`auto.post` 的 `output_dir` 在全局指项目输出目录，在服务脚本中指该服务目录。使用该变量处理自定义输出位置。modify 改过行为后，用最终配置补充拓扑清单；`--graph` 的图在 modify 前生成。

## 4. 使用标准权威支撑区

`resource:/includes/std-auth.yml` 提供 `net`、`servers` 和 `servers.net` 名称地址数据。在主配置中预先声明根 `. master` 行为，供 include 的 setup 接入支撑区。

设置 `vars.std.dnssec` 控制所有含 master 行为的服务。混合签名实验在服务级 modify 中设置该服务的 `dnssec.enable`；它在全局 std-auth modify 之后执行。DNSSEC 具体写法见 [dnssec.md](dnssec.md)。

按实验参数设置模板中的 QMIN、validation、缓存和重试选项，并检查实际生成的配置。Unbound 基础模板的信任锚为空、QMIN 关闭；启用验证时补充本地根锚和 validator 配置。
