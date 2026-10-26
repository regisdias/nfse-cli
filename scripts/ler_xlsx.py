"""Lê uma planilha .xlsx só com a biblioteca padrão: imprime as linhas de cada aba como TSV."""
import sys, zipfile
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def linhas(caminho, aba):
    with zipfile.ZipFile(caminho) as z:
        comp = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                comp.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        folha = ET.fromstring(z.read(f"xl/worksheets/sheet{aba}.xml"))
        for row in folha.iter(f"{{{NS['m']}}}row"):
            valores = {}
            for c in row.findall("m:c", NS):
                ref = "".join(ch for ch in c.get("r") if ch.isalpha())
                v = c.find("m:v", NS)
                if c.get("t") == "s" and v is not None:
                    texto = comp[int(v.text)]
                elif c.get("t") == "inlineStr":
                    texto = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                else:
                    texto = v.text if v is not None else ""
                valores[ref] = texto.replace("\t", " ").replace("\n", " ").strip()
            yield valores


if __name__ == "__main__":
    for l in linhas(sys.argv[1], sys.argv[2]):
        print("\t".join(f"{k}={v}" for k, v in sorted(l.items(), key=lambda kv: (len(kv[0]), kv[0])) if v))
