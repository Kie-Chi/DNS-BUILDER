# 安装与运行

- 安装：
```
pip install mkdocs mkdocs-material mkdocstrings[python] mkdocs-git-revision-date-localized-plugin mkdocs-mermaid2-plugin mkdocs-swagger-ui-tag
```
- 启动文档（避免与后端 8000 冲突）：
```
mkdocs serve -a 127.0.0.1:8001
```
- 启动后端：
```
python -m dnsbuilder --ui
```