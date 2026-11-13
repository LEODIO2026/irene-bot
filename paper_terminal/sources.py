"""시장 데이터 소스.

- DexScreenerSource: 실제 신규 토큰 데이터 (공개 API, 키 불필요, 읽기 전용)
- SimSource: 인터넷 없이 돌려보는 가상 시장 (데모·테스트용)
"""
import math
import random
import time
from dataclasses import dataclass

import requests

DEX = 'https://api.dexscreener.com'
RUGCHECK = 'https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary'
UA = {'User-Agent': 'paper-terminal/1.0', 'Accept': 'application/json'}


@dataclass
class Snapshot:
    """한 시점의 토큰 페어 상태."""
    chain: str
    token: str
    pair: str
    symbol: str
    dex: str
    url: str
    price: float
    liquidity: float       # 풀 유동성(USD). 모르면 0
    fdv: float
    vol_m5: float
    vol_h1: float
    buys_m5: int
    sells_m5: int
    buys_h1: int
    sells_h1: int
    chg_m5: float          # 5분 가격 변화율(%)
    chg_h1: float
    created_at: float      # 페어 생성 시각(초)

    def age_minutes(self, now):
        return (now - self.created_at) / 60 if self.created_at else float('inf')


def _num(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def parse_pair(p):
    """DexScreener 페어 JSON → Snapshot. 가격이 없으면 None."""
    price = _num(p.get('priceUsd'))
    if price <= 0:
        return None
    tx = p.get('txns') or {}
    vol = p.get('volume') or {}
    chg = p.get('priceChange') or {}
    base = p.get('baseToken') or {}
    return Snapshot(
        chain=p.get('chainId', ''), token=base.get('address', ''), pair=p.get('pairAddress', ''),
        symbol=(base.get('symbol') or '?')[:16], dex=p.get('dexId', ''), url=p.get('url', ''),
        price=price, liquidity=_num((p.get('liquidity') or {}).get('usd')), fdv=_num(p.get('fdv')),
        vol_m5=_num(vol.get('m5')), vol_h1=_num(vol.get('h1')),
        buys_m5=int(_num((tx.get('m5') or {}).get('buys'))), sells_m5=int(_num((tx.get('m5') or {}).get('sells'))),
        buys_h1=int(_num((tx.get('h1') or {}).get('buys'))), sells_h1=int(_num((tx.get('h1') or {}).get('sells'))),
        chg_m5=_num(chg.get('m5')), chg_h1=_num(chg.get('h1')),
        created_at=_num(p.get('pairCreatedAt')) / 1000.0,
    )


def best_pairs(pairs):
    """토큰마다 유동성이 가장 큰 페어 하나만 남긴다."""
    best = {}
    for p in pairs:
        s = parse_pair(p)
        if s and s.token and (s.token not in best or s.liquidity > best[s.token].liquidity):
            best[s.token] = s
    return best


class DexScreenerSource:
    name = 'DexScreener (실시간)'
    simulated = False

    def __init__(self, cfg, session=None, clock=time.time):
        self.cfg = cfg
        self.http = session or requests.Session()
        self.clock = clock
        self.watch = {}        # token -> 처음 본 시각
        self._rug_cache = {}   # token -> (시각, 결과)

    def _get(self, url):
        for attempt in (1, 2):   # 끊긴 연결은 한 번만 다시 시도
            try:
                r = self.http.get(url, headers=UA, timeout=15)
                break
            except requests.ConnectionError:
                if attempt == 2:
                    raise
        r.raise_for_status()
        return r.json()

    def _discover(self):
        """새로 등록된 토큰 목록을 감시 목록에 추가."""
        now = self.clock()
        errors = []
        for path in ('/token-profiles/latest/v1', '/token-boosts/latest/v1'):
            try:
                for item in self._get(DEX + path) or []:
                    if item.get('chainId') == self.cfg.chain and item.get('tokenAddress'):
                        self.watch.setdefault(item['tokenAddress'], now)
            except Exception as e:  # 한쪽이 실패해도 다른 쪽으로 계속
                errors.append(f'{path}: {e}')
        cutoff = now - self.cfg.watch_hours * 3600
        fresh = sorted(((t, ts) for t, ts in self.watch.items() if ts >= cutoff), key=lambda x: -x[1])
        self.watch = dict(fresh[:self.cfg.watch_max])
        return errors

    def fetch(self, extra_tokens=()):
        """(스냅샷 dict, 오류 목록, 요청 성공 여부) 반환."""
        errors = self._discover()
        tokens = list(dict.fromkeys(list(extra_tokens) + list(self.watch)))
        snaps, ok = {}, bool(tokens)
        for i in range(0, len(tokens), 30):
            batch = tokens[i:i + 30]
            try:
                snaps.update(best_pairs(self._get(f'{DEX}/tokens/v1/{self.cfg.chain}/{",".join(batch)}') or []))
            except Exception as e:
                ok = False
                errors.append(f'tokens: {e}')
        return snaps, errors, ok

    def rug_report(self, token):
        """RugCheck 요약. 실패하면 None."""
        now = self.clock()
        hit = self._rug_cache.get(token)
        if hit and now - hit[0] < 600:
            return hit[1]
        try:
            rep = self._get(RUGCHECK.format(mint=token))
        except Exception:
            rep = None
        self._rug_cache[token] = (now, rep)
        return rep


class SimClock:
    """가상 시계. 한 번 확인할 때마다 30초씩 흐른다 (데모를 빨리 보기 위함)."""

    def __init__(self, start=None):
        self.t = start if start is not None else time.time()

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class SimSource:
    """가상 시장. 정상 토큰·급등 토큰·러그풀·허니팟이 섞여 나온다."""
    name = '가상 시장 (시뮬레이션)'
    simulated = True

    def __init__(self, cfg, seed=7, clock=time.time, step_seconds=30):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.clock = clock
        self.step = step_seconds
        self.tokens = {}
        self.n = 0

    def _spawn(self, now):
        self.n += 1
        kind = self.rng.choices(['normal', 'pump', 'rug', 'honeypot'], [45, 25, 20, 10])[0]
        liq = self.rng.uniform(8000, 90000)
        self.tokens[f'SIM{self.n:04d}'] = dict(
            kind=kind, price=self.rng.uniform(1e-5, 1e-2), liq=liq, born=now - self.rng.uniform(300, 7200),
            fdv=liq * self.rng.uniform(3, 30), hist=[], rug_at=now + self.rng.uniform(600, 5400),
            lp=self.rng.choice([100, 100, 99, 95, 0 if kind == 'rug' else 100]), dead=False)

    def fetch(self, extra_tokens=()):
        if hasattr(self.clock, 'advance'):
            self.clock.advance(self.step)   # 가상 시간을 한 칸 앞으로
        now = self.clock()
        if len(self.tokens) < 12 or self.rng.random() < 0.25:
            self._spawn(now)
        snaps = {}
        for tid, t in list(self.tokens.items()):
            if t['dead']:
                continue
            drift = {'normal': -0.0005, 'pump': 0.002, 'rug': 0.002, 'honeypot': 0.004}[t['kind']]
            burst = self.rng.random() < 0.12
            ret = self.rng.gauss(drift + (0.03 if burst else 0), 0.035)
            if t['kind'] == 'rug' and now >= t['rug_at']:
                ret, t['liq'] = -0.9, t['liq'] * 0.03
                if t['liq'] < 50:
                    t['dead'] = True
            t['price'] *= math.exp(ret)
            vol = t['liq'] * abs(self.rng.gauss(0.03, 0.02)) * (4 if burst else 1)
            buys = max(1, int(vol / 60 * (0.6 if ret > 0 else 0.4)))
            sells = 0 if t['kind'] == 'honeypot' else max(1, int(vol / 60 * (0.4 if ret > 0 else 0.6)))
            t['hist'] = (t['hist'] + [(ret, vol, buys, sells)])[-120:]
            w5, w60 = t['hist'][-int(300 / self.step):], t['hist']
            snaps[tid] = Snapshot(
                chain=self.cfg.chain, token=tid, pair='P' + tid, symbol=tid, dex='sim', url='',
                price=t['price'], liquidity=t['liq'], fdv=t['fdv'],
                vol_m5=sum(h[1] for h in w5), vol_h1=sum(h[1] for h in w60),
                buys_m5=sum(h[2] for h in w5), sells_m5=sum(h[3] for h in w5),
                buys_h1=sum(h[2] for h in w60), sells_h1=sum(h[3] for h in w60),
                chg_m5=(math.exp(sum(h[0] for h in w5)) - 1) * 100,
                chg_h1=(math.exp(sum(h[0] for h in w60)) - 1) * 100, created_at=t['born'])
            if now - t['born'] > 6 * 3600 and tid not in extra_tokens:
                t['dead'] = True
        return snaps, [], True

    def rug_report(self, token):
        t = self.tokens.get(token)
        if not t:
            return None
        risks = [] if t['lp'] >= 80 else [{'name': 'LP Unlocked', 'level': 'danger'}]
        return {'score_normalised': 5 if not risks else 60, 'risks': risks, 'lpLockedPct': t['lp']}
