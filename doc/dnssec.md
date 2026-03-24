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

DNSSEC Hooks 允许在签名过程的关键节点注入自定义 Python 脚本，主要用于 DNS 漏洞复现场景，例如：

- 在 Re-Sign 之前注入额外的 DS 记录
- 添加额外的密钥模拟密钥泄露场景
- 修改签名参数模拟算法弱点

### 配置格式

在服务配置中使用 `dnssec.hooks` 字段：

```yaml
builds:
  root:
    image: bind
    ref: std:auth
    dnssec:
      enable: true
      hooks:
        pre-sign: |
          print(f"About to sign zone: {zone_name}")

        pre-resign: |
          # 注入额外的 DS 记录
          extra_ds = "example.com. IN DS 12345 13 2 ABCDEF..."
          fs.write_text(f"key:/{service_name}/extra.ds", extra_ds)

        post-sign: |
          print(f"Zone signed: {zone_name}")
          print(f"DS record: {ds_content}")
```

### 可用的 Hooks

| Hook | 执行时机 | 可用变量 | 用途 |
|------|----------|----------|------|
| `pre-sign` | 首次签名之前 | `zone_name`, `unsigned_content`, `service_name`, `fs` | 修改签名前的区域内容 |
| `post-sign` | 首次签名完成之后 | `zone_name`, `signed_content`, `ksk_key`, `zsk_key`, `ds_content` | 检查或修改签名结果 |
| `pre-resign` | Re-Sign 流程开始前 | `zone_name`, `zone_graph`, `fs` | **修改 key:/ 注入伪造 DS** |
| `post-resign` | Re-Sign 流程完成后 | `zone_name`, `zone_graph`, `fs` | 检查最终结果 |

### DS 注入机制

`pre-resign` hook 在整个 re-signing 流程开始前执行，你可以直接修改 `key:/` 文件系统：

```yaml
builds:
  root:
    image: bind
    dnssec:
      enable: true
      hooks:
        pre-resign: |
          # 写入伪造的 DS 文件到 key:/
          fake_ds = "malicious.com. IN DS 99999 13 2 DEADBEEF123456..."
          fs.write_text("key:/root/malicious.ds", fake_ds)

          # 或修改已有的 DS 文件
          # existing = fs.read_text("key:/tld/com.ds")
          # fs.write_text("key:/tld/com.ds", existing + "\n" + fake_ds)
```

系统会在 re-signing 时读取 `key:/` 下所有的 `.ds` 文件。

### Hook 变量说明

每个 hook 都可以访问以下变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `zone_name` | `str` | 当前处理的区域名（如 `example.com.`） |
| `zone_name_clean` | `str` | 清理后的区域名（如 `example.com`） |
| `service_name` | `str` | 服务名称 |
| `fs` | `FileSystem` | 文件系统对象，用于读写文件 |
| `workdir` | `DNSBPath` | 工作目录路径 |
| `config` | `dict` | 当前服务的完整配置 |

### 漏洞复现示例

#### 1. 注入伪造的 DS 记录

```yaml
builds:
  root:
    image: bind
    dnssec:
      enable: true
      hooks:
        pre-resign: |
          # 在 re-signing 前写入伪造的 DS 记录
          fake_ds = "malicious.com. IN DS 99999 13 2 DEADBEEF..."
          fs.write_text("key:/root/malicious.ds", fake_ds)
```

#### 2. 密钥泄露模拟

```yaml
builds:
  compromised_zone:
    image: bind
    dnssec:
      enable: true
      hooks:
        post-sign: |
          # 将私钥暴露到特定位置，模拟密钥泄露
          import os
          leak_dir = f"temp:/leaked_keys/{service_name}"
          fs.mkdir(leak_dir, exist_ok=True)
          # KSK 私钥已在 key:/ 中，可以复制到其他位置
          ksk_private = fs.read_text(f"key:/{service_name}/{zone_name_clean}.ksk.private")
          fs.write_text(f"{leak_dir}/leaked_ksk.private", ksk_private)
          print(f"[WARNING] Key leaked to {leak_dir}")
```

#### 3. 签名参数修改

```yaml
builds:
  weak_zone:
    image: bind
    dnssec:
      enable: true
      hooks:
        pre-sign: |
          # 可以在这里修改区域内容，例如缩短 TTL
          print(f"Original zone content length: {len(unsigned_content)}")
          # 可以修改 unsigned_content 然后写回
          # 注意：这只是示例，实际修改需要谨慎
```

### 注意事项

1. **执行顺序**：Hooks 按照配置顺序执行，同一 hook 类型可以配置多个脚本（列表格式）
2. **错误处理**：如果 hook 执行失败，整个签名过程会停止
3. **文件路径**：使用 `key:/` 路径访问密钥文件，使用 `temp:/` 访问临时文件
4. **安全性**：Hooks 具有完整的文件系统访问权限，请谨慎使用

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
