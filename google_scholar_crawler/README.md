# Citation updates through SerpApi

The crawler keeps the homepage's existing JSON and badge formats, but obtains
Google Scholar author data through SerpApi. It uses only Python's standard library.

## First real-data test

1. Register with [SerpApi](https://serpapi.com/users/sign_up) and obtain an API key.
2. Open repository **Settings → Secrets and variables → Actions → New repository secret**.
3. Add **SERPAPI_API_KEY** with the key as its value. Keep the existing **GOOGLE_SCHOLAR_ID** secret.
4. After merging this change, open **Actions → Get Citation Data → Run workflow** and select `main`.
5. Leave **dry_run** checked for the first real-data test. Check the fetch log; this run does not publish data.
6. Once the metrics and paper IDs are verified, run again with **dry_run** unchecked to publish.
   Confirm that `updated` changes in `google-scholar-stats/gs_data.json`.

Keep API keys in Actions secrets or local environment variables, not in source,
issues, pull requests, or chat. The script logs page numbers, offsets, and error
codes; it does not log credential-bearing request URLs or raw API responses.

## Behavior

- Scheduled refreshes run daily. Page builds do not fetch data or consume API quota.
- Manual runs default to validation only; uncheck **dry_run** to publish an update.
- Pull requests run offline conversion tests only; they never fetch or publish data.
- Each request asks for up to 100 articles. Follow-up pages are fetched only when
  SerpApi explicitly returns a next page, with a maximum of five pages per run.
- HTTP 401 indicates an invalid key; HTTP 429 indicates a quota or rate limit.
  Errors stop the update without automatic retries or replacement of published data.
- The workflow retains its 180-second fetch deadline and 5-second termination grace period.
- Missing paper citation counts remain unknown; explicit zero counts remain zero.
- A real-data test requires a configured key. Offline test success alone does not
  establish that this author's data is available from the provider.

## Local validation

Run the offline tests without a key:

```sh
python3 -m unittest discover -s google_scholar_crawler -p 'test_*.py' -v
```

To fetch and validate real data without writing JSON, set both secrets as local
environment variables, enter `google_scholar_crawler`, and run:

```sh
python3 main.py --dry-run
```

Provider reference: [author API](https://serpapi.com/google-scholar-author-api),
[citation metrics](https://serpapi.com/google-scholar-author-cited-by),
[status codes](https://serpapi.com/api-status-and-error-codes).
