# nfse-cli

Emissão de NFS-e pela API da **Sefin Nacional** (Sistema Nacional NFS-e), sem passar pelo site do governo.

Duas peças no mesmo repositório:

- **`nfse`**: biblioteca Python **sem estado**. Monta a DPS (leiaute 1.01), assina (XMLDSig), valida no XSD
  oficial e fala com a Sefin por mTLS. Não sabe de banco, cliente nem agenda: numeração, série e configuração
  entram como parâmetro. É o que o painel e a Lambda emissora vão usar.
- **`nfse`** (comando): linha de comando que consome a biblioteca e guarda o pouco estado que precisa
  (configuração e último número de DPS usado).

Dependências do núcleo: só `lxml` e `cryptography`. Nenhuma biblioteca de terceiros específica de NFS-e.

## Instalação

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest            # testes offline
```

Em outro projeto, instalar por tag: `pip install 'nfse-cli @ git+ssh://git@github.com/<dono>/nfse-cli.git@v0.1.0'`.

## Configuração

1. Copie `config.exemplo.toml` para `~/.config/nfse-cli/config.toml` e preencha prestador, serviço e tomadores.
2. Guarde a senha do certificado no Keychain (a CLI lê de lá; nunca do arquivo de configuração):

   ```bash
   security add-generic-password -s nfse-cli -a <CNPJ do prestador> -w
   ```

   Alternativa: variável `NFSE_CERT_SENHA`. Sem nenhuma das duas, a CLI pergunta.

## Uso

Homologação (produção restrita) é o padrão. Produção só com `--producao` **e** confirmação digitada.

```bash
nfse certificado                                   # titular, CNPJ, validade
nfse dps --tomador cliente --valor 9000 --descricao-arquivo desc.txt   # gera e valida, não envia
nfse emitir --tomador cliente --valor 9000 --descricao-arquivo desc.txt
nfse emitir --producao --tomador cliente --valor 9000 --descricao-arquivo desc.txt
nfse consultar --numero 3                          # essa DPS virou nota?
nfse consultar --serie 70000 --numero 3            # idem, para uma nota do Emissor Web
nfse baixar <chave de acesso>                      # XML da NFS-e
nfse danfse <chave de acesso> --tentativas 30      # PDF; o serviço do ADN cai com frequência (503)
```

O número da DPS é o último usado + 1 (guardado em `~/.config/nfse-cli/numeracao.json`, por CNPJ, ambiente e
série), e só avança depois de a nota sair. `--numero` força um número.

## Como a emissão funciona

1. Monta a DPS e assina o `infDPS` (RSA-SHA256, C14N 1.0 inclusiva, enveloped, `<Signature>` sem prefixo).
2. Confere a assinatura e o XSD sobre os **bytes finais**, antes de qualquer envio.
3. Consulta `GET /dps/{id}`: se a DPS já virou nota (envio anterior que deu timeout), baixa a nota existente
   em vez de reenviar.
4. Envia `POST /nfse` com `{"dpsXmlGZipB64": ...}` e devolve chave de acesso, número e XML da NFS-e.

Erros da Sefin (`E0xxx`) viram `nfse.Rejeicao` e não adianta tentar de novo; rede, timeout e 5xx viram
`nfse.FalhaComunicacao`, que pode ser repetida, sempre consultando a DPS antes.

## Armadilhas já resolvidas

- **C14N do libxml2 com namespace padrão aninhado.** O `<Signature>` redefine o namespace padrão da `<DPS>`, e o
  C14N de subárvore do lxml emite `xmlns=""` falso nos netos. A assinatura sairia sobre bytes que a Sefin nunca
  calcula (E0714). `assinatura._c14n` canonicaliza uma cópia do elemento como raiz, e
  `test_c14n_confere_com_implementacao_independente` confere contra o `canonicalize` em Python puro da stdlib.
- **Prefixo de namespace é rejeitado** (E1228): `Signature`, nunca `ds:Signature`.
- **Dois leiautes com o mesmo nome "1.01".** A NT 009 mudou o conteúdo sem mudar a versão: `finNFSe` passou a
  ser obrigatório logo depois de `tpEmit`, e `cNBS` foi para antes de `xDescServ`. A produção restrita já está
  nela (pacote de 20/10/2026); a produção, não. Cada pacote oficial fica em `src/nfse/esquemas/<data>/` e
  `nfse.LEIAUTE_POR_AMBIENTE` diz qual cada ambiente usa. Na virada da produção, trocar ali. Sinal de que virou:
  rejeição `E1235` falando de `finNFSe`.
- **XSD de 09/02/2026 com `^...$` na série.** Em regex de XSD, `^` e `$` são literais; o libxml2 recusaria toda
  série. A cópia em `esquemas/20260209/` tira os dois (comentado no arquivo). O pacote de 20/10/2026 já corrigiu
  e está sem alteração.
- **Texto só até U+00FF.** Travessão (—) e aspas curvas reprovam no esquema; a biblioteca recusa antes, com a
  lista dos caracteres.
- **Série de aplicativo próprio: 1 a 49999** (E0010). O Emissor Web usa 70000+, então a numeração daqui não
  colide com a de lá.
- **ME/EPP no Simples, sem retenção:** não informa `pAliq` (E0625) e não pode usar `indTotTrib` (E0712).
- **Prestador emitente não informa nome nem endereço** (E0121): vêm do cadastro nacional.

## Referências oficiais

- Documentação atual (XSD, Anexo I com leiaute e regras): <https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual>
- APIs e swaggers: <https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao>
