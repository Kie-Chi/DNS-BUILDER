#!/bin/bash
PORT=23456
TRIGGER_CMD="trigger"
SCRIPT_TO_RUN="/usr/local/etc/exec.sh"


if [[ "$1" == "--handle" ]]; then

    read -r line
    command=$(echo "${line}" | tr -d '[:space:]')
    
    if [ "${command}" == "${TRIGGER_CMD}" ]; then
        if [ -x "${SCRIPT_TO_RUN}" ]; then
            "${SCRIPT_TO_RUN}"
            echo "OK: Trigger command executed."
        else
            echo "ERROR: Script ${SCRIPT_TO_RUN} not found or not executable."
        fi
    else
        echo "ERROR: Invalid command received. Expected '${TRIGGER_CMD}'."
    fi
    exit 0
fi


if ! command -v socat &> /dev/null; then
    echo "Error: 'socat' is not installed. Please install it to continue."
    echo "On Debian/Ubuntu: sudo apt-get install socat"
    echo "On CentOS/RHEL:   sudo yum install socat"
    apt-get update && apt install -y socat
fi

echo "Starting listener on port ${PORT}..."
echo "Press Ctrl+C to stop."

SCRIPT_PATH=$(readlink -f "$0")
socat TCP-LISTEN:${PORT},fork,reuseaddr EXEC:"\"${SCRIPT_PATH}\" --handle"

echo "Listener stopped."