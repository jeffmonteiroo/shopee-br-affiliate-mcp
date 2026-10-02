# Deploy no Coolify — 0.5.0

Uma aplicação Python, um volume SQLite e uma chave secreta. Não precisa de
Postgres, Redis ou serviço externo de login. Use uma réplica e um worker.

## Tela de criação

| Campo | Valor |
| --- | --- |
| Repository URL | `https://github.com/jeffmonteiroo/shopee-br-affiliate-mcp` |
| Branch | `main` |
| Build Pack | **Dockerfile** |
| Base Directory | `/` |
| Dockerfile Location | `/Dockerfile` |
| Port / Ports Exposes | `8765` |
| Static site | Desmarcado |

Após Continue, em configurações de build, defina **Docker Build Target =
`remote`**. O alvo padrão do Dockerfile é stdio, usado para execução local;
o alvo `remote` inicia `oauth-http` em `0.0.0.0:8765`.

## Antes de Deploy

1. Escolha um subdomínio dedicado com DNS apontando para a VPS. Em Domains,
   use `https://mcp.seu-dominio.com`. Não use o domínio do painel Coolify.
2. Em Environment Variables, configure as variáveis abaixo **no runtime**;
   a chave não deve ser variável de build.
3. Em Persistent Storage, adicione um **volume persistente** montado em
   `/app/data`. O processo usa UID/GID `10001`; o diretório precisa ser gravável
   por esse usuário. Um volume Docker novo herda o diretório da imagem. Se usar
   bind mount, ajuste o proprietário do diretório do host para `10001:10001`.
4. Configure somente uma réplica. Ative o health check do tipo **CMD**, com
   comando `python -m shopee_mcp.healthcheck`. Ele confere `/health` na porta
   `8765` com o header `Host` correto.
5. Clique Deploy. Confirme `https://mcp.seu-dominio.com/health` e a descoberta
   OAuth antes de adicionar a conexão ao cliente.

```dotenv
MCP_OWNER_KEY_SHA256=HASH_DA_CHAVE_PRIVADA
MCP_PUBLIC_URL=https://mcp.seu-dominio.com
MCP_STATE_DB=/app/data/oauth.sqlite3
MCP_CREDENTIALS_KEY=COLE_A_CHAVE_GERADA
MCP_OAUTH_REDIRECT_URIS=["http://localhost:27890/callback"]
MCP_ALLOW_LOOPBACK_CALLBACKS=true
```

A lista de callback localhost acima é para Hermes; ChatGPT é permitido por
padrão. O perfil Shopee já está configurado na imagem `remote`.

Gere a chave **uma vez**, no seu terminal com o ambiente Python do projeto:

```sh
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Guarde a chave num gerenciador de senhas e coloque-a no campo secreto do
Coolify. Ela permanece a mesma em novos deploys. Não coloque a chave no GitHub,
na imagem ou em mensagens. Faça backup do volume e da chave separadamente.
Sem a chave correta, o servidor recusa iniciar e preserva o banco.

Comando alternativo de health check, sem expor segredos:

```sh
python -m shopee_mcp.healthcheck
```

## Uso

Adicione `https://mcp.seu-dominio.com/mcp` ao ChatGPT/Hermes com OAuth. Siga [PRIVATE.md](PRIVATE.md) para configurar os clientes. O navegador
abre a tela da chave privada, App ID e App Secret da Open API de Afiliados. Você informa uma vez
por conexão, e o cliente recebe tokens próprios. As credenciais ficam
criptografadas no banco do volume da VPS, preservadas em reinícios e deploys.

O token de acesso dura uma hora e o cliente o renova automaticamente via
refresh. Cada renovação prolonga a conexão por 90 dias. Após 90 dias sem
renovação, ou após revogação, é necessário conectar novamente. Isso remove a
exigência diária sem deixar tokens abandonados válidos para sempre.

O administrador da VPS tem acesso à chave e ao banco; criptografia protege o
banco isoladamente, não de um administrador com acesso a ambos. Não envie suas
credenciais Shopee pela conversa. Veja [fluxo e limites](REMOTE.md).

Referências: [Dockerfile no Coolify](https://coolify.io/docs/applications/builds/dockerfile)
e [Fernet](https://cryptography.io/en/latest/fernet/).
