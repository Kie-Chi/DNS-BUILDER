# 推导式语法（已弃用）

**此功能已过时，即将删除。不推荐在新项目中使用。** 

请使用最新的配置方式（字典格式）直接定义 `images` 和 `builds`。如需大量重复配置，建议使用 `auto.setup` 自动化功能或外部配置生成工具

---

## 迁移

如果你之前使用了推导式语法生成多个相似服务，现在可以改用 `auto.setup`：

**旧方式（推导式，已过时）：**
```yaml
builds:
  - name: "sld-{{ value }}"
    for_each:
      range: [1, 3]
    template:
      image: "bind"
      ref: "std:auth"
      behavior: |
        example.com master www A 1.2.3.{{ value }}
```

**新方式（auto.setup）：**
```yaml
auto:
  setup: |
    for i in range(1, 4):
      name = f"sld-{i}"
      config.setdefault('builds', {})[name] = {
        'image': 'bind',
        'ref': 'std:auth',
        'behavior': f'example.com master www A 1.2.3.{i}'
      }

builds: {}
```


用于批量生成 `images` 或 `builds` 的条目，通过列表项中的推导式块组合 `name` 模板、迭代器与配置模板，实现重复结构的简洁声明

## 语法结构

- 位置：在 `images:` 或 `builds:` 的 **列表项** 中使用，不支持 **字典项使用**
- 必要键：`name`、`for_each`、`template`
- 解析顺序：在预处理阶段读取并展开，随后进入校验与解析

```yaml
# 以 builds 为例
builds:
  - name: "sld-{{ value }}"
    for_each:
      range: [1, 3]
    template:
      image: "bind"
      ref: "std:auth"
      behavior: |
        example.com master www A 1.2.3.{{ value }}
        example.com master mail A 1.2.3.{{ value + 1 }}
```

## for_each 支持的迭代器

- 列表：`for_each: [a, b, c]`，依次将 `value` 设为列表元素，`i` 为索引
- range：`for_each: { range: N }` 或 `for_each: { range: [start, stop] }` 或 `for_each: { range: [start, stop, step] }`

## 上下文变量

- `value`：当前迭代值；用于渲染 `name` 与 `template` 内的字符串字段
- `i`：当前迭代索引（从 0 开始）

## 渲染范围

- 字符串字段将按 Jinja2 模板渲染；对象与数组会递归渲染其中的字符串值
- 冲突检测：若渲染得到的 `name` 与已有条目重复，会报错

## 在 images 中使用（不推荐）

```yaml
images:
  - name: "bind-{{ i }}"
    for_each: 3
    template:
      ref: "bind:9.18.0"
```

## 错误与校验

- 缺少任一必要键（`name`、`for_each`、`template`）会报错
- `for_each.range` 只能是整数或整数列表；否则报错
- 列表项若不是推导式块、显式 `name` 或单键字典，将报错



## 延伸阅读

- [服务配置](../config/builds.md)
- [内部镜像配置](../config/images.md)
- [合并与覆盖规则](merge-and-override.md)
- [文件路径与FS](paths-and-fs.md)
- [Auto 自动化脚本](../config/auto.md)
