#!/bin/bash

# ─────────────────────────────────────────────
#  아이린(Irene) 배포 스크립트
#  방식: git push → NAS git pull → Docker 재시작
# ─────────────────────────────────────────────

NAS_USER="Agent"
NAS_IP="192.168.50.116"
NAS_PATH="/volume1/docker/irene"
DOCKER="/usr/local/bin/docker"

echo "🚀 아이린 배포 시작..."

# 1. 로컬 git push
echo "📤 GitHub 푸시 중..."
git push origin main
if [ $? -ne 0 ]; then
    echo "❌ git push 실패. 커밋 후 다시 시도하세요."
    exit 1
fi

# 2. NAS에서 git pull + Docker 설정 갱신 및 재시작
echo "📡 NAS 배포 중..."
ssh $NAS_USER@$NAS_IP "cd $NAS_PATH && git pull origin main && /usr/local/bin/docker-compose up -d"

# 3. 로그 확인
echo ""
echo "📺 아이린 로그:"
echo "─────────────────────────────────"
sleep 10
ssh $NAS_USER@$NAS_IP "$DOCKER logs --tail 20 irene_agent"

echo ""
echo "─────────────────────────────────"
echo "✅ 배포 완료! 대시보드: http://$NAS_IP:9090/dashboard"
