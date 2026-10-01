# Verificação — 0.2.0, 2026-10-01

Ambiente local: macOS, Python 3.11.4. Dependências diretas e transitivas estão fixadas em `requirements.lock`. `pip check` passou.

50 testes locais passaram. Há testes de initialize/list/call por subprocesso stdio real, contrato das 17 ferramentas, assinatura dos bytes enviados, IDs acima de 2^53, filtros e metadados de produto, lojas/campanhas, feeds FULL/DELTA, colunas JSON precisas, paginação de relatórios, cursores não repetidos, intervalo inicial, totais decimais, ausência de valores, ajustes negativos, mutações interrompidas após erro, proteção de redirecionamentos, CSV e isolamento do SQLite por conta/modo.

O smoke test `local_test.py --fixture --extended` passou. Documentação oficial foi lida em sessão autenticada do portal brasileiro, sem copiar credenciais. Há um relato de teste live bem-sucedido da versão anterior, sem resultados reproduzíveis incluídos no repositório; isso não valida as novas operações.

As novas operações foram testadas com HTTPX MockTransport e credenciais sintéticas. Ainda precisam de aceitação real na conta: ofertas enriquecidas, lojas/campanhas, feeds, conversões, relatórios validados e geração em lote. Não foram executados testes de integração com a API real durante esta ampliação.

O SDK MCP 1.21.1 registra `anyio.ClosedResourceError` no encerramento de dois roteadores do teste HTTP em memória. As respostas verificadas passam. Os avisos não foram ocultados; stdio passa sem esse problema. Transporte HTTP continua privado/experimental.

A CI do GitHub testa instalação em Linux com Python 3.11/3.12. O Dockerfile não foi executado localmente porque não há daemon Docker disponível. VPS, cliente Hermes no destino, gateway remoto, OAuth, quota compartilhada e atribuição/pagamento reais permanecem sem validação operacional.
