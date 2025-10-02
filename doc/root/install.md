# 安装与运行

## 安装
```shell
git clone https://github.com/Kie-Chi/DNS-BUILDER.git && \
cd DNS-BUILDER && \
pip install .
```

## 运行(CLI)
```shell
dnsb config.yml [cli-args]
```

- `--debug`：DEBUG模式，输出更加详细的日志
- `-h`：获取CLI参数帮助
- `-g/--graph GRAPH_PATH`：生成构建过程服务拓扑环境，保存至 `GRAPH_PATH`处
- `--vfs`：内存构建，不使用真实磁盘空间

## 运行(GUI)
```shell
dnsb --ui
```

- 目前仅有API
