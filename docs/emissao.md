# Como a emissão funciona

O que a biblioteca faz entre receber os dados e devolver a nota, e os erros da API que já custaram uma tarde cada.

## Passo a passo

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
