---
name: dns-builder
description: 根据论文、PoC 或实验需求，使用 DNS-BUILDER 构建并验证 DNS 漏洞复现环境。用于编写 DNS 拓扑、批量生成服务、配置委派与转发、接入动态响应端点、构建 DNSSEC 签名链、修改 zone，以及观测查询放大、缓存和验证开销。
---

# DNS-BUILDER 漏洞环境构建

使用 `behavior` 表达 DNS 关系，使用 `auto.setup` 生成节点和记录，使用 `auto.modify` 输出已解析地址的配置，使用 DNSSEC hooks 操作签名数据，再通过真实 DNS 软件查询验证。

## 工具与路径

- 在 DNS-BUILDER checkout 中使用 `.venv/bin/dnsb`；安装版使用 `dnsb`。通过 `dnsb --no-update-check build --help` 查看当前 CLI，使用 Python >=3.12。
- 本 skill 的 `references/`、`assets/`、`scripts/` 相对于 skill 目录；`doc/`、`examples/`、`src/` 相对于 DNS-BUILDER 仓库根目录。
- `resource:/` 访问工具内置资源；`resource/` 访问当前实验项目文件；hooks 通过 `DNSBPath` 和 `fs` 操作 `temp:/`、`key:/`。
- 在同一个 YAML 映射中合并配置片段，将实验参数放入 `vars`、资源放入项目的 `resource/`。

## 按能力选读

| 操作 | 资料 |
| --- | --- |
| 镜像、角色、DSL、文件注入和构建时序 | [configuration.md](references/configuration.md) |
| 批量节点、边表、NS/glue、按来源地址映射下一跳 | [topology.md](references/topology.md) |
| KSK/ZSK、DS 链、信任锚和 BIND 签名工具 | [dnssec.md](references/dnssec.md) |
| 修改 DNSKEY/RRSIG/DS、精确编辑 RRset、重新加载 zone | [zone-mutation.md](references/zone-mutation.md) |
| 软件矩阵、缓存、动态端点、网络和抓包 | [runtime.md](references/runtime.md) |
| 构建、触发、报文检查和结果记录 | [reproduction.md](references/reproduction.md) |
| NXNS、TsuKing、CAMP、KeyTrap 及其他漏洞的能力组合 | [example-patterns.md](references/example-patterns.md) |
| 命令计时、资源指标和重建比较 | [evaluation.md](references/evaluation.md) |
| 文档、通用示例和源码函数定位 | [source-map.md](references/source-map.md) |

## 从机制选择操作路径

先按机制选读，再替换项目中的名称、软件和规模；同一条操作路径可用于不同漏洞。

| 机制与代表场景 | 阅读顺序 | 首先检查的产物 |
| --- | --- | --- |
| NS 地址解析与扇出：NXNS、NRDelegation | [委派](references/topology.md#delegation) → [响应表](references/runtime.md#response-contract) → [NXNS 组合](references/example-patterns.md#nxns) | NS 名称所属区、地址查询路径与实际出站计数 |
| 来源驱动的查询链：TsuKing、多级转发 | [实例](references/topology.md#layers) → [路由检查](references/topology.md#flow-check) → [TsuKing 组合](references/example-patterns.md#tsuking) | 完整出口映射、组间方向和链尾接收记录 |
| 委派/别名/QMIN 组合：CAMP | [名称计划](references/topology.md#resolution-plan) → [CAMP 组合](references/example-patterns.md#camp) → [自定义区](references/zone-mutation.md#custom-zone) | 各维度独立、zone cut 与真实遍历层级 |
| 签名记录与验证行为：KeyTrap、DNSSEC fault | [签名时序](references/dnssec.md#signing-order) → [记录关联](references/dnssec.md#signature-links) → [RRset 修改](references/zone-mutation.md) | 正常信任链、最终记录集合与验证开销 |

## 构建步骤

### 1. 填写实验参数

从论文或 PoC 填写软件版本、节点角色、QNAME/QTYPE、RD/DO/CD、传输协议、缓存状态和目标现象。将深度、宽度、TTL、时延、记录数量和终止条件设为独立参数。

分别列出 `hint`、`forward`、`stub`、父子 NS 委派、NS 名称地址查询和 CNAME 依赖。为每条关系填写“输入查询 → 响应规则 → 下一次查询 → 观测服务”，再映射到 DSL、端点或 hook。先验证正常解析，再验证一条边、小规模组合，最后改变参数；阶段检查见 [reproduction.md](references/reproduction.md#mechanism-checks)。

### 2. 组合配置与资源

参考 [assets/basic/main.yml](assets/basic/main.yml) 建立正常根委派；单区实验使用 `stub` 直接接入权威。

- 使用 `std:auth`、`std:recursor`、`std:forwarder` 配置软件角色，按版本补充配置 Section。
- 在全局 `auto.setup` 创建所有服务和行为；继承 `build: false` 模板的实例设置 `build: true`。
- 常规下一跳填写服务名；协议要求的 NS 名称填写 FQDN，分别配置委派与名称地址数据。
- 在 setup 中准备 `${srv.<service>.ip}`，在 modify 中将替换后的地址写入 JSON/YAML、命令或配置。
- 将按查询、来源地址、时序或状态变化的 DNS 响应实现为项目端点，通过 `volumes/files/environment` 接入。
- 启用 DNSSEC 时，按 `pre → 首签 → mid → 父区重签 → post` 安排记录修改，挂载 `key:/root.key` 并启用递归器 validation。

### 3. 构建与检查

在实验目录执行；将 `basic` 替换为配置中的 `name`：

```bash
mkdir -p run
dnsb --no-update-check --log-file run/build.log build main.yml --workdir @config
compose=output/basic/docker-compose.yml
docker compose -f "$compose" config --quiet
docker compose -f "$compose" build
docker compose -f "$compose" up -d
```

检查生成的 Compose、服务配置、挂载和最终 zone。DNSSEC 项目逐区检查 DNSKEY/RRSIG、父区 DS、信任锚，再执行直接权威查询与递归验证查询。查找构建问题时，使用 [source-map.md](references/source-map.md) 定位对应阶段。

### 4. 触发与观测

编写项目的 `verify.sh` 或 `verify.py`，依次执行就绪查询、缓存准备、正常查询、漏洞触发和结果断言。正常委派的 A 查询可参考 [assets/basic/verify.sh](assets/basic/verify.sh)。

- 放大实验统计客户端输入和解析器实际出站查询，按目的服务、QTYPE 和时间窗分类。
- DNSSEC 实验对比普通递归与 CD 查询，并记录验证日志、CPU 时间和查询延迟。
- 缓存实验记录填充、到期、刷新与再次查询的时刻；跨软件实验使用相同输入和缓存准备步骤。
- 给查询、采集和等待设置次数与时长，保存原始报文、日志和命令退出码。将超时、SERVFAIL 作为查询结果记录；机制检查使用实际路径、出站计数、缓存变化或验证开销及其对照结果。

### 5. 保存与重建

使用 [scripts/manifest.py](scripts/manifest.py) 保存源码与生成物清单，使用 [scripts/measure_command.py](scripts/measure_command.py) 记录命令耗时。归档日志后，对本项目执行 `docker compose -f "$compose" down --volumes --remove-orphans`，记录清理结果。

再次构建并运行同一验证入口，比较记录语义、查询路径和观测指标。DNSSEC 比较同时记录密钥、SOA serial 和签名有效期。依赖或 Docker 不可用时，将对应运行检查标记为 `not_run`，列出已完成的静态检查。
