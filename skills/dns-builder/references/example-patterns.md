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

## 4. NXNS：连接 referral 与 NS 地址解析

**机制条件**：解析器接受 referral 后，继续解析其中 NS 名称的地址。分别定义触发区、NS 名称所属区及其响应服务；缺失 glue 的分支使用显式 NS FQDN。将 NS 候选数与真实 A/AAAA 查询数分别统计。

| 构建动作 | DNS-BUILDER 接口 | 检查结果 |
| --- | --- | --- |
| 接入触发区与名称支撑区 | 独立 stub 或正常根/TLD 委派 | 两个区的基础查询都到达对应项目服务 |
| 返回所需 referral | 静态 NS DSL 或动态端点；[响应表](runtime.md#response-contract) | 空 ANSWER、正确委派 owner/NS、所选 glue 与 flags |
| 定义 NS 地址查询响应 | 名称支撑区的记录或端点分支 | A/AAAA、NODATA、NXDOMAIN 或下一段 referral 与名称计划一致 |
| 观测名称解析 | 解析器出站 pcap、支撑服务接收日志 | 实际 NS 地址查询、重试与负缓存变化 |

按以下顺序搭建：

1. 先为触发名称返回普通数据，验证 resolver→端点的路径；再为一个 NS 名称完成地址解析或预设负响应。
2. 用 [显式扇出](topology.md#fanout) 或端点生成候选名称，从引用清单派生对应的正向/负向处理。按 [名称计划](topology.md#resolution-plan) 检查每种 QTYPE。
3. 扩大候选集合，检查去重后的 RR 数、wire 长度、EDNS/TC 与 TCP。将名称复用与新名称作为不同缓存条件。
4. 经真实解析器触发，按 run_id、QTYPE、目标服务和时间窗统计查询；比较正常输入与 referral 输入。

**中断定位**：端点未收到触发查询，检查 stub/委派与就绪；收到 referral 却无地址查询，检查 owner、flags、glue、缓存及实现的候选选择；地址查询离开预期路径，检查 NS 所属区的委派/支撑数据。用实际出站计数判定机制，最终超时单独记录。

这些步骤也适用于 glueless delegation、NRDelegation、多权威选择与负缓存实验。

<a id="tsuking"></a>

## 5. TsuKing：组合组内转发与来源驱动的下一跳

本节处理来源驱动的链式组合。分别定义组、组内入口/出口、层间边与终端；组数、每组出口数和层间分支独立配置。

| 关系 | 生成位置 | 必须核对的对象 |
| --- | --- | --- |
| 入口→本组出口候选 | setup 中生成 forward behavior | 实例 build=true、候选出口属于本组 |
| 出口→受控权威 | 出口的 stub/迭代路径 | 权威实际看到的来源地址与查询 |
| 出口来源→下一组入口 | setup 准备具名路由，modify 编译地址 JSON | 全部出口覆盖、目标角色、组间方向 |
| 链尾→终端 | 显式终端映射与响应模式 | 终端实际接收查询及结束条件 |

1. 使用 [分组实例](topology.md#layers) 建立一个组，直接查询验证组内连接与 RD 行为。
2. 用 [来源映射](topology.md#source-routing) 编译路由，并把组内连接与来源路由合成逻辑边，执行 [角色/路径检查](topology.md#flow-check)。应结束的路径逐分支到达终端；循环输入另行声明环。
3. 从每个预期出口查询权威，核对响应 NS/glue 指向的下一组。新增、重排服务或换子网后重新编译并检查全部来源。
4. 加入下一组，观察前一组出口→权威→下一组入口的真实流量。分别记录进入入口时的 RD、转发后的 RD，以及权威回访来源。
5. 再扩展组数与分支，按组保存输入数、出口查询、权威回访和终端计数。上游候选列表的长度与实际并发/重试分别记录。

**中断定位**：来源未命中映射时保存 unmapped-source；默认分支用于明确声明的探测输入。反复只看到同一组时，检查兜底地址、自环和入口/出口角色错配。若 NAT 合并了需要区分的来源，先调整网络或观测位置以恢复来源区分。链在组边界停止时，检查所选软件版本对 RD=0 的实际处理、访问控制和转发行为。

具名角色、来源覆盖和终端可达性的检查，同样用于多级转发、按来源响应及跨实现路由实验。

<a id="camp"></a>

## 6. CAMP：使每个组成部分真正产生后续查询

分别保存每个操作的输入名称、派生名称、所属 zone、负责服务和终止响应。CAMP 的 DD 指 Dense Delegation：在深名称的各级设置实际 zone cut；名称标签深度与实际遍历的委派层数分别测量。

| 组合 | 连接方式 | 关键检查 |
| --- | --- | --- |
| DD–FO | 每层委派提供多个区外 NS，支撑区提供下一层地址 | 父区→子区 owner→NS 地址→下一层权威；所有引用与链尾都有处理 |
| FO–CN | 多个 NS 名称的地址解析分别进入 CNAME 链 | 检查解析器对 NS 目标别名的处理；每条链有明确终端数据或失败响应 |
| CN–QM | 数据 CNAME 链连接多个分区，相关 NS 名称包含多级标签 | 链位置按 length 生成，标签按 depth 生成；支撑数据从全部引用派生 |
| NS–FO | 解析 NS 名称时进入下一段 referral，并产生新的候选集合 | 将名称依赖与父子 zone 深度分开；逐段检查 owner/targets |

### 构建与检查顺序

1. **独立操作**：分别运行单层委派、少量候选、短别名链和深名称查询，保存实际出站查询。
2. **区与服务分配**：普通权威按最长后缀选 zone；把必须逐层经过的嵌套 zone 分配到相应权威实例。检查解析器是否跳过中间层。
3. **名称引用**：从委派/别名清单派生地址数据，执行 [名称计划检查](topology.md#resolution-plan)。对 length/depth、委派深度/扇出宽度使用不相等的参数验证。
4. **精确 RRset**：需要特定 apex NS/SOA 时使用 [自定义 zone](zone-mutation.md#custom-zone)。核对框架默认 apex NS 是否增加了另一条解析路径，并核对父区委派与子区 apex 的实际值。
5. **组合与对照**：先连接两个小规模操作，再改变一个维度。宽度为 1 用作基线，另测非退化宽度；QMIN 显式配置并观测实际后缀查询。
6. **实际路径**：直接查各权威确认记录，再经递归器触发，记录实际遍历的层级、分支、CNAME 追踪和终端接收；分别计算辅助服务与目标服务的流量。

**中断定位**：深度增加而查询路径不变，检查最长 zone 匹配和缓存；别名长度增加而查询数不变，检查是否一次返回整条链；改变 length/depth 后部分名称无响应，检查生成循环与引用清单；组合中出现较快结束，检查额外 NS、终端数据与失败/负缓存语义。

这种按“派生查询→下一组成部分入口”连接的方法，也适用于 CNAME/NS 依赖、QMIN、缓存和多层委派场景。指标口径见 [evaluation.md](evaluation.md)。

<a id="keytrap"></a>

## 7. KeyTrap：保持信任链并定位候选验证开销

先选择要改变的候选集合：DNSKEY、目标 RRSIG、二者组合或 DS。为每种集合分别配置数量、algorithm/tag、owner/type covered、时间窗口与预期验证结果。

| 材料或阶段 | 操作 | 检查结果 |
| --- | --- | --- |
| 正常签名链 | 固定 KSK/ZSK include、自动 DS 传播、真实 validator | 正常查询验证通过，根锚和父区 DS 正确 |
| 附加 DNSKEY | [pre 导入](zone-mutation.md#dnskey-import) 后正常签名 | 实际候选组与 RRSIG(DNSKEY) |
| 目标 RRSIG | [post 导入](zone-mutation.md#rrsig-import)，明确追加或替换 | owner/covers、候选键匹配、时间窗口、保留的有效签名 |
| DS 候选 | 子区 mid 或父区 unsigned | 父区发布并签名目标 DS 集合；中间区再生成顺序正确 |
| 正式查询 | 完整传输检查、普通/CD 查询、CPU 与日志采集 | 查询实际进入目标 RRset 的验证路径 |

1. 先用正常输入完成真实验证，记录软件/工具版本、算法支持、密钥与缓存状态。
2. 按 [材料输入](zone-mutation.md) 生成记录，并用 [关联检查](dnssec.md#signature-links) 比较实际 algorithm/tag、signer、有效期和候选数。候选数量按不同 RDATA 计算。
3. 保持用于建立信任的 DNSKEY RRset 及其签名关系符合预期，再改变目标 RRset 的候选集合。分别验证单类变化与组合变化。
4. 从最终挂载和 TCP 响应核对完整集合与报文容量，再测试 UDP/TC/回退。记录读取到的实际 RR 数。
5. 使用相同缓存准备比较正常输入、目标输入与 CD 查询，采集解析器 CPU、查询时延、验证日志及目标 RRset 的权威查询。

**中断定位**：无候选键、算法不支持、编码错误或签名过期时，先定位提前失败的字段；正常查询也失败时，检查根锚、DS、RRSIG(DNSKEY)、时间与连通性；TCP 获取失败时检查容量与服务；只出现延迟时，区分网络重试、端点等待、验证缓存与实际 CPU 消耗。

签名时序、工具参数与 metadata 处理见 [dnssec.md](dnssec.md#signing-order)。同一流程可用于签名失配、DNSSEC 降级与不同 validator 的行为对比。

## 8. 组合后的检查顺序

按 `配置展开 → 最终文件 → 直接端点报文 → 递归器路径 → 机制指标` 检查。每次变更后重跑对应查询，保存结果，再增加下一段机制。

使用 [source-map.md](source-map.md) 定位通用文档、示例中的具体字段和源码函数。将项目自己的拓扑输入、记录材料、端点和验证入口放在同一工作目录，使用 manifest 保存构建输入与最终产物。
