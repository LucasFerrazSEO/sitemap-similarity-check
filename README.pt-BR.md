[English](README.md) · **Português (Brasil)**

# sitemap-similarity-check

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

`sitemap-similarity-check` é uma ferramenta gratuita, de código aberto e
de linha de comando, que lê um sitemap, baixa as páginas com crawl educado
e mede o quanto elas se parecem entre si de três formas: página com
página, seção com seção e título com título. Antes de comparar, ela tira a
interface (menu, cabeçalho, rodapé, barra lateral, aviso de cookie, botões
de compartilhar, breadcrumb) e separa o texto que se repete na maioria das
páginas, para você ver o texto próprio de cada página e o template em volta
dele.

## Sumário

- [Contexto](#contexto)
- [O que a ferramenta verifica](#o-que-a-ferramenta-verifica)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
- [Perguntas frequentes](#perguntas-frequentes)
- [Limitações](#limitações)
- [Método e origem](#método-e-origem)
- [Como contribuir](#como-contribuir)
- [Autor](#autor)
- [Licença](#licença)

## Contexto

Site que cresce por template (página de cidade, página de nicho, variação
de serviço) tende a repetir seções inteiras trocando só um nome. Duas
páginas com o mesmo texto e títulos diferentes disputam a mesma busca, e
nenhuma das duas entrega ao buscador ou à IA uma passagem que só existe
ali. Ler 30 ou 200 páginas lado a lado para achar essas repetições é
lento. `sitemap-similarity-check` faz a parte mecânica: aponta os pares de
páginas, as seções repetidas e os títulos quase iguais, e deixa a decisão
editorial com você.

## O que a ferramenta verifica

1. **Página com página.** TF-IDF com similaridade de cosseno sobre o corpo
   principal de cada página. Cada par recebe dois scores: `score_pagina`,
   sem o texto comum à maioria das páginas, e `score_bruto`, sobre o corpo
   principal inteiro. O par é apontado quando qualquer um dos dois chega a
   `--threshold` (padrão 0.80). A partir de `--lsh-min` páginas (padrão
   150), MinHash/LSH com shingles de 5 palavras escolhe os pares candidatos
   e o cosseno roda só neles.
2. **Seção com seção.** Cada página é dividida por H2 (e por H3 com
   `--by-h3`). Seções de páginas diferentes são comparadas com TF-IDF e
   cosseno (`--section-threshold`, padrão 0.85), e o relatório mostra o
   heading de cada lado. As seções repetidas também saem agrupadas: "esta
   seção se repete em K páginas". Seção com texto idêntico em mais de 90%
   das páginas (caixa de autor, chamada fixa) aparece uma vez só e fica
   fora da comparação (`--sitewide-ratio`).
3. **Título e H1.** Jaccard de bigramas e trigramas de palavras, depois de
   tirar o sufixo de marca que se repete na maioria dos títulos
   (`--title-threshold`, padrão 0.60).
4. **Texto de template.** Parágrafos e frases presentes em mais de
   `--boilerplate-ratio` das páginas (padrão 0.5) contam como texto comum.
   O relatório mostra quanto do corpo principal eles ocupam, os trechos
   mais repetidos e as páginas que ficam com menos de `--min-words`
   palavras próprias.
5. **Leitura semântica opcional.** Com `--semantic`, embeddings locais do
   modelo `paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers),
   só se a biblioteca estiver instalada. Sem ela, a ferramenta avisa e
   segue na leitura lexical.

Os limiares padrão são pontos de partida ajustáveis. O Google não publica
percentual de duplicação, e nenhum destes números é limite do Google. Leia
os pares apontados antes de decidir fundir, reescrever ou manter uma
página.

## Requisitos

Python 3.9 ou mais recente, mais `requests`, `beautifulsoup4` e `lxml`
(veja `requirements.txt`). `sentence-transformers` é opcional e só entra
no `--semantic`. Stopwords de português e um stemmer RSLP simplificado vêm
embutidos; `--lang en` troca para stopwords em inglês, sem stemmer.

## Instalação

```bash
git clone https://github.com/LucasFerrazSEO/sitemap-similarity-check.git
cd sitemap-similarity-check
pip install -r requirements.txt
```

## Uso

**1. Aponte a ferramenta para um sitemap.** Ela aceita sitemap, sitemap
index, arquivo `.xml.gz` ou um `robots.txt` com linhas `Sitemap:`.

```bash
python sitemap_similarity_check.py https://example.com/sitemap_index.xml --max-urls 30 --include "regioes-atendidas"
```

`--include` e `--exclude` recebem expressões regulares aplicadas à URL.
`--max-urls` (padrão 200) limita o crawl e `--delay` (padrão 1.0 segundo)
define a pausa entre requisições. Em HTTP 429, a ferramenta espera, tenta
de novo uma vez e depois registra a falha.

**2. Leia o relatório.** Uma execução real contra 30 páginas de cidade do
lucasferrazseo.com, encurtada com "...":

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

Nesta execução, nenhum par de páginas passou de 0.80: as páginas de
cidade têm texto próprio. O que se repete é a seção do autor (de
propósito, a mesma bio em todas) e os blocos de depoimento, que a
ferramenta agrupa para a lista continuar legível.

**3. Teste local, sem rede.** A pasta `examples/paginas/` tem cinco
páginas fictícias (example.com), três delas feitas do mesmo template com
só a cidade trocada:

```bash
python sitemap_similarity_check.py --html-dir examples/paginas
```

Saída real, encurtada:

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

**4. Salve os pares.** `--csv` grava uma linha por par (e por seção
repetida daquele par) com as colunas `url_a, url_b, score_pagina,
score_titulo, secao_a, secao_b, score_secao, score_bruto` (mais
`score_semantico` com `--semantic`). `--json` salva tudo, inclusive os
trechos comuns removidos e as páginas com pouco texto próprio.

```bash
python sitemap_similarity_check.py https://example.com/sitemap.xml --csv pares.csv --json pares.json
```

**5. Outras fontes.** Lista de URLs (uma por linha) ou páginas em inglês:

```bash
python sitemap_similarity_check.py --urls urls.txt --delay 2
python sitemap_similarity_check.py https://example.com/sitemap.xml --lang en --by-h3
```

**6. Use em CI/CD.**

```bash
python sitemap_similarity_check.py https://example.com/sitemap.xml --strict   # código de saída 1 se houver par acima do limiar
```

Com `--strict`, o código de saída é 1 se qualquer par de página ou de
seção chegar ao limiar.

## Perguntas frequentes

**0.80 é o percentual que o Google usa para considerar uma página duplicada?**
Não. O Google não publica percentual. 0.80 para página e 0.85 para seção
são pontos de partida para a revisão de páginas de template, e devem ser
ajustados ao seu site depois de ler os primeiros pares
apontados.

**Por que dois scores de página?**
`score_bruto` compara o corpo principal inteiro e pega página de template
que só troca um nome. `score_pagina` ignora o texto comum à maioria das
páginas e mostra se o que sobra também é cópia. Em um site em que toda
página é variação de template, o texto comum já é o achado, e por isso o
relatório mostra a fatia dele e as páginas com pouco texto próprio.

**A ferramenta executa JavaScript?**
Não. Ela lê o HTML que o servidor entrega. Página que só monta o texto no
navegador aparece com o corpo vazio.

**Meus dados vão para algum servidor?**
Não. A ferramenta baixa as páginas públicas que você indicar e faz toda a
conta na sua máquina. O `--semantic` também roda localmente.

**Corrigir os pares apontados garante posição melhor no Google?**
Não. A ferramenta mostra onde as páginas repetem umas às outras. O que
fundir, reescrever ou manter é decisão editorial, e nenhuma ferramenta
controla como o buscador ordena uma página.

## Limitações

A remoção de interface é heurística (nomes de tag, classes e ids comuns);
um tema fora do padrão pode deixar texto de menu ou cortar conteúdo real.
O stemmer RSLP simplificado cobre os sufixos mais frequentes do português,
não o conjunto completo de regras, e pode juntar ou separar algumas
palavras. Similaridade lexical não julga qualidade nem intenção de busca:
duas páginas podem dividir vocabulário e responder perguntas diferentes. O
`--semantic` precisa do modelo em disco; a primeira execução baixa o
modelo pelo sentence-transformers.

## Método e origem

A ferramenta generaliza uma checagem interna de shingles usada no
[lucasferrazseo.com](https://lucasferrazseo.com) para fazer valer a regra
de canibalização do site e para revisar páginas de região e de nicho
montadas sobre template antes de publicar. A versão pública não tem
nenhuma regra específica de site: a remoção de interface usa padrões
genéricos, e todo limiar é parâmetro.

## Como contribuir

Relatos de erro e sugestões são bem-vindos pelas [Issues do GitHub](https://github.com/LucasFerrazSEO/sitemap-similarity-check/issues).

## Autor

[Lucas Ferraz](https://lucasferraz.com) é especialista em SEO, criação de sites e Generative Engine Optimization e fundador da [Lucas Ferraz SEO](https://lucasferrazseo.com).

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
