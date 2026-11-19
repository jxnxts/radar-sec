# Feasibility: a Brazilian (B3) version of Radar using CVM open data

Desk research, 2026-11-18. No code was written. Evidence tags used throughout:

- **[V]** verified by downloading and parsing the file or endpoint on 2026-11-18;
- **[R]** read from the official regulation text;
- **[I]** inferred or not verified (treat as a hypothesis).

## 1. Summary verdict

**Feasible, but the result is a weaker, slower cousin of the SEC Radar, not a port.**

- CVM publishes a **structured, trade-level** dataset of insider dealings (`VLMO`, Res. CVM 44 art. 11),
  with trade date, quantity, price, volume, security class and buy/sell type [V]. It is free, has
  stable CSVs, history from **Dec 2018**, and is refreshed weekly [V].
- The two hard limits:
  1. **No person-level identity.** Rows are consolidated **per body** (Controller, Board, Executive
     Board, Fiscal Council, Statutory/technical bodies), each "or related persons". The regulation
     only requires body-level consolidation to be public [R]. You cannot count distinct insiders or
     tell a CEO from any other officer.
  2. **Latency.** Filing is due 10 days after month end [R]. Measured trade-to-filing lag: median
     **25–27 days**, p90 **38–54 days** [V], plus up to 7 days until the weekly open-data refresh.
     A Form 4 arrives within 2 business days.
- The 13D analogue (art. 12, 5%/10%/15%... thresholds) is **indexed** in the IPE dataset (date,
  company, acquisition vs. disposal, PDF link) but **all details are only inside the PDF** [V].
- Prices: B3 `COTAHIST` raw daily files are still downloadable from 1986 onward and include delisted
  tickers [V]; Yahoo `.SA` drops delisted tickers [V].

Body-level signals can replicate `cluster_buy` only partially, and `big_officer_buy` cannot be
replicated as defined. `activist_13d` can be replicated if PDFs are parsed. The drawdown filter can
be replicated fully. The recommendation (section 9) is a short, time-boxed backtest of body-level
signals before any product work.

## 2. Sources

| Source | URL | Format | Granularity | History (files) | Lag vs event | Update freq. |
|---|---|---|---|---|---|---|
| VLMO, insider trades (art. 11) | https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/ | ZIP of 2 CSVs/year, `;`, Latin-1, CRLF [V] | one row per movement line per body per company-month [V] | 2018 file = Dec 2018 only; full years from 2019 [V] | trade→filing median 25–27 d, p90 38–54 d [V] | weekly ("Semanal") [V] |
| IPE, non-structured docs index | https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ | ZIP, one CSV/year; rows link to PDFs on rad.cvm.gov.br [V] | one row per document version [V] | 2003–2026 [V] | Fato Relevante filed same day as reference date in 93% of 2026 rows [V] | weekly [V] |
| ITR (quarterly FS) | https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/ | ZIP (~22–31 MB/yr) of CSVs per statement [V] | account line per company per period | 2011–2026 [V] | statutory deadlines, not measured [I] | weekly [V] |
| DFP (annual FS) | https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/ | same structure (~8–13 MB/yr) [V] | account line per company per year | 2010–2026 [V] | not measured [I] | weekly [V] |
| CAD, company registry | https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv | single CSV, ~1.5 MB, 2,680 rows [V] | one row per registered company; **no ticker** [V] | current snapshot incl. cancelled registrations [V] | n/a | daily ("Diária") [V] |
| FCA, `valor_mobiliario` (tickers) | https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/ | ZIP of 10 CSVs/year [V] | security per company, with `Codigo_Negociacao` [V] | 2010–2026 [V] | n/a | weekly [V] |
| FRE, `posicao_acionaria` | https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/ | CSV inside yearly ZIP [V] | shareholders ≥5% per company, with class % and controller flag [V] | yearly files; **only the latest version per company** is kept [V] | annual form [I] | weekly [V] |
| B3 COTAHIST | https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2025.ZIP (also `_M{MM}{YYYY}`, `_D{DD}{MM}{YYYY}`) | fixed-width TXT in ZIP; ~89–95 MB/yr zipped [V] | daily OHLC, volume, ISIN per ticker | 1986 onward; still served (A1986 HTTP 200) [V] | T+0 evening (daily file for 13-Nov-2026 dated 23:53 GMT) [V] | daily [V] |
| Yahoo chart API | https://query1.finance.yahoo.com/v8/finance/chart/PETR4.SA | JSON | daily/monthly, adjusted close [V] | listed tickers back to 2000 [V] | — | — |

