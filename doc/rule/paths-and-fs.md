# 文件路径与 FS

系统化说明 DNSBuilder 的路径模型（DNSBPath）、支持的协议与 URI 语法、文件系统（FS）分发与复制规则，以及它们在 `include`、`builds.files`、`builds.volumes`、模板资源等位置的使用与解析。

## 路径模型：DNSBPath

- 字段与语义：
  - `protocol`：协议名；本地文件默认视为 `file`。
  - `host`：URL 的主机部分；`file` 与 `resource` 无主机。
  - `path`：路径主体；对 URL 来说是 `scheme://host/path` 中的 `path`。
  - `query`/`query_str`：查询参数，以字典/原始串表示。
  - `fragment`：片段（`#...`）；对 `git` 用于仓库内路径。
  - `is_origin`：标记来源路径，避免被复制与校验。
- 绝对路径判断：`is_absolute()` 仅判断“路径主体”是否为绝对（以 `/` 开头或 Windows 盘符）；URL 的片段不参与绝对性判断。
- 字符串化与重构：`__str__()` 会按协议重构完整 URI；`_reconstruct()` 保持原协议/主机/查询/片段不变地拼接新路径。
- 复制提示：`need_copy` 为真表示需要将内容落盘到本地工作目录（非 `file` 协议或相对文件路径）。

## 支持的协议与 URI 语法

- 已知协议清单：`constants.KNOWN_PROTOCOLS = {http, https, ftp, s3, gs, file, resource, temp, git}`。
- `file`（隐式或显式）：
  - 形式：`/etc/named.conf`、`./configs/base.conf`、`D:/data/file.txt`。
  - 规则：Windows 路径会被归一化为 POSIX 风格
- `resource:/...`：
  - 指向内置资源包 `dnsbuilder.resources`；只读。
  - 例子：`resource:/configs/bind_recursor_base.conf`。
- `git://<host>/<org>/<repo>.git#<path/in/repo>?ref=<branch|tag|commit>`：
  - 片段必须指定仓库内路径；`ref` 默认 `HEAD`。
  - 系统会将 `git://` 映射为 `https://<host>/<org>/<repo>.git` 进行克隆与检出。
  - 只读；支持复制到磁盘（`copy2disk`）。
  - 例子：`git://github.com/example/dns-assets.git#configs/named.conf?ref=v1.2`。
- 网络协议（`http`、`https`、`ftp`、`s3`、`gs`）：
  - 能被 `DNSBPath` 正确解析，但默认未注册处理器；直接读写将报 `ProtocolError`。
  - 如需使用，请通过 `AppFileSystem.register_handler(protocol, GenericFileSystem(protocol))` 启用。
- `temp:`：内存文件系统，适合测试或临时生成物；默认已注册。

## 文件系统实现与分发

- 分发器：`AppFileSystem` 根据路径的 `protocol` 分发到对应处理器。
  - 默认注册：`file -> DiskFileSystem`、`temp -> MemoryFileSystem`、`resource -> ResourceFileSystem`、`git -> GitFileSystem`。
  - 自定义：可用 `register_handler()` 增/改协议处理器。
  - `create_app_fs(use_vfs)`：在需要“纯内存文件系统”时，用 `use_vfs=true` 覆盖 `file` 为 `MemoryFileSystem`。
- 处理器能力：
  - `DiskFileSystem`：基于 fsspec 的本地磁盘实现；提供 `absolute()`、`copy()`、`copytree()` 等。
  - `GenericFileSystem(protocol)`：通用 fsspec 文件系统，适合网络协议。
  - `ResourceFileSystem`：只读；从资源包读取；支持目录递归复制到磁盘（`copy2disk`）。
  - `GitFileSystem`：只读；克隆到缓存目录并在指定 `ref` 检出；支持复制到磁盘（`copy2disk`）。

## 解析与基准目录

- 基准目录：为主配置文件所在目录
- 通用规则：
  - `resource:/...` 由 `ResourceFS` 直接解析。
  - `file` 且“非绝对”则相对于基准目录解析，推荐写成 `${origin}./relative/path` 以显式声明来源。
  - `git://...#<path>?ref=...` 会被克隆到缓存目录后再复制到目标位置。
- 相关用法入口：`include`、`builds.files`、`builds.volumes`、模板渲染等均基于上述解析与分发。

## 复制与落盘规则

- 复制判定：
  - `DNSBPath.need_copy` 为真时表示需要先将内容复制到本地（例如 `resource:`、`git:` 或相对 `file`）。
  - `is_origin=true` 的路径永远不被复制（用于声明来源目录）。
- 跨文件系统复制：
  - `AppFileSystem.copy(src, dst)`：跨 FS 时退化为“读字节 + 写字节”。
  - `AppFileSystem.copytree(src, dst)`：仅支持以下组合：
    - 同为 `DiskFileSystem`：调用底层 `put(recursive=true)`。
    - `GitFileSystem -> DiskFileSystem`：使用 `gitFS.copy2disk()`。
    - `ResourceFileSystem -> DiskFileSystem`：使用 `resourceFS.copy2disk()`。
  - 其它组合将抛出 `UnsupportedFeatureError`。

## 使用位置与示例

- `include`：

  ```yaml
  include:
    - resource:/includes/sld.yml
    - ./local-extra.yml
  ```

  说明：包含文件会进行相同的预处理（推导式、占位符替换等），并以深度合并规则加入当前配置。
- `builds.files`：

  ```yaml
  builds:
    recursor:
      files:
        "/usr/local/etc/start.sh": "#!/bin/sh\nexec named -g"
  ```

  说明：值既可为资源路径也可为内联字符串；最终写入目标路径。
- `volumes`：

  ```yaml
  builds:
    grafana:
      image: "grafana/grafana"
      volumes:
        - "${origin}./grafana/contents:/var/lib/grafana"
        - "resource:/scripts/configs/supervisord.conf:/usr/local/etc/supervisord.conf"
  ```

  说明：支持资源路径、相对路径，以及绝对路径；权限标记（如 `:rw`）按 Compose 语义透传。
- 从 Git 复制配置到容器：

  ```yaml
  builds:
    bind:
      volumes:
        - git://github.com/example/dns-assets.git#configs/named.conf?ref=v1.2:/usr/local/var/bind/named.conf
  ```

  说明：系统会克隆仓库到缓存目录，检出 `ref`，并将指定文件复制到目标路径。

## 镜像路径

- 本地构建上下文（Local）：

  ```yaml
  builds:
    custom-tool:
      image: "./images/custom-tool"  # 指向包含 Dockerfile 的目录
      build: true
  ```

  解析为本地构建路径；要求存在 Dockerfile。

## 错误与校验

- 未注册协议处理器：抛出 `ProtocolError`。
- 非法路径字符串：抛出 `InvalidPathError`。
- 对只读 FS 的写入：抛出 `ReadOnlyError`（例如 `resource:`、`git:`）。
- 不支持的跨 FS 目录复制：抛出 `UnsupportedFeatureError`。

## 延伸阅读

- [顶层配置](../config/top-level.md)（`include` 的解析与合并）
- [服务配置](../config/builds.md)（`files`、`volumes` 的路径用法）
- [行为 DSL](behavior-dsl.md)（与资源路径及占位符的关系）
- [内置变量与占位符](builtins-and-placeholders.md)（`${origin}` 等变量说明）
