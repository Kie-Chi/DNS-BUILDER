# DNSSEC 支持(试验中)

仅在装有`bind9-utils`的linux环境下可用

DNSBuilder 自动支持 DNSSEC 签名和密钥管理

## 功能特性

- **自动签名链构建**：自动建立从根到叶的信任链
- **密钥自动生成**：KSK 和 ZSK 自动生成和管理
- **DS 记录自动传播**：子区 DS 记录自动添加到父区
- **透明集成**：无需手动配置，自动处理所有 DNSSEC 相关事务

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


## 相关文档

- [Configuration Reference](config/index.md) - 配置文件格式
- [Behavior DSL](rule/behavior-dsl.md) - 区域行为配置

## 参考资源

- [DNSSEC HOWTO](https://www.dnssec-tools.org/)
- [BIND 9 DNSSEC Guide](https://bind9.readthedocs.io/en/latest/dnssec-guide.html)
- [RFC 4033](https://tools.ietf.org/html/rfc4033) - DNSSEC Introduction
- [RFC 4034](https://tools.ietf.org/html/rfc4034) - Resource Records
- [RFC 4035](https://tools.ietf.org/html/rfc4035) - Protocol Modifications
