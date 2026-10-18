# LLM → 可复现 DNS 环境评估

## 通用材料边界（generic-only-v1）

当前 skill 只提供通用方法、独立配置片段和正常 DNS 委派教学骨架，不再包含目标漏洞的完整项目、载荷、固定密钥或专用 verifier。runner 通过显式白名单选择资料，两组收到相同任务要求；workspace 的 task.json 不公开 expected、runtime、rubric 或 fixture 路径。完整 fixture 已移到 `scripts/evaluation/fixtures/`，只供 `--provider fixture` 测验收器。

两组 native agent 都在 checkout 外的临时目录运行；这是减少误读，不是 OS 沙箱。正式实验仍须隔离文件访问、Docker daemon/cache、外网与 CLI 工具，不能以提示词/临时目录代替隔离。当前 runner 版本为 6：真实模型记录 `material_policy: generic-only-v1`，fixture 记录 `fixture-only-v1`。比较脚本排除 fixture、缺失/不匹配材料标记及版本小于 6 的运行，防止沿用旧 repair 回传验收内容的结果。旧运行不被改写，需按新边界与一致预算重新评测。

完整的评估协议、JSONL 事件 schema、token/time 定义、分层验收和统计方法保存在仓库的 `skills/dns-builder/references/evaluation.md`。它将模型轨迹和 DNS 环境验收分开，适用于 `dns-builder` 与 `blank` 两个对照组。

仓库提供三个无第三方依赖的辅助脚本：

```bash
# Record command duration, exit code, and stdout/stderr hashes
python3 skills/dns-builder/scripts/measure_command.py \
  --out run/events/build.json --label dnsb-build --log-dir run/logs -- \
  dnsb --no-update-check build main.yml --workdir @config

# Create an mtime-independent source/build manifest and tree hash
python3 skills/dns-builder/scripts/manifest.py \
  --root output/paper-case --out run/artifacts/manifest.json

# Summarize events by run and by condition/material provenance
python3 skills/dns-builder/scripts/summarize_events.py \
  --events run/events.jsonl --out run/summary.json
```

这些脚本不能取得模型 token；模型调用方必须在每次 API 请求返回时保存供应商原始 usage（包括 input/output/reasoning/cached 字段）和 request latency，再把事件与命令事件按 run_id 合并。Docker daemon 不可用时可以完成配置生成检查，但应将运行验收标为 `not_run`。

## 端到端 runner

仓库内的 `scripts/evaluation/dnsb_agent_runner.py` 记录 PDF 提取、项目生成、模型 ReAct、verifier 独立重跑、分层验收、manifest 和事件轨迹。正式 workspace 项目必须真实执行 `verify.sh`（或 `verify.py`），产生非空检查和命令证据；不能预填 passing 报告。bundle adapter 没有交互式工具通道，只是诊断入口。`dns-builder` 条件继续做构建、Compose 校验、通用结构检查、配置了独立机制验收时的运行检查，以及第二次 clean build；`blank` 不调用 DNS-BUILDER，模型执行和独立重跑通过后由人工确认论文保真与可迁移性。缺少 `evidence.md` 时 runner 只补输入 provenance 和模型 notes，不补机制答案。

**旧 fixture 不是新项目的验收契约。** 任务中的 `fixture_config_path/fixture_expected/fixture_runtime` 仅供 `--provider fixture` 自测。固定服务名、规模、文件路径、脚本关键词及旧触发器不再约束模型项目，结构验收细节也不回传 repair。四个内置任务尚未提供与旧布局解耦的 `independent_runtime`：`--runtime auto` 将该阶段记为 `not_run`，构建/复现通过也只能得到 `partial`；`always` 失败。重复模型自身断言不等于独立机制验收，不能由此声明漏洞成功。

`verification-report.json` 的顶层结果可以写成 `status: "pass"`（也兼容 `passed: true`）；每个检查项可以用 `status: "pass"` 或明确的 `passed: true`。缺少明确结果、存在失败项或没有命令/argv 证据的报告仍会被拒绝。

以论文中的 TsuKing 环境为例，离线检查 runner 自身的完整控制流：

```bash
.venv/bin/python scripts/evaluation/dnsb_agent_runner.py \
  --task tsuking \
  --pdf dnsbuilder.pdf \
  --condition dns-builder \
  --provider fixture \
  --runtime never \
  --output /tmp/dnsb-tsuking-fixture
```

`fixture` 只复制评测侧项目，便于自测；事件写 `usage_source: fixture`、`material_policy: fixture-only-v1` 和空 usage，永远不能作为模型效果数据。上述 `--runtime never` 在其他阶段通过后返回 `partial`；任一构建或语义复现检查失败仍返回 failure。该命令不证明机制，也不运行攻击流量。

真实模型可以使用 OpenAI Responses API：

```bash
export OPENAI_API_KEY=...
.venv/bin/python scripts/evaluation/dnsb_agent_runner.py \
  --task tsuking --pdf dnsbuilder.pdf \
  --condition dns-builder --provider openai \
  --model <model-id> --runtime auto \
  --output evaluation-runs/tsuking-dns-builder
```

