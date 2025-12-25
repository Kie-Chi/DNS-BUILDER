# 概览

本页汇总 DNSBuilder 的语法与规则，帮助你在编写配置时理解

- 如何通过自动化脚本生成配置
- 如何合并覆盖
- 如何引用模板
- 如何解析路径

## 主题速览

- 自动化脚本：使用 Python 脚本自动化配置的 setup（初始化）、modify（修改）和 restrict（验证）阶段
- 合并与覆盖：深度合并模型，字典递归、列表去重追加、`KEY=VALUE` 列表归一化合并
- 标准服务模板：以 `std:<role>` 引用标准角色，结合镜像的软件类型解析为 `<software>:<role>`
- 行为 DSL：声明服务行为脚本，生成 BIND/Unbound 等的具体配置
- 内置变量与占位符：支持 `${origin}` 等变量，模板渲染时参与替换
- 文件路径与 FS：协议与 URI 解析、跨文件系统复制规则、`include/files/volumes` 的路径用法

## 何时使用这些规则

- 需要动态生成或修改配置时使用自动化脚本
- 需要合并多份配置或叠加模板、mixin 时依赖合并与覆盖规则
- 需要快速搭建常见角色（递归、权威、转发）时用标准服务模板
- 需要从资源/Git/服务器 拉取配置文件并复制到容器时关注路径与 FS 规则
- 需要理解配置从加载到输出的完整流程时参考[配置处理流程](../config/processing-pipeline.md)

## 延伸阅读

- [配置处理流程](../config/processing-pipeline.md)
- [自动化脚本（Auto）](../config/auto.md)
- [合并与覆盖规则](merge-and-override.md)
- [标准服务模板](build-templates.md)
- [行为 DSL](behavior-dsl.md)
- [内置变量与占位符](builtins-and-placeholders.md)
- [文件路径与FS](paths-and-fs.md)
- [已弃用：推导式语法](../old/comprehension.md)
