# 漏洞复现的能力组合

按目标机制选用 DNS-BUILDER 的配置、生成、签名和运行接口。将软件版本、名称、数量与时序填入项目参数，使用本页的局部写法连接所需能力。

## 1. 从场景选择构建能力

| 场景 | 使用的能力 | 操作与观测 |
| --- | --- | --- |
| BadCache | 全局 DNSSEC + 服务级 modify + 跨区 NS | 设置签名/非签名服务，检查 NS 地址所属区、父区 DS 和缓存变化 |
| Birthday / Rebirthday | 自定义权威、文件注入、ECS 参数 | 按 ECS 前缀区分请求，记录源端口/ID、等待窗口与查询聚合 |
| CAMP | 动态 zone、NS/CNAME、精确 apex、QMIN | 分别编排委派深度、扇出、别名长度与名称标签深度 |
| Cuckoo | include/ref、软件选择、跨区记录 | 保持角色与边表，切换解析器，检查响应 section 和缓存中的 owner |
| Disbalance | 多权威、端点 delay/TTL | 对不同权威设置时延，统计解析器的选择、重试与请求分布 |
| DNSBomb | 延迟应答、EDNS、队列与时间片采集 | 分别控制等待窗口、查询数量、响应大小，测量聚合与释放流量 |
| DNSPun | 响应模式、共享权威、解析器状态 | 切换正常/失败响应，观察重试、权威可达状态和恢复查询 |
| DNSSEC fault | hooks、运行期 reload、混合权威 | 分离 zone 修改、签名链、控制应用和配置发布 |
| DNSSEC downgrade | 签名链、递归验证配置、CD 对照 | 检查 DS、DNSKEY、RRSIG 和各阶段验证状态 |
| FragForward | 本地 Dockerfile、转发配置、raw socket | 固定编译参数，分别检查 CNAME 追踪、IP 分片与重组 |
| Inject | 原始 zone、标签转义、软件 Section | 保留标签字节，比较配置文本、加载结果与实际 wire name |
| Kaminsky | 固定版本、受控应答延迟、报文关联 | 记录 transaction ID、源端口、匹配窗口和缓存前后值 |
| KeyTrap | 固定密钥、DNSKEY/RRSIG/DS hooks | 保持签名链，控制候选 RRset，测量真实验证开销 |
| Loopy | 自定义镜像、明确根提示、循环边 | 固定源码版本与递归特性，记录重复查询路径与终止行为 |
| Maginot | 指定区 forward + 根层级 + 动态端点 | 检查转发 RD/fallback、响应 owner 和跨区数据的缓存结果 |
| NRDelegation | 多个 stub 区、动态 referral、NS 地址端点 | 分离初始委派与 NS 名称解析，检查每个端点匹配的 zone/QTYPE |
| NXNS | 显式 NS、缺失 glue、动态名称 | 记录 referral 触发的 NS 地址查询及负响应 |
| Phoenix | NS/glue/数据 TTL、延迟响应、缓存操作 | 在到期前后安排查询，分别记录各 RRset 的刷新与剩余 TTL |
| TsuKing | 入口/出口模板、源地址路由、动态 glue | 将服务路由编译为 IP 表，逐层核对来源与下一跳 |
| TsuName | NS 名称依赖图、CNAME 图 | 按真实 owner/target 构造循环，统计重复的名称/类型/上游组合 |
| TuDoor | 批量模式实例、raw DNS/ICMP、基础查询 | 将正常 NS/SOA 与错误响应分开处理，逐模式检查恢复与后续查询 |

配置接口见 [configuration.md](configuration.md)，端点与缓存写法见 [runtime.md](runtime.md)，观测步骤见 [reproduction.md](reproduction.md)。

## 2. 保持拓扑，切换软件实现

为两个候选模板提供镜像，使用 setup 选择 resolver：

```yaml
vars:
  resolver_implementation: candidate-a
builds:
  resolver:
    ref: candidate-a
  candidate-a:
    image: resolver-image
    ref: std:recursor
    build: false
  candidate-b:
    image: alternate-resolver-image
    ref: std:recursor
    build: false
auto:
  setup: |
    selected = config['vars']['resolver_implementation']
    if selected not in {'candidate-a', 'candidate-b'}:
      raise ValueError('Unknown resolver implementation')
    config['builds']['resolver']['ref'] = selected
    config['builds']['resolver']['build'] = True
```

