import hashlib
import json
import unittest
import time
from unittest.mock import patch

import httpx

from shopee_mcp.core import Credentials, FixtureProvider, LiveProvider, Profile, SafeError, Service, SignedClient, load_service, sign_payload, valid_url
from support import ROOT, contract, node, profile, profile_data


async def no_sleep(delay):
    pass


class CoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()

    def live(self, handler, p=None):
        p = p or profile()
        c = SignedClient(p, Credentials("synthetic-app", "synthetic-secret"),
                         transport=httpx.MockTransport(handler), clock=lambda:1700000000, sleep=no_sleep)
        self.clients.append(c)
        return Service(LiveProvider(p,c), "test-account", contract()), c

    async def test_fixture_pagination_and_no_links(self):
        service = load_service("fixture")
        first = await service.call("search_offers", {"keyword":"luminária", "limit":1})
        self.assertTrue(first["synthetic"])
        self.assertEqual(first["data"]["pagination"]["next_page"], 2)
        second = await service.call("search_offers", {"keyword":"luminária","limit":1,"page":2})
        self.assertFalse(second["data"]["pagination"]["has_next_page"])
        offer = await service.call("get_offer", {"item_id":"900001","shop_id":"800001"})
        self.assertEqual(offer["data"]["offer"]["source"], "synthetic_fixture")
        with self.assertRaises(SafeError) as e:
            await service.call("generate_affiliate_link", {"origin_url":"https://shopee.com.br/product/1/2", "sub_ids":["test"],"expected_account_reference":"synthetic-account"})
        self.assertEqual(e.exception.code, "FIXTURE_NO_LINK")

    async def test_fixture_status_does_not_claim_auth(self):
        status = await load_service("fixture").call("affiliate_status", {})
        self.assertFalse(status["data"]["api_authenticated_in_this_call"])
        self.assertTrue(status["data"]["live_acceptance_required"])

    async def test_invalid_inputs(self):
        service = load_service("fixture")
        for args in [{"keyword":""}, {"keyword":"a","page":0},{"keyword":"a","limit":51},{"keyword":"a","page":True},{"keyword":"a","endpoint":"https://evil.invalid"}]:
            with self.subTest(args=args), self.assertRaises(SafeError):
                await service.call("search_offers",args)
        with self.assertRaises(SafeError):
            await service.call("get_offer", {"item_id":12,"shop_id":"1"})

    async def test_pending_profile_blocks_before_credentials(self):
        pending = json.loads((ROOT/'examples/profile.pending.json').read_text())
        with self.assertRaises(SafeError) as e:
            Profile(pending).require_verified()
        self.assertEqual(e.exception.code,"SCHEMA_UNVERIFIED")
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(SafeError) as e:
            load_service("live")
        self.assertEqual(e.exception.code, "SCHEMA_UNVERIFIED")

    async def test_endpoint_pinning(self):
        for endpoint in ['https://evil.invalid/path','http://open-api.affiliate.shopee.com.br/path','https://open-api.affiliate.shopee.com.br.evil.invalid/path','https://user:pass@open-api.affiliate.shopee.com.br/path','https://open-api.affiliate.shopee.com.br/path?secret=x','https://open-api.affiliate.shopee.com.br:123/path']:
            p=profile_data();p['endpoint']=endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(SafeError):
                Profile(p)

    async def test_url_restrictions(self):
        for url in ['https://evil.invalid/item','https://shopee.com.br@evil.invalid/a','https://shopee.com.br/#x','https://shopee.com.br:bad/x','https://shopee.com.br/\nfoo']:
            with self.subTest(url=url), self.assertRaises(SafeError):
                valid_url(url, {'shopee.com.br'})

    async def test_signature_exact_transmitted_utf8_and_int64(self):
        def handler(request):
            b=request.content
            body=json.loads(b)
            self.assertEqual(body['variables']['keyword'],'café "teste"')
            expected=hashlib.sha256(b'synthetic-app1700000000'+b+b'synthetic-secret').hexdigest()
            self.assertEqual(request.headers['Authorization'],f'SHA256 Credential=synthetic-app, Timestamp=1700000000, Signature={expected}')
            return httpx.Response(200,json={'data':{'syntheticSearch':{'nodes':[node()],'pageInfo':{'page':1,'limit':1,'hasNext':False,'cursor':None}}}})
        service,_=self.live(handler)
        result=await service.call('search_offers',{'keyword':'café "teste"','limit':1})
        offer=result['data']['offers'][0]
        self.assertEqual(offer['item_id'],'9007199254740993')
        self.assertEqual(offer['commission_rate_fraction'],'0.12')
        self.assertEqual(offer['commission_status'],'estimated')

    async def test_ids_integer_encoding_exact(self):
        p=profile_data(); p['operations']['get']['variables']['item_id']['encoding']='integer'
        def handler(request):
            self.assertEqual(json.loads(request.content)['variables']['item_id'],9007199254740993)
            return httpx.Response(200,json={'data':{'syntheticGet':node()}})
        service,_=self.live(handler,Profile(p))
        await service.call('get_offer',{'item_id':'9007199254740993','shop_id':'800001'})

    async def test_safe_read_retry(self):
        count=0
        def handler(request):
            nonlocal count
            count+=1
            if count<3: return httpx.Response(503,headers={'Retry-After':'10000'})
            return httpx.Response(200,json={'data':{'syntheticGet':node()}})
        service,_=self.live(handler)
        await service.call('get_offer',{'item_id':'9007199254740993','shop_id':'800001'})
        self.assertEqual(count,3)

    async def test_auth_and_graphql_errors_never_retried_or_echoed(self):
        for status,body,code in [(401,{'secret':'synthetic-secret'},'UPSTREAM_AUTH'),(200,{'data':{'syntheticGet':node()},'errors':[{'message':'synthetic-secret'}]},'UPSTREAM_GRAPHQL'),(200,['unexpected'],'UPSTREAM_SHAPE'),(302,{},'UPSTREAM_HTTP')]:
            count=0
            def handler(request):
                nonlocal count
                count+=1
                return httpx.Response(status,json=body,headers={'Location':'https://evil.invalid'})
            service,_=self.live(handler)
            with self.subTest(status=status,code=code), self.assertRaises(SafeError) as e:
                await service.call('get_offer',{'item_id':'9007199254740993','shop_id':'800001'})
            self.assertEqual(e.exception.code,code)
            self.assertNotIn('synthetic-secret',str(e.exception))
            self.assertEqual(count,1)

    async def test_documented_error_categories_no_retry(self):
        for upstream,expected in [(10000,'UPSTREAM_SYSTEM'),('10010','UPSTREAM_SCHEMA'),(10020,'UPSTREAM_AUTH'),(10030,'UPSTREAM_RATE_LIMIT'),(10031,'UPSTREAM_ACCESS_DENIED'),(10032,'UPSTREAM_AFFILIATE_ID'),(10033,'UPSTREAM_ACCOUNT_FROZEN'),(10034,'UPSTREAM_ACCOUNT_BLOCKED'),(10035,'UPSTREAM_NO_API_ACCESS'),(11000,'UPSTREAM_BUSINESS'),(11001,'UPSTREAM_PARAMETER'),(11002,'UPSTREAM_BOUND_ACCOUNT')]:
            count=0
            def handler(request):
                nonlocal count
                count+=1
                return httpx.Response(200,json={'errors':[{'message':'synthetic-secret','extensions':{'code':upstream}}]})
            service,_=self.live(handler)
            with self.subTest(upstream=upstream),self.assertRaises(SafeError) as e:
                await service.call('get_offer',{'item_id':'1','shop_id':'2'})
            self.assertEqual(e.exception.code,expected)
            self.assertEqual(count,1)
            self.assertNotIn('synthetic-secret',str(e.exception))

    async def test_hourly_local_budget_blocks_before_network(self):
        service,client=self.live(lambda request:self.fail('quota should block'))
        client.call_starts.extend([time.monotonic()]*8000)
        with self.assertRaises(SafeError) as e:
            await service.call('get_offer',{'item_id':'1','shop_id':'2'})
        self.assertEqual(e.exception.code,'LOCAL_RATE_LIMIT')

    async def test_operation_name_in_exact_signed_body(self):
        p=profile_data();p['operations']['get']['operation_name']='SyntheticGet'
        def handler(request):
            self.assertEqual(json.loads(request.content)['operationName'],'SyntheticGet')
            self.assertEqual(request.headers['Authorization'],sign_payload(Credentials('synthetic-app','synthetic-secret'),request.content,1700000000))
            return httpx.Response(200,json={'data':{'syntheticGet':node()}})
        service,_=self.live(handler,Profile(p))
        await service.call('get_offer',{'item_id':'9007199254740993','shop_id':'800001'})

    async def test_mutation_timeout_never_retried(self):
        count=0
        def handler(request):
            nonlocal count
            count+=1
            raise httpx.ReadTimeout('synthetic-secret',request=request)
        service,_=self.live(handler)
        with self.assertRaises(SafeError) as e:
            await service.call('generate_affiliate_link',{'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['canal','campanha','criativo'],'expected_account_reference':'test-account'})
        self.assertEqual(e.exception.code,'LINK_OUTCOME_UNKNOWN')
        self.assertEqual(count,1)

    async def test_mutation_server_error_has_unknown_outcome(self):
        count=0
        def handler(request):
            nonlocal count
            count+=1
            return httpx.Response(503)
        service,_=self.live(handler)
        with self.assertRaises(SafeError) as e:
            await service.call('generate_affiliate_link',{'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['test'],'expected_account_reference':'test-account'})
        self.assertEqual(e.exception.code,'LINK_OUTCOME_UNKNOWN')
        self.assertEqual(count,1)

    async def test_mutation_preserves_subids_and_api_link(self):
        def handler(request):
            variables=json.loads(request.content)['variables']
            self.assertEqual(variables['sub_ids'],['telegram','outubro','criativo_b'])
            return httpx.Response(200,json={'data':{'syntheticLink':{'link':'https://affiliate.example.invalid/returned-verbatim'}}})
        service,_=self.live(handler)
        result=await service.call('generate_affiliate_link',{'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['telegram','outubro','criativo_b'],'expected_account_reference':'test-account'})
        self.assertEqual(result['data']['affiliate_url'],'https://affiliate.example.invalid/returned-verbatim')
        self.assertEqual(result['data']['attribution_evidence'],'credential_context_only')

    async def test_account_subid_and_host_rejections_before_request(self):
        def forbidden(request):
            self.fail('A request should not occur')
        service,_=self.live(forbidden)
        base={'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['test'],'expected_account_reference':'test-account'}
        for override in [{'expected_account_reference':'other'},{'sub_ids':[]},{'sub_ids':['email@example.com']},{'origin_url':'https://evil.invalid'}]:
            with self.subTest(override=override), self.assertRaises(SafeError):
                await service.call('generate_affiliate_link',base|override)
        p=profile_data();p['sub_ids']['official_count_verified']=False
        service,_=self.live(forbidden,Profile(p))
        with self.assertRaises(SafeError) as e:
            await service.call('generate_affiliate_link',base)
        self.assertEqual(e.exception.code,'SUBIDS_UNVERIFIED')

    async def test_missing_operation_does_not_fallback(self):
        p=profile_data();p['operations'].pop('get')
        service,_=self.live(lambda request:self.fail('no call'),Profile(p))
        with self.assertRaises(SafeError) as e:
            await service.call('get_offer',{'item_id':'1','shop_id':'2'})
        self.assertEqual(e.exception.code,'OPERATION_UNAVAILABLE')

    async def test_unknown_rate_unit_does_not_invent_percent(self):
        p=profile_data();p['commission_rate_unit']='unknown'
        service,_=self.live(lambda request:httpx.Response(200,json={'data':{'syntheticGet':node()}}),Profile(p))
        result=await service.call('get_offer',{'item_id':'9007199254740993','shop_id':'800001'})
        self.assertIsNone(result['data']['offer']['commission_rate_fraction'])

    async def test_shape_wrong_product_and_oversize_rejected(self):
        for response,code in [(httpx.Response(200,json={'data':{'syntheticGet':node()}}),'UPSTREAM_SHAPE'),(httpx.Response(200,content=b'x'*(2*1024*1024+1)),'UPSTREAM_SIZE')]:
            service,_=self.live(lambda request:response)
            with self.subTest(code=code), self.assertRaises(SafeError) as e:
                await service.call('get_offer',{'item_id':'111','shop_id':'800001'})
            self.assertEqual(e.exception.code,code)


class PureTests(unittest.TestCase):
    def test_signer_fixed_vector(self):
        expected=hashlib.sha256(b'example-app123{"query":"x"}example-test-secret').hexdigest()
        header=sign_payload(Credentials('example-app','example-test-secret'),b'{"query":"x"}',123)
        self.assertTrue(header.endswith(expected))
        self.assertNotIn('example-test-secret',header)

    def test_secret_repr_omitted(self):
        self.assertNotIn('do-not-leak',repr(Credentials('app','do-not-leak')))
