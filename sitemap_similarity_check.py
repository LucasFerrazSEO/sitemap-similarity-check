#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sitemap-similarity-check: mede o quanto as páginas de um site se parecem
entre si, página com página, seção com seção e título com título, depois de
tirar a interface e o texto que o template repete em todas as páginas.

O QUE FAZ
    Lê um sitemap (URL, sitemap index, .xml.gz, ou robots.txt com linhas
    Sitemap:), uma lista de URLs (--urls arquivo.txt) ou uma pasta de HTML
    local (--html-dir). Baixa as páginas com crawl educado (--delay,
    --max-urls, --include/--exclude por regex), extrai o CORPO PRINCIPAL
    (remove nav, header, footer, aside, form, script, style e blocos comuns
    de ruído: menu, cookie, sidebar, share, breadcrumb) e remove também os
    parágrafos e frases que se repetem em mais de X% das páginas
    (boilerplate do template, --boilerplate-ratio, padrão 0.5).

    Três leituras:
    a) página x página: TF-IDF + cosseno. Acima de --lsh-min páginas,
       MinHash/LSH com shingles de 5 palavras gera os pares candidatos e o
       cosseno roda só neles;
    b) seção x seção: divide cada página por H2 (e H3 com --by-h3) e compara
       blocos de páginas diferentes, apontando o heading das duas;
    c) título e H1: Jaccard de bigramas e trigramas de palavras, depois de
       tirar o sufixo de marca que se repete nos títulos.
    Opcional --semantic: embeddings locais (sentence-transformers,
    paraphrase-multilingual-MiniLM-L12-v2), só se estiver instalado.

MÉTODO
    Generalização de uma checagem interna de lucasferrazseo.com, usada para
    fazer valer a regra de canibalização do site e para conferir páginas de
    região e de nicho montadas sobre template antes de publicar. Stopwords
    pt-BR e um stemmer RSLP simplificado embutidos (--lang en troca para
    stopwords em inglês, sem stemmer). Os limiares padrão (0.80 página,
    0.85 seção, 0.60 título) são pontos de partida ajustáveis. O Google não
    publica percentual de duplicação, e nenhum destes números é limite dele.

USO
    python sitemap_similarity_check.py https://exemplo.com/sitemap.xml
    python sitemap_similarity_check.py https://exemplo.com/robots.txt --include "/blog/"
    python sitemap_similarity_check.py --urls urls.txt --delay 2
    python sitemap_similarity_check.py --html-dir examples/paginas
    python sitemap_similarity_check.py https://exemplo.com/sitemap.xml --csv pares.csv --json pares.json
    python sitemap_similarity_check.py https://exemplo.com/sitemap.xml --by-h3 --semantic
    python sitemap_similarity_check.py https://exemplo.com/sitemap.xml --strict   # saída 1 se houver par acima do limiar

LIMITAÇÕES
    HTML puro, sem executar JavaScript. A remoção de ruído é heurística e
    pode deixar sobra de interface ou cortar conteúdo real em página fora do
    padrão. Em páginas feitas sobre o mesmo template, o texto comum pode ser
    removido como boilerplate: o relatório mostra quanto foi removido, e
    --boilerplate-ratio 1 desliga essa remoção. Similaridade lexical não é
    julgamento de qualidade nem de intenção de busca.

Autor: Lucas Ferraz (lucasferraz.com).
Dependências: requests, beautifulsoup4 (lxml opcional); sentence-transformers
opcional para --semantic. Ver requirements.txt.
Licença: MIT.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print(
        "Dependência faltando. Instale com:\n"
        "    pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(2)

NOME = "sitemap-similarity-check"
UA = {"User-Agent": f"{NOME}/1.0 (+https://github.com/LucasFerrazSEO/{NOME})"}
TIMEOUT = 30

TAGS_DESCARTADAS = ["script", "style", "noscript", "template", "svg", "iframe",
                    "nav", "form", "aside", "button", "select"]
CLASSES_RUIDO = re.compile(
    r"(menu|navbar|breadcrumb|cookie|consent|offcanvas|sidebar|widget|"
    r"share|sharing|social|skip-link|popup|modal|newsletter)",
    re.I,
)
PROTEGIDAS = {"html", "body", "main", "article"}
BLOCOS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre",
          "td", "th", "dt", "dd", "figcaption"]
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

STOP_PT = set("""
a à ao aos aquela aquelas aquele aqueles aquilo as às até com como da das de
dela delas dele deles depois do dos e é ela elas ele eles em entre era eram
essa essas esse esses esta está estão estas estava este estes eu foi foram
há isso isto já lhe lhes mais mas me mesmo meu meus minha minhas muito na nas
não nem no nos nós nossa nossas nosso nossos num numa o os ou para pela pelas
pelo pelos por qual quando que quem se sem ser será seu seus só sua suas também
te tem têm ter teu tua um uma umas uns você vocês vos cada sobre sob após
porque pois então ainda assim onde como tudo todo toda todos todas outro outra
outros outras seja são sendo sido tinha tinham fazer faz feito pode podem
deve devem vai vão bem aqui ali lá
""".split())
STOP_EN = set("""
a about above after again against all am an and any are as at be because been
before being below between both but by can could did do does doing down during
each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no
nor not now of off on once only or other our ours ourselves out over own same
she should so some such than that the their theirs them themselves then there
these they this those through to too under until up very was we were what when
where which while who whom why will with would you your yours yourself
yourselves also may might must shall us get got
""".split())


