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
dnsb demo.yml [--debug]
```

**输出：** 在运行目录下的 `output/demo` 可以看到完整的 `docker-compose` 项目。

## 启动环境

```bash
cd output/demo
docker compose up --build
```

## 下一步

- 了解[配置处理流程](../config/processing-pipeline.md)
- 学习[Auto 自动化脚本](../config/auto.md)的用法
- 查看[配置参考](../config/index.md)了解所有可用选项

## 常见选项

| 选项 | 说明 |
|------|------|
| `--debug` | 输出详细调试日志 |
| `--incremental/-i` | 启用增量构建缓存 |
| `--workdir/-w` | 指定工作目录(`@config`为解析配置的目录，默认为运行命令的工作目录) |
| `--graph <file>` | 生成网络拓扑图（Graphviz 格式） |
| `--vfs` | 使用虚拟文件系统而非本地磁盘 |
