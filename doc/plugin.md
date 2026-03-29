# 插件开发指南

DNSBuilder 支持插件系统，允许你通过自定义 DNS 服务器实现、行为、区域格式和资源来扩展其功能。

## 概述

插件可以注册以下组件来扩展 DNSBuilder：

| 组件 | 说明 |
|------|------|
| **Image** | DNS 软件的 Docker 镜像构建器 |
| **Behavior** | DNS 服务器的行为模式（master、forward、stub 等） |
| **Includer** | 配置文件 include 模式处理 |
| **Section** | 配置块定义（options、zone、server 等） |
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
│       ├── section.py           # Section 实现
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
from .section import MyDNSSection
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

        # 注册 Section（配置块定义）
        registry.register_section("mydns", MyDNSSection)

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

Image 定义 Docker 镜像的构建方式。

| 基类 | 用途 |
|------|------|
| `InternalImage` | 通用内部镜像，从模板构建 |

```python
# src/dnsb_mydns/image.py
from dnsbuilder.abstractions import InternalImage

class MyDNSImage(InternalImage):
    """MyDNS Docker 镜像构建器"""

    def _post_init_hook(self):
        """软件特定的初始化钩子

        在 __init__ 主逻辑之后调用，可重写以：
        - 自定义依赖处理
        - 设置基础 OS
        - 添加默认工具包
        """
        # 示例：设置默认 OS
        if not hasattr(self, 'os') or self.os == 'ubuntu':
            self.os = "debian"
```

**可重写的关键方法**：

| 方法 | 说明 |
|------|------|
| `_post_init_hook()` | 初始化后的自定义逻辑 |
| `_load_defaults()` | 加载默认配置 |
| `_get_template_vars()` | 返回 Dockerfile 模板变量 |

- BIND Image：`src/dnsbuilder/bases/images/` 中的内置实现

### 3. Behavior 实现

Behavior 定义 DNS 服务器的行为模式。

| 基类 | 用途 |
|------|------|
| `Behavior` | 基础行为类，需要实现 `generate()` 方法 |
| `MasterBehavior` | 权威区域行为，自动处理记录生成 |
| `ForwardBehavior` | 转发行为（如有） |

#### MasterBehavior 示例

继承 `MasterBehavior` 时，只需实现 `generate_config_line()` 方法：

```python
# src/dnsb_mydns/behavior.py
from dnsbuilder.abstractions import MasterBehavior, BehaviorArtifact
from dnsbuilder.datacls.contexts import BuildContext

class MyDNSMasterBehavior(MasterBehavior):
    """MyDNS master 区域行为

    解析 behavior DSL: "example.com master www A 3600 1.2.3.4"
    """

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """生成区域配置行

        Args:
            zone_name: 区域名称
            file_path: 区域文件路径
        """
        return f'zone "{zone_name}" {{ file "{file_path}"; }};'

    def generate(self, service_name: str, build_context: BuildContext) -> BehaviorArtifact:
        """生成行为产物

        MasterBehavior 基类已处理大部分记录类型的生成，
        子类通常只需实现 generate_config_line()。
        """
        # 调用父类方法生成记录
        artifact = super().generate(service_name, build_context)

        # 可以在此添加额外的处理逻辑
        return artifact
```

#### ForwardBehavior 示例

```python
# src/dnsb_mydns/behavior.py
from dnsbuilder.abstractions import Behavior, BehaviorArtifact
from dnsbuilder.datacls.contexts import BuildContext

class MyDNSForwardBehavior(Behavior):
    """MyDNS 转发行为"""

    def __init__(self, zone: str, targets: list):
        super().__init__(zone, targets)
        # targets 是目标服务器列表

    def generate(self, service_name: str, build_context: BuildContext) -> BehaviorArtifact:
        """生成转发配置"""
        # 解析目标 IP
        resolved_ips = self.resolve_ips(self.targets, build_context, service_name)

        # 生成配置行
        config_line = f"forward-zone:\n"
        config_line += f"    name: {self.zone}\n"
        config_line += f"    forward-addr: {' '.join(resolved_ips)}"

        return BehaviorArtifact(config_line=config_line)

    @staticmethod
    def resolve_ips(targets, build_context, service_name):
        """解析目标 IP（服务名或 IP 地址）"""
        import ipaddress
        resolved = []
        for target in targets:
            try:
                ipaddress.ip_address(target)
                resolved.append(target)
            except ValueError:
                # 不是 IP，假设是服务名
                ip = build_context.service_ips.get(target)
                if ip:
                    resolved.append(ip)
        return resolved
```
- CoreDNS 行为：`test/plugins/dnsb_coredns/__init__.py`