模型 bundle 的契约要求 `config_path`（默认 `main.yml`）、完整文本 `files` 和 `verify_path`；fixture 的兼容接口允许空 verifier。runner 拒绝绝对路径、`..` 穿越、`output/` 和 `.dnsb_cache/` 写入；构建失败时只回传模型自身工具输出或通用错误，不回传隐藏结构断言。最多由 `--max-attempts` 控制重试。`--provider command --command "local-model-cli ..."` 可把任意本地模型接入，prompt 通过 stdin 发送；本地命令可以让 `DNSB_USAGE_FILE` 指向包含 `input_tokens`、`output_tokens`、`total_tokens` 等字段的 JSON，或在 stderr 输出一行 `DNSB_USAGE_JSON: {...}`。如果命令不返回供应商 usage，runner 会标为 `usage_source: unavailable`，不会用字符数冒充 token。

也可以直接驱动安装在本机的 coding agent，让它像 Harbor 一样在隔离 workspace 中编辑文件：

```bash
# Codex CLI: retain raw JSONL, ATIF trajectory, and workspace manifest
.venv/bin/python scripts/evaluation/dnsb_agent_runner.py \
  --task tsuking --pdf dnsbuilder.pdf \
  --condition dns-builder --provider agent --agent codex \
  --model <codex-model-id> --runtime auto \
  --output evaluation-runs/tsuking-codex

# Claude Code
.venv/bin/python scripts/evaluation/dnsb_agent_runner.py \
  --task tsuking --pdf dnsbuilder.pdf \
  --condition dns-builder --provider agent --agent claude \
  --model <claude-model-id> --runtime auto \
  --output evaluation-runs/tsuking-claude
```

默认的 `--agent-mode workspace` 要求 CLI 能执行可观测的本地文件/命令工具，是正式 ReAct 对比的模式。`--agent-mode bundle` 保留原始 JSONL/ATIF/usage，但没有已证实的交互式执行，不能进入正式配对。两组 native agent 都在 checkout 外的临时目录运行，减少通过父目录误读仓库。Responses adapter 的 `read_file/write_file` 限定 workspace 路径，但 `run_shell` 是任意宿主 shell；native CLI 的策略也不自动隔离 Docker/cache。它们均需外部容器/VM 才能形成正式访问边界。

例如使用同一模型和参数分别运行信息完整的 `dns-builder` 条件和只给论文的 `blank` 条件：

```bash
MODEL='<same-model-snapshot>'
CODEX_CMD='codex exec --json --skip-git-repo-check \
  -s workspace-write --disable code_mode --disable code_mode_only \
  -c model_reasoning_effort=medium -c model_reasoning_summary=none \
  -C {workspace} --model {model} -'

.venv/bin/python scripts/evaluation/dnsb_agent_runner.py \
  --task tsuking --pdf dnsbuilder.pdf --condition blank \
  --provider agent --agent codex --agent-mode workspace --model "$MODEL" \
  --agent-command "$CODEX_CMD" --runtime auto --max-attempts 2 \
  --output evaluation-runs/tsuking-codex-blank

.venv/bin/python scripts/evaluation/dnsb_agent_runner.py \
  --task tsuking --pdf dnsbuilder.pdf --condition dns-builder \
  --provider agent --agent codex --agent-mode workspace --model "$MODEL" \
  --agent-command "$CODEX_CMD" --runtime auto --max-attempts 2 \
  --output evaluation-runs/tsuking-codex-dns-builder
```

以上参数一致不等于访问隔离或独立机制验收已经完成。正式比较前还须建立独立、允许不同等价布局的验收器，并隔离两组工具/镜像/缓存；不能只用普通失败响应代替论文机制。

`agent` provider 的 `workspace` 模式不要求模型返回 JSON；prompt 会通过 stdin 发送，agent 的当前目录是 checkout 外的临时 workspace，交付源码随后归档到 episode 的 `project/`。`bundle` 模式要求最后返回 JSON bundle，但仍保留同样的原始流。Codex 使用 `codex exec --json`，Claude Code 使用 `claude -p --output-format stream-json`。每次尝试会保留：

* `model/attempt-N.codex.txt` 或 `model/attempt-N.claude.txt`：CLI 原始 stdout（包括非 JSON 警告）；
* `model/attempt-N.agent-events.jsonl`：可直接逐行解析的 JSON 事件；
* `model/attempt-N.trajectory.json`：ATIF-v1.7 兼容的消息、tool call、observation 和 final token metrics 投影；
* `artifacts/agent-workspace-N-raw-manifest.json`：agent 进程结束时的原始 workspace；`agent-workspace-N-manifest.json`：加入 provenance 后、进入 DNS-BUILDER build 的最终 workspace；失败尝试另存为 `agent-workspace-attempt-N/`。`model/attempt-N.trajectory.json` 和 `events.jsonl` 中的 `model-react`、`model-verification` 记录验证轨迹与独立重跑；`artifacts/model-verification-report-attempt-N.json` 保留 runner 重跑前的模型原始报告，`project/verification-report.json` 保留最终报告。两组临时 workspace 的通过安全检查的项目复制到 `project/`，失败尝试保留项目清单/可用轨迹，runner 收尾清理临时目录。

