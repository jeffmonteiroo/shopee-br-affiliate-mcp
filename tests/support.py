import json
from pathlib import Path

from shopee_mcp.core import Profile

ROOT = Path(__file__).resolve().parents[1]


def contract():
    return json.loads((ROOT / "src/shopee_mcp/tools.json").read_text())


def profile_data():
    """Synthetic API schema for mock tests. NOT documentation of Shopee operations."""
    fields = {k:k for k in ["item_id", "shop_id", "name", "shop_name", "product_url", "price_min", "price_max", "commission_rate", "commission_amount", "sales", "rating", "period_start", "period_end"]}
    def variables(names):
        return {n:{"name":n,"encoding":"identity"} for n in names}
    return {
        "profile_version":1,"official_docs_verified":True,
        "verification":{"source_url":"https://open-api.affiliate.shopee.com.br/explorer", "checked_at":"TEST-ONLY-NOT-REAL-VERIFICATION", "notes":"Synthetic test schema only; never connect this profile."},
        "endpoint":"https://open-api.affiliate.shopee.com.br/graphql",
        "auth_algorithm":"sha256_app_timestamp_body_secret", "commission_rate_unit":"fraction",
        "affiliate_link_hosts":["affiliate.example.invalid"],
        "sub_ids":{"official_count_verified":True,"max_count":5,"max_length":64,"pattern":"[A-Za-z0-9_-]+"},
        "operations":{
            "search":{"query":"query SyntheticSearch($keyword: String, $page: Int, $limit: Int) { syntheticSearch }", "variables":variables(["keyword","page","limit","cursor","sort_type"]), "result_path":"data.syntheticSearch", "nodes_path":"nodes", "page_info_path":"pageInfo", "fields":fields, "page_fields":{"has_next":"hasNext","page":"page","limit":"limit","cursor":"cursor"}},
            "get":{"query":"query SyntheticGet($item_id: String, $shop_id: String) { syntheticGet }", "variables":variables(["item_id","shop_id"]), "result_path":"data.syntheticGet", "fields":fields},
            "link":{"query":"mutation SyntheticLink($origin_url: String, $sub_ids: [String]) { syntheticLink }", "variables":variables(["origin_url","sub_ids"]), "result_path":"data.syntheticLink", "fields":{"affiliate_url":"link"}}
        }
    }


def profile():
    return Profile(profile_data())


def node():
    return {"item_id":9007199254740993,"shop_id":800001,"name":"Produto sintético é \"especial\"", "shop_name":"Loja fictícia", "product_url":"https://shopee.com.br/product/800001/9007199254740993", "price_min":"10.00", "price_max":"12.00", "commission_rate":"0.12", "commission_amount":"1.20", "sales":22, "rating":"4.5", "period_start":None,"period_end":None}
