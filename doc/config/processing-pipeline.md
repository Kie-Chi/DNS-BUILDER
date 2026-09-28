# 配置处理流程
本文档详细说明 DNSB 如何处理配置文件，从加载到最终输出的完整流程

## 流程图

```
配置文件加载
    ↓
[预处理阶段] include 合并 → 变量渲染
    ↓
[Auto Setup] 动态生成配置
    ↓
[镜像初始化] 解析 images 块，创建内部镜像对象
    ↓
[Ref 解析] 解析所有 ref 引用，继承模板配置
    ↓
[网络规划] 为服务分配 IPv4 地址
    ↓
[变量替换] 替换 ${var} 占位符
    ↓
[拓扑映射] 生成网络拓扑图
    ↓
[Auto Modify] 修改已解析的配置
    ↓
[DNSSEC Preflight] 解析 host/docker 工具（启用 DNSSEC 时）
    ↓
[并行服务生成] 初次生成 zone、配置和挂载，等待 barrier
    ↓
[DNSSEC Re-sign] 建立 DS 链并更新最终 signed zone/metadata
    ↓
[配置组装] 生成 Dockerfile、docker-compose.yml 等
    ↓
[Auto Restrict] 验证最终配置有效性
    ↓
[Auto Post] 在 Compose 写出后执行收尾脚本
    ↓
[增量缓存] 检测变化，仅重建必要服务(Optional)
    ↓
输出产物
```

## 阶段

### 1. 配置文件加载

**操作：** 解析 YAML 配置文件

```bash
dnsb build config.yml
```

- 从指定文件读取 YAML 格式的配置
- 初始化 `Config` 对象
- 不进行任何验证或扩展

### 2. 预处理阶段

**操作：** include 合并与初步处理

```yaml
name: demo
inet: 10.88.0.0/24
include:
  - resource:/includes/base.yml
  - ./custom.yml
```

- 递归处理 `include` 字段引用的配置文件
- 使用深度合并策略整合多个配置
- 当前配置的键优先级最高
- 变量和资源路径的初步处理

### 3. Auto Setup 阶段

**操作：** 执行初始化脚本

```yaml
auto:
  setup: |
    # 可以生成新服务、初始化配置
    for i in range(3):
      config['builds'][f'service-{i}'] = {...}
```

- 依照脚本内容对服务配置甚至整体配置进行初始化
- 动态生成基础服务
- 根据外部条件初始化配置
- 从外部数据源导入配置

### 4. 镜像初始化

**操作：** 解析 `images` 块，创建内部镜像对象

```yaml
images:
  bind:
    ref: "bind:9.18.0"
  unbound:
    software: unbound
    version: "1.19.0"
    from: "debian:12"
```

- 逐个加载每个镜像配置
- 创建对应的 `InternalImage` 或 `ExternalImage` 对象
- 缓存镜像对象供后续 ref 解析使用

### 5. Ref 解析

**操作：** 解析所有服务的 `ref` 字段，继承模板配置

```yaml
builds:
  recursor:
    image: bind
    ref: std:recursor        # ← 需要解析
    behavior: . hint root
```


### 6. 网络规划

**操作：** 为每个服务分配 IPv4 地址

```yaml
inet: 10.88.0.0/24
builds:
  recursor:
    address: 10.88.0.2        # ← 手动指定
  root:                        # ← 自动分配
```

### 7. 变量替换

**操作：** 替换配置中的 `${...}` 占位符

```yaml
behavior: |
  server 127.0.0.1@53 ${services.recursor.image.version}
```

### 8. Auto Modify 阶段

**操作：** 执行修改脚本，调整已解析的配置

```yaml
auto:
  modify: |
    # 在所有 ref 解析、网络规划、变量替换后执行
    for svc_name, svc_config in config['builds'].items():
      svc_config['cap_add'] = ['NET_ADMIN']
```

- **禁止在顶层使用 `include` 字段**
  - include 合并必须在 setup 前完成
- **禁止在服务中使用 `ref` 字段**
  - ref 解析必须在 modify 前完成

### 9. DNSSEC 预检与 barrier

启用 DNSSEC 的服务会共享一个工具 runner。`util_mode: host` 解析宿主机工具，`util_mode: docker` 在 `util_image` 中运行临时容器。所有服务先完成初次行为和 zone 生成，再由 barrier 保证父子 zone 都已就绪。

### 10. DNSSEC Re-sign 与配置生成

re-sign 阶段把子区 DS 写回父区并更新最终 `db.<zone>`。`pdns_auth` 服务随后生成 PowerDNS 专用 `pdns.conf`、BIND backend zone 配置以及 SQLite metadata DB；BIND/Unbound 服务则继续使用各自的配置 Section。

### 11. 构建生成

**操作：** 为每个服务生成 Dockerfile、配置文件等

- 根据服务配置和镜像类型生成 Dockerfile
- 生成服务特定的配置文件（如 BIND zone 文件）
- 处理卷挂载和文件复制
- 生成 `docker-compose.yml`

### 12. Auto Restrict 阶段

**操作：** 执行验证脚本，检查最终配置有效性

```yaml
auto:
  restrict: |
    # 在所有生成完成后，部署前执行
    errors = []
    for svc_name, svc_config in config['builds'].items():
      if not svc_config.get('image'):
        errors.append(f"Service {svc_name} missing image")
    
    if errors:
      result = "ERROR: " + "; ".join(errors)
    else:
      result = "PASS"
```

- 验证配置完整性和有效性
- 检查网络连通性要求
- 提供部署前的检查列表


### 13. Auto Post 阶段

Compose 文件写出后执行 `auto.post`，适合生成报告或校验最终产物。

## 延伸阅读

- [Auto 自动化脚本](auto.md)
- [配置概览](index.md)
- [标准服务模板](../rule/build-templates.md)
- [文件路径与FS](../rule/paths-and-fs.md)
