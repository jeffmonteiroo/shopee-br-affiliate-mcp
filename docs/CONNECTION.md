# Conexões — 0.2.0

Use stdio para um cliente no mesmo computador ou VPS. O cliente executa `.venv/bin/python run.py --mode live`, com credenciais e perfil no ambiente do processo. Modelos em `examples/mcp.live.json` e `examples/hermes.live.yaml`; instruções em [VPS.md](VPS.md).

O perfil é configuração do administrador. Ferramentas nunca recebem segredo, endpoint, query GraphQL livre ou caminho de arquivo. O rótulo da conta é local e não comprova titularidade. A geração de links confere `expected_account_reference` antes de enviar.

HTTP privado: `--transport private-http --port 8765`, somente loopback, rota `/mcp/`, `MCP_LOCAL_ACCESS_TOKEN` ASCII com pelo menos 32 caracteres e allowlist de Host/Origin. Esse transporte ainda apresenta avisos de encerramento em teste ASGI e deve ser tratado como experimental.

ChatGPT remoto exige uma implantação HTTPS com autenticação apropriada. O token estático local não implementa OAuth. O projeto não foi exposto publicamente nem instalado na VPS.

Múltiplos consumidores da mesma conta precisam coordenar a quota Shopee e a política dos relatórios. Os controles deste processo não sincronizam máquinas ou processos diferentes.
