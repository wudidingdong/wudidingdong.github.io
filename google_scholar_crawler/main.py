import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from serpapi_source import fetch_author


logger = logging.getLogger(__name__)


def main(dry_run=False):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    started = monotonic()
    stage = 'configuration'

    try:
        scholar_id = os.environ.get('GOOGLE_SCHOLAR_ID', '').strip()
        if not scholar_id:
            raise ValueError('GOOGLE_SCHOLAR_ID is missing or empty')
        api_key = os.environ.get('SERPAPI_API_KEY', '').strip()
        if not api_key:
            raise ValueError('SERPAPI_API_KEY is missing; add it to repository Actions secrets')

        stage = 'serpapi'
        logger.info('stage=%s: requesting author metrics and publications', stage)
        author = fetch_author(scholar_id, api_key)
        logger.info('stage=%s: completed after %.1f seconds', stage, monotonic() - started)

        stage = 'validation'
        for field in ('citedby', 'hindex'):
            if type(author.get(field)) is not int or author[field] < 0:
                raise ValueError(f'Missing or invalid {field}; refusing to publish incomplete data')
        if not isinstance(author.get('cites_per_year'), dict):
            raise ValueError('Missing yearly citation counts; refusing to publish incomplete data')
        if not isinstance(author.get('publications'), list) or not author['publications']:
            raise ValueError('Missing publications; refusing to replace the existing snapshot')

        author['publications'] = {paper['author_pub_id']: paper for paper in author['publications']}
        author['updated'] = str(datetime.now(timezone.utc).replace(tzinfo=None))
        shields_data = {
            'schemaVersion': 1,
            'label': 'citations',
            'message': str(author['citedby']),
        }
        # Serialize everything before writing any results. Only a successful run is published.
        payloads = {
            'gs_data.json': json.dumps(author, ensure_ascii=False),
            'gs_data_shieldsio.json': json.dumps(shields_data, ensure_ascii=False),
        }

        if dry_run:
            logger.info(
                'Dry run passed: citations=%s, h-index=%s, publications=%s, zero-citation publications=%s; no files written',
                author['citedby'], author['hindex'], len(author['publications']),
                sum(paper.get('num_citations') == 0 for paper in author['publications'].values()),
            )
            return 0

        stage = 'write'
        results = Path('results')
        results.mkdir(exist_ok=True)
        for filename, content in payloads.items():
            (results / (filename + '.tmp')).write_text(content, encoding='utf-8')
        for filename in payloads:
            (results / (filename + '.tmp')).replace(results / filename)
        logger.info(
            'Citation snapshot ready after %.1f seconds: citations=%s, h-index=%s, publications=%s',
            monotonic() - started, author['citedby'], author['hindex'], len(author['publications']),
        )
        return 0
    except Exception:
        logger.exception('Citation update failed at stage=%s after %.1f seconds', stage, monotonic() - started)
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Update Google Scholar statistics via SerpApi')
    parser.add_argument('--dry-run', action='store_true', help='Fetch and validate without writing results')
    raise SystemExit(main(dry_run=parser.parse_args().dry_run))
