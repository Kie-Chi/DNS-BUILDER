# 构建与运行测量

分别测量资源准备、dnsb 构建、镜像构建、服务就绪、正式查询与清理。将时间和协议指标对应到同一实验批次。

## 1. 记录命令耗时

在实验目录设置 `skill_dir` 为 skill 安装目录，将命令交给计时脚本：

```bash
python3 "$skill_dir/scripts/measure_command.py" \
  --out run/build-event.json --label dnsb-build --log-dir run/logs -- \
  dnsb --no-update-check build main.yml --workdir @config

python3 "$skill_dir/scripts/measure_command.py" \
  --out run/verify-event.json --label verify --log-dir run/logs -- \
  bash verify.sh
```

脚本记录 `argv`、`cwd`、起止时间、`duration_s`、`exit_code`、stdout/stderr 路径、长度和 hash，并返回被测命令的退出码。使用独立 label/输出路径保存各阶段与重试。查询和验证脚本自行设置等待超时。

## 2. 记录放大与资源指标

| 指标 | 计算方式 |
| --- | --- |
| 解析器查询放大 | 解析器发往指定观测范围的查询数 ÷ 客户端触发查询数 |
| 目标接收端放大 | 目标接收端实际收到的查询数 ÷ 客户端触发查询数 |
| DNS 字节放大 | 指定方向的 DNS payload 字节 ÷ 触发 payload 字节 |
| 网络字节放大 | 同一网络层、同一时间窗的出站字节 ÷ 输入字节 |
| 验证开销 | 相同输入条件下的解析器 CPU 时间、查询延迟与内存 |
| 释放峰值 | 固定时间片内的包数/字节数及峰值出现时刻 |
| 缓存行为 | 命中/未命中、TTL 变化、重复查询和权威回访 |

在客户端、解析器、权威和接收端分别计数，记录采集位置与过滤器。保存分子和分母；输入数量为零时将比值设为 null。使用服务 CPU 计数器或采样器测量验证开销，使用单调时钟测量查询与等待时间。

## 3. 对比实验批次

- 固定软件版本、并发、缓存准备、触发次数与采集时间窗。
- 分别运行正常输入、修改后输入和移除某一组成部分的输入，按同一指标比较。
- 分开记录资源生成、DNSSEC 签名、Docker 冷/暖构建和 DNS 冷/暖缓存。
- 对每个配置重复运行，保留成功、失败和超时样本，报告中位数与分位数。
- 使用 [manifest.py](../scripts/manifest.py) 标记源码与生成物；比较 DNSSEC 输出时同时记录 key tag、DS、SOA serial 与签名有效期。

## 4. 汇总已有事件

为事件填写 `run_id`，用 `run_start` 的 `condition` 标记实验条件，把命令计时 JSON 作为 `tool_call` 事件写入 JSONL。再运行：

```bash
python3 "$skill_dir/scripts/summarize_events.py" --events run/events.jsonl --out run/summary.json
```

`summarize_events.py` 按批次汇总工具调用数、时间和阶段状态。协议查询计数、pcap 与 CPU 原始样本保存在项目的指标文件中，再按 run_id 对应到批次。报告结构与清理步骤见 [reproduction.md](reproduction.md)。
