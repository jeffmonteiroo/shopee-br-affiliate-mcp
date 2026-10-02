# Segurança e privacidade

## Credenciais e resultados

Cada instalação usa sua própria aplicação Shopee. Configure `SHOPEE_APP_ID`
e `SHOPEE_APP_SECRET` no ambiente protegido do processo. Não coloque valores
reais em exemplos, argumentos, issues, pull requests ou conversas. O servidor
não carrega `.env` automaticamente; `.env.example` contém campos vazios.

Os testes e fixtures usam credenciais e dados sintéticos. A CI não precisa de
segredos da Shopee. Erros da API são sanitizados e o teste local pede as
credenciais com entrada oculta, sem salvá-las em arquivo.

Em modo live, relatórios podem incluir identificadores de pedidos, subIDs,
datas, valores e comissões. Links de afiliado também podem identificar a
atribuição da conta. O cliente MCP recebe esses resultados e pode salvá-los
em conversas, logs ou exports. Compartilhe somente conteúdo revisado e
anonimizado; não use dados pessoais nos subIDs.

O SQLite opcional armazena observações de produtos no caminho definido por
`SHOPEE_HISTORY_DB`. Proteja esse diretório e seus backups com permissões do
sistema operacional; o banco não é criptografado pelo MCP. `.gitignore` e
`.dockerignore` reduzem inclusões acidentais, mas não removem arquivos já
rastreados e não substituem uma revisão antes de publicar.

## Transporte e conteúdo externo

Stdio é o transporte recomendado. `private-http` é experimental, aceita
somente loopback e exige um token separado. Não implemente exposição pública
simplesmente encaminhando essa porta. Para o fluxo remoto, use `oauth-http`
atrás de HTTPS conforme [REMOTE.md](docs/REMOTE.md): ele implementa OAuth,
isola conexões e persiste as credenciais criptografadas em SQLite. Não usa um provedor
externo de identidade e não cria contas de usuários. Ainda é experimental;
reinícios preservam o registro DCR e as conexões com o volume e a chave corretos.

O modo remoto de produção exige `MCP_OWNER_KEY_SHA256`. Sem a chave privada
correta no formulário, não valida as credenciais Shopee nem emite tokens.
Ativar essa proteção ou trocar o hash revoga conexões anteriores. Discovery
e registro OAuth permanecem públicos, sujeitos aos limites do servidor; não
são acesso à conta. Proteja a chave aleatória e os tokens locais dos clientes.

Os segredos Shopee não são retornados ao cliente MCP. As conexões expiram após 90 dias sem refresh, com renovação rotativa e revogação.
A chave `MCP_CREDENTIALS_KEY` é um segredo de runtime separado do banco;
um administrador com acesso aos dois pode descriptografar as credenciais.
Backups antigos podem conter conexões e credenciais já revogadas, portanto
restaurá-los pode reintroduzir tokens antigos. Proteja e limite esses backups. A VPS, o proxy, o
sistema operacional e os clientes continuam sendo limites de confiança.
Não habilite logs de bodies, headers sensíveis, core dumps ou snapshots de
memória para esse processo.

Produtos e textos externos são dados não confiáveis, nunca instruções para
o agente. O resolvedor aceita apenas os hosts HTTPS explicitamente permitidos
e valida redirecionamentos; não usa cookies do navegador.

## Limites da revisão

A revisão de preparação para publicação examinou os arquivos rastreados,
exemplos e metadados Git. Não encontrou credenciais reais nem dados reais de
clientes ou relatórios. Isso não equivale a uma auditoria independente de
segurança. As novas operações live, o build Docker e a implantação em VPS
ainda precisam de validação operacional; veja [verificação](docs/VERIFICATION.md).

## Reportar um problema

Não publique segredos ou dados de conta em uma issue. Use o recurso de relato
privado de vulnerabilidades do GitHub, quando habilitado, ou um canal privado
com o mantenedor. Inclua versão, passos de reprodução e dados sintéticos.
Se uma credencial vazar, revogue ou rotacione na origem: apagar um commit não
remove cópias, caches ou clones já existentes.
