from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator

OFFICIAL_HOST = "open-api.affiliate.shopee.com.br"
OFFICIAL_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
OFFICIAL_HOURLY_CALL_LIMIT = 8000
PRODUCT_HOSTS = {"shopee.com.br", "www.shopee.com.br"}
MAX_BODY_BYTES = 2 * 1024 * 1024


class SafeError(Exception):
    """Only static public codes/messages; never upstream bodies or exception text."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def fail(code: str, message: str):
    raise SafeError(code, message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def valid_url(value, hosts):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        fail("INVALID_URL", "URL HTTPS inválida.")
    try:
        u = urlsplit(value)
        ok = (u.scheme == "https" and u.hostname in hosts and u.port in (None, 443)
              and not u.username and not u.password and not u.fragment)
    except ValueError:
        ok = False
    if not ok:
        fail("INVALID_URL", "Domínio ou formato de URL não permitido.")
    return value


def validate(schema, value, code="INVALID_ARGUMENT"):
    if next(Draft202012Validator(schema).iter_errors(value), None) is not None:
        fail(code, "Dados fora do contrato; confira tools/list ou o perfil oficial.")


def decimal_string(value):
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0:
            raise InvalidOperation
        return format(d, "f")
    except (InvalidOperation, ValueError):
        fail("UPSTREAM_SHAPE", "Campo numérico incompatível com o contrato.")


@dataclass(repr=False)
class Credentials:
    app_id: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_env(cls):
        app_id, secret = os.getenv("SHOPEE_APP_ID", ""), os.getenv("SHOPEE_APP_SECRET", "")
        if not app_id or not secret:
            fail("CREDENTIALS_MISSING", "Configure credenciais no ambiente seguro do processo.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", app_id):
            fail("CONFIGURATION", "Formato do identificador de aplicação inválido.")
        return cls(app_id, secret)


def sign_payload(credentials, payload: bytes, timestamp: int):
    """Documented concatenated SHA256. The exact transmitted bytes are signed."""
    ts = str(timestamp)
    digest = hashlib.sha256(credentials.app_id.encode() + ts.encode() + payload
                            + credentials.secret.encode()).hexdigest()
    return f"SHA256 Credential={credentials.app_id}, Timestamp={ts}, Signature={digest}"


def path_get(value, path):
    try:
        for key in path.split(".") if path else []:
            value = value[key]
        return value
    except (KeyError, TypeError):
        fail("UPSTREAM_SHAPE", "Resposta não corresponde ao perfil verificado.")


def render_query(op, args):
    """One-pass JSON-compatible GraphQL string/list literals; no guessed input type."""
    literals = set(op.get("literal_arguments", []))
    tokens = set(re.findall(r"\{\{([a-z_]+)\}\}", op["query"]))
    if tokens != literals:
        fail("CONFIGURATION", "Placeholders GraphQL não correspondem ao perfil.")
    encoded = {}
    integer_args = set(op.get("literal_integer_arguments", []))
    if not integer_args <= literals:
        fail("CONFIGURATION", "Encoding inteiro sem literal correspondente.")
    for name in literals:
        value = args.get(name)
        if value is None and name in op.get("optional_arguments", []):
            encoded[name] = "null"
            continue
        if name in op.get("literal_boolean_arguments", []):
            if type(value) is not bool:
                fail("INVALID_ARGUMENT", "Literal booleano GraphQL inválido.")
            encoded[name] = "true" if value else "false"
            continue
        if name in op.get("literal_enum_arguments", {}):
            if value not in op["literal_enum_arguments"][name]:
                fail("INVALID_ARGUMENT", "Enum GraphQL inválido.")
            encoded[name] = value
            continue
        if name in op.get("literal_integer_list_arguments", []):
            if not isinstance(value, list) or any(type(x) is not int or x not in {1, 2, 4} for x in value):
                fail("INVALID_ARGUMENT", "Lista de tipos de loja inválida.")
            encoded[name] = json.dumps(value, separators=(",", ":"))
            continue
        if name in integer_args:
            if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,20}", str(value)):
                fail("INVALID_ARGUMENT", "Literal inteiro GraphQL inválido.")
            value = int(value)
            if value > 9223372036854775807:
                fail("INVALID_ARGUMENT", "Inteiro excede limite local de 64 bits assinado.")
            encoded[name] = str(value)
            continue
        if not (isinstance(value, str) or isinstance(value, list) and all(isinstance(x, str) for x in value)):
            fail("INVALID_ARGUMENT", "Literal GraphQL exige string ou lista de strings.")
        encoded[name] = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    # Single substitution pass: user strings containing {{another_token}} cannot be re-expanded.
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda match: encoded[match.group(1)], op["query"])


def mapped_inputs(op):
    return set(op["variables"]) | set(op.get("literal_arguments", []))


class Profile:
    """Reviewed admin configuration, never writable through MCP arguments."""
    def __init__(self, data):
        schema = json.loads(Path(__file__).with_name("profile.schema.json").read_text())
        validate(schema, data)
        self.data = data
        self.endpoint = valid_url(data["endpoint"], {OFFICIAL_HOST})
        if self.endpoint != OFFICIAL_ENDPOINT:
            fail("CONFIGURATION", "Endpoint deve ser a URL GraphQL oficial BR confirmada.")
        self.confirmed = data["official_docs_verified"]

    def require_verified(self):
        if not self.confirmed or not self.data["verification"]["source_url"] or not self.data["verification"]["checked_at"]:
            fail("SCHEMA_UNVERIFIED", "Confirme endpoint, autenticação e schema no portal oficial primeiro.")
        valid_url(self.data["verification"]["source_url"], {OFFICIAL_HOST, "affiliate.shopee.com.br"})
        if self.data["auth_algorithm"] != "sha256_app_timestamp_body_secret":
            fail("AUTH_UNVERIFIED", "Algoritmo de autenticação ainda não confirmado.")

    def operation(self, name):
        self.require_verified()
        op = self.data["operations"].get(name)
        if not op or not op["query"] or not op["result_path"]:
            fail("OPERATION_UNAVAILABLE", "Operação ainda não mapeada no perfil oficial.")
        expected = "mutation" if name == "link" else "query"
        if not op["query"].lstrip().startswith(expected):
            fail("CONFIGURATION", "Tipo da operação GraphQL incompatível.")
        return op


class SignedClient:
    def __init__(self, profile, credentials, *, transport=None, clock=time.time, sleep=asyncio.sleep):
        self.profile, self.credentials = profile, credentials
        self.clock, self.sleep = clock, sleep
        self.http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(8, connect=3),
                                     follow_redirects=False, trust_env=False,
                                     limits=httpx.Limits(max_connections=2))
        self.lock = asyncio.Lock()
        self.last_start = 0.0
        self.call_starts = deque()

    async def close(self):
        await self.http.aclose()

    async def _request(self, op, args, *, read_only):
        variables = {}
        for source, spec in op["variables"].items():
            if source not in args or args[source] is None:
                continue
            value = args[source]
            if spec["encoding"] == "integer":
                value = int(value)
            variables[spec["name"]] = value
        payload = {"query": render_query(op, args), "variables": variables}
        if op.get("operation_name"):
            payload["operationName"] = op["operation_name"]
        body = json.dumps(payload,
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # One mutation attempt: an ambiguous timeout must not create a second link.
        attempts = 3 if read_only and not op.get("cursor_single_use") else 1
        for attempt in range(attempts):
            # Per-process budget counts attempts. Vendor quota scope is undocumented.
            async with self.lock:
                gap = 0.5 - (time.monotonic() - self.last_start)
                if gap > 0:
                    await self.sleep(gap)
                self.last_start = time.monotonic()
                while self.call_starts and self.last_start - self.call_starts[0] >= 3600:
                    self.call_starts.popleft()
                if len(self.call_starts) >= OFFICIAL_HOURLY_CALL_LIMIT:
                    fail("LOCAL_RATE_LIMIT", "Orçamento horário local esgotado; aguarde antes de tentar novamente.")
                self.call_starts.append(self.last_start)
                headers = {"Authorization": sign_payload(self.credentials, body, int(self.clock())),
                           "Content-Type": "application/json", "Accept": "application/json"}
                try:
                    async with self.http.stream("POST", self.profile.endpoint, content=body, headers=headers) as r:
                        status = r.status_code
                        chunks, size = [], 0
                        async for chunk in r.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BODY_BYTES:
                                fail("UPSTREAM_SIZE", "Resposta da API excede limite local.")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        retry_after = r.headers.get("Retry-After", "")
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt + 1 < attempts:
                        await self.sleep(0.5 * 2 ** attempt)
                        continue
                    fail("UPSTREAM_TIMEOUT" if read_only else "LINK_OUTCOME_UNKNOWN",
                         "Consulta não concluída." if read_only else "Resultado do link desconhecido; não repetir automaticamente.")
            if status in (502, 503, 504) and attempt + 1 < attempts:
                try:
                    delay = min(3.0, max(0.5, float(retry_after)))
                except ValueError:
                    delay = 0.5 * 2 ** attempt
                await self.sleep(delay)
                continue
            if status in (401, 403):
                fail("UPSTREAM_AUTH", "A API recusou a autenticação ou o escopo.")
            if status == 429:
                fail("UPSTREAM_RATE_LIMIT", "Limite da API atingido; tente depois.")
            if status >= 500 and not read_only:
                fail("LINK_OUTCOME_UNKNOWN", "Servidor falhou após envio do link; não repetir automaticamente.")
            if status != 200:
                fail("UPSTREAM_HTTP", "Resposta HTTP inesperada da API; corpo omitido.")
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                fail("UPSTREAM_SHAPE", "Resposta JSON inválida da API.")
            if not isinstance(result, dict):
                fail("UPSTREAM_SHAPE", "Resposta GraphQL inválida.")
            # Reject partial GraphQL successes; no raw message can echo secrets/user input.
            if result.get("errors"):
                errors = result["errors"]
                # Only documented numeric categories are interpreted; never expose raw messages.
                mapping = {
                    "10000": ("UPSTREAM_SYSTEM", "API retornou erro de sistema."),
                    "10010": ("UPSTREAM_SCHEMA", "API recusou parsing, schema ou tipos da operação."),
                    "10020": ("UPSTREAM_AUTH", "API recusou autenticação, credencial, assinatura ou validade temporal."),
                    "10030": ("UPSTREAM_RATE_LIMIT", "Limite de tráfego da API atingido; tente depois."),
                    "10031": ("UPSTREAM_ACCESS_DENIED", "Acesso à API negado."),
                    "10032": ("UPSTREAM_AFFILIATE_ID", "Identificador de afiliado recusado pela API."),
                    "10033": ("UPSTREAM_ACCOUNT_FROZEN", "API indica conta congelada."),
                    "10034": ("UPSTREAM_ACCOUNT_BLOCKED", "API indica afiliado bloqueado."),
                    "10035": ("UPSTREAM_NO_API_ACCESS", "API indica ausência de acesso à plataforma Open API."),
                    "11000": ("UPSTREAM_BUSINESS", "API recusou a operação por regra de negócio."),
                    "11001": ("UPSTREAM_PARAMETER", "API recusou parâmetros da operação."),
                    "11002": ("UPSTREAM_BOUND_ACCOUNT", "API indica erro de vinculação de conta."),
                }
                if isinstance(errors, list):
                    for error in errors:
                        ext = error.get("extensions") if isinstance(error, dict) else None
                        code = str(ext.get("code", "")) if isinstance(ext, dict) else ""
                        if code in mapping:
                            fail(*mapping[code])
                fail("UPSTREAM_GRAPHQL", "API retornou erro GraphQL; confira o contrato no portal.")
            return path_get(result, op["result_path"])

    async def execute(self, op, args, *, read_only):
        try:
            async with asyncio.timeout(30):
                return await self._request(op, args, read_only=read_only)
        except TimeoutError:
            fail("UPSTREAM_TIMEOUT" if read_only else "LINK_OUTCOME_UNKNOWN", "Prazo total da operação excedido.")


class LiveProvider:
    mode = "live"
    def __init__(self, profile, client):
        self.profile, self.client = profile, client

    def normalize_offer(self, node, op, observed_at):
        if not isinstance(node, dict):
            fail("UPSTREAM_SHAPE", "Produto inválido na resposta da API.")
        fields = op["fields"]
        def get(name):
            return path_get(node, fields[name]) if name in fields else None
        item, shop, name = get("item_id"), get("shop_id"), get("name")
        if item is None or shop is None or not isinstance(name, str):
            fail("UPSTREAM_SHAPE", "Identificadores ou nome de produto ausentes.")
        ids = [str(item), str(shop)]
        if not all(re.fullmatch(r"[0-9]{1,20}", i) for i in ids):
            fail("UPSTREAM_SHAPE", "Identificadores de produto inválidos.")
        product_url = valid_url(get("product_url"), PRODUCT_HOSTS)
        rate = decimal_string(get("commission_rate"))
        unit = self.profile.data["commission_rate_unit"]
        fraction = (decimal_string(Decimal(rate) / 100) if unit == "percent"
                    else rate if unit == "fraction" else None) if rate is not None else None
        if fraction is not None and Decimal(fraction) > 1:
            fail("UPSTREAM_SHAPE", "Taxa de comissão fora da faixa confirmada.")
        result = {"item_id": ids[0], "shop_id": ids[1], "name": name[:1000],
                "shop_name": str(get("shop_name"))[:300] if get("shop_name") is not None else None,
                "product_url": product_url, "price_min_brl": decimal_string(get("price_min")),
                "price_max_brl": decimal_string(get("price_max")),
                "commission_rate_raw": rate, "commission_rate_fraction": fraction,
                "commission_estimated_brl": decimal_string(get("commission_amount")),
                "currency_evidence": "market_region_inference",
                "commission_status": "estimated", "sales": get("sales"), "rating": get("rating"),
                "period_start_raw": get("period_start"), "period_end_raw": get("period_end"),
                "observed_at": observed_at, "source": "shopee_affiliate_open_api"}
        for key in ("image_url", "category_ids", "discount_percent", "shop_types"):
            if key in fields:
                result[key] = get(key)
        for key in ("seller_commission_rate", "shopee_commission_rate"):
            if key in fields:
                result[key] = decimal_string(get(key))
        return result

    async def search(self, args):
        op = self.profile.operation("search")
        for key in ("keyword", "page", "limit"):
            if key not in mapped_inputs(op):
                fail("CONFIGURATION", "Pesquisa exige keyword, page e limit no perfil.")
        if args.get("cursor") is not None and "cursor" not in op["variables"]:
            fail("INVALID_ARGUMENT", "Este perfil não aceita cursor.")
        if any(key not in mapped_inputs(op) for key in args):
            fail("OPERATION_UNAVAILABLE", "Filtro solicitado não está mapeado neste perfil.")
        raw = await self.client.execute(op, args, read_only=True)
        nodes = path_get(raw, op["nodes_path"])
        page_info = path_get(raw, op["page_info_path"])
        if not isinstance(nodes, list) or len(nodes) > args["limit"] or not isinstance(page_info, dict):
            fail("UPSTREAM_SHAPE", "Paginação incompatível com o contrato.")
        has_next = path_get(page_info, op["page_fields"]["has_next"])
        page = path_get(page_info, op["page_fields"]["page"])
        limit = path_get(page_info, op["page_fields"]["limit"])
        if type(has_next) is not bool or page != args["page"] or limit != args["limit"]:
            fail("UPSTREAM_SHAPE", "Metadados de paginação inválidos.")
        cursor = path_get(page_info, op["page_fields"]["cursor"]) if "cursor" in op["page_fields"] else None
        observed = utc_now()
        return {"offers": [self.normalize_offer(n, op, observed) for n in nodes],
                "pagination": {"page": page, "limit": limit, "has_next_page": has_next,
                               "next_page": page + 1 if has_next else None,
                               "next_cursor": cursor if has_next else None}, "observed_at": observed}

    async def get(self, args):
        op = self.profile.operation("get")
        if not {"item_id", "shop_id"} <= mapped_inputs(op):
            fail("CONFIGURATION", "Detalhe exige item_id e shop_id no perfil.")
        raw = await self.client.execute(op, args, read_only=True)
        if op.get("nodes_path"):
            raw = path_get(raw, op["nodes_path"])
        if isinstance(raw, list):
            raw = next((n for n in raw if str(path_get(n, op["fields"]["item_id"])) == args["item_id"]
                        and str(path_get(n, op["fields"]["shop_id"])) == args["shop_id"]), None)
        if raw is None:
            fail("NOT_FOUND", "Produto não retornado pela API para os IDs solicitados.")
        result = self.normalize_offer(raw, op, utc_now())
        if result["item_id"] != args["item_id"] or result["shop_id"] != args["shop_id"]:
            fail("UPSTREAM_SHAPE", "API retornou outro produto.")
        return {"offer": result}

    def validate_link(self, args):
        valid_url(args["origin_url"], PRODUCT_HOSTS)
        op = self.profile.operation("link")
        if not {"origin_url", "sub_ids"} <= mapped_inputs(op):
            fail("CONFIGURATION", "Link exige origin_url e sub_ids no perfil.")
        rules = self.profile.data["sub_ids"]
        if not rules["official_count_verified"]:
            fail("SUBIDS_UNVERIFIED", "Quantidade de subIDs pendente de confirmação oficial.")
        if not args["sub_ids"] or len(args["sub_ids"]) > rules["max_count"]:
            fail("INVALID_ARGUMENT", "Quantidade de subIDs incompatível com o perfil.")
        if any(len(x) > rules["max_length"] or not re.fullmatch(rules["pattern"], x) for x in args["sub_ids"]):
            fail("INVALID_ARGUMENT", "Formato dos subIDs incompatível com o perfil.")
        return op

    async def link(self, args):
        op = self.validate_link(args)
        raw = await self.client.execute(op, args, read_only=False)
        link = valid_url(path_get(raw, op["fields"]["affiliate_url"]), set(self.profile.data["affiliate_link_hosts"]))
        return {"affiliate_url": link, "origin_url": args["origin_url"], "sub_ids": args["sub_ids"],
                "generated_at": utc_now(), "source": "shopee_affiliate_open_api",
                "attribution_evidence": "credential_context_only",
                "commission_status": "estimated"}


class FixtureProvider:
    mode = "fixture"
    def __init__(self):
        self.rows = json.loads(Path(__file__).with_name("fixtures.json").read_text())

    async def search(self, args):
        if args.get("cursor"):
            fail("INVALID_ARGUMENT", "Fixtures usam somente paginação numérica.")
        rows = [r.copy() for r in self.rows if args["keyword"].casefold() in r["name"].casefold()]
        if args.get("shop_id"):
            rows = [r for r in rows if r["shop_id"] == args["shop_id"]]
        if args.get("category_id"):
            rows = [r for r in rows if args["category_id"] in r.get("category_ids", [])]
        if args.get("is_ams_offer"):
            rows = [r for r in rows if Decimal(r.get("seller_commission_rate") or "0") > 0]
        if args.get("is_key_seller"):
            rows = []  # Fixtures have no key-seller evidence.
        sort_type = args.get("sort_type", 1)
        if sort_type in (2, 3, 4, 5):
            key = {2: "sales", 3: "price_max_brl", 4: "price_min_brl", 5: "commission_rate_fraction"}[sort_type]
            rows.sort(key=lambda r: Decimal(str(r[key])), reverse=sort_type != 4)
        start = (args["page"] - 1) * args["limit"]
        observed = utc_now()
        selection = rows[start:start + args["limit"]]
        for r in selection:
            r["observed_at"] = observed
        has_next = start + args["limit"] < len(rows)
        return {"offers": selection, "observed_at": observed,
                "pagination": {"page": args["page"], "limit": args["limit"], "has_next_page": has_next,
                               "next_page": args["page"] + 1 if has_next else None, "next_cursor": None}}

    async def get(self, args):
        row = next((r.copy() for r in self.rows if r["item_id"] == args["item_id"] and r["shop_id"] == args["shop_id"]), None)
        if row is None:
            fail("NOT_FOUND", "Produto não encontrado nas fixtures sintéticas.")
        row["observed_at"] = utc_now()
        return {"offer": row}

    async def link(self, args):
        fail("FIXTURE_NO_LINK", "Modo sintético não gera links de afiliado. API real precisa ser validada.")


class Service:
    def __init__(self, provider, account_reference, contract):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account_reference):
            fail("CONFIGURATION", "Referência local de conta inválida.")
        self.provider, self.account, self.contract = provider, account_reference, contract
        self.history_path = os.getenv("SHOPEE_HISTORY_DB", "")
        self.report_lock = asyncio.Lock()
        self.report_starts = {}
        self.used_cursors = {}

    async def call(self, name, args):
        if name not in self.contract:
            fail("UNKNOWN_TOOL", "Ferramenta inexistente.")
        validate(self.contract[name]["inputSchema"], args)
        if name == "affiliate_status":
            data = {"api_authenticated_in_this_call": False,
                    "account_binding": "local_configuration_not_api_identity",
                    "official_schema_verified": self.provider.profile.confirmed if isinstance(self.provider, LiveProvider) else False,
                    "live_acceptance_required": True,
                    "tools_available": list(self.contract),
                    "history_enabled": bool(self.history_path)}
        elif name not in {"search_offers", "get_offer", "generate_affiliate_link"}:
            from .features import call_feature
            data = await call_feature(self, name, dict(args))
        else:
            args = dict(args)
            if name == "generate_affiliate_link":
                if args.pop("expected_account_reference") != self.account:
                    fail("ACCOUNT_MISMATCH", "Conta esperada difere do contexto deste servidor.")
                data = await self.provider.link(args)
            elif name == "search_offers":
                args.setdefault("page", 1)
                args.setdefault("limit", 10)
                args.setdefault("sort_type", 1)
                data = await self.provider.search(args)
            else:
                data = await self.provider.get(args)
        result = {"mode": self.provider.mode, "synthetic": self.provider.mode == "fixture",
                  "account_reference": self.account, "data": data}
        validate(self.contract[name]["outputSchema"], result, "UPSTREAM_SHAPE")
        return result


def load_service(mode):
    contract = json.loads(Path(__file__).with_name("tools.json").read_text())
    if mode == "fixture":
        return Service(FixtureProvider(), "synthetic-account", contract)
    profile_path = os.getenv("SHOPEE_VERIFIED_PROFILE", "")
    if not profile_path:
        fail("SCHEMA_UNVERIFIED", "Configure perfil oficial verificado antes do modo live.")
    try:
        profile = Profile(json.loads(Path(profile_path).read_text()))
    except (OSError, ValueError):
        fail("CONFIGURATION", "Perfil oficial não pôde ser carregado.")
    profile.require_verified()
    credentials = Credentials.from_env()
    account = os.getenv("SHOPEE_ACCOUNT_REFERENCE", "")
    return Service(LiveProvider(profile, SignedClient(profile, credentials)), account, contract)
