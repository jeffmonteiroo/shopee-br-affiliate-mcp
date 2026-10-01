# Aceitação real da versão 0.2.0

1. Confirme no painel que a aplicação pertence à conta pretendida. Não envie credenciais na conversa.
2. Execute `local_test.py --extended`: produto, detalhe, lojas, campanhas e lista de feeds devem responder sem erros de schema/auth/acesso. Uma lista vazia não confirma presença de ofertas.
3. Se houver feed, use o datafeed ID devolvido em `get_product_feed` e confira offset/hasMore e colunas.
4. Execute `get_conversion_report` para um período escolhido, inicialmente uma página; confira pedidos/comissões com o painel. `max_pages` permite coleta automática limitada. Cursores expiram em 30 segundos e não podem ser repetidos.
5. Obtenha um validation ID no faturamento e confira `get_validated_report`. Não confunda validação com pagamento recebido.
6. Teste um link com produto, conta e subIDs escolhidos. Depois teste o lote. Em resultado desconhecido, reconcilie com o painel antes de repetir.
7. Habilite histórico opcional e confira a persistência de uma observação e sua separação por conta/modo.
8. Após aceitação local, repita consultas na VPS e valide o cliente que consumirá o MCP.

Guarde somente evidências sem segredo: data, ambiente, ferramentas utilizadas, IDs dos produtos, conta confirmada no painel e resultado sanitizado. O agente não executou as novas operações com credenciais reais nesta entrega.
