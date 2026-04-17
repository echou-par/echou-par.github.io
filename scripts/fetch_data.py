#!/usr/bin/env python3
"""
PAR Intel data fetcher — runs in GitHub Actions on a schedule.
Fetches RSS feeds + Yahoo Finance data, writes JSON to par-comp-intel/data/.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote
import requests
import feedparser

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'par-comp-intel', 'data')
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; PAR-Intel-Bot/1.0; +https://echou-par.github.io/par-comp-intel/)'
}

TICKERS = ['PAR', 'TOST', 'DASH', 'VYX', 'LSPD', 'FOUR', 'SQ', 'GPN', 'FI', 'UBER']

COMPANY_MAP = {
    'PAR': 'PAR', 'TOST': 'Toast', 'DASH': 'DoorDash', 'VYX': 'NCR Voyix',
    'LSPD': 'Lightspeed', 'FOUR': 'Shift4', 'SQ': 'Square', 'GPN': 'Global Payments',
    'FI': 'Fiserv', 'UBER': 'Uber',
}

RANGE_PARAMS = {
    '1W': ('5d', '1d'),
    '1M': ('1mo', '1d'),
    '3M': ('3mo', '1wk'),
    'YTD': ('ytd', '1wk'),
}

RSS_FEEDS = [
    ('Restaurant Dive', 'https://www.restaurantdive.com/feeds/news/'),
    ('Restaurant Technology News', 'https://restauranttechnologynews.com/feed/'),
    ('Hospitality Technology', 'https://hospitalitytech.com/rss.xml'),
    ('Google News – Restaurant Tech', 'https://news.google.com/rss/search?q=%22restaurant+technology%22+OR+%22restaurant+POS%22&hl=en-US&gl=US&ceid=US:en'),
    ('Google News – Competitors', 'https://news.google.com/rss/search?q=Toast+Tab+OR+DoorDash+OR+Lightspeed+POS+OR+Shift4+OR+Clover+POS+OR+SpotOn+OR+Paytronix&hl=en-US&gl=US&ceid=US:en'),
    ('Google News – PAR Technology', 'https://news.google.com/rss/search?q=%22PAR+Technology%22+OR+%22PAR+Brink%22+OR+%22NYSE:+PAR%22&hl=en-US&gl=US&ceid=US:en'),
]

COMP_KEYWORDS = {
    'PAR': ['par technology', 'par tech ', 'brink pos', 'nyse: par', 'par holdings'],
    'Toast': ['toast tab', 'toast inc', 'toasttab', 'nyse: tost', 'toast pos'],
    'DoorDash': ['doordash', 'nyse: dash'],
    'NCR Voyix': ['ncr voyix', 'ncrvoyix', 'nyse: vyx'],
    'Lightspeed': ['lightspeed commerce', 'lightspeed pos', 'nyse: lspd', 'lightspeed hq'],
    'Shift4': ['shift4', 'revel systems', 'revel pos', 'nyse: four'],
    'Square': ['square for restaurants', 'block inc', 'square pos', 'nyse: sq'],
    'Global Payments': ['global payments', 'heartland payment', 'heartland pos', 'nyse: gpn'],
    'Fiserv': ['fiserv', 'clover pos', 'clover network', 'nyse: fi'],
    'Uber Eats': ['uber eats', 'ubereats'],
    'Olo': ['olo inc', 'olo.com'],
    'SpotOn': ['spoton'],
    'TouchBistro': ['touchbistro'],
    'Deliverect': ['deliverect'],
    'Paytronix': ['paytronix'],
    'Snackpass': ['snackpass'],
    'Thanx': ['thanx loyalty', 'thanx inc'],
    'Bikky': ['bikky'],
    'ItsaCheckmate': ['itsacheckmate', "it's a checkmate"],
    'Otter POS': ['otter pos', 'tryotter'],
    'Tillster': ['tillster'],
    'TalonOne': ['talon.one', 'talonone'],
    'Sparkfly': ['sparkfly'],
    'Hang': ['hang.com loyalty', 'hang membership'],
}


def detect_company(text):
    lower = text.lower()
    for company, keywords in COMP_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return company
    return None


def pick_emoji(headline):
    h = headline.lower()
    if any(k in h for k in ['partner', 'integrat', 'deal ', 'teams up', 'joins force']):
        return '🤝'
    if any(k in h for k in ['launch', 'introduc', 'announces', 'unveils', 'debuts', 'new product']):
        return '🚀'
    if any(k in h for k in ['revenue', 'earnings', 'quarter', 'stock', 'shares', 'profit', 'loss', 'beat', 'miss', 'guidance']):
        return '📈'
    if any(k in h for k in ['lawsuit', 'investigation', 'decline', 'concern', 'risk', 'breach', 'downgrade']):
        return '⚠️'
    return '📰'


def fetch_yahoo_chart(ticker, range_key):
    r, interval = RANGE_PARAMS[range_key]
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={r}&interval={interval}&events=history'
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
        chart = data.get('chart', {}).get('result', [None])[0]
        if not chart:
            return None
        closes = [c for c in chart.get('indicators', {}).get('quote', [{}])[0].get('close', []) if c is not None]
        if len(closes) < 2:
            return None
        pct = ((closes[-1] - closes[0]) / closes[0]) * 100
        meta = chart.get('meta', {})
        return {
            'ticker': ticker,
            'company': COMPANY_MAP.get(ticker, ticker),
            'change_pct': round(pct, 2),
            'price': round(meta.get('regularMarketPrice', 0), 2) if meta.get('regularMarketPrice') else None,
            'market_cap_b': round(meta.get('marketCap', 0) / 1e9, 2) if meta.get('marketCap') else None,
        }
    except Exception as e:
        print(f'  Yahoo chart failed for {ticker} ({range_key}): {e}')
        return None


def fetch_yahoo_news(ticker):
    url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US'
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        feed = feedparser.parse(res.text)
        items = []
        for entry in feed.entries[:8]:
            items.append({
                'headline': entry.get('title', ''),
                'url': entry.get('link', ''),
                'date': entry.get('published', ''),
                'source': f'Yahoo Finance ({ticker})',
                'company': COMPANY_MAP.get(ticker, ticker),
                'type': 'public',
                'emoji': '📈',
            })
        return items
    except Exception as e:
        print(f'  Yahoo news failed for {ticker}: {e}')
        return []


def fetch_rss(name, url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        res.raise_for_status()
        feed = feedparser.parse(res.text)
        items = []
        for entry in feed.entries[:40]:
            headline = entry.get('title', '').strip()
            if not headline:
                continue
            items.append({
                'headline': headline,
                'url': entry.get('link', ''),
                'date': entry.get('published', entry.get('updated', '')),
                'source': name,
                'type': 'trade',
            })
        return items
    except Exception as e:
        print(f'  RSS failed for {name}: {e}')
        return []


def main():
    now_iso = datetime.now(timezone.utc).isoformat()

    # ─── Stock data for all ranges ─────────────────────────────────────
    print('Fetching stock data…')
    stock_data = {}
    for range_key in RANGE_PARAMS.keys():
        print(f'  Range {range_key}…')
        results = []
        for t in TICKERS:
            r = fetch_yahoo_chart(t, range_key)
            if r:
                results.append(r)
        stock_data[range_key] = results
    with open(os.path.join(OUT_DIR, 'stocks.json'), 'w') as f:
        json.dump({'updated': now_iso, 'ranges': stock_data}, f, indent=2)
    print(f'  Wrote stocks.json ({sum(len(v) for v in stock_data.values())} total data points)')

    # ─── News from all RSS feeds + Yahoo Finance ───────────────────────
    print('Fetching RSS feeds…')
    all_news = []
    for name, url in RSS_FEEDS:
        items = fetch_rss(name, url)
        print(f'  {name}: {len(items)} items')
        all_news.extend(items)

    print('Fetching Yahoo Finance news…')
    for t in TICKERS:
        items = fetch_yahoo_news(t)
        print(f'  Yahoo {t}: {len(items)} items')
        all_news.extend(items)

    # Tag company + emoji for trade items
    for item in all_news:
        if not item.get('company'):
            detected = detect_company(item['headline'])
            item['company'] = detected or 'Industry'
        if not item.get('emoji'):
            item['emoji'] = pick_emoji(item['headline'])
        # Normalize date to readable format if possible
        try:
            if item.get('date'):
                # feedparser already gave us published_parsed in some cases, but to keep
                # date format consistent, leave raw and let the frontend format it.
                pass
        except Exception:
            pass

    # Keep only competitor-relevant items for news feed
    relevant = [i for i in all_news if i.get('company') and i['company'] != 'Industry']

    # Dedupe by normalized headline
    seen = set()
    deduped = []
    for item in relevant:
        key = re.sub(r'\W+', '', item['headline'].lower())[:80]
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    # Sort by date (descending); items without dates go last
    def parse_dt(s):
        if not s:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            import email.utils
            t = email.utils.parsedate_tz(s)
            if t:
                return datetime.fromtimestamp(email.utils.mktime_tz(t), tz=timezone.utc)
        except Exception:
            pass
        return datetime.min.replace(tzinfo=timezone.utc)

    deduped.sort(key=lambda i: parse_dt(i.get('date', '')), reverse=True)

    # Full news feed (top 40)
    with open(os.path.join(OUT_DIR, 'news.json'), 'w') as f:
        json.dump({'updated': now_iso, 'items': deduped[:40]}, f, indent=2)
    print(f'  Wrote news.json ({len(deduped[:40])} items)')

    # Highlights: top 8 deduped items
    highlights = deduped[:8]
    alert_count = sum(1 for i in highlights if i.get('emoji') == '⚠️')
    with open(os.path.join(OUT_DIR, 'highlights.json'), 'w') as f:
        json.dump({'updated': now_iso, 'items': highlights, 'alert_count': alert_count}, f, indent=2)
    print(f'  Wrote highlights.json ({len(highlights)} items, {alert_count} alerts)')

    # ─── Per-competitor news buckets ───────────────────────────────────
    print('Building per-competitor buckets…')
    per_comp = {}
    for item in deduped:
        c = item['company']
        if c == 'Industry':
            continue
        per_comp.setdefault(c, []).append(item)
    with open(os.path.join(OUT_DIR, 'competitors.json'), 'w') as f:
        json.dump({'updated': now_iso, 'companies': per_comp}, f, indent=2)
    print(f'  Wrote competitors.json ({len(per_comp)} companies)')

    # ─── Summary manifest ──────────────────────────────────────────────
    with open(os.path.join(OUT_DIR, 'manifest.json'), 'w') as f:
        json.dump({
            'updated': now_iso,
            'stocks_count': sum(len(v) for v in stock_data.values()),
            'news_count': len(deduped),
            'highlights_count': len(highlights),
            'alert_count': alert_count,
            'per_competitor_count': len(per_comp),
        }, f, indent=2)
    print(f'\nAll data written to {OUT_DIR}')


if __name__ == '__main__':
    main()