# ---------------------------------------------------------------------------
# Stemmer RSLP simplificado (Orengo e Huyck, 2001), subconjunto das regras.
# Cada regra: (sufixo, tamanho mínimo do radical, substituição, exceções)
# ---------------------------------------------------------------------------
R_PLURAL = [
    ("ns", 1, "m", ()), ("ões", 3, "ão", ()), ("ães", 1, "ão", ("mães",)),
    ("ais", 1, "al", ("cais", "mais")), ("éis", 2, "el", ()), ("eis", 2, "el", ()),
    ("óis", 2, "ol", ()), ("is", 2, "il", ("lápis", "cais", "mais", "pois", "depois", "dois", "leis")),
    ("les", 3, "l", ()), ("res", 3, "r", ()),
    ("s", 2, "", ("aliás", "pires", "lápis", "cais", "mais", "mas", "menos", "férias",
                  "gás", "atrás", "através", "país", "após", "ambas", "ambos", "ônibus", "vírus")),
]
R_FEMININO = [
    ("ona", 3, "ão", ()), ("ã", 2, "ão", ()), ("ora", 3, "or", ()), ("na", 4, "no", ()),
    ("inha", 3, "inho", ()), ("esa", 3, "ês", ("mesa", "empresa", "presa", "defesa", "despesa", "surpresa", "princesa")), ("osa", 3, "oso", ()), ("íaca", 3, "íaco", ()),
    ("ica", 3, "ico", ()), ("ada", 2, "ado", ()), ("ida", 3, "ido", ()), ("ída", 3, "ido", ()),
    ("ima", 3, "imo", ()), ("iva", 3, "ivo", ()), ("eira", 3, "eiro", ()),
]
R_ADVERBIO = [("mente", 4, "", ())]
R_GRAU = [
    ("díssimo", 5, "", ()), ("abilíssimo", 5, "", ()), ("íssimo", 3, "", ()), ("ésimo", 3, "", ()),
    ("érrimo", 4, "", ()), ("zinho", 2, "", ()), ("quinho", 4, "c", ()), ("uinho", 4, "", ()),
    ("adinho", 3, "", ()), ("inho", 3, "", ()), ("alhão", 4, "", ()), ("uça", 4, "", ()),
    ("aço", 4, "", ()), ("aça", 4, "", ()), ("adão", 4, "", ()), ("idão", 4, "", ()),
    ("zão", 2, "", ()), ("arrão", 4, "", ()), ("zito", 2, "", ()), ("ito", 3, "", ()),
]
R_NOME = [
    ("encialista", 4, "", ()), ("alista", 5, "", ()), ("agem", 3, "", ()), ("iamento", 4, "", ()),
    ("amento", 3, "", ()), ("imento", 3, "", ()), ("uamento", 4, "", ()), ("alizado", 4, "", ()),
    ("atizado", 4, "", ()), ("izado", 5, "", ()), ("ativo", 4, "", ()), ("tivo", 4, "", ()),
    ("ivo", 4, "", ()), ("ado", 2, "", ()), ("ido", 3, "", ()), ("ador", 3, "", ()),
    ("edor", 3, "", ()), ("idor", 4, "", ()), ("dor", 4, "", ()), ("sor", 4, "", ()),
    ("atória", 5, "", ()), ("tor", 3, "", ()), ("ante", 2, "", ()), ("ância", 3, "", ()),
    ("ência", 3, "", ()), ("ista", 4, "", ()), ("ismo", 3, "", ()), ("ização", 5, "", ()),
    ("ação", 3, "", ()), ("ução", 3, "", ()), ("ável", 2, "", ()), ("ível", 5, "", ()),
    ("idade", 4, "", ()), ("eza", 3, "", ()), ("ez", 4, "", ()), ("ual", 3, "", ()),
    ("ial", 3, "", ()), ("al", 4, "", ()), ("ário", 3, "", ()), ("ério", 6, "", ()),
    ("ês", 4, "", ()), ("vel", 5, "", ()), ("ico", 4, "", ()), ("oso", 3, "", ()),
    ("esco", 4, "", ()), ("ente", 4, "", ()), ("eiro", 3, "", ()), ("ão", 3, "", ()),
]
R_VERBO = [
    ("aríamos", 2, "", ()), ("eríamos", 2, "", ()), ("iríamos", 3, "", ()), ("ássemos", 2, "", ()),
    ("êssemos", 2, "", ()), ("íssemos", 3, "", ()), ("aremos", 2, "", ()), ("eremos", 2, "", ()),
    ("iremos", 3, "", ()), ("ávamos", 2, "", ()), ("íamos", 3, "", ()), ("aram", 2, "", ()),
    ("eram", 3, "", ()), ("iram", 3, "", ()), ("avam", 2, "", ()), ("arem", 2, "", ()),
    ("erem", 3, "", ()), ("irem", 3, "", ()), ("ando", 2, "", ()), ("endo", 3, "", ()),
    ("indo", 3, "", ()), ("ondo", 3, "", ()), ("amos", 2, "", ()), ("emos", 2, "", ()),
    ("imos", 3, "", ()), ("ar", 2, "", ()), ("er", 2, "", ()), ("ir", 3, "", ()),
    ("ou", 3, "", ()), ("am", 2, "", ()), ("em", 2, "", ()), ("ei", 3, "", ()),
    ("iu", 3, "", ()), ("eu", 3, "", ()), ("ia", 3, "", ()), ("ou", 2, "", ()),
]
R_VOGAL = [("a", 3, "", ()), ("e", 3, "", ()), ("o", 3, "", ())]


