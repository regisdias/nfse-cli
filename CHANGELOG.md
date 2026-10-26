# Mudanças

Formato de [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Função para AWS Lambda (`nfse_lambda`), com certificado no Secrets Manager e empacotamento determinístico.
- Configuração a partir de dicionário (`nfse.config_de_dict`), a mesma para a CLI e a Lambda.
- PDF da nota (DANFSe) gerado a partir do XML, no leiaute da Nota Técnica 008.
- Esquemas da Nota Técnica 009 (homologação) ao lado dos de produção.
- `nfse consultar --serie`, para notas do Emissor Web.

## [0.1.0]

### Adicionado
- Biblioteca e linha de comando: montar, assinar, validar e enviar a DPS; consultar e baixar a NFS-e.
