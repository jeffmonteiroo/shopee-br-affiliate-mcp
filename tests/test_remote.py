import asyncio
import base64
import hashlib
import json
import re
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from shopee_mcp.core import Credentials, SafeError, SignedClient, load_service, sign_payload
from shopee_mcp.remote import ACCESS_TTL, SESSION_TTL, build_remote_app, live_factory
from support import ROOT

ORIGIN = 'https://mcp.example.invalid'
CALLBACK = 'https://client.example.invalid/callback'
VERIFIER = 'synthetic-pkce-verifier-' + 'x' * 32
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')


class RemoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = time.time()
        self.created = []
        async def factory(credentials, account):
            self.created.append((credentials.app_id, account))
            if credentials.secret == 'synthetic-rejected-secret':
                raise SafeError('UPSTREAM_AUTH', 'A API recusou a autenticação ou o escopo.')
            service = load_service('fixture')
            service.account = account
            return service
        self.app = build_remote_app(ORIGIN, factory=factory, clock=lambda: self.now, redirects=[CALLBACK])
        self.ready, self.stop = asyncio.Event(), asyncio.Event()
        async def run_lifespan():
            async with self.app.router.lifespan_context(self.app):
                self.ready.set()
                await self.stop.wait()
        self.lifespan_task = asyncio.create_task(run_lifespan())
        await self.ready.wait()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.stop.set()
        await self.lifespan_task

    async def register(self, callback=CALLBACK):
        r = await self.client.post('/register', json={'redirect_uris': [callback],
            'client_name': 'Synthetic MCP client', 'token_endpoint_auth_method': 'none',
            'grant_types': ['authorization_code', 'refresh_token'], 'scope': 'shopee'})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    async def form(self, client, **overrides):
        params = {'client_id': client['client_id'], 'response_type': 'code', 'redirect_uri': CALLBACK,
            'scope': 'shopee', 'state': 'synthetic-state', 'code_challenge': CHALLENGE,
            'code_challenge_method': 'S256', 'resource': ORIGIN + '/mcp'} | overrides
        r = await self.client.get('/authorize', params=params)
        self.assertEqual(r.status_code, 302, r.text)
        r = await self.client.get(r.headers['location'])
        self.assertEqual(r.status_code, 200, r.text)
        hidden = dict(re.findall(r'name="(flow|csrf)" value="([^"]+)"', r.text))
        return hidden, r

    async def code(self, client, app_id='synthetic-app-one', secret='synthetic-secret-one'):
        form, _ = await self.form(client)
        r = await self.client.post('/connect', data=form | {'app_id': app_id, 'secret': secret},
            headers={'Origin': ORIGIN})
        self.assertEqual(r.status_code, 303, r.text)
        params = parse_qs(urlsplit(r.headers['location']).query)
        self.assertEqual(params['state'], ['synthetic-state'])
        self.assertNotIn(secret, r.text + r.headers['location'])
        return params['code'][0]

    async def exchange(self, client, code, **overrides):
        return await self.client.post('/token', data={'grant_type': 'authorization_code',
            'client_id': client['client_id'], 'code': code, 'redirect_uri': CALLBACK,
            'code_verifier': VERIFIER, 'resource': ORIGIN + '/mcp'} | overrides)

    async def token(self, **credentials):
        client = await self.register()
        code = await self.code(client, **credentials)
        r = await self.exchange(client, code)
        self.assertEqual(r.status_code, 200, r.text)
        return client, r.json()

    async def mcp(self, token, method='tools/call', params=None):
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': '2025-06-18'}
        return await self.client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': method,
            'params': params if params is not None else {'name': 'affiliate_status', 'arguments': {}}})

    async def test_discovery_and_auth_required(self):
        r = await self.client.get('/.well-known/oauth-authorization-server')
        self.assertEqual(r.json()['code_challenge_methods_supported'], ['S256'])
        self.assertIn('none', r.json()['token_endpoint_auth_methods_supported'])
        for path in ['/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp']:
            r = await self.client.get(path)
            self.assertEqual(r.json()['resource'], ORIGIN + '/mcp')
        r = await self.client.post('/mcp', json={})
        self.assertEqual(r.status_code, 401)
        self.assertIn('resource_metadata=', r.headers['www-authenticate'])
        self.assertEqual((await self.mcp('synthetic-invalid-token')).status_code, 401)

    async def test_full_flow_account_isolation_and_shared_limits(self):
        a, ta = await self.token()
        b, tb = await self.token(app_id='synthetic-app-two', secret='synthetic-secret-two')
        _, tc = await self.token()
        responses = await asyncio.gather(*(self.mcp(t['access_token']) for t in [ta, tb, tc]))
        accounts = [r.json()['result']['structuredContent']['account_reference'] for r in responses]
        self.assertNotEqual(accounts[0], accounts[1])
        self.assertEqual(accounts[0], accounts[2])
        self.assertEqual(len(self.created), 2)
        init = await self.mcp(ta['access_token'], 'initialize', {'protocolVersion': '2025-06-18',
            'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
        self.assertEqual(init.json()['result']['serverInfo']['version'], '0.3.0')
        tools = (await self.mcp(ta['access_token'], 'tools/list', {})).json()['result']['tools']
        self.assertEqual(len(tools), 17)
        self.assertTrue(all(t['securitySchemes'][0]['type'] == 'oauth2' for t in tools))
        search = await self.mcp(ta['access_token'], params={'name': 'search_offers', 'arguments': {'keyword': 'Luminária'}})
        self.assertTrue(search.json()['result']['structuredContent']['data']['offers'])
        wrong = await self.mcp(ta['access_token'], params={'name': 'generate_affiliate_link', 'arguments': {
            'origin_url': 'https://shopee.com.br/product/1/2', 'sub_ids': ['test'],
            'expected_account_reference': accounts[1]}})
        self.assertTrue(wrong.json()['result']['isError'])
        self.assertIn('ACCOUNT_MISMATCH', wrong.text)
        self.assertNotIn('synthetic-secret', json.dumps([r.json() for r in responses]))

    async def test_pkce_redirect_resource_binding_and_code_replay(self):
        client = await self.register()
        code = await self.code(client)
        for override in [{'code_verifier': 'wrong'}, {'redirect_uri': 'https://evil.invalid/callback'},
                         {'resource': 'https://evil.invalid/mcp'}]:
            self.assertEqual((await self.exchange(client, code, **override)).status_code, 400)
        other = await self.register()
        self.assertEqual((await self.exchange(other, code)).status_code, 400)
        self.assertEqual((await self.exchange(client, code)).status_code, 200)
        self.assertEqual((await self.exchange(client, code)).status_code, 400)

    async def test_csrf_missing_cookie_bad_origin_and_expired_form(self):
        client = await self.register()
        form, page = await self.form(client)
        self.assertIn('httponly', page.headers['set-cookie'].lower())
        self.assertIn('secure', page.headers['set-cookie'].lower())
        self.assertEqual(page.headers['referrer-policy'], 'no-referrer')
        data = form | {'app_id': 'synthetic-app', 'secret': 'synthetic-secret'}
        self.assertEqual((await self.client.post('/connect', data=data)).status_code, 403)
        self.assertEqual((await self.client.post('/connect', data=data, headers={'Origin': 'https://evil.invalid'})).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual((await self.client.post('/connect', data=data, headers={'Origin': ORIGIN})).status_code, 400)
        self.assertFalse(self.created)
        self.now += 301
        self.assertEqual((await self.client.get('/connect', params={'flow': form['flow']})).status_code, 400)

    async def test_invalid_credentials_not_issued_and_not_echoed(self):
        client = await self.register()
        form, _ = await self.form(client)
        secret = 'synthetic-rejected-secret'
        r = await self.client.post('/connect', data=form | {'app_id': 'synthetic-app', 'secret': secret},
            headers={'Origin': ORIGIN})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(secret, r.text)
        self.assertFalse(self.app.state.oauth.access)
        self.assertFalse(self.app.state.oauth.accounts)

    async def test_refresh_rotation_revocation_and_absolute_expiry(self):
        client, token = await self.token()
        form = {'grant_type': 'refresh_token', 'client_id': client['client_id'],
            'refresh_token': token['refresh_token'], 'resource': ORIGIN + '/mcp'}
        self.now += ACCESS_TTL + 1
        self.assertEqual((await self.mcp(token['access_token'])).status_code, 401)
        r = await self.client.post('/token', data=form)
        self.assertEqual(r.status_code, 200, r.text)
        newer = r.json()
        self.assertNotEqual(newer['refresh_token'], token['refresh_token'])
        self.assertEqual((await self.client.post('/token', data=form)).status_code, 400)
        self.assertEqual((await self.mcp(newer['access_token'])).status_code, 200)
        r = await self.client.post('/revoke', data={'client_id': client['client_id'], 'token': newer['refresh_token']})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.mcp(newer['access_token'])).status_code, 401)
        self.assertFalse(self.app.state.oauth.accounts)
        _, token = await self.token()
        self.now += SESSION_TTL + 1
        self.assertEqual((await self.mcp(token['access_token'])).status_code, 401)
        await self.app.state.oauth.sweep()
        self.assertFalse(self.app.state.oauth.accounts)

    async def test_registration_callback_allowlist_and_body_limits(self):
        for callback in ['https://evil.invalid/callback', 'https://chatgpt.com.evil.invalid/connector/oauth/abc',
                         'http://localhost:1234/callback']:
            r = await self.client.post('/register', json={'redirect_uris': [callback]})
            self.assertEqual(r.status_code, 400)
        await self.register('https://chatgpt.com/connector/oauth/synthetic-callback')
        r = await self.client.post('/connect', content='x'*16385)
        self.assertEqual(r.status_code, 413)
        self.assertEqual((await self.client.get('/connect', headers={'Host': 'evil.invalid'})).status_code, 403)

    async def test_restart_drops_credentials_and_tokens(self):
        _, token = await self.token()
        await self.app.state.oauth.close()
        self.assertEqual((await self.mcp(token['access_token'])).status_code, 401)
        self.assertFalse(self.app.state.oauth.clients)
        self.assertFalse(self.app.state.oauth.accounts)

    async def test_abandoned_code_expires_and_drops_credentials(self):
        client = await self.register()
        code = await self.code(client)
        self.now += 61
        await self.app.state.oauth.sweep()
        self.assertFalse(self.app.state.oauth.accounts)
        self.assertEqual((await self.exchange(client, code)).status_code, 400)

    async def test_streamable_http_sdk_client_calls_tools(self):
        _, token = await self.token()
        def client_factory(**kwargs):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), **kwargs)
        async with streamablehttp_client(ORIGIN + '/mcp',
                headers={'Authorization': 'Bearer ' + token['access_token']},
                httpx_client_factory=client_factory) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                self.assertEqual(len(listing.tools), 17)
                result = await session.call_tool('search_offers', {'keyword': 'Luminária'})
                self.assertFalse(result.isError)
                self.assertTrue(result.structuredContent['data']['offers'])

    async def test_invalid_scope_resource_and_challenge_denied_before_form(self):
        client = await self.register()
        for override in [{'resource': 'https://evil.invalid/mcp'}, {'scope': 'admin'},
                         {'code_challenge': 'short'}]:
            r = await self.client.get('/authorize', params={'client_id': client['client_id'],
                'redirect_uri': CALLBACK, 'response_type': 'code', 'code_challenge': CHALLENGE,
                'scope': 'shopee', 'resource': ORIGIN + '/mcp'} | override)
            self.assertNotIn('/connect', r.headers.get('location', ''))
        self.assertFalse(self.app.state.oauth.pending)


class LiveFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_validates_submitted_credentials_with_signed_api_call(self):
        credentials = Credentials('synthetic-submitted-app', 'synthetic-submitted-secret')
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.headers['Authorization'], sign_payload(credentials, request.content, 1700000000))
            return httpx.Response(200, json={'data': {'productOfferV2': {
                'nodes': [], 'pageInfo': {'page': 1, 'limit': 1, 'hasNextPage': False}}}})
        def client(profile, submitted):
            return SignedClient(profile, submitted, transport=httpx.MockTransport(handler), clock=lambda: 1700000000)
        with patch.dict('os.environ', {'SHOPEE_VERIFIED_PROFILE': str(ROOT/'examples/profile.official.json')}):
            with patch('shopee_mcp.remote.SignedClient', client):
                service = await live_factory()(credentials, 'synthetic-account')
        self.assertEqual(len(requests), 1)
        self.assertEqual(service.history_path, '')
        self.assertEqual(service.provider.client.credentials.app_id, credentials.app_id)
        await service.provider.client.close()

    async def test_rejected_credentials_close_client_and_hide_upstream_body(self):
        clients = []
        def create(profile, credentials):
            client = SignedClient(profile, credentials, transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text='synthetic-secret-must-not-echo')))
            clients.append(client)
            return client
        with patch.dict('os.environ', {'SHOPEE_VERIFIED_PROFILE': str(ROOT/'examples/profile.official.json')}):
            with patch('shopee_mcp.remote.SignedClient', create):
                with self.assertRaises(SafeError) as error:
                    await live_factory()(Credentials('synthetic-app', 'synthetic-secret'), 'synthetic-account')
        self.assertNotIn('synthetic-secret-must-not-echo', str(error.exception))
        self.assertTrue(clients[0].http.is_closed)


class ConfigurationTests(unittest.TestCase):
    def test_public_url_rejects_insecure_remote_or_paths(self):
        from shopee_mcp.remote import public_origin
        for url in ['', 'http://example.com', 'https://example.com/mcp',
                    'https://user:pass@example.com', 'https://example.com?x=1']:
            with self.assertRaises(SafeError):
                public_origin(url)
        self.assertEqual(public_origin('http://127.0.0.1:8765'), 'http://127.0.0.1:8765')
