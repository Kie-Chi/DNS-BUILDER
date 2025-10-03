# 资源与模板

DNSBuilder 提供一组内置资源与模板，位于只读的 `resource:/` 文件系统中。你可以在 `include`、`builds.volumes`、`builds.files`、标准服务模板等位置引用它们，快速搭建常见场景

## 引用方式

- 使用 `resource:/...` 路径引用内置资源，例如：
  - `resource:/includes/monitor.yml`
  - `resource:/configs/bind_recursor_base.conf`
  - `resource:/images/controls/unbound`
- 在 `include` 中引入：
  ```yaml
  include:
    - resource:/includes/sld.yml
    - resource:/includes/traffic.yml
  ```
- 在 `volumes`/`files` 中挂载或写入：
  ```yaml
  builds:
    recursor:
      volumes:
        - "resource:/configs/unbound_recursor_base.conf:/usr/local/etc/unbound/unbound.conf"
        - "resource:/images/controls/unbound:/usr/local/var/unbound:rw"
      files:
        "/usr/local/etc/start.sh": "#!/bin/sh\nexec named -g"
  ```

更多路径与文件系统规则详见[文件路径与 FS](rule/paths-and-fs.md)

## 目录结构概览

内置资源仓库位于 `src/dnsbuilder/resources`，按用途分为以下子目录：

- `includes/`：可直接 `include` 的配置片段（YAML）

  - `sld.yml`：示例包含 Root/TLD/SLD/Recursor 的标准模板组合与行为 DSL
  - `monitor.yml`：监控栈（InfluxDB、cAdvisor、Grafana），依赖 `traffic.yml`(暂不完善)
  - `traffic.yml`：流量采集/统计镜像与服务定义
  - `analyze.yml`：分析脚本运行示例
  - `diy-auth.yml`：自定义权威服务示例
- `configs/`：基础配置文件模板

  - `bind_auth_base.conf`：BIND 权威服务器基础配置
  - `bind_forwarder_base.conf`：BIND 转发器基础配置
  - `bind_recursor_base.conf`：BIND 递归解析基础配置
  - `unbound_forwarder_base.conf`：Unbound 转发器基础配置
  - `unbound_recursor_base.conf`：Unbound 递归解析基础配置
- `images/`

  - `controls/`：控制文件与密钥（随`traffic`挂载）
    - `bind/`：`rndc.key`
    - `unbound/`：`control.conf`、`unbound_control.key/.pem`、`unbound_server.key/.pem`
  - `templates/`：标准服务模板（按软件分类）
    - `bind`、`unbound`、`python`、`judas` 等目录下存放模板片段
  - `rules/`：镜像规则定义（按软件分类）
- `builder/templates`：标准服务模板的聚合定义（JSON），供 `std:<role>`/`<software>:<role>` 解析时使用
- `scripts/`

  - `configs/supervisord.conf`：进程管理配置
  - `py/`：Python 脚本
    - `bind.py`、`unbound.py`：与 DNS 服务相关的操作/示例
    - `stat.py`、`trace.py`：统计与跟踪
    - `none.py`：示例占位脚本
  - `sh/`：Shell 脚本
    - `pcap.sh`、`recv.sh`、`stat.sh`、`trigger.sh`：抓包、接收、统计、触发等工具脚本

### includes 模版的挂载要求

为避免在使用 `include` 引入资源时出现校验错误或运行问题，下面明确每个内置 `includes/*.yml` 的“必须挂载项”和“可选挂载项”。其中 `${required}` 表示该占位符必须在实际使用时被具体值覆盖，否则将触发校验错误

- `sld.yml`

  - 必须挂载项：无（依赖标准服务模板 `std:auth/std:recursor` 自动挂载对应 `resource:/configs/*` 与控制文件）
  - 可选挂载项：可追加自定义 `volumes`/`files`，例如为 `bind`/`unbound` 增加额外配置片段
- `monitor.yml`

  - 必须挂载项：无显式必挂项；
  - 可选挂载项：可按需覆盖或补充 `ports`、`environment`、`volumes` 等 Compose 字段
- `traffic.yml`

  - 必须挂载项：
    - 同时需要环境变量：
      - `ANAME`（被测权威域名或服务名）
      - `RNAME`（递归服务名）
  - 可选挂载项：可添加额外脚本或调整 `FILTER`（pcap 过滤表达式）
- `analyze.yml`

  - 必须挂载项：`${required}:/usr/local/etc/analyze.py`（分析脚本）
  - 可选挂载项：可追加数据文件或结果输出目录
