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
from datetime import datetime, timezone, timedelta
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

# ─── Per-competitor content sources (Phase 1 config map) ────────────────────
#
# Four possible slots per competitor:
#   blog_rss       — marketing/company blog RSS or Atom feed
#   press_rss      — investor-relations or newsroom RSS
#   changelog_rss  — public release notes / API changelog feed
#   site_domain    — domain for Google News site: queries (always fallback-available)
#
# URLs are BEST-EFFORT. The fetcher treats fetch failures (403/404/non-XML/empty
# feed) as "skip silently" — no workflow failures. After the first daily run
# we'll see which endpoints actually returned content and can prune the config.
#
# Note: Toast/DoorDash/Shift4/NCR/Global Payments/Fiserv/Uber/etc. do not publish
# their marketing blogs or changelogs as public RSS. We rely on site: queries via
# Google News for those — covered by the site_domain field below.
COMPETITOR_CONTENT_SOURCES = {
    # Public companies — most don't expose blog RSS; rely primarily on site: queries
    'Toast': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'pos.toasttab.com',
    },
    'DoorDash': {
        'blog_rss': 'https://doordash.engineering/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'blog.doordash.com',
    },
    'NCR Voyix': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'ncrvoyix.com',
    },
    'Lightspeed': {
        'blog_rss': 'https://www.lightspeedhq.com/blog/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'lightspeedhq.com',
    },
    'Shift4': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'shift4.com',
    },
    'Square': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': 'https://developer.squareup.com/changelog.rss',
        'site_domain': 'developer.squareup.com',
    },
    'Global Payments': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'globalpayments.com',
    },
    'Fiserv': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'fiserv.com',
    },
    'Uber Eats': {
        'blog_rss': 'https://www.uber.com/blog/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'uber.com',
    },

    # Private companies — many are on WordPress which exposes /feed/
    'Olo': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': 'https://developers.olo.com/changelog/rss',
        'site_domain': 'olo.com',
    },
    'Thanx': {
        'blog_rss': 'https://www.thanx.com/blog/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'thanx.com',
    },
    'Deliverect': {
        'blog_rss': 'https://www.deliverect.com/en/blog/rss.xml',
        'press_rss': None,
        'changelog_rss': 'https://docs.deliverect.com/changelog/feed',
        'site_domain': 'deliverect.com',
    },
    'TouchBistro': {
        'blog_rss': 'https://www.touchbistro.com/blog/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'touchbistro.com',
    },
    'SpotOn': {
        'blog_rss': 'https://www.spoton.com/blog/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'spoton.com',
    },
    'Bikky': {
        'blog_rss': 'https://www.bikky.com/blog/rss.xml',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'bikky.com',
    },
    'ItsaCheckmate': {
        'blog_rss': 'https://itsacheckmate.com/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'itsacheckmate.com',
    },
    'Otter POS': {
        'blog_rss': 'https://www.tryotter.com/blog/rss.xml',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'tryotter.com',
    },
    'Snackpass': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'snackpass.co',
    },
    'Peppr POS': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'peppr.com',
    },
    'Revi': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'getrevi.com',
    },
    'TalonOne': {
        'blog_rss': 'https://www.talon.one/blog/feed',
        'press_rss': None,
        'changelog_rss': 'https://docs.talon.one/changelog/feed',
        'site_domain': 'talon.one',
    },
    'Sparkfly': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'sparkfly.com',
    },
    'Tillster': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'tillster.com',
    },
    'Paytronix': {
        'blog_rss': 'https://www.paytronix.com/blog/feed/',
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'paytronix.com',
    },
    'Hang': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'hang.com',
    },
    'Spendgo': {
        'blog_rss': None,
        'press_rss': None,
        'changelog_rss': None,
        'site_domain': 'spendgo.com',
    },
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
    # Use word-start boundary so "downgrade" matches "downgrades" but "risk" doesn't
    # match "frisky" (since 'risk' starts at position 2 in 'frisky', not a word boundary).
    def starts_word(word):
        return re.search(r'\b' + re.escape(word), h) is not None

    if any(k in h for k in ['partner', 'integrat', 'teams up', 'joins force']) or starts_word('deal'):
        return '🤝'
    if any(k in h for k in ['launch', 'introduc', 'unveils', 'debuts', 'new product']) or starts_word('announce'):
        return '🚀'
    # Check risk BEFORE financial so "Seaport downgrades X stock" → ⚠️ not 📈
    if any(starts_word(k) for k in ['lawsuit', 'investigation', 'decline', 'concern', 'risk', 'breach', 'downgrade', 'layoff']):
        return '⚠️'
    if any(starts_word(k) for k in ['revenue', 'earning', 'quarter', 'stock', 'share', 'stake', 'profit', 'loss', 'beat', 'miss', 'guidance', 'ipo', 'funding', 'raises', 'valuation', 'round', 'upgrade']):
        return '📈'
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


