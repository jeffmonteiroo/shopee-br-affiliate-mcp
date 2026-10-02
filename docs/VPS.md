# Instalação na VPS — stdio

Este guia prepara o MCP para Hermes ou outro cliente na mesma VPS. A implantação real requer host SSH, usuário e diretório escolhidos. Não houve acesso à VPS nesta entrega.

## Instalação com Python

Clone o repositório; enquanto ele estiver privado, use sua autenticação GitHub. No diretório clonado:

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e .
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python local_test.py --fixture --extended
.venv/bin/python local_test.py --extended
```

Python deve ser 3.11+. O último comando pede credenciais no Terminal SSH com entrada oculta e testa consultas reais. Não transfira a `.venv` do macOS para Linux.

## Cliente

Adapte `examples/hermes.live.yaml` ou `examples/mcp.live.json`. O cliente deve executar a `.venv/bin/python` da VPS com `run.py --mode live` e receber as variáveis descritas no README. Segredos vêm do ambiente protegido do processo; não os coloque no Git, na skill ou em argumentos.

Para histórico opcional, configure `SHOPEE_HISTORY_DB` com um caminho absoluto de um diretório gravável pelo usuário do MCP. Faça backup do SQLite se precisar preservar as observações. Vários consumidores da mesma conta precisam coordenar a quota e o intervalo dos relatórios; os controles locais são por processo.

## Docker opcional

```sh
docker build -t shopee-affiliate-mcp .
docker run --rm -i shopee-affiliate-mcp --mode fixture
```

Para live, disponibilize credenciais no ambiente antes de executar:

```sh
docker run --rm -i   --env SHOPEE_APP_ID   --env SHOPEE_APP_SECRET   --env SHOPEE_ACCOUNT_REFERENCE   --env SHOPEE_VERIFIED_PROFILE=/app/examples/profile.official.json   shopee-affiliate-mcp --mode live
```

O cliente MCP pode usar `docker` como command e `run --rm -i ...` como args. Não use `-t`: stdio MCP precisa de streams sem terminal interativo. Histórico em container requer volume persistente e diretório gravável pelo UID 10001. Sem volume, os dados somem ao remover o container.

O Dockerfile foi preparado, mas não executado localmente porque o daemon Docker estava indisponível. A CI valida a instalação Python em Linux.

## Acesso remoto

Stdio é iniciado pelo cliente e não é um serviço web. O HTTP atual escuta somente em 127.0.0.1, exige `MCP_LOCAL_ACCESS_TOKEN` e não implementa OAuth. Para conectar ChatGPT ou Hermes pela internet, use o novo transporte `oauth-http` conforme [REMOTE.md](REMOTE.md), com HTTPS, formulário de credenciais e sessões criptografadas em volume persistente.
