#!/bin/bash

# ─────────────────────────────────────────────
#  아이린(Irene) 배포 스크립트
#  방식: git push → NAS git pull → Docker 재시작
# ─────────────────────────────────────────────

NAS_USER="Agent"
NAS_IP="192.168.50.116"
NAS_DDNS="leodio.asuscomm.com"
NAS_PORT="2222"
NAS_PATH="/volume1/docker/irene"
DOCKER="/usr/local/bin/docker"

echo "🚀 아이린 배포 시작..."

# 네트워크 접속 상태 확인 (macOS nc 명령어)
nc -z -G 2 $NAS_IP 22 > /dev/null 2>&1
if [ $? -eq 0 ]; then
    TARGET_HOST="$NAS_IP"
    SSH_CMD="ssh"
    DASHBOARD_URL="http://$TARGET_HOST:9090/dashboard"
    echo "🏠 내부망 접속 확인됨 ($TARGET_HOST)"
else
    TARGET_HOST="$NAS_DDNS"
    SSH_CMD="ssh -p $NAS_PORT"
    # 외부 접속용 대시보드 포트가 있다면 수정 가능하지만 일단 생략
    DASHBOARD_URL="http://$TARGET_HOST:9090/dashboard (포트포워딩 필요)"
    echo "🌍 외부망 접속 시도 ($TARGET_HOST:$NAS_PORT)"
fi

# 1. 로컬 git push
echo "📤 GitHub 푸시 중..."
git push origin main
if [ $? -ne 0 ]; then
    echo "❌ git push 실패. 커밋 후 다시 시도하세요."
    exit 1
fi

# 2. NAS에서 git pull + Docker 설정 갱신 및 재시작
echo "📡 NAS 배포 중..."
$SSH_CMD $NAS_USER@$TARGET_HOST "cd $NAS_PATH && git pull origin main && /usr/local/bin/docker-compose up -d"

# 3. 로그 확인
echo ""
echo "📺 아이린 로그:"
echo "─────────────────────────────────"
sleep 10
$SSH_CMD $NAS_USER@$TARGET_HOST "$DOCKER logs --tail 20 irene_agent"

echo ""
echo "─────────────────────────────────"
echo "✅ 배포 완료! 대시보드: $DASHBOARD_URL"
