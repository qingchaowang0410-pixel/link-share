#!/bin/bash
# 双击启动链接库 —— 后台启服务 + Cloudflare Tunnel 公网穿透
# 启动后自动弹窗显示本机/局域网/公网三个网址

cd "$(dirname "$0")"

PORT=8000
URL="http://127.0.0.1:${PORT}"
LOG_DIR="data"
mkdir -p "${LOG_DIR}"

SERVER_LOG="${LOG_DIR}/server.log"
SERVER_PID="${LOG_DIR}/server.pid"
TUNNEL_LOG="${LOG_DIR}/tunnel.log"
TUNNEL_PID="${LOG_DIR}/tunnel.pid"
TUNNEL_URL_FILE="${LOG_DIR}/tunnel_url.txt"

# 找到 cloudflared（Homebrew 在 Apple Silicon 上装到 /opt/homebrew/bin，PATH 在双击场景下可能没加载）
CLOUDFLARED=""
for cand in /opt/homebrew/bin/cloudflared /usr/local/bin/cloudflared "$(which cloudflared 2>/dev/null)"; do
  if [ -x "${cand}" ]; then CLOUDFLARED="${cand}"; break; fi
done

# ====== 启服务 ======
start_server() {
  if [ -f "${SERVER_PID}" ]; then
    PID=$(cat "${SERVER_PID}" 2>/dev/null)
    if [ -n "${PID}" ] && ps -p "${PID}" >/dev/null 2>&1; then
      echo "✓ 服务已在运行 (PID ${PID})"
      return 0
    fi
    rm -f "${SERVER_PID}"
  fi

  if lsof -ti :${PORT} >/dev/null 2>&1; then
    echo "⚠️  端口 ${PORT} 被占用，请先关闭占用程序"
    return 1
  fi

  if ! python3 -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "首次启动，安装依赖（约 30 秒）..."
    python3 -m pip install --user -q -r requirements.txt
  fi

  nohup python3 app.py >"${SERVER_LOG}" 2>&1 &
  PID=$!
  disown ${PID} 2>/dev/null
  echo ${PID} > "${SERVER_PID}"

  for i in 1 2 3 4 5 6 7 8; do
    curl -s -o /dev/null "${URL}" && return 0
    sleep 1
  done
  return 1
}

# ====== 启 Tunnel ======
start_tunnel() {
  [ -z "${CLOUDFLARED}" ] && return 1

  # 已经在跑就别重复启
  if [ -f "${TUNNEL_PID}" ]; then
    PID=$(cat "${TUNNEL_PID}" 2>/dev/null)
    if [ -n "${PID}" ] && ps -p "${PID}" >/dev/null 2>&1; then
      return 0
    fi
    rm -f "${TUNNEL_PID}"
  fi

  rm -f "${TUNNEL_URL_FILE}" "${TUNNEL_LOG}"

  # 启动临时 tunnel
  nohup "${CLOUDFLARED}" tunnel --url "${URL}" --no-autoupdate >"${TUNNEL_LOG}" 2>&1 &
  PID=$!
  disown ${PID} 2>/dev/null
  echo ${PID} > "${TUNNEL_PID}"

  # 从日志里抓 https://*.trycloudflare.com URL（最多等 30 秒）
  for i in $(seq 1 30); do
    URL_LINE=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "${TUNNEL_LOG}" 2>/dev/null | head -1)
    if [ -n "${URL_LINE}" ]; then
      echo "${URL_LINE}" > "${TUNNEL_URL_FILE}"
      return 0
    fi
    sleep 1
  done
  return 1
}

# ============================================================

echo "======================================"
echo "  🔗 链接库 启动中..."
echo "======================================"
echo ""

echo "→ 启动本地服务..."
if ! start_server; then
  echo "❌ 本地服务启动失败，请查看 ${SERVER_LOG}"
  echo "（按任意键关闭）"
  read -n 1
  exit 1
fi
echo "✓ 本地服务 OK"

# 局域网 IP
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null)
[ -z "${LAN_IP}" ] && LAN_IP=$(ipconfig getifaddr en1 2>/dev/null)

# 启 tunnel
PUBLIC_URL=""
if [ -n "${CLOUDFLARED}" ]; then
  echo "→ 启动公网穿透（Cloudflare Tunnel）..."
  if start_tunnel; then
    PUBLIC_URL=$(cat "${TUNNEL_URL_FILE}" 2>/dev/null)
    echo "✓ 公网穿透 OK"
  else
    echo "⚠️  公网穿透启动超时，可在 ${TUNNEL_LOG} 查看原因"
  fi
else
  echo "⚠️  未安装 cloudflared，跳过公网穿透"
  echo "   安装命令：brew install cloudflared"
fi

echo ""
echo "本机访问：${URL}"
[ -n "${LAN_IP}" ] && echo "局域网（同 WiFi）：http://${LAN_IP}:${PORT}"
[ -n "${PUBLIC_URL}" ] && echo "公网（任何网络）：${PUBLIC_URL}"

open "${URL}"
sleep 1

# 读密码（如有）
AUTH_PASSWORD=""
if [ -f "data/auth.txt" ]; then
  AUTH_PASSWORD=$(cat data/auth.txt 2>/dev/null | tr -d '[:space:]')
fi

# 系统对话框显示地址 + 密码
DIALOG_TEXT="✓ 链接库已启动

本机访问：
${URL}"
[ -n "${LAN_IP}" ] && DIALOG_TEXT="${DIALOG_TEXT}

局域网（同 WiFi）：
http://${LAN_IP}:${PORT}"
[ -n "${PUBLIC_URL}" ] && DIALOG_TEXT="${DIALOG_TEXT}

公网（任何网络都能访问）：
${PUBLIC_URL}"
[ -n "${AUTH_PASSWORD}" ] && DIALOG_TEXT="${DIALOG_TEXT}

访问密码：${AUTH_PASSWORD}

把上面的「公网」网址和密码发给同事。"

osascript <<EOF >/dev/null 2>&1 &
tell application "System Events"
  display dialog "${DIALOG_TEXT}" with title "链接库" buttons {"知道了"} default button 1 with icon note
end tell
EOF

# 自动关终端窗口
osascript -e 'tell application "Terminal" to close (every window whose name contains "启动.command")' >/dev/null 2>&1 &
exit 0
