# 快速开始

- 准备一个最小配置 `dnsbuilder.yml`：
```
name: demo
inet: 10.88.0.0/16
images: []
builds: {}
```
- 运行 CLI：
```
python -m dnsbuilder path/to/dnsbuilder.yml --debug --vfs -g graph.dot
```
- 启动后端 API（可选）：
```
python -m dnsbuilder --ui
```
然后在文档中查看 API 概览与 OpenAPI。