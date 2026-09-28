# DNSSEC 支持(试验中)

DNSBuilder 的 DNSSEC 链路使用 BIND DNSSEC 工具生成预签名 zonefile，并在构建阶段建立 DS 信任链。工具依赖与运行时 DNS 服务分开处理。

默认 `util_mode: host`，按 `BIND_DNSSEC_*` 环境变量、PATH 和常见系统路径查找 `dnssec-signzone`、`dnssec-keygen` 等工具；`util_auto_install: true` 才会根据宿主机尝试安装 `bind9-utils`/`bind-utils`/`bind-tools` 或 macOS Homebrew `bind`。设置 `util_mode: docker` 时，DNSBuilder 在指定 `util_image` 中运行临时工具容器，不把工具安装到最终服务镜像，也不会自动拉取镜像。

PowerDNS Authoritative 使用预签名 zonefile 时还需要 BIND DNSSEC metadata DB。DNSBuilder 使用 Python 标准库 `sqlite3` 生成该数据库，因此 `pdnsutil` 不是必要依赖。

## 功能特性

- **自动签名链构建**：自动建立从根到叶的信任链
- **密钥自动生成**：KSK 和 ZSK 自动生成和管理
- **DS 记录自动传播**：子区 DS 记录自动添加到父区
- **显式配置工具依赖**：支持 host/docker 两种工具模式和环境变量覆盖
- **DNSSEC Hooks**：支持在签名过程中注入自定义脚本，用于漏洞复现场景
- **预生成密钥支持**：支持使用预先生成的密钥，便于控制 key tag 和密钥复用

## 使用预生成密钥

通过 `dnssec.include` 字段指定包含预生成密钥的目录：

```yaml
builds:
  root:
    image: bind
    dnssec:
      enable: true
      include: "resource:/keys/root"  # 密钥目录
```

### 密钥文件命名

系统会扫描目录中以下格式的密钥文件：

**推荐格式：**
```
<zone>.ksk.key       # KSK 公钥
<zone>.ksk.private   # KSK 私钥
<zone>.zsk.key       # ZSK 公钥
<zone>.zsk.private   # ZSK 私钥
```

**BIND 标准格式：**
```
K<zone>.+<alg>+<keytag>.key
K<zone>.+<alg>+<keytag>.private
```

系统会自动识别 KSK（flags: 257）和 ZSK（flags: 256）。

### 使用场景

#### 1. 控制特定 Key Tag

```bash
# 暴力生成特定 key tag 的密钥
while true; do
  dnssec-keygen -a ECDSAP256SHA256 -n ZONE example.com
  # 检查生成的 key tag 是否符合要求
done
```

#### 2. 密钥复用

多次构建使用同一套密钥，保持 DS 记录不变：

```yaml
builds:
  root:
    image: bind
    dnssec:
      enable: true
      include: "resource:/persistent_keys/root"
```

#### 3. 模拟密钥泄露

使用已知的"泄露"密钥进行漏洞复现：

```yaml
builds:
  compromised:
    image: bind
    dnssec:
      enable: true
      include: "resource:/leaked_keys/compromised"
```

### Fallback 行为

如果 `include` 目录不存在或没有找到有效密钥，系统会：
1. 输出警告日志
2. 自动 fallback 到密钥生成
3. 继续正常签名流程

## PowerDNS Authoritative 预签名链路

将服务的镜像类型写成 `pdns_auth`，角色仍使用独立的 `pdns_auth:auth`（`std:auth` 会按软件类型解析）：

```yaml
images:
  powerdns:
    ref: pdns_auth:5.0.7
builds:
  auth-cn:
    image: powerdns
    ref: std:auth
    dnssec: true
    behavior: |
      cn master dlv NS auth-dlv
```

也可以在服务级直接使用可识别的外部镜像，例如 `powerdns/pdns-auth-50:5.0.7`。DNSBuilder 会生成并挂载：

- `/usr/local/etc/pdns.conf`：`launch=bind`、`bind-config` 和兼容现有 glue 的 `bind-ignore-broken-records=yes`；
- `/usr/local/etc/zones/generated_zones.conf` 与 `db.<zone>`：BIND backend 读取的 zone 配置和最终签名文件；
- `/usr/local/etc/includes/pdns_dnssec.conf`：`bind-dnssec-db` 路径；
- `/usr/local/var/lib/pdns/bind-dnssec-db.sqlite3`：包含 `cryptokeys`、`domainmetadata`、`tsigkeys` 的 metadata DB。