def _aplica(palavra: str, regras: list) -> tuple[str, bool]:
    for suf, minimo, troca, excecoes in regras:
        if palavra.endswith(suf) and len(palavra) - len(suf) >= minimo and palavra not in excecoes:
            return palavra[: len(palavra) - len(suf)] + troca, True
    return palavra, False


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


_CACHE_STEM: dict[str, str] = {}


def rslp(palavra: str) -> str:
    if palavra in _CACHE_STEM:
        return _CACHE_STEM[palavra]
    p = palavra
    if len(p) > 3:
        if p.endswith("s"):
            p, _ = _aplica(p, R_PLURAL)
        if p.endswith("a"):
            p, _ = _aplica(p, R_FEMININO)
        p, _ = _aplica(p, R_GRAU)
        p, _ = _aplica(p, R_ADVERBIO)
        p, mudou = _aplica(p, R_NOME)
        if not mudou:
            p, mudou = _aplica(p, R_VERBO)
            if not mudou:
                p, _ = _aplica(p, R_VOGAL)
    p = sem_acento(p)
    _CACHE_STEM[palavra] = p
    return p


RE_PALAVRA = re.compile(r"[^\W\d_]+", re.UNICODE)


def palavras(texto: str) -> list[str]:
    return RE_PALAVRA.findall(texto.lower())


def termos(texto: str, lang: str) -> list[str]:
    """Palavras sem stopword, com stemmer em pt."""
    stop = STOP_PT if lang == "pt" else STOP_EN
    out = []
    for w in palavras(texto):
        if w in stop or len(w) < 2:
            continue
        out.append(rslp(w) if lang == "pt" else w)
    return out


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
class Cliente:
    def __init__(self, delay: float):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.delay = delay
        self._ultimo = 0.0
        self.erros: list[tuple[str, str]] = []

    def get(self, url: str) -> "requests.Response | None":
        for tentativa in (1, 2):
            espera = self.delay - (time.monotonic() - self._ultimo)
            if espera > 0:
                time.sleep(espera)
            try:
                r = self.s.get(url, timeout=TIMEOUT)
            except requests.RequestException as exc:
                self._ultimo = time.monotonic()
                self.erros.append((url, f"erro de rede: {exc.__class__.__name__}"))
                return None
            self._ultimo = time.monotonic()
            if r.status_code == 429 and tentativa == 1:
                ra = r.headers.get("Retry-After", "")
                pausa = int(ra) if ra.isdigit() else 30
                pausa = max(5, min(pausa, 120))
                print(f"  429 em {url}: esperando {pausa}s e tentando de novo uma vez", file=sys.stderr)
                time.sleep(pausa)
                continue
            if r.status_code == 429:
                self.erros.append((url, "429 (limite de requisições), aumente --delay"))
                return None
            return r
        return None


def xml_de_resposta(r: "requests.Response") -> bytes:
    dados = r.content
    if dados[:2] == b"\x1f\x8b":
        dados = gzip.decompress(dados)
    return dados


def sem_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def le_sitemap(cli: Cliente, url: str, visitados: set[str], limite_sitemaps: int = 500) -> list[str]:
    if url in visitados or len(visitados) >= limite_sitemaps:
        return []
    visitados.add(url)
    r = cli.get(url)
    if r is None or r.status_code != 200:
        if r is not None:
            cli.erros.append((url, f"sitemap respondeu {r.status_code}"))
        return []
    if urlparse(url).path.endswith("robots.txt"):
        filhos = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
        out: list[str] = []
        for f in filhos:
            out += le_sitemap(cli, f.strip(), visitados, limite_sitemaps)
        return out
    try:
        raiz = ET.fromstring(xml_de_resposta(r))
    except (ET.ParseError, OSError) as exc:
        cli.erros.append((url, f"XML inválido: {exc}"))
        return []
    locs: list[str] = []
    if sem_ns(raiz.tag) == "sitemapindex":
        for sm in raiz:
            loc = next((c.text for c in sm if sem_ns(c.tag) == "loc" and c.text), None)
            if loc:
                locs += le_sitemap(cli, loc.strip(), visitados, limite_sitemaps)
    else:
        for u in raiz:
            loc = next((c.text for c in u if sem_ns(c.tag) == "loc" and c.text), None)
            if loc:
                locs.append(loc.strip())
    return locs


# ---------------------------------------------------------------------------
# Extração do corpo principal
# ---------------------------------------------------------------------------
def escolhe_parser() -> str:
    try:
        BeautifulSoup("<i></i>", "lxml")
        return "lxml"
    except Exception:  # noqa: BLE001
        return "html.parser"


PARSER = escolhe_parser()


@dataclass
class Pagina:
    url: str
    titulo: str = ""
    h1: str = ""
    blocos: list[tuple[str, str]] = field(default_factory=list)  # (tag, texto)
    corpo: str = ""
    corpo_bruto: str = ""
    palavras_brutas: int = 0
    palavras_finais: int = 0
    secoes: list[tuple[str, str]] = field(default_factory=list)  # (heading, texto)
    headings: list[str] = field(default_factory=list)


