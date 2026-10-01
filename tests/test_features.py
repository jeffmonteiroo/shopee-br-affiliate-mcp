import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from shopee_mcp.core import (
    Credentials,
    LiveProvider,
    SafeError,
    Service,
    SignedClient,
    load_service,
    render_query,
)
from shopee_mcp.features import (
    export_rows,
    product_identity,
    resolve_url,
    report_record,
    summary,
)
from support import contract
from test_official_profile import official_node, official_profile, no_sleep


def conversion(cid="9007199254740993", total="0.10", net="0.08"):
    return {
        "conversionId": int(cid),
        "purchaseTime": 1700000000,
        "clickTime": 1699999900,
        "shopeeCommissionCapped": "0.03",
        "sellerCommission": "0.07",
        "totalCommission": total,
        "netCommission": net,
        "mcnManagementFee": "0.02",
        "utmContent": "telegram-outubro",
        "campaignType": "Seller Open Campaign",
        "device": "APP",
        "orders": [
            {
                "orderId": "TEST-ORDER",
                "orderStatus": "PENDING",
                "items": [
                    {
                        "shopId": 800001,
                        "shopName": "Synthetic Shop",
                        "itemId": 9007199254740993,
                        "itemName": "Synthetic item",
                        "actualAmount": "10.00",
                        "qty": 1,
                        "itemTotalCommission": total,
                        "itemSellerCommission": "0.07",
                        "itemShopeeCommissionCapped": "0.03",
                        "displayItemStatus": "PENDING",
                        "fraudStatus": "UNVERIFIED",
                        "campaignType": "Seller Open Campaign",
                    }
                ],
            }
        ],
    }


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()

    def service(self, handler):
        profile = official_profile()
        client = SignedClient(
            profile,
            Credentials("synthetic-app", "synthetic-secret"),
            transport=httpx.MockTransport(handler),
            sleep=no_sleep,
        )
        self.clients.append(client)
        return Service(LiveProvider(profile, client), "test-account", contract())

    async def test_enriched_product_and_filters_reach_api(self):
        def handler(request):
            query = json.loads(request.content)["query"]
            self.assertIn("productCatId:100001", query)
            self.assertIn("shopId:800001", query)
            self.assertIn("isAMSOffer:true", query)
            node = official_node()
            node.update(
                imageUrl="https://cf.shopee.com.br/file/synthetic",
                productCatIds=[100001],
                priceDiscountRate=10,
                shopType=[2],
                sellerCommissionRate="0.03",
                shopeeCommissionRate="0.07",
            )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "productOfferV2": {
                            "nodes": [node],
                            "pageInfo": {"page": 1, "limit": 10, "hasNextPage": False},
                        }
                    }
                },
            )

        response = await self.service(handler).call(
            "search_offers",
            {
                "keyword": "fone",
                "category_id": 100001,
                "shop_id": "800001",
                "is_ams_offer": True,
            },
        )
        offer = response["data"]["offers"][0]
        self.assertEqual(offer["seller_commission_rate"], "0.03")
        self.assertEqual(offer["category_ids"], [100001])

    async def test_shops_and_campaigns_use_different_sort_contracts(self):
        def handler(request):
            query = json.loads(request.content)["query"]
            if "shopOfferV2" in query:
                self.assertIn("shopType:[1,4]", query)
                field = "shopOfferV2"
                node = {
                    "commissionRate": "0.12",
                    "imageUrl": None,
                    "offerLink": "https://shope.ee/test",
                    "originalLink": "https://shopee.com.br/shop/800001",
                    "shopId": 800001,
                    "shopName": "Loja",
                    "ratingStar": "4.8",
                    "shopType": [1, 4],
                    "remainingBudget": 2,
                    "periodStartTime": 1,
                    "periodEndTime": 2,
                }
            else:
                field = "shopeeOfferV2"
                node = {
                    "commissionRate": "0.12",
                    "imageUrl": None,
                    "offerLink": "https://shope.ee/test",
                    "offerName": "Campanha",
                    "offerType": 2,
                    "categoryId": 100001,
                    "collectionId": None,
                    "periodStartTime": 1,
                    "periodEndTime": 2,
                }
            return httpx.Response(
                200,
                json={
                    "data": {
                        field: {
                            "nodes": [node],
                            "pageInfo": {"page": 1, "limit": 20, "hasNextPage": False},
                        }
                    }
                },
            )

        service = self.service(handler)
        shop = await service.call("search_shop_offers", {"shop_types": [1, 4]})
        campaign = await service.call("search_campaign_offers", {})
        self.assertEqual(shop["data"]["offers"][0]["shop_id"], "800001")
        self.assertEqual(campaign["data"]["offers"][0]["category_id"], "100001")
        with self.assertRaises(SafeError):
            await service.call("search_campaign_offers", {"sort_type": 5})

    async def test_feed_enum_and_json_ids_preserve_precision(self):
        def handler(request):
            query = json.loads(request.content)["query"]
            if "listItemFeeds" in query:
                self.assertIn("feedMode:DELTA", query)
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "listItemFeeds": {
                                "feeds": [
                                    {
                                        "datafeedId": "test_DELTA",
                                        "datafeedName": "Synthetic",
                                        "referenceId": "99",
                                        "description": "Test",
                                        "totalCount": 9007199254740993,
                                        "date": "2026-10-01",
                                        "feedMode": "DELTA",
                                    }
                                ]
                            }
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "getItemFeedData": {
                            "rows": [
                                {
                                    "columns": '{"itemId":9007199254740993,"price":0.10}',
                                    "updateType": "UPDATE",
                                }
                            ],
                            "pageInfo": {
                                "offset": 0,
                                "limit": 100,
                                "totalCount": 2,
                                "hasMore": True,
                            },
                        }
                    }
                },
            )

        service = self.service(handler)
        listing = await service.call("list_product_feeds", {"feed_mode": "DELTA"})
        feed = await service.call("get_product_feed", {"datafeed_id": "test_DELTA"})
        self.assertEqual(listing["data"]["feeds"][0]["total_count"], "9007199254740993")
        self.assertEqual(
            feed["data"]["rows"][0]["columns"]["itemId"], "9007199254740993"
        )
        self.assertEqual(feed["data"]["rows"][0]["columns"]["price"], "0.10")
        self.assertEqual(feed["data"]["pagination"]["next_offset"], 1)

    async def test_report_pagination_summary_decimals_and_cursor_reuse(self):
        requests = []

        def handler(request):
            query = json.loads(request.content)["query"]
            requests.append(query)
            more = "scrollId:null" in query
            return httpx.Response(
                200,
                json={
                    "data": {
                        "conversionReport": {
                            "nodes": [
                                conversion(
                                    "9007199254740993" if more else "9007199254740994",
                                    "0.10" if more else "0.20",
                                )
                            ],
                            "pageInfo": {
                                "limit": 100,
                                "hasNextPage": more,
                                "scrollId": "single-use" if more else None,
                            },
                        }
                    }
                },
            )

        service = self.service(handler)
        args = {
            "purchase_time_start": 1699999000,
            "purchase_time_end": 1700001000,
            "max_pages": 2,
        }
        result = await service.call("summarize_report", args)
        self.assertEqual(result["data"]["groups"][0]["known_total_commission"], "0.30")
        self.assertTrue(result["data"]["complete"])
        self.assertEqual(len(requests), 2)
        with self.assertRaises(SafeError) as error:
            await service.call(
                "get_conversion_report", {**args, "cursor": "single-use"}
            )
        self.assertEqual(error.exception.code, "CURSOR_ALREADY_USED")
        with self.assertRaises(SafeError) as error:
            await service.call("get_conversion_report", args)
        self.assertEqual(error.exception.code, "LOCAL_REPORT_INTERVAL")

    async def test_partial_report_and_missing_values_are_explicit(self):
        service = self.service(
            lambda request: httpx.Response(
                200,
                json={
                    "data": {
                        "conversionReport": {
                            "nodes": [conversion(net=None)],
                            "pageInfo": {
                                "limit": 100,
                                "hasNextPage": True,
                                "scrollId": "next-page",
                            },
                        }
                    }
                },
            )
        )
        response = await service.call(
            "summarize_report",
            {"purchase_time_start": 1699999000, "purchase_time_end": 1700001000},
        )
        self.assertFalse(response["data"]["complete"])
        self.assertEqual(response["data"]["groups"][0]["missing_net_commission"], 1)

    async def test_cursor_timeout_never_retried(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic", request=request)

        service = self.service(handler)
        with self.assertRaises(SafeError) as error:
            await service.call(
                "get_validated_report",
                {"validation_id": "9007199254740993", "cursor": "once"},
            )
        self.assertEqual(error.exception.code, "UPSTREAM_TIMEOUT")
        self.assertEqual(len(calls), 1)

    async def test_report_invalid_range_rejected_before_network(self):
        service = self.service(lambda request: self.fail("must not call API"))
        for start, end in [(20, 10), (0, 91 * 86400)]:
            with self.assertRaises(SafeError):
                await service.call(
                    "get_conversion_report",
                    {"purchase_time_start": start, "purchase_time_end": end},
                )

    async def test_validated_adjustments_preserve_negative_amounts(self):
        def handler(request):
            self.assertIn(
                "validationId:9007199254740993", json.loads(request.content)["query"]
            )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "validatedReport": {
                            "nodes": [conversion(total="-0.10", net="-0.08")],
                            "pageInfo": {
                                "limit": 100,
                                "hasNextPage": False,
                                "scrollId": None,
                            },
                        }
                    }
                },
            )

        response = await self.service(handler).call(
            "get_validated_report", {"validation_id": "9007199254740993"}
        )
        self.assertEqual(response["data"]["records"][0]["total_commission"], "-0.10")
        self.assertEqual(response["data"]["commission_status"], "validated")

    async def test_batch_preflight_and_stop_after_uncertain_result(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(503)

        service = self.service(handler)
        good = {
            "origin_url": "https://shopee.com.br/product/1/2",
            "sub_ids": ["telegram"],
        }
        with self.assertRaises(SafeError):
            await service.call(
                "generate_affiliate_links_batch",
                {
                    "expected_account_reference": "test-account",
                    "links": [good, {**good, "origin_url": "https://evil.invalid"}],
                },
            )
        self.assertEqual(len(calls), 0)
        response = await service.call(
            "generate_affiliate_links_batch",
            {"expected_account_reference": "test-account", "links": [good, good]},
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            response["data"]["results"][0]["error"]["code"], "LINK_OUTCOME_UNKNOWN"
        )
        self.assertEqual(response["data"]["results"][1]["status"], "not_attempted")

    async def test_redirect_allowlist_before_second_request(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

        with self.assertRaises(SafeError):
            await resolve_url(
                "https://shope.ee/test", transport=httpx.MockTransport(handler)
            )
        self.assertEqual(calls, ["https://shope.ee/test"])

    async def test_history_partitioned_by_mode_and_account(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                "os.environ",
                {"SHOPEE_HISTORY_DB": str(Path(directory) / "history.sqlite3")},
            ),
        ):
            first = load_service("fixture")
            args = {"item_id": "900001", "shop_id": "800001"}
            response = await first.call("observe_offer", args)
            self.assertEqual(len(response["data"]["observations"]), 1)
            first.account = "another-account"
            self.assertEqual(
                (await first.call("get_offer_history", args))["data"]["observations"],
                [],
            )
            first.account = "synthetic-account"
            first.provider.mode = "live"
            self.assertEqual(
                (await first.call("get_offer_history", args))["data"]["observations"],
                [],
            )

    async def test_new_tools_usable_through_stdio(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import sys
        from support import ROOT

        async with stdio_client(
            StdioServerParameters(
                command=sys.executable, args=[str(ROOT / "run.py"), "--mode", "fixture"]
            )
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                parsed = await session.call_tool(
                    "parse_product_url",
                    {"url": "https://shopee.com.br/name-i.800001.9007199254740993"},
                )
                self.assertFalse(parsed.isError)
                self.assertEqual(
                    parsed.structuredContent["data"]["item_id"], "9007199254740993"
                )
                exported = await session.call_tool(
                    "export_data", {"format": "csv", "rows": [{"name": "=danger"}]}
                )
                self.assertFalse(exported.isError)
                self.assertIn("'=danger", exported.structuredContent["data"]["content"])


class LocalHelperTests(unittest.TestCase):
    def test_item_summary_uses_item_commission_and_counts_conversion_once(self):
        node = conversion(total="99.00")
        first = node["orders"][0]["items"][0]
        first["itemTotalCommission"] = "0.10"
        node["orders"][0]["items"].append(
            {**first, "itemId": 9007199254740994, "itemTotalCommission": "0.20"}
        )
        report = {
            "records": [report_record(node, "conversion")],
            "complete": True,
            "pagination": {},
            "commission_status": "reported_unvalidated",
        }
        result = summary(report, "shop_id")
        self.assertEqual(result["groups"][0]["known_total_commission"], "0.30")
        self.assertEqual(result["groups"][0]["conversions"], 1)
        self.assertEqual(result["groups"][0]["missing_net_commission"], 2)
        day = summary(report, "day")
        self.assertEqual(day["groups"][0]["group"], "2023-11-14")
        self.assertEqual(day["day_timezone"], "UTC")

    def test_url_parsing_and_bad_hosts(self):
        for url in [
            "https://shopee.com.br/product/1/9007199254740993",
            "https://shopee.com.br/produto-i.1.9007199254740993",
            "https://shopee.com.br/item?shopid=1&itemid=9007199254740993",
        ]:
            self.assertEqual(product_identity(url)["item_id"], "9007199254740993")
        for url in [
            "https://shopee.com.br.evil.invalid/product/1/2",
            "https://user:pass@shopee.com.br/product/1/2",
            "http://shopee.com.br/product/1/2",
            "https://shopee.com.br/product/1/9223372036854775808",
        ]:
            with self.assertRaises(SafeError):
                product_identity(url)

    def test_csv_formulas_and_unicode(self):
        values = ["=SUM(1,2)", " +attack", "-1", "@attack", "\tattack", "café"]
        exported = export_rows([{"=header": v} for v in values], "csv")
        rows = list(csv.reader(io.StringIO(exported["content"])))
        self.assertEqual(rows[0], ["'=header"])
        self.assertTrue(all(row[0].startswith("'") for row in rows[1:6]))
        self.assertEqual(rows[6], ["café"])

    def test_enum_boolean_and_optional_literals(self):
        profile = official_profile()
        self.assertIn(
            "feedMode:FULL",
            render_query(profile.operation("feeds"), {"feed_mode": "FULL"}),
        )
        with self.assertRaises(SafeError):
            render_query(profile.operation("feeds"), {"feed_mode": "FULL){evil}"})
        query = render_query(
            profile.operation("search"),
            {"keyword": "x", "page": 1, "limit": 10, "sort_type": 1},
        )
        self.assertIn("shopId:null", query)