`pdns_recursor` 是递归软件的 canonical 类型；`pdns_recur`、`pdns-recur` 等仅为输入 alias。Authoritative 与 Recursor 不能用同一个软件角色或配置文件。

PowerDNS 的 bind backend 会忽略 zone 外的 `*.servers.net.` glue；DNSBuilder 的 PowerDNS 基础配置开启 `bind-ignore-broken-records=yes`，否则同一份现有 zonefile 会被拒绝。

验证时直接查询 Authoritative 地址检查 SOA/DNSKEY/DS，再经 Unbound 查询正记录和 NXDOMAIN。递归响应应带 `ad`，负响应应带 `NSEC3` 和对应 `RRSIG`。

## 工作原理

### 签名流程

1. **密钥生成阶段**
   - 为每个区域生成 KSK（Key Signing Key）
   - 为每个区域生成 ZSK（Zone Signing Key）
   - 密钥存储在`key:/` 文件系统中

2. **区域签名阶段**
   - 使用 ZSK 签名区域数据
   - 使用 KSK 签名 DNSKEY 记录集
   - 生成最终签名区域文件 `db.<zone>`（`.signed` 仅是旧实现中的中间命名，不是运行时契约）

3. **信任链建立**
   - 从子区 KSK 生成 DS 记录
   - DS 记录自动添加到父区
   - 根区配置信任锚点（Trust Anchor）

## DNSSEC Hooks

DNSSEC Hooks 允许在签名过程的关键节点注入自定义 Python 脚本，主要用于 DNS 漏洞复现场景。

### 签名流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        DNSSEC 签名流程                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 首次签名阶段 (每个 zone 独立执行)                            │
│     ┌──────────────┐                                            │
│     │ 生成 zone 文件 │                                           │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │写入 unsigned │  → temp:/services/.../db.<zone>.unsigned   │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │   pre hook   │  ← 可修改: temp:/.../db.<zone>.unsigned    │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │  DNSSEC 签名  │                                            │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │ 写入 key:/   │  ← 密钥、DS 记录写入 key:/ 文件系统          │
│     │ 写入 signed  │  → temp:/services/.../db.<zone>            │
│     └──────────────┘                                            │
│                                                                 │
│  2. Re-signing 阶段 (建立信任链，父 zone 签名子 zone 的 DS)       │
│     ┌──────────────┐                                            │
│     │   mid hook   │  ← 可修改: key:/ (注入伪造 DS、修改密钥)     │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │  Re-signing  │  ← 父 zone 重新签名，包含子 zone 的 DS       │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │  post hook   │  ← 可修改: temp:/services/... (最终签名结果) │
│     └──────────────┘                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 配置格式

```yaml
builds:
  root:
    image: bind
    ref: std:auth
    dnssec:
      enable: true
      hooks:
        pre: |
          # 修改未签名的 zone 内容
          print(f"Zone: {zone.fqdn}")
          # unsigned_content = "modified..."

        mid: |
          # 注入伪造的 DS 记录到 key:/
          fake_ds = "malicious.com. IN DS 99999 13 2 DEADBEEF..."
          fs.write_text("key:/root/malicious.ds", fake_ds)

        post: |
          # 修改最终的签名结果
          signed_path = f"temp:/services/{service_name}/zones/{zone.filename}"
          content = fs.read_text(signed_path)
          # fs.write_text(signed_path, modified_content)
```

### Hooks 详细说明

| Hook | 执行时机 | 可修改内容 | 执行次数 |
|------|----------|------------|----------|
| `pre` | 单个 zone 签名前 | `temp:/services/.../db.<zone>.unsigned` (未签名的 zone 文件) | 每个 zone 一次 |
| `mid` | 所有 zone 签名完成后，re-signing 前 | `key:/` 文件系统 (DS 记录、密钥) | 每个 zone 一次 |
| `post` | Re-signing 完成后 | `temp:/services/...` 文件系统 (最终签名结果) | 每个 zone 一次 |

### 可用变量

