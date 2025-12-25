# DNSB

DNSBuilder 是用于构建与模拟 DNS 环境的工具，包含：

- CLI：完整功能，可直接从配置生成构建产物
- API：基于 FastAPI，提供项目、构建、资源等接口；当前 UI 尚未完工

本文档帮助你快速了解、安装、使用与扩展 DNSB

## 端口与运行提醒

- 后端 API：
  - 执行 `dnsb --ui` 将启动后端服务，默认地址为 `http://localhost:8000`, 当前仅提供 API，无完整 Web U
  - API 使用示例见 [API使用](api/index.md) 与 OpenAPI
- 文档预览：本地预览文档默认使用 `http://localhost:8001`（示例命令：`mkdocs serve -a 127.0.0.1:8001`）
- 端口占用：如 `8000/8001` 被占用，请关闭占用进程或临时调整预览端口以避免冲突

## 快速路径

- 文件路径与挂载：建议先阅读资源路径与文件系统的说明，了解 `resource:/`、相对/绝对路径的复制与挂载行为。详见[文件路径与FS](rule/paths-and-fs.md)
- [按要求安装](root/install.md)后，参考[快速开始](root/getting-started.md)，按示例运行 `dnsb config.yml [--debug]`，并在输出目录执行 `docker compose up --build` 完成环境搭建
- 遇到问题请查看[配置参考](config/index.md)与[FAQ](faq.md)，重点关注循环引用、模板使用与路径挂载等常见误区
- 需要在配置生成或修改阶段执行自定义逻辑时，使用 [Auto 自动化脚本](config/auto.md)
- 想要理解配置的完整处理流程时，参考[配置处理流程](config/processing-pipeline.md)
