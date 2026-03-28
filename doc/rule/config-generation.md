# DNS Builder 配置生成与挂载机制

本文档详细说明 DNS Builder 如何为不同的 DNS 软件生成配置文件并进行挂载，包括 Section 系统、配置片段管理和 Includer 机制。

---

## 概要

DNSBuilder以挂载文件的后缀`.conf`来识别DNS软件配置并协助挂载，例如`should_be_included.conf`，将被自动引用至DNS软件的主配置中

具体内容详见后续`Section/SectionReference`介绍
```shell
named.conf
>>> is_conf: true, section: global, params: {}

named.a.b.c.d.conf
>>> is_conf: true, section: global, params: {}

named.conf.options
>>> is_conf: true, section: options, params: {}

named.conf.zone?name=www.example.com
>>> is_conf: true, section: zone, params: {name : "www.example.com"}

```


## 概念

### 1.1 Section 与 SectionInfo

`Section` 系统定义了各 DNS 软件支持的配置块结构。每个软件（BIND、Unbound 等）都有对应的 `Section` 子类，定义其支持的配置块。

**Section 类属性**：

```python
class Section(ABC):
    # 软件特定配置
    conf_suffix: ClassVar[str] = ".conf"    # 配置文件后缀
    include_tpl: ClassVar[str] = ""          # include 语句模板
```

| 属性 | 说明 |
|------|------|
| `conf_suffix` | 配置文件后缀，用于生成文件名 |
| `include_tpl` | include 语句模板，如 `'include "{path}";'` |

**SectionInfo** 描述单个配置块的元数据：

```python
@dataclass
class SectionInfo:
    name: str              # 块名称，如 "options", "zone", "server"
    template: str          # 格式模板，如 "options {{\n{content}\n}};"
    indent: int = 4        # 内容缩进空格数
    params: Set[str] = {}  # 必需参数，如 {"name"} 用于 zone "example.com"
    repeatable: bool = False  # 是否可重复出现
    wrap_re: str = None    # 用于定位块的正则表达式（自动生成）
```

**关键属性说明**：

| 属性 | 说明 |
|------|------|
| `template` | 定义块的格式模板，必须包含 `{content}` 占位符 |
| `params` | 模板参数集合，如 `zone` 块需要 `name` 参数 |
| `repeatable` | `False` 表示块只能出现一次（如 `options`），`True` 表示可多次出现（如 `zone`） |

### 1.2 SectionReference（配置引用）

`SectionReference` 从配置文件路径中解析出目标 section 和参数。

**支持的路径格式**：

```
/path/to/file.conf[?param=value&param2=value2][#section]
```

**解析规则**：

| 格式 | 示例 | 解析结果 |
|------|------|---------|
| 后缀格式 | `named.conf.options` | section = `options` |
| Fragment 格式 | `named.conf#options` | section = `options` |
| 带参数 | `zones.conf?name=example.com#zone` | section = `zone`, params = `{"name": "example.com"}` |

**优先级**：`#fragment` > `.suffix` > `"global"`

### 1.3 ConfigFragment（配置片段）

`ConfigFragment` 表示一个待组装的配置片段：

```python
class ConfigFragment(BaseModel):
    src: DNSBPath              # 源文件路径
    dst: str                   # 容器内目标路径
    dcr: Optional[str]         # Docker-compose 相对路径
    section: str = "global"    # 目标 section
    is_main: bool = False      # 是否为 global main config
    content: Optional[str]     # 可选内容
    params: Dict[str, Any]     # section 模板参数
```

**工作流程**：

1. 只有 `section == "global"` 且 `is_main == True` 的 fragment 成为 **global main config**
2. 其他所有 fragment 添加到 `_pending_fragments` 等待组装

---

## 2. Section 系统详解

### 2.1 各软件支持的 Section

**BIND**：

| Section | repeatable | params | 模板示例 |
|---------|------------|--------|---------|
| global | False | - | `{content}` |
| options | False | - | `options {\n{content}\n};` |
| logging | False | - | `logging {\n{content}\n};` |
| zone | True | `name` | `zone "{name}" {\n{content}\n};` |
| acl | True | `name` | `acl "{name}" {\n{content}\n};` |
| key | True | `key_name` | `key "{key_name}" {\n{content}\n};` |
| view | True | `name` | `view "{name}" {\n{content}\n};` |
| controls | False | - | `controls {\n{content}\n};` |
| server | False | - | `server {\n{content}\n};` |

**Unbound**：

