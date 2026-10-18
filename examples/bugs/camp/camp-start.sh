docker exec -d camp-unbound unbound -d -c /usr/local/etc/unbound/unbound.conf

docker exec -d camp-bind named -g -c /usr/local/etc/named.conf

docker exec -d camp-pdns pdns_recursor --config-dir=/usr/local/etc

docker exec -d camp-knot /tmp/kr/sbin/kresd -n -v -c /usr/local/etc/kresd.conf