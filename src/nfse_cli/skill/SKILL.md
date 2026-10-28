---
name: nfse
description: Emite NFS-e (nota fiscal de serviço eletrônica) pela API nacional da Receita com o comando `nfse`, configura a empresa a partir de uma nota anterior ou por perguntas, arquiva o PDF e prepara o e-mail para o cliente. Usar quando a pessoa pedir para emitir, configurar, consultar ou enviar uma nota fiscal de serviço (ex. "emite a nota da Empresa X", "faz a NF de novembro", "configura minha nota fiscal", "a nota deste mês já saiu?").
---

# NFS-e com o nfse

Você opera o comando `nfse` (projeto nfse-cli) no terminal. Ele fala direto com a API da NFS-e nacional usando
o certificado digital A1 da empresa. Documento fiscal é coisa séria: siga os passos na ordem, mostre o que vai
acontecer antes de acontecer e, na dúvida, pergunte.

## Regras que não mudam

1. **Senha do certificado: nunca peça, nunca leia, nunca digite.** Quem digita é a pessoa, no terminal dela
   (`nfse configurar certificado`). Se algum comando reclamar da senha, explique e peça para ela rodar.
2. **Produção só com confirmação.** Antes de emitir de verdade, mostre o resumo de `nfse dps --producao` e
   espere um "sim" explícito para aquela nota. Só então rode `nfse emitir --producao ... --confirmacao <código>`
   com o código do resumo. Nunca invente nem reaproveite um código; se algo mudou, gere o resumo de novo.
3. **Falha de comunicação no `emitir` (saída 3): não repita direto.** A nota pode ter saído. Rode
   `nfse consultar --producao --numero <n>` com o número da DPS do resumo; se virou nota, siga com ela.
4. **Não invente código tributário.** Código de serviço, NBS, regime, alíquota: venha de uma nota anterior, das
   buscas oficiais (`nfse servico`, `nfse nbs`, `nfse municipio`) ou da pessoa. Se ela não souber, diga para
   confirmar com a contabilidade.
5. **Homologação para testar.** Sem `--producao`, a nota vai para o ambiente de testes da Receita, sem valor
   fiscal. Use para a primeira nota depois de configurar.
6. **E-mail: só prepara, nunca envia.** E rode `nfse email` uma vez por nota (no Outlook, cada execução cria
   outro rascunho).
7. **Não cole XML, senha nem dados de clientes em lugares públicos** (issues, gists, buscas na web).
8. **Versão nova.** Se a saída de qualquer comando terminar com "Nova versão do nfse-cli", avise a pessoa e
   ofereça `nfse atualizar` (atualiza o comando e esta skill). Antes de emitir em produção, recomende atualizar
   primeiro: versões novas costumam trazer mudança de leiaute exigida pela Receita.

Se `nfse` não existir no terminal, a instalação não foi feita: aponte para
<https://github.com/regisdias/nfse-cli#instalação>.

## Primeiro: já está configurado?

```bash
nfse configurar mostrar
```

Se mostrar a empresa e os clientes, vá para **Emitir a nota do mês**. Se disser que não há configuração, faça a
**Configuração** abaixo.

## Configuração (primeira vez)

### 1. Certificado

Pergunte onde está o arquivo `.pfx` (ou `.p12`) do certificado A1 da empresa e peça para a pessoa rodar, ela
mesma, num terminal:

```bash
nfse configurar certificado "<caminho do .pfx>"
```

O comando pede a senha, confere o certificado, copia para a pasta de configuração e guarda a senha no cofre do
sistema. Fora do macOS, ele avisa para usar a variável `NFSE_CERT_SENHA`. Espere ela dizer que deu certo (a saída
mostra titular, CNPJ e validade) antes de seguir.

### 2. Escolha o caminho

Pergunte: **"Você já emitiu alguma nota de serviço por esta empresa?"**

#### Caminho A: a partir de uma nota anterior (preferido)

Peça o PDF, o XML ou a chave de acesso (50 dígitos, aparece no PDF) de uma nota recente para o mesmo cliente.

```bash
nfse configurar modelo "<arquivo .pdf ou .xml, ou a chave>"
```

Mostre o resumo para a pessoa conferir, item por item, em português. Pontos de atenção:

- **"NÃO SUPORTADO"** no resumo: o nfse ainda não emite notas assim. Explique o que é e diga para continuar
  pelo Emissor Web do governo por enquanto. Não tente contornar.
- **"Atenção"**: leia e explique o aviso.
- **Descrição:** se tiver mês ou ano escritos ("serviços de outubro"), sugira trocar por `{mes_min}`,
  `{mes}` ou `{ano}` para virar automática (veja Recorrência abaixo).

Depois, complete o rascunho (`~/.config/nfse-cli/rascunho.json`) com o que ainda falta, seguindo
**Recorrência e entrega**, e salve.