CKAN metadata: `package_list` at https://dados.cvm.gov.br/api/3/action/package_list has 54
datasets [V]. The IDs used here are `cia_aberta-doc-vlmo`, `cia_aberta-doc-ipe`, `cia_aberta-doc-itr`,
`cia_aberta-doc-dfp`, `cia_aberta-doc-fca`, `cia_aberta-doc-fre`, `cia_aberta-cad` and
`cia_aberta-eventos-recompra_acoes` (buyback programmes). Fetch any of them with
`https://dados.cvm.gov.br/api/3/action/package_show?id=<id>` [V].

The CKAN text says datasets cover "the last five years", and CKAN lists only the 2021–2026
resources. The directory listings still serve the older files: VLMO from 2018, IPE from 2003 [V].
Mirror the older files locally, because CVM could prune them [I].

## 3. VLMO dataset, field by field

Every yearly ZIP contains two CSV files [V]. The data dictionary is at
`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/META/meta_vlmo_cia_aberta.zip`.

**`vlmo_cia_aberta_YYYY.csv`** (document header, 4,512 rows in 2026 YTD, 454 companies) [V]:
`CNPJ_Companhia; Nome_Companhia; Data_Referencia; Versao; Codigo_CVM; Categoria; Tipo; Data_Entrega;
Tipo_Apresentacao; Motivo_Reapresentacao; Protocolo_Entrega; Link_Download`

- `Data_Referencia` is always the first day of the month [V]. `Data_Entrega` is the filing date.
- `Tipo` is always `Posição Consolidada` [V]. The issuer's own trades ("Posição Individual - Cia,
  Controladas e Coligadas") appear only in IPE as PDFs [V].
- `Versao`/`Tipo_Apresentacao` mark re-filings (`RE - Reapresentação Espontânea`, 259 in 2026) [V].
  Use the latest version for analysis. Use version 1's `Data_Entrega` as the point-in-time date.

**`vlmo_cia_aberta_con_YYYY.csv`** (movement lines, 48,454 rows in 2026 YTD; 63,235 in 2025) [V]:

| Column | Meaning / observed values (2026) [V] |
|---|---|
| `CNPJ_Companhia`, `Nome_Companhia`, `Data_Referencia`, `Versao` | join keys to the header file |
| `Tipo_Empresa` | whose security was traded: `Companhia` (issuer itself), `Controladora` (parent), `Controlada` (subsidiary) |
| `Empresa` | name of that issuing company |
| `Tipo_Cargo` | **the body**: `Conselho de Administração ou Vinculado`, `Diretor ou Vinculado`, `Controlador ou Vinculado`, `Conselho Fiscal ou Vinculado`, `Órgão Estatutário ou Vinculado`, blank (218 rows) |
| `Tipo_Movimentacao` | 35 values, e.g. `Saldo Inicial`, `Compra à vista`, `Venda à vista`, `Compra`, `Venda`, `Compra à termo`, `Subscrição`, `Ações de plano de remuneração`, `Exercício opção de compra`, `Doação`, `Herança`, `Desdobramento/bonificação`, `Grupamento`, loan open/close, `Posse` (took office), `Desligamento/saída` (left office) |
| `Descricao_Movimentacao` | free text, mostly blank |
| `Tipo_Operacao` | `Crédito` / `Débito` |
| `Tipo_Ativo` | `Ações`, `Units`, `Debêntures`, `Opção de Compra`/`de Venda`, `Derivativos`, `BDR Patrocinados`, ... |
| `Caracteristica_Valor_Mobiliario` | free text, 737 distinct values: `ON`, `PN`, `PNA`, `PNB`, unit compositions, sometimes a ticker (`KLBN11`) |
| `Intermediario` | broker name (filled in ~85% of buys) |
| `Data_Movimentacao` | **trade date** (filled on 100% of buy lines) |
| `Quantidade`, `Preco_Unitario`, `Volume` | quantity, unit price and value in BRL. Price/volume are **0 on ~7% of buy lines** (e.g. Banco do Brasil) |

