# DNSSEC fault topology

这个目录保留两套配置：

- `bind.yml` 是原来的纯 BIND 权威配置，内容保留用于回归对照。
- `pdns.yml` 是新的混合配置；`auth-cn` 使用固定版本 `powerdns/pdns-auth-50:5.0.7` 作为 PowerDNS Authoritative，其余权威节点仍为 BIND，递归节点为 Unbound。

两套配置都使用 DNSBuilder 生成 BIND 风格 zonefile 并预签名。PowerDNS 节点使用 `launch=bind` 和 `bind-config` 直接挂载生成的 `db.cn`；DNSSEC 元数据由 DNSBuilder 使用 Python 标准库 `sqlite3` 写入 `pdns-dnssec/bind-dnssec-db.sqlite3`，不需要 `pdnsutil`。

## 运行

在仓库根目录执行：

```bash
# 需要宿主机可用的 dnssec-signzone；也可以在配置中设置 util_mode: docker
.venv/bin/python -m dnsbuilder.cli build examples/bugs/dnssec-fault/pdns.yml --workdir @config
docker compose -f examples/bugs/dnssec-fault/output/dnssec-fault-pdns/docker-compose.yml build --pull=false
docker compose -f examples/bugs/dnssec-fault/output/dnssec-fault-pdns/docker-compose.yml up -d --pull never
./examples/bugs/dnssec-fault/verify.sh

# 结束实验
docker compose -f examples/bugs/dnssec-fault/output/dnssec-fault-pdns/docker-compose.yml down
```

`docker compose` 会自动创建 `auth-cn/contents/includes` 的 bind mount 源目录；不需要预创建空目录。PowerDNS 的 SQLite 数据库目录由构建器生成，因为构建阶段必须先写入数据库。

验证脚本从 `client` 容器查询：

- PowerDNS 直接返回 `cn` 的 SOA、DNSKEY、DS；
- 递归查询 `www.dlv.cn` 和 `www.target.com` 返回 `RRSIG` 与 `ad`；
- `missing.dlv.cn` 返回带 `NSEC3`/`RRSIG` 的 DNSSEC NXDOMAIN。

如果重复构建并复用已有容器，递归缓存可能保留旧签名；验证前使用 `docker compose ... up -d --force-recreate`，或执行 `unbound-control flush_zone .`。

`resource/nginx/nginx.conf` 的挂载目标故意使用 `/etc/nginx/nginx.config`，启动命令显式传入 `nginx -c`。`.config` 后缀不会被 DNSBuilder 当作 DNS `.conf` 片段拼入 Unbound。