#### Caminho B: manual (primeira nota da empresa)

Pergunte uma coisa de cada vez, e só o que se aplica. Use as buscas para achar os códigos; mostre as opções e
deixe a pessoa escolher.

1. **Regime da empresa.** MEI, Simples Nacional (ME ou EPP) ou fora do Simples (Lucro Presumido ou Real)?
   - MEI: ainda não suportado. Pare e explique.
   - Simples ME/EPP: `op_simp_nac = 3`, `reg_ap_trib_sn = 1` (tributos federais e municipal pelo Simples, o caso
     comum; se a pessoa disser outra coisa, confirme com a contabilidade).
   - Fora do Simples: `op_simp_nac = 1`. Avise que esse regime ainda não foi testado em produção.
2. **Município da empresa.** `nfse municipio <nome> <UF>` dá o código IBGE.
3. **Serviço.** Peça para descrever com as palavras dela. `nfse servico <palavras>` (tente sinônimos) e
   `nfse nbs <palavras>`. Mostre as melhores opções com a descrição oficial.
4. **ISS.** O cliente retém o ISS? Se sim: ainda não suportado, pare. O serviço é prestado em outro município?
   Se sim, `cod_municipio_prestacao`. Simples ME/EPP sem retenção não informa alíquota (`p_aliq`); fora do
   Simples, pergunte a alíquota.
5. **Retenções federais** pelo cliente? IR retido é suportado: `irrf` com a alíquota da contabilidade
   (`{"p_aliq": "1.50"}`); a retenção de até R$ 10,00 é dispensada sozinha (Lei 9.430/1996, art. 67). PIS,
   COFINS, CSLL ou INSS retidos: ainda não suportado, pare.
   Fora do Simples, sem retenção: PIS/COFINS de apuração própria (`pis_cofins`, alíquotas da contabilidade:
   presumido 0,65 e 3,00; real 1,65 e 7,60) e o grupo IBS/CBS (`ibs_cbs`: CST, cClassTrib e indicador da
   operação). Os códigos de IBS/CBS vêm da contabilidade ou de uma nota do Emissor Web; não invente.
6. **Tributos aproximados** (Lei 12.741): no Simples, o percentual efetivo do Simples
   (`{"modo": "sn", "percentual": "6.00"}`, confirmar com a contabilidade). Fora do Simples, percentuais
   federal, estadual e municipal, ou `nao_informado`.
7. **Telefone e e-mail da empresa** (opcionais).
8. **Cliente.** CNPJ ou CPF, razão social e endereço (logradouro, número, complemento, bairro, município, CEP).
   Cliente no exterior: ainda não suportado. Peça os dados à pessoa (de um contrato ou do cartão CNPJ); não
   busque CNPJ em sites de terceiros sem ela pedir.

Escreva o rascunho em `~/.config/nfse-cli/rascunho.json` no formato de `docs/configuracao.md` do projeto (o
mesmo que o Caminho A gera), com **Recorrência e entrega**, e salve.

### 3. Recorrência e entrega

Para cada cliente, pergunte e coloque no rascunho, dentro do cliente:

```json
"recorrente": {"valor": "9000.00", "descricao": "Consultoria em tecnologia referente a {mes_min}/{ano}."},
"entrega": {"pasta": "Empresa X", "para": "financeiro@empresax.com.br", "cc": "",
            "saudacao": "Olá, Fulana,", "assunto": "NFS-e {mes_min}/{ano} - {prestador}"}
```

E uma vez, no topo do rascunho, o padrão de todos:

```json
"entrega": {"pasta": "~/Documents/NFS-e", "assinatura": "Nome de quem assina", "email": "outlook"}
```

- `email`: o programa de e-mail. **Pergunte qual a pessoa usa**; não confie no padrão do sistema (muita gente
  usa Outlook ou Gmail com o Mail da Apple como padrão sem saber). `nfse programas-de-email` mostra o que está
  instalado. Opções:

  | `email` | Para quem usa | Anexo |
  |---|---|---|
  | `outlook` | Outlook no Mac | vai junto |
  | `mail` | Mail da Apple | vai junto |
  | `thunderbird` | Thunderbird (qualquer sistema) | vai junto |
  | `gmail` | Gmail no navegador | a pessoa arrasta o PDF (a pasta abre junto) |
  | `outlook-web` | Outlook na web / Microsoft 365 | a pessoa arrasta o PDF (a pasta abre junto) |
  | `eml` | Outro programa, ou Windows sem Thunderbird | vai junto; a pessoa abre o arquivo |
  | `nenhum` | Não quer e-mail | |

  Nenhum webmail aceita anexo vindo de fora; diga isso para quem escolher `gmail` ou `outlook-web`.
