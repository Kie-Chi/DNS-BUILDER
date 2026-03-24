# 插件开发指南

DNSBuilder 支持插件系统，允许你通过自定义 DNS 服务器实现、行为、区域格式和资源来扩展其功能。

## 概述

插件可以注册以下组件来扩展 DNSBuilder：

| 组件 | 说明 |
|------|------|
| **Image** | DNS 软件的 Docker 镜像构建器 |
| **Behavior** | DNS 服务器的行为模式（master、forward、stub 等） |
| **Includer** | 配置文件 include 模式处理 |
| **ZoneGenerator** | 自定义区域文件格式生成(非BIND格式zonefile) |
| **Resources** | 模板、规则、默认值、控制文件、脚本 |
| **Attributes** | 扩展常量（通过 `attributes` 类属性） |

## 插件结构

典型的插件包结构：

```
dnsb_mydns/
├── pyproject.toml
├── src/
│   └── dnsb_mydns/
│       ├── __init__.py          # 插件入口
│       ├── image.py             # Image 实现
│       ├── behavior.py          # Behavior 实现
│       ├── includer.py          # Includer 实现
│       ├── zone.py              # ZoneGenerator（可选）
│       └── resources/
│           ├── images/
│           │   ├── templates/
│           │   │   └── mydns    # Dockerfile 模板
│           │   ├── rules/
│           │   │   └── mydns    # 版本规则
│           │   └── defaults/
│           │       └── mydns    # 默认依赖/工具
│           └── configs/
│               ├── mydns_master_base.conf
│               └── mydns_recursor_base.conf
```

## 创建插件

### 1. 插件类

创建继承自 `Plugin` 的类：

```python
# src/dnsb_mydns/__init__.py
import logging
from typing import Dict, Any

from dnsbuilder.plugins import Plugin, PluginRegistry

from .zone import MyDNSZoneGenerator
from .behavior import MyDNSMasterBehavior
from .includer import MyDNSIncluder
from .image import MyDNSImage

logger = logging.getLogger(__name__)

__version__ = "0.0.1"

class MyDNSPlugin(Plugin):
    """MyDNS 插件"""

    # 必需的元数据
    name = "mydns"
    version = __version__
    description = "MyDNS 服务器支持"
    author = "Your Name"
    priority = 50  # 数值越小越早加载

    # 扩展常量（与 .dnsbattribute 相同的合并逻辑）
    attributes: Dict[str, Any] = {
        "DNS_SOFTWARE_BLOCKS": {
            "mydns": {"global", "zone"}
        },
        "RECOGNIZED_PATTERNS": {
            "mydns": [r"\bmydns\b", r"\bmy-dns\b"]
        }
    }

    def on_load(self, registry: PluginRegistry):
        """注册 MyDNS 实现"""
        logger.info("[MyDNSPlugin] 加载 MyDNS 插件...")

        # 注册 Image
        registry.register_image("mydns", MyDNSImage)

        # 注册 Behavior
        registry.register_behavior("mydns", "master", MyDNSMasterBehavior)

        # 注册 Includer
        registry.register_includer("mydns", MyDNSIncluder)

        # 注册 Zone Generator（可选，用于自定义格式）
        registry.register_zone_generator("mydns", MyDNSZoneGenerator)

        # 注册资源
        registry.register_resources(
            "mydns",
            "dnsb_mydns.resources",
            templates=True,    # images/templates/mydns
            rules=True,        # images/rules/mydns
            defaults=True,     # images/defaults/mydns
            controls=False,    # images/controls/mydns
            scripts=False,     # scripts/mydns
            configs=True       # configs/
        )

    def on_unload(self):
        """插件卸载时的清理工作"""
        logger.info("[MyDNSPlugin] 卸载 MyDNS 插件...")


# 导出供入口点使用
__all__ = ['MyDNSPlugin']
```

### 2. Image 实现

```python
# src/dnsb_mydns/image.py
from dnsbuilder.bases.internal import InternalImage

class MyDNSImage(InternalImage):
    """MyDNS Docker 镜像构建器"""

    def _setup_software(self):
        """软件特定的初始化钩子"""
        # 在默认初始化之后调用
        # 可重写以自定义依赖处理
        pass
```

### 3. Behavior 实现

```python
# src/dnsb_mydns/behavior.py
from dnsbuilder.bases import ForwardBehavior

class MyDNSMasterBehavior(ForwardBehavior):
    """MyDNS master 区域行为"""

    def generate_config(self) -> str:
        """生成区域配置"""
        lines = []
        for zone in self.zones:
            lines.append(f"zone \"{zone.name}\" {{")
            lines.append(f"    file \"{zone.file}\";")
            lines.append("};")
        return "\n".join(lines)
```

### 4. Includer 实现

