#!/bin/sh
set -eu
install -o 1000 -g 1000 -m 0400 /etc/letsencrypt/live/<{ domain }>/fullchain.pem /etc/neon/tls/fullchain.pem.new
install -o 1000 -g 1000 -m 0400 /etc/letsencrypt/live/<{ domain }>/privkey.pem /etc/neon/tls/privkey.pem.new
mv /etc/neon/tls/fullchain.pem.new /etc/neon/tls/fullchain.pem
mv /etc/neon/tls/privkey.pem.new /etc/neon/tls/privkey.pem
docker compose -f /opt/neon/compose.json up -d --force-recreate compute
