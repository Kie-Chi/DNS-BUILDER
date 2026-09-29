# 安装与运行

## 环境准备

- Python 3.12 或更高版本（推荐使用项目虚拟环境）
- Docker 与 Compose：需已安装并可用的 Docker 环境（Windows 建议 Docker Desktop + WSL2）。验证：`docker --version` 与 `docker compose version` 均正常输出
- 启用 DNSSEC 时：默认需要宿主机 `dnssec-signzone`；也可设置 `util_mode: docker` 与本地 `util_image`。`pdnsutil` 不属于必要依赖，PowerDNS metadata 使用 Python 标准库 `sqlite3`。

## 安装

```shell
git clone https://github.com/Kie-Chi/DNS-BUILDER.git && \
cd DNS-BUILDER && \
python -m pip install .
```

## 运行(CLI)

```shell
dnsb COMMAND CONFIG_FILE [OPTIONS]
```

### 常用命令

- `build`: 构建项目配置
- `run`: 构建并启动容器
- `up`: 启动已构建的项目
- `down`: 停止并清理容器
- `shell`: 进入容器 shell
- `logs`: 查看容器日志
- `ps`: 列出容器状态
- `clean`: 清理镜像
- `update`: 检查并可选安装新版本

详细命令说明请查看 [CLI 命令参考](../cli.md)

### 常用选项

- `--debug`：DEBUG模式，输出更加详细的日志
- `-h`：获取CLI参数帮助
- `-g/--graph GRAPH_PATH`：生成构建过程服务拓扑环境，保存至 `GRAPH_PATH`处
- `--vfs`：内存构建，不使用真实磁盘空间
- `-l/--log-levels`: 模块级控制日志
- `-f/--log-file`: 保存log文件
- `-i/--incremental`: 启用增量构建缓存
- `-w/--workdir WORKDIR`: 指定工作目录
  - 默认为配置文件所在目录（输出为该目录下的 `output/<name>`）
  - `@config` 代表配置文件所在目录
  - 也可使用相对路径（相对于当前目录）或绝对路径

### 版本检查与更新

DNSBuilder 的普通命令会按缓存周期检查 GitHub tags；发现新版本时只显示提示，不会自动修改环境。需要手动检查时执行：

```shell
dnsb update
```

确认后安装新版本：

```shell
dnsb update --upgrade
# 自动确认安装
dnsb update --upgrade --yes
```

启动检查不会阻塞构建。可使用 `--no-update-check` 或 `DNSB_UPDATE_CHECK=0` 关闭；显式运行 `dnsb update` 仍会检查。检查周期、超时、API 地址和 pip 源的环境变量详见 [CLI 命令参考](../cli.md#update)。

#### 日志示例

```shell
# 全局调试 + 指定子模块级别（别名：sub、res、svc、bld、io、fs、conf、api、pre）
dnsb demo.yml --debug -l "res=INFO"

# 为顶层 builder 应用（自动补全为 dnsbuilder.builder）
dnsb demo.yml -l "builder.*=DEBUG"

# 使用环境变量（CLI 参数优先生效）
setx DNSB_LOG_LEVELS"sub=DEBUG,fs=WARNING"
dnsb demo.yml

```


## 运行(GUI)

```shell
dnsb --ui
```

- 目前仅有API

## DNSSEC 工具

```yaml
util_mode: host
# util_auto_install: true  # 仅在明确允许自动安装时打开
```

在没有宿主机 BIND 工具的环境中，DNSBuilder 会在 `util_mode: docker` 下使用仓库内置 Dockerfile 构建默认工具镜像：

```yaml
util_mode: docker
```

默认镜像为 `dnsbuilder/dnssec-tools:9.18.4`，Dockerfile 基于明确的 `docker.1ms.run/library/debian:12.11-slim`，安装 `bind9-utils` 后只用于构建期签名。若已有自己的工具镜像，可以覆盖：

```yaml
util_mode: docker
util_image: my-registry.example/bind-tools:9.18.4
```

自定义 `util_image` 必须预先在本地存在；DNSBuilder 不会自动拉取或构建覆盖镜像。默认工具镜像只会从仓库内置 Dockerfile 执行 `docker build --pull=false`，因此缺少基础镜像时会明确失败并提示准备镜像。