```python
# src/dnsb_mydns/includer.py
from dnsbuilder.bases import Includer

class MyDNSIncluder(Includer):
    """MyDNS 配置 include 处理器"""

    def get_include_pattern(self, config_name: str) -> str:
        """返回 include 指令模式"""
        return f'include "/etc/mydns/{config_name}";'
```

### 5. Zone Generator（可选）

用于自定义区域文件格式：

```python
# src/dnsb_mydns/zone.py
from dnsbuilder.bases import ZoneGenerator

class MyDNSZoneGenerator(ZoneGenerator):
    """MyDNS 自定义区域文件格式"""

    def generate_soa(self, zone) -> str:
        """以 MyDNS 格式生成 SOA 记录"""
        return f"SOA {zone.name} {zone.primary_ns} {zone.admin_email}"

    def generate_rr(self, record) -> str:
        """以 MyDNS 格式生成资源记录"""
        return f"{record.name} {record.ttl} {record.type} {record.value}"
```

## 资源文件

### templates/{software}

Dockerfile 模板（Jinja2 格式）：

```dockerfile
# images/templates/mydns
FROM {{ base_image }}

# 安装依赖
RUN apt-get update && apt-get install -y \
    {% for dep in dependencies %}
    {{ dep }} \
    {% endfor %}
    && rm -rf /var/lib/apt/lists/*

# 安装 MyDNS
RUN wget {{ download_url }} && \
    tar xzf mydns-{{ version }}.tar.gz && \
    cd mydns-{{ version }} && \
    ./configure && make && make install

# 复制配置
COPY {{ config_file }} /etc/mydns/mydns.conf

CMD ["mydns", "-g"]
```

### rules/{software}

版本到基础镜像的映射（JSON 格式）：

```json
{
    "1.0.0": "ubuntu:20.04",
    "[1.0.0, 2.0.0]": "ubuntu:22.04",
    "2.0.0": null
}
```

规则说明：
- `"version": "base_image"` — 指定版本使用指定基础镜像
- `"[min, max]": "base_image"` — 版本区间内的版本使用指定基础镜像
- `"version": null` — 该版本能够支持

### defaults/{software}

默认依赖和工具包（JSON 格式）：

```json
{
    "default_deps": [
        "build-essential",
        "libssl-dev"
    ],
    "default_utils": [
        "vim",
        "dnsutils",
        "tcpdump"
    ]
}
```

字段说明：
- `default_deps` — 构建期依赖包
- `default_utils` — 运行期工具包

## 插件加载方式

插件可以通过三种方式加载：

### 1. 入口点（推荐）

在 `pyproject.toml` 中配置：

```toml
[project.entry-points."dnsb.plugins"]
mydns = "dnsb_mydns:MyDNSPlugin"
```

在`config`中指定
```yaml
plugins:
  - "dnsb_mydns:MyDNSPlugin"
```

### 2. PYTHONPATH

```shell
export PYTHONPATH=/path/to/mydns/plugin
```

在 `config` 中指定：
```yaml
plugins:
  - "dnsb_mydns:MyDNSPlugin"
```

### 3. DNSB_PLUGINS

```bash
export DNSB_PLUGINS="dnsb_mydns:MyDNSPlugin"
```

在 `config` 中指定：
```yaml
plugins:
  - "dnsb_mydns:MyDNSPlugin"
```

## 扩展常量（attributes）

插件的 `attributes` 类属性用于在加载时扩展 DNSBuilder 的全局常量，与 `.dnsbattribute` 文件使用相同的合并逻辑。

### 合并策略

| 类型 | 合并策略 | 说明 |
|------|----------|------|
| dict | 深度合并 | 递归合并字典，保留原有键值 |
| list | 扩展 | 将新元素追加到列表末尾 |
| 其他 | 替换 | 直接用新值覆盖旧值 |

### 可扩展的常量

| 常量名 | 类型 | 说明 |
|--------|------|------|
| `DNS_SOFTWARE_BLOCKS` | dict | DNS 软件的配置块类型定义 |
| `RECOGNIZED_PATTERNS` | dict | DNS 软件识别的正则模式 |
| `LOG_ALIAS_MAP` | dict | 日志模块名称别名 |
| `SUPPORTED_OS` | list | 支持的操作系统列表 |
| `DEFAULT_OS` | str | 默认操作系统 |
| `BASE_PACKAGE_MANAGERS` | dict | 基础包管理器配置 |
| `SOFT_PACKAGE_MANAGERS` | dict | 软件包管理器配置 |
| `ALIAS_MAP` | dict | 配置字段别名映射 |
| `KNOWN_PROTOCOLS` | set | 已知的路径协议 |
| `BEHAVIOR_TYPES` | set | 支持的行为类型 |

### 常量详解

#### DNS_SOFTWARE_BLOCKS

定义 DNS 软件支持的配置块类型，影响 behavior DSL 的解析：

