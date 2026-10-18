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

## 7. 定位运行问题

| 现象 | 检查与操作 |
| --- | --- |
| 构建失败 | 查看 include/ref、资源路径、变量替换、网络容量和日志中的首个服务错误 |
| Compose 校验失败 | 检查额外字段、environment 标量、挂载目标与 entrypoint/command |
| daemon 退出 | 在目标镜像中运行配置检查器，检查 UID/GID、区文件语法和启动日志 |
| 权威查询超时 | 检查监听地址、端口、ACL、TCP/UDP 和 zone 加载状态 |
| resolver SERVFAIL | 分别查询 referral、NS 地址、父区 DS 与根锚，关联实际查询路径 |
| 修改后仍返回旧值 | 检查复制后的挂载源、reload、journal 与递归缓存 |
| 放大链在中途结束 | 检查该层 QNAME/QTYPE、缓存命中、NS 可达性、重试与 fetch 参数 |
| DNSSEC 响应过大 | 分别检查 UDP 长度、TC、TCP 服务和完整 RRset 的传输 |
