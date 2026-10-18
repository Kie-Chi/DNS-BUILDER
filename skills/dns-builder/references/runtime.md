# 运行配置、动态端点与观测

使用角色模板组织服务，通过文件与环境变量接入项目端点，并按实验条件配置缓存、网络与采集。

## 1. 组合 include/ref 与启动命令

字典递归合并，子项标量覆盖父值，列表通常取去重并集。需要替换整个列表时，在 modify 赋值；需要删除某些挂载或工具时，过滤展开后的列表。

下面为现有 resolver 替换完整 argv：

```yaml
builds:
  resolver:
    auto:
      modify: |
        config['command'] = ['unbound', '-d', '-c', '/usr/local/etc/unbound/unbound.conf']
```

`files` 的同名键替换整段内容。同一容器目标的挂载按最终合并结果选择源文件，检查 Compose 确认结果。设置命令时同时检查镜像的 entrypoint；在容器前台运行 DNS daemon。

## 2. 软件矩阵与镜像

用同一份边表生成不同实现的实例，分别配置各软件支持的 directive：

| 软件 | 配置入口 | 需要设置与检查 |
| --- | --- | --- |
| BIND | named.conf、options、zone | hints、forward/fallback、DNSSEC、控制 key、daemon 用户 |
| Unbound | server、stub-zone、forward-zone | validation、QMIN、缓存、访问控制、控制文件 |
| PowerDNS Authoritative | pdns.conf、BIND backend | zone 路径、预签名 metadata、backend reload |
| PowerDNS Recursor | 版本对应的递归配置 | validation、trust anchor、RD、forward-zones-recurse、旧配置兼容开关 |
| Knot Resolver | 版本对应的 Lua/YAML | policy、daemon 启动参数、缓存与根锚 |
| 自定义软件 | 本地 Dockerfile、软件配置文件 | 源码版本、编译特性、运行路径和查询行为 |

检查软件特定的下一跳语义：当前 PowerDNS Recursor 的 forward/stub DSL 都生成 `forward-zones`；需要上游递归时，按版本配置 `forward-zones-recurse`。BIND forward 的 fallback 由实际配置决定。通过出站报文确认 RD 和目标地址。

本地构建上下文写法：

```yaml
builds:
  tool:
    image: ./images/tool
    command: python3 /usr/local/bin/probe.py
    volumes:
      - resource/probe.py:/usr/local/bin/probe.py:ro
```

在 `images/tool/` 提供 Dockerfile，将依赖安装与源码编译放在镜像构建阶段。固定软件版本、编译参数和基础镜像，启动后执行 `named -V`、`unbound -V` 等命令记录实际版本。跨架构运行时检查镜像平台与 daemon 的架构。

## 3. 从 vars 输出运行期数据

在 setup 准备名称与地址占位符，在局部 modify 将已经解析的映射写入 JSON。使用 service vars 存放构建数据，使用 environment 传递标量参数：

```yaml
vars:
  probe_targets: [resolver]
builds:
  probe:
    image: tool-image
    command: tail -f /dev/null
    vars:
      subnet: ${proj.inet}
    auto:
      modify: |
        import ipaddress
        import json
        targets = config['vars']['target_addresses']
        subnet = ipaddress.ip_network(config['vars']['subnet'])
        for name, address in targets.items():
          if ipaddress.ip_address(address) not in subnet:
            raise ValueError(f'Target is outside the case network: {name}')
        config.setdefault('files', {})['/usr/local/etc/targets.json'] = json.dumps(targets, sort_keys=True) + '\n'
auto:
  setup: |
    names = config['vars']['probe_targets']
    if len(set(names)) != len(names) or any(name not in config['builds'] for name in names):
      raise ValueError('Invalid probe target names')
    probe = config['builds']['probe']
    probe.setdefault('vars', {})['target_addresses'] = {
      name: f'${{srv.{name}.ip}}' for name in names
    }
```

