# AWS Lambda

`nfse_lambda.handler.handler` é uma função pronta para AWS Lambda; os projetos usam o pacote por versão, sem
copiar código. Sem estado, como a biblioteca: o evento traz a configuração do prestador (mesmo formato do
TOML, em JSON), a série e o número da DPS, que é o projeto quem controla no banco dele.

```json
{"acao": "emitir", "ambiente": "homologacao", "config": {"prestador": {...}, "servico": {...}},
 "serie": "1", "numero": 7, "valor": "9000.00", "descricao": "...", "tomador": {...}}
```

Ações: `emitir`, `dps` (assina e valida sem enviar), `consultar`, `baixar`, `danfse`. Resposta `{"ok": true, ...}`
ou `{"ok": false, "erro": "rejeicao" | "dados" | "certificado" | "comunicacao", ...}`; `comunicacao` pode ser
repetida, porque `emitir` consulta a DPS antes de enviar. Detalhes no cabeçalho de `handler.py`.

- **Certificado** no Secrets Manager, um segredo por CNPJ (`NFSE_SEGREDO_CERTIFICADO="nfse/certificado/{cnpj}"`),
  conteúdo `{"pfx": "<base64>", "senha": "..."}`. Nunca no evento nem em variável de ambiente. Fica em cache
  na instância por uma hora.
- **Produção** só com `"ambiente": "producao"` no evento **e** `NFSE_PRODUCAO_LIBERADA=1` na função.
- **Log** só com ação, id da DPS, chave e códigos de erro.
- **Rede:** a função precisa sair para a internet (fora de VPC, ou com NAT).

Empacotar (de um Mac também: o pip baixa as rodas Linux da arquitetura pedida):

```bash
.venv/bin/python lambda/empacotar.py               # dist/nfse-lambda-arm64-py3.13.zip, ~10 MB
.venv/bin/python lambda/empacotar.py --danfse      # com reportlab, ~19 MB
.venv/bin/python lambda/empacotar.py --camada      # como Lambda layer, para um handler próprio
```

O zip é determinístico: sem mudança, mesmo hash, e o deploy não reenvia a função. `lambda/template.exemplo.yaml`
tem a função, as permissões (segredo e KMS) e o comando para criar o segredo.
