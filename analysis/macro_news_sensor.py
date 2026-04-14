"""
아이린(Irene) v3 — 📰 매크로 뉴스 센서 (Macro News Sensor)
──────────────────────────────────────────────────────────────
"국제 정세와 뉴스가 코인에 미치는 영향을 실시간으로 점수화한다."

데이터 소스 (전부 무료, 키 불필요):
1. CoinDesk RSS Feed
2. CoinTelegraph RSS Feed
3. Bitcoin Magazine RSS Feed
4. 키워드 기반 자체 감정 분석 (외부 AI API 불필요)

최대 점수: 1.0/10.0
"""

import time
import re
try:
    import feedparser
except ImportError:
    feedparser = None
    print("아이린: feedparser 미설치. pip install feedparser 필요.")

import requests


class MacroNewsSensor:
    def __init__(self):
        self._news_cache = {'articles': [], 'ts': 0}
        self._cache_ttl = 300  # 5분 캐시

        # ── 키워드 사전 (영어 + 한국어) ──
        self.BULLISH_KEYWORDS = [
            # 영어
            'etf approved', 'etf approval', 'institutional', 'adoption',
            'halving', 'accumulation', 'whale buy', 'whale accumulation',
            'bullish', 'rally', 'breakout', 'all-time high', 'ath',
            'partnership', 'integration', 'upgrade', 'milestone',
            'inflow', 'record high', 'recovery', 'surge', 'soar',
            'buy signal', 'golden cross', 'fed rate cut', 'rate cut',
            'stimulus', 'easing', 'strategic reserve', 'nation adopt',
            'legal tender', 'stablecoin bill', 'regulation clarity',
            'demand', 'growth', 'expansion', 'innovation',
            # 한국어
            '승인', '기관 매수', '반감기', '상승', '돌파', '신고가',
            '매수세', '강세', '회복', '급등', '금리 인하',
        ]

        self.BEARISH_KEYWORDS = [
            # 영어
            'hack', 'hacked', 'exploit', 'vulnerability', 'breach',
            'sec lawsuit', 'sec sue', 'regulation', 'ban', 'crackdown',
            'crash', 'plunge', 'dump', 'liquidation', 'rug pull',
            'ponzi', 'fraud', 'scam', 'bankruptcy', 'insolvency',
            'outflow', 'sell-off', 'selloff', 'bear market', 'bearish',
            'death cross', 'fed rate hike', 'rate hike', 'tightening',
            'war', 'sanctions', 'tariff', 'trade war', 'recession',
            'bank failure', 'bank run', 'contagion', 'collapse',
            'delisting', 'shutdown', 'fine', 'penalty',
            # 한국어
            '해킹', '규제', '하락', '폭락', '청산', '금리 인상',
            '매도세', '약세', '파산', '사기', '제재', '전쟁', '관세',
        ]

        # RSS 피드 소스
        self.RSS_FEEDS = [
            'https://www.coindesk.com/arc/outboundfeeds/rss/',
            'https://cointelegraph.com/rss',
            'https://bitcoinmagazine.com/.rss/full/',
        ]

    # ─── RSS 뉴스 수집 ───────────────────────────────────────
    def fetch_recent_news(self, max_hours=2):
        """
        주요 크립토 뉴스 사이트의 RSS 피드에서 최근 뉴스를 수집합니다.
        5분 캐시 적용.

        Args:
            max_hours: 최근 N시간 이내의 뉴스만 필터링

        Returns:
            list[dict]: [{'title': str, 'source': str, 'link': str, 'published': str}, ...]
        """
        now = time.time()
        if self._news_cache['articles'] and (now - self._news_cache['ts']) < self._cache_ttl:
            return self._news_cache['articles']

        if feedparser is None:
            return self._fetch_fallback_news()

        articles = []
        cutoff = now - (max_hours * 3600)

        for feed_url in self.RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                source = feed.feed.get('title', feed_url.split('/')[2])

                for entry in feed.entries[:15]:  # 각 피드에서 최신 15개만
                    published = entry.get('published_parsed')
                    if published:
                        entry_ts = time.mktime(published)
                        if entry_ts < cutoff:
                            continue

                    articles.append({
                        'title': entry.get('title', ''),
                        'source': source,
                        'link': entry.get('link', ''),
                        'published': entry.get('published', ''),
                        'summary': entry.get('summary', '')[:200]
                    })
            except Exception as e:
                print(f"아이린: RSS 파싱 실패 ({feed_url}): {e}")
                continue

        self._news_cache = {'articles': articles, 'ts': now}
        return articles

    def _fetch_fallback_news(self):
        """feedparser가 없을 때 대안: Alternative.me에서 최소 정보만"""
        try:
            resp = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
            data = resp.json()
            classification = data['data'][0].get('value_classification', 'Neutral')
            return [{
                'title': f'Market Sentiment: {classification}',
                'source': 'Alternative.me',
                'link': '',
                'published': '',
                'summary': ''
            }]
        except:
            return []

    # ─── 헤드라인 감정 점수 ──────────────────────────────────
    def score_headline(self, headline):
        """
        개별 헤드라인의 감정 점수를 계산합니다.
        키워드 매칭 기반 (외부 AI API 불필요).

        Returns:
            float: -1.0 (극도 약세) ~ +1.0 (극도 강세), 0.0 = 중립
        """
        text = headline.lower()
        bull_count = sum(1 for kw in self.BULLISH_KEYWORDS if kw.lower() in text)
        bear_count = sum(1 for kw in self.BEARISH_KEYWORDS if kw.lower() in text)

        total = bull_count + bear_count
        if total == 0:
            return 0.0

        # -1 ~ +1 범위로 정규화
        score = (bull_count - bear_count) / total
        return round(max(-1.0, min(1.0, score)), 3)

    # ─── 종합 매크로 뉴스 분석 ───────────────────────────────
    def analyze(self, htf_bias):
        """
        최근 뉴스의 전체적인 감정을 분석하고 점수를 산출합니다.

        Args:
            htf_bias: 'bullish' 또는 'bearish'

        Returns:
            dict: {
                'score': float (0~1.0),
                'reasons': list[str],
                'details': dict,
                'top_headlines': list
            }
        """
        score = 0.0
        reasons = []

        articles = self.fetch_recent_news(max_hours=4)

        if not articles:
            reasons.append("📰 최근 뉴스 없음 — 매크로 분석 스킵")
            return {
                'score': 0,
                'reasons': reasons,
                'details': {'article_count': 0},
                'top_headlines': []
            }

        # 각 헤드라인 점수 산출
        scored_articles = []
        for article in articles:
            text = article['title'] + ' ' + article.get('summary', '')
            article_score = self.score_headline(text)
            scored_articles.append({
                **article,
                'sentiment_score': article_score
            })

        # 전체 감정 집계
        scores = [a['sentiment_score'] for a in scored_articles]
        avg_sentiment = sum(scores) / len(scores) if scores else 0
        bullish_count = sum(1 for s in scores if s > 0.1)
        bearish_count = sum(1 for s in scores if s < -0.1)
        neutral_count = len(scores) - bullish_count - bearish_count

        # 감정 강도에 따른 점수 부여
        news_bias = 'bullish' if avg_sentiment > 0.15 else ('bearish' if avg_sentiment < -0.15 else 'neutral')

        # 바이어스 방향과 뉴스 감정이 일치하면 점수 부여
        if (htf_bias == 'bullish' and news_bias == 'bullish'):
            strength = min(0.5, abs(avg_sentiment) * 2)
            score += strength
            reasons.append(
                f"📰 뉴스 감정 강세 (평균 {avg_sentiment:+.2f}, "
                f"강세 {bullish_count}건/약세 {bearish_count}건) "
                f"+ 상승 바이어스 → 확인 (+{strength:.2f})")
        elif (htf_bias == 'bearish' and news_bias == 'bearish'):
            strength = min(0.5, abs(avg_sentiment) * 2)
            score += strength
            reasons.append(
                f"📰 뉴스 감정 약세 (평균 {avg_sentiment:+.2f}, "
                f"강세 {bullish_count}건/약세 {bearish_count}건) "
                f"+ 하락 바이어스 → 확인 (+{strength:.2f})")
        elif news_bias == 'neutral':
            reasons.append(
                f"📰 뉴스 감정 중립 (평균 {avg_sentiment:+.2f}, "
                f"{len(articles)}건 분석) — 보너스 없음")
        else:
            reasons.append(
                f"📰 뉴스 감정 ({news_bias}) ↔ 바이어스 ({htf_bias}) 불일치 — 경고")

        # 극단적 뉴스 이벤트 보너스 (+0.5 추가)
        extreme_bull = sum(1 for s in scores if s >= 0.5)
        extreme_bear = sum(1 for s in scores if s <= -0.5)

        if htf_bias == 'bullish' and extreme_bull >= 3:
            bonus = 0.5
            score += bonus
            reasons.append(
                f"🚀 극도 강세 뉴스 {extreme_bull}건 집중 → 강력 확인 (+{bonus})")
        elif htf_bias == 'bearish' and extreme_bear >= 3:
            bonus = 0.5
            score += bonus
            reasons.append(
                f"💀 극도 약세 뉴스 {extreme_bear}건 집중 → 강력 확인 (+{bonus})")

        # 최종 점수 상한 1.0
        score = min(1.0, score)

        # 인상적인 헤드라인 TOP 3
        top = sorted(scored_articles, key=lambda x: abs(x['sentiment_score']), reverse=True)[:3]

        return {
            'score': round(score, 2),
            'reasons': reasons,
            'details': {
                'article_count': len(articles),
                'avg_sentiment': round(avg_sentiment, 3),
                'bullish_count': bullish_count,
                'bearish_count': bearish_count,
                'neutral_count': neutral_count,
                'news_bias': news_bias
            },
            'top_headlines': [
                f"[{a['sentiment_score']:+.2f}] {a['title']}" for a in top
            ]
        }


if __name__ == "__main__":
    print("─── 아이린 v3: 매크로 뉴스 센서 단독 테스트 ───")
    sensor = MacroNewsSensor()

    # 뉴스 수집
    articles = sensor.fetch_recent_news()
    print(f"수집된 뉴스: {len(articles)}건")
    for a in articles[:5]:
        s = sensor.score_headline(a['title'])
        print(f"  [{s:+.2f}] {a['title'][:80]}...")

    # 종합 분석
    result = sensor.analyze('bullish')
    print(f"\n매크로 점수: {result['score']}/1.0")
    for r in result['reasons']:
        print(f"  {r}")
    if result['top_headlines']:
        print("\nTOP 헤드라인:")
        for h in result['top_headlines']:
            print(f"  {h}")
