# 快速开始

## 准备配置文件

创建一个 `demo.yml`：

```yaml
name: "demo"
inet: "10.66.66.0/24"

images:
  bind:
    ref: "bind:9.18.0"

builds:
  recursor:
    image: "bind"
    ref: "std:recursor"
    behavior: . hint root
  
  root:
    image: "bind"
    ref: "std:auth"
    behavior: |
      . master com NS tld
  
  tld:
    image: "bind"
    ref: "std:auth"
    behavior: |
      com master example NS sld
  
  sld:
    image: "bind"
    ref: "std:auth"
    behavior: |
      example.com master www A 1.2.3.4
      example.com master mail A 1.2.3.5
```

**说明：** 该配置文件用于生成一个简单的 `root → tld → sld` DNS 服务环境，模拟现实世界中查询 `*.example.com` 的过程。

## 运行构建

```bash
dnsb build demo.yml [--debug]
```

**输出：** 在运行目录下的 `output/demo` 可以看到完整的 `docker-compose` 项目。

## 启动环境

使用 DNSBuilder CLI 启动：

```bash
# 方式1：构建并启动
dnsb run demo.yml -d

# 方式2：手动启动
cd output/demo
docker compose up --build -d
```

## 管理容器

```bash
# 查看状态
dnsb ps demo.yml

# 查看日志
dnsb logs demo.yml -f

# 进入容器
dnsb shell demo.yml sld

# 重启服务
dnsb restart demo.yml sld

# 停止并清理
dnsb down demo.yml
```

更多命令请查看 [CLI 命令参考](../cli.md)

## 参考

- 了解[CLI 命令参考](../cli.md)掌握所有可用命令
- 了解[配置处理流程](../config/processing-pipeline.md)
- 学习[Auto 自动化脚本](../config/auto.md)的用法
- 查看[配置参考](../config/index.md)了解所有可用选项
- 探索[DNSSEC 支持](../dnssec.md)了解自动签名功能

## 常见选项

| 命令 | 说明 |
|------|------|
| `dnsb build` | 构建项目配置 |
| `dnsb run -d` | 构建并后台启动 |
| `dnsb up -d` | 启动已构建项目 |
| `dnsb down -c` | 停止并清理镜像 |
| `dnsb shell SERVICE` | 进入容器 shell |
| `dnsb logs -f` | 实时查看日志 |

| 选项 | 说明 |
|------|------|
| `--debug` | 输出详细调试日志 |
| `-i, --incremental` | 启用增量构建缓存 |
| `-w, --workdir` | 指定工作目录(`@config`为配置文件目录) |
| `-g, --graph <file>` | 生成网络拓扑图（Graphviz 格式） |
| `--vfs` | 使用虚拟文件系统而非本地磁盘 |
