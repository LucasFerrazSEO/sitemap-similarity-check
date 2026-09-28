**English** · [Português (Brasil)](README.pt-BR.md)

# sitemap-similarity-check

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

`sitemap-similarity-check` is a free, open source command-line tool that
reads a sitemap, downloads the pages with a polite crawl and measures how
similar they are to each other in three ways: page against page, section
against section and title against title. Before comparing, it strips the
interface (menu, header, footer, sidebar, cookie banner, share buttons,
breadcrumb) and separates the text that repeats across most pages, so you
can see both the page's own text and the template around it.

The tool prints its report in Brazilian Portuguese. Stopwords and a
simplified RSLP stemmer for Brazilian Portuguese are built in, and
`--lang en` switches to English stopwords.

## Contents

- [Background](#background)
- [What it checks](#what-it-checks)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [FAQ](#faq)
- [Limitations](#limitations)
- [Methodology](#methodology)
- [Contributing](#contributing)
- [Author](#author)
- [License](#license)

## Background

Sites that grow by template (city pages, niche pages, service variations)
tend to repeat whole sections with only a name swapped. Two pages with the
same text and different titles compete for the same search, and neither one
gives a search engine or an AI system a passage that is only found there.
Reading 30 or 200 pages side by side to find those repetitions is slow.
`sitemap-similarity-check` does the mechanical part: it points to the pairs
of pages, the repeated sections and the near-identical titles, and leaves
the editorial decision to you.

## What it checks

1. **Page against page.** TF-IDF with cosine similarity over the main
   content of each page. Each pair gets two scores: `score_pagina`, without
   the text shared by most pages, and `score_bruto`, over the whole main
   content. A pair is flagged when either one reaches `--threshold`
   (default 0.80). From `--lsh-min` pages up (default 150), MinHash/LSH
   with 5-word shingles picks the candidate pairs and cosine runs only on
   them.
2. **Section against section.** Each page is split by H2 (and H3 with
   `--by-h3`). Sections from different pages are compared with TF-IDF and
   cosine (`--section-threshold`, default 0.85), and the report shows the
   heading on each side. Repeated sections are also grouped: "this section
   repeats on K pages". A section with identical text on more than 90% of
   the pages (author box, fixed call to action) is listed once and left out
   of the comparison (`--sitewide-ratio`).
3. **Title and H1.** Jaccard similarity of word bigrams and trigrams, after
   removing the brand suffix that repeats in most titles
   (`--title-threshold`, default 0.60).
4. **Template text.** Paragraphs and sentences present on more than
   `--boilerplate-ratio` of the pages (default 0.5) are counted as shared
   text. The report shows how much of the main content they represent, the
   most repeated passages and the pages left with fewer than `--min-words`
   words of their own.
5. **Optional semantic reading.** With `--semantic`, local embeddings from
   `paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers), only if
   the library is installed. Without it, the tool warns and continues with
   the lexical reading.

The default thresholds are adjustable starting points. Google does not
publish a duplication percentage, and none of these numbers is a Google
limit. Read the flagged pairs before deciding to merge, rewrite or keep a
page.

## Requirements

Python 3.9 or newer, plus `requests`, `beautifulsoup4` and `lxml` (see
`requirements.txt`). `sentence-transformers` is optional and only used by
`--semantic`.

## Installation

```bash
git clone https://github.com/LucasFerrazSEO/sitemap-similarity-check.git
cd sitemap-similarity-check
pip install -r requirements.txt
```

## Usage

**1. Point the tool to a sitemap.** It accepts a sitemap, a sitemap index,
a `.xml.gz` file or a `robots.txt` with `Sitemap:` lines.

```bash
python sitemap_similarity_check.py https://example.com/sitemap_index.xml --max-urls 30 --include "regioes-atendidas"
```

`--include` and `--exclude` take regular expressions matched against the
URL. `--max-urls` (default 200) caps the crawl and `--delay` (default 1.0
second) sets the pause between requests. On HTTP 429 the tool waits and
retries once, then records the failure.

**2. Read the report.** A real run against 30 city pages of
lucasferrazseo.com, shortened with "...":

```
=== sitemap-similarity-check: https://lucasferrazseo.com/sitemap_index.xml ===
URLs na fila: 30 | páginas comparadas: 29 | fora por corpo vazio (< 50 palavras): 1 | falhas: 0
Boilerplate: 37 bloco(s) e 28 frase(s) presentes em mais de 50% das páginas, 18% do texto do corpo principal
  Trechos comuns mais repetidos:
    29/29 páginas  "no estudo científico com doi que publicou no zenodo, lucas ferraz acompanhou por..."
    ...
Leitura página x página: 406 pares (todos contra todos)

Página x página (TF-IDF cosseno >= 0.80, sem boilerplate ou corpo inteiro): 0 par(es)
Seção x seção   (TF-IDF cosseno >= 0.85): 470 par(es) em 270 seções de H2
                  29 seção(ões) idêntica(s) em mais de 90% das páginas ficaram fora da comparação, por exemplo "Quer um site profissional para atender clientes em"
Título/H1       (Jaccard 2-3-gramas >= 0.60): 1 par(es)

Seções repetidas, agrupadas (17 grupo(s); top 5):
  29 páginas | média 0.94 | "Conheça o especialista por trás da agência"
      ex.: /regioes-atendidas/criacao-de-sites-em-contagem/, /regioes-atendidas/criacao-de-sites-em-casa-branca/, /regioes-atendidas/criacao-de-sites-em-campo-grande/ ...
  10 páginas | média 0.90 | "O que dizem sobre nossa criação de sites em Contagem"
      ex.: /regioes-atendidas/criacao-de-sites-em-contagem/, /regioes-atendidas/criacao-de-sites-em-aracaju/, /regioes-atendidas/criacao-de-sites-em-confins/ ...
  ...

Top 5 títulos/H1 parecidos:
  0.64  "Criação de sites em Ouro Branco"  x  "Criação de sites em Ouro Preto"

(Limiares são ponto de partida ajustável, não limite do Google. Leia os pares antes de decidir.)
```

In this run no pair of pages crossed 0.80: the city pages carry their own
text. What repeats are the author section (on purpose, the same bio on
every page) and the testimonial blocks, grouped by the tool so the list
stays readable.

**3. Test locally, without network.** The `examples/paginas/` folder has
five fictitious pages (example.com), three of them built from the same
template with only the city swapped:

```bash
python sitemap_similarity_check.py --html-dir examples/paginas
```

Real output, shortened:

```
Boilerplate: 4 bloco(s) e 9 frase(s) presentes em mais de 50% das páginas, 78% do texto do corpo principal
  ATENÇÃO  mais da metade do corpo principal é texto comum a muitas páginas. Em páginas de região ou de nicho feitas sobre template, esse já é o sinal de duplicação.
  ATENÇÃO  3 página(s) com menos de 50 palavras próprias depois de tirar o texto comum:
           reforma-belo-horizonte.html (11 de 207 palavras)
           ...
Página x página (TF-IDF cosseno >= 0.80, sem boilerplate ou corpo inteiro): 3 par(es)
...
Top 3 pares de página:
  0.98  reforma-betim.html  x  reforma-contagem.html  (sem boilerplate 0.68, corpo inteiro 0.98, título 0.56)
```

**4. Save the pairs.** `--csv` writes one row per pair (and per repeated
section of that pair) with the columns `url_a, url_b, score_pagina,
score_titulo, secao_a, secao_b, score_secao, score_bruto` (plus
`score_semantico` with `--semantic`). `--json` saves everything, including
the shared passages removed and the pages with little text of their own.

```bash
python sitemap_similarity_check.py https://example.com/sitemap.xml --csv pares.csv --json pares.json
```

**5. Other sources.** A list of URLs (one per line) or English pages:

```bash
python sitemap_similarity_check.py --urls urls.txt --delay 2
python sitemap_similarity_check.py https://example.com/sitemap.xml --lang en --by-h3
```

**6. Use it in CI/CD.**

```bash
python sitemap_similarity_check.py https://example.com/sitemap.xml --strict   # código de saída 1 se houver par acima do limiar
```

With `--strict`, the exit code is 1 when any page pair or section pair
reaches its threshold.

## FAQ

**Is 0.80 the percentage Google uses to call a page duplicate?**
No. Google does not publish a percentage. 0.80 for pages and 0.85 for
sections are starting points for reviewing template pages, and you should
adjust them to your site after reading the first flagged pairs.

**Why two page scores?**
`score_bruto` compares the whole main content and catches template pages
that differ only by a name. `score_pagina` ignores the text shared by most
pages and shows whether the text that is left is also a copy. On a site
where every page is a template variation, the shared text is the finding
itself, which is why the report shows its share and the pages with little
text of their own.

**Does it run JavaScript?**
No. It reads the HTML the server delivers. A page that only renders its
text in the browser will show up with an empty body.

**Is my data sent anywhere?**
No. The tool downloads the public pages you point it to and does all the
math on your machine. `--semantic` also runs locally.

**Does it guarantee better rankings after I fix the pairs?**
No. It shows where pages repeat each other. What to merge, rewrite or keep
is an editorial decision, and no tool controls how a search engine ranks a
page.

## Limitations

Interface removal is heuristic (common tag names, classes and ids); an
unusual theme may leave menu text behind or cut real content. The
simplified RSLP stemmer covers the most frequent Portuguese suffixes, not
the full rule set, and may merge or split some words. Lexical similarity
does not judge quality or search intent: two pages can share vocabulary and
still answer different questions. `--semantic` needs the model on disk; the
first run downloads it through sentence-transformers.

## Methodology

The tool generalizes an internal shingle check used at
[lucasferrazseo.com](https://lucasferrazseo.com) to enforce the site's
cannibalization rule and to review city and niche pages built on a template
before publishing. The public version has no site-specific rule: interface
removal uses generic patterns, and every threshold is a parameter.

## Contributing

Bug reports and suggestions are welcome through [GitHub Issues](https://github.com/LucasFerrazSEO/sitemap-similarity-check/issues).

## Author

[Lucas Ferraz](https://lucasferraz.com) is an SEO, website development and Generative Engine Optimization specialist and the founder of [Lucas Ferraz SEO](https://lucasferrazseo.com).

## License

MIT. See [LICENSE](LICENSE).
