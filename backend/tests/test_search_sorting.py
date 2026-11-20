import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.imports import router
from app.auth.dependencies import require_user
from app.sources.access import SearchCache
from app.sources.arxiv import API_URL, ArxivClient, ArxivError, ArxivPage, ProviderReply
from app.sources.arxiv_transport import validate_request


class SearchSortingTests(unittest.TestCase):
    def test_page_sizes_through_client_transport_parser_and_cache(self):
        cache = SearchCache()
        for size in [10, 25, 50]:
            with self.subTest(size=size):
                entries = ''.join(f'<entry><id>https://arxiv.org/abs/2601.{index + 1:05d}v1</id><title>Research paper</title><summary>Evidence.</summary><author><name>Researcher</name></author><category term="cs.AI"/><published>2026-01-01T00:00:00Z</published><updated>2026-01-01T00:00:00Z</updated></entry>' for index in range(size))
                body = f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/"><o:totalResults>1500</o:totalResults><o:startIndex>1000</o:startIndex><o:itemsPerPage>{size}</o:itemsPerPage>{entries}</feed>'.encode()
                transport = Mock()
                transport.request.return_value = ProviderReply(200, {}, body)
                page = ArxivClient(transport).search('rust', limit=size, offset=1000)
                self.assertEqual(len(page.items), size)
                self.assertEqual(page.limit, size)
                validate_request(API_URL, transport.request.call_args.kwargs['params'], None)
                cache.put('rust', size, 1000, page)
                self.assertEqual(cache.get('rust', size, 1000), page)
        for limit in [0, 51, True]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                ArxivClient(Mock()).search('rust', limit=limit)
        with self.assertRaises(ArxivError):
            validate_request(API_URL, {'search_query': 'rust', 'start': 0, 'max_results': 51, 'sortBy': 'relevance', 'sortOrder': 'descending'}, None)

    def test_upstream_sort_and_transport_allowlist(self):
        body = b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/"><o:totalResults>0</o:totalResults><o:startIndex>0</o:startIndex><o:itemsPerPage>10</o:itemsPerPage></feed>'
        transport = Mock()
        transport.request.return_value = ProviderReply(200, {}, body)
        for sort_by in ['relevance', 'submittedDate', 'lastUpdatedDate']:
            for sort_order in ['ascending', 'descending']:
                with self.subTest(sort_by=sort_by, sort_order=sort_order):
                    ArxivClient(transport).search('rust agents', sort_by=sort_by, sort_order=sort_order)
                    params = transport.request.call_args.kwargs['params']
                    self.assertEqual(params['sortBy'], sort_by)
                    self.assertEqual(params['sortOrder'], sort_order)
                    validate_request(API_URL, params, None)
        for key, value in [('sortBy', 'title'), ('sortOrder', 'random')]:
            invalid_params = {**params, key: value}
            with self.assertRaises(ArxivError):
                validate_request(API_URL, invalid_params, None)
        for options in [{'sort_by': 'title'}, {'sort_order': 'random'}]:
            with self.assertRaises(ValueError):
                ArxivClient(transport).search('rust', **options)

    def test_cached_metadata_is_exact_version_unexpired_and_copied(self):
        from datetime import datetime, timezone
        from app.sources.arxiv import ArxivPaper
        now = [0.0]
        cache = SearchCache(clock=lambda: now[0])
        paper = ArxivPaper(external_id='1706.03762v1', title='Fixture', authors=['Author'], abstract='',
                           categories=['cs.AI'], published_at=datetime.now(timezone.utc), source_updated_at=datetime.now(timezone.utc))
        cache.put('fixture', 10, 0, ArxivPage([paper], 1, 0, 10))
        self.assertIsNone(cache.find_paper('1706.03762v2'))
        found = cache.find_paper('1706.03762v1')
        found.authors.append('Changed')
        self.assertEqual(cache.find_paper('1706.03762v1').authors, ['Author'])
        now[0] = 601
        self.assertIsNone(cache.find_paper('1706.03762v1'))

    def test_cache_separates_sort_and_direction(self):
        cache = SearchCache()
        page = ArxivPage([], 30, 0, 10)
        cache.put('rust agents', 10, 0, page)
        self.assertEqual(cache.get(' rust   agents ', 10, 0), page)
        self.assertIsNone(cache.get('rust agents', 10, 0, sort_by='submittedDate'))
        cache.put('rust agents', 10, 0, page, sort_by='submittedDate', sort_order='ascending')
        self.assertEqual(cache.get('rust agents', 10, 0, sort_by='submittedDate', sort_order='ascending'), page)
        self.assertIsNone(cache.get('rust agents', 10, 0, sort_by='submittedDate', sort_order='descending'))

    def test_api_sorting_defaults_cache_and_invalid_parameters(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=uuid4())
        app.state.settings = SimpleNamespace(arxiv_configured=True)
        app.state.arxiv_cache = SearchCache()
        app.state.arxiv_client = Mock()
        app.state.arxiv_client.search.return_value = ArxivPage([], 30, 0, 10)
        app.state.sessions = MagicMock()
        with TestClient(app) as client:
            for _ in range(2):
                self.assertEqual(client.get('/api/v1/paper-search', params={'q': 'rust'}).status_code, 200)
            self.assertEqual(app.state.arxiv_client.search.call_count, 1)
            app.state.arxiv_client.search.assert_called_with('rust', limit=10, offset=0, sort_by='relevance', sort_order='descending')
            for _ in range(2):
                response = client.get('/api/v1/paper-search', params={'q': 'rust', 'sort_by': 'submittedDate', 'sort_order': 'ascending'})
                self.assertEqual(response.status_code, 200)
            self.assertEqual(app.state.arxiv_client.search.call_count, 2)
            app.state.arxiv_client.search.assert_called_with('rust', limit=10, offset=0, sort_by='submittedDate', sort_order='ascending')
            for size in [10, 25, 50]:
                response = client.get('/api/v1/paper-search', params={'q': 'page-size-fixture', 'limit': size})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['limit'], size)
                app.state.arxiv_client.search.assert_called_with('page-size-fixture', limit=size, offset=0, sort_by='relevance', sort_order='descending')
            self.assertEqual(client.get('/api/v1/paper-search', params={'q': 'rust', 'limit': 51}).status_code, 422)
            for options in [{'sort_by': 'title'}, {'sort_order': 'random'}, {'offset': 1010}]:
                self.assertEqual(client.get('/api/v1/paper-search', params={'q': 'rust', **options}).status_code, 422)
            self.assertEqual(app.state.arxiv_client.search.call_count, 5)


if __name__ == '__main__':
    unittest.main()
