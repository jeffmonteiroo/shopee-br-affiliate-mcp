import json
import os
import sys
import unittest

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from jsonschema import Draft202012Validator

from shopee_mcp.core import load_service, SafeError
from shopee_mcp.server import build_private_http
from support import ROOT, contract

TEST_TOKEN = 'synthetic-local-test-token-0000000000000000'


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_handshake_discovery_calls_and_errors(self):
        # No persistent environment/configuration and no Shopee credentials.
        params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'run.py'),'--mode','fixture'],env={'PATH':os.environ.get('PATH','')})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                init=await session.initialize()
                self.assertEqual(init.serverInfo.name,'shopee-affiliate-mcp')
                listing=await session.list_tools()
                self.assertEqual({t.name for t in listing.tools},set(contract()))
                for t in listing.tools:
                    Draft202012Validator.check_schema(t.inputSchema)
                    Draft202012Validator.check_schema(t.outputSchema)
                status=await session.call_tool('affiliate_status',{})
                self.assertFalse(status.isError)
                self.assertTrue(status.structuredContent['synthetic'])
                search=await session.call_tool('search_offers',{'keyword':'Luminária','limit':1})
                self.assertEqual(len(search.structuredContent['data']['offers']),1)
                bad=await session.call_tool('search_offers',{'keyword':'x','limit':100})
                self.assertTrue(bad.isError)
                self.assertIn('INVALID_ARGUMENT',bad.content[0].text)
                link=await session.call_tool('generate_affiliate_link',{'origin_url':'https://shopee.com.br/product/1/2','sub_ids':['test'],'expected_account_reference':'synthetic-account'})
                self.assertTrue(link.isError)
                self.assertIn('FIXTURE_NO_LINK',link.content[0].text)

    async def test_private_http_auth_origin_host_and_protocol(self):
        app=build_private_http(load_service('fixture'),TEST_TOKEN,8765)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                r=await client.post('/mcp/',json={})
                self.assertEqual(r.status_code,401)
                headers={'Authorization':'Bearer '+TEST_TOKEN}
                r=await client.post('/mcp/',json={},headers=headers|{'Origin':'https://evil.invalid'})
                self.assertEqual(r.status_code,403)
                r=await client.post('/mcp/',json={},headers=headers|{'Host':'evil.invalid'})
                self.assertEqual(r.status_code,403)
                # Request SDK handles fully in-memory: no TCP listener or public exposure.
                hdr=headers|{'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
                r=await client.post('/mcp/',headers=hdr,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'unit-test','version':'1'}}})
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.json()['result']['serverInfo']['name'],'shopee-affiliate-mcp')
                r=await client.post('/mcp/',headers=hdr|{'MCP-Protocol-Version':'2025-06-18'},json={'jsonrpc':'2.0','id':2,'method':'tools/list'})
                self.assertEqual(r.status_code,200)
                self.assertEqual(len(r.json()['result']['tools']),len(contract()))
                r=await client.post('/mcp/',headers=hdr|{'MCP-Protocol-Version':'2025-06-18'},json={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'affiliate_status','arguments':{}}})
                self.assertEqual(r.status_code,200)
                self.assertTrue(r.json()['result']['structuredContent']['synthetic'])

    async def test_http_missing_or_weak_token_refused(self):
        for token in ['', 'weak']:
            with self.assertRaises(SafeError):
                build_private_http(load_service('fixture'),token)


class PackageTests(unittest.TestCase):
    def test_manifest_and_pending_profile_contract(self):
        manifest=json.loads((ROOT/'plugin.json').read_text())
        self.assertEqual(manifest['name'],ROOT.name)
        self.assertLessEqual(len(manifest['extensions']['com.openai']['interface']['shortDescription']),30)
        mcp=json.loads((ROOT/'mcp.json').read_text())
        self.assertEqual(mcp['mcpServers']['shopee-affiliate']['args'][-1],'fixture')
        schema=json.loads((ROOT/'src/shopee_mcp/profile.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(json.loads((ROOT/'examples/profile.pending.json').read_text()))
