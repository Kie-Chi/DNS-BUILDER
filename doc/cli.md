# CLI 手册

命令入口：`src/dnsbuilder/__main__.py`

参数：
- `config_file`（位置参数）：配置文件路径。
- `--debug`：启用调试日志。
- `--vfs`：启用虚拟文件系统。
- `-g/--graph`：输出网络拓扑 DOT 文件。
- `--ui`：启动后端 API 与静态 UI。

示例：
```
python -m dnsbuilder path/to/dnsbuilder.yml --debug --vfs -g graph.dot
```