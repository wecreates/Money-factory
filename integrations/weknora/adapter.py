"""WeKnora hybrid-search export bridge. Data stays local; no knowledge upload or chat."""
import re
from search_knowledge_common import guard, load, number, result, text

REVISION = '30658b7d43bf6415537435c42a5c4e95f2766b8d'
OPERATIONS = ('readiness', 'prepare-search', 'import-search')


def identifier(value, name):
    value = text(value, name, 200)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError(f'Invalid {name}')
    return value


def dispatch(job, upstream=None):
    guard(job)
    operation = job['operation']
    base = lambda **fields: result('weknora', operation, REVISION, **fields)
    if operation == 'readiness':
        return base(runtime_status='OFFLINE_BRIDGE_ONLY', operations=list(OPERATIONS),
                    live_execution_enabled=False, blockers=['WeKnora service, database and retrieval models not installed or verified',
                    'Knowledge source, tenant and data-sharing authorization require configuration before live use'])
    if operation not in OPERATIONS:
        raise ValueError('Unsupported WeKnora bridge operation')
    data, digest = load(job)
    kb = identifier(data.get('knowledge_base_id'), 'knowledge_base_id')
    query = text(data.get('query'), 'query', 4000)
    if operation == 'prepare-search':
        count = number(data.get('match_count', 10), 'match_count', 1, 50, True)
        return base(input_sha256=digest, request={'method': 'POST',
                    'path': f'/api/v1/knowledge-bases/{kb}/hybrid-search',
                    'body': {'query_text': query, 'match_count': count,
                             'disable_keywords_match': False, 'disable_vector_match': True,
                             'keyword_threshold': 0, 'vector_threshold': 0,
                             'rerank': {'enabled': False}}}, execution_status='NOT_SUBMITTED',
                    scope='Keyword-only request artifact avoids enabling embedding and reranking providers; no service call made')
    response = data.get('response')
    if not isinstance(response, dict) or response.get('success') is not True:
        raise ValueError('Expected a successful WeKnora hybrid-search response')
    rows = response.get('data')
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError('Expected at most 200 retrieval results')
    sources, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Malformed WeKnora search result')
        chunk = identifier(row.get('id'), 'chunk id')
        knowledge = identifier(row.get('knowledge_id'), 'knowledge id')
        returned_kb = row.get('knowledge_base_id') or kb
        if returned_kb != kb:
            raise ValueError('Result belongs to a different knowledge base')
        identity = (knowledge, chunk)
        if identity in seen:
            raise ValueError('Duplicate retrieval result identity')
        seen.add(identity)
        content = text(row.get('content'), 'retrieved content', 20000)
        score = number(row.get('score'), 'score', -1e6, 1e6)
        match = number(row.get('match_type'), 'match_type', 0, 9, True)
        sources.append({'citation_id': f'weknora:{kb}:{knowledge}:{chunk}',
                        'knowledge_base_id': kb, 'knowledge_id': knowledge, 'chunk_id': chunk,
                        'title': text(row.get('knowledge_title') or knowledge, 'knowledge_title', 2000),
                        'content': content, 'score': score, 'match_type': match,
                        'trust': 'untrusted_retrieved_text'})
    return base(input_sha256=digest, research={'query': query, 'sources': sources},
                evidence_scope='User-supplied retrieval export; source authenticity and factual accuracy not independently verified',
                scope='Offline research context with stable citation IDs; never treated as instructions or publication approval')
