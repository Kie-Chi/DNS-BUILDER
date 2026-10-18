# 动态拓扑、委派与下一跳

先用服务名和有类型的边描述关系，再生成配置与地址表。分别维护服务连接图、DNS 名称依赖图和动态响应路由表。

## 1. 用边表生成查询链

以下配置用 `vars.links` 声明 `entry → upstream → auth`：

```yaml
name: graph-teaching
inet: 10.89.0.0/24
images:
  resolver-image:
    ref: unbound:1.19.0
  auth-image:
    ref: bind:9.18.4
vars:
  links:
    entry:
      kind: forward
      zone: example.com
      targets: [upstream]
    upstream:
      kind: stub
      zone: example.com
      targets: [auth]
builds:
  resolver-template:
    image: resolver-image
    ref: std:recursor
    build: false
  auth:
    image: auth-image
    ref: std:auth
    behavior: example.com master www A 192.0.2.10
auto:
  setup: |
    links = config['vars']['links']
    builds = config['builds']
    for name, edge in links.items():
      if name in builds:
        raise ValueError(f'Duplicate node: {name}')
      targets = edge['targets']
      if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets):
        raise ValueError(f'Invalid targets: {name}')
      if edge['kind'] not in {'forward', 'stub'}:
        raise ValueError(f'Unsupported next-hop kind: {name}')
      builds[name] = {'ref': 'resolver-template', 'build': True}
    for name, edge in links.items():
      targets = edge['targets']
      if any(target not in builds or not builds[target].get('build', True) for target in targets):
        raise ValueError(f'Missing next hop: {name}')
      builds[name]['behavior'] = f'{edge["zone"]} {edge["kind"]} {",".join(targets)}'
  restrict: |
    expected = set(config['vars']['links']) | {'auth'}
    if not expected.issubset(config['builds']):
      raise ValueError('Topology nodes are missing')
    result = 'PASS'
```

从文件读取边表时，在 setup 使用 `json.loads(fs.read_text(workdir / 'resource' / 'topology.json'))`。先创建全部节点，再检查目标存在并填写行为，以支持前向引用。

| 边类型 | 配置位置 | 观测内容 |
| --- | --- | --- |
| hint | 递归器根提示 | 根查询目的地址 |
| forward | 下游解析器 | 上游查询的 RD、回退和重试 |
| stub | 递归器的指定区 | 发往该区权威的查询 |
| delegation | 父区 NS RRset | referral 中的 owner、NS 和 glue |
| NS address | NS 名称所属区 | 解析 NS 地址产生的 A/AAAA 查询 |
| CNAME | 别名 owner 所属区 | 下一次查询的名称及类型 |

多个 forward/stub targets 构成候选上游集合。通过日志或 pcap 确认实现的选择、并发与重试策略。

## 2. 动态生成权威区

合并到 [configuration.md](configuration.md) 的单区配置，将两个标签展开为独立服务：

```yaml
vars:
  labels: [alpha, beta]
auto:
  setup: |
    builds = config['builds']
    parent = builds['auth']
    lines = [parent.get('behavior', '').rstrip()]
    for label in config['vars']['labels']:
      name = f'auth-{label}'
      if name in builds:
        raise ValueError(f'Duplicate service: {name}')
      lines.append(f'example.com master {label} NS {name}')
      builds[name] = {
        'image': 'auth-image',
        'ref': 'std:auth',
        'behavior': f'{label}.example.com master www A 192.0.2.10',
      }
    parent['behavior'] = '\n'.join(lines).strip()
```

将区域列表、节点数量和分层关系放在 vars 或拓扑文件。使用 `'\n'.join(...)` 连接完整行为行。为服务名、zone origin、委派 owner 和 NS 主机名分别设字段。

<a id="delegation"></a>

## 3. 显式 NS 名称与 glue

需要区内 NS 时，分别填写父区的委派和 glue：

```yaml
builds:
  auth:
    image: auth-image
    ref: std:auth
    behavior: |
      example.com master child NS ns.child.example.com.
      example.com master ns.child A ${srv.child-auth.ip}
  child-auth:
    image: auth-image
    ref: std:auth
    behavior: child.example.com master www A 192.0.2.10
```

