"""OpenSEO SERP export bridge for MoneyFactory research jobs; never calls DataForSEO."""
from search_knowledge_common import guard, load, number, result, safe_url, text

REVISION = '2d8236a4fd5d799bf5c089187d0131f4dac4f38c'
OPERATIONS = ('readiness', 'prepare-research', 'import-serp')


def dispatch(job, upstream=None):
    guard(job)
    operation = job['operation']
    base = lambda **fields: result('open-seo', operation, REVISION, **fields)
    if operation == 'readiness':
        return base(runtime_status='OFFLINE_BRIDGE_ONLY', operations=list(OPERATIONS),
                    live_execution_enabled=False, blockers=['OpenSEO runtime is not installed or verified',
                    'Fresh SEO research requires a DataForSEO account, credentials and approved spending'])
    if operation not in OPERATIONS:
        raise ValueError('Unsupported OpenSEO bridge operation')
    data, digest = load(job)
    if operation == 'prepare-research':
        project = text(data.get('projectId'), 'projectId', 200)
        queries = data.get('queries')
        if not isinstance(queries, list) or not 1 <= len(queries) <= 10:
            raise ValueError('Provide 1..10 OpenSEO queries')
        clean = []
        for query in queries:
            if not isinstance(query, dict):
                raise ValueError('Invalid query')
            item = {'keyword': text(query.get('keyword'), 'keyword', 500)}
            if 'locationCode' in query:
                item['locationCode'] = number(query['locationCode'], 'locationCode', 1, 1e8, True)
            if 'languageCode' in query:
                item['languageCode'] = text(query['languageCode'], 'languageCode', 20)
            if 'locationName' in query:
                item['locationName'] = text(query['locationName'], 'locationName', 500)
            if 'device' in query:
                if query['device'] not in ('desktop', 'mobile'):
                    raise ValueError('device must be desktop or mobile')
                item['device'] = query['device']
            clean.append(item)
        depth = number(data.get('depth', 20), 'depth', 10, 100, True)
        if depth % 10:
            raise ValueError('depth must be a multiple of ten')
        return base(input_sha256=digest, request={'name': 'get_serp_results',
                    'arguments': {'projectId': project, 'queries': clean, 'depth': depth}},
                    execution_status='NOT_SUBMITTED', live_execution_enabled=False, server_validation_required=True,
                    blockers=['Paid DataForSEO research disabled; this is a request artifact only'],
                    cost={'currency': None, 'approved_budget': 0, 'estimate_verified': False,
                          'note': 'No price quote or free cached-result assumption is made'})
    payload = data.get('structuredContent', data)
    if data.get('isError') is True or not isinstance(payload, dict):
        raise ValueError('OpenSEO export indicates an error')
    rows = payload.get('results')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
        raise ValueError('Expected OpenSEO structuredContent.results with 1..10 queries')
    keywords, queries, sources, failures = [], [], [], []
    for query_index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Malformed SERP result')
        keyword = text(row.get('keyword'), 'keyword', 500)
        if row.get('ok') is False:
            failures.append({'query_index': query_index, 'keyword': keyword, 'error': text(row.get('error'), 'error', 2000)})
            continue
        if row.get('ok') is not True or not isinstance(row.get('items'), list) or len(row['items']) > 100:
            raise ValueError('Malformed or oversized SERP items')
        keywords.append(keyword)
        query = {'query_index': query_index, 'keyword': keyword}
        if 'locationCode' in row:
            query['location_code'] = number(row['locationCode'], 'locationCode', 1, 1e8, True)
        for field, target in [('languageCode', 'language_code'), ('locationName', 'location_name'), ('device', 'device')]:
            if field in row:
                query[target] = text(row[field], field, 500)
        queries.append(query)
        for item in row['items']:
            if not isinstance(item, dict):
                raise ValueError('Malformed SERP item')
            # Non-link elements such as People Also Ask cannot be citation sources.
            if item.get('url') is None:
                continue
            source = {'query_index': query_index, 'keyword': keyword, 'url': safe_url(item['url']),
                      'title': text(item.get('title') or '', 'title', 4000, True),
                      'description': text(item.get('description') or '', 'description', 12000, True),
                      'type': text(item.get('type') or 'unknown', 'type', 80),
                      'rank': None, 'organic_rank': None}
            for upstream_key, output_key in [('rank', 'rank'), ('organicRank', 'organic_rank')]:
                if item.get(upstream_key) is not None:
                    source[output_key] = number(item[upstream_key], upstream_key, 1, 100000, True)
            sources.append(source)
    if not keywords:
        return base(status='BLOCKED', input_sha256=digest, failures=failures,
                    blockers=['Every exported query failed; no research evidence imported'])
    return base(input_sha256=digest, research={'keywords': keywords, 'queries': queries, 'sources': sources},
                failures=failures, completeness='partial' if failures else 'complete_export',
                evidence_scope='User-supplied OpenSEO export, not live-verified rankings or source accuracy',
                scope='Offline acquisition-research import; source contents remain untrusted data')