### 4. Includer 实现

Includer 负责将配置片段组装到主配置文件中。有两种实现模式：

#### 继承 BaseIncluder

适用于有传统 include 指令机制的软件（如 BIND、Unbound）。只需实现 `inject()` 方法：

```python
# src/dnsb_mydns/includer.py
from typing import List, Tuple
from dnsbuilder.abstractions import BaseIncluder

class MyDNSIncluder(BaseIncluder):
    """MyDNS 配置 include 处理器（传统 include 模式）

    include_tpl 从 MyDNSSection 获取（如 'include "{path}";'）
    """

    def inject(self, content: str, section: str, lines: List[str]) -> Tuple[str, bool]:
        """
        注入内容到现有块中。

        如果软件支持块注入（如 BIND 通过括号计数），
        返回 (修改后的内容, True)。

        如果不支持（如 Unbound 无明确结束标记），
        返回 (原内容, False)，BaseIncluder 会自动创建新块。

        Args:
            content: 当前配置文件内容
            section: 要注入的 section 名称
            lines: 要注入的 include 语句列表
        """
        # 如果不支持注入，直接返回 False
        return content, False
```

**BaseIncluder 工作流程**：

1. 对于 `global` section：直接追加 include 到主配置
2. 对于 `repeatable=True` 的 section：创建新块并追加
3. 对于 `repeatable=False` 的 section：
   - 调用 `inject()` 尝试注入到现有块
   - 如果注入失败，创建新块并追加

#### 继承 Includer

适用于无传统 include 机制的软件（如 CoreDNS）。需要实现完整的 `assemble()` 方法：

```python
# src/dnsb_mydns/includer.py
import logging
from dnsbuilder.abstractions import Includer
from dnsbuilder.datacls import ConfigFragment

logger = logging.getLogger(__name__)

class MyDNSIncluder(Includer):
    """MyDNS 配置组装器（自定义 assemble 模式）

    用于无传统 include 指令的软件，需要完全自定义组装逻辑。
    """

    def assemble(self) -> None:
        """
        组装所有待处理的配置片段到主配置文件。

        这是核心方法，必须由子类实现。
        实现时应：
        1. 遍历 self.get_all_sections() 获取所有 section
        2. 对每个 section 调用 self.get_pendings(section) 获取片段
        3. 按软件特定方式处理每个片段
        """
        if not self.main:
            logger.warning("No global main config found")
            return

        # 获取所有 section 和其片段
        for section in self.get_all_sections():
            fragments = self.get_pendings(section)

            for fragment in fragments:
                self._process_fragment(fragment)

    def _process_fragment(self, fragment: ConfigFragment):
        """处理单个配置片段"""
        # 读取生成的配置内容
        content = self.fs.read_text(fragment.src)

        # 按软件特定方式追加到主配置
        append_content = f"\n# Auto-included from {fragment.dst}\n{content}\n"
        self.fs.append_text(self.main.src, append_content)
```

**Includer 基类提供的辅助方法**：

| 方法 | 说明 |
|------|------|
| `add(fragment)` | 注册一个 ConfigFragment |
| `adds(fragments)` | 注册多个 ConfigFragment |
| `get_pendings(section)` | 获取指定 section 的待处理片段 |
| `get_all_sections()` | 获取所有有待处理片段的 section |
| `is_repeatable(section)` | 检查 section 是否可重复 |
| `get_section_info(section)` | 获取 SectionInfo 对象 |