| Section | repeatable | 模板示例 |
|---------|------------|---------|
| global | False | `{content}` |
| server | True | `server:\n{content}` |
| remote-control | False | `remote-control:\n{content}` |
| forward-zone | True | `forward-zone:\n{content}` |
| stub-zone | True | `stub-zone:\n{content}` |
| auth-zone | True | `auth-zone:\n{content}` |

**PowerDNS Recursor / Knot Resolver**：

仅支持 `global` section。

### 2.2 Section 模板参数

某些 section 需要额外参数来格式化块头：

**BIND zone 示例**：

```yaml
volumes:
  - ./zones/example.conf?name=example.com#zone:/etc/named/zones/example.conf
```

解析为：
- `section = "zone"`
- `params = {"name": "example.com"}`

生成的配置：
```bind
zone "example.com" {
    # 文件内容...
};
```

**BIND acl 示例**：

```yaml
volumes:
  - ./acls/trusted.conf?name=trusted#acl:/etc/named/acls/trusted.conf
```

生成：
```bind
acl "trusted" {
    192.168.1.0/24;
    10.0.0.0/8;
};
```

---

## 3. Includer 机制

### 3.1 工作原理

`Includer` 负责将所有配置片段组装到 global main config 中。

**核心流程**：

```
┌─────────────────────────────────────────────────────────────────┐
│                      Includer.assemble()                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 检查 self.main  │
                    │ (global main)   │
                    └─────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
┌───────────────┐                         ┌─────────────────┐
│ section ==    │                         │ section !=      │
│ "global"      │                         │ "global"        │
└───────────────┘                         └─────────────────┘
        │                                           │
        ▼                                 ┌─────────┴─────────┐
┌───────────────┐                         ▼                   ▼
│ 直接 include  │                 ┌───────────────┐   ┌───────────────┐
│ 到 main config│                 │ repeatable    │   │ 非 repeatable │
└───────────────┘                 │ = True        │   │ = False       │
                                  └───────────────┘   └───────────────┘
                                          │                   │
                                          ▼                   ▼
                                  ┌───────────────┐   ┌───────────────┐
                                  │ 创建新块      │   │ 尝试注入现有块│
                                  │ 并追加        │   │ 或创建新块    │
                                  └───────────────┘   └───────────────┘
```

### 3.2 Fragment 处理策略

| 条件 | 处理方式 |
|------|---------|
| `section == "global"` | 直接在 main config 末尾追加 include |
| `repeatable == True` | 创建新的块并追加到 main config |
| `repeatable == False` 且块已存在 | 注入 include 到现有块内部 |
| `repeatable == False` 且块不存在 | 创建新块并追加到 main config |

### 3.3 各软件 Includer 实现

所有 Includer 继承自 `BaseIncluder`，只需实现 `inject()` 方法。`include_tpl` 从对应的 Section 类获取。

#### BindIncluder

```python
class BindIncluder(BaseIncluder):
    """BIND-style 配置组装器，使用括号计数注入"""

    def inject(self, content: str, section: str, lines: List[str]) -> Tuple[str, bool]:
        """通过括号计数找到块结束位置，注入内容"""
        # ... 括号计数逻辑 ...
        return updated_content, True  # 或 (content, False) 失败时
```

**特点**：
- `include_tpl` 来自 `BindSection`: `'include "{path}";'`
- 支持 `block_pattern` 检测现有块
- 对于 `options`、`logging` 等非重复块，通过括号计数注入到现有块内
- 对于 `zone`、`acl` 等可重复块，每次创建新块

**生成示例**：

```bind
# options 块注入
options {
    listen-on port 53 { any; };
    # Auto Generated by DNS-Builder
    include "/etc/named/options/custom.conf";
};

# zone 块新建
zone "example.com" {
    # Auto Generated by DNS-Builder
    include "/etc/named/zones/example.conf";
};
```

#### UnboundIncluder

```python
class UnboundIncluder(BaseIncluder):
    """Unbound 配置组装器，不支持注入"""

    def inject(self, content: str, section: str, lines: List[str]) -> Tuple[str, bool]:
        """Unbound 无明确块结束标记，不支持注入"""
        return content, False
```

**特点**：
- `include_tpl` 来自 `UnboundSection`: `'include: "{path}"'`
- 所有 section 都视为可重复（不支持注入）
- 使用 Section 模板包装 include

**生成示例**：

```yaml
# Auto Generated by DNS-Builder
server:
    # Auto Generated by DNS-Builder
    include: "/etc/unbound/server.conf"

# Auto Generated by DNS-Builder
forward-zone:
    # Auto Generated by DNS-Builder
    include: "/etc/unbound/forward.conf"
```

