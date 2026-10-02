"""Single-worker OAuth gateway. Encrypted persistence for Shopee credentials and OAuth tokens."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizeError, ProviderTokenVerifier,
    RefreshToken, RegistrationError, TokenError, construct_redirect_uri,
)
from mcp.server.auth.routes import build_metadata, create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .core import Credentials, LiveProvider, Profile, SafeError, Service, SignedClient, load_service
from .server import build_server
from .storage import EncryptedStore

SCOPE = "shopee"
SESSION_TTL = 90 * 24 * 3600
ACCESS_TTL = 3600
FLOW_TTL = 300
LIMIT = 256
COOKIE = "shopee_connect"


@dataclass(repr=False)
class Grant:
    account: str
    client_id: str
    expires_at: float


class SessionCode(AuthorizationCode):
    grant: str


class SessionAccess(AccessToken):
    grant: str


class SessionRefresh(RefreshToken):
    grant: str


def public_origin(value):
    p = urlsplit(value)
    if (not p.hostname or p.username or p.password or p.query or p.fragment
            or p.path not in ("", "/") or p.scheme not in ("http", "https")
            or (p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1"))):
        raise SafeError("CONFIGURATION", "MCP_PUBLIC_URL deve ser uma origem HTTPS sem caminho; HTTP somente local.")
    try:
        p.port
    except ValueError:
        raise SafeError("CONFIGURATION", "Porta de MCP_PUBLIC_URL inválida.") from None
    return str(AnyHttpUrl(value)).rstrip("/")


def live_factory(*, validate=True):
    path = os.getenv("SHOPEE_VERIFIED_PROFILE", "")
    try:
        profile = Profile(json.loads(Path(path).read_text()))
    except (OSError, ValueError):
        raise SafeError("CONFIGURATION", "Configure SHOPEE_VERIFIED_PROFILE com o perfil oficial.") from None
    profile.require_verified()
    contract = load_service("fixture").contract

    async def create(credentials, account):
        service = Service(LiveProvider(profile, SignedClient(profile, credentials)), account, contract)
        service.history_path = ""  # Remote sessions never persist observations or secrets.
        try:
            if validate:
                await service.call("search_offers", {"keyword": "teste", "limit": 1})
        except BaseException:
            await service.provider.client.close()
            raise
        return service
    return create


class OAuthConnections:
    # ponytail: one worker, one encrypted SQLite snapshot; no extra database service.
    def __init__(self, origin, factory, *, clock=time.time, redirects=(), allow_loopback=False, store=None, restore_factory=None):
        self.origin, self.resource, self.factory = origin, origin + "/mcp", factory
        self.clock, self.redirects, self.allow_loopback = clock, set(redirects), allow_loopback
        self.clients, self.pending, self.codes, self.access, self.refresh = {}, {}, {}, {}, {}
        self.grants, self.accounts, self.credentials = {}, {}, {}
        self.store, self.restore_factory = store, restore_factory or factory
        self.pepper = secrets.token_bytes(32)
        self.connect_lock = asyncio.Lock()
        self.auth_attempts = deque()

    def save(self):
        if not self.store:
            return
        state = {"version": 1, "origin": self.origin,
            "pepper": base64.urlsafe_b64encode(self.pepper).decode(),
            "grants": {k: asdict(v) for k, v in self.grants.items()},
            "accounts": {k: {"account": self.accounts[k].account, **asdict(v)}
                for k, v in self.credentials.items()}}
        for name in ("clients", "codes", "access", "refresh"):
            state[name] = {k: v.model_dump(mode="json") for k, v in getattr(self, name).items()}
        self.store.save(state)

    async def restore(self):
        if not self.store:
            return
        try:
            state = self.store.load()
            if state is None:
                return
            if state["version"] != 1 or state["origin"] != self.origin:
                raise ValueError
            self.pepper = base64.urlsafe_b64decode(state["pepper"])
            if len(self.pepper) != 32:
                raise ValueError
            for name, model in (("clients", OAuthClientInformationFull), ("codes", SessionCode),
                                ("access", SessionAccess), ("refresh", SessionRefresh)):
                setattr(self, name, {k: model.model_validate(v) for k, v in state[name].items()})
            self.grants = {k: Grant(**v) for k, v in state["grants"].items()}
            now = self.clock()
            referenced = {v.grant for name in ("codes", "access", "refresh")
                for v in getattr(self, name).values() if v.expires_at > now}
            active = {g.account for k, g in self.grants.items() if g.expires_at > now and k in referenced}
            for fingerprint in active:
                account = state["accounts"][fingerprint]
                credentials = Credentials(account["app_id"], account["secret"])
                self.accounts[fingerprint] = await self.restore_factory(credentials, account["account"])
                self.credentials[fingerprint] = credentials
            await self.sweep()
        except BaseException as error:
            await self.close()
            if isinstance(error, (KeyError, ValueError, TypeError)):
                raise SafeError("CONFIGURATION", "Estado OAuth inválido ou origem alterada; preserve o banco.") from None
            raise

    def allowed_redirect(self, value):
        if value in self.redirects:
            return True
        p = urlsplit(value)
        if p.username or p.password or p.fragment:
            return False
        if (p.scheme == "https" and p.netloc == "chatgpt.com" and not p.query
                and re.fullmatch(r"/connector/oauth(?:/[A-Za-z0-9_-]{1,128})?", p.path)):
            return True
        # Explicit opt-in for Hermes/browser callbacks on the user's own computer.
        return (self.allow_loopback and p.scheme == "http"
                and p.hostname in {"localhost", "127.0.0.1"} and not p.query)

    async def sweep(self):
        before = tuple(len(getattr(self, n)) for n in ("codes", "grants", "access", "refresh", "accounts"))
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if v[2] > now}
        self.codes = {k: v for k, v in self.codes.items() if v.expires_at > now}
        self.grants = {k: v for k, v in self.grants.items() if v.expires_at > now}
        self.access = {k: v for k, v in self.access.items() if v.expires_at > now and v.grant in self.grants}
        self.refresh = {k: v for k, v in self.refresh.items() if v.expires_at > now and v.grant in self.grants}
        referenced = {v.grant for store in (self.codes, self.access, self.refresh) for v in store.values()}
        self.grants = {k: v for k, v in self.grants.items() if k in referenced}
        self.codes = {k: v for k, v in self.codes.items() if v.grant in self.grants}
        active = {g.account for g in self.grants.values()}
        for account in list(self.accounts):
            if account not in active:
                service = self.accounts.pop(account)
                self.credentials.pop(account, None)
                if isinstance(service.provider, LiveProvider):
                    await service.provider.client.close()

        after = tuple(len(getattr(self, n)) for n in ("codes", "grants", "access", "refresh", "accounts"))
        if before != after:
            self.save()

    async def close(self):
        services = list(self.accounts.values())
        self.clients.clear()
        self.pending.clear()
        self.codes.clear()
        self.access.clear()
        self.refresh.clear()
        self.grants.clear()
        self.accounts.clear()
        self.credentials.clear()
        for service in services:
            if isinstance(service.provider, LiveProvider):
                await service.provider.client.close()

        if self.store:
            self.store.close()
            self.store = None

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info):
        if len(self.clients) >= LIMIT:
            raise RegistrationError("invalid_client_metadata", "Limite de clientes atingido.")
        if client_info.token_endpoint_auth_method not in {"none", "client_secret_post"}:
            raise RegistrationError("invalid_client_metadata", "Método de autenticação não suportado.")
        if not client_info.redirect_uris or any(not self.allowed_redirect(str(u)) for u in client_info.redirect_uris):
            raise RegistrationError("invalid_redirect_uri", "Callback não autorizado pelo administrador.")
        self.clients[client_info.client_id] = client_info
        self.save()

    async def authorize(self, client, params):
        await self.sweep()
        if (params.resource not in (None, self.resource)
                or params.scopes != [SCOPE]
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge)):
            raise AuthorizeError("invalid_request", "Recurso, escopo ou PKCE inválido.")
        if len(self.pending) >= LIMIT:
            raise AuthorizeError("temporarily_unavailable", "Limite de conexões atingido.")
        flow = secrets.token_urlsafe(32)
        self.pending[flow] = (client.client_id, params, self.clock() + FLOW_TTL, None)
        return self.origin + "/connect?flow=" + flow

    def pending_flow(self, flow):
        pending = self.pending.get(flow)
        return pending if pending and pending[2] > self.clock() else None

    async def connect(self, flow, csrf, cookie, credentials):
        async with self.connect_lock:
            pending = self.pending_flow(flow)
            if (not pending or not pending[3] or not csrf or not cookie
                    or not secrets.compare_digest(csrf, pending[3])
                    or not secrets.compare_digest(cookie, pending[3])):
                raise SafeError("CONNECT_EXPIRED", "Conexão expirada ou formulário inválido; conecte novamente.")
            # Bound outbound credential probes and memory usage in this small gateway.
            now = self.clock()
            while self.auth_attempts and self.auth_attempts[0] <= now - 60:
                self.auth_attempts.popleft()
            if len(self.auth_attempts) >= 10 or len(self.grants) >= LIMIT:
                raise SafeError("CONNECT_LIMIT", "Muitas conexões; aguarde um minuto.")
            self.auth_attempts.append(now)
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", credentials.app_id)
                    or not 1 <= len(credentials.secret) <= 512
                    or any(ord(c) < 33 or ord(c) > 126 for c in credentials.secret)):
                raise SafeError("CREDENTIALS_INVALID", "Confira o formato do App ID e App Secret.")
            fingerprint = hmac.new(self.pepper,
                (credentials.app_id + "\0" + credentials.secret).encode(), hashlib.sha256).hexdigest()
            service = self.accounts.get(fingerprint)
            if service is None:
                service = await self.factory(credentials, "conta-" + secrets.token_hex(12))
                self.accounts[fingerprint] = service
                self.credentials[fingerprint] = credentials
            # Validity can change during the Shopee request; never issue stale grants.
            if not self.pending_flow(flow):
                if not any(g.account == fingerprint for g in self.grants.values()):
                    self.accounts.pop(fingerprint, None)
                    self.credentials.pop(fingerprint, None)
                    if isinstance(service.provider, LiveProvider):
                        await service.provider.client.close()
                raise SafeError("CONNECT_EXPIRED", "Conexão expirada; conecte novamente.")
            self.pending.pop(flow)
            client_id, params, _, _ = pending
            grant = secrets.token_urlsafe(32)
            self.grants[grant] = Grant(fingerprint, client_id, self.clock() + SESSION_TTL)
            code = SessionCode(code=secrets.token_urlsafe(32), grant=grant, scopes=[SCOPE],
                expires_at=self.clock() + 60, client_id=client_id, code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri, redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=self.resource)
            self.codes[code.code] = code
            self.save()
            return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state)

    async def load_authorization_code(self, client, authorization_code):
        code = self.codes.get(authorization_code)
        return code if code and code.client_id == client.client_id else None

    def issue(self, client_id, grant):
        session = self.grants.get(grant)
        if not session or session.expires_at <= self.clock() or session.client_id != client_id:
            raise TokenError("invalid_grant", "Conexão expirada; conecte novamente.")
        access = SessionAccess(token=secrets.token_urlsafe(32), client_id=client_id, grant=grant,
            scopes=[SCOPE], expires_at=min(int(self.clock()) + ACCESS_TTL, int(session.expires_at)), resource=self.resource)
        refresh = SessionRefresh(token=secrets.token_urlsafe(32), client_id=client_id, grant=grant,
            scopes=[SCOPE], expires_at=int(session.expires_at))
        self.access[access.token], self.refresh[refresh.token] = access, refresh
        self.save()
        return OAuthToken(access_token=access.token, refresh_token=refresh.token,
            token_type="Bearer", expires_in=access.expires_at-int(self.clock()), scope=SCOPE)

    async def exchange_authorization_code(self, client, authorization_code):
        code = self.codes.pop(authorization_code.code, None)
        if not code or code.expires_at <= self.clock() or code.client_id != client.client_id:
            raise TokenError("invalid_grant", "Código inválido ou já utilizado.")
        return self.issue(client.client_id, code.grant)

    async def load_refresh_token(self, client, refresh_token):
        token = self.refresh.get(refresh_token)
        return token if token and token.client_id == client.client_id else None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        token = self.refresh.pop(refresh_token.token, None)
        if (not token or token.client_id != client.client_id or scopes != [SCOPE]
                or token.expires_at <= self.clock() or token.grant not in self.grants
                or self.grants[token.grant].expires_at <= self.clock()):
            raise TokenError("invalid_grant", "Refresh inválido ou já utilizado.")
        self.grants[token.grant].expires_at = self.clock() + SESSION_TTL
        for key, value in list(self.access.items()):
            if value.grant == token.grant:
                self.access.pop(key)
        return self.issue(client.client_id, token.grant)

    async def load_access_token(self, token):
        access = self.access.get(token)
        grant = self.grants.get(access.grant) if access else None
        if (not access or not grant or access.expires_at <= self.clock()
                or grant.expires_at <= self.clock() or access.resource != self.resource):
            return None
        return access

    async def revoke_token(self, token):
        self.grants.pop(token.grant, None)
        await self.sweep()

    def resolve_service(self, request):
        user = request.scope.get("user") if request else None
        access = getattr(user, "access_token", None)
        grant = self.grants.get(access.grant) if isinstance(access, SessionAccess) else None
        if (not grant or grant.expires_at <= self.clock() or access.expires_at <= self.clock()
                or self.access.get(access.token) is not access):
            raise SafeError("AUTH_REQUIRED", "Conecte novamente sua conta Shopee.")
        return self.accounts[grant.account]


class RemoteGuard:
    """Host/origin, request size and cache controls before OAuth or MCP parsing."""
    def __init__(self, app, origin):
        self.app, self.origin, self.host = app, origin, urlsplit(origin).netloc

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if (headers.get(b"host", b"").decode() != self.host
                or headers.get(b"origin", self.origin.encode()).decode() != self.origin):
            return await JSONResponse({"error": "invalid host/origin"}, status_code=403)(scope, receive, send)
        limit = 1024 * 1024 if scope["path"] in {"/mcp", "/mcp/"} else 16384
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                return await JSONResponse({"error": "request too large"}, status_code=413)(scope, receive, send)
            if not message.get("more_body"):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        async def secured_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
                ]
            await send(message)
        await self.app(scope, replay, secured_send)


def build_remote_app(public_url, *, factory=None, clock=time.time, redirects=None, allow_loopback=None, store=None, restore_factory=None):
    origin = public_origin(public_url)
    if redirects is None:
        try:
            redirects = json.loads(os.getenv("MCP_OAUTH_REDIRECT_URIS", "[]"))
            if not isinstance(redirects, list) or any(not isinstance(u, str) for u in redirects):
                raise ValueError
        except ValueError:
            raise SafeError("CONFIGURATION", "MCP_OAUTH_REDIRECT_URIS deve ser uma lista JSON de callbacks.") from None
    if factory is None:
        factory = live_factory()
        restore_factory = live_factory(validate=False)
        store = store or EncryptedStore(os.getenv("MCP_STATE_DB", "/app/data/oauth.sqlite3"),
            os.getenv("MCP_CREDENTIALS_KEY", ""))
    provider = OAuthConnections(origin, factory, clock=clock, redirects=redirects,
        store=store, restore_factory=restore_factory,
        allow_loopback=allow_loopback if allow_loopback is not None else os.getenv("MCP_ALLOW_LOOPBACK_CALLBACKS") == "true")
    registration = ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE])
    revocation = RevocationOptions(enabled=True)
    routes = create_auth_routes(provider, AnyHttpUrl(origin),
        client_registration_options=registration, revocation_options=revocation)
    # SDK v1 defaults to secret_post; explicitly advertise both supported DCR methods.
    metadata = build_metadata(AnyHttpUrl(origin), None, registration, revocation)
    metadata.token_endpoint_auth_methods_supported = ["none", "client_secret_post"]
    metadata.revocation_endpoint_auth_methods_supported = ["none", "client_secret_post"]
    token_handler = TokenHandler(provider, ClientAuthenticator(provider))

    async def token_endpoint(request):
        form = await request.form()
        if form.get("resource") not in (None, provider.resource):
            return JSONResponse({"error": "invalid_target"}, status_code=400)
        if form.get("grant_type") == "authorization_code" and not re.fullmatch(
                r"[A-Za-z0-9._~-]{43,128}", str(form.get("code_verifier", ""))):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return await token_handler.handle(request)

    async def revoke_endpoint(request):
        # SDK 1.21.1 incorrectly requires client_secret even for public clients.
        form = await request.form()
        try:
            client = await ClientAuthenticator(provider).authenticate(
                str(form.get("client_id", "")), form.get("client_secret"))
        except AuthenticationError:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        value = str(form.get("token", ""))
        token = await provider.load_access_token(value) or await provider.load_refresh_token(client, value)
        if token and token.client_id == client.client_id:
            await provider.revoke_token(token)
        return JSONResponse({})

    for i, route in enumerate(routes):
        if route.path == "/.well-known/oauth-authorization-server":
            routes[i] = Route(route.path, MetadataHandler(metadata).handle, methods=["GET"])
        elif route.path == "/token":
            routes[i] = Route(route.path, token_endpoint, methods=["POST"])
        elif route.path == "/revoke":
            routes[i] = Route(route.path, revoke_endpoint, methods=["POST"])
    resource_routes = create_protected_resource_routes(AnyHttpUrl(provider.resource), [AnyHttpUrl(origin)],
        scopes_supported=[SCOPE], resource_name="Shopee Affiliate MCP")
    routes.extend(resource_routes)
    routes.append(Route("/.well-known/oauth-protected-resource", resource_routes[0].endpoint, methods=["GET"]))

    async def connect(request: Request):
        if request.method == "GET":
            flow = request.query_params.get("flow", "")
            pending = provider.pending_flow(flow)
            if not pending:
                return HTMLResponse("Conexão expirada. Volte ao cliente e conecte novamente.", status_code=400)
            csrf = secrets.token_urlsafe(32)
            provider.pending[flow] = (*pending[:3], csrf)
            client = provider.clients[pending[0]]
            destination = html.escape(str(pending[1].redirect_uri))
            name = html.escape(client.client_name or "Cliente MCP")
            page = f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Conectar Shopee</title>
<style>body{{font:16px system-ui;background:#f5f5f5;color:#222;margin:0;padding:24px}}main{{max-width:440px;margin:8vh auto;padding:28px;background:white;border-radius:16px}}h1{{font-size:26px}}label{{display:block;margin-top:20px}}input,button{{box-sizing:border-box;width:100%;padding:12px;margin-top:8px;border:1px solid #ccc;border-radius:8px;font:inherit}}button{{background:#b9380a;color:white;border:0;margin-top:24px}}small{{display:block;margin-top:20px;line-height:1.5}}code{{overflow-wrap:anywhere}}</style>
<main><h1>Conectar sua Shopee</h1><p>Informe as credenciais da Open API de Afiliados. Não é a senha da sua conta Shopee.</p>
<p>Você autoriza <strong>{name}</strong> a pesquisar ofertas, gerar links e consultar seus relatórios enquanto esta conexão estiver autorizada.</p><small>O acesso será entregue a: <code>{destination}</code>. Confira o destino antes de continuar.</small>
<form method="post" action="/connect"><input type="hidden" name="flow" value="{html.escape(flow)}"><input type="hidden" name="csrf" value="{csrf}">
<label for="app_id">App ID</label><input id="app_id" name="app_id" type="password" maxlength="128" autocomplete="off" required>
<label for="secret">App Secret</label><input id="secret" name="secret" type="password" maxlength="512" autocomplete="off" required>
<button>Conectar e autorizar</button></form><small>As credenciais ficam criptografadas neste servidor. A conexão é renovada automaticamente; após 90 dias sem renovação, conecte novamente. Serviço independente, sem vínculo oficial com a Shopee.</small></main></html>'''
            response = HTMLResponse(page)
            response.set_cookie(COOKIE, csrf, max_age=FLOW_TTL, httponly=True,
                secure=origin.startswith("https:"), samesite="strict", path="/connect")
            return response
        if request.headers.get("origin") != origin:
            return HTMLResponse("Origem do formulário inválida.", status_code=403)
        try:
            form = await request.form()
            credentials = Credentials(str(form.get("app_id", "")), str(form.get("secret", "")))
            target = await provider.connect(str(form.get("flow", "")), str(form.get("csrf", "")),
                request.cookies.get(COOKIE, ""), credentials)
        except SafeError as error:
            return HTMLResponse(html.escape(error.message) + " Volte e tente conectar novamente.", status_code=400)
        except Exception:
            return HTMLResponse("Não foi possível validar as credenciais. Tente conectar novamente.", status_code=400)
        response = RedirectResponse(target, status_code=303)
        response.delete_cookie(COOKIE, path="/connect")
        return response

    server = build_server(load_service("fixture"), resolve_service=provider.resolve_service)
    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(origin).netloc], allowed_origins=[origin]))
    authenticated = RequireAuthMiddleware(manager.handle_request, [SCOPE],
        resource_metadata_url=AnyHttpUrl(origin + "/.well-known/oauth-protected-resource/mcp"))
    async def health(request):
        return JSONResponse({"status": "ok", "version": "0.4.0"})

    routes.extend([Route("/health", health, methods=["GET"]),
        Route("/connect", connect, methods=["GET", "POST"]),
        Route("/mcp", authenticated, methods=["GET", "POST", "DELETE"]),
        Route("/mcp/", authenticated, methods=["GET", "POST", "DELETE"])])

    @asynccontextmanager
    async def lifespan(app):
        await provider.restore()
        async def cleanup():
            while True:
                await asyncio.sleep(30)
                async with provider.connect_lock:
                    await provider.sweep()
        task = asyncio.create_task(cleanup())
        try:
            async with manager.run():
                yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await provider.close()

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.oauth = provider
    app.add_middleware(AuthenticationMiddleware, backend=BearerAuthBackend(ProviderTokenVerifier(provider)))
    app.add_middleware(RemoteGuard, origin=origin)
    return app
