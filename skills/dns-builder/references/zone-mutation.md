# Zone 与 RRset 修改

按“修改的数据接下来是否需要签名”选择 hook，用 `(origin, owner, class, type, covers)` 定位 RRset。将记录材料放入 `resource/records/`，将生成文件的修改放入对应构建阶段。

## 1. 选择修改位置

| 操作 | 位置 | 后续处理 |
| --- | --- | --- |
| 添加将正常签名的记录或 DNSKEY | `dnssec.hooks.pre` | 首签使用修改后的 unsigned；父区重签再次使用该文件 |
| 调整下一层父区将读取的 DS | 子区 `dnssec.hooks.mid` | 父区收集 DS 并签名 |
| 调整父区待签的 DS/普通 RR | 父区 unsigned，在父区重签前完成 | 重签覆盖最终 signed 文件 |
| 改最终 RRset、RRSIG 或保留旧签名 | `dnssec.hooks.post` | 挂载复制读取修改后的最终文件 |
| 修改已复制的普通配置或 zone | `auto.post` | 使用实际 `output_dir`，随后检查加载结果 |
| 修改正在运行的权威 | 实际挂载文件 + reload | 直接权威查询确认，然后检查递归缓存 |

每个 DNSSEC hook 接收当前服务 `config`、`zone`、`service_name`、`fs` 和 `workdir`；mid/post 还接收 `zone_graph`。同一服务管理多个 zone 时，使用 origin 条件限定修改对象。

### 为记录材料填写输入与预期

| 材料 | 输入检查 | 发布后的检查 |
| --- | --- | --- |
| DNSKEY | 显式 apex FQDN、TTL、flags/protocol/algorithm、公钥编码、去重后的数量 | 与实际签名公钥取并集后的数量、候选分组、RRSIG(DNSKEY) |
| RRSIG | owner/type covered、signer、tag/algorithm、labels、original TTL、有效期 | 目标 RRset 与覆盖签名关联，明确保留、追加或替换哪些签名 |
| DS | 子区 owner、tag/algorithm、digest type/内容、数量 | 父区实际发布集合与 RRSIG(DS)，以及更上一层的 DS |

片段中的材料文件使用完整 FQDN；先以根 origin 解析，再检查唯一的目标 RRset，使混入其他区的记录也进入输入检查。最终整区文件仍按实际 zone origin 解析。

