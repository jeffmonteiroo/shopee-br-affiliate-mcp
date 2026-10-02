# Conexão remota com uma única tela — 0.5.0

O cliente abre uma tela da chave privada, App ID e App Secret Shopee.
A chave privada é obrigatória para autorizar o acesso; veja [PRIVATE.md](PRIVATE.md). Não há cadastro nem
senha adicional. As credenciais são enviadas diretamente ao servidor HTTPS,
validadas com uma pesquisa de produto e armazenadas criptografadas em SQLite num volume persistente. O cliente
MCP recebe um token próprio, sem receber os segredos Shopee.

No Coolify, siga [COOLIFY.md](COOLIFY.md).

## Na VPS

Use uma origem dedicada, por exemplo `https://mcp.example.com`, sem caminho.
Configure DNS e um proxy HTTPS com certificado válido antes de conectar.
O proxy precisa preservar o header `Host` público e encaminhar todos os
caminhos, incluindo `/mcp`, `/connect`, `/authorize`, `/register`, `/token`,
`/revoke` e `/.well-known/*`. Não registre corpos de requisições nem headers
de autorização no proxy; desabilite cache e mantenha limites de tráfego.
Para health checks, use `/health` com o `Host` público configurado.

Com Docker Compose, configure no ambiente ou em um `.env` local da VPS:

```dotenv
MCP_OWNER_KEY_SHA256=HASH_DA_CHAVE_PRIVADA
MCP_PUBLIC_URL=https://mcp.example.com
MCP_STATE_DB=/app/data/oauth.sqlite3
MCP_CREDENTIALS_KEY=COLE_A_CHAVE_FERNET_GERADA
MCP_OAUTH_REDIRECT_URIS=["http://localhost:27890/callback"]
```

Esse arquivo contém a chave de criptografia; proteja-o e não envie ao GitHub.
Não recebe App ID ou App Secret Shopee. Gere e guarde a chave conforme
[COOLIFY.md](COOLIFY.md), e preserve o volume entre deploys.

```sh
docker compose -f compose.remote.yaml up -d --build
```

O Compose publica a porta 8765 somente no loopback do host, para um proxy
instalado no host. Se o proxy roda em container ou no Coolify, conecte os dois
containers à rede privada apropriada e aponte o proxy para a porta 8765 do
serviço. Não deixe essa porta HTTP exposta diretamente na internet.

Sem Docker, instale o pacote e execute com as variáveis de configuração e a chave secreta exportada:

```sh
MCP_PUBLIC_URL=https://mcp.example.com \
MCP_STATE_DB=/opt/shopee-affiliate-mcp/data/oauth.sqlite3 \
SHOPEE_VERIFIED_PROFILE=/opt/shopee-affiliate-mcp/examples/profile.official.json \
.venv/bin/python run.py --transport oauth-http --port 8765
```

Este transporte sempre opera em live; não lê credenciais Shopee do ambiente.
Ele escuta em `0.0.0.0` dentro do processo/container para o proxy alcançá-lo.
Use firewall/rede privada para permitir acesso somente pelo proxy HTTPS.

## No ChatGPT

Habilite o modo de desenvolvedor, quando disponível na sua conta/workspace,
e adicione uma conexão MCP com a URL `https://mcp.example.com/mcp`.
Selecione autenticação OAuth e cadastro dinâmico de cliente (DCR), se a
interface pedir essa escolha. Não configure uma chave Shopee como secret
OAuth: o cadastro do cliente é separado das credenciais Shopee.

Ao conectar, o navegador abre a tela de credenciais. Confira o domínio do
servidor e o destino ChatGPT mostrado na tela. Preencha App ID e App Secret da
Open API de Afiliados, confirme e volte ao ChatGPT. Nunca use a senha de login
da Shopee nesse formulário. Se a API não aceitar a pesquisa, não há emissão
de token; uma pesquisa aceita sem produtos também valida o acesso inicial.

Comece pedindo `affiliate_status`, depois uma busca. Para gerar links, use a
referência de conta retornada pelo status; ela é um identificador local opaco
e não comprova titularidade por si só.

Os callbacks HTTPS de `chatgpt.com/connector/oauth` são permitidos por padrão.
Caso sua interface forneça outro callback, copie a URL exata para a lista
`MCP_OAUTH_REDIRECT_URIS`, sem adicionar domínios arbitrários.

Fontes: [autenticação OpenAI](https://developers.openai.com/plugins/build/auth)
e [conexão e testes](https://developers.openai.com/plugins/deploy/connect-chatgpt).

## No Hermes

Use [hermes.remote.yaml](../examples/hermes.remote.yaml), alterando a URL.
O servidor deve permitir exatamente `http://localhost:27890/callback` em
`MCP_OAUTH_REDIRECT_URIS`. Hermes registra seu cliente OAuth e abre o mesmo
formulário. Não precisa receber App ID/Secret na configuração.

Se Hermes roda via SSH na VPS, abra o link no seu navegador e conclua pelo
fluxo de colar o callback do Hermes, ou encaminhe a porta de callback por SSH.
O callback deve coincidir com o registrado. O suporte depende da versão
instalada do Hermes; atualize se ela não reconhecer `auth: oauth`.

Fontes: [MCP no Hermes](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md)
e [OAuth por SSH](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/guides/oauth-over-ssh.md).

## Duração e limites

- A tela de autorização expira em cinco minutos; códigos expiram em um minuto
  e só podem ser usados uma vez, com PKCE S256 e callback registrado.
- Tokens de acesso duram até uma hora. O refresh é rotativo e cada renovação
  prolonga a conexão por 90 dias. Após 90 dias sem renovação, conecte novamente.
- Credenciais, tokens, códigos e registros OAuth são salvos criptografados.
  Reinícios e deploys preservam as conexões se o volume, a chave e a origem
  HTTPS forem mantidos. Formulários ainda não concluídos precisam ser reabertos.
- Revogar uma conexão invalida seus tokens. Quando nenhuma conexão ativa usa
  aquela conta, suas credenciais são removidas do estado ativo; backups antigos
  podem conservar cópias criptografadas.
- Use somente um processo e uma réplica. O banco tem trava de processo;
  não existe sincronização de estado entre réplicas.
- Conexões com as mesmas credenciais compartilham o serviço Shopee e seus
  controles de quota/relatórios. Contas diferentes têm serviços separados.
  Instalações externas da mesma conta não participam dessa coordenação.
- Histórico SQLite é desabilitado no transporte remoto. As ferramentas de
  histórico continuam disponíveis em instalações stdio configuradas.
- Limites por processo: 256 clientes/conexões pendentes/sessões; até dez
  tentativas de conexão por minuto. Comece com poucos usuários e configure
  limites por IP no proxy. Não é um serviço de escala nem gestão de usuários.
- A chave Fernet fica na variável secreta `MCP_CREDENTIALS_KEY`, separada do
  banco. Proteja ambos e seus backups. O administrador da VPS pode descriptografar
  os dados se tiver acesso aos dois. Evite logs de corpos/headers sensíveis e
  dumps de memória; a remoção lógica não garante apagar backups antigos.

Esta versão foi verificada com API simulada e cliente HTTP MCP do SDK.
A CI validou o build Docker e uma conexão MCP stdio em fixture dentro do
container. ChatGPT, Hermes, API real, o fluxo HTTPS e a VPS ainda precisam de
testes no destino.