There is no "Saldo Final" row. The closing balance is `Saldo Inicial` plus credits minus debits [V].
There is **no person name, CPF, title or person ID** [V]. The PDF behind `Link_Download` shows the
same form, with a checkbox per body ("Grupo e Pessoas Ligadas"). It is also anonymous [V].

**Aggregation rule.** Art. 11 §7 requires disclosure "individual e consolidada por órgão". Only the
issuer's own positions are public individually. Managers' positions are public "consolidadas por
órgão" [R] (https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/001/resol044consolid.pdf).
Individual reports go to the company within 5 days of each trade (§4 I), but they are not public [R].

**Size of the opportunity.** Lines below are on-market buys (`Compra à vista`/`Compra`) of shares
or units in the latest filing version [V]:

| | 2025 | 2026 (Jan–Oct) |
|---|---|---|
| buy lines | 6,186 | 4,081 |
| company × month × body groups | 1,137 | 893 |
| groups ≥ R$500k (about US$100k) | 389 (130 companies) | 300 (114 companies) |
| Executive-board groups ≥ R$1.25M (about US$250k) | 55 | 34 |
| company-months with ≥2 bodies buying | 146 | 111 |
| exact duplicate lines | 1,578 | 1,161 |

The largest "buys" are controller tender offers or take-privates, for example Neoenergia
(R$11.9bn) and Serena (R$5.1bn) in 2025 [V]. They must be filtered out.

## 4. Can each signal be replicated?

| Signal | Verdict | Reason |
|---|---|---|
| `cluster_buy` (≥2 distinct insiders, 14 d, ≥US$100k) | **Partially** | Trade dates allow a 14-day window. "Distinct insiders" is not observable, though. The best proxy is ≥2 distinct **bodies** buying, or ≥N buy lines inside one body. Identical lines may be two people or a duplicate, so they cannot be told apart. |
| `big_officer_buy` (CEO/CFO ≥US$250k) | **No (proxy only)** | `Diretor ou Vinculado` pools every statutory officer plus spouses, dependents and controlled entities. The proxy is "Executive board net buys ≥ R$1.25M in the month" (55 cases in 2025). |
| `activist_13d` (new ≥5% stake) | **Partially** | The art. 12 index is structured: IPE `Categoria=Comunicado ao Mercado`, `Tipo=Aquisição/Alienação de Participação Acionária (art. 12 ...)`, `Especie` = acquisition vs disposal declaration (640 docs, 171 companies in 2026; 608 in 2015) [V]. `Assunto` is empty in 100% of the 2026 rows [V]. Holder, %, class and intent are only in the PDF. The sample PDF did have a text layer and stated "exclusively investment" intent, which is a 13G-like statement [V]. Most filers are passive asset managers [I]. Thresholds apply **per class** (ON or PN) and include cash-settled derivatives [R]. |
| opportunistic vs routine (Cohen–Malloy–Pomorski) | **Partially, body level** | Monthly history per body starts in Dec 2018, so three prior years are available from 2022 onward. A body with 10 members almost always looks "routine", which blurs the signal. |
| first buy (no buy in 24 m) | **Partially, body level** | Can be computed per company × body. It is diluted by membership changes (`Posse`/`Desligamento` lines show joins and exits but not who). |
| stake increase (bought ÷ held before) | **Partially, body level** | `Saldo Inicial` per body and class gives the denominator. Controller bodies hold huge balances, so this works best for board and executive bodies. |
| buy after drop (63-day drawdown) | **Yes** | It needs only prices at `Data_Entrega` (section 5). |

**Point-in-time rule for any backtest.** Enter at version 1's `Data_Entrega`, not at
`Data_Movimentacao`. Add up to 7 days if the live system reads the weekly CSV. Reading the RAD/ENET
filing as soon as it appears would avoid that delay, but this was not verified [I]. With a median
lag of about 26 days, much of the post-trade drift documented for US insiders may already be priced
in when the signal fires [I].

## 5. Price data options

