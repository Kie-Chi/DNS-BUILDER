# 动态常量配置

## 概述

`.dnsbattribute` 文件允许你在运行时动态覆盖 DNSBuilder 的常量系统，无需修改源代码。适用于以下场景：

- 添加自定义日志模块别名
- 支持额外的操作系统
- 定义自定义 DNS 软件识别模式
- 添加自定义包管理器
- 扩展 DNS 软件配置块定义

## 文件位置

将 `.dnsbattribute` 文件放在 **workdir** 中（通过 `--workdir` 选项指定的目录，或配置文件所在目录）。文件会在 dnsbuilder 配置初始化时自动加载。

```
workdir/
├── config.yml
├── .dnsbattribute          ← 自动加载
├── top-1k.txt
└── shared/
```

## 配置格式

`.dnsbattribute` 文件使用 YAML 格式，包含要覆盖的常量：

```yaml
# 添加自定义日志别名
LOG_ALIAS_MAP:
  custom: "dnsbuilder.custom.module"
  mylog: "dnsbuilder.my.custom.logger"

# 扩展支持的操作系统
SUPPORTED_OS:
  - alpine
  - rocky

# 添加自定义 DNS 软件识别模式
RECOGNIZED_PATTERNS:
  my_custom_dns:
    - r"\bmydns\b"
    - r"\bcustom-bind\b"
```

## 覆盖策略

加载器支持三种不同的覆盖策略：

### 替换

对于非字典、非列表类型，整个常量被替换：

```yaml
DEFAULT_OS: "alpine"  # 替换整个值
```

### 合并

字典类型进行**深度合并**，保留原有的键值：

```yaml
LOG_ALIAS_MAP:
  new_alias: "dnsbuilder.new.module"
  # 原有别名会被保留
```

结果：
```python
LOG_ALIAS_MAP = {
    "sub": "dnsbuilder.builder.substitute",
    # ... 原有条目 ...
    "new_alias": "dnsbuilder.new.module",
}
```

### 扩展

列表类型会被**扩展**，新元素追加到末尾：

```yaml
SUPPORTED_OS:
  - alpine
  - rocky
```

结果：
```python
SUPPORTED_OS = ["ubuntu", "debian", "alpine", "rocky"]
```

## 示例

### 添加自定义日志别名

```yaml
# .dnsbattribute
LOG_ALIAS_MAP:
  mymod: "dnsbuilder.my.module"
  dbg: "dnsbuilder.debug"
```

然后在环境中使用：
```bash
export DNSB_DEBUG="mymod,dbg"
dnsbuilder build config.yml
```

### 支持Alpine Linux

```yaml
# .dnsbattribute
SUPPORTED_OS:
  - alpine

BASE_PACKAGE_MANAGERS:
  apk:
    supported_os: ["alpine"]
    check_cmd: "command -v apk >/dev/null 2>&1"
    install_cmd: "apk add --no-cache {packages}"
    cleanup_cmd: ""
```

### 添加自定义 DNS 软件

```yaml
# .dnsbattribute
RECOGNIZED_PATTERNS:
  my_dns:
    - r"\bmydns\b"
    - r"\bcustom-bind\b"

DNS_SOFTWARE_BLOCKS:
  my_dns:
    - "global"
    - "zone"
    - "custom-section"
```

### 扩展自定义包管理器

```yaml
# .dnsbattribute
SOFT_PACKAGE_MANAGERS:
  custom_pkg:
    check_cmd: "command -v custom-pkg >/dev/null 2>&1"
    install_cmd: "custom-pkg install {packages}"
    cleanup_cmd: "custom-pkg cleanup"
    base_requirements:
      apt: ["custom-pkg"]
      apk: ["custom-pkg"]
```

## 可覆盖的常量

常用可覆盖的常量：

| 常量 | 类型 | 用途 |
|------|------|------|
| `LOG_ALIAS_MAP` | dict | 日志模块名称别名 |
| `SUPPORTED_OS` | list | 支持的操作系统列表 |
| `DEFAULT_OS` | str | 未指定时的默认操作系统 |
| `RECOGNIZED_PATTERNS` | dict | DNS 软件识别模式 |
| `DNS_SOFTWARE_BLOCKS` | dict | DNS 软件配置块定义 |
| `BEHAVIOR_TYPES` | set | 支持的行为类型 |
| `RESOURCE_PREFIX` | str | 资源 URL 前缀 |
| `STD_BUILD_PREFIX` | str | 标准构建引用前缀 |
| `BASE_PACKAGE_MANAGERS` | dict | 基础包管理器配置 |
| `SOFT_PACKAGE_MANAGERS` | dict | 软件包管理器配置 |

完整列表见 `src/dnsbuilder/constants.py`。

## 日志

属性加载器在 INFO 级别记录所有操作：

```
[AttributeLoader] Loaded attributes from /path/to/.dnsbattribute
[AttributeLoader] Attributes to override: ['LOG_ALIAS_MAP', 'SUPPORTED_OS']
[AttributeLoader] Updated constant 'LOG_ALIAS_MAP'
[AttributeLoader] Updated constant 'SUPPORTED_OS'
```

启用调试日志查看详细的合并操作：

```bash
export DNSB_DEBUG="auto"
dnsbuilder build config.yml
```

## 相关文档

- `constants.py` — 所有常量的源码定义
- [插件开发](plugin.md) — 插件的 `attributes` 属性使用相同机制