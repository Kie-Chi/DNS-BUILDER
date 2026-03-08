# Dynamic Constants Configuration (.dnsbattribute)

## Overview

The `.dnsbattribute` file allows you to dynamically override DNS Builder constants at runtime without modifying the source code. This is useful for:

- Adding custom logging module aliases
- Supporting additional operating systems
- Defining custom DNS software patterns
- Adding custom package managers
- Extending DNS software block definitions

## File Location

Place the `.dnsbattribute` file in your **workdir** (the directory specified via `--workdir` CLI option, or the config directory if not specified). The file will be automatically loaded when the dnsbuilder configuration is initialized.

```
workdir/
├── config.yml
├── .dnsbattribute          ← Place here (will be auto-loaded)
├── top-1k.txt
└── shared/
```

### Command Examples

```bash
# Use current directory as workdir (will look for .dnsbattribute here)
dnsbuilder build config.yml --workdir @cwd

# Use config directory as workdir
dnsbuilder build config.yml --workdir @config

# Use custom directory as workdir
dnsbuilder build config.yml --workdir /path/to/workdir
```

## Configuration Format

The `.dnsbattribute` file uses YAML format and contains constants to override:

```yaml
# Add custom log aliases
LOG_ALIAS_MAP:
  custom: "dnsbuilder.custom.module"
  mylog: "dnsbuilder.my.custom.logger"

# Extend supported operating systems
SUPPORTED_OS:
  - alpine
  - rocky

# Add custom DNS software patterns
RECOGNIZED_PATTERNS:
  my_custom_dns:
    - r"\bmydns\b"
    - r"\bcustom-bind\b"
```

## Override Modes

The loader supports three different strategies for applying overrides:

### 1. Replace (Default)
For non-dict, non-list types, the entire constant is replaced:

```yaml
DEFAULT_OS: "alpine"  # Replaces the entire value
```

### 2. Merge (for Dictionaries)
Dictionaries are **deep-merged**, preserving existing keys:

```yaml
LOG_ALIAS_MAP:
  new_alias: "dnsbuilder.new.module"
  # Existing aliases are preserved
```

Result:
```python
LOG_ALIAS_MAP = {
    "sub": "dnsbuilder.builder.substitute",
    # ... existing entries ...
    "new_alias": "dnsbuilder.new.module",
}
```

### 3. Extend (for Lists)
Lists are **extended** with new items:

```yaml
SUPPORTED_OS:
  - alpine
  - rocky
```

Result:
```python
SUPPORTED_OS = ["ubuntu", "debian", "alpine", "rocky"]
```

## Examples

### Example 1: Add Custom Log Aliases

```yaml
# .dnsbattribute
LOG_ALIAS_MAP:
  mymod: "dnsbuilder.my.module"
  dbg: "dnsbuilder.debug"
```

Then use in environment:
```bash
export DNSB_DEBUG="mymod,dbg"
dnsbuilder build config.yml
```

### Example 2: Support Alpine Linux

```yaml
# .dnsbattribute
SUPPORTED_OS:
  - alpine

BASE_PACKAGE_MANAGERS:
  apk:
    supported_os: ["alpine"]
    check_cmd: "command -v apk >/dev/null 2>&1"
    install_cmd: "apk add --no-cache {packages}"
    cleanup_cmd: ""
```

### Example 3: Add Custom DNS Software

```yaml
# .dnsbattribute
RECOGNIZED_PATTERNS:
  my_dns:
    - r"\bmydns\b"
    - r"\bcustom-bind\b"

DNS_SOFTWARE_BLOCKS:
  my_dns:
    - "global"
    - "zone"
    - "custom-section"
```

### Example 4: Extend Custom Package Manager

```yaml
# .dnsbattribute
SOFT_PACKAGE_MANAGERS:
  custom_pkg:
    check_cmd: "command -v custom-pkg >/dev/null 2>&1"
    install_cmd: "custom-pkg install {packages}"
    cleanup_cmd: "custom-pkg cleanup"
    base_requirements:
      apt: ["custom-pkg"]
      apk: ["custom-pkg"]
```

## Available Constants to Override

Here are some commonly overridden constants:

| Constant | Type | Purpose |
|----------|------|---------|
| `LOG_ALIAS_MAP` | dict | Logging module name aliases |
| `SUPPORTED_OS` | list | Supported operating systems |
| `DEFAULT_OS` | str | Default OS when not specified |
| `RECOGNIZED_PATTERNS` | dict | DNS software detection patterns |
| `DNS_SOFTWARE_BLOCKS` | dict | DNS software configuration blocks |
| `BEHAVIOR_TYPES` | set | Supported behavior types |
| `RESOURCE_PREFIX` | str | Resource URL prefix |
| `STD_BUILD_PREFIX` | str | Standard build reference prefix |
| `BASE_PACKAGE_MANAGERS` | dict | Base package manager configs |
| `SOFT_PACKAGE_MANAGERS` | dict | Software package manager configs |

See `src/dnsbuilder/constants.py` for the complete list.

## Validation & Error Handling

- **Non-existent constant**: A warning is logged, override is skipped
- **Invalid YAML**: Error is logged, file is skipped
- **Type mismatch**: Best-effort handling:
  - Dict + Dict: Merged
  - List + List: Extended
  - Other: Replaced

## Logging

The attribute loader logs all operations at the INFO level:

```
[AttributeLoader] Loaded attributes from /path/to/.dnsbattribute
[AttributeLoader] Attributes to override: ['LOG_ALIAS_MAP', 'SUPPORTED_OS']
[AttributeLoader] Updated constant 'LOG_ALIAS_MAP'
[AttributeLoader] Updated constant 'SUPPORTED_OS'
```

Enable debug logging to see detailed merge operations:

```bash
export DNSB_DEBUG="auto"
dnsbuilder build config.yml
```

## Tips

1. **Namespacing**: Use descriptive names for custom entries to avoid conflicts
2. **Validation**: Test your `.dnsbattribute` file with a simple config first
3. **Portability**: Keep `.dnsbattribute` out of version control if it's environment-specific
4. **Documentation**: Comment your custom additions for team reference

## See Also

- `constants.py` - Source of all constant definitions
- `.dnsbattribute.example` - Example configuration file
