# 文档、示例与源码定位

以下 `doc/`、`examples/`、`src/` 路径相对于 DNS-BUILDER 仓库根目录。先按操作读取对应 skill 片段，查看参数或生成结果时再定位到表中的字段与函数。

## 1. 配置与运行接口

| 操作 | 文档 | 源码位置 |
| --- | --- | --- |
| 定义主配置与合并 include | `doc/config/top-level.md`、`doc/rule/merge-and-override.md` | `src/dnsbuilder/config.py`、`src/dnsbuilder/preprocess.py`、`src/dnsbuilder/utils/merge.py` |
| 选择软件、镜像与角色 | `doc/config/images.md`、`doc/config/external-images.md`、`doc/rule/build-templates.md` | `src/dnsbuilder/builder/resolve.py` 的 `Resolver`，`src/dnsbuilder/resources/builder/templates/` |
| 解析 behavior | `doc/rule/behavior-dsl.md` | `src/dnsbuilder/factories.py` 的 `BehaviorFactory` |
| 生成 owner、NS 与 glue | `doc/rule/behavior-dsl.md` | `src/dnsbuilder/abstractions.py` 的 `MasterBehavior._parse_args/generate/get_rname` |
| 比较 forward/stub 的软件语义 | `doc/rule/behavior-dsl.md` | `src/dnsbuilder/bases/behaviors.py` 的各软件 `ForwardBehavior/StubBehavior` |
| 动态生成服务与后处理 | `doc/config/auto.md`、`doc/config/processing-pipeline.md` | `src/dnsbuilder/auto/manager.py` 的 `AutomationManager.setup/modify/post`；`src/dnsbuilder/auto/executor.py` |
| 分配 IP 与替换变量 | `doc/rule/builtins-and-placeholders.md` | `src/dnsbuilder/builder/net.py` 的 `NetworkManager.plan`；`src/dnsbuilder/builder/substitute.py` 的 `VariableSubstitutor` |
| 写入 files、复制 volumes | `doc/rule/paths-and-fs.md`、`doc/config/builds.md` | `src/dnsbuilder/builder/service.py` 的 `ServiceHandler._process_files/_process_volumes` |
| 将配置片段放入 Section | `doc/rule/config-generation.md` | `src/dnsbuilder/io/path.py` 的 `parse_sr`；`src/dnsbuilder/bases/includers.py` |
| 接入内置名称支撑区 | `doc/resources.md` | `src/dnsbuilder/resources/includes/std-auth.yml` 的 setup/modify |
| 构建命令与输出目录 | `doc/cli.md` | `src/dnsbuilder/cli.py`；`src/dnsbuilder/builder/build.py` 的 `Builder.run/_setup/_assemble` |

## 2. DNSSEC 数据流

文档入口：`doc/dnssec.md`；操作片段：[dnssec.md](dnssec.md)、[zone-mutation.md](zone-mutation.md)。

| 操作 | 源码位置 | 读取重点 |
| --- | --- | --- |
| 解析 enable/include/hooks | `src/dnsbuilder/utils/dnssec.py` 的 `get_dnssec_config` | bool 与字典格式，include 列表化 |
| 创建工具 runner | `src/dnsbuilder/utils/dnssec_tools.py` 的 `create_dnssec_tool_runner` | host/docker、环境变量、临时工作目录与工具路径 |
| 查找固定 KSK/ZSK | `src/dnsbuilder/builder/zone.py` 的 `ZoneGenerator._find_keys_in_include` | flags、目录匹配顺序、BIND basename |
| 首签与 pre | `src/dnsbuilder/builder/zone.py` 的 `ZoneGenerator.generate/_sign_zone` | unsigned、keygen、$INCLUDE、signzone 参数、DS 输出 |
| 确定父子区 | `src/dnsbuilder/builder/dnssec.py` 的 `DNSSECResigner._bld_deps/_find_parent` | key 路径、逐标签父区、同 origin 条目 |
| mid、重签与 post | 同文件的 `DNSSECResigner.run/_resign_parent_zone/_resign_zone` | 所有 mid → 子到父重签 → 所有 post |
| 汇总根锚与 DS | 同文件的 `DNSSECHandler.run/_generate_root_key/_combine_ds_records` | post 后从 key FS 汇总 root.key/all.ds |
| barrier 与挂载时机 | `src/dnsbuilder/builder/build.py` 的 `Builder._generate`；`src/dnsbuilder/builder/service.py` 的 `ServiceHandler.generate_all` | 首签完成、等待、重签、复制顺序 |
| PowerDNS metadata | `src/dnsbuilder/builder/service.py` 的 `_write_pdns_dnssec_metadata`；`src/dnsbuilder/utils/pdns_dnssec.py` 的 `write_bind_dnssec_db` | 首签缓存、NSEC3PARAM、PRESIGNED；修改后按最终文件同步数据库 |
| 区名与文件名 | `src/dnsbuilder/utils/zone.py` 的 `ZoneName` | fqdn/label/filename，根区命名 |

检查实现时同时查看失败分支与最终产物。当前部分签名失败路径输出 unsigned，部分重签错误只写日志；用最终 RRset 与正常验证查询检查签名结果。

## 3. 通用示例的具体使用位置

| 使用点 | 文件与字段 | 应用方式 |
| --- | --- | --- |
| 服务名→IP/软件映射 | `examples/app/cache/cache.yml` 的 `auto.setup` 与服务 `auto.modify` | 在 setup 准备占位符，在 modify 输出工具配置；本 skill 的写法使用 service vars |
| 跨实现查询与配置输出 | `examples/app/difference/differ.yaml` 的服务定义与 JSON/YAML 输出 | 保持相同输入，按软件生成控制配置；目标使用项目中的服务 |
| 选择报文生成函数 | `examples/app/error/test_custom.yml` 的 `query_targets` | 按名称、文件和函数组织项目探测输入 |
| 构造通用协议字段 | `examples/app/error/custom_packets.py` | 定位 TC、TTL、SOA、EDNS、CNAME、CD 等相应函数 |
| 混合权威与应用配置 | `examples/bugs/dnssec-fault/pdns.yml` 的 `auth-cn`、`rec-host.volumes/files` | 配置 pdns_auth，挂载根锚，将 nginx 配置使用独立后缀 |

动态拓扑使用 [topology.md](topology.md) 的片段；漏洞能力组合使用 [example-patterns.md](example-patterns.md)；按具体功能读取上述位置。

## 4. 回归检查入口

- `test/skills/test_dns_builder_skill.py`：配置片段、角色/名称计划、地址迁移、UDP/TCP 响应、DNSSEC 关联与 hooks、引用检查；BIND 工具可用时执行真实签名验证。
- `test/utils/test_dnssec_tools.py`：工具选择、host/docker runner。
- `test/utils/test_zone.py`：zone 名称与路径。
- `test/utils/test_pdns_dnssec.py`、`test/test_powerdns.py`：PowerDNS 配置与签名 metadata。
- `test/sections/`、`test/rules/`：配置 Section、软件版本规则。

在仓库根目录运行选定测试，例如 `.venv/bin/python -m pytest test/skills/test_dns_builder_skill.py -q`。对需要外部工具的签名检查准备 BIND utilities，再对生成文件执行 zone 检查与真实验证。
