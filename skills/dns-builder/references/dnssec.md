# DNSSEC：签名链、密钥与工具联动

分别配置权威签名、父区 DS 和递归器 validation。按构建时序放置 DNSKEY、RRSIG 与 DS 修改，再从最终 zone 和实际查询检查结果。

## 1. 建立正常签名链

合并到 [../assets/basic/main.yml](../assets/basic/main.yml) 的同名字段，签名 root/com/example.com 及名称支撑区，并为 Unbound 配置信任锚：

```yaml
util_mode: host
util_auto_install: false
vars:
  std:
    dnssec: true
builds:
  resolver:
    volumes:
      - key:/root.key:/usr/local/etc/keys/root.key:ro
    files:
      /usr/local/etc/unbound/validation.conf.server: |
        trust-anchor-file: /usr/local/etc/keys/root.key
        module-config: "validator iterator"
        val-permissive-mode: no
```

`std-auth` 的全局 modify 按 `vars.std.dnssec` 设置所有含 master 行为的服务，并保留其 include/hooks。使用独立权威配置时，在各签名服务设置 `dnssec: {enable: true}`。混合签名场景在服务级 modify 中设置该服务的 `config['dnssec']['enable']`，同时检查父区 DS 的有无。

### 选择构建期工具

- `util_mode: host`：使用宿主 BIND 工具，按 `BIND_DNSSEC_*`、PATH 和常见目录查找。
- `util_mode: docker`：使用独立的工具容器；默认工具镜像由内置 Dockerfile 构建。设置 `util_image` 时，预先在本地准备该镜像。
- 工具安装由 `util_auto_install` 或 `DNSSEC_AUTO_INSTALL` 控制。记录 `dnssec-signzone -V` 与运行时权威软件的版本，分别管理构建与服务依赖。
- `util_mode` 控制框架的工具 runner；项目在 setup 中直接调用的 subprocess 仍在宿主执行。为这些脚本单独准备工具/Python 依赖，或显式调用选定的工具容器，并检查输出文件。
- `BIND_DNSSEC_KEYGEN`、`BIND_DNSSEC_SIGNZONE`、`BIND_DNSSEC_DSFROMKEY`、`BIND_DNSSEC_CHECKZONE` 可指定可执行文件。Docker 模式下，指定容器内路径。

<a id="signing-order"></a>

## 2. 按真实签名顺序操作

| 次序 | 源码入口 | 输入与输出 |
| --- | --- | --- |
| 1 | `Builder._prepare_dnssec_tools` | 创建共享 runner，预检 `dnssec-signzone` |
| 2 | `ZoneGenerator.generate` | 每区生成 SOA、默认 NS 与数据，写 `db.<zone>.unsigned` |
| 3 | `ZoneGenerator._sign_zone` | 执行 pre，然后读取修改后的 unsigned |
| 4 | `ZoneGenerator._find_keys_in_include` | 从 include 选取一对 KSK/ZSK；未找到完整密钥时执行 keygen |
| 5 | `ZoneGenerator._sign_zone` | 在工具临时目录追加公钥 `$INCLUDE`，首签，读取 `.signed` 与 `dsset-<zone>.` |
| 6 | `ZoneGenerator.generate` | 发布最终 zone、KSK/ZSK、私钥、DS 和 `.keynames` 到构建 FS |
| 7 | `ServiceHandler.generate_all` | 所有服务完成初始 zone 后进入 barrier |
| 8 | `DNSSECResigner.run` | 建立 zone_graph，对图中所有区执行 mid |
| 9 | `DNSSECResigner._resign_parent_zone` | 子到父处理；将子区 DS 追加到父区 unsigned 副本，再用原密钥重签 |
| 10 | `DNSSECResigner.run` | 重签完成后，对图中所有区执行 post |
| 11 | `DNSSECHandler.run` | 从根 KSK 汇总 `key:/root.key`，并汇总 `key:/all.ds` |
| 12 | `ServiceHandler.generate_all` | 复制最终挂载、生成 PowerDNS metadata、组装服务配置 |
| 13 | `Builder.run` | restrict、写出 Compose、auto.post |