- BIND 风格：`src/dnsbuilder/bases/includers.py` 中的 `BindIncluder`
- CoreDNS 风格：`test/plugins/dnsb_coredns/__init__.py` 中的 `CoreDNSIncluder`

### 5. Section 实现

Section 定义软件支持的配置块结构，包括模板格式、参数和软件特定的配置：

```python
# src/dnsb_mydns/section.py
from typing import Dict
from dnsbuilder.sections import Section, SectionInfo
from dnsbuilder import constants

class MyDNSSection(Section):
    """MyDNS 配置块定义"""

    # ===== 软件特定配置 =====

    # 配置文件后缀（默认使用 constants.DEFAULT_CONF_SUFFIX = ".conf"）
    conf_suffix: str = ".conf"

    # include 语句模板，{path} 会被替换为文件路径
    # BIND: 'include "{path}";'
    # Unbound: 'include: "{path}"'
    # Knot Resolver: "dofile('{path}')"
    include_tpl: str = 'include "{path}";'

    @classmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        return {
            # global section（主配置，无块包装）
            "global": SectionInfo(
                name="global",
                template="{content}",
                indent=0,
            ),
            # server section（可重复出现）
            "server": SectionInfo(
                name="server",
                template="server {\n{content}\n};",
                indent=4,
                repeatable=True,
            ),
            # zone section（需要 name 参数）
            "zone": SectionInfo(
                name="zone",
                template='zone "{name}" {{\n{content}\n}};',
                indent=4,
                params={"name"},
                repeatable=True,
            ),
            # options section（只能出现一次）
            "options": SectionInfo(
                name="options",
                template="options {\n{content}\n};",
                indent=4,
                repeatable=False,
            ),
            # acl section（需要 name 参数，可重复）
            "acl": SectionInfo(
                name="acl",
                template='acl "{name}" {{\n{content}\n}};',
                indent=4,
                params={"name"},
                repeatable=True,
            ),
        }
```

**Section 类属性**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `conf_suffix` | str | 配置文件后缀，默认 `.conf` |
| `include_tpl` | str | include 语句模板，用于 Includer |

**SectionInfo 关键属性**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `name` | str | 块名称 |
| `template` | str | 格式模板，必须包含 `{content}` |
| `indent` | int | 内容缩进空格数，默认 4 |
| `params` | Set[str] | 必需参数名集合 |
| `repeatable` | bool | 是否可重复出现，默认 False |
| `wrap_re` | str | 自定义正则表达式，用于定位 block（可选） |
| `block_pattern` | str | 属性，返回用于定位 block 的正则表达式（自动生成或使用 wrap_re） |

**block_pattern 说明**：

`block_pattern` 是一个 property，由 Includer 使用来定位配置文件中的 block：
- 对于 `global` section，返回 `None`（无 block 需要定位）
- 对于其他 section：
  - 如果提供了 `wrap_re`，使用自定义正则
  - 否则从 `template` 自动生成正则表达式

例如：
- `template="options {{\n{content}\n}};"` 自动生成 `block_pattern = r'options\s*\{'`
- `template='acl "{name}" {{\n{content}\n}};'` 自动生成 `block_pattern = r'acl\s+"[^"]*"\s*\{'`

**配置文件路径语法**：

用户可以通过路径指定 section 和参数：

```yaml
volumes:
  # 后缀格式：named.conf.options -> section = "options"
  - ./options.conf:/etc/named.conf.options

  # Fragment 格式：使用 # 指定 section
  - ./server.conf:/etc/named.conf#server

  # 带参数格式：?name=value 指定参数
  - ./example.conf:/etc/zones.conf?name=example.com#zone
```

### 6. Zone Generator（可选）

用于自定义区域文件格式。默认使用 BIND 格式，插件可注册自定义格式：

