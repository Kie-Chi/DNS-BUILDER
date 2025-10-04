# 外部镜像配置

除在顶层 `images` 中声明的内部镜像外，服务还可以直接使用外部镜像。外部镜像分为两类：

- DNSB构建镜像（Local）：`image` 指向一个包含 `Dockerfile` 的目录路径（也可使用DNSB协议文件系统拉取）；由DNSB在构建阶段获取本地构建
- Docker社区镜像（Remote）：`image` 指向一个仓库镜像名（如 `ubuntu:22.04`、`grafana/grafana`）；由Docker拉取并直接使用

## 与内部镜像的区别

- 内部镜像：在顶层 `images` 中声明，支持 `ref`、`software`/`version`/`from` 三元组、依赖与工具的默认值处理，并参与标准模板（`std:`）解析的“软件类型”推断
- 外部镜像：不在 `images` 中声明，直接在服务的 `image` 写字符串使用；不具备“软件类型”，因此无法用于 `std:` 的角色推断

## 用法示例

### DNSB构建

```yaml
builds:
  custom-tool:
    image: "./images/custom-tool"  # 指向包含 Dockerfile 的目录
    build: true
    volumes:
      - "${origin}./custom-tool/contents:/usr/local/etc"
```

说明：

- 路径可为DNSB中可支持的任意路径，详见[文件路径与FS](../rule/paths-and-fs.md)；相对路径相对于主配置文件所在目录解析
- 该路径指向的目录应包含 `Dockerfile` 及相关构建上下文文件，或直接指向 `Dockerfile`文件

### Docker社区

```yaml
builds:
  grafana:
    image: "grafana/grafana:latest"
    ports:
      - "3000:3000"
    volumes:
      - "${origin}./grafana/contents:/var/lib/grafana"
```

说明：

- 符合Docker Compose的[image要求](https://docs.docker.com/reference/compose-file/services/#image)
- 仍可透传 Compose 字段（如 `ports`、`environment`、`volumes` 等）

## 约束与注意事项

- `std:` 模板、`behavior`等内置行为与“软件类型”相关，需从内部镜像的  `software`类型推断；因此外部镜像 **均不适用**
- 外部镜像无法被内部镜像所引用

## 何时选择外部镜像

- 直接使用社区或厂商提供的镜像（如 `grafana/grafana`、`google/cadvisor`）。
- 已有用户自定义的、成熟的 `Dockerfile` 构建上下文，且不需要内部镜像的校验与模板扩展。

更多内部镜像的声明与约束，详见[内部镜像配置](images.md)

## 延伸阅读

- [内部镜像配置](images.md)
- [服务配置](builds.md)
- [文件路径与FS](../rule/paths-and-fs.md)