初始 ref 指向已声明的模板，以通过配置加载。使用同一份 resolver behavior；将软件专用文件放到各模板。对比前检查最终 command、配置目录、DNSSEC、QMIN 和转发 RD。

## 3. 将端点模式与时序参数化

在项目中编写响应程序，通过环境变量接收模式、时延和绑定地址：

```yaml
builds:
  controlled-endpoint:
    image: tool-image
    command: python3 /usr/local/bin/endpoint.py
    volumes:
      - resource/endpoint.py:/usr/local/bin/endpoint.py:ro
    environment:
      BIND_ADDRESS: ${ip}
      CASE_NETWORK: ${proj.inet}
      RESPONSE_MODE: normal
      RESPONSE_DELAY_SECONDS: "0"
```

增加模式时复用该接口，分别控制正常应答、延迟、错误码和原始报文。记录查询输入、响应内容与发出时刻；把端点等待时间与解析器 CPU 时间分别测量。

<a id="nxns"></a>

## 4. NXNS：将 NS 名称解析变成可观测的独立分支

1. 用 `stub` 接入单个受控区，或用根/TLD 委派接入该区；为 NS 名称所属区建立独立的名称解析路径。
2. 将 referral owner、NS 目标名与服务名分开。静态 RR 使用 [topology.md](topology.md#fanout) 的显式 FQDN 扇出片段；随查询变化的 RR 使用端点生成。
3. 按报文要求设置 ANSWER、AUTHORITY 和 ADDITIONAL。缺失 glue 的输入使用显式 NS FQDN，并保持对应 ADDITIONAL 为空；`NS <service>` 用于需要框架生成地址记录的情况。
4. 为 NS 地址查询分别设置 A、AAAA、NXDOMAIN、NODATA 或下一层 referral。保持 apex NS/SOA 查询可用，并覆盖解析器实际发出的 QTYPE。
5. 将每次查询的名称序号、seed 和 NS 候选数作为输入。检查实际响应长度、截断和去重后的 NS 数。
6. 从解析器出站流量统计 NS 地址查询，按目标权威与 QTYPE 分类；记录缓存命中、负缓存、fetch 限制和重试对查询数的影响。

将“返回了多少条 NS”和“解析器实际发出了多少条 A/AAAA 查询”分别记录。扩展到多层名称依赖时，对每层的 zone 匹配、返回类型和终止响应做相同检查。

<a id="tsuking"></a>

## 5. TsuKing：连接服务内转发与来源驱动的委派

分别定义两组关系：

- **组内服务连接**：入口转发器的候选出口列表，出口递归器接入受控权威的方式。
- **组间响应路由**：权威观察到的出口源地址，对应的下一层入口地址列表。

使用 [topology.md](topology.md#layers) 生成入口/出口实例，再使用 [来源路由片段](topology.md#source-routing) 输出 JSON。给实例显式设置 `build: true`；在 setup 生成服务名与占位符，在 modify 序列化已分配的地址。

端点从接收查询的源 IP 查表，将结果用于本次 NS/glue。分别记录 NS 名称、glue 地址和下一层服务角色。将链尾映射到项目定义的接收端或终止响应。

逐层检查：

1. 入口发往组内出口的实际目标与 RD。
2. 出口发往权威的源 IP 是否存在于路由表。
3. 权威返回的 NS/glue 是否指向下一层入口。
4. 下一层入口如何处理 RD=0 查询，以及转发后的 RD、QNAME/QTYPE。
5. 每组收到的查询数、权威回访次数、终端收到的查询数及时间窗。

将组数、出口宽度、层间分支、NS 名称复用和 TTL 分别参数化。用实例角色和显式边表建立连接，按观测结果修正 NAT 或其他网络模式下的来源映射。

<a id="camp"></a>

## 6. CAMP：连接委派、扇出、别名与 QMIN

为每个操作分别保存输入名称、输出名称、所属 zone、负责服务和终止条件。定义四个独立规模参数：委派深度、NS 候选数、CNAME 长度和名称标签深度。

| 组合 | 编写方式 | 连接点与检查 |
| --- | --- | --- |
| DD–FO | setup 逐层生成子区，在每个父区为下一级委派写多个区外 NS；在名称支撑区生成下一层地址 | 当前父区 origin → 子区 owner → NS 名称 → 下一层权威地址；检查层尾数据 |
| FO–CN | 生成多个待解析的 NS 名称，在其所属区分别配置 CNAME 链与终端地址 | 每个 NS 名称作为地址解析入口；检查解析器对 NS 目标别名的处理与权威加载结果 |
| CN–QM | 连接数据名称的 CNAME 链，为相关分区使用具有多级标签的 NS 名称；启用对应 QMIN 参数 | 每次别名追踪与 NS 地址解析的入口；记录逐后缀查询及空非终端响应 |
| NS–FO | 将 NS 名称的地址解析连接到下一段委派，再为该委派提供多个 NS 候选 | 区分父子 zone 深度与“解析 NS 名称所依赖的下一段”；逐段检查 owner 和 targets |

### 编写连续委派

- 将每层记录保存为 `parent_zone/child_label/ns_names/address_zone/next_services`；按服务聚合 behavior 行。
- 父区用 `<parent> master <child> NS <fqdn>` 生成委派；名字支撑区用 `<address-zone> master <ns-label> A <service>` 映射地址。
- 区内 NS 由父区提供必要 glue；区外 NS 在其所属区解析。需要继续查询名称时，选择相应的地址解析关系。
- 根据完整 child origin 创建下一层 zone。查询每层 SOA、委派 NS 和 NS 地址，直到指定链尾。

### 编写别名与深名称

- 对每个 CNAME owner 生成唯一目标，并为链尾提供明确数据或响应。跨 zone 的目标使用 FQDN。
- 需要精确的 apex NS/SOA 或自定义 zone cut 时，通过 [自定义 zone](zone-mutation.md#custom-zone) 发布文件，保持注册的 zone origin 与文件一致。
- 启用 QMIN 后，分别检查中间后缀、空非终端节点、NS/A/AAAA 和最终名称；按实际查询日志识别展开位置。
- 将不同分支的名称与地址分别计数。共享地址、共享后缀、缓存和重试策略会影响实际请求数；CNAME 链也可能在一次权威响应中整体返回。

先运行单个操作，再逐段连接并测量。使用 [evaluation.md](evaluation.md) 的查询数与字节口径比较各段，以及组合后的实际输出。

<a id="keytrap"></a>

## 7. KeyTrap：保持验证链，控制候选记录与修改时机

1. 建立能够通过真实 validator 的正常链，逐区检查 DNSKEY、父区 DS 和目标 RRset 的 RRSIG。
2. 将一对可签名 KSK/ZSK 放到独立 include 目录；将候选公钥与目标签名放在记录文件中。
3. 用 [pre DNSKEY 导入](zone-mutation.md#dnskey-import) 将附加公钥写入 apex RRset，使首签覆盖这些数据。
4. 用 [post RRSIG 导入](zone-mutation.md#rrsig-import) 操作选定 owner/type covered 的签名集合，使修改发生在父区重签结束后。
5. 按实际 RDATA 计算 key tag，检查候选键与签名的 algorithm、tag、signer、labels、TTL、有效期和编码。分别检查 `RRSIG(DNSKEY)` 与目标数据的覆盖签名。
6. DS 候选实验使用子区 mid 或父区 unsigned，使父区的 `RRSIG(DS)` 覆盖目标集合。检查中间区重签时 DS 再生成的顺序。
7. 通过 TCP 获取完整 DNSKEY/RRSIG 集合，再经真实递归器测量正常与修改后查询的 CPU、时延和验证结果。记录保留的有效签名、验证缓存和实际算法支持情况。

签名命令、密钥目录、NSEC3、DS 传播和工具版本的联动见 [dnssec.md](dnssec.md#signzone)；首签/重签/post 的完整时序见 [签名顺序](dnssec.md#signing-order)。

## 8. 组合后的检查顺序

按 `配置展开 → 最终文件 → 直接端点报文 → 递归器路径 → 机制指标` 检查。每次变更后重跑对应查询，保存结果，再增加下一段机制。

使用 [source-map.md](source-map.md) 定位通用文档、示例中的具体字段和源码函数。将项目自己的拓扑输入、记录材料、端点和验证入口放在同一工作目录，使用 manifest 保存构建输入与最终产物。
