# CLI 命令参考

DNSBuilder 提供了完整的命令行工具，支持项目构建、容器管理、镜像清理等功能

## 全局选项

```bash
dnsb [OPTIONS] COMMAND [ARGS]
```

### 选项

- `--debug`: 启用调试日志输出
- `-l, --log-levels TEXT`: 逐模块设置日志级别（如 `sub=DEBUG,res=INFO`）
- `-f, --log-file TEXT`: 指定日志文件路径
- `--version`: 显示版本信息
- `--help`: 显示帮助信息

### 示例

```bash
dnsb build config.yml -i    # 使用增量模式构建
dnsb clean --all            # 清理所有共享镜像
dnsb ui                     # 启动 Web UI
```

## 命令列表

### build

从配置文件构建 DNS 基础设施

```bash
dnsb build CONFIG_FILE [OPTIONS]
```

**参数：**
- `CONFIG_FILE`: 配置文件路径（.yml 或 .yaml）

**选项：**
- `-i, --incremental`: 启用增量构建缓存
- `-g, --graph PATH`: 生成网络拓扑图（DOT 格式）
- `-w, --workdir PATH`: 工作目录
  - 默认：当前目录
  - `@config`: 配置文件所在目录
  - `@cwd`: 显式使用当前目录
- `--vfs`: 启用虚拟文件系统（内存构建）

**示例：**
```bash
dnsb build test.yml
dnsb build test.yml -i -g topology.dot
dnsb build test.yml -w @config
```

---

### run

构建项目并启动所有容器（相当于 `build` + `docker compose up`）

```bash
dnsb run CONFIG_FILE [OPTIONS]
```

**选项：**
- `-i, --incremental`: 启用增量构建
- `-g, --graph PATH`: 生成拓扑图
- `-w, --workdir PATH`: 工作目录
- `--vfs`: 虚拟文件系统
- `-d, --detach`: 后台运行容器
- `--build`: 强制重新构建 Docker 镜像

**流程：**
1. 构建 DNS 基础设施配置
2. 使用 docker compose 启动所有容器

**示例：**
```bash
dnsb run test.yml -d         # 后台运行
dnsb run test.yml --build    # 强制重建镜像
```

---

### up

启动已构建的项目（跳过 build 步骤）

```bash
dnsb up CONFIG_FILE [OPTIONS]
```

**选项：**
- `-w, --workdir PATH`: 工作目录
- `-d, --detach`: 后台运行

**说明：**
适用于配置未改变，只需快速启动容器的场景

**示例：**
```bash
dnsb up test.yml -d
```

---

### down

停止容器并清理资源

```bash
dnsb down CONFIG_FILE [OPTIONS]
```

**选项：**
- `-w, --workdir PATH`: 工作目录
- `-v, --volumes`: 同时删除卷
- `-c, --clean`: 同时删除镜像

**清理范围：**
1. 停止并删除所有容器
2. 删除项目网络
3. 删除卷（如果指定 `-v`）
4. 删除镜像（如果指定 `-c`）

**示例：**
```bash
dnsb down test.yml           # 仅停止容器
dnsb down test.yml -c        # 停止并清理镜像
dnsb down test.yml -vc       # 完全清理（包括卷）
```

---

### exec

在运行中的服务容器内执行命令。

```bash
dnsb exec CONFIG_FILE SERVICE [COMMAND...] [OPTIONS]
```

**参数：**
- `SERVICE`: 服务名称（支持自动补全）
- `COMMAND`: 要执行的命令（默认：`/bin/bash`）

**选项：**
- `-w, --workdir PATH`: 工作目录
- `-u, --user USER`: 指定用户

**示例：**
```bash
dnsb exec test.yml sld                    # 启动 bash shell
dnsb exec test.yml sld sh                 # 启动 sh
dnsb exec test.yml sld cat /etc/hosts     # 执行命令
dnsb exec test.yml sld -u root bash       # 以 root 用户运行
```

---

### shell

在容器中启动交互式 shell（`exec` 的快捷方式）

```bash
dnsb shell CONFIG_FILE SERVICE [SHELL_CMD] [OPTIONS]
```

**参数：**
- `SERVICE`: 服务名称
- `SHELL_CMD`: Shell 命令（默认：`/bin/bash`）

**示例：**
```bash
dnsb shell test.yml sld          # 启动 bash
dnsb shell test.yml sld sh       # 启动 sh
```

---

### logs

查看服务容器的日志输出

```bash
dnsb logs CONFIG_FILE [SERVICES...] [OPTIONS]
```

**参数：**
- `SERVICES`: 服务名称列表（为空则显示所有服务）

**选项：**
- `-w, --workdir PATH`: 工作目录
- `-f, --follow`: 实时跟踪日志
- `-t, --tail N`: 只显示最后 N 行

