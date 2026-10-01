"""Document-grounded operation shapes, exercised only with synthetic API responses."""
import json
import unittest
from unittest.mock import patch

import httpx

from shopee_mcp.core import Credentials, LiveProvider, Profile, SafeError, Service, SignedClient, load_service, render_query, sign_payload
from support import ROOT, contract, node


async def no_sleep(delay):
    pass


def official_profile():
    return Profile(json.loads((ROOT/'examples/profile.official.json').read_text()))


def official_node():
    p=official_profile()
    synthetic=node()
    return {path:synthetic.get(key) for key,path in p.data['operations']['get']['fields'].items()}


def strip_string_literals(query):
    """Independent JSON string decoder removes values while retaining executable tokens."""
    result=[];i=0;decoder=json.JSONDecoder()
    while i<len(query):
        if query[i]=='"':
            _,end=decoder.raw_decode(query[i:])
            result.append('VALUE');i+=end
        else:
            result.append(query[i]);i+=1
    return ''.join(result)


class OfficialProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clients=[]

    async def asyncTearDown(self):
        for c in self.clients:await c.close()

    def service(self,handler):
        p=official_profile()
        client=SignedClient(p,Credentials('synthetic-app','synthetic-secret'),transport=httpx.MockTransport(handler),clock=lambda:1700000000,sleep=no_sleep)
        self.clients.append(client)
        return Service(LiveProvider(p,client),'test-account',contract())

    async def test_documented_product_query_no_scroll_or_scalar_guess(self):
        def handler(request):
            self.assertEqual(str(request.url),'https://open-api.affiliate.shopee.com.br/graphql')
            body=json.loads(request.content);query=body['query']
            self.assertIn('productOfferV2(keyword:"fone",page:1,limit:2,sortType:2,',query)
            self.assertNotIn('scrollId',query)
            self.assertNotIn('$',query)
            self.assertNotIn('price ',query)
            self.assertEqual(body['operationName'],'SearchOffers')
            self.assertEqual(request.headers['Authorization'],sign_payload(Credentials('synthetic-app','synthetic-secret'),request.content,1700000000))
            return httpx.Response(200,json={'data':{'productOfferV2':{'nodes':[official_node()],'pageInfo':{'page':1,'limit':2,'hasNextPage':True}}}})
        response=await self.service(handler).call('search_offers',{'keyword':'fone','limit':2,'sort_type':2})
        self.assertEqual(response['data']['pagination']['next_page'],2)
        self.assertIsNone(response['data']['pagination']['next_cursor'])
        self.assertEqual(response['data']['offers'][0]['currency_evidence'],'market_region_inference')

    async def test_lookup_uses_same_documented_query_exact_int64_literal(self):
        def handler(request):
            query=json.loads(request.content)['query']
            self.assertIn('productOfferV2(itemId:9007199254740993,shopId:800001)',query)
            self.assertNotIn('Int64',query)
            return httpx.Response(200,json={'data':{'productOfferV2':{'nodes':[official_node()]}}})
        response=await self.service(handler).call('get_offer',{'item_id':'9007199254740993','shop_id':'800001'})
        self.assertEqual(response['data']['offer']['item_id'],'9007199254740993')

    async def test_link_input_shape_and_verbatim_mock_response(self):
        def handler(request):
            query=json.loads(request.content)['query']
            self.assertIn('generateShortLink(input:{originUrl:"https://shopee.com.br/product/1/2",subIds:["telegram","outubro","criativo"]})',query)
            self.assertNotIn('$',query)
            return httpx.Response(200,json={'data':{'generateShortLink':{'shortLink':'https://shope.ee/synthetic-test-only'}}})
        response=await self.service(handler).call('generate_affiliate_link',{'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['telegram','outubro','criativo'],'expected_account_reference':'test-account'})
        self.assertEqual(response['data']['affiliate_url'],'https://shope.ee/synthetic-test-only')

    async def test_cursor_rejected_for_official_product_query(self):
        service=self.service(lambda request:self.fail('cursor must not make API call'))
        with self.assertRaises(SafeError):
            await service.call('search_offers',{'keyword':'fone','cursor':'unsupported'})

    async def test_unknown_shortlink_host_rejected(self):
        service=self.service(lambda request:httpx.Response(200,json={'data':{'generateShortLink':{'shortLink':'https://evil.invalid/link'}}}))
        with self.assertRaises(SafeError):
            await service.call('generate_affiliate_link',{'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['test'],'expected_account_reference':'test-account'})


class GraphQLLiteralTests(unittest.TestCase):
    def test_documented_profile_does_not_bypass_missing_credentials(self):
        with patch.dict('os.environ', {'SHOPEE_VERIFIED_PROFILE':str(ROOT/'examples/profile.official.json')}, clear=True),self.assertRaises(SafeError) as e:
            load_service('live')
        self.assertEqual(e.exception.code,'CREDENTIALS_MISSING')

    def test_injection_and_placeholder_strings_remain_inside_literals(self):
        op=official_profile().operation('link')
        attacks=['x"}){evil}#','line\nnext\r\t\\end','{{sub_ids}}','café 😃', '"\\u0022']
        for value in attacks:
            with self.subTest(value=value):
                query=render_query(op,{'origin_url':value,'sub_ids':[value,'{{origin_url}}']})
                executable=strip_string_literals(query)
                self.assertEqual(executable,'mutation GenerateAffiliateLink { generateShortLink(input:{originUrl:VALUE,subIds:[VALUE,VALUE]}) { shortLink } }')

    def test_integer_literal_bounds_and_no_string_quoting(self):
        op=official_profile().operation('get')
        query=render_query(op,{'item_id':'9007199254740993','shop_id':'1'})
        self.assertIn('itemId:9007199254740993',query)
        for item in ['9223372036854775808','1){evil}','-1',True]:
            with self.subTest(item=item),self.assertRaises(SafeError):
                render_query(op,{'item_id':item,'shop_id':'1'})
