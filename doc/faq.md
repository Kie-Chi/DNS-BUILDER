# FAQ

本页汇总 DNSB 使用中常见报错与解决方法，按错误类型与场景归档，建议配合 `--debug` 查看详细日志定位问题

## 通用排错建议

- 启用调试日志：运行 CLI 时追加 `--debug`，或运行 API 时查看控制台输出。
- 最小化配置复现：先移除复杂 include/模板/DSL，仅保留核心字段，逐步加回。
- 路径与挂载：阅读[文件路径与FS](rule/paths-and-fs.md)，确认 `resource:/`、相对/绝对路径行为

### 日志与排查

- 全局级别：`--debug` 开启后基础级别为 `DEBUG`；不加时为 `INFO`。
- 模块级微调：`-l/--log-levels` 支持对特定模块单独设定级别，覆盖全局。示例：

  ```shell
  dnsb config.yml --debug -l "res=INFO"    # 使用别名
  dnsb config.yml -l "builder.*=DEBUG"                 # 顶层通配，等价于 dnsbuilder.builder
  setx DNSB_LOG_LEVELS "fs=WARNING,api=DEBUG"        # 环境变量（CLI 参数优先生效）
  dnsb config.yml
  ```
- 别名与自动前缀：

  - 别名包括 `sub、res、svc、bld、io、fs、conf、api、pre`，会扩展为完整模块名。
  - `builder.*` 表示基础 logger（去掉 `.*`）；未以 `dnsbuilder.` 开头但属于已知顶层模块名（如 `builder`、`io`、`api` 等）会自动补全前缀。
- 典型场景：

  - 替换流程细到 DEBUG，其余都不关心：`-l "sub=DEBUG"`

## 配置加载与校验

- ConfigFileMissingError
  - 现象：提示找不到配置文件
  - 常见原因：传入的 `config.yml` 路径错误；API 模式下项目目录意外删除/缺失了 `dnsbuilder.yml`
  - 解决：确认路径正确；API 下在 `.dnsb_cache/workspace/<project_name>/dnsbuilder.yml` 确认配置
- ConfigParsingError
  - 现象：YAML 语法错误（缩进/列表/字符串等）
  - 常见原因：列表缩进不一致；键值少空格；多行文本缩进错误
  - 解决：用 YAML 校验工具检查；统一示例风格为“顶层字典”，避免混用多种结构
- ConfigValidationError
  - 现象：结构校验失败（Pydantic 报错）
  - 常见原因与修复：
    - `builds` 中同时缺少 `image` 与 `ref` → 至少提供其一
    - 使用 `std:` 模板时未提供 `image` → 必须提供 `image`（决定软件类型）
    - `images` 中使用 `ref` 的同时又提供了 `software/version/from` → 二者互斥，改为只用其一
    - 镜像名含冒号或重复 → 去掉冒号并保证唯一
    - `inet` 非合法私有 IPv4 网段 → 使用如 `10.88.0.0/24` 的有效网段

## 定义与引用

- ReferenceNotFoundError
  - 现象：`ref` 指向的镜像/服务不存在
  - 常见原因：大小写不一致；引用了尚未定义的名称；include 合并覆盖导致键缺失
  - 解决：确认被引用项存在且拼写一致；调整 include 顺序或键覆盖策略
- CircularDependencyError
  - 现象：镜像或服务之间形成循环引用
  - 常见原因：A 引用 B、B 又引用 A；链式 `ref` 闭环
  - 解决：打断环路；消除相互引用，使用显式模板或独立定义
- ImageDefinitionError / BuildDefinitionError
  - 现象：镜像或服务定义不合法（冲突键、模板不支持等）
  - 常见原因：镜像既声明 `software/version/from` 又 `ref`；服务 `ref` 指向未知模板；`std:` 模板与 `image` 类型不匹配
  - 解决：遵循互斥与匹配规则；参考[标准服务模版](rule/build-templates.md)确保组合合法
- NetworkDefinitionError（可能出现于固定地址场景）
  - 现象：静态地址或网段不合法
  - 常见原因：`address` 不属于项目 `inet` 子网；格式不符 IPv4
  - 解决：保证 `address` 在 `inet` 范围内且合法

## 构建阶段

- VolumeError
  - 现象：卷处理失败（源路径不存在或不可复制）
  - 常见原因：挂载源未找到；绝对路径复制规则不理解；缺少 `${required}` 占位符实际值
  - 解决：检查路径存在；遵循“绝对路径不复制、相对路径会复制到 `service_name/contents`”的规则；确保占位符有值
- BehaviorError
  - 现象：行为 DSL 解析或生成失败（如 Zone 定义异常）
  - 常见原因：DSL 语法不符合Behavior DSL；变量替换失败；模板不支持该行为
  - 解决：参考[行为 DSL](rule/behavior-dsl.md)规范；简化行为脚本定位问题；核对变量与模板支持范围
- UnsupportedFeatureError
  - 现象：请求了尚未实现的功能或不支持的组合
  - 解决：调整为已支持的配置；关注发行说明与文档中的可用特性

## 路径与文件系统

- InvalidPathError / ProtocolError
  - 现象：路径或协议不支持（如错误的 `resource:/`/自定义协议）
  - 解决：仅使用支持的协议；确认 `resource:/` 路径存在于内置资源
- DNSBPathNotFoundError / DNSBPathExistsError / DNSBNotAFileError / DNSBNotADirectoryError
  - 现象：文件/目录不存在、已存在、类型不符等
  - 解决：核实目标路径；避免对目录执行“写文件”操作或反之；必要时调整 `parents=True` 创建目录
- ReadOnlyError
  - 现象：在只读文件系统上尝试写入
  - 解决：确认当前 FS 模式（仅磁盘文件系统与内存文件系统可写，其他协议文件系统均只可读），在需要写入的场景使用可写 FS

## API 使用与状态码

- 404：`ConfigFileMissingError` 或 `ReferenceNotFoundError`
  - 说明：项目或配置缺失；或引用对象不存在。
  - 解决：创建项目并放置 `dnsbuilder.yml`；修正引用名称。
- 422：`ConfigValidationError`
  - 说明：结构校验失败。
  - 解决：按“配置校验”一节逐条修复必填与约束。

## 端口冲突与运行

- 后端服务：`dnsb --ui` 默认使用 `http://localhost:8000`。
- 文档预览：`mkdocs serve -a 127.0.0.1:8001`；与后端区分端口，避免冲突。
- 冲突处理：如 8000/8001 被占用，关闭占用进程或变更预览端口。

## 常见场景速查

- “std: 前缀报错”：未提供 `image` 或 `image` 软件类型与模板角色不匹配
- “循环引用”：简化并打断 `ref` 链；避免 A↔B 互引
- “挂载失败”：检查源路径存在；理解绝对/相对路径复制与挂载规则；确认 `resource:/` 资源可用
- “DSL 生成失败”：缩减行为；核对语法与模板支持；查看调试日志中的解析步骤