#### PdnsRecursorIncluder

```python
class PdnsRecursorIncluder(Includer):
    """PowerDNS Recursor 使用 include-dir 指令"""
    _tmpl = '\n# include {config_line}'
    _write = "\n# Auto Generated by DNS Builder\ninclude-dir={include_dir}\n"
```

**特点**：
- 不继承 `BaseIncluder`（使用特殊的 include-dir 机制）
- 将配置文件移动到统一的 include 目录
- 使用 `include-dir` 指令

**生成示例**：

```ini
# Auto Generated by DNS Builder
include-dir=/usr/local/etc/includes
# include original/path.conf -> /usr/local/etc/includes/file.conf
```

#### KnotResolverIncluder

```python
class KnotResolverIncluder(Includer):
    """Knot Resolver 使用 Lua dofile() 函数"""
    _tmpl = "\n-- Auto Generated by DNS Builder\ndofile('{config_line}')\n"
```

**特点**：
- 不继承 `BaseIncluder`（使用 Lua 格式）
- `include_tpl` 来自 `KnotResolverSection`: `"dofile('{path}')"`
- 仅支持 global section

---

## 4. 配置文件路径语法

### 4.1 基本格式

配置文件的挂载路径可以使用特殊语法指定 section 和参数：

```yaml
volumes:
  # 基本格式：容器路径
  - ./local.conf:/etc/named.conf

  # 后缀格式：指定 section
  - ./options.conf:/etc/named.conf.options      # section = "options"
  - ./logging.conf:/etc/named.conf.logging      # section = "logging"

  # Fragment 格式：显式指定 section
  - ./custom.conf:/etc/named.conf#server        # section = "server"

  # 带参数格式
  - ./example.conf:/etc/zones.conf?name=example.com#zone
```

### 4.2 路径解析示例

| 容器路径 | 解析结果 |
|---------|---------|
| `/etc/named.conf` | section = `global`，成为 main config |
| `/etc/named.conf.options` | section = `options` |
| `/etc/named.conf.logging` | section = `logging` |
| `/etc/zones.conf#zone` | section = `zone` |
| `/etc/zones.conf?name=com#zone` | section = `zone`, params = `{"name": "com"}` |
| `/etc/acl.conf?name=trusted#acl` | section = `acl`, params = `{"name": "trusted"}` |

### 4.3 文件命名约定

推荐使用 `.conf.<section>` 后缀命名：

```
configs/
├── named.conf              # global section（主配置）
├── named.conf.options      # options section
├── named.conf.logging      # logging section
├── named.conf.controls     # controls section
└── zones/
    ├── example.conf?name=example.com#zone
    └── test.conf?name=test.com#zone
```

---

## 5. Behavior 配置生成

### 5.1 BehaviorArtifact

`BehaviorArtifact` 是 behavior 生成的输出结构：

```python
class BehaviorArtifact(BaseModel):
    config_line: str                    # 配置行内容
    section: str = "global"             # 目标 section
    section_params: Dict[str, Any]      # section 模板参数
    new_volume: Optional[VolumeArtifact] # 需要生成的文件（如 zone 文件）
    new_records: Optional[List[RR]]     # DNS 记录（Master behavior）
```

### 5.2 配置生成对照表

| Behavior | BIND | Unbound |
|----------|------|---------|
| forward | `zone "x" { type forward; forwarders {...}; };` | `forward-zone:\n\tname: "x"\n\tforward-addr: ...` |
| stub | `zone "x" { type stub; masters {...}; };` | `stub-zone:\n\tname: "x"\n\tstub-addr: ...` |
| master | `zone "x" { type master; file "..."; };` | `auth-zone:\n\tname: "x"\n\tzonefile: "..."` |
| hint | 生成 root.hints + zone 配置 | `root-hints: "..."` (server section) |

---

## 6. 完整使用示例

### 6.1 BIND 递归解析器

```yaml
images:
  bind:
    ref: bind:9.18.0

builds:
  recursor:
    image: bind
    ref: std:recursor
    behavior: . hint root
    volumes:
      # 主配置（global section）
      - ./configs/named.conf:/usr/local/etc/named.conf
      # options 块配置
      - ./configs/named.conf.options:/usr/local/etc/named.conf.options
      # 自定义 zone 配置
      - ./configs/custom.zone?name=custom.local#zone:/usr/local/etc/zones/custom.conf
```