def detect_alerts(deduped_news, stocks, now_utc_iso):
    """
    Scan the full news corpus (last ~48h) for material, PAR-relevant alerts.
    Returns a list of {category, severity, company, headline, url, source,
    detected_at, par_relevance} dicts and a by-category count dict.

    Categories:
      analyst_downgrade  — broker downgrade / rating cut
      executive_departure — CEO/CFO/president resign / steps down
      guidance_cut        — lowers guidance / cuts forecast / misses
      stock_move          — abs(1W change) >= 7% (using the weekly bucket as proxy for 'material')
      cross_competitor    — single headline mentions 3+ tracked competitors
      regulatory          — SEC / FTC / lawsuit / investigation / subpoena / probe

    PAR relevance scoring (0-3):
      3 — PAR itself, or a direct head-to-head in POS/loyalty/payments
      2 — adjacent competitor (delivery platform, horizontal SaaS)
      1 — tangentially relevant (e.g. Block, Uber)
      0 — not tracked / low relevance
    Only alerts with relevance >= 1 are surfaced.
    """
    alerts = []

    # PAR competitive-zone map → relevance weight
    # Direct head-to-head (POS, loyalty, payments to restaurants)
    PAR_DIRECT = {
        'PAR': 3, 'Toast': 3, 'NCR Voyix': 3, 'Lightspeed': 3, 'SpotOn': 3,
        'TouchBistro': 3, 'Otter POS': 3, 'Revi': 3, 'Peppr POS': 3,
        'Shift4': 3, 'Fiserv': 3, 'Global Payments': 3, 'Square': 3, 'Block': 3,
        'Paytronix': 3, 'Thanx': 3, 'Sparkfly': 3, 'Hang': 3, 'Spendgo': 3,
        'Punchh': 3,
    }
    # Adjacent (delivery aggregators, horizontal, ordering)
    PAR_ADJACENT = {
        'DoorDash': 2, 'Uber Eats': 2, 'Olo': 2, 'Deliverect': 2,
        'ItsaCheckmate': 2, 'Snackpass': 2, 'Bikky': 2, 'Tillster': 2,
        'TalonOne': 2,
    }

    def par_relevance(company):
        if not company:
            return 0
        if company in PAR_DIRECT:
            return PAR_DIRECT[company]
        if company in PAR_ADJACENT:
            return PAR_ADJACENT[company]
        return 0

    # Keyword patterns (word-boundary) per category — tuned to avoid common false positives
    CATEGORY_PATTERNS = [
        # (category, severity_weight, regex_pattern_list)
        ('analyst_downgrade', 'high', [
            r'\bdowngrad',  # downgrade/downgraded/downgrades
            r'\b(cuts?|lowers?|reduces?)\s+(price\s+target|target\s+price|rating)',
            r'\bsell\s+rating',
        ]),
        ('executive_departure', 'high', [
            r'\b(CEO|CFO|COO|President|chief\s+\w+\s+officer)\s+(resign|step\s+down|steps\s+down|depart|exits?|leaves?|ousted|fired)',
            r'\b(resign|step\s+down|steps\s+down|departs?)\s+as\s+(CEO|CFO|COO|President)',
            r'\b(announces?|appoints?)\s+new\s+(CEO|CFO|COO|President)',
        ]),
        ('guidance_cut', 'high', [
            r'\b(cut|lower|reduce|slash)\w*\s+(guidance|outlook|forecast)',
            r'\bmisses?\s+(earnings|revenue|expectations?|estimates?)',
            r'\b(weak|soft|disappointing)\s+(guidance|outlook|quarter|results)',
            r'\bearnings?\s+miss',
        ]),
        ('regulatory', 'medium', [
            r'\b(SEC|FTC|DOJ)\s+(investigation|probe|subpoena|charges?|lawsuit)',
            r'\b(SEC|FTC|DOJ)\s+(files?|launches?)',
            r'\b(class[- ]action|antitrust)\s+(lawsuit|suit|investigation)',
            r'\bsubpoena',
            r'\bdata\s+breach',
            r'\bsecurity\s+breach',
        ]),
    ]

    compiled = [(cat, sev, [re.compile(p, re.IGNORECASE) for p in pats]) for cat, sev, pats in CATEGORY_PATTERNS]

    # Cross-competitor detection: scan headlines for 3+ tracked names via word boundary
    tracked_names = set(COMPETITOR_QUERIES.keys()) | {'Block', 'Square', 'PAR'}

    seen_dedup_keys = set()

    def add_alert(item, category, severity, note=None):
        # Dedup by (category, normalized headline)
        key = (category, re.sub(r'\W+', '', item['headline'].lower())[:80])
        if key in seen_dedup_keys:
            return
        seen_dedup_keys.add(key)

        company = item.get('company', '')
        rel = par_relevance(company)
        if rel == 0 and category != 'cross_competitor':
            return  # filter Option C

        alerts.append({
            'category': category,
            'severity': severity,
            'company': company,
            'headline': item['headline'],
            'url': item.get('url', ''),
            'source': item.get('source', 'Industry'),
            'date': item.get('date', ''),
            'par_relevance': rel,
            'note': note,
            'detected_at': now_utc_iso,
        })

    # Keyword-driven category scan over the last 7 days of news (wider than live feed
    # so rotating in/out of the top 50 feed doesn't silently drop recent downgrades)
    try:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=7)
    except Exception:
        cutoff_dt = None

    for item in deduped_news:
        # Date filter — keep items without parseable dates, drop older than 48h
        item_dt = parse_dt(item.get('date', ''))
        if cutoff_dt and item_dt != datetime.min.replace(tzinfo=timezone.utc) and item_dt < cutoff_dt:
            continue

        headline = item['headline']
        for cat, sev, patterns in compiled:
            for rx in patterns:
                if rx.search(headline):
                    add_alert(item, cat, sev)
                    break  # one category per item

        # Cross-competitor cluster detection
        mentioned = set()
        for name in tracked_names:
            if len(name) < 4:
                continue
            if re.search(r'\b' + re.escape(name) + r'\b', headline, re.IGNORECASE):
                mentioned.add(name)
        if len(mentioned) >= 3:
            # Relevance = max of mentioned companies
            max_rel = max((par_relevance(n) for n in mentioned), default=0)
            if max_rel >= 1:
                key = ('cross_competitor', re.sub(r'\W+', '', headline.lower())[:80])
                if key not in seen_dedup_keys:
                    seen_dedup_keys.add(key)
                    alerts.append({
                        'category': 'cross_competitor',
                        'severity': 'medium',
                        'company': ', '.join(sorted(mentioned)),
                        'headline': headline,
                        'url': item.get('url', ''),
                        'source': item.get('source', 'Industry'),
                        'date': item.get('date', ''),
                        'par_relevance': max_rel,
                        'note': f'{len(mentioned)} tracked competitors co-mentioned',
                        'detected_at': now_utc_iso,
                    })

    # Material stock moves — from weekly stock data (>= 7% abs)
    if stocks and stocks.get('1W'):
        for row in stocks['1W']:
            pct = row.get('change_pct')
            ticker = row.get('ticker')
            company = row.get('company', ticker)
            if pct is None or abs(pct) < 7:
                continue
            rel = par_relevance(company)
            # PAR itself always qualifies even if not in _DIRECT (it is, but explicit)
            if ticker == 'PAR':
                rel = 3
            if rel == 0:
                continue
            direction = 'up' if pct > 0 else 'down'
            alerts.append({
                'category': 'stock_move',
                'severity': 'medium' if abs(pct) < 12 else 'high',
                'company': company,
                'headline': f'{company} ({ticker}) stock {direction} {abs(pct):.1f}% over the past week',
                'url': f'https://finance.yahoo.com/quote/{ticker}',
                'source': 'Yahoo Finance',
                'date': now_utc_iso,
                'par_relevance': rel,
                'note': f'{pct:+.1f}% 1W',
                'detected_at': now_utc_iso,
            })

    # Sort: highest severity first, then highest PAR relevance, then most recent
    severity_rank = {'high': 0, 'medium': 1, 'low': 2}
    alerts.sort(key=lambda a: (
        severity_rank.get(a['severity'], 3),
        -a['par_relevance'],
        -parse_dt(a['date']).timestamp() if a['date'] else 0,
    ))

    # Counts by category (for the overview card breakdown)
    from collections import Counter
    by_category = Counter(a['category'] for a in alerts)

    return {
        'total': len(alerts),
        'by_category': dict(by_category),
        'alerts': alerts,
    }