```python
# src/dnsb_mydns/zone.py
import time
from typing import List, Optional, Dict, Any
from dnslib import RR, SOA, A, NS, QTYPE, CLASS

from dnsbuilder.builder.zone import ZoneGenerator
from dnsbuilder.datacls import BuildContext
from dnsbuilder.datacls.artifacts import ZoneArtifact

class MyDNSZoneGenerator(ZoneGenerator):
    """MyDNS 自定义区域文件格式

    继承 ZoneGenerator 基类，重写 generate() 方法
    实现自定义的区域文件格式。
    """

    def generate(self) -> List[ZoneArtifact]:
        """
        生成区域文件产物。

        Returns:
            ZoneArtifact 列表，包含区域文件内容
        """
        # 生成 SOA 记录
        serial = int(time.time())
        ns_name = f"{self.service_name}.servers.net."

        # 生成自定义格式的区域文件
        lines = []

        # SOA 记录（自定义格式）
        lines.append(
            f"SOA {self.zone.fqdn} {ns_name} admin.servers.net. "
            f"{serial} 7200 3600 1209600 3600"
        )

        # NS 记录
        lines.append(f"NS {self.zone.fqdn} {ns_name}")

        # 用户记录
        for record in self.records:
            rname = str(record.rname).rstrip('.')
            rtype = QTYPE.get(record.rtype, f"TYPE{record.rtype}")
            rdata = record.rdata.toZone()
            lines.append(f"{rtype} {rname} {record.ttl} {rdata}")

        content = "\n".join(lines)

        return [
            ZoneArtifact(
                filename=f"{self.zone.label}.zone",
                content=content,
                container_path=f"/usr/local/etc/zones/{self.zone.label}.zone",
                is_primary=True
            )
        ]
```

**ZoneGenerator 关键属性**：

| 属性 | 说明 |
|------|------|
| `context` | BuildContext 对象 |
| `zone` | ZoneName 对象，包含 `fqdn`、`label`、`filename` 等 |
| `ip` | 服务 IP 地址 |
| `service_name` | 服务名称 |
| `records` | RR 记录列表 |
| `enable_dnssec` | 是否启用 DNSSEC |

**实际示例参考**：
- BIND 格式：`src/dnsbuilder/builder/zone.py` 中的 `ZoneGenerator`
- AXDNS 格式：`dnsb_axdns/src/dnsb_axdns/zone.py`

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

插件通过以下顺序自动发现和加载：

1. **入口点** — 自动发现已安装包中声明的插件
2. **配置文件** — 加载用户在 config.yml 中指定的插件
3. **环境变量** — 加载 `DNSB_PLUGINS` 指定的插件

### 1. 入口点（推荐发布方式）

在 `pyproject.toml` 中声明入口点，插件安装后会自动被发现：

```toml
[project.entry-points."dnsb.plugins"]
mydns = "dnsb_mydns:MyDNSPlugin"
```

**说明**：
- 入口点声明的插件在包安装后会被 DNSBuilder 自动发现
- 无需在 config.yml 或环境变量中再次指定
- 适合发布到 PyPI 的插件包

### 2. 配置文件（本地开发/未发布插件）

在 `config.yml` 中指定未通过 entry-points 发布的插件：

```yaml
plugins:
  - "dnsb_mydns:MyDNSPlugin"      # 格式：module.path:ClassName
  - "my_local_plugin"              # 自动发现模块中的 Plugin 子类
```

**说明**：
- 适用于本地开发中的插件
- 适用于不想发布到 PyPI 的私有插件
- 格式支持 `"module.path:ClassName"` 或 `"module.path"`（自动发现）

### 3. 环境变量

```bash
export DNSB_PLUGINS="dnsb_mydns:MyDNSPlugin,another_plugin:AnotherPlugin"
```

**说明**：
- 多个插件用逗号分隔
- 适用于临时测试或 CI/CD 环境

### 加载优先级

当同一插件通过多种方式指定时：
- 按发现顺序加载，先发现者优先
- 后发现的同名插件会被跳过
- 最终按 `priority` 属性排序后依次加载

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
        # 注册 Section（配置块定义）
        registry.register_section("mydns", MyDNSSection)
        # 注册其他组件...
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

### Section 注册

```python
registry.register_section(
    software="mydns",
    section_class=MyDNSSection,
    override=False
)
```

Section 类定义软件支持的配置块，详见 [配置生成机制](config-generation.md)。

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