# Contratos oficiais e políticas locais — 0.2.0

Os contratos abaixo foram lidos no portal brasileiro autenticado em 2026-10-01. Consultar documentação não comprova a execução da API nem as permissões da conta. Implementação própria; os projetos pesquisados foram usados para identificar funcionalidades, sem copiar suas implementações.

| Operação | Documentação | Implementação |
|---|---|---|
| `productOfferV2` | [Produto v2](https://affiliate.shopee.com.br/open_api/list?type=product_offer) | Pesquisa, filtros de loja/categoria/AMS/key seller, detalhe e dados enriquecidos |
| `shopOfferV2` | [Lojas v2](https://affiliate.shopee.com.br/open_api/list?type=brand_offer) | Ofertas de lojas e faixas de orçamento restante |
| `shopeeOfferV2` | [Campanhas v2](https://affiliate.shopee.com.br/open_api/list?type=shopee_offer) | Ofertas Shopee com categoria/coleção |
| `listItemFeeds` | [Lista de feeds](https://affiliate.shopee.com.br/open_api/list?type=product_feed_offer) | Enum FULL/DELTA sem aspas |
| `getItemFeedData` | [Feed](https://affiliate.shopee.com.br/open_api/list?type=product_feed_offer_detail) | datafeedId, offset, limit, rows(columns/updateType), pageInfo |
| `conversionReport` | [Conversões](https://affiliate.shopee.com.br/open_api/list?type=conversion_report) | Período de compra, loja, produto, pedido/status e cursor |
| `validatedReport` | [Validados](https://affiliate.shopee.com.br/open_api/list?type=validation_report) | validationId do faturamento, limite/cursor |
| `generateShortLink` | [Link](https://affiliate.shopee.com.br/open_api/list?type=short_link) | originUrl/subIds e shortLink oficial |

## Transporte e assinatura

[Requisições](https://affiliate.shopee.com.br/open_api/document?type=request_response): POST GraphQL oficial BR com query, variables e operationName; erros GraphQL podem ocorrer em HTTP 200. Não aceitar sucesso parcial com errors.

[Autenticação](https://affiliate.shopee.com.br/open_api/document?type=authentication): SHA256(AppId + timestamp Unix em segundos + corpo JSON exato + Secret), sem separadores. Header singular Credential segue os exemplos finais. O cliente serializa uma vez, assina/transmite os mesmos bytes UTF-8 e mantém verificação TLS. Não usa proxy ambiental nem redirecionamentos na API.

[Overview](https://affiliate.shopee.com.br/open_api/document?type=overview): quota de 8.000 chamadas/hora; escopo do bucket não explicitado. Nosso orçamento e espaçamento mínimo de 500 ms são por processo.

## Tipos e dinheiro

Literais são serializados em uma única passagem; strings não viram código GraphQL. Inteiros preservam precisão. Booleanos e enums têm validação específica. Argumentos opcionais ausentes são enviados como null; a aceitação executável desse formato deve ser validada na conta, porque a documentação em tabelas não fornece um SDL completo.

Produtos: comissão é fracionária (`0.0123` = 1,23%), preços/comissão em moeda local. BRL é inferido do mercado e identificado na resposta. Desconto é o percentual informado, sem recalcular um preço antigo presumido. Não usamos campos depreciados.

Relatórios: selecionar somente campos conhecidos, sem dados pessoais de compradores. `totalCommission` é o total da conversão; itens têm `itemTotalCommission`. Não duplicar o total da conversão ao agrupar por produto/loja. `netCommission` inclui os ajustes indicados pelo fornecedor; relatório validado não significa depósito recebido. Valores assinados negativos são preservados para ajustes. `utmContent` fica bruto e `clickTime` não é contagem de todos os cliques.

## Paginação

Produtos/lojas/campanhas usam page/limit/hasNextPage. Feed usa offset/limit/totalCount/hasMore, com máximo documentado de 500. Relatórios usam limit/hasNextPage/scrollId, máximo documentado de 500; cursor de uso único, validade de 30 segundos, intervalo maior que 30 segundos entre consultas sem cursor. Relatórios nunca recebem retry automático. Paginação automática tem orçamento de 1–10 páginas; a resposta indica cobertura parcial.

## Políticas locais

Janela máxima de 90 dias por relatório, 50 ofertas por página, até 20 links por lote, exportação de até 500 registros/1 MiB, limite de resposta da API 2 MiB por chamada e prazo 30 s são políticas locais, exceto os limites explicitamente documentados acima. SubIDs: máximo oficial de cinco; ASCII alfanumérico/underscore/hífen e até 64 caracteres são restrições locais.

Link de saída: host shope.ee conforme exemplo oficial. Resolução de URL usa apenas HTTPS com hosts exatos shopee.com.br, www.shopee.com.br, s.shopee.com.br e shope.ee, valida cada salto antes da requisição e limita redirecionamentos. Não recebe cookies de navegador ou headers arbitrários.

Histórico é opt-in por variável administrativa e só guarda observações de produtos coletadas pelo servidor. Conta/modo são parte da chave de consulta. Exportação retorna conteúdo e não aceita caminho de arquivo.

## Fora do contrato

Estoque, frete, cupons, avaliações textuais, todos os cliques, administração de vendedor, publicação social, compras, OAuth remoto e confirmação de pagamento. listType/matchId e filtros adicionais de relatórios não foram incluídos nesta versão.