**示例：**
```bash
dnsb logs test.yml                  # 所有服务日志
dnsb logs test.yml sld tld          # 特定服务日志
dnsb logs test.yml -f               # 实时跟踪
dnsb logs test.yml sld -f -t 100    # 跟踪最后 100 行
```

---

### ps

显示项目中所有容器的状态

```bash
dnsb ps CONFIG_FILE [OPTIONS]
```

**选项：**
- `-w, --workdir PATH`: 工作目录

**示例：**
```bash
dnsb ps test.yml
```

---

### restart

重启一个或多个服务容器

```bash
dnsb restart CONFIG_FILE [SERVICES...] [OPTIONS]
```

**参数：**
- `SERVICES`: 服务名称列表（为空则重启所有服务）

**选项：**
- `-w, --workdir PATH`: 工作目录

**示例：**
```bash
dnsb restart test.yml              # 重启所有服务
dnsb restart test.yml sld tld      # 重启特定服务
```

---

### clean

清理项目或共享镜像

```bash
dnsb clean [CONFIG_FILE] [OPTIONS]
```

**参数：**
- `CONFIG_FILE`: 配置文件（可选）

**选项：**
- `--all`: 清理所有 `dnsb-*` 共享镜像
- `-w, --workdir PATH`: 工作目录

**清理模式：**
1. **项目模式**（指定 CONFIG_FILE）：清理该项目的镜像
2. **全局模式**（`--all`）：清理所有共享镜像

**示例：**
```bash
dnsb clean test.yml       # 清理项目镜像
dnsb clean --all          # 清理所有共享镜像
```

---

### ui

启动 Web UI 服务器

```bash
dnsb ui
```

**访问地址：** `http://localhost:8000`

**说明：** 提供 API 接口和管理界面

---

## 自动补全

DNSBuilder CLI 支持智能自动补全：

### 配置文件补全

所有需要 `CONFIG_FILE` 的命令都支持自动补全当前目录的 `.yml` 和 `.yaml` 文件：

```bash
dnsb ps <TAB>           # 显示: test.yml, prod.yml, ...
```

### 服务名称补全

`exec`、`shell`、`logs`、`restart` 命令支持服务名称补全：

```bash
dnsb shell test.yml <TAB>   # 显示: sld, tld, root, resolver, ...
```

**注意：** 自动补全会自动过滤掉内部构建器服务（`dnsb-image-builder-*`）。

### 启用补全

Bash/Zsh 补全需要先注册：

```bash
# Bash
eval "$(_DNSB_COMPLETE=bash_source dnsb)"

# Zsh
eval "$(_DNSB_COMPLETE=zsh_source dnsb)"

# 永久启用（添加到 ~/.bashrc 或 ~/.zshrc）
echo 'eval "$(_DNSB_COMPLETE=bash_source dnsb)"' >> ~/.bashrc
```

---

## 日志控制

### 全局调试

```bash
dnsb --debug build test.yml
```

### 模块级日志

使用 `-l/--log-levels` 指定各模块日志级别：

```bash
dnsb build test.yml -l "sub=DEBUG,res=INFO,fs=WARNING"
```

**模块别名：**
- `sub`: 变量替换
- `res`: 资源解析
- `svc`: 服务处理
- `bld`: 构建器
- `io`/`fs`: 文件系统
- `conf`: 配置
- `api`: API
- `pre`: 预处理

**通配符：**
```bash
dnsb build test.yml -l "builder.*=DEBUG"  # 所有 builder 子模块
```

### 日志文件

保存日志到文件：

```bash
dnsb build test.yml -f build.log
```

### 环境变量

也可以通过环境变量设置（CLI 参数优先）：

```bash
export DNSB_LOG_LEVELS="sub=DEBUG,fs=WARNING"
dnsb build test.yml
```

---

## 工作流示例

### 标准开发流程

```bash
# 1. 构建项目
dnsb build test.yml -i

# 2. 启动服务
dnsb run test.yml -d

# 3. 查看状态
dnsb ps test.yml

# 4. 查看日志
dnsb logs test.yml -f

# 5. 进入容器调试
dnsb shell test.yml sld

# 6. 重启服务
dnsb restart test.yml sld

# 7. 停止并清理
dnsb down test.yml -c
```

### 快速迭代

```bash
# 修改配置后重新构建并启动
dnsb run test.yml -i --build

# 只重启改变的服务
dnsb restart test.yml sld tld
```

### 镜像管理

```bash
# 查看项目镜像
docker images | grep test-

# 清理项目镜像
dnsb clean test.yml

# 清理所有共享镜像（释放磁盘空间）
dnsb clean --all
```

## 参考
- [配置文件格式](config/index.md)
