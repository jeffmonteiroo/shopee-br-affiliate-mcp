# Changelog

## 0.3.0 — 2026-10-01

- Transporte `oauth-http` com cadastro dinâmico de clientes, PKCE S256, refresh rotativo e revogação.
- Tela única de App ID/App Secret, validação de acesso e credenciais somente em memória.
- Conexões isoladas e controles compartilhados quando usam as mesmas credenciais.
- Sessão absoluta de 24 horas, limpeza de conexões expiradas e limites de memória/formulário.
- Guia remoto, Compose, exemplo Hermes OAuth e correção do contexto de build Docker.
- 14 testes adicionais, incluindo cliente MCP HTTP do SDK e API Shopee simulada. Integração real e implantação ainda pendentes.

## Preparação para publicação

- Licença MIT, orientações de segurança e privacidade e metadados do pacote.
- Exemplos com referência genérica de conta e exclusão de logs e arquivos de autenticação.
- Autoria Git configurada com endereço noreply, sem e-mail pessoal no histórico da branch.

## 0.2.0 — 2026-10-01

- 17 ferramentas: produtos enriquecidos e filtros, lojas, campanhas, feeds FULL/DELTA, relatórios de conversões/validados, resumos, links em lote, URLs, exportação e histórico opcional.
- Cursores de uso único sem retry, intervalo entre relatórios iniciais e indicação de cobertura parcial.
- Precisão decimal/IDs, comissões negativas de ajustes e separação de comissões de itens/conversões.
- Histórico SQLite separado por conta/modo; proteção de fórmulas CSV e destinos de redirecionamentos.
- Teste local ampliado, dependências fixadas, CI Linux e preparação para VPS/Docker.
- Contratos conferidos no portal brasileiro; operações novas ainda aguardam aceitação real da conta.

## 0.1.0

Núcleo de produtos, detalhe, link e status com fixtures, perfil documentado e testes MCP.
