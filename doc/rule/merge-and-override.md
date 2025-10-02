# 合并与覆盖规则

本文阐述 DNSBuilder 在配置合并时的“覆盖”语义，帮助你在使用 `include`、标准模板 `ref/std:`、`mixins` 等功能时预测最终结果。

## 合并模型概览

- 基本行为：
  - 字典：递归合并（相同键继续进入下一层）。
  - 列表：按“唯一项并集”合并（以字符串化结果判断唯一性）。
  - 字典/列表混合：尝试将两者都“归一化为字典”再合并；失败则进行覆盖。
  - 其他类型：子值覆盖父值。
- 不变性：对“父”进行深拷贝后生成结果，源数据不会被修改。

## 字典递归合并

- 同键字典会进入下一层继续 `deep_merge`；不存在的键直接拷贝子值。

示例：

```yaml
parent:
  service:
    command: ["named", "-g"]
    env:
      A: a
child:
  service:
    env:
      B: b
```

结果：

```yaml
service:
  command: ["named", "-g"]
  env:
    A: a
    B: b
```

## 列表并集合并

- 列表合并采用“字符串化去重”的并集策略：
  - 先收集父列表的字符串化集合（`{str(item)}`）。
  - 逐项遍历子列表，若字符串化结果不在集合中则追加。
- 注意：
  - 两个结构不同但字符串化后相等的项会被视为重复，从而不追加。
  - 合并后项的顺序为“父项在前，子新项追加在后”。

示例：

```yaml
parent:
  util: ["vim", "dnsutils"]
child:
  util: ["dnsutils", "tcpdump"]
```

结果：

```yaml
util: ["vim", "dnsutils", "tcpdump"]
```

## 字典/列表混合合并

- 当父为字典、子为列表或反之：
  - 先对两者各自调用 `_normalize_to_dict`，将“列表形式的 `KEY=VALUE`”归一化为字典；
  - 成功后对这两个字典执行浅合并（子覆盖同键）；
  - 若任一方归一化失败（抛 `TypeError`），则直接使用“子覆盖父”。

示例：

```yaml
parent:
  environment:
    HTTP_USER: root
child:
  environment:
    - "HTTP_PASS=root"
    - "VAR_ONLY"
```

结果（归一化后浅合并）：

```yaml
environment:
  HTTP_USER: root
  HTTP_PASS: root
  VAR_ONLY: null
```

## 标量与其他类型覆盖

- 既非字典也非列表的类型，统一采用“子覆盖父”的策略。
- 例如：字符串、数字、布尔、空值等直接替换父值。

## 合并的应用场景

- include 预处理：
  - 处理配置（尤其是同名配置的合并，主要为**相同名称的镜像或服务**）
- 服务解析与模板混入：
  - 将父模板（`ref:` 或 `std:`）与 `mixins` 通过 `deep_merge` 与子服务合并，子服务的同键覆盖父/mixin 键

## 注意事项

- 统一用法：
  - 需要“追加”列表项时，确保同项字符串表示不同，以避免被视为重复
  - 对环境变量或 `KEY=VALUE` 列表，优先考虑使用列表形式，可被自动归一化与合并
- 使用建议
  - 对于有多种格式的属性（例如 `command: str | list`），请考虑清楚后续是覆盖还是添加以合理使用某种属性

## 示例：include 合并与覆盖

```yaml
# a.yml
builds:
  bind:
    image: bind
    environment:
      - "HTTP_USER=root"

# b.yml
builds:
  bind:
    environment:
      - "HTTP_PASS=root"
    util: ["vim"]

# 主配置
include:
  - a.yml
  - b.yml
builds:
  bind:
    util: ["dnsutils"]
    environment:
      HTTP_USER: admin  # 覆盖同键
```

合并结果（关键片段）：

```yaml
builds:
  bind:
    image: bind
    util: ["vim", "dnsutils"]
    environment:
      HTTP_USER: admin
      HTTP_PASS: root
```

## 延伸阅读

- [推导式语法](comprehension.md)
- [标准服务模板](build-templates.md)
- [文件路径与FS](paths-and-fs.md)
- [顶层配置（include 用法）](../config/top-level.md)
