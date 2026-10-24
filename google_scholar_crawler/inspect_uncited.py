"""Temporary real-data diagnostic; prints no URLs, credentials, or raw responses."""
import json
import os
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from serpapi_source import request_page

author_id = os.environ['GOOGLE_SCHOLAR_ID']
target = author_id + ':iH-uZ7U-co4C'
payload = request_page(author_id, os.environ['SERPAPI_API_KEY'], 0)
article = next(item for item in payload['articles'] if item['citation_id'] == target)
cited_by = article.get('cited_by')
print(json.dumps({
    'target': 'first homepage paper',
    'cited_by_present': 'cited_by' in article,
    'cited_by_keys': sorted(cited_by) if isinstance(cited_by, dict) else None,
    'value_present': isinstance(cited_by, dict) and 'value' in cited_by,
    'value_is_null': isinstance(cited_by, dict) and cited_by.get('value') is None,
    'has_citation_link': bool(cited_by.get('link')) if isinstance(cited_by, dict) else False,
    'has_cites_id': bool(cited_by.get('cites_id')) if isinstance(cited_by, dict) else False,
}))


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.row = None
        self.capturing = False
        self.result = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr' and 'gsc_a_tr' in attrs.get('class', '').split():
            self.row = {'paper_id': None, 'citation_cell_present': False, 'citation_text': ''}
        if self.row is not None and tag == 'a':
            query = parse_qs(urlsplit(attrs.get('href', '')).query)
            if 'citation_for_view' in query:
                self.row['paper_id'] = query['citation_for_view'][0]
            if 'gsc_a_ac' in attrs.get('class', '').split():
                self.row['citation_cell_present'] = True
                self.capturing = True

    def handle_data(self, data):
        if self.row is not None and self.capturing:
            self.row['citation_text'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.capturing = False
        if tag == 'tr' and self.row is not None:
            if self.row['paper_id'] == target:
                self.result = self.row
            self.row = None


raw_url = payload.get('search_metadata', {}).get('raw_html_file', '')
if urlsplit(raw_url).netloc != 'serpapi.com':
    raise RuntimeError('No trusted raw HTML reference returned')
try:
    with urlopen(raw_url, timeout=30) as response:
        html = response.read().decode('utf-8')
except HTTPError as error:
    raise RuntimeError(f'Raw HTML diagnostic returned HTTP {error.code}') from None
parser = Rows()
parser.feed(html)
if parser.result is None:
    raise RuntimeError('First paper row was not found in the returned HTML')
print(json.dumps({
    'raw_html_row_found': True,
    'citation_cell_present': parser.result['citation_cell_present'],
    'citation_text': parser.result['citation_text'].strip(),
}))
