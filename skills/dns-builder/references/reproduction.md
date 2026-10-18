# 构建、查询与结果验证

将实验参数、配置生成、报文检查和指标采集连接为可重复执行的验证入口。

## 1. 填写参数与查询条件

| 项目 | 填写内容 |
| --- | --- |
| 软件 | 实现、版本、补丁、镜像平台、启动方式 |
| 角色 | 解析器、转发器、权威、响应端点、客户端、接收端、观测服务 |
| 关系 | hint/forward/stub、父子委派、NS 名称解析、CNAME 依赖 |
| 状态 | validation、QMIN、缓存、重试、并发、运行时间 |
| 查询 | QNAME/QTYPE、RD/CD/DO、EDNS、UDP/TCP、次数与间隔 |
| 响应 | RCODE、AA/RA/AD/TC、各 section 的 owner/type/TTL、glue 与签名 |
| 指标 | 查询数、字节数、延迟、CPU、缓存条目、验证结果 |

从论文或 PoC 填写目标参数，保留对应出处。将深度、宽度、链长、时延和记录数量放入 vars 或独立数据文件。

## 2. 编写验证入口

在项目根目录提供 `verify.sh` 或 `verify.py`，按以下次序执行：

1. **构建**：运行 dnsb，保存构建日志，确认生成的 Compose 路径。
2. **静态检查**：解析 Compose，检查镜像、服务、挂载、软件配置、zone、下一跳和信任锚。
3. **启动与就绪**：启动项目服务，按次数和时间上限查询 SOA/正常名称；使用独立就绪名称或在正式查询前准备缓存。
4. **直接端点检查**：向权威或响应端点发送规定查询，检查各 section、记录数量、owner、glue、DNSSEC 和 transport。
5. **递归触发**：向真实解析器发出实验查询，同时采集端点日志、解析器日志和 pcap。
6. **指标与对照**：以相同版本、缓存和时间条件比较正常与修改后输入，记录目标路径和指标。
7. **保存与清理**：保存容器日志、原始报文和结果，停止采集进程，再清理本项目并记录退出状态。

SOA、DNSKEY、DS 和 NS 地址查询分别检查；涉及大响应时分别测试 TCP 完整数据与 UDP 截断/回退。循环实验按 `(qname, qtype, upstream)` 记录重复路径。

## 3. 记录 DNS 查询结果

下面的片段可放入项目查询工具；`resolver_ip` 从本项目配置获取：

```python
import json
import time
import dns.flags
import dns.message
import dns.query
import dns.rcode

query = dns.message.make_query('www.example.com', 'A', want_dnssec=True)
started = time.perf_counter()
response = dns.query.udp(query, resolver_ip, timeout=3)
counts = {
    name: sum(len(rrset) for rrset in getattr(response, name))
    for name in ('answer', 'authority', 'additional')
}
print(json.dumps({
    'rcode': dns.rcode.to_text(response.rcode()),
    'ad': bool(response.flags & dns.flags.AD),
    'tc': bool(response.flags & dns.flags.TC),
    'query_bytes': len(query.to_wire()),
    'response_bytes': len(response.to_wire()),
    'latency_seconds': time.perf_counter() - started,
    'rr_counts': counts,
}, sort_keys=True))
```

将 timeout、socket 错误与 DNS RCODE 分别记录。`len(section)` 表示 RRset 数，`sum(len(rrset) ...)` 表示 RR 数；OPT/TSIG 单独处理。上述字节值来自重新编码的 DNS payload，精确传输长度从原始 wire 或 pcap 获取。

## 4. 计算目标指标

- **查询放大**：统计指定时间窗内客户端触发查询与解析器实际出站查询。按权威、名称支撑服务、链层和 QTYPE 分组。
- **字节放大**：分别记录 DNS payload 与网络层字节，区分 UDP、TCP、重传和分片。
- **DNSSEC 开销**：记录真实解析器 CPU 时间、内存、延迟、验证日志以及最终 DNSKEY/RRSIG/DS 数量。
- **缓存变化**：记录查询前后缓存项、剩余 TTL、实际权威回访，以及 normal/CD、cold/warm 状态。
- **时序释放**：按固定时间片记录输入、等待中查询与输出峰值，同时保存端点排队/发送时刻。

使用同一计数口径比较单个机制与组合机制。将基础服务流量与目标接收端流量单列；按照实际请求计算结果。测量方法见 [evaluation.md](evaluation.md)。

## 5. 保存验证结果

用 JSON serializer 根据执行结果生成报告：

| 字段 | 内容 |
| --- | --- |
| `status` | `pass`：检查已通过；`fail`：检查失败；`not_run`：依赖不足或该项未执行 |
| `commands` | argv、exit code、duration、stdout/stderr、超时状态 |
| `checks` | 静态、就绪、端点、查询路径、指标、清理的 expected/observed |
| `metrics` | 指标定义、原始样本与计算值；缺失值使用 null |
| `environment` | image ID/digest、软件与签名工具版本、网络、缓存和时间窗 |
| `artifacts` | 配置、资源、zone、pcap、日志与 manifest 路径 |

将清理命令执行结果写入报告，失败时同样保存日志。重跑验证入口，检查配置、运行路径和目标指标的一致性。

## 6. 保存文件清单并重建

`skill_dir` 指本 skill 的实际安装目录。在实验目录执行：

```bash
python3 "$skill_dir/scripts/manifest.py" --root . --out run/source-manifest.json --ignore 'output/*' --ignore 'run/*'
python3 "$skill_dir/scripts/manifest.py" --root output/basic --out run/build-manifest.json
python3 "$skill_dir/scripts/measure_command.py" --out run/query-event.json --label normal-query --log-dir run/logs -- docker compose -f output/basic/docker-compose.yml exec -T client dig +time=3 +tries=1 @resolver www.example.com A
```

源码清单包含配置、拓扑数据、脚本、记录材料和依赖；生成物清单包含 Compose、Dockerfiles、最终 zone/config 和挂载快照。

当前 `--output-dir` 指定输出基目录，CLI 在其下追加 `output/<name>`。例如 `--output-dir run/generated` 的 Compose 位于 `run/generated/output/<name>/docker-compose.yml`；hooks 使用注入的 `output_dir`。

重新构建前保存当前输出和运行日志；Builder 会清理本次输出目录。使用同一输入再次构建并运行验证。比较语义结果，同时记录动态 SOA serial、密钥、签名时间与有效期。复用镜像缓存时记录缓存状态；验证迁移性时单独检查依赖构建与镜像平台。