1. **B3 COTAHIST** [V]. Annual (`COTAHIST_AYYYY.ZIP`), monthly and daily files are all still served
   from `bvmf.bmfbovespa.com.br/InstDados/SerHist/`. The 2026 annual file was last modified
   18-Nov-2026, and 1986 is available. Each record is a fixed-width line (`01` + date + BDI code +
   ticker + market type + short name + spec + OHLC/avg/close in cents + trades + qty + volume +
   quote factor + **ISIN** + distribution number). A parsed sample (PETR4, 13-Nov-2026: close 45.30,
   ISIN `BRPETRACNPR6`) worked. Prices are **raw (unadjusted)**. You must build split, dividend and
   JCP adjustments yourself from corporate events. The `FATCOT` quote factor and the ISIN
   distribution number help but do not do this for you. Delisted names stay in the files, so there
   is **no survivorship bias**. Layout doc: B3 "Séries Históricas" page
   (https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/series-historicas/, HTTP 200 [V]).
2. **Yahoo `.SA`** [V]. Gives adjusted closes, and renamed tickers keep their history under the new
   symbol (`AXIA3.SA` back to 2000). Delisted or renamed old symbols return "No data found, symbol
   may be delisted" (`BRML3.SA`, `LAME4.SA`, `VVAR3.SA`, `ELET3.SA`). This is the same survivorship
   problem phase 1 found in the US. Benchmarks `^BVSP` (from 1993), `BOVA11.SA` and `SMAL11.SA`
   (from 2008-12) are available.
3. **Suggested approach.** Use COTAHIST as the source of truth for coverage. Use Yahoo adjusted
   closes for live names to check the corporate-action adjustment. Benchmark against
   `SMAL11`/`^BVSP` [I].

## 6. Pitfalls

- **CNPJ → ticker.** CAD has no ticker [V]. FCA `valor_mobiliario` has `Codigo_Negociacao`,
  `Valor_Mobiliario` (ON/PN/Units/Debêntures...) and `Data_Inicio/Fim_Negociacao` [V]. FCA files from
  2010, 2019 and 2026 map **340 of 454** VLMO filers in 2026 and 304 of 399 in 2018. The rest are
  mostly debt-only issuers [I], and all FCA years would be needed to close the gap. Codes need
  cleaning (`BSLI03` next to `BSLI4`) [V].
- **Ticker changes.** One CNPJ can carry old and new codes, e.g. `ELET3/5/6` → `AXIA3/7` [V]. Keep a
  dated CNPJ→ticker table. Do not use a static map.
- **Multiple share classes (ON/PN/PNA/PNB/UNIT).** VLMO gives the class as free text
  (`ON`, `PN`, `1 ON E 2 PNA`, ...) [V]. Matching it to the correct ticker (`xxxx3/4/5/6/11`) needs
  rules plus a manual exceptions list. Art. 12 thresholds are per class [R].
- **Parent/subsidiary double counting.** One trade can appear under `Companhia` in the subsidiary's
  filing and under `Controladora` in the parent's filing. Keep `Tipo_Empresa = Companhia` only [I].
- **Duplicates.** Exact duplicate lines are about 2.5% of 2026 rows [V]. They could be several
  people or a re-keying error, and the data cannot tell which.
- **Zero prices.** Some issuers report price and volume as 0 [V]. Fill these from COTAHIST using the
  trade date.
- **Non-discretionary flows.** Separate out stock-plan grants, option exercises, subscriptions,
  donations, inheritance, loans, tender offers and take-privates. The movement type covers most of
  this. Tender offers need a cross-check against IPE `OPA - Edital de Oferta Pública de Ações` [I].
- **Corporate actions.** `Desdobramento/bonificação` and `Grupamento` lines change body balances [V].
  Stake-increase ratios must use the same pre/post-event basis.
- **Liquidity and universe.** Only about 450–500 filers per year [V], and many are illiquid. Expect far
  fewer tradeable signals than the SEC Radar, with wide bid-ask spreads [I].
- **Encoding.** All CVM CSVs are ISO-8859-1 with `;` and CRLF [V].
- **Ordering.** Use `ORDEM_EXERC` in ITR/DFP and `Versao` everywhere. Restatements are frequent
  (`RE` re-filings) [V].

## 7. Other datasets (for context and features)

