# MCP pessoal na VPS — 0.5.0

Uma única instalação serve Codex, Hermes e Claude Code. O MCP HTTP exige
OAuth, e só emite uma conexão após você informar sua **chave de acesso privada**
no formulário. App ID/App Secret da Shopee, sozinhos, não autorizam ninguém.
A chave de acesso é um segredo aleatório separado das credenciais Shopee e da
chave Fernet do banco. Não coloque nenhum desses segredos em conversas ou Git.

O domínio e as páginas de descoberta continuam acessíveis publicamente.
Isso não dá acesso às ferramentas, produtos ou relatórios. A proteção identifica
quem possui sua chave privada; ela não é um cadastro de identidade pessoal.
Quem tiver seus tokens pode usá-los até expiração/revogação. Proteja também os
computadores, a VPS e as contas que executam os harnesses.

## Configuração do servidor

Além de [COOLIFY.md](COOLIFY.md), configure no runtime:

```dotenv
MCP_OWNER_KEY_SHA256=HASH_SHA256_DA_CHAVE_PRIVADA
MCP_ALLOW_LOOPBACK_CALLBACKS=true
```

Gere uma chave aleatória de pelo menos 32 bytes, guarde-a no seu gerenciador de
senhas e coloque somente seu SHA256 na variável. O servidor remoto de produção
não inicia se o hash estiver ausente ou malformado. Não use uma senha curta
ou previsível: SHA256 aqui depende da entropia da chave gerada.

Ativar a proteção numa instalação antiga ou trocar esse hash invalida **todas**
as conexões anteriores e remove suas credenciais do estado ativo. Reconecte os
harnesses. A chave Fernet `MCP_CREDENTIALS_KEY` permanece inalterada; trocar
essa chave sem migrar o banco impede abrir os dados. Backups antigos continuam
sensíveis e não são apagados automaticamente.

O modo loopback permite callbacks `http://127.0.0.1` e `http://localhost` com
portas variáveis, necessários aos clientes locais. O código OAuth exige PKCE e
fica vinculado ao cliente/callback registrado. Não libera callbacks externos.

## Codex

```sh
codex mcp add shopee-private --url https://mcp.example.com/mcp
codex mcp login shopee-private
```

Também pode usar a configuração TOML abaixo. Não coloque sua chave privada
nem as credenciais Shopee no TOML.

```toml
[mcp_servers.shopee-private]
url = "https://mcp.example.com/mcp"
startup_timeout_sec = 30
tool_timeout_sec = 60
```

## Claude Code

```sh
claude mcp add --transport http --scope user shopee-private https://mcp.example.com/mcp
```

Em Claude Code, abra `/mcp`, selecione `shopee-private` e autentique pelo
navegador. Não passe a chave privada como OAuth client secret: são coisas
diferentes, e o servidor registra os clientes OAuth automaticamente.

## Hermes

```sh
hermes mcp add shopee-private --url https://mcp.example.com/mcp --auth oauth
hermes mcp login shopee-private
```

Ou adicione ao `config.yaml`:

```yaml
mcp_servers:
  shopee-private:
    url: https://mcp.example.com/mcp
    auth: oauth
    oauth:
      redirect_host: localhost
      redirect_port: 27890
    timeout: 60
    connect_timeout: 30
    parallel_tool_calls: false
```

## Primeira autorização

O navegador pede sua chave privada, App ID e App Secret da API de Afiliados.
Confira o domínio e o callback exibidos, autorize e volte ao harness. Cada
harness recebe tokens próprios; o segredo Shopee fica criptografado na VPS.
Após essa conexão, o refresh é automático. Não precisa enviar a chave em
cada busca. Comece com `affiliate_status` e `search_offers`. Geração de links
usa a referência de conta do status para conferir a atribuição.

OAuth e as ferramentas foram testados com o cliente MCP do SDK e API simulada.
A autenticação interativa dos três harnesses e as operações reais da sua conta
precisam ser concluídas com suas credenciais. Não é uma auditoria independente
nem garantia contra comprometimento da VPS ou dos seus dispositivos.

Fontes: [Codex MCP](https://developers.openai.com/codex/mcp),
[Claude Code MCP](https://code.claude.com/docs/en/mcp) e
[Hermes MCP](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md).