def generate_insights(deduped_news, per_company, financials, stocks):
    """
    Derive specific, sourced insight bullets from the current news cycle.
    Each insight is grounded in actual articles — no generic truisms.
    Returns a list of {text, sources: [{title, url, source}]} dicts.
    """
    from collections import Counter
    insights = []

    # ── Signal 1: Cross-competitor clustered events ────────────────────────────
    # When a single headline mentions multiple tracked companies, that's a cross-sector signal.
    # Use word-boundary match to avoid false positives (e.g. "Revi" in "Review").
    cross_mentions = []
    tracked_names = set(COMPETITOR_QUERIES.keys()) | {'Block', 'Square'}
    for item in deduped_news:
        headline = item['headline']
        mentioned = set()
        for name in tracked_names:
            if len(name) < 4:
                continue
            # Word-boundary regex — the name must be a whole word, not inside another word
            pattern = r'\b' + re.escape(name) + r'\b'
            if re.search(pattern, headline, re.IGNORECASE):
                mentioned.add(name)
        if len(mentioned) >= 2:
            cross_mentions.append({'item': item, 'companies': sorted(mentioned)})

    for cm in cross_mentions[:2]:
        item = cm['item']
        companies_str = ', '.join(cm['companies'])
        insights.append({
            'text': f"Cross-competitor event: {companies_str} appeared together in coverage — \"{item['headline'][:160]}\"",
            'sources': [{
                'title': item['headline'],
                'url': item.get('url', ''),
                'source': item.get('source', 'Industry'),
            }],
        })

    # ── Signal 2: High-signal thematic density ──────────────────────────────────
    # Prefer specific action-type items (🤝 partnerships, 🚀 products, ⚠️ risks) since
    # financial/market items (📈) are noisy and common. Only surface 📈 with >=5 items.
    emoji_labels_priority = [
        ('🤝', 'partnership', 3),
        ('🚀', 'product launch', 3),
        ('⚠️', 'risk', 2),
        ('📈', 'financial/market', 5),  # higher bar
    ]
    used_companies = set()
    for emoji, label, threshold in emoji_labels_priority:
        candidates = []
        for company, items in per_company.items():
            count = sum(1 for i in items if i.get('emoji') == emoji)
            if count >= threshold and company not in used_companies:
                candidates.append((company, count, items))
        # Sort by count desc, take top 1-2 per emoji type
        candidates.sort(key=lambda x: x[1], reverse=True)
        for company, count, items in candidates[:2]:
            relevant_items = [i for i in items if i.get('emoji') == emoji][:3]
            insights.append({
                'text': f"{company} shows concentrated {label} activity — {count} tracked {label} item{'s' if count != 1 else ''} this cycle. Latest: \"{relevant_items[0]['headline'][:140]}\"",
                'sources': [
                    {'title': i['headline'], 'url': i.get('url', ''), 'source': i.get('source', 'Industry')}
                    for i in relevant_items
                ],
                'company': company,
            })
            used_companies.add(company)

    # ── Signal 3: Notable stock moves (>5% weekly for ANY ticker) ───────────────
    if stocks and stocks.get('1W'):
        moves = stocks['1W']
        big_movers = [m for m in moves if abs(m.get('change_pct') or 0) >= 5]
        big_movers.sort(key=lambda m: abs(m.get('change_pct', 0)), reverse=True)
        for mover in big_movers[:2]:  # reduced from 3 to 2
            pct = mover['change_pct']
            direction = 'gained' if pct > 0 else 'declined'
            # Find supporting news for this company from deduped
            supporting = [i for i in deduped_news if i['company'] == mover['company'] and i.get('emoji') in ('📈', '📰')][:2]
            sources = [
                {'title': i['headline'], 'url': i.get('url', ''), 'source': i.get('source', 'Industry')}
                for i in supporting
            ] or [{'title': f'{mover["ticker"]} on Yahoo Finance', 'url': f'https://finance.yahoo.com/quote/{mover["ticker"]}', 'source': 'Yahoo Finance'}]
            insights.append({
                'text': f"{mover['company']} ({mover['ticker']}) stock {direction} {abs(pct):.1f}% over the past week — material weekly move relative to broader cohort.",
                'sources': sources,
                'company': mover['company'],
            })

    # ── Signal 4: Risk items not already covered ─────────────────────────────────
    risk_items = [i for i in deduped_news if i.get('emoji') == '⚠️']
    for r in risk_items[:2]:
        # Skip if we already have a risk cluster insight for this company
        if any(ins.get('company') == r['company'] and 'risk' in ins.get('text', '').lower() for ins in insights):
            continue
        insights.append({
            'text': f"Risk signal — {r['company']}: \"{r['headline'][:160]}\"",
            'sources': [{'title': r['headline'], 'url': r.get('url', ''), 'source': r.get('source', 'Industry')}],
            'company': r['company'],
        })

    # ── Signal 5: TTM revenue growth outlier ─────────────────────────────────────
    if financials:
        growth_rows = []
        for ticker, fin in financials.items():
            if fin.get('revenue_growth_yoy') is not None:
                growth_rows.append((fin.get('company') or ticker, ticker, fin['revenue_growth_yoy']))
        growth_rows.sort(key=lambda x: x[2], reverse=True)
        if growth_rows:
            top = growth_rows[0]
            if top[2] > 0.2:
                insights.append({
                    'text': f"{top[0]} ({top[1]}) leading revenue growth at {top[2]*100:+.1f}% YoY — fastest grower among tracked public competitors.",
                    'sources': [{'title': f'{top[0]} financials on Yahoo Finance', 'url': f'https://finance.yahoo.com/quote/{top[1]}/financials', 'source': 'Yahoo Finance'}],
                    'company': top[0],
                })

    # De-dupe insights by text similarity and cap
    seen = set()
    final = []
    for ins in insights:
        key = re.sub(r'\W+', '', ins['text'].lower())[:100]
        if key in seen:
            continue
        seen.add(key)
        final.append(ins)
        if len(final) >= 7:
            break

    # ── Most-mentioned companies (with counts for linking) ─────────────────────
    most_mentioned = []
    for company, items in sorted(per_company.items(), key=lambda kv: -len(kv[1]))[:8]:
        most_mentioned.append({
            'company': company,
            'count': len(items),
        })

    return {
        'insights': final,
        'most_mentioned': most_mentioned,
    }


