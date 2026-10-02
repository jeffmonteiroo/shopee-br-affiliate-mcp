# Verificação — 0.4.0, 2026-10-01

72 testes locais passaram. A ampliação verifica conexão após reinício, conservação
da referência da conta, refresh e revogação persistidos, renovação além dos primeiros
90 dias, expiração por inatividade e reconstrução do cliente Shopee sem consulta de
validação no startup. O armazenamento foi testado para ausência de segredos em
texto puro, permissões 0600, chave incorreta sem sobrescrita e trava de processo.
Nenhuma credencial real foi usada. Ruff passou nos arquivos alterados de Python.

O transporte continua experimental e requer uma réplica/processo. HTTPS no destino,
Coolify, ChatGPT, Hermes e chamadas reais à Shopee ainda precisam ser validados.
O SDK MCP 1.21.1 continua emitindo avisos `anyio.ClosedResourceError` no encerramento
de transportes HTTP stateless; as respostas verificadas passam.

## Verificação anterior — 0.3.0

64 testes locais passaram, sendo 14 novos para o transporte remoto. Cobrem
OAuth discovery/DCR, formulário e cookie de proteção, PKCE, vínculo de
callback/recurso/cliente, rejeição e não exposição de credenciais, códigos
únicos e expirados, refresh rotativo, revogação, expiração absoluta, limpeza
em restart, buscas por um cliente Streamable HTTP real do SDK e chamadas
concorrentes de contas distintas. Conexões com as mesmas credenciais usam o
mesmo serviço e controles. A validação Shopee foi exercitada com MockTransport,
conferindo a assinatura com as credenciais fornecidas e o fechamento do cliente
quando a API recusa acesso. Nenhuma credencial real foi usada nesses testes.

A tela foi inspecionada no Chrome com um servidor local e dados fictícios.
A CI passou em Linux/Python 3.11 e 3.12 e validou o build Docker, além de
initialize/list/status MCP dentro do container em fixture. O endpoint HTTPS,
ChatGPT, Hermes, o fluxo live no container e a VPS ainda exigem teste no destino.
O Dockerfile agora inclui README/LICENSE antes da instalação para satisfazer
os metadados do pacote. O daemon Docker local continua indisponível.

O SDK MCP 1.21.1 ainda registra avisos `anyio.ClosedResourceError` ao encerrar
transportes HTTP stateless; as respostas testadas passam. A integração remota
continua experimental, com uma réplica/processo e credenciais em memória.
Reiniciar o serviço apaga também o cadastro OAuth/DCR do cliente, podendo
exigir remover e recriar a conexão. Não há persistência ou conta de usuário.

## Verificação anterior — 0.2.0

Ambiente local: macOS, Python 3.11.4. Dependências diretas e transitivas estão fixadas em `requirements.lock`. `pip check` passou.

50 testes locais passaram. Há testes de initialize/list/call por subprocesso stdio real, contrato das 17 ferramentas, assinatura dos bytes enviados, IDs acima de 2^53, filtros e metadados de produto, lojas/campanhas, feeds FULL/DELTA, colunas JSON precisas, paginação de relatórios, cursores não repetidos, intervalo inicial, totais decimais, ausência de valores, ajustes negativos, mutações interrompidas após erro, proteção de redirecionamentos, CSV e isolamento do SQLite por conta/modo.

O smoke test `local_test.py --fixture --extended` passou. Documentação oficial foi lida em sessão autenticada do portal brasileiro, sem copiar credenciais. Há um relato de teste live bem-sucedido da versão anterior, sem resultados reproduzíveis incluídos no repositório; isso não valida as novas operações.

As novas operações foram testadas com HTTPX MockTransport e credenciais sintéticas. Ainda precisam de aceitação real na conta: ofertas enriquecidas, lojas/campanhas, feeds, conversões, relatórios validados e geração em lote. Não foram executados testes de integração com a API real durante esta ampliação.

O SDK MCP 1.21.1 registra `anyio.ClosedResourceError` no encerramento de dois roteadores do teste HTTP em memória. As respostas verificadas passam. Os avisos não foram ocultados; stdio passa sem esse problema. Transporte HTTP continua privado/experimental.

A CI do GitHub testa instalação em Linux com Python 3.11/3.12. O Dockerfile não foi executado localmente porque não há daemon Docker disponível. VPS, cliente Hermes no destino, gateway remoto, OAuth, quota compartilhada e atribuição/pagamento reais permanecem sem validação operacional.