所有 hooks 都可以访问以下变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone` | `ZoneName` | 区域名对象，可通过 `zone.fqdn` 获取 `example.com.`，`zone.label` 获取 `example.com` |
| `service_name` | `str` | 服务名称 |
| `fs` | `FileSystem` | 文件系统对象 |
| `workdir` | `DNSBPath` | 工作目录路径 |
| `config` | `dict` | 当前服务的完整配置 |

`mid` hook 额外变量：
| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone_graph` | `dict` | 所有 zone 的依赖关系图 |

`post` hook 额外变量：
| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone_graph` | `dict` | 所有 zone 的依赖关系图 |

### 文件系统路径

**密钥存储（key:/）** — 用于 DNSSEC re-signing 时读取：

| 路径 | 用途 | 可用阶段 |
|------|------|----------|
| `key:/<service>/<zone>.ksk.key` | KSK 公钥 | mid, post |
| `key:/<service>/<zone>.ksk.private` | KSK 私钥 | mid, post |
| `key:/<service>/<zone>.zsk.key` | ZSK 公钥 | mid, post |
| `key:/<service>/<zone>.zsk.private` | ZSK 私钥 | mid, post |
| `key:/<service>/<zone>.ds` | DS 记录 | mid, post |

**服务目录（temp:/services/）** — zone 文件存储：

| 路径 | 用途 | 可用阶段 |
|------|------|----------|
| `temp:/services/<service>/zones/db.<zone>.unsigned` | 未签名的 zone 文件 | pre, post |
| `temp:/services/<service>/zones/db.<zone>` | 签名后的 zone 文件 | post |

### 使用场景

#### 1. 修改签名前的 zone 内容 (pre)

```yaml
hooks:
  pre: |
    # 直接操作文件系统修改未签名的 zone 文件
    unsigned_path = f"temp:/services/{service_name}/zones/{zone.filename}.unsigned"
    content = fs.read_text(unsigned_path)
    # 缩短所有 TTL 值
    modified = content.replace('3600', '300')
    fs.write_text(unsigned_path, modified)
```

#### 2. 注入伪造的 DS 记录 (mid)

```yaml
hooks:
  mid: |
    # 写入伪造的 DS 记录
    fake_ds = "malicious.com. IN DS 99999 13 2 DEADBEEF123456..."
    fs.write_text("key:/root/malicious.ds", fake_ds)

    # 或修改已有的 DS 文件
    # existing = fs.read_text("key:/tld/com.ds")
    # fs.write_text("key:/tld/com.ds", existing + "\n" + fake_ds)
```

#### 3. 修改最终签名结果 (post)

```yaml
hooks:
  post: |
    # 读取签名后的 zone 文件
    signed_path = f"temp:/services/{service_name}/zones/{zone.filename}"
    content = fs.read_text(signed_path)

    # 进行修改（例如添加额外的记录）
    # modified = content + "\nextra.example.com. IN A 1.2.3.4"
    # fs.write_text(signed_path, modified)
```

#### 4. 密钥泄露模拟 (mid)

```yaml
hooks:
  mid: |
    # 将私钥复制到临时目录，模拟泄露
    ksk_private = fs.read_text(f"key:/{service_name}/{zone.label}.ksk.private")
    fs.write_text(f"temp:/leaked_keys/{zone.label}.ksk.private", ksk_private)
    print(f"[WARNING] Key leaked to temp:/leaked_keys/")
```

### 注意事项

1. **执行顺序**：Hooks 按照 pre → mid → post 的顺序执行
2. **错误处理**：如果 hook 执行失败，整个签名过程会停止
3. **安全性**：Hooks 具有完整的文件系统访问权限，请谨慎使用

## 相关文档

- [Configuration Reference](config/index.md) - 配置文件格式
- [Behavior DSL](rule/behavior-dsl.md) - 区域行为配置
- [Auto Scripts](config/auto.md) - 自动化脚本

## 参考资源

- [DNSSEC HOWTO](https://www.dnssec-tools.org/)
- [BIND 9 DNSSEC Guide](https://bind9.readthedocs.io/en/latest/dnssec-guide.html)
- [RFC 4033](https://tools.ietf.org/html/rfc4033) - DNSSEC Introduction
- [RFC 4034](https://tools.ietf.org/html/rfc4034) - Resource Records
- [RFC 4035](https://tools.ietf.org/html/rfc4035) - Protocol Modifications
