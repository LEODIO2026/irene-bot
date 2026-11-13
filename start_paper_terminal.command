#!/bin/bash
# 아이린 모의거래 터미널 — 맥에서 더블클릭으로 실행
# 실제 시장 데이터로 시작합니다. 가상 시장으로 보려면: ./start_paper_terminal.command sim
cd "$(dirname "$0")" || exit 1

echo "──────────────────────────────────────────"
echo "  아이린 모의거래 터미널을 준비하고 있어요"
echo "  (실제 돈·지갑·API 키는 쓰지 않아요)"
echo "──────────────────────────────────────────"

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo
  echo "파이썬이 필요해요. 지금 열리는 페이지에서 내려받아 설치한 뒤,"
  echo "이 파일을 다시 더블클릭해 주세요."
  command -v open >/dev/null && open "https://www.python.org/downloads/"
  read -r -p "Enter 키를 누르면 창이 닫혀요. "
  exit 1
fi

if [ ! -x .venv-paper/bin/python ]; then
  echo "처음 한 번만 필요한 준비를 하는 중이에요 (1분쯤 걸려요)..."
  python3 -m venv .venv-paper || { read -r -p "준비에 실패했어요. Enter 키를 누르면 닫혀요. "; exit 1; }
fi
.venv-paper/bin/python -c 'import flask, requests' 2>/dev/null \
  || .venv-paper/bin/python -m pip install --quiet --disable-pip-version-check flask requests \
  || { read -r -p "설치에 실패했어요. 인터넷 연결을 확인해 주세요. Enter 키를 누르면 닫혀요. "; exit 1; }

PORT="${PAPER_PORT:-9191}"
ARGS=()
[ "$1" = "sim" ] && ARGS=(--source sim)

echo
echo "준비 끝! 브라우저가 곧 열려요:  http://127.0.0.1:$PORT"
echo "끄려면 이 창을 닫거나 Ctrl + C 를 누르세요."
echo
( sleep 3; command -v open >/dev/null && open "http://127.0.0.1:$PORT" ) &
exec .venv-paper/bin/python -m paper_terminal --port "$PORT" "${ARGS[@]}"
