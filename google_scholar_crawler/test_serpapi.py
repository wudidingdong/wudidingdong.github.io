import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import main as crawler
import serpapi_source as source


AUTHOR = 'test-author'
KEY = 'test-secret-never-log'


def response(paper='paper-1'):
    return {
        'search_metadata': {'status': 'Success'},
        'search_parameters': {'author_id': AUTHOR},
        'author': {'name': 'Test Author', 'affiliations': 'Test University'},
        'cited_by': {
            'table': [
                {'citations': {'all': '398', 'since_2021': 394}},
                {'h_index': {'all': 12, 'since_2021': 12}},
                {'i10_index': {'all': 13, 'since_2021': 13}},
            ],
            'graph': [{'year': 2026, 'citations': '118'}],
        },
        'articles': [{
            'citation_id': AUTHOR + ':' + paper, 'title': 'Test article',
            'publication': 'Test Journal, 2026', 'year': '2026',
            'cited_by': {'value': 0},
        }],
    }


class ConversionTests(unittest.TestCase):
    def test_metrics_and_publication_ids_match_existing_schema(self):
        with patch.object(source, 'request_page', return_value=response()) as request:
            author = source.fetch_author(AUTHOR, KEY)
        request.assert_called_once_with(AUTHOR, KEY, 0)
        self.assertEqual((author['citedby'], author['hindex'], author['i10index']), (398, 12, 13))
        self.assertEqual(author['citedby5y'], 394)
        self.assertEqual(author['cites_per_year'], {'2026': 118})
        self.assertEqual(author['publications'][0]['author_pub_id'], AUTHOR + ':paper-1')
        self.assertEqual(author['publications'][0]['num_citations'], 0)
        self.assertNotIn(KEY, json.dumps(author))

    def test_missing_paper_count_is_not_fabricated_as_zero(self):
        payload = response()
        payload['articles'][0]['cited_by'] = {}
        with patch.object(source, 'request_page', return_value=payload):
            author = source.fetch_author(AUTHOR, KEY)
        self.assertNotIn('num_citations', author['publications'][0])

    def test_uncited_null_marker_is_converted_to_zero(self):
        payload = response()
        payload['articles'][0]['cited_by'] = {'value': None}
        with patch.object(source, 'request_page', return_value=payload):
            author = source.fetch_author(AUTHOR, KEY)
        self.assertEqual(author['publications'][0]['num_citations'], 0)

    def test_partial_citation_reference_is_not_guessed_as_zero(self):
        payload = response()
        payload['articles'][0]['cited_by'] = {'value': None, 'link': 'https://scholar.google.com/scholar?cites=123'}
        with patch.object(source, 'request_page', return_value=payload):
            author = source.fetch_author(AUTHOR, KEY)
        self.assertNotIn('num_citations', author['publications'][0])

    def test_both_documented_pagination_offsets_are_supported(self):
        for parameter in ('start', 'cstart'):
            with self.subTest(parameter=parameter):
                first, second = response(), response('paper-2')
                first['serpapi_pagination'] = {'next': f'https://serpapi.com/search.json?{parameter}=100'}
                with patch.object(source, 'request_page', side_effect=[first, second]) as request:
                    author = source.fetch_author(AUTHOR, KEY)
                self.assertEqual(len(author['publications']), 2)
                self.assertEqual(request.call_args_list[1].args, (AUTHOR, KEY, 100))

    def test_invalid_pagination_or_repeated_pages_are_rejected(self):
        for next_url in ('https://example.org/?start=100', 'https://serpapi.com/search.json?start=0'):
            with self.subTest(next_url=next_url):
                first = response()
                first['serpapi_pagination'] = {'next': next_url}
                with patch.object(source, 'request_page', return_value=first), self.assertRaises(ValueError):
                    source.fetch_author(AUTHOR, KEY)
        first = response()
        first['serpapi_pagination'] = {'next': 'https://serpapi.com/search.json?start=100'}
        with patch.object(source, 'request_page', side_effect=[first, response()]), self.assertRaisesRegex(ValueError, 'no new'):
            source.fetch_author(AUTHOR, KEY)

    def test_page_budget_does_not_publish_truncated_data(self):
        first, second = response(), response('paper-2')
        first['serpapi_pagination'] = {'next': 'https://serpapi.com/search.json?start=100'}
        second['serpapi_pagination'] = {'next': 'https://serpapi.com/search.json?start=200'}
        with patch.object(source, 'MAX_PAGES', 2), patch.object(source, 'request_page', side_effect=[first, second]) as request, self.assertRaisesRegex(ValueError, 'page limit'):
            source.fetch_author(AUTHOR, KEY)
        self.assertEqual(request.call_count, 2)

    def test_incomplete_metrics_and_wrong_author_are_rejected(self):
        incomplete = response()
        incomplete['cited_by']['table'] = []
        with patch.object(source, 'request_page', return_value=incomplete), self.assertRaises(ValueError):
            source.fetch_author(AUTHOR, KEY)
        wrong_paper = response()
        wrong_paper['articles'][0]['citation_id'] = 'another-author:paper-1'
        with patch.object(source, 'request_page', return_value=wrong_paper), self.assertRaisesRegex(ValueError, 'mismatched'):
            source.fetch_author(AUTHOR, KEY)

    def test_numeric_strings_are_accepted_but_invalid_counts_are_not(self):
        self.assertEqual(source.count('1,234', 'count'), 1234)
        for invalid in (None, True, -1, 1.5, 'unknown'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                source.count(invalid, 'count')


class RequestTests(unittest.TestCase):
    def test_success_uses_fixed_endpoint_and_one_request(self):
        with patch.object(source, 'urlopen') as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(json.dumps(response()).encode())
            source.request_page(AUTHOR, KEY, 0)
        request = opener.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://serpapi.com/search.json?'))
        self.assertIn('num=100', request.full_url)
        self.assertEqual(opener.call_args.kwargs['timeout'], 45)

    def test_api_errors_and_unfinished_results_fail_without_retry(self):
        for payload in ({'error': 'failed'}, {'search_metadata': {'status': 'Processing'}}, []):
            with self.subTest(payload=payload), patch.object(source, 'urlopen') as opener:
                opener.return_value.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
                with self.assertRaises((ValueError, RuntimeError)):
                    source.request_page(AUTHOR, KEY, 0)
                self.assertEqual(opener.call_count, 1)

    def test_invalid_json_network_failure_and_author_mismatch(self):
        with patch.object(source, 'urlopen') as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(b'not JSON')
            with self.assertRaisesRegex(RuntimeError, 'invalid JSON'):
                source.request_page(AUTHOR, KEY, 0)
        with patch.object(source, 'urlopen', side_effect=URLError('network timeout')):
            with self.assertRaisesRegex(RuntimeError, 'connection failed'):
                source.request_page(AUTHOR, KEY, 0)
        wrong = response()
        wrong['search_parameters']['author_id'] = 'different-author'
        with patch.object(source, 'urlopen') as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(json.dumps(wrong).encode())
            with self.assertRaisesRegex(ValueError, 'different author'):
                source.request_page(AUTHOR, KEY, 0)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.directory = tempfile.TemporaryDirectory(prefix='.scholar-test-', dir=self.root)
        self.assertEqual(Path(self.directory.name).resolve().parent, self.root)
        self.previous = Path.cwd()
        os.chdir(self.directory.name)
        Path('results').mkdir()
        self.old = {'gs_data.json': b'old snapshot', 'gs_data_shieldsio.json': b'old badge'}
        for name, contents in self.old.items():
            Path('results', name).write_bytes(contents)
        self.env = patch.dict(os.environ, {'GOOGLE_SCHOLAR_ID': AUTHOR, 'SERPAPI_API_KEY': KEY})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.previous)
        self.directory.cleanup()

    def assert_preserved(self):
        for name, contents in self.old.items():
            self.assertEqual(Path('results', name).read_bytes(), contents)

    def test_success_writes_existing_homepage_and_badge_formats(self):
        with patch.object(source, 'request_page', return_value=response()), self.assertLogs(level='INFO'):
            self.assertEqual(crawler.main(), 0)
        author = json.loads(Path('results/gs_data.json').read_text(encoding='utf-8'))
        badge = json.loads(Path('results/gs_data_shieldsio.json').read_text(encoding='utf-8'))
        self.assertEqual(author['publications'][AUTHOR + ':paper-1']['num_citations'], 0)
        self.assertEqual(badge['message'], '398')
        self.assertIn('updated', author)
        self.assertNotIn(KEY, json.dumps(author))

    def test_dry_run_and_missing_key_keep_previous_files(self):
        with patch.object(source, 'request_page', return_value=response()), self.assertLogs(level='INFO'):
            self.assertEqual(crawler.main(dry_run=True), 0)
        self.assert_preserved()
        with patch.dict(os.environ, {'SERPAPI_API_KEY': ''}), patch.object(crawler, 'fetch_author') as fetch, self.assertLogs(level='INFO') as logs:
            self.assertEqual(crawler.main(), 1)
        fetch.assert_not_called()
        self.assertIn('SERPAPI_API_KEY is missing', '\n'.join(logs.output))
        self.assert_preserved()

    def test_later_page_failure_keeps_previous_files(self):
        first = response()
        first['serpapi_pagination'] = {'next': 'https://serpapi.com/search.json?start=100'}
        with patch.object(source, 'request_page', side_effect=[first, RuntimeError('second page failed')]), self.assertLogs(level='INFO'):
            self.assertEqual(crawler.main(), 1)
        self.assert_preserved()

    def test_http_errors_do_not_expose_key_in_tracebacks(self):
        for code in (401, 403, 429, 503):
            error = HTTPError('https://serpapi.com/search.json?api_key=' + KEY, code, KEY, {}, None)
            with self.subTest(code=code), patch.object(source, 'urlopen', side_effect=error), self.assertLogs(level='INFO') as logs:
                self.assertEqual(crawler.main(), 1)
            text = '\n'.join(logs.output)
            self.assertIn(f'SerpApi HTTP {code}', text)
            self.assertNotIn(KEY, text)
            self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