`pre` 只在首签时执行。重签直接读取保存的 unsigned 与 key 文件；叶区跳过重签，有子区的父区重新生成最终 signed 文件。将最终 RRSIG 修改安排在 post，使叶区和父区使用同一处理方式。

重签时，父区的 DS 追加发生在签名输入副本中；保留的 `.unsigned` 文件仍是 pre 处理后的内容。重签还会更新该父区自身的 `.ds`，供更上一层读取。

### 构建文件定位

| 路径 | 内容与使用阶段 |
| --- | --- |
| `temp:/services/<service>/zones/db.<zone>.unsigned` | pre 修改，父区重签再次读取 |
| `temp:/services/<service>/zones/db.<zone>` | 首签输出、父区重签输出、post 修改 |
| `key:/<service>/<zone>.ksk.key` / `.zsk.key` | 保存的签名公钥 |
| 对应 `.private` | 重签读取的私钥 |
| `key:/<service>/<zone>.keynames` | KSK/ZSK 的 BIND basename，重建工具工作目录时使用 |
| `key:/<service>/<zone>.ds` | 下一层父区重签读取的 DS |
| `key:/root.key` | post 全部结束后汇总的根 KSK |
| `output/<name>/<service>/contents/db.<zone>` | 服务挂载的最终 zone；通过 Compose 确认容器目标 |

使用 `zone.fqdn`、`zone.label`、`zone.filename` 组装路径。根区分别为 `.`、`root`、`db.root`。

## 3. 生成并导入固定密钥

每个 include 目录存放一个 zone 的完整 KSK/ZSK 公私钥，保留 BIND basename：

```bash
keys_dir="$PWD/resource/keys/example"
mkdir -p "$keys_dir"
zsk=$(dnssec-keygen -q -K "$keys_dir" -a ECDSAP256SHA256 -n ZONE example.com.)
ksk=$(dnssec-keygen -q -K "$keys_dir" -a ECDSAP256SHA256 -f KSK -n ZONE example.com.)
dnssec-dsfromkey -2 "$keys_dir/$ksk.key" > "$keys_dir/example.com.ds"
```

将该目录配置给拥有 example.com 的权威：

```yaml
builds:
  auth:
    dnssec:
      enable: true
      include: resource/keys/example
```

- `include` 接受目录或目录列表，查找完整 KSK/ZSK 对。当前查找使用文件模式和 flags，按首次完整匹配选取；为需要不同固定密钥的区分配独立服务和目录。
- 推荐保留 `K<zone>.+<algorithm>+<tag>.key/.private`。工具也识别 `*.ksk.*`、`*.zsk.*`；检查公私钥 basename 一致且 signer 可加载。
- 将附加 DNSKEY、RRSIG、DS 记录放在独立的 `resource/records/`。通过 hooks 导入这些 RR；include 用于提供签名密钥。
- 在日志查找 `Using included keys`，再比较最终 DNSKEY、key tag 与输入公钥。固定密钥的重建同时记录签名时间和 SOA serial。
- 运行时权威读取预签名 zone；递归器挂载公钥信任锚。构建期私钥保存在签名资源目录。

<a id="signzone"></a>

## 4. 掌握 dnssec-signzone 的调用与产物

当前首签和重签采用相同的核心参数：

```text
dnssec-signzone -3 <salt> -N INCREMENT -o <zone.fqdn> <unsigned-file>
```

salt 取 `sha1(zone.fqdn)` 的前 16 个十六进制字符。自动 keygen 使用 `ECDSAP256SHA256`。所选 KSK/ZSK 的公钥通过 `$INCLUDE` 加入工具临时输入，私钥按 BIND basename 放在同一目录。签名输出包含 DNSKEY、RRSIG 和 NSEC3；子区的 `dsset-*` 用于建立父区 DS。