```python
attributes = {
    "DNS_SOFTWARE_BLOCKS": {
        "mydns": {"global", "zone", "forward"}  # 支持的配置块
    }
}
```

配置块类型说明：
- `global` — 全局配置块（所有软件必须支持）
- `zone` — 区域配置块
- `forward-zone` — 转发区域配置块
- `stub-zone` — 存根区域配置块
- `options` — 选项配置块

#### RECOGNIZED_PATTERNS

定义如何从镜像名称识别 DNS 软件类型：

```python
attributes = {
    "RECOGNIZED_PATTERNS": {
        "mydns": [
            r"\bmydns\b",           # 匹配 mydns
            r"\bmy-dns\b",          # 匹配 my-dns
            r"\bmydns\d",           # 匹配 mydns1, mydns2 等
        ]
    }
}
```

#### BASE_PACKAGE_MANAGERS

添加新的基础包管理器（用于不同操作系统）：

```python
attributes = {
    "BASE_PACKAGE_MANAGERS": {
        "pacman": {
            "supported_os": ["arch"],
            "check_cmd": "command -v pacman >/dev/null 2>&1",
            "install_cmd": "pacman -Sy --noconfirm {packages}",
            "cleanup_cmd": "pacman -Sc --noconfirm"
        }
    },
    "SUPPORTED_OS": ["arch"]  # 同时添加支持的操作系统
}
```

#### SOFT_PACKAGE_MANAGERS

添加新的软件包管理器（如 pip、npm 等）：

```python
attributes = {
    "SOFT_PACKAGE_MANAGERS": {
        "uv": {
            "check_cmd": "command -v uv >/dev/null 2>&1",
            "install_cmd": "uv pip install {packages}",
            "cleanup_cmd": "",
            "base_requirements": {
                "apt": ["uv"],
                "apk": None  # 不支持
            }
        }
    }
}
```

### 完整示例

```python
class MyDNSPlugin(Plugin):
    name = "mydns"
    version = "0.0.1"

    attributes: Dict[str, Any] = {
        # 深度合并：添加 mydns 的配置块定义
        "DNS_SOFTWARE_BLOCKS": {
            "mydns": {"global", "zone", "forward-zone"}
        },

        # 深度合并：添加 mydns 的识别模式
        "RECOGNIZED_PATTERNS": {
            "mydns": [
                r"\bmydns\b",
                r"\bmy-dns\b",
            ]
        },

        # 扩展列表：添加新的行为类型
        "BEHAVIOR_TYPES": {"CustomBehavior"},

        # 替换：修改默认操作系统
        "DEFAULT_OS": "alpine",

        # 扩展列表：添加支持的操作系统
        "SUPPORTED_OS": ["arch", "fedora"],
    }

    def on_load(self, registry: PluginRegistry):
        # attributes 会在插件加载前自动合并
        registry.register_image("mydns", MyDNSImage)
        # ...
```

### 加载顺序

常量合并发生在插件 `on_load` 方法调用之前：

1. 加载 DNSBuilder 内置常量
2. 加载 `.dnsbattribute` 文件（如存在）
3. 按插件 `priority` 排序，依次合并各插件的 `attributes`
4. 调用各插件的 `on_load` 方法


## PluginRegistry API

### Image 注册

```python
registry.register_image(
    software="mydns",           # 软件标识符
    image_class=MyDNSImage,     # Image 类
    override=False              # 是否允许覆盖已有注册
)
```

### Behavior 注册

```python
registry.register_behavior(
    software="mydns",
    behavior_type="master",      # master, forward, stub, hint 等
    behavior_class=MyDNSMasterBehavior,
    override=False
)
```

### Includer 注册

```python
registry.register_includer(
    software="mydns",
    includer_class=MyDNSIncluder,
    override=False
)
```

### Zone Generator 注册

```python
registry.register_zone_generator(
    software="mydns",
    generator_class=MyDNSZoneGenerator,
    override=False
)
```

### Resource 注册

```python
registry.register_resources(
    software="mydns",
    package="dnsb_mydns.resources",
    image_templates=True, # 注册 resource:/images/templates/mydns
    build_templates=True, # 注册 resource:/builder/templates/mydns
    rules=True,        # 注册 resource:/images/rules/mydns
    defaults=True,     # 注册 resource:/images/defaults/mydns
    controls=True,     # 注册 resource:/images/controls/mydns
    scripts=False,     # 注册 resource:/scripts/mydns
    configs=True       # 注册 resource:/configs/
)
```

## 完整示例：CoreDNS 插件

参见 `test/dnsb_coredns/` 目录，这是一个完整可运行的示例

## 相关文档

- [动态常量配置](dnsbattribute.md) — 运行时常量覆盖
- [资源与模板](resources.md) — 内置资源
- [标准服务模板](rule/build-templates.md) — 标准服务模板