- Campos que os textos aceitam: `{numero}`, `{valor}`, `{mes}` (Outubro), `{mes_min}` (outubro), `{mes_num}`,
  `{ano}`, `{cliente}`, `{prestador}`, `{saudacao}`, `{assinatura}`, `{anexos}`.
- Também dá para mudar o `nome_arquivo` (padrão `NFS-e {numero} - {cliente} - {mes} de {ano}`), o `corpo` do
  e-mail e `anexar_xml` (padrão: só o PDF).

### 4. Salvar e testar

```bash
nfse configurar salvar ~/.config/nfse-cli/rascunho.json
nfse configurar mostrar
```

Se `salvar` recusar, leia o erro: ou é algo não suportado (pare e explique), ou um dado inválido (corrija com a
pessoa). Depois, uma nota de teste em homologação, que não vale nada:

```bash
nfse emitir --tomador <apelido>
```

Saiu número e chave: configuração pronta. Rejeição: mostre o código e a mensagem da Sefin e corrija com a
pessoa antes de qualquer nota em produção.

**Teste do e-mail** (se já existe nota de produção, como no Caminho A): ofereça abrir um rascunho de teste
endereçado à própria pessoa, para ela ver se o programa certo abriu, com o PDF:

```bash
nfse arquivar <chave da nota modelo>
nfse email <chave da nota modelo> --para <e-mail da pessoa>
```

Peça para ela conferir e apagar o rascunho de teste. Não abriu ou abriu o programa errado: troque o `email` e
teste de novo. No Caminho B, o teste fica para a primeira nota de verdade.

## Emitir a nota do mês

1. **Já foi emitida?**

   ```bash
   nfse notas --tomador <apelido>
   ```

   Se o mês já tem nota, pare e avise o número. Não emita outra, a menos que a pessoa peça explicitamente (por
   exemplo, uma segunda nota no mês). A primeira vez demora um pouco: ele procura nota por nota.

2. **Confere com o mês anterior.** Valor e descrição da última nota da lista devem bater com os de
   `nfse configurar mostrar`. Se a pessoa falou outro valor, ou algo mudou, pergunte antes.

3. **Resumo, sem enviar:**

   ```bash
   nfse dps --producao --tomador <apelido>
   ```

   Com outro valor ou descrição neste mês: acrescente `--valor` e `--descricao` (ou `--descricao-arquivo`).
   Para competência diferente de hoje: `--competencia AAAA-MM-DD`. Use os mesmos argumentos no passo 4.

   Mostre à pessoa: cliente, valor, descrição, competência e número da DPS. Pergunte: **"Posso emitir esta nota
   em produção?"**

4. **Emitir**, só depois do "sim", com os mesmos argumentos e o código do resumo:

   ```bash
   nfse emitir --producao --tomador <apelido> --confirmacao <código>
   ```

   O código não bate: algo mudou entre o resumo e agora. Volte ao passo 3. Rejeição da Sefin (saída 2): mostre
   os códigos e mensagens, não tente de novo sem entender. Falha de comunicação (saída 3): regra 3.

5. **Arquivar:** `nfse arquivar <chave>` grava o XML e o PDF na pasta do cliente.

6. **E-mail:** `nfse email <chave>`, uma vez. Avise que o rascunho está pronto e que quem envia é a pessoa.

7. **Relatar:** número da nota, chave de acesso, onde ficaram os arquivos e o estado do e-mail.

## Outras tarefas

| Pedido | Comando |
|---|---|
| "Essa DPS virou nota?" | `nfse consultar --producao --numero <n>` (`--serie 70000` para notas do Emissor Web) |
| PDF de uma nota | `nfse danfse <chave> --producao` ou `nfse danfse --xml <arquivo>` |
| XML de uma nota | `nfse baixar <chave> --producao` |
| Ver o certificado | `nfse certificado` |
| Novo cliente | Caminho A com uma nota dele, ou só o passo 8 do Caminho B + Recorrência; depois `salvar` |
| Certificado renovado | A pessoa roda `nfse configurar certificado <novo .pfx>` |

Cancelar ou substituir nota: o nfse ainda não faz. Oriente a usar o Emissor Web do governo.

## Erros comuns

| Mensagem | O que fazer |
|---|---|
| `configuração não encontrada` | Configuração (primeira vez) |
| `senha do certificado não encontrada` | A pessoa roda `nfse configurar certificado` no terminal dela |
| `certificado venceu` | Renovar o certificado A1 e configurar de novo |
| `E1235` falando de `finNFSe` | A produção mudou de leiaute: atualizar o nfse (reinstalar) |
| `já existe ... com outro conteúdo` | Arquivo com o mesmo nome de outra nota: mudar `nome_arquivo` (incluir `{ano}`) ou mover o antigo |
