# PDF da nota (DANFSe)

**Gerar o PDF por conta própria é o caminho oficial, não um improviso.** O documento fiscal é o XML; o DANFSe
é só a representação impressa dele. A Nota Técnica 008 manda o software de emissão gerar o PDF, no leiaute que
ela define, e proíbe mostrar nele qualquer informação que não esteja no XML. Quem recebe confere a nota pelo QR
Code, que leva à consulta pública no site da NFS-e nacional.

A API de DANFSe do ADN foi suspensa em 03/08/2026: pela Nota Técnica SE/CGNFS-e nº 008, o PDF passou a ser
gerado pelo próprio software de emissão, no leiaute da NT. `nfse.gerar_danfse(xml)` faz isso (extra
`danfse`, que traz o reportlab; o núcleo continua só com lxml e cryptography):

- uma página A4, blocos e posições do item 2.4.5 da NT, QR Code para a consulta pública da nota;
- só mostra o que está no XML (a NT proíbe acrescentar informação); campo vazio vira `-`;
- blocos sem dados encolhem (notas 2 a 5) e a sobra vai para "Informações Complementares";
- homologação sai com "NFS-e SEM VALIDADE JURÍDICA" em vermelho.

Fontes: Helvetica (mesmas métricas da Arial pedida pela NT). Nome do município do tomador vem da tabela do IBGE
empacotada em `danfse_recursos/municipios.csv`. Ainda não faz as marcas d'água de cancelada/substituída: o XML
da nota não diz isso (é um evento à parte).
