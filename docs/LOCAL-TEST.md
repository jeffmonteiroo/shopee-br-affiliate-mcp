# Teste local

No Terminal, dentro do projeto:

```sh
.venv/bin/python local_test.py --fixture --extended
.venv/bin/python local_test.py --extended
```

O primeiro comando verifica somente dados sintéticos. O segundo pede App ID e App Secret com entrada oculta e testa a Shopee real: conexão MCP, descoberta de ferramentas, status, pesquisa/detalhe de produto, ofertas de lojas, campanhas e lista de feeds. Os valores não são gravados em arquivo. Variáveis já presentes no ambiente são reutilizadas.

Para outro produto: `.venv/bin/python local_test.py --keyword fone --extended`.

O rótulo local padrão é `minha-conta`; confirme a associação aplicação/conta no portal. Status sozinho não comprova autenticação. A pesquisa aceita é a evidência inicial de acesso.

Relatórios e geração de links são testados separadamente pelas ferramentas MCP com parâmetros escolhidos pelo usuário; consulte [PORTAL-CHECK.md](PORTAL-CHECK.md). Compartilhe somente mensagens sanitizadas, sem credenciais.

Depois do teste local, siga [VPS.md](VPS.md). Não transfira a `.venv` do macOS para a VPS Linux.