在项目参数中定义预期字段和数量，依次比较生成材料、hook 输入、最终挂载文件及实际报文。用 [记录关联检查](dnssec.md#signature-links) 定位不匹配字段，再用正常签名验证与运行查询定位失败阶段。

## 2. pre：添加随后签名的记录

在拥有 example.com 的 `auth` 服务追加 TXT：

```yaml
builds:
  auth:
    dnssec:
      enable: true
      hooks:
        pre: |
          if zone.fqdn == 'example.com.':
            from dnsbuilder.io import DNSBPath
            path = DNSBPath(f'temp:/services/{service_name}/zones/{zone.filename}.unsigned')
            content = fs.read_text(path)
            marker = 'teaching-note'
            if marker in content:
              raise ValueError('The teaching record already exists')
            record = f'{marker}.{zone.fqdn} 300 IN TXT "before-signing"'
            fs.write_text(path, content + '\n' + record + '\n')
```

使用完整 owner、TTL、class 和 type 写入独立 RR。添加新 owner 或类型后，由 signer 生成对应 RRSIG 和 NSEC3 数据。

## 3. mid：替换子区 DS 输入

将项目准备的 `resource/records/<zone>.ds` 写入实际子区 key 路径：

```yaml
builds:
  auth:
    dnssec:
      hooks:
        mid: |
          if zone.fqdn == 'example.com.':
            import dns.rdatatype
            import dns.zone
            from dnsbuilder.io import DNSBPath
            source = workdir / 'resource' / 'records' / f'{zone.label}.ds'
            text = fs.read_text(source)
            parsed = dns.zone.from_text(text, origin='.', relativize=False, check_origin=False)
            if parsed.get_rdataset(zone.fqdn, dns.rdatatype.DS) is None or len(list(parsed.iterate_rdatasets())) != 1:
              raise ValueError('Expected one DS RRset at the expected child apex')
            destination = DNSBPath(f'key:/{service_name}/{zone.label}.ds')
            fs.write_text(destination, text)
```

DS 的 owner 是子区名，DS RRset 由父区发布和签名。检查父区最终的 DS 数量、tag、algorithm、digest type 和 digest。

叶区的 DS 会直接进入父区；拥有子区的中间区会在重签后更新自己的 DS。按照 `zone_graph` 确定输入被读取和重新生成的顺序。需要让父区签名覆盖特定 DS 集合时，在重签前准备父区 unsigned/子区 DS；需要保留旧 RRSIG 的 DS 失配时，在最终父区 post 修改。

## 4. post：替换数据并保留覆盖签名

下面将已签名的 `www.example.com A` 改为另一地址，保留原有 `RRSIG(A)`，并保存修改记录：

```yaml
builds:
  auth:
    vars:
      replacement_address: 192.0.2.20
    dnssec:
      enable: true
      hooks:
        post: |
          if zone.fqdn == 'example.com.':
            import hashlib
            import json
            import dns.rdatatype
            import dns.rdataset
            import dns.zone
            from dnsbuilder.io import DNSBPath
            path = DNSBPath(f'temp:/services/{service_name}/zones/{zone.filename}')
            before = fs.read_text(path)
            parsed = dns.zone.from_text(before, origin=zone.fqdn, relativize=False)
            owner = f'www.{zone.fqdn}'
            original = parsed.get_rdataset(owner, dns.rdatatype.A)
            signature = parsed.get_rdataset(owner, dns.rdatatype.RRSIG, dns.rdatatype.A)
            if original is None or signature is None:
              raise ValueError('The signed A RRset is missing')
            previous = original.to_text()
            signature_before = signature.to_text()
            replacement = dns.rdataset.from_text('IN', 'A', original.ttl, config['vars']['replacement_address'])
            if original == replacement:
              raise ValueError('The replacement does not change the RRset')
            parsed.replace_rdataset(owner, replacement)
            after = parsed.to_text(relativize=False)
            reloaded = dns.zone.from_text(after, origin=zone.fqdn, relativize=False)
            kept = reloaded.get_rdataset(owner, dns.rdatatype.RRSIG, dns.rdatatype.A)
            if kept is None or kept.to_text() != signature_before:
              raise ValueError('The covering RRSIG changed unexpectedly')
            fs.write_text(path, after)
            report = {
              'zone': zone.fqdn,
              'owner': owner,
              'original_rrset': previous,
              'replacement_rrset': replacement.to_text(),
              'covering_rrsig_unchanged': True,
              'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
              'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
            }
            report_path = DNSBPath(f'temp:/mutations/{service_name}-{zone.label}.json')
            fs.write_text(report_path, json.dumps(report, indent=2) + '\n')
```

使用 DNS parser 处理省略 owner、括号多行、`$ORIGIN` 和 RRSIG。`covers` 区分同一 owner 的 `RRSIG(A)`、`RRSIG(NS)` 等集合。比较解析后的记录语义，并单独保存需要逐字节比较的输入。

`dns.zone` 会按 origin 过滤区外记录。将框架的 `*.servers.net.` 地址放在名称支撑区；包含需要原样保留的区外数据或特殊字节时，使用保留这些记录的解析方式或精确文本编辑。修改 SOA serial 时，同时处理 SOA 的覆盖签名。

### 从最终输出检查修改

全局 auto.post 在挂载复制和 Compose 写出后读取实际产物：

```yaml
auto:
  post: |
    import dns.rdatatype
    import dns.zone
    from dnsbuilder.io import DNSBPath
    base = DNSBPath(output_dir)
    path = base / 'auth' / 'contents' / 'db.example.com'
    parsed = dns.zone.from_text(fs.read_text(path), origin='example.com.', relativize=False)
    changed = parsed.get_rdataset('www.example.com.', dns.rdatatype.A)
    signature = parsed.get_rdataset('www.example.com.', dns.rdatatype.RRSIG, dns.rdatatype.A)
    expected = config['builds']['auth']['vars']['replacement_address']
    if changed is None or {rr.address for rr in changed} != {expected} or signature is None:
      raise ValueError('The final signed-zone mutation is missing')
    report = fs.read_text(DNSBPath('temp:/mutations/auth-example.com.json'))
    fs.write_text(base / 'zone-mutation.json', report)
```

随后执行 `named-checkzone`、直接权威查询、普通递归/CD 对照，并结合 validation 日志检查修改结果。

<a id="dnskey-import"></a>

## 5. pre：导入附加 DNSKEY

为项目生成 `resource/records/additional-dnskeys.rr`，每条记录写出完整 apex owner 与 TTL。将此 pre 片段合并到签名服务；多个 pre 操作合并为一个脚本，按追加顺序执行：

```yaml
builds:
  auth:
    dnssec:
      enable: true
      hooks:
        pre: |
          if zone.fqdn == 'example.com.':
            import dns.rdatatype
            import dns.zone
            from dnsbuilder.io import DNSBPath
            source = workdir / 'resource' / 'records' / 'additional-dnskeys.rr'
            import dns.name
            extra = dns.zone.from_text(fs.read_text(source), origin='.', relativize=False, check_origin=False)
            keys = extra.get_rdataset(zone.fqdn, dns.rdatatype.DNSKEY)
            if keys is None or len(list(extra.iterate_rdatasets())) != 1:
              raise ValueError('Expected one apex DNSKEY RRset')
            if any(key.protocol != 3 for key in keys):
              raise ValueError('Expected DNSKEY protocol 3')
            path = DNSBPath(f'temp:/services/{service_name}/zones/{zone.filename}.unsigned')
            fs.write_text(path, fs.read_text(path) + '\n' + keys.to_text(name=dns.name.from_text(zone.fqdn), relativize=False) + '\n')
```

签名后查询 apex DNSKEY，比较实际候选集合与输入，并检查 `RRSIG(DNSKEY)`。使用 `dns.dnssec.key_id` 分组统计 tag/algorithm；DNSKEY 与目标 RRSIG 的对应关系见 [dnssec.md](dnssec.md#keytrap-records)。

<a id="rrsig-import"></a>

## 6. post：导入目标 RRset 的覆盖签名

将需要发布的完整 RRSIG 记录写入 `resource/records/target-signatures.rr`，保留显式 owner 与 TTL。以下片段替换一个 type covered 的签名集合；其余记录保持原有语义：

```yaml
builds:
  auth:
    vars:
      signature_owner: www.example.com.
      covered_type: A
    dnssec:
      enable: true
      hooks:
        post: |
          if zone.fqdn == 'example.com.':
            import dns.rdatatype
            import dns.zone
            from dnsbuilder.io import DNSBPath
            owner = config['vars']['signature_owner']
            covered = dns.rdatatype.from_text(config['vars']['covered_type'])
            source = workdir / 'resource' / 'records' / 'target-signatures.rr'
            extra = dns.zone.from_text(fs.read_text(source), origin='.', relativize=False, check_origin=False)
            signatures = extra.get_rdataset(owner, dns.rdatatype.RRSIG, covered)
            if signatures is None or len(list(extra.iterate_rdatasets())) != 1:
              raise ValueError('Expected one covering RRSIG RRset at the selected owner')
            path = DNSBPath(f'temp:/services/{service_name}/zones/{zone.filename}')
            parsed = dns.zone.from_text(fs.read_text(path), origin=zone.fqdn, relativize=False)
            if parsed.get_rdataset(owner, covered) is None:
              raise ValueError('The covered RRset is missing')
            parsed.replace_rdataset(owner, signatures)
            fs.write_text(path, parsed.to_text(relativize=False))
```

需要追加时，将现有覆盖签名与输入签名通过 `Rdataset.update` 合并后写回。按实际报文计数；同一 RDATA 的重复文本会合并为同一 RR。将签名有效期、labels、algorithm、key tag、signer 和目标 RRset 分开检查。

<a id="custom-zone"></a>

## 7. 发布精确控制的自定义 zone

控制 apex NS、SOA、zone cut 或外部签名输出时，直接发布项目 zone：

1. 在 `resource/zones/` 生成完整 zone 文件，显式写出 origin、SOA、apex NS 和所需记录。
2. 用 `volumes` 将文件挂到独立容器路径；通过 `files` 写入软件对应的 zone 配置。例如 BIND 的配置内容为 `zone "example.com" { type master; file "/usr/local/etc/zones/manual.example.com"; };`。
3. 在该服务的 behavior 中移除同一 origin 的 master 行，将其自动 DNSSEC 开关设为 false；保留其他服务的委派或 stub 关系。
4. 发布预签名文件时，同时提供父区 DS、递归器信任锚和所用 backend 的 metadata。检查最终 Compose 的挂载源与容器读取路径。

自定义 zone 的注册入口是 `ServiceHandler._process_files`、`_process_volumes` 与配置 Section；自动签名入口是 `_process_master_zones`。按选定的发布方式提供对应产物。

## 8. 运行期更新与 reload

- 从 Compose 找到实际挂载源。相对 resource 已复制为构建快照，更新该快照或共享目录中的运行文件。
- 原子替换文件时使用目录挂载，让容器读取新 inode。配置、日志、cache 和 journal 分别使用适合的目录及 UID/GID 权限。
- 普通发布更新 SOA serial 并重签；保留旧签名的实验只修改选定 RRset，并记录其前后值。
- BIND 按区执行 `rndc reload <zone>`；动态区按实际使用的 journal/inline signing 配置处理 freeze/thaw 或重新加载。
- PowerDNS 重新加载 backend 并同步 metadata；解析器刷新配置与清理缓存分别执行。
- reload 后直接查询 SOA 和目标 RR，再查询递归器。按实验阶段选择保留、flush 或重建递归缓存，并记录时刻。