def texto_de(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def extrai_pagina(url: str, html: str) -> Pagina:
    soup = BeautifulSoup(html, PARSER)
    pag = Pagina(url=url)
    pag.titulo = texto_de(soup.title) if soup.title else ""
    h1 = soup.find("h1")
    pag.h1 = texto_de(h1) if h1 else ""

    for tag in soup(TAGS_DESCARTADAS):
        tag.decompose()
    # header e footer do site saem; os de dentro de article/main ficam, exceto footer
    for tag in soup.find_all(["header", "footer"]):
        if tag.name == "footer" or not tag.find_parent(["article", "main"]):
            tag.decompose()
    for attr in ("class", "id"):
        for el in soup.find_all(attrs={attr: CLASSES_RUIDO}):
            if el.name not in PROTEGIDAS and not el.decomposed:
                el.decompose()
    for el in soup.find_all(attrs={"role": re.compile(r"navigation|banner|contentinfo|complementary", re.I)}):
        if el.name not in PROTEGIDAS and not el.decomposed:
            el.decompose()

    raiz = soup.find("main") or soup.find("article") or soup.body or soup
    for el in raiz.find_all(BLOCOS):
        if el.find_parent(BLOCOS):
            continue
        t = texto_de(el)
        if t:
            pag.blocos.append((el.name, t))
    if not pag.blocos:
        t = texto_de(raiz)
        if t:
            pag.blocos.append(("p", t))
    pag.corpo_bruto = "\n".join(t for tag, t in pag.blocos if tag not in HEADINGS)
    pag.palavras_brutas = len(palavras(pag.corpo_bruto))
    return pag


# ---------------------------------------------------------------------------
# Boilerplate: blocos e frases repetidos em mais de X% das páginas
# ---------------------------------------------------------------------------
RE_FRASE = re.compile(r"(?<=[.!?])\s+")


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower()).strip()


def remove_boilerplate(paginas: list[Pagina], ratio: float, min_paginas: int) -> tuple[int, int, list]:
    """Tira blocos e frases presentes em mais de `ratio` das páginas.
    Devolve (n blocos, n frases, lista dos trechos removidos com contagem)."""
    n = len(paginas)
    if ratio >= 1 or n < min_paginas:
        for p in paginas:
            finaliza(p, set(), set())
        return 0, 0, []
    df_bloco: Counter = Counter()
    df_frase: Counter = Counter()
    for p in paginas:
        bl = {norm(t) for tag, t in p.blocos if tag not in HEADINGS}
        fr = set()
        for tag, t in p.blocos:
            if tag in HEADINGS:
                continue
            for f in RE_FRASE.split(t):
                if len(palavras(f)) >= 6:
                    fr.add(norm(f))
        df_bloco.update(bl)
        df_frase.update(fr)
    corte = ratio * n
    blocos_bp = {b for b, c in df_bloco.items() if c > corte}
    frases_bp = {f for f, c in df_frase.items() if c > corte}
    for p in paginas:
        finaliza(p, blocos_bp, frases_bp)
    removidos = [(c, b) for b, c in df_bloco.items() if c > corte]
    removidos += [(c, f) for f, c in df_frase.items() if c > corte
                  and not any(f in b for b in blocos_bp)]
    removidos.sort(key=lambda x: (-x[0], -len(x[1])))
    return len(blocos_bp), len(frases_bp), removidos


def finaliza(p: Pagina, blocos_bp: set, frases_bp: set) -> None:
    limpos: list[tuple[str, str]] = []
    for tag, t in p.blocos:
        if tag in HEADINGS:
            limpos.append((tag, t))
            continue
        if norm(t) in blocos_bp:
            continue
        if frases_bp:
            partes = [f for f in RE_FRASE.split(t) if norm(f) not in frases_bp]
            t = " ".join(partes).strip()
        if t:
            limpos.append((tag, t))
    # p.blocos fica intacto: seções e score_bruto usam o corpo principal inteiro
    p.corpo ="\n".join(t for tag, t in limpos if tag not in HEADINGS)
    p.palavras_finais = len(palavras(p.corpo))
    p.headings = [t for tag, t in limpos if tag in ("h2", "h3")]


def monta_secoes(p: Pagina, by_h3: bool) -> None:
    cortes = {"h2", "h3"} if by_h3 else {"h2"}
    atual, textos = "(abertura)", []
    secoes = []
    for tag, t in p.blocos:
        if tag in cortes:
            if textos:
                secoes.append((atual, " ".join(textos)))
            atual, textos = t, []
        elif tag in HEADINGS:
            continue
        else:
            textos.append(t)
    if textos:
        secoes.append((atual, " ".join(textos)))
    p.secoes = secoes


# ---------------------------------------------------------------------------
# TF-IDF, cosseno, MinHash/LSH, Jaccard
# ---------------------------------------------------------------------------
def tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
    vetores = []
    for d in docs:
        tf = Counter(d)
        v = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
        norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vetores.append({t: x / norma for t, x in v.items()})
    return vetores