`events.jsonl` 另外为每一条 native agent event 保存事件类型、session id、原始行 hash，并为每个 `Read`/`Edit`/`Bash`（或 Codex/Claude 等价工具）保存 tool 名称、call id、参数 hash、结果 hash 和可得到的 duration。Codex 的 `turn.completed`/`token_count` 和 Claude 的 `result`/assistant usage 会进入 `model_call.usage`；如果 CLI 或中间代理不暴露 usage，字段保持 `null`，不会以字符数估算 token。原始流仍是审计依据。

常用选项如下：

* `--runtime auto|always|never`：`auto` 对缺少独立验收器或 Docker 不可用记录 `not_run`；`always` 判为失败；`never` 禁用该运行阶段（模型 verifier 仍按 gate 执行）。
* `--tool-timeout`、`--model-timeout`：分别限制构建/Compose 命令和模型请求；超时会保留 stdout/stderr 及 hash。
* `--input-price`、`--output-price`、`--cached-input-price`：按供应商价格快照计算 `cost_usd`；省略时只记录原始 token。
* `--allow-model-verify`：对不受 ReAct gate 的 bundle（例如 `dns-builder` adapter）显式重跑其中的 `verify_path`；workspace agent 和所有真实 `blank` episode 会自动执行并记录模型验证，不能用此开关绕过 ReAct 要求。

episode 目录中的 `events.jsonl` 可直接交给汇总脚本：

```bash
.venv/bin/python skills/dns-builder/scripts/summarize_events.py \
  --events /tmp/dnsb-tsuking-fixture/events.jsonl \
  --out /tmp/dnsb-tsuking-fixture/summary.json
```

两组 native agent 的临时 workspace 都在结束前归档到 `project/` 并清理。旧版本只将 blank 放到 checkout 外；当前版本也对 dns-builder 条件使用外部目录。

`artifacts/reproducibility.json` 保存两次原始 manifest/hash 和语义 hash。当前只规范化构建路径、SOA serial、构建注释和已声明的 pip prerequisite 片段；保留 DNSKEY/DS/RRSIG 的密钥、签名、时间、TTL、algorithm 和 key tag，也不把 Unbound directive 顺序全局排序抹平。随机签名材料/配置顺序不同会明确失败，需要任务级声明和独立验证后才能采用更细规范化，不能整块删除 DNSSEC。第二次 build 没有重新运行环境，因此构建一致不等于运行行为一致。blank 保存自己的模型验证与 manifest 后进入人工审核。

每个 episode 结束时还会生成 `artifacts/episode-manifest.json`，列出 `input/`、`model/`、`project/`、`build-*`、`logs/`、`events.jsonl`、`summary.json` 和其它 artifact 的相对路径、字节数与 SHA-256。它让归档或上传后可以检查是否缺失原始 agent 流、trajectory、prompt、stderr、构建输出或验收记录。

两个 episode 可以用比较脚本生成一份 paired JSON（数值 delta 定义为 `dns-builder - blank`）：

```bash
.venv/bin/python scripts/evaluation/compare_episodes.py \
  --skill evaluation-runs/tsuking-codex-dns-builder \
  --blank evaluation-runs/tsuking-codex-blank \
  --out evaluation-runs/tsuking-codex-comparison.json
```

比较文件保留两边 acceptance、manifest/hash 和时间/token；`fairness.eligible` 与 `true_success.pair` 都要求非 fixture、runner 版本至少 6、共同 `generic-only-v1` 材料策略、两组模型执行/独立重跑通过、两组最终 success，外加 dns-builder 的 build/runtime/reproducibility 和 blank 的人工 feasible。没有独立机制验收的 `partial` 不满足门槛；旧/未知材料的运行可作诊断，不能算真实成功。该门槛仍不替代文件/工具/缓存隔离或人工核查。缺失 usage 继续为 `null`。人工已宣称 feasible 却缺少模型 gate 的结果会被拒绝。

`summary.json` 还会给出 `end_to_end_seconds`：自动条件等于 runner 的 wall time，blank 在人工审核后等于模型 episode wall time 加审核耗时。因此 blank 的人工检查不会被误认为免费或零时间。

`summary.json`（schema 3）保留 provider、runner_version 和 material_policy，条件统计按这三个来源字段及 condition 分组；未知/旧材料及 fixture 不与新模型数据混合。另汇总 `model_verification_seconds` 与 `react_tool_calls`。分组 success 是 runner 状态，不是自主复现结论；最终比较仍使用完整门槛并核查独立机制和隔离。人工审核只能在 `model-react` 与 `model-verification` 均为 `pass` 后执行。
