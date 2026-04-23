"""
아이린(Irene) v3 — 📅 경제 지표 캘린더 (Economic Calendar)
──────────────────────────────────────────────────────────────
"주요 거시경제 지표 발표 일정을 파악하여 다가오는 변동성을 경고한다."

데이터 소스: Forex Factory XML Feed (무료, API 키 불필요)
"""

import time
import requests
import datetime
import xml.etree.ElementTree as ET

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


class EconomicCalendar:
    def __init__(self):
        self.url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        self._cache = {'events': [], 'ts': 0}
        self._cache_ttl = 3600  # 1시간 캐시

    def fetch_upcoming_events(self, limit_hours=24) -> list:
        """
        현재 시각 기준 limit_hours 이내에 예정된 미국(USD) 'High' 임팩트 지표를 반환합니다.
        
        Returns:
            list[dict]: [{'title': str, 'kst_time': str, 'time_left': str}, ...]
        """
        now = time.time()
        if self._cache['events'] and (now - self._cache['ts']) < self._cache_ttl:
            all_events = self._cache['events']
        else:
            all_events = self._fetch_from_api()
            self._cache = {'events': all_events, 'ts': now}

        kst_now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
        upcoming = []

        for event in all_events:
            event_dt = event.get('dt_kst')
            if not event_dt:
                continue
                
            # 현재 시점부터 미래 일정인지, 그리고 지정된 시간 이내인지 확인
            delta = event_dt - kst_now
            hours_left = delta.total_seconds() / 3600

            if 0 <= hours_left <= limit_hours:
                # 남은 시간 포맷팅
                if hours_left < 1:
                    time_left = f"{int(hours_left * 60)}분 후"
                else:
                    time_left = f"{int(hours_left)}시간 {int((hours_left % 1) * 60)}분 후"

                upcoming.append({
                    'title': event['title'],
                    'kst_time': event_dt.strftime('%H:%M KST'),
                    'time_left': time_left,
                    'is_critical': 'CPI' in event['title'] or 'FOMC' in event['title'] or 'Non-Farm' in event['title']
                })

        return upcoming

    def _fetch_from_api(self) -> list:
        """Forex Factory API에서 데이터를 가져와 파싱합니다."""
        try:
            resp = requests.get(self.url, timeout=10)
            if resp.status_code != 200:
                return []
                
            root = ET.fromstring(resp.content)
            events = []
            ny_tz = ZoneInfo("America/New_York")
            kst_tz = ZoneInfo("Asia/Seoul")

            for event in root.findall('event'):
                country = event.findtext('country')
                impact = event.findtext('impact')
                
                # 미국(USD)의 High 임팩트 지표만 필터링
                if country != 'USD' or impact != 'High':
                    continue

                title = event.findtext('title')
                date_str = event.findtext('date')  # MM-DD-YYYY
                time_str = event.findtext('time')  # h:mma (e.g., 8:30am)

                # 시간 파싱 시도 (Tentative, All Day 등 예외 처리)
                dt_kst = None
                if time_str and 'am' in time_str.lower() or 'pm' in time_str.lower():
                    try:
                        # 예: 04-19-2026 8:30am
                        dt_str = f"{date_str} {time_str.upper()}"
                        dt_ny = datetime.datetime.strptime(dt_str, '%m-%d-%Y %I:%M%p')
                        # 시간대 정보 추가 및 KST 변환
                        dt_ny = dt_ny.replace(tzinfo=ny_tz)
                        dt_kst = dt_ny.astimezone(kst_tz)
                    except Exception as e:
                        pass

                events.append({
                    'title': title,
                    'dt_kst': dt_kst
                })

            return events
        except Exception as e:
            print(f"아이린: 경제 캘린더 수집 실패: {e}")
            return []

if __name__ == "__main__":
    print("─── 아이린 v3: 경제 지표 캘린더 단독 테스트 ───")
    calendar = EconomicCalendar()
    # 테스트를 위해 1주일(168시간) 범위로 조회
    upcoming = calendar.fetch_upcoming_events(limit_hours=168)
    
    if not upcoming:
        print("이번 주 예정된 USD High 임팩트 지표가 없습니다.")
    else:
        for ev in upcoming:
            warn = "🚨 [초특급 주의]" if ev['is_critical'] else "⚠️"
            print(f"{warn} {ev['title']}")
            print(f"   발표: {ev['kst_time']} ({ev['time_left']})")
