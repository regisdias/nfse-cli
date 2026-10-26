# Mudanças

Formato de [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em [SemVer](https://semver.org/lang/pt-BR/).

## [0.2.0] - 2026-10-26

### Adicionado
- Skill `nfse` para Claude Code, Codex e Antigravity (padrão Agent Skills), com configuração guiada e emissão
  mensal; `nfse skill instalar|remover`.
- `install.sh`: instalação de um comando, só no usuário, e desinstalação.
- `nfse notas`, `nfse arquivar` e `nfse email`: notas já emitidas, XML e PDF na pasta do cliente, rascunho do
  e-mail (Outlook no Mac ou `.eml`).
- Valor e descrição recorrentes por cliente (`[tomadores.<apelido>.recorrente]`), com `{mes}` e `{ano}`.
- E-mail no programa que a pessoa usa: Outlook e Mail (Mac), Thunderbird, Gmail e Outlook na web (mensagem
  preenchida e a pasta do PDF aberta), `.eml`; `nfse programas-de-email`; `nfse email --para` para testar.
- Aviso de versão nova (uma consulta por dia ao GitHub, desligável) e `nfse atualizar`, que atualiza o comando e
  a skill.
- Código de confirmação para produção: `nfse dps --producao` mostra, `nfse emitir --confirmacao` exige.
- `nfse configurar`: certificado (senha direto no Keychain), nota modelo pelo XML, PDF ou chave de acesso, e
  salvar com validação nos esquemas oficiais. Recusa o que ainda não sabe emitir.
- `nfse servico`, `nfse nbs` e `nfse municipio`: busca nas tabelas oficiais (Anexo B e IBGE), embutidas no pacote.
- Função para AWS Lambda (`nfse_lambda`), com certificado no Secrets Manager e empacotamento determinístico.
- Configuração a partir de dicionário (`nfse.config_de_dict`), a mesma para a CLI e a Lambda.
- PDF da nota (DANFSe) gerado a partir do XML, no leiaute da Nota Técnica 008.
- Esquemas da Nota Técnica 009 (homologação) ao lado dos de produção.
- `nfse consultar --serie`, para notas do Emissor Web.

### Corrigido
- O número da DPS é conferido na Sefin antes de usar: com a numeração local perdida, a Sefin devolveria a nota
  antiga no lugar da nova.
- O mesmo XML gera sempre o mesmo PDF (antes, a data de criação mudava o arquivo).
- Senha com acento guardada no Keychain: o `security` devolve em hexadecimal e agora é reconhecida.

## [0.1.0]

### Adicionado
- Biblioteca e linha de comando: montar, assinar, validar e enviar a DPS; consultar e baixar a NFS-e.
