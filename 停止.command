#!/bin/bash
# 双击停止链接库（同时关闭服务和公网穿透）

cd "$(dirname "$0")"

PORT=8000
SERVER_PID="data/server.pid"
TUNNEL_PID="data/tunnel.pid"
TUNNEL_URL_FILE="data/tunnel_url.txt"

STOPPED=0

# 停服务
if [ -f "${SERVER_PID}" ]; then
  PID=$(cat "${SERVER_PID}" 2>/dev/null)
  if [ -n "${PID}" ] && ps -p "${PID}" >/dev/null 2>&1; then
    kill "${PID}" 2>/dev/null
    sleep 1
    ps -p "${PID}" >/dev/null 2>&1 && kill -9 "${PID}" 2>/dev/null
    STOPPED=1
  fi
  rm -f "${SERVER_PID}"
fi

# 停 tunnel
if [ -f "${TUNNEL_PID}" ]; then
  PID=$(cat "${TUNNEL_PID}" 2>/dev/null)
  if [ -n "${PID}" ] && ps -p "${PID}" >/dev/null 2>&1; then
    kill "${PID}" 2>/dev/null
    sleep 1
    ps -p "${PID}" >/dev/null 2>&1 && kill -9 "${PID}" 2>/dev/null
    STOPPED=1
  fi
  rm -f "${TUNNEL_PID}" "${TUNNEL_URL_FILE}"
fi

# 兜底：按端口和进程名清理
PORT_PIDS=$(lsof -ti :${PORT} 2>/dev/null)
if [ -n "${PORT_PIDS}" ]; then
  echo "${PORT_PIDS}" | xargs kill 2>/dev/null
  sleep 1
  PORT_PIDS=$(lsof -ti :${PORT} 2>/dev/null)
  [ -n "${PORT_PIDS}" ] && echo "${PORT_PIDS}" | xargs kill -9 2>/dev/null
  STOPPED=1
fi
# 残留的 cloudflared 进程
pkill -f "cloudflared tunnel --url http://127.0.0.1:${PORT}" 2>/dev/null

if [ ${STOPPED} -eq 1 ]; then
  echo "✓ 服务已停止"
else
  echo "ℹ️  服务本来就没在运行"
fi

sleep 1
osascript -e 'tell application "Terminal" to close (every window whose name contains "停止.command")' >/dev/null 2>&1 &
exit 0
