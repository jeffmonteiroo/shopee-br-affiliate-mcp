"""Affiliate operations checked against the Brazilian portal; local helpers use stdlib."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .core import (
    SafeError,
    decimal_string,
    fail,
    path_get,
    utc_now,
    valid_url,
    validate,
    PRODUCT_HOSTS,
)


def product_identity(url):
    valid_url(url, PRODUCT_HOSTS)
    parsed = urlsplit(url)
    match = re.search(r"^/product/([0-9]+)/([0-9]+)(?:/|$)", parsed.path)
    if not match:
        match = re.search(r"-i\.([0-9]+)\.([0-9]+)(?:/|$)", parsed.path)
    query = parse_qs(parsed.query)
    if match:
        shop, item = match.groups()
    elif len(query.get("shopid", [])) == len(query.get("itemid", [])) == 1:
        shop, item = query["shopid"][0], query["itemid"][0]
    else:
        fail("INVALID_URL", "URL não contém IDs de produto reconhecíveis.")
    if any(
        not re.fullmatch(r"[0-9]{1,20}", value)
        or not 0 < int(value) <= 9223372036854775807
        for value in (shop, item)
    ):
        fail("INVALID_URL", "IDs na URL fora da faixa suportada.")
    return {
        "shop_id": shop,
        "item_id": item,
        "product_url": f"https://shopee.com.br/product/{shop}/{item}",
    }


async def resolve_url(url, *, transport=None):
    # Exact host allowlist + no proxy + validate every redirect before sending it.
    hosts = PRODUCT_HOSTS | {"s.shopee.com.br", "shope.ee"}
    original = url
    async with httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(8, connect=3),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for _ in range(6):
            valid_url(url, hosts)
            try:
                async with client.stream(
                    "GET", url, headers={"User-Agent": "ShopeeAffiliateMCP/0.2"}
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            fail("UPSTREAM_SHAPE", "Redirecionamento sem destino.")
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        fail("UPSTREAM_HTTP", "Não foi possível resolver a URL Shopee.")
                    return {
                        "origin_url": original,
                        "resolved_url": url,
                        **product_identity(url),
                    }
            except (httpx.TimeoutException, httpx.NetworkError):
                fail("UPSTREAM_TIMEOUT", "Resolução do link não concluída.")
    fail("INVALID_URL", "Link excedeu o limite de redirecionamentos.")


def identifier(value):
    if value is None:
        return None
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,20}", str(value)):
        fail("UPSTREAM_SHAPE", "Identificador inválido na resposta.")
    return str(value)


def normalized_row(node, fields, money=(), ids=(), signed_money=False):
    if not isinstance(node, dict):
        fail("UPSTREAM_SHAPE", "Registro inválido na resposta.")
    result = {}
    for output, source in fields.items():
        value = path_get(node, source)
        if output in money:
            if signed_money and value is not None:
                try:
                    amount = Decimal(str(value))
                    if not amount.is_finite():
                        raise InvalidOperation
                    value = format(amount, "f")
                except (InvalidOperation, ValueError):
                    fail("UPSTREAM_SHAPE", "Valor monetário inválido no relatório.")
            else:
                value = decimal_string(value)
        elif output in ids:
            value = identifier(value)
        elif isinstance(value, str):
            value = value[:4000]
        result[output] = value
    return result


async def page_offers(service, operation, args):
    args.setdefault("keyword", "")
    args.setdefault("sort_type", 2)
    args.setdefault("page", 1)
    args.setdefault("limit", 20)
    provider = service.provider
    if provider.mode == "fixture":
        return {
            "offers": [],
            "pagination": {
                "page": args["page"],
                "limit": args["limit"],
                "has_next_page": False,
                "next_page": None,
            },
            "observed_at": utc_now(),
        }
    op = provider.profile.operation(operation)
    raw = await provider.client.execute(op, args, read_only=True)
    nodes, page = path_get(raw, "nodes"), path_get(raw, "pageInfo")
    if (
        not isinstance(nodes, list)
        or len(nodes) > args["limit"]
        or not isinstance(page, dict)
    ):
        fail("UPSTREAM_SHAPE", "Lista ou paginação inválida.")
    if (
        page.get("page") != args["page"]
        or page.get("limit") != args["limit"]
        or type(page.get("hasNextPage")) is not bool
    ):
        fail("UPSTREAM_SHAPE", "Metadados de paginação inválidos.")
    offers = [
        normalized_row(
            n,
            op["fields"],
            money=("commission_rate",),
            ids=("shop_id", "category_id", "collection_id"),
        )
        for n in nodes
    ]
    for offer in offers:
        if (
            offer.get("commission_rate") is not None
            and Decimal(offer["commission_rate"]) > 1
        ):
            fail("UPSTREAM_SHAPE", "Taxa de comissão inválida.")
        if offer.get("offer_url"):
            valid_url(
                offer["offer_url"],
                set(provider.profile.data["affiliate_link_hosts"]) | PRODUCT_HOSTS,
            )
    return {
        "offers": offers,
        "pagination": {
            "page": page["page"],
            "limit": page["limit"],
            "has_next_page": page["hasNextPage"],
            "next_page": page["page"] + 1 if page["hasNextPage"] else None,
        },
        "observed_at": utc_now(),
    }


REPORT_FIELDS = {
    "conversion_id": "conversionId",
    "purchase_time": "purchaseTime",
    "click_time": "clickTime",
    "shopee_commission_capped": "shopeeCommissionCapped",
    "seller_commission": "sellerCommission",
    "total_commission": "totalCommission",
    "net_commission": "netCommission",
    "mcn_management_fee": "mcnManagementFee",
    "utm_content": "utmContent",
    "campaign_type": "campaignType",
    "device": "device",
}
ITEM_FIELDS = {
    "shop_id": "shopId",
    "shop_name": "shopName",
    "item_id": "itemId",
    "item_name": "itemName",
    "actual_amount": "actualAmount",
    "quantity": "qty",
    "total_commission": "itemTotalCommission",
    "seller_commission": "itemSellerCommission",
    "shopee_commission_capped": "itemShopeeCommissionCapped",
    "status": "displayItemStatus",
    "fraud_status": "fraudStatus",
    "campaign_type": "campaignType",
}
REPORT_MONEY = {
    "shopee_commission_capped",
    "seller_commission",
    "total_commission",
    "net_commission",
    "mcn_management_fee",
}


def report_record(node, kind):
    result = normalized_row(
        node,
        REPORT_FIELDS,
        money=REPORT_MONEY,
        ids=("conversion_id",),
        signed_money=True,
    )
    if not result["conversion_id"]:
        fail("UPSTREAM_SHAPE", "Conversão sem identificador.")
    if (
        type(result["purchase_time"]) is not int
        or not 0 <= result["purchase_time"] <= 2147483647
    ):
        fail("UPSTREAM_SHAPE", "Horário de compra inválido no relatório.")
    orders = path_get(node, "orders")
    if not isinstance(orders, list):
        fail("UPSTREAM_SHAPE", "Lista de pedidos inválida.")
    result["orders"] = []
    for order in orders:
        entry = normalized_row(
            order, {"order_id": "orderId", "order_status": "orderStatus"}
        )
        items = path_get(order, "items")
        if not isinstance(items, list):
            fail("UPSTREAM_SHAPE", "Lista de itens inválida.")
        entry["items"] = [
            normalized_row(
                item,
                ITEM_FIELDS,
                money=REPORT_MONEY | {"actual_amount"},
                ids=("shop_id", "item_id"),
                signed_money=True,
            )
            for item in items
        ]
        result["orders"].append(entry)
    result["commission_status"] = (
        "validated" if kind == "validated" else "reported_unvalidated"
    )
    return result


async def reports(service, kind, args):
    args.setdefault("limit", 100)
    max_pages = args.pop("max_pages", 1)
    if kind == "conversion":
        start, end = args["purchase_time_start"], args["purchase_time_end"]
        if start > end or end - start > 90 * 86400:
            fail(
                "INVALID_ARGUMENT",
                "Período inválido; limite local de 90 dias por consulta.",
            )
    if service.provider.mode == "fixture":
        return {
            "records": [],
            "report_type": kind,
            "commission_status": "synthetic",
            "pagination": {
                "pages_fetched": 1,
                "has_next_page": False,
                "next_cursor": None,
                "cursor_ttl_seconds": 30,
            },
            "complete": True,
            "observed_at": utc_now(),
        }
    provider = service.provider
    op = provider.profile.operation(kind)
    records, seen = [], set()
    async with service.report_lock:
        if not args.get("cursor"):
            last = service.report_starts.get(kind)
            if last is not None and time.monotonic() - last <= 30:
                fail(
                    "LOCAL_REPORT_INTERVAL",
                    "Aguarde mais de 30 segundos entre relatórios sem cursor.",
                )
            service.report_starts[kind] = time.monotonic()
        for page_number in range(1, max_pages + 1):
            cursor = args.get("cursor")
            if cursor:
                now = time.monotonic()
                service.used_cursors = {
                    key: expiry
                    for key, expiry in service.used_cursors.items()
                    if expiry > now
                }
                digest = hashlib.sha256(cursor.encode()).hexdigest()
                if digest in service.used_cursors:
                    fail(
                        "CURSOR_ALREADY_USED",
                        "Cursor de relatório já consumido; inicie outra consulta após o intervalo.",
                    )
                service.used_cursors[digest] = now + 60
            raw = await provider.client.execute(op, args, read_only=True)
            nodes, page = path_get(raw, "nodes"), path_get(raw, "pageInfo")
            if (
                not isinstance(nodes, list)
                or len(nodes) > args["limit"]
                or not isinstance(page, dict)
            ):
                fail("UPSTREAM_SHAPE", "Lista ou paginação do relatório inválida.")
            has_next, next_cursor = page.get("hasNextPage"), page.get("scrollId")
            if type(has_next) is not bool or page.get("limit") != args["limit"]:
                fail(
                    "UPSTREAM_SHAPE",
                    "Paginação do relatório incompatível com o pedido.",
                )
            if has_next and (
                not isinstance(next_cursor, str)
                or not next_cursor
                or len(next_cursor) > 4096
            ):
                fail("UPSTREAM_SHAPE", "Relatório incompleto sem cursor válido.")
            for node in nodes:
                record = report_record(node, kind)
                if record["conversion_id"] in seen:
                    fail(
                        "UPSTREAM_SHAPE",
                        "Conversão duplicada entre páginas; totais não calculados.",
                    )
                seen.add(record["conversion_id"])
                records.append(record)
            if not has_next:
                break
            args["cursor"] = next_cursor
    return {
        "records": records,
        "report_type": kind,
        "commission_status": "validated"
        if kind == "validated"
        else "reported_unvalidated",
        "pagination": {
            "pages_fetched": page_number,
            "has_next_page": has_next,
            "next_cursor": next_cursor if has_next else None,
            "cursor_ttl_seconds": 30,
        },
        "complete": not has_next,
        "observed_at": utc_now(),
    }


def summary(report, group_by):
    groups = defaultdict(
        lambda: {
            "conversions": set(),
            "total": Decimal(0),
            "net": Decimal(0),
            "missing_total": 0,
            "missing_net": 0,
        }
    )
    for record in report["records"]:
        entries = (
            [item for order in record["orders"] for item in order["items"]]
            if group_by in {"item_id", "shop_id"}
            else [record]
        )
        for entry in entries:
            if group_by == "day":
                key = (
                    datetime.fromtimestamp(record["purchase_time"], timezone.utc)
                    .date()
                    .isoformat()
                )
            else:
                key = entry.get(group_by) or "not_informed"
            group = groups[key]
            group["conversions"].add(record["conversion_id"])
            for field, label in (
                ("total_commission", "total"),
                ("net_commission", "net"),
            ):
                if entry.get(field) is None:
                    group["missing_" + label] += 1
                else:
                    group[label] += Decimal(entry[field])
    rows = [
        {
            "group": key,
            "conversions": len(value["conversions"]),
            "known_total_commission": format(value["total"], "f"),
            "known_net_commission": format(value["net"], "f"),
            "missing_total_commission": value["missing_total"],
            "missing_net_commission": value["missing_net"],
        }
        for key, value in sorted(groups.items())
    ]
    return {
        "groups": rows,
        "group_by": group_by,
        "day_timezone": "UTC" if group_by == "day" else None,
        "aggregation_scope": "items"
        if group_by in {"item_id", "shop_id"}
        else "conversions",
        "conversions": len(report["records"]),
        "complete": report["complete"],
        "pagination": report["pagination"],
        "commission_status": report["commission_status"],
        "click_metric": "not_available: clickTime represents clicks attached to conversions only",
    }


def export_rows(rows, format_name):
    if len(json.dumps(rows, ensure_ascii=False).encode()) > 1024 * 1024:
        fail("INVALID_ARGUMENT", "Exportação excede 1 MiB.")
    if format_name == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        mime = "application/json"
    else:
        columns = sorted({key for row in rows for key in row})
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)

        def cell(value):
            text = (
                json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else str(value)
                if value is not None
                else ""
            )
            return (
                "'" + text
                if text.lstrip().startswith(("=", "+", "-", "@"))
                or text.startswith(("\t", "\r", "\n"))
                else text
            )

        writer.writerow([cell(c) for c in columns])
        writer.writerows([[cell(row.get(c)) for c in columns] for row in rows])
        content, mime = buffer.getvalue(), "text/csv"
    return {
        "format": format_name,
        "mime_type": mime,
        "content": content,
        "row_count": len(rows),
        "source": "caller_supplied_data",
    }


def history(service, args, offer=None):
    if not service.history_path:
        fail(
            "HISTORY_DISABLED",
            "Configure SHOPEE_HISTORY_DB no ambiente para habilitar histórico local.",
        )
    path = Path(service.history_path).expanduser()
    if not path.is_absolute():
        fail("CONFIGURATION", "SHOPEE_HISTORY_DB deve ser um caminho absoluto.")
    if offer is None and not path.exists():
        return {
            "observations": [],
            "history_scope": "observations_collected_by_this_server",
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, account TEXT, mode TEXT, item TEXT, shop TEXT, observed TEXT, payload TEXT)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS observation_lookup ON observations(account, mode, item, shop, id)"
        )
        if offer is not None:
            db.execute(
                "INSERT INTO observations(account,mode,item,shop,observed,payload) VALUES(?,?,?,?,?,?)",
                (
                    service.account,
                    service.provider.mode,
                    offer["item_id"],
                    offer["shop_id"],
                    offer["observed_at"],
                    json.dumps(offer),
                ),
            )
        records = db.execute(
            "SELECT payload FROM observations WHERE account=? AND mode=? AND item=? AND shop=? ORDER BY id DESC LIMIT ?",
            (
                service.account,
                service.provider.mode,
                args["item_id"],
                args["shop_id"],
                args.get("limit", 20),
            ),
        ).fetchall()
    return {
        "observations": [json.loads(row[0]) for row in records],
        "history_scope": "observations_collected_by_this_server",
    }


async def call_feature(service, name, args):
    provider = service.provider
    if name == "parse_product_url":
        return product_identity(args["url"])
    if name == "resolve_product_url":
        if provider.mode == "fixture":
            fail(
                "FIXTURE_NO_NETWORK", "Resolução remota indisponível em modo sintético."
            )
        try:
            async with asyncio.timeout(30):
                return await resolve_url(args["url"])
        except TimeoutError:
            fail("UPSTREAM_TIMEOUT", "Prazo total da resolução do link excedido.")
    if name in {"search_shop_offers", "search_campaign_offers"}:
        return await page_offers(
            service, "shops" if name == "search_shop_offers" else "campaigns", args
        )
    if name == "list_product_feeds":
        if provider.mode == "fixture":
            return {"feeds": []}
        op = provider.profile.operation("feeds")
        raw = await provider.client.execute(
            op, {"feed_mode": args.get("feed_mode", "FULL")}, read_only=True
        )
        feeds = path_get(raw, "feeds")
        if not isinstance(feeds, list) or len(feeds) > 10000:
            fail("UPSTREAM_SHAPE", "Lista de feeds inválida.")
        return {
            "feeds": [
                normalized_row(n, op["fields"], ids=("total_count",)) for n in feeds
            ]
        }
    if name == "get_product_feed":
        args.setdefault("offset", 0)
        args.setdefault("limit", 100)
        if provider.mode == "fixture":
            return {
                "rows": [],
                "pagination": {
                    "offset": args["offset"],
                    "limit": args["limit"],
                    "total_count": "0",
                    "has_more": False,
                    "next_offset": None,
                },
            }
        op = provider.profile.operation("feed")
        raw = await provider.client.execute(op, args, read_only=True)
        nodes, page = path_get(raw, "rows"), path_get(raw, "pageInfo")
        if (
            not isinstance(nodes, list)
            or len(nodes) > args["limit"]
            or not isinstance(page, dict)
        ):
            fail("UPSTREAM_SHAPE", "Feed ou paginação inválidos.")
        if (
            page.get("offset") != args["offset"]
            or page.get("limit") != args["limit"]
            or type(page.get("hasMore")) is not bool
        ):
            fail("UPSTREAM_SHAPE", "Paginação do feed incompatível.")
        rows = []
        for node in nodes:
            try:
                columns = json.loads(
                    path_get(node, "columns"), parse_int=str, parse_float=str
                )
            except (ValueError, TypeError):
                fail("UPSTREAM_SHAPE", "Colunas do feed não são JSON válido.")
            if not isinstance(columns, dict):
                fail("UPSTREAM_SHAPE", "Colunas do feed não são um objeto.")
            rows.append(
                {"columns": columns, "update_type": path_get(node, "updateType")}
            )
        if page["hasMore"] and not nodes:
            fail("UPSTREAM_SHAPE", "Feed vazio com continuação não permite avançar.")
        return {
            "rows": rows,
            "pagination": {
                "offset": args["offset"],
                "limit": args["limit"],
                "total_count": identifier(page.get("totalCount")),
                "has_more": page["hasMore"],
                "next_offset": args["offset"] + len(rows) if page["hasMore"] else None,
            },
        }
    if name in {"get_conversion_report", "get_validated_report", "summarize_report"}:
        kind = "validated" if name == "get_validated_report" else "conversion"
        group = args.pop("group_by", "utm_content")
        report = await reports(service, kind, args)
        return summary(report, group) if name == "summarize_report" else report
    if name == "generate_affiliate_links_batch":
        if args["expected_account_reference"] != service.account:
            fail(
                "ACCOUNT_MISMATCH", "Conta esperada difere do contexto deste servidor."
            )
        if provider.mode == "fixture":
            fail("FIXTURE_NO_LINK", "Modo sintético não gera links de afiliado.")
        # Validate the entire batch before the first mutation.
        for link in args["links"]:
            validate(
                service.contract["generate_affiliate_link"]["inputSchema"],
                {**link, "expected_account_reference": service.account},
            )
            provider.validate_link(link)
        results = []
        stopped = False
        for index, link in enumerate(args["links"]):
            if stopped:
                results.append({"index": index, "status": "not_attempted"})
                continue
            try:
                results.append(
                    {"index": index, "status": "ok", "data": await provider.link(link)}
                )
            except SafeError as error:
                results.append(
                    {
                        "index": index,
                        "status": "error",
                        "error": {"code": error.code, "message": error.message},
                    }
                )
                stopped = True
        return {"results": results, "stopped_on_error": stopped}
    if name == "export_data":
        return export_rows(args["rows"], args["format"])
    if name in {"observe_offer", "get_offer_history"}:
        if not service.history_path:
            fail(
                "HISTORY_DISABLED",
                "Configure SHOPEE_HISTORY_DB no ambiente para habilitar histórico local.",
            )
        offer = (await provider.get(args))["offer"] if name == "observe_offer" else None
        return history(service, args, offer)
    fail("UNKNOWN_TOOL", "Ferramenta inexistente.")
