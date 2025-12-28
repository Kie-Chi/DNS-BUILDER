# 安装与运行

## 环境准备

- Docker 与 Compose：需已安装并可用的 Docker 环境（Windows 建议 Docker Desktop + WSL2）。验证：`docker --version` 与 `docker compose version` 均正常输出

## 安装

```shell
git clone https://github.com/Kie-Chi/DNS-BUILDER.git && \
cd DNS-BUILDER && \
pip install .
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
  - 默认为运行命令的当前目录
  - `@config` 代表配置文件所在目录
  - 也可使用相对路径（相对于当前目录）或绝对路径

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