**生成结果**：

`/usr/local/etc/named.conf`:
```bind
# 原有内容...
include "/usr/local/var/bind/rndc.key";

controls {
    inet * port 953 allow { internal-network; } keys { "rndc-key"; };
};

# Auto Generated by DNS-Builder
include "/usr/local/etc/named.conf.options";

# Auto Generated by DNS-Builder
zone "custom.local" {
    # Auto Generated by DNS-Builder
    include "/usr/local/etc/zones/custom.conf";
};

# Auto Generated by DNS-Builder
include "/usr/local/etc/zones/generated_zones.conf";
```

### 6.2 BIND 权威服务器

```yaml
builds:
  auth:
    image: bind
    ref: std:auth
    behavior: |
      . master com NS tld
      com master example NS sld
    volumes:
      - ./configs/auth.conf:/usr/local/etc/named.conf
      - ./configs/acl.conf?name=trusted#acl:/usr/local/etc/acl.conf
```

**生成结果**：

`/usr/local/etc/named.conf`:
```bind
# 原有内容...

# Auto Generated by DNS-Builder
acl "trusted" {
    # Auto Generated by DNS-Builder
    include "/usr/local/etc/acl.conf";
};

# Auto Generated by DNS-Builder
include "/usr/local/etc/zones/generated_zones.conf";
```

`generated_zones.conf`:
```bind
zone "." {
    type master;
    file "/usr/local/etc/zones/db.root";
};

zone "com" {
    type master;
    file "/usr/local/etc/zones/db.com";
};
```

### 6.3 Unbound 转发器

```yaml
images:
  unbound:
    ref: unbound:1.19.0

builds:
  forwarder:
    image: unbound
    ref: std:forwarder
    behavior: example.com forward 8.8.8.8,8.8.4.4
    volumes:
      - ./configs/server.conf:/usr/local/etc/unbound/server.conf
      - ./configs/remote.conf#remote-control:/usr/local/etc/unbound/remote.conf
```

**生成结果**：

`/usr/local/etc/unbound/unbound.conf`:
```yaml
# 原有内容...

# Auto Generated by DNS-Builder
server:
    # Auto Generated by DNS-Builder
    include: "/usr/local/etc/unbound/server.conf"

# Auto Generated by DNS-Builder
remote-control:
    # Auto Generated by DNS-Builder
    include: "/usr/local/etc/unbound/remote.conf"

# Auto Generated by DNS-Builder
include: "/usr/local/etc/zones/generated_zones.conf"
```

---

## 7. 关键文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| SectionInfo | `src/dnsbuilder/sections.py` | Section 元数据定义 |
| Section 实现 | `src/dnsbuilder/bases/sections.py` | 各软件 Section 定义 |
| SectionReference | `src/dnsbuilder/io/path.py` | 路径解析 |
| ConfigFragment | `src/dnsbuilder/datacls/artifacts.py` | 配置片段数据结构 |
| Includer 基类 | `src/dnsbuilder/abstractions.py` | Includer 抽象类 |
| Includer 实现 | `src/dnsbuilder/bases/includers.py` | 各软件 Includer |

---

## 8. 扩展开发

### 8.1 添加新的 Section

```python
from dnsbuilder.sections import Section, SectionInfo
from dnsbuilder import constants

class MyDNSSection(Section):
    # 软件特定配置
    conf_suffix: str = ".conf"
    include_tpl: str = 'include "{path}";'

    @classmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        return {
            "global": SectionInfo(name="global", template="{content}"),
            "server": SectionInfo(
                name="server",
                template="server {\n{content}\n}",
                indent=4,
                repeatable=False,
            ),
            "zone": SectionInfo(
                name="zone",
                template='zone "{name}" {{\n{content}\n}};',
                indent=4,
                params={"name"},
                repeatable=True,
            ),
        }
```

### 8.2 添加新的 Includer

推荐继承 `BaseIncluder`，只需实现 `inject()` 方法：

```python
from typing import List, Tuple
from dnsbuilder.abstractions import BaseIncluder

class MyDNSIncluder(BaseIncluder):
    """MyDNS 配置组装器

    include_tpl 从 MyDNSSection.include_tpl 获取
    """

    def inject(self, content: str, section: str, lines: List[str]) -> Tuple[str, bool]:
        """
        注入内容到现有块中。

        如果软件支持块注入，返回 (修改后的内容, True)。
        如果不支持，返回 (原内容, False)，BaseIncluder 会自动创建新块。
        """
        # 不支持注入的情况
        return content, False
```