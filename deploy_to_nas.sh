#!/bin/bash

# ─────────────────────────────────────────────
#  아이린(Irene) NAS 완전 자동 배포 스크립트
# ─────────────────────────────────────────────

NAS_USER="Agent"
NAS_IP="192.168.50.116"
NAS_PATH="/volume1/docker/irene"
DOCKER="/usr/local/bin/docker"
COMPOSE="/usr/local/bin/docker-compose"

echo "🚀 아이린 자동 배포 시작..."

# 1. 설정 파일 및 소스 코드 전송 (라이브 패치)
echo "📡 소스코드 및 설정 파일 전송 중..."
tar c .env docker-compose.yml main.py core execution analysis strategy requirements.txt | ssh $NAS_USER@$NAS_IP "tar x -C $NAS_PATH"

# 2. 코드 변경 시 이미지 전송 + 로드
if [ "$1" == "--full" ]; then
    echo "🐳 도커 이미지 전송 중... (약 2~3분)"
    cat irene-agent.tar.gz | ssh $NAS_USER@$NAS_IP "cat > $NAS_PATH/irene-agent.tar.gz"
    echo "📦 이미지 로드 중..."
    ssh $NAS_USER@$NAS_IP "$DOCKER load < $NAS_PATH/irene-agent.tar.gz"
fi

# 3. 컨테이너 재시작
echo "♻️  아이린 재시작 중..."
ssh $NAS_USER@$NAS_IP "cd $NAS_PATH && $COMPOSE down && $COMPOSE up -d"

# 4. 로그 확인
echo ""
echo "📺 아이린 로그:"
echo "─────────────────────────────────"
sleep 8
ssh $NAS_USER@$NAS_IP "$DOCKER logs --tail 15 irene_agent"

echo ""
echo "─────────────────────────────────"
echo "✅ 배포 완료! 대시보드: http://$NAS_IP:9090/dashboard"
