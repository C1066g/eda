#!/bin/bash
# 在本机启动静态网页服务，同 WiFi/热点下的设备可访问
cd "$(dirname "$0")"
PORT="${1:-8765}"

IP=""
for iface in en0 en1 bridge0; do
  ip=$(ipconfig getifaddr "$iface" 2>/dev/null)
  if [ -n "$ip" ]; then IP="$ip"; break; fi
done
[ -z "$IP" ] && IP="127.0.0.1"

echo "=============================================="
echo "  通信网络技术 · 复习网页"
echo "=============================================="
echo ""
echo "  本机访问:"
echo "    http://127.0.0.1:${PORT}/通信网络技术_考试中心.html"
echo ""
echo "  同热点/同 WiFi 的其他设备访问:"
echo "    http://${IP}:${PORT}/通信网络技术_考试中心.html"
echo ""
echo "  按 Ctrl+C 停止服务"
echo "=============================================="
echo ""

exec python3 -m http.server "$PORT" --bind 0.0.0.0
