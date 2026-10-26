# Política de segurança

## Versões com suporte

O projeto não tem versões de manutenção em paralelo: **a versão mais recente da branch `main` é a que recebe
correções.** Quem instala por tag deve atualizar para a tag mais nova.

## Como reportar uma falha

**Não abra issue pública.** Use o [aviso privado de vulnerabilidade do GitHub](https://github.com/regisdias/nfse-cli/security/advisories/new).
Conte o que encontrou, como reproduzir e o impacto que você enxerga.

Nunca mande certificado, senha, XML de nota real ou dado de cliente no relato. Se precisar de um exemplo, use o
certificado autoassinado que os testes geram (`tests/conftest.py`).

## O que o projeto toca, para delimitar o risco

| | O quê | Onde |
|---|---|---|
| Rede | Só os servidores da Sefin Nacional (`sefin.nfse.gov.br` e `sefin.producaorestrita.nfse.gov.br`), por TLS com o certificado do cliente | `src/nfse/sefin.py` |
| Certificado | Lido de bytes; a chave privada fica em memória e passa pelo disco só cifrada, por instantes, para o TLS | `src/nfse/certificado.py` |
| Senha | Keychain do macOS, variável `NFSE_CERT_SENHA` ou digitada; na Lambda, Secrets Manager. Nunca em arquivo | `src/nfse_cli/cli.py`, `src/nfse_lambda/handler.py` |
| Disco | Configuração, numeração e XML das notas em `~/.config/nfse-cli/` (CLI); nada na biblioteca nem na Lambda | `src/nfse_cli/cli.py` |
| Logs | Ação, id da DPS, chave de acesso e códigos de erro. Nunca XML, dado do cliente ou senha | `src/nfse_lambda/handler.py` (tem teste) |

## Dependências

O núcleo usa só `lxml` e `cryptography`, de propósito: nenhuma biblioteca de terceiros específica de NFS-e,
para que tudo o que assina com o certificado esteja aqui e possa ser lido. O `reportlab` (PDF) é opcional e
não toca o certificado. Pull request que adicione dependência ao núcleo vai ser recusado.
