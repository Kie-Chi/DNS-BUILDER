# DNSSEC 支持(试验中)

仅在装有`bind9-utils`的linux环境下可用

DNSBuilder 自动支持 DNSSEC 签名和密钥管理

## 功能特性

- **自动签名链构建**：自动建立从根到叶的信任链
- **密钥自动生成**：KSK 和 ZSK 自动生成和管理
- **DS 记录自动传播**：子区 DS 记录自动添加到父区
- **透明集成**：无需手动配置，自动处理所有 DNSSEC 相关事务
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

## 工作原理

### 签名流程

1. **密钥生成阶段**
   - 为每个区域生成 KSK（Key Signing Key）
   - 为每个区域生成 ZSK（Zone Signing Key）
   - 密钥存储在`key:/` 文件系统中

2. **区域签名阶段**
   - 使用 ZSK 签名区域数据
   - 使用 KSK 签名 DNSKEY 记录集
   - 生成签名区域文件（`.signed`）

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
│     │   pre hook   │  ← 可修改: unsigned_content                 │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │  DNSSEC 签名  │                                            │
│     └──────┬───────┘                                            │
│            ↓                                                    │
│     ┌──────────────┐                                            │
│     │ 写入 key:/   │  ← 密钥、DS 记录写入 key:/ 文件系统          │
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
          print(f"Zone: {zone_name}")
          # unsigned_content = "modified..."

        mid: |
          # 注入伪造的 DS 记录到 key:/
          fake_ds = "malicious.com. IN DS 99999 13 2 DEADBEEF..."
          fs.write_text("key:/root/malicious.ds", fake_ds)

        post: |
          # 修改最终的签名结果
          signed_path = f"temp:/services/{service_name}/zones/db.{zone_name_clean}"
          content = fs.read_text(signed_path)
          # fs.write_text(signed_path, modified_content)
```

### Hooks 详细说明

| Hook | 执行时机 | 可修改内容 | 执行次数 |
|------|----------|------------|----------|
| `pre` | 单个 zone 签名前 | `unsigned_content` (未签名的 zone 文件) | 每个 zone 一次 |
| `mid` | 所有 zone 签名完成后，re-signing 前 | `key:/` 文件系统 (DS 记录、密钥) | 每个 zone 一次 |
| `post` | Re-signing 完成后 | `temp:/services/...` 文件系统 (最终签名结果) | 每个 zone 一次 |

### 可用变量

所有 hooks 都可以访问以下变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone_name` | `str` | 当前区域名（如 `example.com.`） |
| `zone_name_clean` | `str` | 清理后的区域名（如 `example.com`） |
| `service_name` | `str` | 服务名称 |
| `fs` | `FileSystem` | 文件系统对象 |
| `workdir` | `DNSBPath` | 工作目录路径 |
| `config` | `dict` | 当前服务的完整配置 |

`pre` hook 额外变量：
| 变量名 | 类型 | 说明 |
|--------|------|------|
| `unsigned_content` | `str` | 未签名的 zone 文件内容，**可修改** |

`mid` hook 额外变量：
| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone_graph` | `dict` | 所有 zone 的依赖关系图 |

`post` hook 额外变量：
| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone_graph` | `dict` | 所有 zone 的依赖关系图 |

### 文件系统路径

| 路径 | 用途 | 可用阶段 |
|------|------|----------|
| `key:/<service>/<zone>.ksk.key` | KSK 公钥 | mid, post |
| `key:/<service>/<zone>.ksk.private` | KSK 私钥 | mid, post |
| `key:/<service>/<zone>.zsk.key` | ZSK 公钥 | mid, post |
| `key:/<service>/<zone>.zsk.private` | ZSK 私钥 | mid, post |
| `key:/<service>/<zone>.ds` | DS 记录 | mid, post |
| `temp:/services/<service>/zones/db.<zone>` | 签名后的 zone 文件 | post |
| `temp:/services/<service>/zones/db.<zone>.unsigned` | 未签名的 zone 文件 | post |

### 使用场景

#### 1. 修改签名前的 zone 内容 (pre)

```yaml
hooks:
  pre: |
    # 缩短所有 TTL 值
    lines = unsigned_content.split('\n')
    modified = [line.replace('3600', '300') for line in lines]
    unsigned_content = '\n'.join(modified)
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
    signed_path = f"temp:/services/{service_name}/zones/db.{zone_name_clean}"
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
    ksk_private = fs.read_text(f"key:/{service_name}/{zone_name_clean}.ksk.private")
    fs.write_text(f"temp:/leaked_keys/{zone_name_clean}.ksk.private", ksk_private)
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
