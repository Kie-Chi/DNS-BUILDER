# 自动化脚本

用于在配置构建的各个阶段自动执行 Python 脚本，实现动态配置生成、修改和验证。支持全局脚本和服务级脚本，脚本可串行或并行执行

## 概览

Auto 功能通过三个执行阶段来管理配置：

1. **setup**：初始化阶段，在配置解析前预执行，用于生成基础配置或新增服务
2. **modify**：修改阶段，在配置解析后(`ref`展开、内置变量替换后)执行，用于动态调整已解析的配置
3. **restrict**：验证阶段，在配置完全解析后执行，用于检查配置有效性

## 配置结构

### 全局自动化脚本

在顶层配置中声明 `auto` 块：

```yaml
name: demo
inet: 10.88.0.0/24

auto:
  setup: |
    # Python 代码，可修改或增加 config 的内容
    if 'custom_key' not in config:
      config['custom_key'] = 'custom_value'
  
  modify: |
    # Python 代码，在所有 ref 解析后执行
    for svc_name, svc_config in config.get('builds', {}).items():
      svc_config['custom_field'] = 'modified'
  
  restrict: |
    # Python 代码，验证配置有效性
    result = "PASS"  # 必须赋值给 result，作为验证结果
    if not config.get('inet'):
      result = "ERROR: Missing inet"

builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
```

### 服务级自动化脚本

在各个服务配置中声明 `auto` 块：

```yaml
builds:
  my_service:
    image: "bind"
    ref: "std:auth"
    
    auto:
      setup: |
        # 初始化该服务的配置
        config['behavior'] = '. master com NS tld'
      
      modify: |
        # 修改该服务的配置
        config['cap_add'] = ['NET_ADMIN']
      
      restrict: |
        # 验证该服务的配置
        if 'behavior' not in config:
          result = "ERROR: Missing behavior"
        else:
          result = "PASS"
```

## 脚本格式

### 单个脚本

脚本内容直接写在字符串中：

```yaml
auto:
  setup: |
    config['new_service'] = {'image': 'bind', 'ref': 'std:recursor'}
```

### 多个脚本

使用列表串行执行多个脚本：

```yaml
auto:
  setup:
    - |
      config['builds'] = {}
    - |
      config['builds']['s1'] = {'image': 'bind', 'ref': 'std:auth'}
    - |
      config['builds']['s2'] = {'image': 'bind', 'ref': 'std:recursor'}
```

支持显式格式（虽然目前所有脚本都是 Python）：

```yaml
auto:
  modify:
    - content: |
        config['builds']['s1']['cap_add'] = ['NET_ADMIN']
      type: python
    - content: |
        config['builds']['s2']['cap_add'] = ['NET_ADMIN']
      type: python
```

## 执行环境

每个脚本都在隔离的环境中执行，可访问以下全局变量：

| 变量名 | 类型 | 说明 |
|-------|------|------|
| `config` | `dict` | 当前配置字典（全局脚本传入完整配置，服务级脚本传入该服务配置） |
| `service_name` | `str` \| `None` | 当前服务名（全局脚本为 `None`，服务级脚本为对应的服务名） |
| `result` | `Any` | 仅 `restrict` 脚本使用，存储验证结果 |
| `fs` | `FileSystem` | 文件系统对象，用于文件读写操作 |
| `workdir` | `str` | 工作目录路径（chroot），可用于相对路径操作 |

### 变量使用示例

```python
# 读取文件
content = fs.read_text('resource:/configs/example.conf')

# 写入文件
fs.write_text('temp://temp/config.txt', 'some content')

# 检查路径存在
if fs.exists('file:///path/to/file'):
    data = fs.read_text('file:///path/to/file')
```

### 并行执行
- 服务级 `setup` 脚本：多个服务的脚本 **并行** 执行（但单个服务内的多个脚本串行）
- 服务级 `modify` 脚本：多个服务的脚本 **并行** 执行（但单个服务内的多个脚本串行）
- `restrict` 脚本：所有脚本 **并行** 执行


## 例子

### 1. 动态服务生成

```yaml
auto:
  setup: |
    # 基于配置动态生成多个递归服务
    base_name = "recursor"
    for i in range(3):
      name = f"{base_name}_{i}"
      config.setdefault('builds', {})[name] = {
        'image': 'bind',
        'ref': 'std:recursor',
        'behavior': '. hint 8.8.8.8'
    }
```

### 2. 根据条件修改配置

```yaml
auto:
  modify: |
    # 根据镜像类型为所有服务注入额外参数
    for svc_name, svc_config in config.get('builds', {}).items():
      image_name = svc_config.get('image', '')
      if 'bind' in image_name:
        svc_config.setdefault('cap_add', []).append('NET_ADMIN')
```

### 3. 验证配置完整性

```yaml
auto:
  restrict: |
    # 验证所有服务都有行为定义
    errors = []
    for svc_name, svc_config in config.get('builds', {}).items():
      if not svc_config.get('behavior'):
        errors.append(f"Service '{svc_name}' missing 'behavior'")
    
    if errors:
      result = "ERROR: " + "; ".join(errors)
    else:
      result = "PASS"
```

### 4. 生成行为脚本(服务级)

```yaml
builds:
  auth_server:
    image: "bind"
    ref: "std:auth"
    
    auto:
      setup: |
        # 根据服务级参数生成 behavior
        zone_name = config.get('zone_name', 'example.com')
        config['behavior'] = f"{zone_name} master www A 1.2.3.4"
```

## 约束与限制

### setup 阶段约束

- 在 `setup` 阶段执行后，系统会自动进行 `ref` 解析
- 新增的服务可以继承其 `ref` 对应模板中的 `auto.setup`
- 新增服务的`ref`的对象中包含`auto.setup`，可能还有问题(待修改，目前不支持)

### modify 阶段约束

- `modify` 阶段 **禁止** 在全局配置中使用 `include` 字段
- `modify` 阶段 **禁止** 在服务配置中使用 `ref` 字段
- 这两个限制是为了避免在修改后重新进行解析，保证整个构建流程的确定性

### 脚本执行错误处理

- 脚本执行异常会导致整个构建失败
- 错误消息会在日志中输出，包含脚本位置和异常详情
- 使用 `--debug` 标志可获取更详细的日志信息

## 推荐

1. **使用 setup 进行初始化**：在不需要 ref 解析的场景下，使用 `setup` 生成初始配置
2. **使用 modify 进行微调**：在所有 ref 都解析完毕后，使用 `modify` 进行最终调整
3. **使用 restrict 进行验证**：在构建前，使用 `restrict` 检查配置的有效性和完整性
4. **避免过度复杂的脚本**：脚本应保持简洁，复杂逻辑建议分离为多个脚本
5. **利用并行执行**：服务级脚本会自动并行执行，无需手动优化


## 延伸阅读

- [配置处理流程](processing-pipeline.md)
- [配置概览](index.md)
- [顶层配置](top-level.md)
- [服务配置](builds.md)
- [内部镜像配置](images.md)
