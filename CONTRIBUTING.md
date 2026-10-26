# Como contribuir

Obrigado pelo interesse. É um projeto pequeno, com algumas regras firmes por lidar com certificado digital e
documento fiscal.

## Regras

1. **Nenhum dado real.** Nada de CNPJ, CPF, nome, endereço, telefone, e-mail, chave de acesso ou XML de nota de
   verdade em teste, exemplo, issue ou commit. Use os dados sintéticos de `tests/conftest.py` (CNPJ
   11.222.333/0001-81, Praça da Sé em São Paulo) e o certificado autoassinado que os testes geram.
2. **Nenhuma dependência nova no núcleo.** `src/nfse` usa só `lxml`, `cryptography` e a biblioteca padrão. O que
   for opcional entra como extra (como o `danfse`), importado só dentro da função que usa.
3. **A biblioteca não guarda estado.** Numeração, cadastro e arquivos são de quem chama (a CLI, a Lambda, o seu
   sistema). Nada de ler ou gravar em disco dentro de `src/nfse`.
4. **Os dois leiautes.** Enquanto a produção e a homologação usarem esquemas diferentes, toda DPS é testada nos
   dois (a fixture `emissao` já faz isso).
5. **Logs sem XML, sem dado do cliente e sem senha.**
6. **Mudança de regra fiscal cita a fonte:** nota técnica, anexo ou código de rejeição da Sefin.

## Ambiente

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Os testes rodam sem internet e sem certificado real. Os que falam com a Sefin de homologação são marcados e só
rodam quando pedidos, com certificado configurado: `.venv/bin/pytest -m homologacao`.

## Pull requests

- Um assunto por PR, com teste que falha sem a mudança.
- Texto, mensagens e nomes em português, como o resto do código.
- Descreva como testou. Se emitiu em homologação, diga; nunca cole o XML.
