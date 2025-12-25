# 已弃用的文档（Old）

本目录包含已过时、即将删除或不再推荐使用的功能的文档。这些功能仍在代码中可用（以保持向后兼容），但不应在新项目中使用

## 包含的文档

- [推导式语法](comprehension.md) **已弃用**
  - 用于批量生成 `images` 或 `builds` 的条目
  - 推荐替代：使用 [Auto 自动化脚本](../config/auto.md) 的 `setup` 阶段实现相同功能
  - 删除计划：将在未来版本中移除

## 迁移指南

如果你正在使用这些已弃用的功能，以下是迁移到新推荐方式的步骤：

### 推导式语法 → Auto Setup

**旧方式（推导式）：**
```yaml
builds:
  - name: "service-{{ value }}"
    for_each:
      range: [1, 3]
    template:
      image: "bind"
      ref: "std:auth"
```

**新方式（Auto）：**
```yaml
auto:
  setup: |
    for i in range(1, 4):
      config.setdefault('builds', {})[f'service-{i}'] = {
        'image': 'bind',
        'ref': 'std:auth'
      }

builds: {}
```

## 相关文档

- [Auto 自动化脚本 - 迁移指南](../config/auto.md)
- [配置概览](../config/index.md)
- [配置处理流程](../config/processing-pipeline.md)