- `diy-auth.yml`

  - 必须挂载项：`${required}:/usr/src/judasdns/config.json`（Judas 权威服务配置）
  - 可选挂载项：可追加自定义脚本、日志目录等
- `cadvisor.yml`

  - 必须挂载项：无显式必挂项
  - 可选挂载项：可调整端口 `8080:8080` 或附加只读挂载

### 脚本用途与使用说明

- `pcap.sh`

  - 作用：根据 `INET` 自动选择匹配网卡，使用 `supervisord` 启动抓包与日志进程，便于持续采集 DNS 流量
  - 必要环境：`INET`（CIDR，如 `10.88.0.0/24`）；可选 `FILTER`（默认 `udp and port 53`）
  - 入口：在 `monitor:traffic` 模板中作为容器启动命令执行
- `stat.sh`

  - 作用：基于 `tcpdump` 的行流，按毫秒周期统计包数量与总大小，输出实时报表
  - 可选环境：`USED_IFACE`（默认 `any`）、`FILTER`（默认 `udp and port 53`）、`POLL_GAP`（默认 `500`ms）
  - 用法：适合在已确定网卡与过滤表达式后进行轻量级实时观测
- `recv.sh`

  - 作用：在指定端口（默认 `23456`）启动 TCP 监听；当收到纯文本 `trigger` 指令时，触发执行 `/usr/local/etc/exec.sh` 并返回结果
  - 运行方式：
    - 前台监听：`bash /path/to/recv.sh`（若缺少 `socat`，脚本会尝试安装）
    - 作为 handler：`echo trigger | socat TCP:HOST:23456 -` 或由 `socat` 使用 `EXEC` 模式回调脚本 `--handle` 分支
  - 约定：在目标主机上提前放置并赋可执行权限的 `exec.sh`（例如执行一次攻击或测试流程）
- `trigger.sh`

  - 作用：向远端监听器发送触发指令，常与 `recv.sh` 配合使用，实现“远程触发本地脚本”
  - 必要环境：`ATTACKER`（目标主机地址或容器名）；可选：`TIMEOUT`（默认 `5` 秒）
  - 用法示例：
    - 在源主机执行：`ATTACKER=attacker-host bash /path/to/trigger.sh`
    - 期望行为：脚本使用 `nc` 连接 `${ATTACKER}:23456`，发送字符串 `trigger`；若远端 `recv.sh` 接收到并执行 `exec.sh`，将返回 `OK` 或错误信息。
  - 故障排查：
    - 检查环境变量是否设置（`ATTACKER`）
    - 确认目标主机运行了 `recv.sh` 且防火墙允许端口 `23456`
    - 网络连通性与工具安装情况（`nc`/`socat`）

## 标准服务模板（Std Templates）

通过 `ref: "std:<role>"` 可以快速声明常见角色的服务配置；系统会根据 `image` 的软件类型（如 `bind`、`unbound`）解析为具体模板（等价于 `<software>:<role>`）。

- 可用角色示例：
  - `bind:recursor`：递归解析器，挂载 `bind_recursor_base.conf` 与必要控制文件
  - `bind:auth`：权威服务器，挂载 `bind_auth_base.conf`
  - `bind:forwarder`：转发器，挂载 `bind_forwarder_base.conf`
  - `unbound:recursor`：递归解析器，挂载 `unbound_recursor_base.conf`
  - `unbound:forwarder`：转发器，挂载 `unbound_forwarder_base.conf`

使用示例：

```yaml
builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
  root:
    image: "bind"
    ref: "bind:auth"  # 显式写法
```

模板详细说明见[标准服务模板](rule/build-templates.md)

## 示例：组合 include 与模板

将内置 `include` 与标准模板合并，可快速搭建监控与基础 DNS 服务：

```yaml
include:
  - resource:/includes/traffic.yml
  - resource:/includes/monitor.yml

images:
  - name: "root"
    ref: "bind:9.18.0"

builds:
  root:
    image: root
    ref: std:auth
    behavior: |
      example.com master www A 1.2.3.4
      example.com master mail A 1.2.3.5
```

## 延伸阅读

- [文件路径与 FS](rule/paths-and-fs.md)（路径协议、复制与落盘规则）
- [标准服务模板](rule/build-templates.md)（角色列表与解析规则）
- [顶层配置](config/top-level.md)《镜像配置》《服务配置》（引用与 include 的综合用法）
