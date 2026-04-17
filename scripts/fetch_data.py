#!/usr/bin/env python3
"""
PAR Intel data fetcher — runs in GitHub Actions on a schedule.
Fetches:
  - Stock price across 1W/1M/3M/YTD
  - Income Statement, Balance Sheet, TTM metrics for public companies
  - Multi-source news (trade press, Google News per-competitor, Yahoo Finance)
Writes JSON to par-comp-intel/data/.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
import requests
import feedparser

sys.path.insert(0, os.path.dirname(__file__))
from private_company_data import write_private_data

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'par-comp-intel', 'data')
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

TICKERS = ['PAR', 'TOST', 'DASH', 'VYX', 'LSPD', 'FOUR', 'XYZ', 'GPN', 'FISV', 'UBER']

COMPANY_MAP = {
    'PAR': 'PAR', 'TOST': 'Toast', 'DASH': 'DoorDash', 'VYX': 'NCR Voyix',
    'LSPD': 'Lightspeed', 'FOUR': 'Shift4', 'XYZ': 'Block (Square)', 'GPN': 'Global Payments',
    'FISV': 'Fiserv', 'UBER': 'Uber',
}

RANGE_PARAMS = {
    '1W': ('5d', '1d'),
    '1M': ('1mo', '1d'),
    '3M': ('3mo', '1wk'),
    'YTD': ('ytd', '1wk'),
}

PRIVATE_COMPANIES = [
    'Olo', 'Thanx', 'Deliverect', 'TouchBistro', 'SpotOn', 'Bikky',
    'ItsaCheckmate', 'Otter POS', 'Snackpass', 'Peppr POS', 'Revi',
    'TalonOne', 'Sparkfly', 'Tillster', 'Paytronix', 'Hang', 'Spendgo',
]

RSS_FEEDS = [
    ('Restaurant Dive', 'https://www.restaurantdive.com/feeds/news/'),
    ('Restaurant Technology News', 'https://restauranttechnologynews.com/feed/'),
    ('Hospitality Technology', 'https://hospitalitytech.com/rss.xml'),
    ('QSR Magazine', 'https://www.qsrmagazine.com/rss.xml'),
    ('Modern Restaurant Management', 'https://modernrestaurantmanagement.com/feed/'),
    ('Google News - Restaurant Tech', 'https://news.google.com/rss/search?q=%22restaurant+technology%22+OR+%22restaurant+POS%22&hl=en-US&gl=US&ceid=US:en'),
    ('Google News - POS Industry', 'https://news.google.com/rss/search?q=%22point+of+sale%22+restaurant+OR+%22POS+system%22+restaurant&hl=en-US&gl=US&ceid=US:en'),
    ('Google News - Restaurant Loyalty', 'https://news.google.com/rss/search?q=restaurant+loyalty+platform+OR+restaurant+CRM&hl=en-US&gl=US&ceid=US:en'),
    ('Google News - Restaurant M&A', 'https://news.google.com/rss/search?q=restaurant+technology+acquisition+OR+restaurant+SaaS+funding&hl=en-US&gl=US&ceid=US:en'),
]

COMPETITOR_QUERIES = {
    'PAR': '%22PAR+Technology%22+OR+%22PAR+Brink%22+OR+%22NYSE%3A+PAR%22',
    'Toast': '%22Toast+Inc%22+OR+%22Toast+Tab%22+OR+%22NYSE%3A+TOST%22',
    'DoorDash': '%22DoorDash%22+restaurant+OR+%22NYSE%3A+DASH%22',
    'NCR Voyix': '%22NCR+Voyix%22+OR+%22NYSE%3A+VYX%22',
    'Lightspeed': '%22Lightspeed+Commerce%22+OR+%22Lightspeed+POS%22+OR+%22NYSE%3A+LSPD%22',
    'Shift4': '%22Shift4%22+OR+%22Revel+Systems%22+OR+%22NYSE%3A+FOUR%22',
    'Square': '%22Square+for+Restaurants%22+OR+%22Block+Inc%22+restaurant+OR+%22NYSE%3A+SQ%22',
    'Global Payments': '%22Global+Payments%22+Heartland+OR+%22Heartland+POS%22+OR+%22NYSE%3A+GPN%22',
    'Fiserv': '%22Fiserv%22+Clover+OR+%22Clover+POS%22+OR+%22NYSE%3A+FI%22',
    'Uber Eats': '%22Uber+Eats%22+restaurant',
    'Olo': '%22Olo+Inc%22+OR+%22Olo+ordering%22',
    'Thanx': '%22Thanx+loyalty%22+OR+%22Thanx+Inc%22+restaurant',
    'Deliverect': '%22Deliverect%22',
    'TouchBistro': '%22TouchBistro%22',
    'SpotOn': '%22SpotOn%22+restaurant',
    'Bikky': '%22Bikky%22+restaurant',
    'ItsaCheckmate': '%22ItsaCheckmate%22+OR+%22Checkmate%22+restaurant',
    'Otter POS': '%22Otter+POS%22+OR+%22tryotter%22+OR+%22Otter+restaurant%22',
    'Snackpass': '%22Snackpass%22',
    'Peppr POS': '%22Peppr+POS%22+OR+%22Peppr+restaurant%22',
    'Revi': '%22GetRevi%22+OR+%22Revi+restaurant%22',
    'TalonOne': '%22Talon.One%22+OR+%22TalonOne%22',
    'Sparkfly': '%22Sparkfly%22',
    'Tillster': '%22Tillster%22',
    'Paytronix': '%22Paytronix%22',
    'Hang': '%22Hang+loyalty%22+OR+%22Hang+membership%22+restaurant',
    'Spendgo': '%22Spendgo%22',
}

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
    'Olo': ['olo inc', 'olo.com', ' olo '],
    'SpotOn': ['spoton'],
    'TouchBistro': ['touchbistro'],
    'Deliverect': ['deliverect'],
    'Paytronix': ['paytronix'],
    'Snackpass': ['snackpass'],
    'Thanx': ['thanx loyalty', 'thanx inc', ' thanx '],
    'Bikky': [' bikky '],
    'ItsaCheckmate': ['itsacheckmate', "it's a checkmate"],
    'Otter POS': ['otter pos', 'tryotter'],
    'Tillster': ['tillster'],
    'TalonOne': ['talon.one', 'talonone'],
    'Sparkfly': ['sparkfly'],
    'Peppr POS': ['peppr pos', 'peppr restaurant'],
    'Revi': ['getrevi', 'revi restaurant'],
    'Hang': ['hang.com loyalty', 'hang membership', 'hang loyalty'],
    'Spendgo': ['spendgo'],
}


def detect_company(text):
    lower = ' ' + text.lower() + ' '
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
    if any(k in h for k in ['revenue', 'earnings', 'quarter', 'stock', 'shares', 'profit', 'loss', 'beat', 'miss', 'guidance', 'ipo', 'funding', 'raises', 'valuation', 'round']):
        return '📈'
    if any(k in h for k in ['lawsuit', 'investigation', 'decline', 'concern', 'risk', 'breach', 'downgrade', 'layoff']):
        return '⚠️'
    return '📰'


def normalize_for_dedup(text):
    text = re.sub(r'\s*[-|]\s*(MSN|Reuters|Bloomberg|CNBC|Yahoo|Seeking Alpha|The Motley Fool|Barrons?|Business Wire|PR Newswire|GlobeNewswire).*$', '', text, flags=re.IGNORECASE)
    words = re.findall(r'[a-z0-9$]+', text.lower())
    stop = {'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'at', 'by', 'is', 'as', 'with', 'from', 'that', 'this', 's'}
    return frozenset(w for w in words if w not in stop and len(w) > 1)


def is_duplicate(item_tokens, seen_token_sets, threshold=0.6):
    if not item_tokens:
        return True
    for seen in seen_token_sets:
        if not seen:
            continue
        intersect = len(item_tokens & seen)
        union = len(item_tokens | seen)
        if union and intersect / union >= threshold:
            return True
    return False


def fetch_yahoo_chart(ticker, range_key, retries=2):
    """Use yfinance to get price history — handles cookies/crumb properly on GitHub runners."""
    import yfinance as yf
    r, _interval = RANGE_PARAMS[range_key]
    # Map range_key to yfinance period format
    period_map = {'1W': '5d', '1M': '1mo', '3M': '3mo', 'YTD': 'ytd'}
    interval_map = {'1W': '1d', '1M': '1d', '3M': '1wk', 'YTD': '1wk'}
    period = period_map.get(range_key, '5d')
    interval = interval_map.get(range_key, '1d')
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, interval=interval, auto_adjust=True)
            if hist is None or hist.empty or len(hist) < 2:
                return None
            closes = [float(v) for v in hist['Close'].dropna().tolist()]
            if len(closes) < 2:
                return None
            pct = ((closes[-1] - closes[0]) / closes[0]) * 100
            # Try to get current price from fast_info, fall back to last close
            price = None
            try:
                price = float(t.fast_info.get('last_price') or closes[-1])
            except Exception:
                price = closes[-1]
            return {
                'ticker': ticker,
                'company': COMPANY_MAP.get(ticker, ticker),
                'change_pct': round(pct, 2),
                'price': round(price, 2) if price else None,
            }
        except Exception as e:
            if attempt == retries:
                print(f'  yfinance chart failed for {ticker} ({range_key}): {e}')
            else:
                time.sleep(1)
    return None


def _safe_num(v):
    """Coerce pandas/numpy scalar to python float."""
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN check
            return None
        return f
    except Exception:
        return None


def _df_col_to_dict(df, col):
    """Given a financials DataFrame and a column (period), return dict of row→value."""
    try:
        if df is None or df.empty or col not in df.columns:
            return {}
        series = df[col]
        # Convert index (row labels) + values to dict
        return {str(idx): _safe_num(v) for idx, v in series.items()}
    except Exception:
        return {}


def _map_statement(period_dict, end_date):
    """Map yfinance statement row names to our canonical schema."""
    out = {'endDate': end_date}
    # yfinance uses these canonical labels (as of yfinance ~0.2.x / 2026)
    mapping = {
        'totalRevenue':                  ['Total Revenue', 'Revenue', 'Operating Revenue'],
        'costOfRevenue':                 ['Cost Of Revenue', 'Cost of Revenue'],
        'grossProfit':                   ['Gross Profit'],
        'researchDevelopment':           ['Research And Development', 'Research & Development', 'Research Development'],
        'sellingGeneralAdministrative':  ['Selling General And Administration', 'Selling General and Administration', 'Selling General Administrative'],
        'totalOperatingExpenses':        ['Operating Expense', 'Total Operating Expenses'],
        'operatingIncome':               ['Operating Income'],
        'ebit':                          ['EBIT'],
        'netIncome':                     ['Net Income', 'Net Income Common Stockholders'],
        'incomeBeforeTax':               ['Pretax Income', 'Income Before Tax'],
        # Balance sheet
        'cash':                          ['Cash And Cash Equivalents', 'Cash'],
        'shortTermInvestments':          ['Other Short Term Investments', 'Short Term Investments'],
        'netReceivables':                ['Accounts Receivable', 'Receivables'],
        'totalCurrentAssets':            ['Current Assets'],
        'totalAssets':                   ['Total Assets'],
        'totalCurrentLiabilities':       ['Current Liabilities'],
        'longTermDebt':                  ['Long Term Debt'],
        'totalLiab':                     ['Total Liabilities Net Minority Interest', 'Total Liab'],
        'totalStockholderEquity':        ['Stockholders Equity', 'Common Stock Equity', 'Total Equity Gross Minority Interest'],
        'goodWill':                      ['Goodwill'],
        'intangibleAssets':              ['Other Intangible Assets', 'Intangible Assets'],
    }
    for our_key, candidates in mapping.items():
        for candidate in candidates:
            if candidate in period_dict and period_dict[candidate] is not None:
                out[our_key] = period_dict[candidate]
                break
    return out


def fetch_yahoo_quote_summary(ticker, retries=2):
    """Use yfinance to get comprehensive financials (market cap, TTM, income stmt, balance sheet)."""
    import yfinance as yf
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            def parse_df(df):
                """Take yfinance financials DataFrame and return list of period-dicts."""
                if df is None or df.empty:
                    return []
                periods = []
                # Columns are timestamps (dates); take first N
                for col in df.columns:
                    end_date = col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)
                    period_dict = {str(idx): _safe_num(v) for idx, v in df[col].items()}
                    periods.append(_map_statement(period_dict, end_date))
                return periods

            income_a = parse_df(t.income_stmt)[:3]
            income_q_all = parse_df(t.quarterly_income_stmt)[:8]  # need 8 for YoY
            income_q = income_q_all[:4]
            balance_a = parse_df(t.balance_sheet)[:2]
            balance_q = parse_df(t.quarterly_balance_sheet)[:2]

            # TTM fallback: when .info omits totalRevenue/ebitda (happens for some tickers
            # like FISV), derive from the 4 most recent quarters of income statements.
            def sum_last_4_quarters(key):
                vals = [q.get(key) for q in income_q_all[:4] if q.get(key) is not None]
                if len(vals) >= 4:
                    return sum(vals[:4])
                return None

            def compute_yoy_from_quarters(key):
                """Compare last 4Q sum to preceding 4Q sum. Requires 8 quarters."""
                vals = [q.get(key) for q in income_q_all[:8] if q.get(key) is not None]
                if len(vals) >= 8:
                    recent = sum(vals[:4])
                    prior = sum(vals[4:8])
                    if prior and prior != 0:
                        return (recent - prior) / abs(prior)
                # Fall back to annual YoY
                if len(income_a) >= 2:
                    curr = income_a[0].get(key)
                    prev = income_a[1].get(key)
                    if curr is not None and prev and prev != 0:
                        return (curr - prev) / abs(prev)
                return None

            # Resolve TTM with fallbacks
            ttm_revenue = _safe_num(info.get('totalRevenue')) or sum_last_4_quarters('totalRevenue')
            ttm_ebitda = _safe_num(info.get('ebitda'))
            # For EBITDA, we don't have it in income statement rows, but we can approximate
            # as operating income + D&A; however D&A isn't in the mapped keys. Fall back to
            # operating income as proxy if ebitda is missing.
            ttm_operating_income = sum_last_4_quarters('operatingIncome')
            if ttm_ebitda is None and ttm_operating_income is not None:
                ttm_ebitda = ttm_operating_income  # approximation; labeled in UI

            # Resolve YoY growth with fallback
            revenue_growth_yoy = _safe_num(info.get('revenueGrowth'))
            if revenue_growth_yoy is None:
                revenue_growth_yoy = compute_yoy_from_quarters('totalRevenue')

            # Resolve EBITDA margin
            ebitda_margin = _safe_num(info.get('ebitdaMargins'))
            if ebitda_margin is None and ttm_ebitda and ttm_revenue:
                ebitda_margin = ttm_ebitda / ttm_revenue

            # Gross margin fallback
            gross_margin = _safe_num(info.get('grossMargins'))
            if gross_margin is None:
                ttm_gross = sum_last_4_quarters('grossProfit')
                if ttm_gross and ttm_revenue:
                    gross_margin = ttm_gross / ttm_revenue

            # Market cap from fast_info (most reliable) with fallback to info
            try:
                market_cap = _safe_num(t.fast_info.get('market_cap'))
            except Exception:
                market_cap = None
            if not market_cap:
                market_cap = _safe_num(info.get('marketCap'))

            # Price similarly
            try:
                price = _safe_num(t.fast_info.get('last_price'))
            except Exception:
                price = None
            if not price:
                price = _safe_num(info.get('regularMarketPrice') or info.get('currentPrice'))

            return {
                'ticker': ticker,
                'company': COMPANY_MAP.get(ticker, ticker),
                'price': price,
                'market_cap': market_cap,
                'ttm_revenue': ttm_revenue,
                'ttm_ebitda': ttm_ebitda,
                'ttm_gross_profit': _safe_num(info.get('grossProfits')) or sum_last_4_quarters('grossProfit'),
                'revenue_growth_yoy': revenue_growth_yoy,
                'ebitda_margin': ebitda_margin,
                'gross_margin': gross_margin,
                'enterprise_value': _safe_num(info.get('enterpriseValue')),
                'trailing_pe': _safe_num(info.get('trailingPE')),
                'forward_pe': _safe_num(info.get('forwardPE')),
                'income_statement_annual': income_a,
                'income_statement_quarterly': income_q,
                'balance_sheet_annual': balance_a,
                'balance_sheet_quarterly': balance_q,
            }
        except Exception as e:
            if attempt == retries:
                print(f'  yfinance quoteSummary failed for {ticker}: {e}')
            else:
                time.sleep(1.5)
    return None


def fetch_yahoo_news(ticker, retries=1):
    url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US'
    for attempt in range(retries + 1):
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            res.raise_for_status()
            feed = feedparser.parse(res.text)
            items = []
            for entry in feed.entries[:12]:
                items.append({
                    'headline': entry.get('title', ''),
                    'url': entry.get('link', ''),
                    'date': entry.get('published', ''),
                    'source': f'Yahoo Finance ({ticker})',
                    'company': COMPANY_MAP.get(ticker, ticker),
                    'type': 'public',
                })
            return items
        except Exception as e:
            if attempt == retries:
                print(f'  Yahoo news failed for {ticker}: {e}')
            else:
                time.sleep(1)
    return []


def fetch_competitor_google_news(company, query):
    url = f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        res.raise_for_status()
        feed = feedparser.parse(res.text)
        items = []
        for entry in feed.entries[:15]:
            items.append({
                'headline': entry.get('title', '').strip(),
                'url': entry.get('link', ''),
                'date': entry.get('published', ''),
                'source': 'Google News',
                'company': company,
                'type': 'private' if company in PRIVATE_COMPANIES else 'public',
            })
        return items
    except Exception as e:
        print(f'  Google News failed for {company}: {e}')
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


def main():
    now_iso = datetime.now(timezone.utc).isoformat()

    # Stock chart data
    print('Fetching stock chart data…')
    stock_data = {}
    for range_key in RANGE_PARAMS.keys():
        print(f'  Range {range_key}…')
        results = []
        for t in TICKERS:
            r = fetch_yahoo_chart(t, range_key)
            if r:
                results.append(r)
            time.sleep(0.3)
        stock_data[range_key] = results
    with open(os.path.join(OUT_DIR, 'stocks.json'), 'w') as f:
        json.dump({'updated': now_iso, 'ranges': stock_data}, f, indent=2)
    print('  Wrote stocks.json')

    # Comprehensive financials
    print('\nFetching comprehensive financials…')
    financials = {}
    for t in TICKERS:
        print(f'  {t}…')
        data = fetch_yahoo_quote_summary(t)
        if data:
            financials[t] = data
        time.sleep(0.5)
    with open(os.path.join(OUT_DIR, 'financials.json'), 'w') as f:
        json.dump({'updated': now_iso, 'tickers': financials}, f, indent=2)
    print(f'  Wrote financials.json ({len(financials)} tickers)')

    # News from all sources
    print('\nFetching broad RSS feeds…')
    all_news = []
    for name, url in RSS_FEEDS:
        items = fetch_rss(name, url)
        print(f'  {name}: {len(items)} items')
        all_news.extend(items)
        time.sleep(0.5)

    print('\nFetching Yahoo Finance news per ticker…')
    for t in TICKERS:
        items = fetch_yahoo_news(t)
        print(f'  Yahoo {t}: {len(items)} items')
        all_news.extend(items)
        time.sleep(0.3)

    print('\nFetching per-competitor Google News…')
    for company, query in COMPETITOR_QUERIES.items():
        items = fetch_competitor_google_news(company, query)
        print(f'  {company}: {len(items)} items')
        all_news.extend(items)
        time.sleep(0.4)

    for item in all_news:
        if not item.get('company'):
            detected = detect_company(item['headline'])
            item['company'] = detected or 'Industry'
        if not item.get('emoji'):
            item['emoji'] = pick_emoji(item['headline'])

    relevant = [i for i in all_news if i.get('company') and i['company'] != 'Industry']
    relevant.sort(key=lambda i: parse_dt(i.get('date', '')), reverse=True)

    # Dedup
    print('\nDeduplicating news…')
    seen_token_sets = []
    deduped = []
    for item in relevant:
        tokens = normalize_for_dedup(item['headline'])
        if is_duplicate(tokens, seen_token_sets):
            continue
        seen_token_sets.append(tokens)
        deduped.append(item)
    print(f'  {len(relevant)} relevant → {len(deduped)} after dedup')

    with open(os.path.join(OUT_DIR, 'news.json'), 'w') as f:
        json.dump({'updated': now_iso, 'items': deduped[:50]}, f, indent=2)
    print(f'  Wrote news.json ({min(50, len(deduped))} items)')

    # Highlights: diversified (1 per company, balance public/private)
    by_company = {}
    for item in deduped:
        c = item['company']
        if c not in by_company:
            by_company[c] = item

    public_cos = ['PAR', 'Toast', 'DoorDash', 'NCR Voyix', 'Lightspeed', 'Shift4', 'Square', 'Global Payments', 'Fiserv', 'Uber', 'Uber Eats']
    pubs = sorted([by_company[c] for c in by_company if c in public_cos],
                  key=lambda i: parse_dt(i.get('date', '')), reverse=True)
    privs = sorted([by_company[c] for c in by_company if c not in public_cos],
                   key=lambda i: parse_dt(i.get('date', '')), reverse=True)

    highlights = []
    for i in range(max(len(pubs), len(privs))):
        if i < len(pubs):
            highlights.append(pubs[i])
        if i < len(privs):
            highlights.append(privs[i])
        if len(highlights) >= 10:
            break
    highlights = highlights[:10]
    alert_count = sum(1 for i in highlights if i.get('emoji') == '⚠️')

    with open(os.path.join(OUT_DIR, 'highlights.json'), 'w') as f:
        json.dump({'updated': now_iso, 'items': highlights, 'alert_count': alert_count}, f, indent=2)
    print(f'  Wrote highlights.json ({len(highlights)} items, {alert_count} alerts)')

    # Per-competitor news
    per_comp = {}
    for item in deduped:
        c = item['company']
        if c == 'Industry':
            continue
        per_comp.setdefault(c, []).append(item)

    # Ensure every tracked company has at least some news (fallback to raw pre-dedup)
    for company in COMPETITOR_QUERIES.keys():
        if company not in per_comp or len(per_comp[company]) < 3:
            company_specific = [i for i in relevant if i['company'] == company]
            if company_specific:
                per_comp[company] = company_specific[:10]

    with open(os.path.join(OUT_DIR, 'competitors.json'), 'w') as f:
        json.dump({'updated': now_iso, 'companies': per_comp}, f, indent=2)
    print(f'  Wrote competitors.json ({len(per_comp)} companies)')

    # Private company curated data (valuations, funding, employees)
    n_private = write_private_data(OUT_DIR)
    print(f'  Wrote private_companies.json ({n_private} companies)')

    with open(os.path.join(OUT_DIR, 'manifest.json'), 'w') as f:
        json.dump({
            'updated': now_iso,
            'financials_count': len(financials),
            'news_count': len(deduped),
            'highlights_count': len(highlights),
            'alert_count': alert_count,
            'per_competitor_count': len(per_comp),
            'public_companies_with_news': len(pubs),
            'private_companies_with_news': len(privs),
        }, f, indent=2)
    print(f'\nAll data written to {OUT_DIR}')


if __name__ == '__main__':
    main()