def cosseno(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


_P = (1 << 61) - 1


def minhash(tokens: list[str], params: list[tuple[int, int]], k: int = 5) -> list[int]:
    if len(tokens) < k:
        shingles = {" ".join(tokens)}
    else:
        shingles = {" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}
    base = [int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big") for s in shingles]
    return [min((a * x + b) % _P for x in base) for a, b in params]


def candidatos_lsh(docs_tokens: list[list[str]], perms: int = 128, linhas: int = 2) -> set[tuple[int, int]]:
    rnd = random.Random(20260928)
    params = [(rnd.randrange(1, _P), rnd.randrange(0, _P)) for _ in range(perms)]
    assinaturas = [minhash(t, params) for t in docs_tokens]
    pares: set[tuple[int, int]] = set()
    for banda in range(perms // linhas):
        baldes: dict[tuple, list[int]] = defaultdict(list)
        for i, sig in enumerate(assinaturas):
            baldes[tuple(sig[banda * linhas:(banda + 1) * linhas])].append(i)
        for idx in baldes.values():
            if 1 < len(idx) <= 200:
                for x in range(len(idx)):
                    for y in range(x + 1, len(idx)):
                        pares.add((idx[x], idx[y]))
    return pares


def ngramas(texto: str) -> set[str]:
    w = [sem_acento(x) for x in palavras(texto)]
    out = set()
    for k in (2, 3):
        out |= {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}
    if not out and w:
        out = set(w)
    return out


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


RE_SEP_TITULO = re.compile(r"\s+[|\-–—·:»]\s+")


def tira_sufixo_marca(titulos: list[str]) -> list[str]:
    """Remove o segmento de título (separado por barra vertical ou hífen) comum a mais da metade."""
    cont: Counter = Counter()
    for t in titulos:
        partes = RE_SEP_TITULO.split(t)
        if len(partes) > 1:
            cont[partes[-1].strip().lower()] += 1
            cont[partes[0].strip().lower()] += 1
    comuns = {s for s, c in cont.items() if c > len(titulos) / 2}
    out = []
    for t in titulos:
        partes = [x for x in RE_SEP_TITULO.split(t) if x.strip().lower() not in comuns]
        out.append(" ".join(partes) if partes else t)
    return out


# ---------------------------------------------------------------------------
# Semântico (opcional)
# ---------------------------------------------------------------------------
MODELO = "paraphrase-multilingual-MiniLM-L12-v2"


def semantico(paginas: list[Pagina]):
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("  --semantic ignorado: sentence-transformers não está instalado "
              "(pip install sentence-transformers). Seguindo só no lexical.", file=sys.stderr)
        return None
    try:
        modelo = SentenceTransformer(MODELO)
    except Exception as exc:  # noqa: BLE001
        print(f"  --semantic ignorado: não consegui carregar o modelo {MODELO} ({exc}).", file=sys.stderr)
        return None
    vetores = []
    for p in paginas:
        partes = [t for _, t in p.secoes] or [p.corpo or p.titulo]
        emb = modelo.encode(partes, normalize_embeddings=True, show_progress_bar=False)
        v = emb.mean(axis=0)
        vetores.append(v / (np.linalg.norm(v) or 1.0))
    m = np.vstack(vetores)
    return m @ m.T


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def curto(url: str) -> str:
    p = urlparse(url)
    if p.scheme in ("http", "https"):
        return (p.path or "/") + (("?" + p.query) if p.query else "")
    return os.path.basename(url)


def coleta_urls(args, cli: Cliente) -> list[str]:
    if args.urls:
        with open(args.urls, encoding="utf-8") as fh:
            urls = [x.strip() for x in fh if x.strip() and not x.lstrip().startswith("#")]
    else:
        urls = le_sitemap(cli, args.sitemap, set())
    vistos, out = set(), []
    inc = re.compile(args.include) if args.include else None
    exc = re.compile(args.exclude) if args.exclude else None
    for u in urls:
        if u in vistos:
            continue
        vistos.add(u)
        if inc and not inc.search(u):
            continue
        if exc and exc.search(u):
            continue
        out.append(u)
    return out[: args.max_urls]


def baixa(urls: list[str], cli: Cliente) -> list[Pagina]:
    paginas: list[Pagina] = []
    finais: set[str] = set()
    for i, u in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {u}", file=sys.stderr)
        r = cli.get(u)
        if r is None:
            continue
        if r.status_code != 200:
            cli.erros.append((u, f"respondeu {r.status_code}"))
            continue
        if "html" not in r.headers.get("Content-Type", "").lower():
            cli.erros.append((u, "não é HTML"))
            continue
        if r.url in finais:
            cli.erros.append((u, f"redireciona para URL já lida ({r.url})"))
            continue
        finais.add(r.url)
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
        paginas.append(extrai_pagina(u, r.text))
    return paginas


def le_pasta(pasta: str, max_urls: int) -> list[Pagina]:
    nomes = sorted(n for n in os.listdir(pasta) if n.lower().endswith((".html", ".htm")))
    out = []
    for n in nomes[:max_urls]:
        with open(os.path.join(pasta, n), encoding="utf-8", errors="replace") as fh:
            out.append(extrai_pagina(n, fh.read()))
    return out


def main() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Similaridade entre páginas de um sitemap: página, seção e título/H1, sem o boilerplate do template."
    )
    ap.add_argument("sitemap", nargs="?", default="",
                    help="URL do sitemap, do sitemap index (.xml ou .xml.gz) ou do robots.txt")
    ap.add_argument("--urls", default="", help="arquivo .txt com uma URL por linha (em vez do sitemap)")
    ap.add_argument("--html-dir", default="", help="pasta com arquivos .html locais (sem rede)")
    ap.add_argument("--max-urls", type=int, default=200, help="máximo de páginas lidas (padrão 200)")
    ap.add_argument("--delay", type=float, default=1.0, help="segundos entre requisições (padrão 1.0)")
    ap.add_argument("--include", default="", help="regex: só URLs que casam")
    ap.add_argument("--exclude", default="", help="regex: descarta URLs que casam")
    ap.add_argument("--lang", choices=("pt", "en"), default="pt",
                    help="pt: stopwords pt-BR + stemmer RSLP simplificado (padrão); en: stopwords em inglês, sem stemmer")
    ap.add_argument("--threshold", type=float, default=0.80, help="limiar página x página (padrão 0.80)")
    ap.add_argument("--section-threshold", type=float, default=0.85, help="limiar seção x seção (padrão 0.85)")
    ap.add_argument("--title-threshold", type=float, default=0.60, help="limiar título/H1 (padrão 0.60)")
    ap.add_argument("--semantic-threshold", type=float, default=0.90, help="limiar do --semantic (padrão 0.90)")
    ap.add_argument("--boilerplate-ratio", type=float, default=0.50,
                    help="remove blocos/frases presentes em mais desta fração das páginas (padrão 0.50; 1 desliga)")
    ap.add_argument("--boilerplate-min-pages", type=int, default=5,
                    help="só remove boilerplate com pelo menos N páginas (padrão 5)")
    ap.add_argument("--by-h3", action="store_true", help="divide seções também por H3")
    ap.add_argument("--min-words", type=int, default=50, help="página com menos palavras úteis fica fora (padrão 50)")
    ap.add_argument("--min-section-words", type=int, default=30, help="seção com menos palavras fica fora (padrão 30)")
    ap.add_argument("--sitewide-ratio", type=float, default=0.90,
                    help="seção idêntica em mais desta fração das páginas sai da comparação de seções (padrão 0.90)")
    ap.add_argument("--lsh-min", type=int, default=150,
                    help="a partir de N páginas usa MinHash/LSH para gerar candidatos (padrão 150)")
    ap.add_argument("--semantic", action="store_true",
                    help=f"também calcula similaridade semântica local ({MODELO}), se instalado")
    ap.add_argument("--top", type=int, default=10, help="quantos pares mostrar no terminal (padrão 10)")
    ap.add_argument("--csv", default="", help="grava os pares em CSV")
    ap.add_argument("--json", default="", help="grava o resultado completo em JSON")
    ap.add_argument("--strict", action="store_true",
                    help="código de saída 1 se houver par de página ou de seção acima do limiar")
    args = ap.parse_args()

    fontes = sum(bool(x) for x in (args.sitemap, args.urls, args.html_dir))
    if fontes != 1:
        ap.error("informe exatamente uma fonte: URL do sitemap, --urls ou --html-dir")

    cli = Cliente(args.delay)
    if args.html_dir:
        origem = args.html_dir
        paginas = le_pasta(args.html_dir, args.max_urls)
        n_urls = len(paginas)
    else:
        origem = args.sitemap or args.urls
        urls = coleta_urls(args, cli)
        n_urls = len(urls)
        if not urls:
            print("Nenhuma URL encontrada (confira o sitemap e os filtros --include/--exclude).", file=sys.stderr)
            for u, e in cli.erros:
                print(f"  {u}: {e}", file=sys.stderr)
            sys.exit(2)
        paginas = baixa(urls, cli)

    curtas = [p for p in paginas if p.palavras_brutas < args.min_words]
    paginas = [p for p in paginas if p.palavras_brutas >= args.min_words]
    n_bp_blocos, n_bp_frases, removidos = remove_boilerplate(paginas, args.boilerplate_ratio,
                                                             args.boilerplate_min_pages)
    pouco_proprio = [p for p in paginas if p.palavras_finais < args.min_words]
    for p in paginas:
        monta_secoes(p, args.by_h3)
    n = len(paginas)
    if n < 2:
        print(f"Só {n} página(s) com texto suficiente para comparar.", file=sys.stderr)
        sys.exit(2)

    # a) página x página
    vet = tfidf([termos(p.corpo, args.lang) for p in paginas])
    vet_b = tfidf([termos(p.corpo_bruto, args.lang) for p in paginas])
    if n >= args.lsh_min:
        cand = candidatos_lsh([palavras(p.corpo_bruto) for p in paginas])
        modo = f"MinHash/LSH gerou {len(cand)} candidato(s) de {n * (n - 1) // 2} pares possíveis"
    else:
        cand = {(i, j) for i in range(n) for j in range(i + 1, n)}
        modo = f"{len(cand)} pares (todos contra todos)"

    # c) título/H1 (todos os pares, é barato)
    tit = tira_sufixo_marca([p.titulo for p in paginas])
    ng_t = [ngramas(t) for t in tit]
    ng_h = [ngramas(p.h1) for p in paginas]

    def score_titulo(i: int, j: int) -> float:
        return max(jaccard(ng_t[i], ng_t[j]), jaccard(ng_h[i], ng_h[j]))

    def par(i: int, j: int) -> dict:
        return {"score_pagina": cosseno(vet[i], vet[j]), "score_bruto": cosseno(vet_b[i], vet_b[j]),
                "score_titulo": score_titulo(i, j)}

    pares: dict[tuple[int, int], dict] = {k: par(*k) for k in cand}
    titulos_altos = []
    for i in range(n):
        for j in range(i + 1, n):
            st = score_titulo(i, j)
            if st >= args.title_threshold:
                titulos_altos.append((st, i, j))
                if (i, j) not in pares:
                    pares[(i, j)] = par(i, j)

    # b) seção x seção
    # seção de texto idêntico em mais de --sitewide-ratio das páginas (caixa de autor,
    # CTA fixo) sai da comparação e aparece uma vez só no relatório
    df_secao: Counter = Counter()
    for p in paginas:
        df_secao.update({norm(t) for _, t in p.secoes})
    sitewide = {t for t, c in df_secao.items()
                if n >= args.boilerplate_min_pages and c > args.sitewide_ratio * n}
    secoes_sitewide = sorted({(df_secao[norm(t)], h) for p in paginas for h, t in p.secoes
                              if norm(t) in sitewide}, reverse=True)
    secoes = [(pi, h, t) for pi, p in enumerate(paginas) for h, t in p.secoes
              if len(palavras(t)) >= args.min_section_words and norm(t) not in sitewide]
    sdocs = [termos(t, args.lang) for _, _, t in secoes]
    svet = tfidf(sdocs)
    postings: dict[str, list[int]] = defaultdict(list)
    for si, d in enumerate(sdocs):
        for t in set(d):
            postings[t].append(si)
    teto = max(50, int(0.2 * len(secoes)))
    scand: set[tuple[int, int]] = set()
    for lista in postings.values():
        if len(lista) > teto:
            continue
        for x in range(len(lista)):
            for y in range(x + 1, len(lista)):
                a, b = lista[x], lista[y]
                if secoes[a][0] != secoes[b][0]:
                    scand.add((a, b))
    secoes_altas = []
    for a, b in scand:
        s = cosseno(svet[a], svet[b])
        if s >= args.section_threshold:
            secoes_altas.append((s, a, b))
    secoes_altas.sort(reverse=True)

    sem = semantico(paginas) if args.semantic else None

    paginas_altas = sorted(((max(v["score_pagina"], v["score_bruto"]), k) for k, v in pares.items()
                            if max(v["score_pagina"], v["score_bruto"]) >= args.threshold), reverse=True)
    titulos_altos.sort(reverse=True)
    semanticos_altos = []
    if sem is not None:
        for i in range(n):
            for j in range(i + 1, n):
                if sem[i, j] >= args.semantic_threshold:
                    semanticos_altos.append((float(sem[i, j]), i, j))
        semanticos_altos.sort(reverse=True)

    bruto = sum(p.palavras_brutas for p in paginas) or 1
    final = sum(p.palavras_finais for p in paginas)
    pct_bp = 100 * (1 - final / bruto)

    # ---------------- relatório ----------------
    print(f"\n=== {NOME}: {origem} ===")
    print(f"URLs na fila: {n_urls} | páginas comparadas: {n} | fora por corpo vazio (< {args.min_words} palavras): "
          f"{len(curtas)} | falhas: {len(cli.erros)}")
    if args.boilerplate_ratio < 1 and n >= args.boilerplate_min_pages:
        print(f"Boilerplate: {n_bp_blocos} bloco(s) e {n_bp_frases} frase(s) presentes em mais de "
              f"{args.boilerplate_ratio:.0%} das páginas, {pct_bp:.0f}% do texto do corpo principal")
        if pct_bp > 50:
            print("  ATENÇÃO  mais da metade do corpo principal é texto comum a muitas páginas."
                  " Em páginas de região ou de nicho feitas sobre template, esse já é o sinal de duplicação.")
        if pouco_proprio:
            print(f"  ATENÇÃO  {len(pouco_proprio)} página(s) com menos de {args.min_words} palavras próprias"
                  " depois de tirar o texto comum:")
            for p in pouco_proprio[: args.top]:
                print(f"           {curto(p.url)} ({p.palavras_finais} de {p.palavras_brutas} palavras)")
        if removidos:
            print("  Trechos comuns mais repetidos:")
            for c, t in removidos[:5]:
                print(f"    {c}/{n} páginas  \"{t[:80]}{'...' if len(t) > 80 else ''}\"")
    else:
        print("Boilerplate: remoção desligada (ratio 1 ou menos páginas que --boilerplate-min-pages)")
    print(f"Leitura página x página: {modo}\n")
    print(f"Página x página (TF-IDF cosseno >= {args.threshold:.2f}, sem boilerplate ou corpo inteiro): "
          f"{len(paginas_altas)} par(es)")
    print(f"Seção x seção   (TF-IDF cosseno >= {args.section_threshold:.2f}): {len(secoes_altas)} par(es) "
          f"em {len(secoes)} seções de {'H2/H3' if args.by_h3 else 'H2'}")
    if secoes_sitewide:
        print(f"                  {len(secoes_sitewide)} seção(ões) idêntica(s) em mais de {args.sitewide_ratio:.0%} "
              f"das páginas ficaram fora da comparação, por exemplo \"{secoes_sitewide[0][1][:50]}\"")
    print(f"Título/H1       (Jaccard 2-3-gramas >= {args.title_threshold:.2f}): {len(titulos_altos)} par(es)")
    if sem is not None:
        print(f"Semântico       (cosseno de embeddings >= {args.semantic_threshold:.2f}): {len(semanticos_altos)} par(es)")

    if paginas_altas:
        print(f"\nTop {args.top} pares de página:")
        for s, (i, j) in paginas_altas[: args.top]:
            v = pares[(i, j)]
            print(f"  {s:.2f}  {curto(paginas[i].url)}  x  {curto(paginas[j].url)}  "
                  f"(sem boilerplate {v['score_pagina']:.2f}, corpo inteiro {v['score_bruto']:.2f}, "
                  f"título {v['score_titulo']:.2f})")
    if secoes_altas:
        # agrupa os pares em componentes: "esta seção se repete em K páginas"
        pai = list(range(len(secoes)))

        def raiz(x: int) -> int:
            while pai[x] != x:
                pai[x] = pai[pai[x]]
                x = pai[x]
            return x

        soma: dict[int, list[float]] = defaultdict(list)
        for s, a, b in secoes_altas:
            pai[raiz(a)] = raiz(b)
        for s, a, b in secoes_altas:
            soma[raiz(a)].append(s)
        grupos: dict[int, list[int]] = defaultdict(list)
        for si in {x for _, a, b in secoes_altas for x in (a, b)}:
            grupos[raiz(si)].append(si)
        ordem = sorted(grupos.items(), key=lambda kv: (-len({secoes[x][0] for x in kv[1]}),
                                                       -sum(soma[kv[0]]) / len(soma[kv[0]])))
        print(f"\nSeções repetidas, agrupadas ({len(grupos)} grupo(s); top {args.top}):")
        for g, membros in ordem[: args.top]:
            pags = sorted({secoes[x][0] for x in membros})
            media = sum(soma[g]) / len(soma[g])
            ex = secoes[membros[0]]
            print(f"  {len(pags)} páginas | média {media:.2f} | \"{ex[1][:60]}\"")
            print(f"      ex.: {', '.join(curto(paginas[p].url) for p in pags[:3])}"
                  f"{' ...' if len(pags) > 3 else ''}")
        print(f"\nTop {args.top} pares de seção:")
        for s, a, b in secoes_altas[: args.top]:
            pa, ha, _ = secoes[a]
            pb, hb, _ = secoes[b]
            print(f"  {s:.2f}  {curto(paginas[pa].url)} \"{ha[:60]}\"\n        x {curto(paginas[pb].url)} \"{hb[:60]}\"")
    if titulos_altos:
        print(f"\nTop {args.top} títulos/H1 parecidos:")
        for s, i, j in titulos_altos[: args.top]:
            print(f"  {s:.2f}  \"{tit[i][:55]}\"  x  \"{tit[j][:55]}\"")
    if semanticos_altos:
        print(f"\nTop {args.top} pares semânticos:")
        for s, i, j in semanticos_altos[: args.top]:
            print(f"  {s:.2f}  {curto(paginas[i].url)}  x  {curto(paginas[j].url)}")
    if cli.erros:
        print("\nFalhas:")
        for u, e in cli.erros[:20]:
            print(f"  {u}: {e}")
        if len(cli.erros) > 20:
            print(f"  ... e mais {len(cli.erros) - 20}")
    print("\n(Limiares são ponto de partida ajustável, não limite do Google. Leia os pares antes de decidir.)")

    # ---------------- saídas ----------------
    linhas = []
    secoes_por_par: dict[tuple[int, int], list] = defaultdict(list)
    for s, a, b in secoes_altas:
        i, j = sorted((secoes[a][0], secoes[b][0]))
        ha, hb = (secoes[a][1], secoes[b][1]) if secoes[a][0] == i else (secoes[b][1], secoes[a][1])
        secoes_por_par[(i, j)].append((ha, hb, s))
    chaves = {k for s, k in paginas_altas} | {(i, j) for _, i, j in titulos_altos} | set(secoes_por_par)
    for k in chaves:
        if k not in pares:
            pares[k] = par(*k)
    for i, j in sorted(chaves, key=lambda k: -max(pares[k]["score_pagina"], pares[k]["score_bruto"])):
        v = pares[(i, j)]
        base = {"url_a": paginas[i].url, "url_b": paginas[j].url, "score_pagina": round(v["score_pagina"], 4),
                "score_titulo": round(v["score_titulo"], 4), "score_bruto": round(v["score_bruto"], 4)}
        if sem is not None:
            base["score_semantico"] = round(float(sem[i, j]), 4)
        if secoes_por_par.get((i, j)):
            for ha, hb, s in secoes_por_par[(i, j)]:
                linhas.append({**base, "secao_a": ha, "secao_b": hb, "score_secao": round(s, 4)})
        else:
            linhas.append({**base, "secao_a": "", "secao_b": "", "score_secao": ""})

    if args.csv:
        campos = ["url_a", "url_b", "score_pagina", "score_titulo", "secao_a", "secao_b", "score_secao",
                  "score_bruto"]
        if sem is not None:
            campos.append("score_semantico")
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
            w.writeheader()
            w.writerows(linhas)
        print(f"CSV: {args.csv} ({len(linhas)} linha(s))")
    if args.json:
        saida = {
            "origem": origem,
            "parametros": {k: v for k, v in vars(args).items() if k not in ("csv", "json")},
            "paginas": [{"url": p.url, "titulo": p.titulo, "h1": p.h1, "palavras_corpo": p.palavras_brutas,
                         "palavras_sem_boilerplate": p.palavras_finais, "secoes": [h for h, _ in p.secoes]}
                        for p in paginas],
            "fora_por_corpo_vazio": [p.url for p in curtas],
            "pouco_texto_proprio": [p.url for p in pouco_proprio],
            "boilerplate_removido": [{"paginas": c, "trecho": t} for c, t in removidos[:50]],
            "secoes_em_quase_todas_as_paginas": [{"paginas": c, "heading": h} for c, h in secoes_sitewide],
            "pares": linhas,
            "falhas": [{"url": u, "erro": e} for u, e in cli.erros],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(saida, fh, ensure_ascii=False, indent=2)
        print(f"JSON: {args.json}")

    if args.strict and (paginas_altas or secoes_altas):
        sys.exit(1)


if __name__ == "__main__":
    main()
