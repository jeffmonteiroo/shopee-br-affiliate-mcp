# Shopee Affiliate MCP — 0.3.0

Servidor MCP em Python para a Open API de Afiliados Shopee Brasil. Expõe 17 ferramentas por stdio ou Streamable HTTP com OAuth e usa consultas GraphQL assinadas com App ID e Secret da conta configurada.

O modo padrão é `fixture`: produtos sintéticos e nenhuma chamada externa. O modo `live` exige credenciais e o perfil administrativo oficial. Os contratos foram conferidos no portal brasileiro em 2026-10-01. As novas operações foram testadas com respostas simuladas; a aceitação real depende das permissões da conta.

## Uso público e privacidade

Projeto independente, sem vínculo, endosso ou suporte oficial da Shopee. Licença [MIT](LICENSE). Cada instalação precisa das próprias credenciais e do acesso à Open API de afiliados; o repositório não fornece uma conta nem um serviço compartilhado. A licença do código não concede direitos sobre dados, marcas ou serviços da Shopee.

O modo live pode devolver links com atribuição, identificadores de pedidos, subIDs e valores de comissão. Esses resultados e os exports devem ser tratados como dados privados da conta. Revise conversas, logs e arquivos antes de compartilhá-los. O histórico opcional fica no SQLite local. Publicar o código não publica esses dados, mas o cliente MCP pode guardar as respostas. Veja [orientações de segurança](SECURITY.md).

Esta versão é inicial: as novas ferramentas passaram em testes simulados e ainda precisam de validação com a API real. HTTP permanece experimental e local; não exponha esse transporte na internet.

## Ferramentas

| Ferramenta | Função |
|---|---|
| `affiliate_status` | Modo, referência local da conta, ferramentas e histórico habilitado; não autentica sozinho |
| `search_offers` | Produtos por palavra-chave, loja, categoria, AMS/key seller e ordenação; imagens, desconto, categorias e componentes de comissão |
| `get_offer` | Consulta atual do produto por item/shop IDs |
| `search_shop_offers` | Ofertas de lojas, tipo de loja, comissão e faixa de orçamento restante |
| `search_campaign_offers` | Campanhas Shopee, categoria/coleção, comissão e período |
| `list_product_feeds` | Catálogos oficiais FULL/DELTA |
| `get_product_feed` | Página de catálogo por datafeed ID e offset; colunas JSON preservadas |
| `generate_affiliate_link` | Link oficial com até cinco subIDs ordenados e conta esperada |
| `generate_affiliate_links_batch` | Até 20 links; valida tudo antes de enviar e para no primeiro erro |
| `parse_product_url` | Extrai IDs de URLs de produto e gera URL canônica; sem acesso à rede |
| `resolve_product_url` | Resolve link curto, validando cada destino antes de acessá-lo |
| `get_conversion_report` | Conversões e comissões reportadas ainda não validadas |
| `get_validated_report` | Relatório validado por validation ID obtido no faturamento |
| `summarize_report` | Resumo por subID bruto, campanha, dia UTC, produto ou loja |
| `export_data` | CSV/JSON dos registros fornecidos; CSV neutraliza fórmulas |
| `observe_offer` | Coleta e grava uma observação de produto no histórico opcional |
| `get_offer_history` | Histórico local separado por conta, modo, item e loja |

## Conectar pelo ChatGPT ou Hermes

O transporte `oauth-http` oferece uma única tela com App ID e App Secret. Não exige cadastro, senha adicional ou banco de credenciais. Valida o acesso à Shopee antes de autorizar o cliente. As credenciais e sessões ficam somente na memória por até 24 horas; o servidor entrega tokens próprios ao cliente MCP.

Hospede atrás de HTTPS na VPS e configure `MCP_PUBLIC_URL` e `SHOPEE_VERIFIED_PROFILE`. Cada conexão usa sua própria conta. Conexões com as mesmas credenciais compartilham o cliente e os controles locais. Histórico SQLite fica desabilitado neste transporte.

Veja o [guia de conexão remota](docs/REMOTE.md), o [Compose](compose.remote.yaml) e o [exemplo Hermes com OAuth](examples/hermes.remote.yaml). Esta integração é experimental e passou em testes simulados; a conexão real pelo ChatGPT/Hermes e a VPS ainda precisam de aceitação.

## Instalação