| 工具参数 | 用法 |
| --- | --- |
| `-o` | 指定 zone origin，保持与记录 owner 和 signer name 一致 |
| `-K` | 指定密钥目录 |
| `-S` | 手工签名时按密钥元数据搜索、发布和使用密钥 |
| `-k` / 命令末尾的 key basename | 手工指定 KSK / 签名密钥，按工具版本查看 `-h` |
| `-N INCREMENT` / `-N keep` | 控制 SOA serial；框架使用前者 |
| `-3` / `-H` | 设置 NSEC3 salt / 迭代数；框架只显式设置 salt |
| `-s` / `-e` | 控制 RRSIG 生效时间和失效时间 |
| `-f` / `-d` | 指定最终 zone / DS 等辅助产物目录 |
| `-n` | 控制工具线程数 |

手工签名时，对项目生成的输入 zone 执行以下片段：

```bash
mkdir -p run
named-checkzone example.com. resource/zones/example.com.zone
dnssec-signzone -n 1 -K "$keys_dir" -S -o example.com. -N keep -d run \
  -f run/example.com.signed resource/zones/example.com.zone
dnssec-verify -o example.com. run/example.com.signed
```

按目的选择联动方式：

1. **固定算法或密钥**：用 keygen 生成所需密钥，通过 include 交给框架签名和建链。
2. **增加待签记录**：在 pre 修改 unsigned，沿用框架的 KSK/ZSK 和父区重签。
3. **保留额外或修改后的签名**：在 post 修改最终文件，使用 [zone-mutation.md](zone-mutation.md) 的 RRset 操作。
4. **控制完整签名参数**：用外部脚本签名，通过 `files/volumes` 和 zone 配置发布结果；同步管理父区 DS、根锚及 PowerDNS metadata。按 [zone-mutation.md](zone-mutation.md#custom-zone) 注册自定义 zone。

在 `auto.setup` 执行资源准备脚本时，传入绝对脚本路径、`cwd` 和 `check=True`，将输出放在项目资源目录；对长任务设置 timeout。预先生成耗时的记录材料，可缩短后续反复构建的时间。服务等待 barrier 的当前超时为 30 秒，将耗时的材料生成安排在服务签名前。

<a id="keytrap-records"></a>

## 5. 配置 DNSSEC 候选记录与校验输入

将输入分为签名密钥、附加 DNSKEY、目标 RRSIG 和父区 DS 四组，分别控制生成数量与注入阶段：

| 输入 | 操作 | 检查关系 |
| --- | --- | --- |
| KSK/ZSK | 用 include 提供完整密钥对 | DNSKEY flags/protocol/algorithm、公私钥匹配 |
| 附加候选 DNSKEY | 在 pre 追加到 apex DNSKEY RRset，随后签名 | 同一候选组的 algorithm/key tag，公钥内容互异 |
| 目标 RRset 的 RRSIG | 在 post 按 owner/type covered 导入或替换 | signer、algorithm、key tag、labels、original TTL、有效期和签名字节格式 |
| DS 候选集 | 在子区 mid 写 `key:/<service>/<zone>.ds`，由父区签名 | owner 为子区名，tag/algorithm/digest type/长度与实验参数对应 |

使用 `dns.dnssec.key_id(rdata)` 对实际 DNSKEY RDATA 计算 key tag；flags、protocol、algorithm 和公钥字节共同参与计算。用不同的 RDATA 表达候选数量，按解析后的 RRset 计数。

先通过正常 DNSKEY 信任链，再添加候选数据。将附加 DNSKEY 放在 pre，使 KSK 签名覆盖最终 DNSKEY RRset；把目标数据的附加 RRSIG 放在 post，保留其原始字节和实验设定。记录是否保留原有有效覆盖签名，并观察验证器的签名尝试与结束位置。

保持签名时间覆盖实验时刻，按 owner 计算 labels，按算法检查公钥与签名编码。区分 `RRSIG(DNSKEY)`、`RRSIG(A/AAAA/...)` 和父区 `RRSIG(DS)`；分别检查实际查询是否进入目标 RRset 的校验路径。

DS 密集变体通过父区的有效 `RRSIG(DS)` 将候选集送入后续匹配。若 mid 修改的区自身也会被重签，处理其 `.ds` 再生成顺序；需要直接控制最终父区内容时，在父区 unsigned 上准备记录并重签。需要旧签名失配时，使用父区 post。

对正常输入与修改后输入使用相同的 resolver 版本、缓存准备和查询条件。记录解析器 CPU 时间、响应延迟、DNSKEY/RRSIG 数量和验证日志；使用 TCP 查询检查完整的大 RRset，再测试 UDP、TC 和 TCP 回退。

<a id="signature-links"></a>

### 检查候选记录与目标签名的关联

先选择目标 owner/type covered，再从最终区文件统计候选关系。以下函数用于普通数据、DNSKEY 或父区 DS 的结构检查；`now` 使用 UTC Unix 秒，时间窗口按 DNSSEC 32 位序号计算：

```python
from collections import Counter
import dns.dnssec
import dns.rdatatype


def inspect_signature_links(parsed, owner, covered, now):
    kind = dns.rdatatype.from_text(covered)
    records = parsed.get_rdataset(owner, kind)
    keys = parsed.get_rdataset(parsed.origin, 'DNSKEY')
    signatures = parsed.get_rdataset(owner, 'RRSIG', kind)
    if records is None or keys is None or signatures is None:
        raise ValueError('Missing data, DNSKEY, or covering RRSIG')
    groups = Counter(
        (key.algorithm, dns.dnssec.key_id(key))
        for key in keys if key.protocol == 3 and key.flags & 256
    )
    rows = []
    for signature in signatures:
        lifetime = (signature.expiration - signature.inception) & 0xffffffff
        age = (int(now) - signature.inception) & 0xffffffff
        rows.append({
            'algorithm': int(signature.algorithm),
            'key_tag': signature.key_tag,
            'candidate_keys': groups[(signature.algorithm, signature.key_tag)],
            'signer_matches': signature.signer.derelativize(parsed.origin).canonicalize() == parsed.origin.canonicalize(),
            'current_window': age <= lifetime < 0x80000000,
            'labels': signature.labels,
            'original_ttl': signature.original_ttl,
            'observed_ttl': records.ttl,
        })
    return rows
```

- 正常与候选匹配实验检查 signer、时间窗口和预期候选数；专门构造失配时，记录预期改变的字段以及实际失败位置。
- 生成候选材料时固定 flags/protocol/algorithm，再按实际 key tag 分组；同组记录使用不同 RDATA。保留签名密钥、公钥候选和签名材料各自的来源与参数。
- 按 owner 解释 labels，通配符签名单独核对其展开规则；对比 original TTL 与实际 TTL，区分正常 TTL 递减和改变签名数据。
- 结构检查、加密校验与运行开销分别记录。使用真实工具验证正常签名及 DNSKEY 信任链；公钥格式、算法支持和签名字节的有效性由实际 signer/validator 检查。
- 按 `正常输入 → 改一类 RRset → 改第二类 RRset → 组合` 对照，分别改变密钥候选、签名候选或 DS 候选数。先核对传输成功和目标 RRset 被查询，再测 CPU、延迟和缓存。

## 6. 检查自动建链与跨软件配置

自动依赖图扫描 `key:/*/*.ksk.key`，通过去掉最左标签确定父区。建立逐标签的已签名父区，或为跳级委派单独编排 DS。多服务管理同一 origin 时，当前图按 origin 保留一个条目；使用共享签名产物或分别管理这些服务的密钥与发布。

PowerDNS Authoritative 的 BIND backend 使用 `PRESIGNED`、`NSEC3PARAM` metadata 和 SQLite 数据库。当前服务在挂载复制后写出 metadata，但输入来自首签时保存的 `_pdns_dnssec_zones`。修改 NSEC3PARAM 后，在 auto.post 从最终 zone 重建 metadata，使数据库与发布文件一致。

以下片段用于只管理 example.com 的 `pdns_auth` 服务 `auth`；多区服务将该服务的所有已签名区加入 `zone_files`。按 RR 类型提取 NSEC3PARAM 后写 metadata，避免把单行 `RRSIG(NSEC3PARAM)` 当作参数记录：

```yaml
auto:
  post: |
    import tempfile
    from pathlib import Path
    import dns.zone
    from dnsbuilder.io import DNSBPath
    from dnsbuilder.utils.pdns_dnssec import write_bind_dnssec_db
    contents = DNSBPath(output_dir) / 'auth' / 'contents'
    zone_files = {'example.com.': 'db.example.com'}
    zones = {}
    for origin, filename in zone_files.items():
      signed = dns.zone.from_text(fs.read_text(contents / filename), origin=origin, relativize=False)
      parameters = signed.get_rdataset(signed.origin, 'NSEC3PARAM')
      if parameters is None:
        raise ValueError(f'Missing NSEC3PARAM: {origin}')
      zones[origin] = parameters.to_text(name=signed.origin, relativize=False)
    with tempfile.TemporaryDirectory() as directory:
      database = write_bind_dnssec_db(zones, Path(directory) / 'metadata.sqlite3')
      fs.write_bytes(contents / 'pdns-dnssec' / 'bind-dnssec-db.sqlite3', database.read_bytes())
```

`write_bind_dnssec_db` 要求 NSEC3PARAM 使用 hash algorithm 1。使用该自动 metadata 路径时，手工签名也生成 NSEC3；改为 NSEC 发布时，提供相应的 backend metadata。源码见 `src/dnsbuilder/utils/pdns_dnssec.py`。

PowerDNS Recursor 使用独立的 validation/trust-anchor 配置，旧 key=value 与新配置格式按版本选择；Knot Resolver 按 Lua/YAML 模板及实际启动方式配置。软件切换后重复相同的正向和负向 DNSSEC 查询。

## 7. 验证最终产物与查询

在 basic 容器链中执行：

```bash
compose=output/basic/docker-compose.yml
docker compose -f "$compose" exec -T client dig +time=3 +tries=1 +norecurse +dnssec @root . DNSKEY
docker compose -f "$compose" exec -T client dig +time=3 +tries=1 +norecurse +dnssec @tld example.com DS
docker compose -f "$compose" exec -T client dig +time=3 +tries=1 +norecurse +dnssec @auth www.example.com A
docker compose -f "$compose" exec -T client dig +time=3 +tries=1 +dnssec @resolver www.example.com A
docker compose -f "$compose" exec -T client dig +time=3 +tries=1 +dnssec +cdflag @resolver www.example.com A
docker compose -f "$compose" exec -T client dig +time=3 +tries=1 +dnssec @resolver missing.example.com A
```

检查正向结果的 A/RRSIG 与 AD，检查负向结果的 NXDOMAIN、NSEC3/RRSIG 与 AD。DO 请求 DNSSEC 数据，CD 请求跳过校验；结合当前解析器的信任锚解释 AD。

用 `named-checkzone` 检查可加载语法，用 `dnssec-verify` 检查正常 zone 的签名，再通过真实递归器检查 DS 链。修改后对比普通查询、CD 查询、直接权威响应和验证日志，记录确切失败关系。

部分签名失败分支返回 unsigned，部分重签异常记录日志后继续构建。对每个预期签名区检查最终 DNSKEY、目标 RRSIG、父区 DS、root.key 和 hooks 产物，使构建检查覆盖这些分支。
