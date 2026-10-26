# Configuração

Tudo fica em `~/.config/nfse-cli/` (ou na pasta de `NFSE_HOME`): `config.toml`, `certificado.pfx`,
`numeracao.json` e as notas emitidas. A senha do certificado nunca: ela vai para o Keychain (macOS) ou para a
variável `NFSE_CERT_SENHA`.

## Os três passos

```bash
nfse configurar certificado empresa.pfx     # 1. certificado (no seu terminal: pede a senha)
nfse configurar modelo nota.pdf             # 2a. rascunho a partir de uma nota já emitida
                                            # 2b. ou escreva o rascunho à mão (abaixo)
nfse configurar salvar rascunho.json        # 3. valida e grava o config.toml
```

**1. Certificado.** Copia o `.pfx` para a pasta de configuração (permissão 600) e guarda a senha no Keychain. A
senha é pedida no terminal e nunca aparece na linha de comando: vai para o `security` pela entrada padrão. Se o
comando não estiver num terminal interativo (um agente rodando, por exemplo), ele recusa e diz para você rodar.

**2a. Nota modelo.** Aceita o XML da nota, o PDF (DANFSe) ou a chave de acesso. Do PDF, tira a chave do texto e
baixa o XML pela API com o seu certificado (a nota precisa ser da sua empresa). O rascunho sai em
`~/.config/nfse-cli/rascunho.json` com um resumo em português; nada é gravado na configuração ainda.

**3. Salvar.** Antes de gravar, monta uma DPS de teste com a configuração, assina com um certificado temporário e
valida nos esquemas oficiais (os dois em uso). Recusa o que o nfse ainda não emite (MEI, ISS retido, retenções
federais, cliente no exterior...). Guarda uma cópia do `config.toml` anterior, mantém os outros clientes e não
troca de CNPJ sem `--substituir`. Se a nota modelo foi emitida por este aplicativo em produção, a numeração da
DPS continua dela.

## O rascunho

O mesmo formato serve para a nota modelo e para o caminho manual (que é o que a skill escreve com as suas
respostas):

```json
{
  "config": {
    "prestador": {"cnpj": "11222333000181", "cod_municipio": "3550308", "op_simp_nac": 3, "reg_ap_trib_sn": 1,
                  "reg_esp_trib": 0, "fone": "11999999999", "email": "contato@empresa.com.br"},
    "servico": {"c_trib_nac": "170101", "c_nbs": "114013900", "trib_issqn": 1, "tp_ret_issqn": 1,
                "tot_trib": {"modo": "sn", "percentual": "6.00"}}
  },
  "tomadores": {
    "cliente": {"documento": "11444777000161", "nome": "CLIENTE EXEMPLO LTDA", "email": "fiscal@cliente.com.br",
                "endereco": {"cod_municipio": "3550308", "cep": "01001000", "logradouro": "Praça da Sé",
                             "numero": "1", "bairro": "Sé"}}
  }
}
```

| Campo | O que é | Onde achar |
|---|---|---|
| `op_simp_nac` | 1 fora do Simples, 2 MEI, 3 ME/EPP | Cartão CNPJ ou contabilidade |
| `reg_ap_trib_sn` | Só ME/EPP: 1 federais e municipal pelo Simples | Contabilidade |
| `cod_municipio` | Código IBGE de 7 dígitos | `nfse municipio <nome>` |
| `c_trib_nac` | Código de tributação nacional, 6 dígitos | `nfse servico <palavras>` |
| `c_nbs` | Nomenclatura Brasileira de Serviços, 9 dígitos | `nfse nbs <palavras>` |
| `tot_trib` | Tributos aproximados: `sn` (percentual do Simples), `percentual`, `valor` ou `nao_informado` | Contabilidade |
| `p_aliq` | Alíquota do ISS; ME/EPP no Simples sem retenção não informa | Prefeitura ou contabilidade |

`nfse configurar mostrar` resume a configuração gravada em português.