同样准备 `${srv.<name>.image.software}` 以选择软件专用控制命令或配置。按来源 IP 路由的端点使用 [topology.md](topology.md#source-routing) 的路由表片段。

配置数据生成方式可定位 `examples/app/cache/cache.yml`、`examples/app/difference/differ.yaml` 的 setup/modify；运行本地实验时将其目标列表替换为项目服务，并使用本节的 vars/files 接口。

## 4. 缓存、TTL 与查询最小化

将 QMIN、prefetch、serve-expired、负缓存和验证缓存分别设为实验变量。下面为缓存观测设置 Unbound 参数：

```yaml
builds:
  resolver:
    files:
      /usr/local/etc/unbound/cache-observation.conf.server: |
        cache-min-ttl: 0
        prefetch: no
        serve-expired: no
        qname-minimisation: yes
        log-queries: yes
        log-replies: yes
```

- 依据目标机制设置上述值，并在最终主配置中检查；对比时只调整选定变量。
- 就绪查询使用独立名称；正式查询前按需要 flush 或重建解析器。记录 cold/warm cache、填充时刻与剩余 TTL。
- NXDOMAIN 表示名称不存在；NODATA 使用 NOERROR、空 ANSWER 与适当 SOA。负缓存观测同时记录 SOA TTL 与 MINIMUM。
- Phoenix 类时序设置分别控制父区 NS、glue、子区数据和响应延迟；用单调时钟安排 TTL 到期前后查询。
- QMIN 观测按后缀层级记录实际 QNAME/QTYPE；深名称、CNAME 链和空非终端节点分别检查。
- 名称随机化通过 seed 与序号管理。比较名称复用与新名称时，分别记录缓存键及实际出站查询。
- 缓存清理使用对应软件的 `rndc flush`、`unbound-control flush_zone` 或本项目解析器重建；权威 reload 与递归缓存清理分开执行。

## 5. 编写动态 DNS 响应端点

用常规 DSL 配置静态 RR；对来源地址、查询、状态、时延或原始字节有要求时，编写项目端点。真实解析器和 validator 使用待测软件，端点负责提供所需响应。

将 bind address、port、zone origin、mode、delay、seed、记录数量和下一跳映射作为输入。将响应结构与时序控制拆成独立函数：

| 处理环节 | 实现内容 |
| --- | --- |
| 接收查询 | 保存源 IP/port、transaction ID、QNAME/QTYPE、RD/CD/DO、EDNS 与 transport |
| 选择响应 | 按后缀、QTYPE、来源和状态选择正常 answer、referral、NODATA、NXDOMAIN 或原始字节 |
| 构造报文 | 显式设置 RCODE、AA/RA/TC 和各 section，检查 NS owner 与 glue owner |
| 设置时序 | 分别记录接收、排队、发出时间；使用明确的时延单位 |
| 输出日志 | 每条查询记录 mode、seed、下一跳、响应字节数和耗时 |
| 结束实验 | 按查询数、时间窗或控制信号结束并刷出日志 |

- NXNS 类端点分别处理 apex NS、触发查询和 NS 地址查询；检查 referral 的 AUTHORITY 与 ADDITIONAL。
- TsuKing 类端点按实际源地址读取路由，分别控制 NS 名称生成与 glue 地址。
- TuDoor 类端点保留基础 NS/SOA 应答，将 FORMERR、空报文、短报文、原始字节和 ICMP 设为独立模式。
- DNSBomb 类端点显式管理等待窗口和响应大小，按时间片记录收到的查询与释放的响应；分别测量请求聚合和报文大小。
- ECS 实验记录 family、source prefix、scope prefix 和 subnet 字节，再检查相同名称在不同 ECS 输入下的聚合与缓存。

UDP 接收与 TCP 长度前缀、重试分别实现。大 RRset 查询先检查 TCP 完整响应，再测 EDNS 大小、TC 和 UDP→TCP 回退。特殊标签保存 wire bytes，并检查 YAML、zone parser、DNS 编码各层的转义结果。

通用报文生成接口可定位 `examples/app/error/test_custom.yml` 与 `examples/app/error/custom_packets.py` 的函数，将所需生成函数作为项目探测输入。

<a id="response-contract"></a>

### 用响应表连接协议输入与后续查询

为每个端点列出匹配顺序，并单独列出未匹配来源、名称和 QTYPE 的处理。将每行关联到日志字段与一个直接查询用例：

| 输入条件 | 响应内容 | 后续检查 |
| --- | --- | --- |
| 当前权威区 apex 的 NS/SOA | NOERROR，正常权威应答的 AA=1、RA=0，ANSWER 为所问 RRset | zone 已加载，返回可达的权威名称 |
| 需要继续委派的名称 | NOERROR、空 ANSWER，AUTHORITY 中为委派 owner 的 NS；普通 referral 使用 AA=0、RA=0 | 解析器查询下一权威，或解析 NS 的 A/AAAA |
| NS 地址查询有数据 | 相应 A/AAAA；按需要另设 CNAME 分支 | owner、地址、别名链尾与服务一致 |
| 名称存在但所问类型不存在 | NOERROR、空 ANSWER，按区提供 SOA | 记录 NODATA 与该 QTYPE 的负缓存 |
| 名称不存在 | NXDOMAIN，按区提供 SOA | 记录名称负缓存及后续查询的变化 |
| 来源不在该模式的路由中 | 项目选定的明确响应，例如 REFUSED，日志写出 unmapped-source | 修正来源或映射后重试，核对是否恢复预期路径 |

先处理特定名称/类型，再处理范围较大的后缀规则。基础就绪查询与实验分支分别匹配；使用相同查询名称时记录状态变化和缓存准备。

下面只构造普通 IN 类 referral，可嵌入项目端点的对应分支。`cut` 和 `targets` 使用 FQDN，`addresses` 为 NS 名称到地址列表的映射；空映射表示省略地址记录：

```python
import ipaddress
import dns.flags
import dns.message
import dns.name
import dns.rdataclass
import dns.rrset


def make_referral(query, cut, targets, addresses, ttl=60):
    cut = dns.name.from_text(cut, origin=None)
    targets = [dns.name.from_text(name, origin=None) for name in targets]
    if not cut.is_absolute() or not targets or any(not name.is_absolute() for name in targets):
        raise ValueError('Use an absolute cut and nonempty NS targets')
    if len(targets) != len(set(targets)):
        raise ValueError('Duplicate NS target')
    if len(query.question) != 1 or query.question[0].rdclass != dns.rdataclass.IN:
        raise ValueError('Expected one IN question')
    if not query.question[0].name.is_subdomain(cut):
        raise ValueError('Question is outside the delegated name')
    reply = dns.message.make_response(query)
    reply.flags &= ~(dns.flags.AA | dns.flags.RA | dns.flags.AD)
    reply.authority.append(dns.rrset.from_text(cut, ttl, 'IN', 'NS', *(name.to_text() for name in targets)))
    for owner, values in addresses.items():
        owner = dns.name.from_text(owner, origin=None)
        if owner not in targets:
            raise ValueError('Address owner is not an NS target')
        addresses_by_family = [ipaddress.ip_address(value) for value in values]
        for kind, version in (('A', 4), ('AAAA', 6)):
            values = [str(value) for value in addresses_by_family if value.version == version]
            if values:
                reply.additional.append(dns.rrset.from_text(owner, ttl, 'IN', kind, *values))
    return reply
```

该片段保留请求 ID、QUESTION 和 RD；将特殊 flags/RCODE 作为其他明确的响应模式。按父区、委派 owner 和 NS 名称关系检查地址的 bailiwick，观察解析器是否采用 ADDITIONAL 或另发地址查询。

序列化 UDP 响应时按请求的 EDNS payload 和服务上限选择大小，记录 TC；TCP 使用两字节长度前缀并循环读取完整帧。先确认完整 DNS 消息可在 65535 字节内编码，再测试 UDP 截断与 TCP 回退。输入记录数量、去重后的 RR 数和实际 wire 长度分别保存。

## 6. 网络、挂载与抓包

- 使用项目 bridge 中的服务名发起容器内查询；需要宿主访问时配置 `127.0.0.1:<host-port>:<container-port>`。
- 使用 `cap_add: [NET_RAW]` 配置 raw socket；修改路由、MTU 或 netem 时配置所需的 NET_ADMIN。为运行文件设置实际 daemon UID/GID 的权限。
- 在目标服务容器或共享其 network namespace 的观测容器采集单播流量。使用 host network 时，先确认 Docker 平台上的实际接口与源地址。
- 常规 DNS 抓包覆盖 UDP/TCP 53；分片实验按服务地址与 `ip proto 17` 采集，使后续分片进入 pcap。分析时记录 IPID、offset、MF、UDP 校验和及重组结果。
- 同时为采集设置包数与总时长；结束时发送终止信号、等待进程退出并保存文件。
- 将 cache、journal、控制文件和采集输出放在适当的可写目录。通过最终 Compose 确认共享目录与复制快照的位置。

### 固定项目网络的出站路径

Docker bridge 默认可经 NAT 出网。需要仅使用项目内部网络时，在最终 Compose 设置 `internal`：

```yaml
auto:
  post: |
    import yaml
    from dnsbuilder.io import DNSBPath
    path = DNSBPath(output_dir) / 'docker-compose.yml'
    compose = yaml.safe_load(fs.read_text(path))
    compose['networks']['app_net']['internal'] = True
    fs.write_text(path, yaml.safe_dump(compose, sort_keys=False))
```

该设置作用于 app_net；同时检查服务使用的其他网络、network_mode 和端口。镜像准备由宿主 Docker daemon 完成。在该 post 后导出拓扑清单，记录最终网络配置。

<a id="diagnostics"></a>

## 7. 按失败阶段定位问题

先保存失败命令和首个根因，再修改该阶段的输入并重跑同一检查：

| 现象 | 检查与修正 | 重查方式 |
| --- | --- | --- |
| `inet Field required` 或出现 Compose 的 services 输入 | 用 `name/inet/images/builds` 编写 dnsb 配置；检查传给 CLI 的文件 | 重新运行 dnsb build，核对服务名 |
| 动态节点缺失或 behavior 为空 | 查看 setup/ref 顺序、实例的 `build: true`、实例 vars 和最终合并配置 | 比较角色清单与 Compose 服务集合 |
| 占位符未解析、地址为 none、来源落入默认分支 | setup 创建节点与占位符，modify 输出 IP 表；从角色表检查映射覆盖 | 对照实际地址，从每个预期来源查询端点 |
| 多个服务出现 barrier 错误 | 找到最先失败的服务与 hook；检查文件路径、依赖、签名 stderr；服务等待上限为 30 秒 | 修正根因，将耗时材料准备移到签名前，再构建 |
| build 返回成功但签名/修改缺失 | 检查签名日志、最终 RRset、DS/根锚和预期 hook 产物 | 执行 zone 检查、记录关联检查与正常验证查询 |
| 宿主脚本或容器缺少模块/工具 | 宿主生成器用项目 Python 环境；端点依赖安装到其镜像；分别预检签名工具 | 在实际执行环境检查 import、工具版本与工作目录 |
| Docker API 不可用 | 用 `docker info` 检查 daemon/连接；保留已完成的静态结果 | 恢复 daemon 后重跑运行阶段，未执行项为 not_run |
| Compose 校验失败或 daemon 退出 | 检查额外字段、environment 标量、entrypoint/argv、Section、UID/GID；在目标镜像执行配置检查器 | Compose config、软件检查器、启动日志、SOA 查询 |
| Python 报 shell 变量未定义 | 用 argv 或环境变量传入 compose、工作目录和输出路径 | 单独运行验证脚本并检查非零退出码 |
| 权威查询超时 | 检查监听地址、端口、ACL、zone 加载、UDP/TCP，先查基础 SOA | 同一网络中的直接查询与抓包 |
| resolver SERVFAIL 或链中断 | 从最后可见查询检查 referral owner、NS 地址、RD、缓存、DS/根锚与重试 | 正常对照、逐边探测、递归器出站路径 |
| 委派层被跳过或别名链只查一次 | 检查同一权威上的最长 zone 匹配，以及响应内携带的完整 CNAME 链 | 调整区/服务分布后，统计实际遍历层级 |
| 改资源后仍返回旧值 | 从 Compose 定位复制快照或目录挂载，检查 reload、journal 与递归缓存 | 先直接权威查询，再按缓存条件查递归器 |
| 大 RRset 导致超时或截断 | 检查编码大小、EDNS、TC、TCP 服务和完整帧读取 | 分别测试小集合、完整 TCP、UDP 回退 |

运行报告每次初始化；命令、查询、机制和清理各自记录实际结果。单次超时先进入上表的连接、协议、路径或验证分支，再由对应观测确定原因。