- `NS child-auth` 会生成 `child-auth.servers.net.` 和地址记录；`NS ns.child.example.com.` 保留指定名称，glue 由单独的 A/AAAA 行提供。
- 区外 NS 的地址在其名称所属权威区提供。为该支撑区配置独立委派或 stub，并查询 NS 名称验证路径。
- 复现缺失 glue 或不存在 NS 名称的场景时，使用显式 FQDN，按输入配置该名称的 NXDOMAIN、NODATA 或下一层 referral。
- 查询父区确认委派，查询子区确认 apex NS/SOA。生成器会为每区添加 `<service>.servers.net.` apex NS；需要精确控制该 RRset 时，使用 [zone-mutation.md](zone-mutation.md#custom-zone) 中的自定义 zone 发布方式。

## 4. 编译地址与名称

- 在 setup 写入 `${srv.<service>.ip}`，由 IP 规划后的替换阶段解析。
- 在 modify 读取已解析值并序列化。将占位符放在映射的值中，待替换完成后再生成以 IP 为键的字典。
- 给每个分层节点保存 `layer`、`index`、`role` 和下一跳服务列表；按这些字段生成连接，而非按 IP 尾段推算。
- 使用固定排序或显式 seed 生成名称。检查每个标签的长度、完整域名长度和不同分支的名称唯一性。
- 为链尾定义明确的响应服务与模式；把环表示为显式边，并设置查询次数、重试和采集时长。

## 5. 导出实际地址与边

在全局 post 从最终 Compose 生成拓扑清单：

```yaml
auto:
  post: |
    import json
    import yaml
    from dnsbuilder.io import DNSBPath
    base = DNSBPath(output_dir)
    compose = yaml.safe_load(fs.read_text(base / 'docker-compose.yml'))
    nodes = {}
    for name, service in compose['services'].items():
      if name.startswith('dnsb-image-builder-'):
        continue
      network = service.get('networks', {}).get('app_net', {})
      nodes[name] = {
        'ipv4_address': network.get('ipv4_address'),
        'image': service.get('image'),
      }
    data = {'schema_version': 1, 'nodes': nodes, 'links': config['vars']['links']}
    fs.write_text(base / 'topology.json', json.dumps(data, indent=2, sort_keys=True) + '\n')
```

将清单中的地址与 pcap 的源/目的地址关联，分别标记解析器、权威、名称支撑服务和观测服务。依据实际查询确认每条边的流量。

<a id="layers"></a>

## 6. 批量生成入口与出口实例

以下片段读取组名与每组出口数，使用已有 `auth`、`resolver-image`。需要其他分层关系时，替换 groups/targets 数据并保留显式实例开关：

```yaml
vars:
  groups: [blue, green]
  egress_per_group: 2
builds:
  ingress-template:
    image: resolver-image
    ref: std:forwarder
    build: false
  egress-template:
    image: resolver-image
    ref: std:recursor
    build: false
auto:
  setup: |
    builds = config['builds']
    width = int(config['vars']['egress_per_group'])
    if width < 1:
      raise ValueError('Egress count must be positive')
    for group in config['vars']['groups']:
      targets = [f'egress-{group}-{index}' for index in range(width)]
      for name in targets:
        if name in builds:
          raise ValueError(f'Duplicate node: {name}')
        builds[name] = {
          'ref': 'egress-template', 'build': True,
          'behavior': 'example.com stub auth',
        }
      name = f'ingress-{group}'
      if name in builds:
        raise ValueError(f'Duplicate node: {name}')
      builds[name] = {
        'ref': 'ingress-template', 'build': True,
        'behavior': f'. forward {",".join(targets)}',
      }
```

在全局 setup 直接填充实例字段；需要服务 setup 时，将脚本及使用的 vars 同时放到新实例。按最终 Compose 检查实例数量、每组出口数量和 forward 目标。

<a id="source-routing"></a>

## 7. 生成按查询来源选择下一跳的配置

TsuKing 类端点需要区分发来查询的出口解析器。用服务名保存路由，在 modify 将其编译为 `源 IP → 下一跳 IP 列表`。以下片段输出路由文件，供项目端点读取：

```yaml
vars:
  route_sources: [resolver]
  endpoint_routes:
    resolver: [auth]
builds:
  endpoint:
    image: tool-image
    command: tail -f /dev/null
    auto:
      modify: |
        import ipaddress
        import json
        routes = {}
        for row in config['vars']['resolved_routes']:
          source = str(ipaddress.ip_address(row['source']))
          targets = [str(ipaddress.ip_address(value)) for value in row['targets']]
          if source in routes or not targets:
            raise ValueError('Duplicate source or empty next-hop list')
          routes[source] = targets
        config.setdefault('files', {})['/usr/local/etc/routes.json'] = json.dumps(routes, sort_keys=True) + '\n'
auto:
  setup: |
    builds = config['builds']
    rows = []
    expected = config['vars']['route_sources']
    routes = config['vars']['endpoint_routes']
    if len(expected) != len(set(expected)) or set(routes) != set(expected):
      raise ValueError('Route source coverage mismatch')
    for source, targets in routes.items():
      if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)):
        raise ValueError('Use a nonempty list of distinct route targets')
      if any(name not in builds or not builds[name].get('build', True) for name in [source, *targets]):
        raise ValueError('Route references an unavailable service')
      rows.append({
        'source': f'${{srv.{source}.ip}}',
        'targets': [f'${{srv.{target}.ip}}' for target in targets],
      })
    builds['endpoint'].setdefault('vars', {})['resolved_routes'] = rows
```

`route_sources` 从节点角色表独立派生，列出所有预期查询来源；与 `endpoint_routes` 一起填写。将端点的 `command` 改为项目响应程序，读取路由文件，并使用接收到的源地址查表。日志记录 `source_ip/qname/qtype/next_hops`；使用不同出口分别查询，检查返回的 NS/glue 与路由表一致。host network、NAT 或代理场景下，以实际接收地址建立映射。

<a id="fanout"></a>

## 8. 用显式名称生成委派扇出

为 `vars.delegation` 提供 `parent_zone`、`child_label` 和 `ns_names`，将片段合并到拥有该父区的 `auth`。`ns_names` 使用不同的完整域名：

```yaml
auto:
  setup: |
    import dns.name
    spec = config['vars']['delegation']
    names = spec['ns_names']
    parsed_names = [dns.name.from_text(name, origin=None) for name in names]
    if not names or len(set(parsed_names)) != len(names) or any(not name.is_absolute() for name in parsed_names):
      raise ValueError('Use distinct absolute NS names')
    auth = config['builds']['auth']
    lines = [auth.get('behavior', '').rstrip()]
    lines.extend(
      f'{spec["parent_zone"]} master {spec["child_label"]} NS {name}'
      for name in names
    )
    auth['behavior'] = '\n'.join(lines).strip()
```

逐层委派时，为每层生成独立的 parent/child/NS 记录数据，并为下一层 zone 配置对应服务。将“NS 名称需要继续解析”和“NS 地址直接访问下一层”分别表达为名称依赖与地址映射。

组合深层委派、扇出和别名时，分别设置委派深度、每层 NS 数量、CNAME 长度和 NS 名称的标签深度。逐层直接查询父区与名称支撑区，再经递归器统计实际出站查询。组合方法见 [example-patterns.md](example-patterns.md#camp)。

<a id="flow-check"></a>

## 9. 按角色检查具名查询路径

为本次路径单独准备 `roles={服务名: 逻辑角色}`、`edges={服务名: 下一跳列表}`、入口和终端集合。将控制端点的决策展开为逻辑边：例如组内的入口→出口来自 forward 配置，出口→下一组入口来自响应路由表。权威的控制查询另行观测。

以下函数适用于应当结束的无环路径，放入项目校验脚本或节点生成后的 setup 脚本。`allowed_steps` 由项目提供角色对，适配转发、递归、权威或接收端等不同组合：

```python
def check_acyclic_flow(roles, edges, entry, terminals, allowed_steps):
    nodes, terminals = set(roles), set(terminals)
    allowed_steps = {tuple(step) for step in allowed_steps}
    if entry not in nodes or not terminals or not terminals <= nodes or set(edges) - nodes:
        raise ValueError('Invalid entry, terminal, or edge source')
    for source in nodes:
        targets = edges.get(source, [])
        if not isinstance(targets, list) or len(targets) != len(set(targets)):
            raise ValueError(f'Invalid target list: {source}')
        if source in terminals:
            if targets:
                raise ValueError(f'Terminal has outgoing edges: {source}')
        elif not targets:
            raise ValueError(f'Missing next hop: {source}')
        for target in targets:
            if target not in nodes or (roles[source], roles[target]) not in allowed_steps:
                raise ValueError(f'Invalid role transition: {source} -> {target}')
    visited, active = set(), set()
    def visit(source):
        if source in active:
            raise ValueError(f'Unexpected cycle: {source}')
        if source in visited:
            return
        active.add(source)
        for target in edges.get(source, []):
            visit(target)
        active.remove(source)
        visited.add(source)
    visit(entry)
    if visited != nodes:
        raise ValueError(f'Unreachable nodes: {sorted(nodes - visited)}')
    return sorted(visited)
```

- 将该检查视图中的节点限定为本次预期路径；分别验证多个入口与不同模式。
- 从角色表派生全部出口，再检查 `route_sources` 与路由键一致。生成 IP 路由后逐项对照 Compose；服务重排和换子网后重做检查。
- 为未知来源单独定义响应与日志，例如记录 unmapped-source 并返回 REFUSED；探测入口需要默认行为时，明确区分探测来源和出口来源。
- 循环类实验改为核对显式声明的环成员和回边，分别统计进入环、重复路径及退出/截止条件。
- 静态边表描述候选路径；运行时依据时间、QNAME/QTYPE、源/目的服务重建实际路径，统计重试与分支选择。

<a id="resolution-plan"></a>

## 10. 让名称引用随参数一起变化

分别给链长、标签深度、分支数和出口数命名。先生成委派/别名的引用清单，再从清单派生名称支撑数据。链位置用链长遍历，标签用标签深度遍历；用 `length=2, depth=3` 和交换后的参数检查两者独立。

在名称已解析为 FQDN 后，对每个预期查询检查正向路径或预设负响应。`required/positive/negative` 均为 `(owner, qtype)` 列表；positive 表示可得到相应类型数据的路径，包含已经规划的别名追踪，negative 表示预设的 NXDOMAIN/NODATA 等终止响应：

```python
import dns.name
import dns.rdatatype


def check_resolution_plan(required, positive, negative):
    def normalize(rows):
        result = set()
        for owner, qtype in rows:
            name = dns.name.from_text(owner, origin=None)
            if not name.is_absolute():
                raise ValueError(f'Use an absolute owner: {owner}')
            result.add((name.canonicalize(), dns.rdatatype.from_text(qtype)))
        return result
    required, positive, negative = map(normalize, (required, positive, negative))
    if positive & negative:
        raise ValueError('Conflicting response plans')
    if required - positive - negative:
        raise ValueError('Missing resolution paths')
```

A 与 AAAA 分别列出；将计划中的负响应与遗漏的地址路径区分开。同名 A 正向与 AAAA NODATA 可以并存，NXDOMAIN 则是名称级结果，需检查与同名正向数据的一致性。用 [响应表](runtime.md#response-contract) 为同一清单逐项发送查询，检查实际 owner、RCODE、SOA 和后续查询。

对层层委派检查 `parent origin → child owner → NS 名称 → 地址所属区 → 下一层服务`。普通权威会选择其承载 zone 中与查询名称最长匹配的一项；逐层遍历时，将路径上的嵌套 zone 分到相应权威实例，防止直接选中更深的 zone。别名链同样检查是否被权威一次性打包返回。

源码定位：`src/dnsbuilder/auto/manager.py` 的 `AutomationManager.setup`；`src/dnsbuilder/abstractions.py` 的 `MasterBehavior.generate`；`src/dnsbuilder/builder/net.py` 的 `NetworkManager`；`src/dnsbuilder/builder/substitute.py` 的 `VariableSubstitutor`。
