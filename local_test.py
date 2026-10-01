"""Teste MCP local; credenciais digitadas ficam somente na memória do processo."""

import argparse
import asyncio
import getpass
import json
import os
import sys
import warnings
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent


async def check(mode, keyword, env, extended=False):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "run.py"), "--mode", mode],
        cwd=str(ROOT),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            expected = {
                "affiliate_status",
                "search_offers",
                "get_offer",
                "generate_affiliate_link",
            }
            if not expected <= {tool.name for tool in listing.tools}:
                raise RuntimeError("Descoberta MCP retornou ferramentas inesperadas.")
            print(f"Conexão MCP OK; {len(listing.tools)} ferramentas disponíveis.")
            for name, arguments in [
                ("affiliate_status", {}),
                ("search_offers", {"keyword": keyword, "page": 1, "limit": 3}),
            ]:
                result = await session.call_tool(name, arguments)
                if result.isError:
                    print(result.content[0].text)
                    return 1
                data = result.structuredContent
                if (
                    not data
                    or data["mode"] != mode
                    or data["synthetic"] != (mode == "fixture")
                ):
                    raise RuntimeError("Resposta MCP com modo inesperado.")
                print(json.dumps(data, ensure_ascii=False, indent=2))
            offers = data["data"]["offers"]
            if offers:
                first = offers[0]
                detail = await session.call_tool(
                    "get_offer",
                    {
                        "item_id": first["item_id"],
                        "shop_id": first["shop_id"],
                    },
                )
                if detail.isError:
                    print(detail.content[0].text)
                    return 1
                offer = detail.structuredContent["data"]["offer"]
                if (offer["item_id"], offer["shop_id"]) != (
                    first["item_id"],
                    first["shop_id"],
                ):
                    raise RuntimeError("Detalhe retornou um produto diferente.")
                print("Consulta de detalhe OK.")
            else:
                print("Consulta aceita; nenhuma oferta encontrada para esse termo.")
            if extended:
                for name in (
                    "search_shop_offers",
                    "search_campaign_offers",
                    "list_product_feeds",
                ):
                    response = await session.call_tool(name, {})
                    print(name + ":")
                    if response.isError:
                        print(response.content[0].text)
                        return 1
                    print(
                        json.dumps(
                            response.structuredContent, ensure_ascii=False, indent=2
                        )
                    )
            print("Teste concluído em modo " + mode + ".")
            return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", action="store_true", help="Testar somente dados sintéticos."
    )
    parser.add_argument("--keyword", default="Luminária")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Testar também ofertas de lojas, campanhas e lista de feeds.",
    )
    args = parser.parse_args()
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("SHOPEE_")
    }
    mode = "fixture" if args.fixture else "live"
    try:
        if mode == "live":
            env["SHOPEE_VERIFIED_PROFILE"] = str(
                ROOT / "examples/profile.official.json"
            )
            env["SHOPEE_ACCOUNT_REFERENCE"] = os.getenv(
                "SHOPEE_ACCOUNT_REFERENCE", "minha-conta"
            )
            # Refuse getpass fallback: a redirected terminal must never echo credentials.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                for key, label in [
                    ("SHOPEE_APP_ID", "App ID Shopee"),
                    ("SHOPEE_APP_SECRET", "App Secret Shopee"),
                ]:
                    env[key] = os.getenv(key) or getpass.getpass(
                        label + " (entrada oculta): "
                    )
                    if not env[key]:
                        print("Credencial vazia; teste cancelado.")
                        return 1
        return asyncio.run(check(mode, args.keyword, env, args.extended))
    except (KeyboardInterrupt, EOFError):
        print("Teste cancelado.")
        return 1
    except getpass.GetPassWarning:
        print(
            "Execute em um terminal interativo para inserir credenciais com entrada oculta."
        )
        return 1
    except Exception:
        print("Falha na conexão ou no contrato MCP. Detalhes sensíveis omitidos.")
        return 1
    finally:
        env.pop("SHOPEE_APP_ID", None)
        env.pop("SHOPEE_APP_SECRET", None)


if __name__ == "__main__":
    raise SystemExit(main())
