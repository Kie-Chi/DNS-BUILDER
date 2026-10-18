# KeyTrap reproduction case

这个目录是一个可供验证工具和大模型参考的最小化案例。案例固定分成三部分：

1. **CVE/PoC 原料**：`main.yml` 和 `resource/keytrap/`；
2. **生成的 Docker 环境**：`output/keytrap/`；
3. **结构化说明**：`case.yaml`（本文件负责补充人类可读的运行说明）。

## 结构化入口

优先读取 [`case.yaml`](case.yaml)。新案例可以复制它，只修改 `cve`、`nodes`、`connections` 和 `poc` 四个区块。

其中最重要的约定是：

- `nodes[].name` 必须与实际 Docker 容器名一致；本例使用 `keytrap-<service>`。
- `main.yml:name`、Compose 项目名和容器名前缀必须相同，都是 `keytrap`。
- `connections` 只记录攻击过程中的通信关系，不记录所有支撑服务内部关系。
- 镜像标签会包含内容哈希（例如 `dnsb-unbound-1.19.0-...`）；迁移时需要连同镜像归档一起保存。

## 1. CVE / PoC 原料

| 类型 | 路径 | 用途 |
| --- | --- | --- |
| CVE | `CVE-2023-50387`、`CVE-2023-50868` | KeyTrap / DNSSEC 验证开销攻击 |
| DNSB 配置 | [`main.yml`](main.yml) | 声明网络、镜像、递归解析器和权威链 |
| 攻击素材 | `resource/keytrap/colliding_keys.txt` | 冲突 DNSKEY 记录 |
| 攻击素材 | `resource/keytrap/fake.rrsig` | 伪造 RRSIG 记录 |
| 生成脚本 | `resource/keytrap/gen-key.py` | 生成指定 Key Tag 的 DNSKEY |
| 生成脚本 | `resource/keytrap/gen-rrsig.py` | 生成伪造 RRSIG |
| 自动化脚本 | `resource/keytrap/start.sh` | 生成/刷新 `fake.rrsig` |
| 触发脚本 | `resource/keytrap/query.py` | 通过 Unbound 查询 `www.example.com.` |

`main.yml` 中的 `sld` 服务是攻击基础设施，`resolver` 是漏洞目标；其中的 `dnssec.hooks` 负责把攻击素材插入到 `example.com` 区域的生成流程中，`client` 启动后运行 `query.py` 查询 `www.example.com.` 触发验证路径。

> **当前状态说明**：本例的 `main.yml` 已设置 `sld.dnssec.enable: true`。执行 `dnsb build` 时，DNSSEC hooks 会把 `colliding_keys.txt` 和 `fake.rrsig` 注入到 `example.com` 区域；随后 `client` 容器运行 `query.py` 查询 `www.example.com.`，触发 `resolver` 的 DNSSEC 验证路径。

## 2. 生成的 Docker 环境

已经用下面的命令生成了本地 Docker Compose 工程：

```bash
cd examples/bugs/keytrap
uv run dnsb build main.yml
```

产物目录为 [`output/keytrap/`](output/keytrap/)，关键文件如下：

```text
output/keytrap/
├── docker-compose.yml
├── .images/*/Dockerfile
├── client/
├── resolver/
├── root/
├── tld/
├── sld/
├── net/                  # std-auth 自动生成的支持服务
└── servers/              # std-auth 自动生成的地址服务
```

Compose 项目名是 `keytrap`，服务名和容器名的对应关系如下：

| Compose 服务 | 容器名 | 地址 | 作用 |
| --- | --- | --- | --- |
| `client` | `keytrap-client` | `10.10.0.5` | 发起 DNS 查询 |
| `resolver` | `keytrap-resolver` | `10.10.0.6` | Unbound 递归/验证解析器 |
| `root` | `keytrap-root` | `10.10.0.7` | 根区权威服务 |
| `tld` | `keytrap-tld` | `10.10.0.8` | `.com` 权威服务 |
| `sld` | `keytrap-sld` | `10.10.0.9` | `example.com` 权威服务和 PoC 目标 |
| `net` | `keytrap-net` | `10.10.0.3` | `std-auth` 生成的 `net` 支持服务 |
| `servers` | `keytrap-servers` | `10.10.0.4` | `std-auth` 生成的服务地址记录 |

### 销毁前保存镜像

需要保留实际 Docker 镜像时，在执行 `docker compose down --rmi ...` 或清理 Docker 之前运行：

```bash
cd examples/bugs/keytrap
compose=output/keytrap/docker-compose.yml
docker compose -f "$compose" build
docker image save -o output/keytrap/keytrap-images.tar \\
  $(docker compose -f "$compose" config --images | sort -u)
```

恢复时执行：

```bash
docker image load -i output/keytrap/keytrap-images.tar
```

`output/keytrap/docker-compose.yml` 和 `.images/` 是可重建的文本产物；`keytrap-images.tar` 是可选的本地镜像快照，不应作为稳定的服务标识。当前工作机的 Docker daemon 未启动，因此这里只生成了 Compose/Dockerfile 产物，没有生成镜像归档。

## 3. 连接关系

验证时按 [`case.yaml`](case.yaml) 的 `connections` 读取连接关系。核心 DNS 查询路径是：

```text
client → resolver → root → tld → sld → resolver
```

- `client` 通过环境变量 `R=10.10.0.6` 指向 `resolver`。
- `resolver` 的 root hints 指向 `root`（`10.10.0.7`）。
- `root` 将 `com` 委派给 `tld`，`tld` 再将 `example.com` 委派给 `sld`。
- `sld` 返回 PoC 相关的 DNSSEC 响应，`resolver` 执行验证。
- `net` 和 `servers` 是 `std-auth` 自动生成的支撑服务，记录服务名到固定 IP 的映射，不是攻击查询链上的业务节点。

## 验证入口

```bash
cd examples/bugs/keytrap
uv run dnsb build main.yml
docker compose -f output/keytrap/docker-compose.yml up --build -d
docker compose -f output/keytrap/docker-compose.yml ps
docker compose -f output/keytrap/docker-compose.yml logs client
```

验证完成后，如果已经按上面的步骤保存镜像，可以销毁运行中的容器：

```bash
docker compose -f output/keytrap/docker-compose.yml down --remove-orphans
```