- **IPE** columns: `CNPJ_Companhia; Nome_Companhia; Codigo_CVM; Data_Referencia; Categoria; Tipo;
  Especie; Assunto; Data_Entrega; Tipo_Apresentacao; Protocolo_Entrega; Versao; Link_Download` [V].
  The 2026 file has 41,030 rows in 55 categories, including `Fato Relevante` (2,211 from 457
  companies), `Comunicado ao Mercado` (5,186) and the VLMO PDFs (8,057) [V]. `Link_Download` points
  to `https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?...`. That URL returns a PDF despite
  `Content-Type: text/html`. The server sometimes resets the connection mid-transfer, so retry and
  check the `%%EOF` trailer [V]. For material facts the open-data CSV adds no latency beyond the
  weekly refresh, since the documents themselves are on RAD the same day [I].
- **ITR/DFP** columns, per statement (BPA, BPP, DRE, DFC_MD/MI, DMPL, DRA, DVA): `CNPJ_CIA, CD_CVM,
  DENOM_CIA, DT_REFER, VERSAO, GRUPO_DFP, MOEDA, ESCALA_MOEDA, ORDEM_EXERC, DT_INI_EXERC, DT_FIM_EXERC,
  CD_CONTA, DS_CONTA, VL_CONTA, ST_CONTA_FIXA` [V, from META]. The index file adds `DT_RECEB`
  (receipt date, the point-in-time key) [V]. `composicao_capital` has ON/PN/total shares and treasury
  shares, which give the denominator for percentage-of-class calculations [V].
- **FRE `posicao_acionaria`**: holder name, CPF/CNPJ, ON/PN quantities and %, controller flag and
  shareholder-agreement flag [V]. Only the latest version per company is kept (656 companies, one
  version each) [V], so it cannot build a history of art. 12 crossings.

## 8. Estimated effort (developer-days)

| Component | Days |
|---|---|
| CVM downloader + local mirror (VLMO, IPE, FCA, CAD, ITR composicao_capital), Latin-1 parsing, version handling | 2 |
| Dated CNPJ→ticker→class mapping (FCA all years + COTAHIST ISIN), class-text normaliser, exceptions list | 3 |
| COTAHIST ingester + corporate-action adjustment (or Yahoo hybrid) + delisted handling | 3–4 |
| VLMO event model: body-level net buys, flow-type filters, Companhia-only, zero-price fill, tender-offer exclusion | 2 |
| Body-level signals (cluster proxy, executive-board big buy, routine/first/stake/dip) with point-in-time = `Data_Entrega` | 2 |
| Art. 12 pipeline: IPE index → PDF fetch with retry → text/LLM extraction (holder, class, %, intent) → new-≥5% events | 3–4 |
| Backtest adaptation (BRL, B3 calendar, IBOV/SMLL benchmarks, liquidity filter) + report | 2–3 |
| Live mode (weekly CSV poll, or RAD scraping for same-day) + panel adjustments | 2–3 |
| **Total** | **19–23** (about 4–5 weeks) |

A research-only spike is much smaller. It would cover VLMO and COTAHIST only, executive-board and
multi-body signals, and a calendar-portfolio backtest for 2019–2026: about **6–8 days**.

## 9. Recommendation

Context from the US phase 2 (`reports/phase2-2026-11-18.md`): with person-level data, two
business days of lag and ten literature-based variants, no insider rule beat SPY and IWM out of
sample in 2023–2025. The Brazilian data is coarser (body level) and slower (about four weeks),
so the prior for a working B3 signal is lower still. The spike below is only worth doing as
research, not as a product step.

1. **Do not port the product yet.** Run a 6–8 day spike first. Backtest two body-level signals
   ("≥2 bodies buy ≥R$500k within 14 days" and "Executive board net buy ≥R$1.25M"), entering at
   `Data_Entrega`. Use COTAHIST prices and a liquidity floor, and benchmark against SMLL/IBOV.
   Freeze parameters on 2019–2022 and test on 2023–2026, mirroring phase 2 discipline.
2. Continue only if the out-of-sample excess return survives the ~4-week disclosure lag. Then add
   the art. 12 PDF pipeline. It is the only Brazilian source that is close to real time (same-day
   filing [V]) and names the holder.
3. Treat person-level signals (`big_officer_buy`, CEO/CFO, opportunistic vs routine per person) as
   **not replicable** with public CVM data, because the law publishes only body aggregates [R].