def write_history_snapshot(insights_data, now_iso):
    """
    Append today's insights to the historical daily log, stored in
    par-comp-intel/history/insights-YYYY-MM-DD.json (date in America/New_York).
    Merges additively: existing insights in the file are preserved, new ones appended,
    deduplicated by normalized text. Prunes files older than 30 days.
    Also maintains history/index.json for client discovery.
    """
    try:
        # Use America/New_York since the business cares about ET "business days"
        try:
            import zoneinfo
            et = datetime.now(zoneinfo.ZoneInfo('America/New_York'))
        except Exception:
            # Fallback — approximate ET as UTC-5 (close enough for date bucketing)
            et = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-5)))
        date_str = et.strftime('%Y-%m-%d')
        weekday = et.strftime('%A')

        history_dir = os.path.join(os.path.dirname(OUT_DIR), 'history')
        os.makedirs(history_dir, exist_ok=True)

        today_file = os.path.join(history_dir, f'insights-{date_str}.json')

        # Load existing insights for today (if any) so we can merge additively
        existing_insights = []
        existing_most_mentioned = []
        first_seen_iso = now_iso
        if os.path.exists(today_file):
            try:
                with open(today_file) as f:
                    prev = json.load(f)
                existing_insights = prev.get('insights', [])
                existing_most_mentioned = prev.get('most_mentioned', [])
                first_seen_iso = prev.get('first_seen', now_iso)
            except Exception as e:
                print(f'  Warning: could not read existing {today_file}: {e}')

        # Normalize insights for dedup by their *semantic shape* rather than exact text.
        # Thematic-density insights ("X shows concentrated Y activity — N items ... Latest: ...")
        # should dedup on (company, category) only — the count and example headline change
        # across the day but the underlying signal is the same. Same logic for other insight
        # types: collapse to (category, primary-company) as the identity.
        THEMATIC_RX = re.compile(
            r'^\s*(.+?)\s+shows concentrated\s+(.+?)\s+activity\b',
            re.IGNORECASE,
        )
        STOCK_MOVE_RX = re.compile(
            r'^\s*(.+?)\s*\(([A-Z]+)\)\s+stock\s+(gained|declined)\b',
            re.IGNORECASE,
        )
        CROSS_COMP_RX = re.compile(
            r'^\s*Cross-competitor event:\s*(.+?)\s+appeared together',
            re.IGNORECASE,
        )
        RISK_RX = re.compile(r'^\s*Risk signal\s*—\s*(.+?):', re.IGNORECASE)
        GROWTH_RX = re.compile(r'^\s*(.+?)\s+\([A-Z]+\)\s+leading revenue growth', re.IGNORECASE)

        def text_key(ins):
            text = ins.get('text', '')
            if not text:
                return ''

            # Try semantic shape matchers in priority order
            m = THEMATIC_RX.search(text)
            if m:
                company = m.group(1).strip().lower()
                category = m.group(2).strip().lower()
                return f'thematic::{company}::{category}'

            m = STOCK_MOVE_RX.search(text)
            if m:
                ticker = m.group(2).lower()
                direction = m.group(3).lower()
                return f'stock::{ticker}::{direction}'

            m = CROSS_COMP_RX.search(text)
            if m:
                # Normalize companies-list order so "A, B" and "B, A" dedup
                companies = sorted(c.strip().lower() for c in m.group(1).split(','))
                return f'cross::{"|".join(companies)}'

            m = RISK_RX.search(text)
            if m:
                company = m.group(1).strip().lower()
                return f'risk::{company}'

            m = GROWTH_RX.search(text)
            if m:
                company = m.group(1).strip().lower()
                return f'growth::{company}'

            # Fallback: normalized prefix. Only useful for genuinely unique free-form insights.
            return 'fallback::' + re.sub(r'\W+', '', text.lower())[:140]

        seen_keys = {text_key(ins) for ins in existing_insights if text_key(ins)}

        # Also scrub any duplicates already in the existing file (from earlier buggy runs
        # before this dedup fix — one-time cleanup so old duplicated history corrects itself)
        cleaned_existing = []
        seen_in_existing = set()
        for ins in existing_insights:
            k = text_key(ins)
            if not k or k in seen_in_existing:
                continue
            seen_in_existing.add(k)
            cleaned_existing.append(ins)
        merged_insights = list(cleaned_existing)
        seen_keys = set(seen_in_existing)

        added_this_run = 0
        for ins in insights_data.get('insights', []):
            k = text_key(ins)
            if k and k not in seen_keys:
                seen_keys.add(k)
                merged_ins = dict(ins)
                merged_ins.setdefault('first_detected', now_iso)
                merged_insights.append(merged_ins)
                added_this_run += 1
            elif k and k in seen_keys:
                # Update the existing insight in place when a later run has a better
                # (higher count, fresher example) version of the same signal. Keeps the
                # original first_detected but refreshes the text/sources/company fields.
                for i, existing in enumerate(merged_insights):
                    if text_key(existing) == k:
                        # Keep earliest first_detected timestamp
                        first = existing.get('first_detected', now_iso)
                        updated = dict(ins)
                        updated['first_detected'] = first
                        merged_insights[i] = updated
                        break

        # For most-mentioned, keep the most recent counts (authoritative)
        merged_most_mentioned = insights_data.get('most_mentioned', existing_most_mentioned)

        snapshot = {
            'date': date_str,
            'weekday': weekday,
            'first_seen': first_seen_iso,
            'last_updated': now_iso,
            'insights': merged_insights,
            'most_mentioned': merged_most_mentioned,
        }
        with open(today_file, 'w') as f:
            json.dump(snapshot, f, indent=2)
        print(f'  Wrote history/insights-{date_str}.json ({len(merged_insights)} total insights, +{added_this_run} new this run)')

        # Prune files older than 30 days
        cutoff = et.date() - timedelta(days=30)
        pruned = 0
        for fname in os.listdir(history_dir):
            m = re.match(r'^insights-(\d{4}-\d{2}-\d{2})\.json$', fname)
            if not m:
                continue
            try:
                file_date = datetime.strptime(m.group(1), '%Y-%m-%d').date()
                if file_date < cutoff:
                    os.remove(os.path.join(history_dir, fname))
                    pruned += 1
            except Exception:
                pass
        if pruned:
            print(f'  Pruned {pruned} history file(s) older than 30 days')

        # Rebuild index.json listing all available dates
        dates = []
        for fname in sorted(os.listdir(history_dir), reverse=True):
            m = re.match(r'^insights-(\d{4}-\d{2}-\d{2})\.json$', fname)
            if m:
                date_key = m.group(1)
                try:
                    with open(os.path.join(history_dir, fname)) as f:
                        s = json.load(f)
                    dates.append({
                        'date': date_key,
                        'weekday': s.get('weekday', ''),
                        'insight_count': len(s.get('insights', [])),
                        'last_updated': s.get('last_updated', ''),
                    })
                except Exception:
                    dates.append({'date': date_key, 'weekday': '', 'insight_count': 0, 'last_updated': ''})

        with open(os.path.join(history_dir, 'index.json'), 'w') as f:
            json.dump({'updated': now_iso, 'days': dates}, f, indent=2)
        print(f'  Wrote history/index.json ({len(dates)} days tracked)')

    except Exception as e:
        print(f'  Error writing history snapshot: {e}')
        import traceback
        traceback.print_exc()


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

    with open(os.path.join(OUT_DIR, 'highlights.json'), 'w') as f:
        json.dump({'updated': now_iso, 'items': highlights}, f, indent=2)
    print(f'  Wrote highlights.json ({len(highlights)} items)')

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

    # ── Alerts: scan full corpus (deduped top 50 + per-competitor items) for
    # PAR-relevant, categorized signals ──────────
    full_corpus = list(deduped)
    seen_headlines = {re.sub(r'\W+', '', i['headline'].lower())[:80] for i in full_corpus}
    for company, items in per_comp.items():
        for item in items:
            key = re.sub(r'\W+', '', item['headline'].lower())[:80]
            if key not in seen_headlines:
                seen_headlines.add(key)
                full_corpus.append(item)

    alerts_data = detect_alerts(full_corpus, stock_data, now_iso)
    with open(os.path.join(OUT_DIR, 'alerts.json'), 'w') as f:
        json.dump({'updated': now_iso, **alerts_data}, f, indent=2)
    print(f'  Wrote alerts.json ({alerts_data["total"]} alerts scanning {len(full_corpus)} items)')
    for cat, n in alerts_data['by_category'].items():
        print(f'    {cat}: {n}')

    # Private company curated data (valuations, funding, employees)
    n_private = write_private_data(OUT_DIR)
    print(f'  Wrote private_companies.json ({n_private} companies)')

    # AI-Intelligence Summary insights derived from news + financials
    insights_data = generate_insights(deduped, per_comp, financials, stock_data)
    with open(os.path.join(OUT_DIR, 'insights.json'), 'w') as f:
        json.dump({'updated': now_iso, **insights_data}, f, indent=2)
    print(f'  Wrote insights.json ({len(insights_data["insights"])} insights, {len(insights_data["most_mentioned"])} most-mentioned companies)')

    # ── Historical daily snapshots (additive — never removes existing insights) ──
    write_history_snapshot(insights_data, now_iso)

    with open(os.path.join(OUT_DIR, 'manifest.json'), 'w') as f:
        json.dump({
            'updated': now_iso,
            'financials_count': len(financials),
            'news_count': len(deduped),
            'highlights_count': len(highlights),
            'alert_count': alerts_data['total'],
            'alerts_by_category': alerts_data['by_category'],
            'per_competitor_count': len(per_comp),
            'public_companies_with_news': len(pubs),
            'private_companies_with_news': len(privs),
        }, f, indent=2)
    print(f'\nAll data written to {OUT_DIR}')


if __name__ == '__main__':
    main()
