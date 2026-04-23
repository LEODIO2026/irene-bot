# ─────────────────────────────────────────────
#  아이린(Irene) 에이전트 - Docker 이미지
#  대상: 시놀로지 NAS DS1618+ (x86-64)
# ─────────────────────────────────────────────

# Python 3.11 슬림 이미지 (x86-64 호환)
FROM python:3.11-slim

# 작업 디렉토리
WORKDIR /app

# 시스템 패키지 설치 생략 (시놀로지 seccomp 호환성 문제 대응)
# 만약 추후 컴파일이 필요한 패키지가 추가되면 그때 다시 대응합니다.
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 복사 (레이어 캐싱 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 복사
COPY . .

# .env 파일은 컨테이너 실행 시 마운트 (보안상 이미지에 포함 X)
# docker-compose.yml 에서 volume 또는 env_file로 주입

# 웹훅 포트 노출
EXPOSE 9090

# 헬스체크 (컨테이너 상태 모니터링)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:9090/health')" || exit 1

# 실행 명령
CMD ["python3", "-u", "main.py"]
