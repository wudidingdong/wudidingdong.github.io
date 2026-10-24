"""Fetch a Scholar author through SerpApi without logging credential-bearing URLs."""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
MAX_PAGES = 5


def count(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'Missing or invalid {field}')
    try:
        number = int(str(value).replace(',', ''))
    except ValueError:
        raise ValueError(f'Missing or invalid {field}') from None
    if number < 0:
        raise ValueError(f'Negative {field}')
    return number


def request_page(author_id, api_key, start):
    params = {
        'engine': 'google_scholar_author', 'author_id': author_id,
        'hl': 'en', 'num': 100, 'start': start, 'api_key': api_key,
    }
    request = Request('https://serpapi.com/search.json?' + urlencode(params))
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.load(response)
    except HTTPError as error:
        hints = {
            401: 'check SERPAPI_API_KEY',
            403: 'check the SerpApi account permissions',
            429: 'check the monthly quota or hourly request limit',
        }
        hint = hints.get(error.code, 'check the SerpApi dashboard')
        # HTTPError includes the complete URL, so never log or chain that exception.
        raise RuntimeError(f'SerpApi HTTP {error.code}: {hint}') from None
    except (URLError, TimeoutError):
        raise RuntimeError('SerpApi connection failed or timed out') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('SerpApi returned invalid JSON') from None
    if not isinstance(payload, dict):
        raise ValueError('SerpApi returned an invalid response object')
    if payload.get('error') or payload.get('search_metadata', {}).get('status') != 'Success':
        raise RuntimeError('SerpApi search did not succeed; check its dashboard')
    response_id = payload.get('search_parameters', {}).get('author_id')
    if response_id and response_id != author_id:
        raise ValueError('SerpApi returned a different author profile')
    return payload


def author_metrics(payload, author_id):
    profile = payload.get('author', {})
    if not isinstance(profile.get('name'), str) or not profile['name'].strip():
        raise ValueError('SerpApi response is missing the author name')
    cited_by = payload.get('cited_by', {})
    metrics = {}
    for row in cited_by.get('table', []):
        metrics.update(row)
    author = {
        'container_type': 'Author', 'source': 'AUTHOR_PROFILE_PAGE',
        'provider': 'SerpApi', 'scholar_id': author_id,
        'name': profile['name'], 'affiliation': profile.get('affiliations', ''),
    }
    for source, target in (('citations', 'citedby'), ('h_index', 'hindex'), ('i10_index', 'i10index')):
        metric = metrics.get(source, {})
        author[target] = count(metric.get('all'), source)
        recent = [value for key, value in metric.items() if key.startswith('since_')]
        if recent:
            author[target + '5y'] = count(recent[0], source + ' (recent)')
    graph = cited_by.get('graph')
    if not isinstance(graph, list) or (author['citedby'] > 0 and not graph):
        raise ValueError('SerpApi response is missing yearly citation counts')
    author['cites_per_year'] = {
        str(count(row.get('year'), 'year')): count(row.get('citations'), 'yearly citations')
        for row in graph
    }
    return author


def fetch_author(author_id, api_key):
    publications = {}
    author = None
    start = 0
    for page_number in range(1, MAX_PAGES + 1):
        logger.info('Requesting SerpApi author page %s (offset=%s)', page_number, start)
        payload = request_page(author_id, api_key, start)
        if author is None:
            author = author_metrics(payload, author_id)
        articles = payload.get('articles')
        if not isinstance(articles, list) or not articles:
            raise ValueError('SerpApi response is missing publications')
        previous_count = len(publications)
        for article in articles:
            paper_id = article.get('citation_id')
            if not isinstance(paper_id, str) or not paper_id.startswith(author_id + ':'):
                raise ValueError('Missing or mismatched publication ID')
            paper = {
                'author_pub_id': paper_id,
                'bib': {
                    'title': article.get('title', ''),
                    'pub_year': article.get('year', ''),
                    'citation': article.get('publication', ''),
                },
            }
            cited_by = article.get('cited_by')
            # SerpApi uses this exact marker for a blank Scholar citation cell.
            # Verified against the first homepage paper's cached source HTML.
            if cited_by == {'value': None}:
                paper['num_citations'] = 0
            elif isinstance(cited_by, dict) and cited_by.get('value') is not None:
                paper['num_citations'] = count(cited_by['value'], 'paper citations')
            # Absent or incomplete metadata stays unknown rather than becoming zero.
            publications[paper_id] = paper
        if len(publications) == previous_count:
            raise ValueError('Pagination returned no new publications')
        next_url = payload.get('serpapi_pagination', {}).get('next')
        if not next_url:
            author['publications'] = list(publications.values())
            return author
        # Parse only the offset; always send credentials to our fixed SerpApi endpoint.
        parsed = urlsplit(next_url)
        if parsed.scheme != 'https' or parsed.netloc != 'serpapi.com':
            raise ValueError('Unexpected pagination address')
        query = parse_qs(parsed.query)
        offsets = query.get('start') or query.get('cstart') or []
        next_start = count(offsets[0] if offsets else None, 'pagination offset')
        if next_start <= start:
            raise ValueError('Pagination did not advance')
        start = next_start
    raise ValueError('SerpApi page limit exceeded; refusing to publish partial data')