Python 3.11+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e .
```

`requirements.lock` fixa o conjunto de dependências testado. Nenhum segredo deve estar no código, no Git ou nos argumentos de ferramentas.

## Testar localmente

```sh
.venv/bin/python local_test.py --fixture --extended
.venv/bin/python local_test.py --extended
```

O segundo comando pede App ID e App Secret com entrada oculta no Terminal e mantém os valores somente em memória. Verifica initialize/list/status, pesquisa/detalhe de produto, ofertas de lojas, campanhas e lista de feeds. Não gera links nem consulta relatórios financeiros automaticamente. Veja [teste local](docs/LOCAL-TEST.md).

Para iniciar um servidor stdio, o cliente MCP deve executar:

```sh
.venv/bin/python run.py --mode live
```

O processo espera mensagens MCP e não mostra um menu. Ele recebe:

| Variável | Uso |
|---|---|
| `SHOPEE_APP_ID` | App ID da Open API de afiliados |
| `SHOPEE_APP_SECRET` | Secret da mesma aplicação |
| `SHOPEE_ACCOUNT_REFERENCE` | Rótulo local, ASCII alfanumérico/underscore/hífen, até 64 caracteres |
| `SHOPEE_VERIFIED_PROFILE` | Caminho absoluto de `examples/profile.official.json` |
| `SHOPEE_HISTORY_DB` | Opcional: caminho absoluto do SQLite de observações |

O servidor não carrega `.env` automaticamente. O arquivo `.env.example` contém somente nomes e caminhos de exemplo. Injete segredos pelo ambiente protegido do processo. Confirme no painel que a aplicação está associada à conta correta; o rótulo local não comprova titularidade.

Modelos: [cliente MCP](examples/mcp.live.json), [Hermes](examples/hermes.live.yaml). Substitua os caminhos pelo diretório de instalação e disponibilize as credenciais ao processo.

## Relatórios e precisão

Use timestamps Unix em segundos para `purchase_time_start` e `purchase_time_end`. `get_validated_report` recebe `validation_id` do painel. `max_pages` controla a paginação automática (1 por padrão, até 10); `limit` aceita até 500 registros. `complete=false` significa que o retorno cobre apenas parte do relatório. `next_cursor` deve ser usado em até 30 segundos e uma única vez. Consultas de relatórios não recebem retry automático; consultas iniciais sem cursor exigem intervalo maior que 30 segundos por tipo de relatório/processo.

Exemplo de argumentos para `summarize_report`:

```json
{
  "purchase_time_start": 1790812800,
  "purchase_time_end": 1790899199,
  "group_by": "utm_content",
  "limit": 100,
  "max_pages": 5
}
```

SubID é preservado como `utm_content` bruto, sem presumir o separador entre slots. Resumos por produto/loja usam comissão dos itens, sem distribuir arbitrariamente a comissão líquida da conversão. Valores ausentes têm contadores explícitos. Comissão validada não comprova depósito recebido. `clickTime` representa o clique associado a uma conversão; não fornece todos os cliques da campanha.

IDs são strings e valores monetários são strings decimais. O feed preserva números JSON como strings para não perder precisão. Nos relatórios, ajustes monetários negativos são preservados. BRL é inferido do mercado brasileiro.

## Histórico e exportação

Configure `SHOPEE_HISTORY_DB` para habilitar as ferramentas de histórico. Somente `observe_offer` grava uma nova observação. Esse histórico começa quando você inicia a coleta; não recupera preços antigos anteriores a ela.

`export_data` recebe uma lista `rows` com até 500 objetos e `format: "csv"` ou `"json"`. Retorna o conteúdo ao cliente sem aceitar caminhos de arquivo. O cliente pode salvar esse conteúdo como um artefato. Dados exportados têm origem `caller_supplied_data`.

## VPS

Veja [instalação na VPS](docs/VPS.md). Para Hermes na mesma VPS, stdio dispensa porta pública. O Dockerfile roda como usuário sem privilégios e inicia em fixture por padrão. A CI valida o build Docker e initialize/list/status MCP dentro do container em fixture. A configuração HTTPS e o fluxo live ainda precisam de teste no destino.

O transporte `private-http` permanece experimental, restrito ao loopback e protegido por um token separado. Para conexão remota, use `oauth-http` atrás de HTTPS conforme o [guia](docs/REMOTE.md).

## Verificação

```sh
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -v
```

CI no GitHub testa Python 3.11 e 3.12. A verificação local passou em 64 testes, incluindo MCP stdio real, assinaturas, precisão, relatórios paginados, batch com resultado incerto, redirecionamentos e isolamento do histórico. O teste HTTP em memória ainda registra avisos de encerramento do SDK; detalhes em [VERIFICATION.md](docs/VERIFICATION.md).

Limites atuais: sem estoque/frete/cupons/avaliações textuais, publicação em redes sociais, compras, administração de vendedor ou métricas de todos os cliques. O escopo é a API de afiliados disponível à conta.

## Fontes

Implementação própria baseada na documentação oficial brasileira: [produtos](https://affiliate.shopee.com.br/open_api/list?type=product_offer), [lojas](https://affiliate.shopee.com.br/open_api/list?type=brand_offer), [campanhas](https://affiliate.shopee.com.br/open_api/list?type=shopee_offer), [feeds](https://affiliate.shopee.com.br/open_api/list?type=product_feed_offer), [conversões](https://affiliate.shopee.com.br/open_api/list?type=conversion_report), [relatórios validados](https://affiliate.shopee.com.br/open_api/list?type=validation_report). Veja [contratos e políticas locais](docs/OFFICIAL-CONTRACT.md).
