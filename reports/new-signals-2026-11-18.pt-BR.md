# Novos sinais de mercado: backtest de 2020-01-01 a 2025-12-31

Gerado em 2026-11-18 14:23. Regras, períodos e critérios de veredito foram fixados antes em [`research/new-signals-plan.md`](../research/new-signals-plan.md). Preços: Yahoo Finance (ajustados), com o mesmo cache e o mesmo motor de entrada e saída do backtest de insiders. Nenhuma IA é usada.

## Veredito

Prazo principal, excesso de retorno sobre o SPY, **período de teste 2023–2025** (Form 144: de 2023-05 a 2025-12, o único histórico eletrônico). Custos: 0,2% ida e volta; 1,0% quando o preço de entrada é menor que US$ 5.

| Sinal | Hipótese | Prazo | N (teste) | Excesso médio | Excesso mediano | Bate SPY | t (safra mensal) | Média treino | Média vs IWM | Mediana vs IWM | Veredito |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `buyback_8k` | compra | 6m | 1.276 | -4,2% | -5,9% | 39,3% | -3,5 | -0,3% | -2,8% | -4,5% | **descartar** |
| `ceo_cfo_exit_8k` | evitar | 3m | 508 | -6,2% | -13,6% | 28,9% | -1,0 | +2,0% | -4,5% | -12,2% | **talvez (evitar)** |
| `bankruptcy_8k` | evitar | 1m | 54 | -30,4% | -38,9% | 25,9% | -3,0 | +13,5% | -30,2% | -38,5% | **talvez (evitar)** |
| `auditor_change_8k` | evitar | 3m | 1.860 | +160,4% | -12,4% | 30,8% | 1,3 | +9,2% | +161,8% | -11,1% | **descartar** |
| `late_filing_nt` | evitar | 3m | 4.949 | +864,3% | -16,9% | 26,9% | 1,2 | +295,4% | +866,0% | -15,7% | **descartar** |
| `form144_cluster` | evitar | 3m | 6.130 | -1,0% | -3,7% | 41,8% | -0,9 | — | +0,2% | -1,9% | **talvez (evitar)** |
| `fund_consensus_13f` | compra | 3m | 349 | +2,0% | -0,2% | 48,4% | 1,7 | -1,0% | +3,5% | +2,3% | **descartar** |
| `notable_fund_new_13f` | compra | 3m | 619 | -0,1% | -1,1% | 45,9% | -0,0 | -1,7% | +1,2% | +0,0% | **descartar** |
| `short_crowded` | evitar | 1m | 916 | -1,3% | -1,7% | 41,4% | -1,0 | -0,7% | -0,6% | -0,8% | **talvez (evitar)** |
| `squeeze_setup` | compra | 1m | 93 | -4,8% | -8,3% | 31,2% | -2,5 | +1,0% | -4,3% | -6,7% | **descartar** |
| `ftd_persistent` | evitar | 1m | 587 | -12,8% | -16,5% | 25,6% | -5,3 | +0,1% | -12,4% | -16,5% | **talvez (evitar)** |

- `buyback_8k`: **descartar** — o excesso do teste não é positivo na média e na mediana.
- `ceo_cfo_exit_8k`: **talvez (evitar)** — média e mediana do teste < 0, mas t = -1.0.
- `bankruptcy_8k`: **talvez (evitar)** — média e mediana do teste < 0 (t = -3.0), mas o treino discorda.
- `auditor_change_8k`: **descartar** — o excesso do teste não é negativo na média e na mediana.
- `late_filing_nt`: **descartar** — o excesso do teste não é negativo na média e na mediana.
- `form144_cluster`: **talvez (evitar)** — média e mediana do teste < 0, mas t = -0.9.
- `fund_consensus_13f`: **descartar** — o excesso do teste não é positivo na média e na mediana.
- `notable_fund_new_13f`: **descartar** — o excesso do teste não é positivo na média e na mediana.
- `short_crowded`: **talvez (evitar)** — média e mediana do teste < 0, mas t = -1.0.
- `squeeze_setup`: **descartar** — o excesso do teste não é positivo na média e na mediana.
- `ftd_persistent`: **talvez (evitar)** — média e mediana do teste < 0 (t = -5.3), mas o treino discorda.

Como ler: *excesso* = retorno líquido menos o SPY nas mesmas datas. *Bate SPY* = fração dos sinais com excesso positivo. *t (safra mensal)* = estatística t da média do excesso por safra mensal (um ponto por mês, para sinais agrupados não inflarem o número). *evitar* = papéis de que convém ficar longe (um filtro, não uma recomendação de venda a descoberto).

> Viés de sobrevivência: o Yahoo quase não guarda histórico de empresas deslistadas. Sinais em empresas que depois faliram ou foram compradas ficam em geral sem medição, e isso pesa mais nos sinais de *evitar* (falências acima de tudo). Veja o funil de cada sinal.

### Visão secundária: recorte líquido

O plano fixou um recorte líquido (preço de entrada ≥ US$ 5 e valor de mercado ≥ US$ 300 mi) como visão reportada, não como base do veredito. A mesma regra de veredito aplicada a ele, para referência:

| Sinal | Hipótese | Prazo | N (teste) | Excesso médio | Excesso mediano | Bate SPY | t (safra mensal) | Média treino | Média vs IWM | Mediana vs IWM | Veredito |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `buyback_8k` | compra | 6m | 821 | -2,9% | -4,4% | 40,8% | -3,1 | +0,2% | -1,5% | -3,4% | **descartar** |
| `ceo_cfo_exit_8k` | evitar | 3m | 120 | -3,3% | -5,0% | 38,3% | -1,6 | -1,6% | -1,8% | -3,1% | **talvez (evitar)** |
| `bankruptcy_8k` | evitar | 1m | 0 | n/d | n/d | n/d | n/d | +29,0% | n/d | n/d | **dados insuficientes** |
| `auditor_change_8k` | evitar | 3m | 264 | -2,9% | -3,7% | 38,3% | -2,1 | +0,9% | -1,1% | -3,3% | **talvez (evitar)** |
| `late_filing_nt` | evitar | 3m | 253 | -8,9% | -8,1% | 31,6% | -2,1 | -7,5% | -6,1% | -6,6% | **evitar** |
| `form144_cluster` | evitar | 3m | 4.198 | -1,2% | -3,2% | 42,4% | -1,2 | — | +0,0% | -1,3% | **talvez (evitar)** |
| `fund_consensus_13f` | compra | 3m | 269 | +2,9% | +0,2% | 50,6% | 1,9 | -1,8% | +4,3% | +2,9% | **talvez** |
| `notable_fund_new_13f` | compra | 3m | 463 | +0,5% | -1,1% | 46,7% | 0,5 | +0,5% | +2,0% | +0,6% | **descartar** |
| `short_crowded` | evitar | 1m | 584 | -1,3% | -1,3% | 41,6% | -2,1 | -0,2% | -0,9% | -0,6% | **evitar** |
| `squeeze_setup` | compra | 1m | 26 | -3,0% | -8,6% | 34,6% | -0,8 | -3,1% | -2,2% | -7,1% | **dados insuficientes** |
| `ftd_persistent` | evitar | 1m | 71 | -1,1% | -2,9% | 47,9% | -0,8 | -2,0% | -0,6% | -2,5% | **talvez (evitar)** |

### Qualidade dos dados: cotações abaixo de um centavo

Quem atrasa relatório, troca de auditor ou pede falência é quase sempre empresa de balcão. As séries do Yahoo delas trazem cotações de US$ 0,0001–0,001 que saltam para centavos ou dólares (um único negócio ou um grupamento não ajustado), o que vira retornos de milhares por cento. O filtro de salto do backtest de insiders ignora de propósito bases abaixo de US$ 0,01, então elas passam. Nestes sinais a **média não tem sentido**: leia a mediana, a média winsorizada e o recorte líquido.

| Sinal | Medidos | Entrada < US$ 0,01 | Entrada < US$ 1 |
|---|---|---|---|
| `buyback_8k` | 2.248 | 1 (0,0%) | 45 (2,0%) |
| `ceo_cfo_exit_8k` | 900 | 13 (1,4%) | 218 (24,2%) |
| `bankruptcy_8k` | 80 | 15 (18,8%) | 58 (72,5%) |
| `auditor_change_8k` | 2.999 | 176 (5,9%) | 1.033 (34,4%) |
| `late_filing_nt` | 8.272 | 1.032 (12,5%) | 4.784 (57,8%) |
| `form144_cluster` | 6.130 | 3 (0,0%) | 105 (1,7%) |
| `fund_consensus_13f` | 690 | 0 (0,0%) | 0 (0,0%) |
| `notable_fund_new_13f` | 1.164 | 0 (0,0%) | 2 (0,2%) |
| `short_crowded` | 1.626 | 0 (0,0%) | 50 (3,1%) |
| `squeeze_setup` | 165 | 0 (0,0%) | 12 (7,3%) |
| `ftd_persistent` | 951 | 8 (0,8%) | 241 (25,3%) |

## `buyback_8k` — Recompra autorizada (8-K)

Regra: o texto do 8-K traz uma das frases fixas de nova autorização de recompra; cooldown de 90 dias. Hipótese: bate o índice. Prazo principal: 6 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 972 | 53,0% | 51,5% | +1,1% | **+0,4%** | **+0,3%** | +0,3% | 0,9 |
| treino 2020–2022 | 3m | 972 | 54,2% | 49,9% | +2,8% | **+0,5%** | **-0,0%** | +0,5% | 0,9 |
| treino 2020–2022 | 6m | 972 | 52,9% | 47,2% | +4,4% | **-0,3%** | **-1,3%** | -0,6% | 0,7 |
| teste 2023–2025 | 1m | 1.276 | 51,6% | 42,6% | +0,8% | **-1,0%** | **-1,3%** | -1,2% | -2,0 |
| teste 2023–2025 | 3m | 1.276 | 53,8% | 41,2% | +2,8% | **-2,4%** | **-3,7%** | -3,0% | -1,9 |
| teste 2023–2025 | 6m | 1.276 | 58,5% | 39,3% | +6,5% | **-4,2%** | **-5,9%** | -4,8% | -3,5 |
| tudo 2020–2025 | 1m | 2.248 | 52,2% | 46,4% | +0,9% | **-0,4%** | **-0,8%** | -0,5% | -0,5 |
| tudo 2020–2025 | 3m | 2.248 | 54,0% | 45,0% | +2,8% | **-1,1%** | **-2,1%** | -1,5% | -0,7 |
| tudo 2020–2025 | 6m | 2.248 | 56,1% | 42,7% | +5,6% | **-2,5%** | **-4,1%** | -2,9% | -1,2 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 972 | 53,0% | 52,2% | +1,1% | **+0,6%** | **+0,5%** | +0,5% | 1,4 |
| treino 2020–2022 | 3m | 972 | 54,2% | 49,2% | +2,8% | **+0,3%** | **-0,3%** | +0,2% | 0,6 |
| treino 2020–2022 | 6m | 972 | 52,9% | 49,2% | +4,4% | **+1,0%** | **-0,2%** | +0,7% | 0,9 |
| teste 2023–2025 | 1m | 1.276 | 51,6% | 46,2% | +0,8% | **-0,6%** | **-0,9%** | -0,8% | -1,0 |
| teste 2023–2025 | 3m | 1.276 | 53,8% | 45,5% | +2,8% | **-1,1%** | **-1,6%** | -1,7% | -0,5 |
| teste 2023–2025 | 6m | 1.276 | 58,5% | 41,7% | +6,5% | **-2,8%** | **-4,5%** | -3,4% | -1,5 |
| tudo 2020–2025 | 1m | 2.248 | 52,2% | 48,8% | +0,9% | **-0,1%** | **-0,3%** | -0,2% | 0,2 |
| tudo 2020–2025 | 3m | 2.248 | 54,0% | 47,1% | +2,8% | **-0,5%** | **-1,1%** | -0,8% | 0,0 |
| tudo 2020–2025 | 6m | 2.248 | 56,1% | 44,9% | +5,6% | **-1,1%** | **-2,4%** | -1,6% | -0,4 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 821 | 42,9% | -0,7% | -1,3% | -2,0 |
| 3m | 821 | 41,4% | -1,7% | -3,1% | -2,2 |
| 6m | 821 | 40,8% | -2,9% | -4,4% | -3,1 |

Funil (2.632 sinais): medido 2.248 (85,4%); sem preços no Yahoo (deslistado ou desconhecido) 196 (7,4%); sem ticker 149 (5,7%); sem preço perto da entrada 39 (1,5%).

Por ano (6m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 226 | +6,2% | +5,2% |
| 2021 | 306 | -1,4% | -2,5% |
| 2022 | 440 | -3,0% | -3,2% |
| 2023 | 350 | -5,2% | -8,1% |
| 2024 | 431 | -2,1% | -4,5% |
| 2025 | 495 | -5,4% | -5,7% |

## `ceo_cfo_exit_8k` — Saída de CEO/CFO (8-K)

Regra: 8-K com item 5.02 cujo texto diz que o CEO ou o CFO renunciou, deixou o cargo ou foi desligado. Hipótese: fica atrás do índice. Prazo principal: 3 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 392 | 40,6% | 37,5% | -2,0% | **-2,8%** | **-3,9%** | -3,5% | -1,1 |
| treino 2020–2022 | 3m | 392 | 41,3% | 37,2% | +4,6% | **+2,0%** | **-7,8%** | -1,3% | 0,8 |
| treino 2020–2022 | 6m | 392 | 39,8% | 36,0% | +20,8% | **+14,9%** | **-15,1%** | +5,6% | 1,0 |
| teste 2023–2025 | 1m | 508 | 43,1% | 37,0% | +0,6% | **-1,0%** | **-4,6%** | -2,1% | -0,8 |
| teste 2023–2025 | 3m | 508 | 36,6% | 28,9% | -1,2% | **-6,2%** | **-13,6%** | -10,6% | -1,0 |
| teste 2023–2025 | 6m | 508 | 40,2% | 28,3% | -1,8% | **-12,5%** | **-21,3%** | -17,7% | -1,6 |
| tudo 2020–2025 | 1m | 900 | 42,0% | 37,2% | -0,5% | **-1,8%** | **-4,2%** | -2,8% | -1,4 |
| tudo 2020–2025 | 3m | 900 | 38,7% | 32,6% | +1,4% | **-2,6%** | **-10,7%** | -6,5% | -0,2 |
| tudo 2020–2025 | 6m | 900 | 40,0% | 31,7% | +8,1% | **-0,6%** | **-19,7%** | -7,5% | 0,4 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 392 | 40,6% | 38,8% | -2,0% | **-2,5%** | **-3,5%** | -3,2% | -1,3 |
| treino 2020–2022 | 3m | 392 | 41,3% | 39,3% | +4,6% | **+2,9%** | **-6,6%** | -0,4% | 0,8 |
| treino 2020–2022 | 6m | 392 | 39,8% | 38,3% | +20,8% | **+16,6%** | **-12,5%** | +7,4% | 1,1 |
| teste 2023–2025 | 1m | 508 | 43,1% | 37,2% | +0,6% | **-0,4%** | **-4,7%** | -1,5% | -0,5 |
| teste 2023–2025 | 3m | 508 | 36,6% | 32,7% | -1,2% | **-4,5%** | **-12,2%** | -8,9% | -0,6 |
| teste 2023–2025 | 6m | 508 | 40,2% | 30,3% | -1,8% | **-9,9%** | **-18,0%** | -14,9% | -1,2 |
| tudo 2020–2025 | 1m | 900 | 42,0% | 37,9% | -0,5% | **-1,3%** | **-4,3%** | -2,4% | -1,2 |
| tudo 2020–2025 | 3m | 900 | 38,7% | 35,6% | +1,4% | **-1,3%** | **-9,5%** | -5,1% | 0,0 |
| tudo 2020–2025 | 6m | 900 | 40,0% | 33,8% | +8,1% | **+1,6%** | **-15,9%** | -5,4% | 0,5 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 120 | 44,2% | -0,3% | -1,5% | -0,7 |
| 3m | 120 | 38,3% | -3,3% | -5,0% | -1,6 |
| 6m | 120 | 38,3% | -4,6% | -6,0% | -0,6 |

Funil (1.420 sinais): medido 900 (63,4%); sem ticker 288 (20,3%); sem preços no Yahoo (deslistado ou desconhecido) 165 (11,6%); sem preço perto da entrada 59 (4,2%); salto suspeito (grupamento não ajustado) 8 (0,6%).

Por ano (3m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 94 | +21,0% | +5,0% |
| 2021 | 160 | -0,3% | -10,2% |
| 2022 | 138 | -8,2% | -8,9% |
| 2023 | 182 | -9,5% | -13,5% |
| 2024 | 157 | -19,8% | -17,2% |
| 2025 | 169 | +10,1% | -10,3% |

## `bankruptcy_8k` — Falência (8-K)

Regra: 8-K com item 1.03 (falência ou recuperação judicial). Hipótese: fica atrás do índice. Prazo principal: 1 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 26 | 53,8% | 50,0% | +17,3% | **+13,5%** | **+0,5%** | +13,1% | 1,0 |
| treino 2020–2022 | 3m | 26 | 69,2% | 57,7% | +22,7% | **+14,1%** | **+10,9%** | +14,0% | 0,8 |
| treino 2020–2022 | 6m | 26 | 61,5% | 50,0% | +1.977,2% | **+1.964,5%** | **+1,9%** | +1.632,5% | 1,2 |
| teste 2023–2025 | 1m | 54 | 24,1% | 25,9% | -28,6% | **-30,4%** | **-38,9%** | -31,4% | -3,0 |
| teste 2023–2025 | 3m | 54 | 20,4% | 20,4% | -46,7% | **-51,4%** | **-66,6%** | -52,0% | -4,8 |
| teste 2023–2025 | 6m | 54 | 14,8% | 11,1% | -57,2% | **-67,9%** | **-106,4%** | -69,9% | -5,5 |
| tudo 2020–2025 | 1m | 80 | 33,8% | 33,8% | -13,7% | **-16,1%** | **-22,1%** | -16,1% | -1,7 |
| tudo 2020–2025 | 3m | 80 | 36,2% | 32,5% | -24,1% | **-30,1%** | **-41,9%** | -30,3% | -2,5 |
| tudo 2020–2025 | 6m | 80 | 30,0% | 23,8% | +604,0% | **+592,6%** | **-71,7%** | +251,6% | 1,1 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 26 | 53,8% | 50,0% | +17,3% | **+13,3%** | **+2,1%** | +12,7% | 0,8 |
| treino 2020–2022 | 3m | 26 | 69,2% | 61,5% | +22,7% | **+13,0%** | **+14,9%** | +12,5% | 0,6 |
| treino 2020–2022 | 6m | 26 | 61,5% | 53,8% | +1.977,2% | **+1.963,4%** | **+5,0%** | +1.631,5% | 1,2 |
| teste 2023–2025 | 1m | 54 | 24,1% | 29,6% | -28,6% | **-30,2%** | **-38,5%** | -31,3% | -2,9 |
| teste 2023–2025 | 3m | 54 | 20,4% | 20,4% | -46,7% | **-49,4%** | **-67,0%** | -50,0% | -4,4 |
| teste 2023–2025 | 6m | 54 | 14,8% | 13,0% | -57,2% | **-64,6%** | **-100,2%** | -66,6% | -5,0 |
| tudo 2020–2025 | 1m | 80 | 33,8% | 36,2% | -13,7% | **-16,1%** | **-22,2%** | -16,1% | -1,7 |
| tudo 2020–2025 | 3m | 80 | 36,2% | 33,8% | -24,1% | **-29,1%** | **-39,0%** | -29,6% | -2,4 |
| tudo 2020–2025 | 6m | 80 | 30,0% | 26,2% | +604,0% | **+594,5%** | **-66,2%** | +253,6% | 1,1 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

_Sem dados._

Funil (576 sinais): sem ticker 335 (58,2%); sem preços no Yahoo (deslistado ou desconhecido) 118 (20,5%); medido 80 (13,9%); sem preço perto da entrada 37 (6,4%); salto suspeito (grupamento não ajustado) 6 (1,0%).

Por ano (1m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 10 | -2,9% | -3,9% |
| 2021 | 12 | +30,9% | +9,3% |
| 2022 | 4 | +1,9% | +0,5% |
| 2023 | 26 | -35,0% | -37,2% |
| 2024 | 22 | -23,8% | -36,2% |
| 2025 | 6 | -34,4% | -50,0% |

## `auditor_change_8k` — Troca de auditor (8-K)

Regra: 8-K com item 4.01 (troca do auditor independente). Hipótese: fica atrás do índice. Prazo principal: 3 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 1.139 | 38,2% | 39,5% | +3,2% | **+2,4%** | **-5,1%** | -0,3% | 1,5 |
| treino 2020–2022 | 3m | 1.139 | 39,8% | 37,1% | +11,9% | **+9,2%** | **-9,3%** | -0,5% | 1,6 |
| treino 2020–2022 | 6m | 1.139 | 37,4% | 32,0% | +25,1% | **+19,2%** | **-18,4%** | -4,1% | 1,6 |
| teste 2023–2025 | 1m | 1.860 | 38,6% | 34,8% | +13,8% | **+11,6%** | **-4,8%** | -3,4% | 1,5 |
| teste 2023–2025 | 3m | 1.860 | 39,8% | 30,8% | +166,7% | **+160,4%** | **-12,4%** | -7,1% | 1,3 |
| teste 2023–2025 | 6m | 1.860 | 37,8% | 28,8% | +103,0% | **+91,1%** | **-24,8%** | -10,0% | 1,6 |
| tudo 2020–2025 | 1m | 2.999 | 38,4% | 36,6% | +9,8% | **+8,1%** | **-4,9%** | -2,1% | 1,8 |
| tudo 2020–2025 | 3m | 2.999 | 39,8% | 33,2% | +107,9% | **+103,0%** | **-11,1%** | -4,5% | 1,4 |
| tudo 2020–2025 | 6m | 2.999 | 37,6% | 30,0% | +73,4% | **+63,8%** | **-22,1%** | -7,4% | 1,9 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 1.139 | 38,2% | 38,8% | +3,2% | **+2,6%** | **-4,9%** | -0,1% | 1,7 |
| treino 2020–2022 | 3m | 1.139 | 39,8% | 39,5% | +11,9% | **+9,2%** | **-8,6%** | -0,6% | 1,7 |
| treino 2020–2022 | 6m | 1.139 | 37,4% | 33,9% | +25,1% | **+20,8%** | **-16,4%** | -2,5% | 1,6 |
| teste 2023–2025 | 1m | 1.860 | 38,6% | 37,9% | +13,8% | **+12,3%** | **-4,7%** | -2,7% | 1,5 |
| teste 2023–2025 | 3m | 1.860 | 39,8% | 33,3% | +166,7% | **+161,8%** | **-11,1%** | -5,7% | 1,3 |
| teste 2023–2025 | 6m | 1.860 | 37,8% | 30,5% | +103,0% | **+92,8%** | **-23,7%** | -8,2% | 1,6 |
| tudo 2020–2025 | 1m | 2.999 | 38,4% | 38,2% | +9,8% | **+8,6%** | **-4,7%** | -1,7% | 1,9 |
| tudo 2020–2025 | 3m | 2.999 | 39,8% | 35,7% | +107,9% | **+103,8%** | **-10,3%** | -3,9% | 1,4 |
| tudo 2020–2025 | 6m | 2.999 | 37,6% | 31,8% | +73,4% | **+65,4%** | **-20,6%** | -6,0% | 1,9 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 264 | 39,8% | -0,5% | -2,6% | -0,8 |
| 3m | 264 | 38,3% | -2,9% | -3,7% | -2,1 |
| 6m | 264 | 39,4% | -4,7% | -9,2% | -1,9 |

Funil (4.332 sinais): medido 2.999 (69,2%); sem ticker 656 (15,1%); sem preços no Yahoo (deslistado ou desconhecido) 405 (9,3%); sem preço perto da entrada 222 (5,1%); salto suspeito (grupamento não ajustado) 50 (1,2%).

Por ano (3m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 280 | +54,4% | +2,7% |
| 2021 | 389 | +1,6% | -14,8% |
| 2022 | 470 | -11,5% | -10,3% |
| 2023 | 575 | +424,0% | -16,0% |
| 2024 | 669 | +18,9% | -13,6% |
| 2025 | 616 | +68,2% | -7,7% |

## `late_filing_nt` — Relatório atrasado (NT)

Regra: NT 10-K ou NT 10-Q original. Hipótese: fica atrás do índice. Prazo principal: 3 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 3.323 | 36,3% | 40,4% | +8,3% | **+8,6%** | **-4,1%** | +0,4% | 1,9 |
| treino 2020–2022 | 3m | 3.323 | 37,6% | 34,6% | +298,5% | **+295,4%** | **-11,4%** | +10,5% | 1,8 |
| treino 2020–2022 | 6m | 3.323 | 36,2% | 32,1% | +135,1% | **+129,8%** | **-22,6%** | +16,2% | 2,3 |
| teste 2023–2025 | 1m | 4.949 | 35,8% | 34,2% | +15,3% | **+13,8%** | **-4,8%** | -1,8% | 1,9 |
| teste 2023–2025 | 3m | 4.949 | 34,6% | 26,9% | +870,5% | **+864,3%** | **-16,9%** | -7,7% | 1,2 |
| teste 2023–2025 | 6m | 4.949 | 32,1% | 23,6% | +2.683,6% | **+2.672,6%** | **-33,3%** | -18,5% | 1,1 |
| tudo 2020–2025 | 1m | 8.272 | 36,0% | 36,7% | +12,5% | **+11,7%** | **-4,6%** | -0,9% | 2,7 |
| tudo 2020–2025 | 3m | 8.272 | 35,8% | 30,0% | +640,7% | **+635,8%** | **-14,8%** | -1,4% | 1,8 |
| tudo 2020–2025 | 6m | 8.272 | 33,8% | 27,0% | +1.659,8% | **+1.651,1%** | **-28,9%** | -5,1% | 1,2 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 3.323 | 36,3% | 41,6% | +8,3% | **+9,2%** | **-3,8%** | +1,0% | 2,0 |
| treino 2020–2022 | 3m | 3.323 | 37,6% | 36,7% | +298,5% | **+295,6%** | **-11,1%** | +10,6% | 1,8 |
| treino 2020–2022 | 6m | 3.323 | 36,2% | 34,0% | +135,1% | **+130,3%** | **-22,2%** | +16,8% | 2,3 |
| teste 2023–2025 | 1m | 4.949 | 35,8% | 39,2% | +15,3% | **+14,4%** | **-5,2%** | -1,2% | 2,0 |
| teste 2023–2025 | 3m | 4.949 | 34,6% | 30,1% | +870,5% | **+866,0%** | **-15,7%** | -6,0% | 1,2 |
| teste 2023–2025 | 6m | 4.949 | 32,1% | 26,5% | +2.683,6% | **+2.675,0%** | **-30,9%** | -16,0% | 1,1 |
| tudo 2020–2025 | 1m | 8.272 | 36,0% | 40,1% | +12,5% | **+12,3%** | **-4,5%** | -0,3% | 2,8 |
| tudo 2020–2025 | 3m | 8.272 | 35,8% | 32,8% | +640,7% | **+636,8%** | **-14,0%** | -0,4% | 1,8 |
| tudo 2020–2025 | 6m | 8.272 | 33,8% | 29,5% | +1.659,8% | **+1.652,8%** | **-27,1%** | -3,5% | 1,2 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 253 | 35,6% | -4,4% | -4,2% | -2,0 |
| 3m | 253 | 31,6% | -8,9% | -8,1% | -2,1 |
| 6m | 253 | 29,6% | -14,8% | -14,2% | -3,3 |

Funil (14.320 sinais): medido 8.272 (57,8%); sem ticker 3.340 (23,3%); sem preços no Yahoo (deslistado ou desconhecido) 1.731 (12,1%); sem preço perto da entrada 731 (5,1%); salto suspeito (grupamento não ajustado) 246 (1,7%).

Por ano (3m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 830 | +903,7% | -1,6% |
| 2021 | 1.141 | +2,7% | -14,7% |
| 2022 | 1.352 | +169,0% | -13,8% |
| 2023 | 1.752 | +2.116,3% | -18,5% |
| 2024 | 1.804 | +22,0% | -19,1% |
| 2025 | 1.393 | +380,4% | -12,9% |

## `form144_cluster` — Grupo de Form 144

Regra: pelo menos 3 vendedores distintos arquivam Form 144 original do mesmo emissor em 10 dias corridos; dispara na data do terceiro; cooldown de 30 dias. Hipótese: fica atrás do índice. Prazo principal: 3 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| 2023-05 → 2024-06 | 1m | 2.598 | 54,0% | 42,5% | +1,3% | **-1,0%** | **-1,5%** | -1,1% | -1,3 |
| 2023-05 → 2024-06 | 3m | 2.598 | 52,5% | 40,3% | +1,6% | **-3,9%** | **-4,2%** | -4,3% | -3,1 |
| 2023-05 → 2024-06 | 6m | 2.598 | 57,0% | 39,6% | +7,5% | **-5,0%** | **-7,2%** | -5,6% | -2,7 |
| 2024-07 → 2025-12 | 1m | 3.532 | 49,5% | 44,7% | +1,0% | **+0,1%** | **-1,2%** | -0,2% | -0,1 |
| 2024-07 → 2025-12 | 3m | 3.532 | 50,8% | 43,0% | +4,9% | **+1,1%** | **-3,4%** | +0,2% | 0,7 |
| 2024-07 → 2025-12 | 6m | 3.532 | 51,1% | 40,5% | +9,8% | **+1,8%** | **-6,9%** | +0,4% | 1,2 |
| tudo (2023-05 → 2025-12) | 1m | 6.130 | 51,4% | 43,8% | +1,1% | **-0,4%** | **-1,4%** | -0,6% | -1,0 |
| tudo (2023-05 → 2025-12) | 3m | 6.130 | 51,5% | 41,8% | +3,5% | **-1,0%** | **-3,7%** | -1,7% | -0,9 |
| tudo (2023-05 → 2025-12) | 6m | 6.130 | 53,6% | 40,1% | +8,8% | **-1,1%** | **-7,1%** | -2,1% | -0,5 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| 2023-05 → 2024-06 | 1m | 2.598 | 54,0% | 48,1% | +1,3% | **-0,1%** | **-0,5%** | -0,3% | -0,6 |
| 2023-05 → 2024-06 | 3m | 2.598 | 52,5% | 46,7% | +1,6% | **-1,4%** | **-1,6%** | -1,8% | -2,0 |
| 2023-05 → 2024-06 | 6m | 2.598 | 57,0% | 45,2% | +7,5% | **-1,1%** | **-3,2%** | -1,7% | -0,9 |
| 2024-07 → 2025-12 | 1m | 3.532 | 49,5% | 45,7% | +1,0% | **+0,1%** | **-0,9%** | -0,1% | -0,0 |
| 2024-07 → 2025-12 | 3m | 3.532 | 50,8% | 45,3% | +4,9% | **+1,4%** | **-2,3%** | +0,6% | 0,8 |
| 2024-07 → 2025-12 | 6m | 3.532 | 51,1% | 43,2% | +9,8% | **+2,1%** | **-5,3%** | +0,7% | 1,2 |
| tudo (2023-05 → 2025-12) | 1m | 6.130 | 51,4% | 46,7% | +1,1% | **+0,1%** | **-0,7%** | -0,2% | -0,3 |
| tudo (2023-05 → 2025-12) | 3m | 6.130 | 51,5% | 45,9% | +3,5% | **+0,2%** | **-1,9%** | -0,4% | -0,0 |
| tudo (2023-05 → 2025-12) | 6m | 6.130 | 53,6% | 44,0% | +8,8% | **+0,7%** | **-4,2%** | -0,3% | 0,7 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 4.198 | 43,9% | -0,5% | -1,2% | -1,5 |
| 3m | 4.198 | 42,4% | -1,2% | -3,2% | -1,2 |
| 6m | 4.198 | 40,7% | -1,2% | -5,7% | -0,7 |

Funil (6.749 sinais): medido 6.130 (90,8%); sem preços no Yahoo (deslistado ou desconhecido) 427 (6,3%); sem preço perto da entrada 131 (1,9%); sem ticker 61 (0,9%).

Por ano (3m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2023 | 1.317 | -4,0% | -3,8% |
| 2024 | 2.492 | -0,2% | -2,7% |
| 2025 | 2.321 | -0,3% | -4,8% |

## `fund_consensus_13f` — Consenso de fundos (13F)

Regra: as 30 ações com maior ganho de alcance entre os gestores ativos do 13F (20 a 500 posições, arquivado até o prazo de 45 dias e também no trimestre anterior), universo com 20 ou mais detentores; datado no prazo. Hipótese: bate o índice. Prazo principal: 3 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 341 | 38,4% | 49,3% | -4,0% | **-0,1%** | **-0,2%** | -0,2% | -0,0 |
| treino 2020–2022 | 3m | 341 | 46,6% | 41,6% | +1,1% | **-1,0%** | **-2,7%** | -1,2% | -0,5 |
| treino 2020–2022 | 6m | 341 | 56,6% | 42,5% | +3,8% | **-1,5%** | **-2,5%** | -1,8% | -0,6 |
| teste 2023–2025 | 1m | 349 | 52,7% | 43,0% | +1,1% | **-0,2%** | **-1,2%** | -0,2% | -0,2 |
| teste 2023–2025 | 3m | 349 | 63,6% | 48,4% | +6,7% | **+2,0%** | **-0,2%** | +1,9% | 1,7 |
| teste 2023–2025 | 6m | 349 | 72,8% | 51,9% | +15,8% | **+5,6%** | **+1,4%** | +5,1% | 2,4 |
| tudo 2020–2025 | 1m | 690 | 45,7% | 46,1% | -1,4% | **-0,1%** | **-0,7%** | -0,2% | -0,1 |
| tudo 2020–2025 | 3m | 690 | 55,2% | 45,1% | +3,9% | **+0,5%** | **-1,5%** | +0,4% | 0,4 |
| tudo 2020–2025 | 6m | 690 | 64,8% | 47,2% | +9,9% | **+2,1%** | **-0,7%** | +1,8% | 1,2 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 341 | 38,4% | 53,4% | -4,0% | **+1,2%** | **+0,3%** | +1,2% | 1,1 |
| treino 2020–2022 | 3m | 341 | 46,6% | 46,0% | +1,1% | **-0,6%** | **-1,2%** | -0,8% | -0,2 |
| treino 2020–2022 | 6m | 341 | 56,6% | 48,4% | +3,8% | **-0,9%** | **-0,4%** | -1,3% | -0,3 |
| teste 2023–2025 | 1m | 349 | 52,7% | 49,0% | +1,1% | **+0,3%** | **-0,1%** | +0,3% | 0,2 |
| teste 2023–2025 | 3m | 349 | 63,6% | 56,2% | +6,7% | **+3,5%** | **+2,3%** | +3,3% | 2,5 |
| teste 2023–2025 | 6m | 349 | 72,8% | 61,6% | +15,8% | **+8,3%** | **+6,4%** | +7,9% | 2,9 |
| tudo 2020–2025 | 1m | 690 | 45,7% | 51,2% | -1,4% | **+0,8%** | **+0,2%** | +0,7% | 0,9 |
| tudo 2020–2025 | 3m | 690 | 55,2% | 51,2% | +3,9% | **+1,4%** | **+0,4%** | +1,3% | 1,1 |
| tudo 2020–2025 | 6m | 690 | 64,8% | 55,1% | +9,9% | **+3,8%** | **+2,4%** | +3,4% | 1,8 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 269 | 45,4% | +0,3% | -1,1% | 0,3 |
| 3m | 269 | 50,6% | +2,9% | +0,2% | 1,9 |
| 6m | 269 | 53,9% | +7,0% | +3,8% | 2,5 |

Funil (720 sinais): medido 690 (95,8%); sem ticker 19 (2,6%); sem preços no Yahoo (deslistado ou desconhecido) 10 (1,4%); sem preço perto da entrada 1 (0,1%).

Por ano (3m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 115 | +3,1% | -1,1% |
| 2021 | 113 | -3,6% | -4,9% |
| 2022 | 113 | -2,7% | -3,5% |
| 2023 | 114 | +1,8% | +0,0% |
| 2024 | 117 | +2,2% | -0,1% |
| 2025 | 118 | +2,1% | -1,1% |

## `notable_fund_new_13f` — Fundo notável, posição nova

Regra: um gestor da lista fixa abre posição ausente do 13F anterior, valendo 1% ou mais do 13F; datado no arquivamento. Hipótese: bate o índice. Prazo principal: 3 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 545 | 45,1% | 50,1% | -3,3% | **-0,6%** | **+0,0%** | -0,7% | -0,7 |
| treino 2020–2022 | 3m | 545 | 56,5% | 46,4% | +1,7% | **-1,7%** | **-1,5%** | -1,8% | -1,1 |
| treino 2020–2022 | 6m | 545 | 56,3% | 44,8% | +4,8% | **-2,9%** | **-2,8%** | -3,2% | -1,3 |
| teste 2023–2025 | 1m | 619 | 53,2% | 44,4% | +1,1% | **-0,2%** | **-1,0%** | -0,3% | -0,2 |
| teste 2023–2025 | 3m | 619 | 59,6% | 45,9% | +4,5% | **-0,1%** | **-1,1%** | -0,2% | -0,0 |
| teste 2023–2025 | 6m | 619 | 61,2% | 42,8% | +9,4% | **-0,8%** | **-4,4%** | -1,2% | -0,2 |
| tudo 2020–2025 | 1m | 1.164 | 49,4% | 47,1% | -1,0% | **-0,4%** | **-0,6%** | -0,5% | -0,7 |
| tudo 2020–2025 | 3m | 1.164 | 58,2% | 46,1% | +3,2% | **-0,8%** | **-1,3%** | -1,0% | -1,0 |
| tudo 2020–2025 | 6m | 1.164 | 58,9% | 43,7% | +7,2% | **-1,8%** | **-4,0%** | -2,1% | -1,3 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 545 | 45,1% | 49,5% | -3,3% | **-0,1%** | **-0,1%** | -0,2% | -0,2 |
| treino 2020–2022 | 3m | 545 | 56,5% | 42,6% | +1,7% | **-2,1%** | **-2,5%** | -2,2% | -1,6 |
| treino 2020–2022 | 6m | 545 | 56,3% | 42,0% | +4,8% | **-4,0%** | **-4,4%** | -4,4% | -1,6 |
| teste 2023–2025 | 1m | 619 | 53,2% | 48,0% | +1,1% | **+0,2%** | **-0,5%** | +0,1% | 0,4 |
| teste 2023–2025 | 3m | 619 | 59,6% | 50,2% | +4,5% | **+1,2%** | **+0,0%** | +1,1% | 1,0 |
| teste 2023–2025 | 6m | 619 | 61,2% | 50,6% | +9,4% | **+1,9%** | **+0,2%** | +1,5% | 0,8 |
| tudo 2020–2025 | 1m | 1.164 | 49,4% | 48,7% | -1,0% | **+0,1%** | **-0,2%** | -0,0% | 0,0 |
| tudo 2020–2025 | 3m | 1.164 | 58,2% | 46,6% | +3,2% | **-0,3%** | **-1,1%** | -0,4% | -0,4 |
| tudo 2020–2025 | 6m | 1.164 | 58,9% | 46,6% | +7,2% | **-0,9%** | **-1,7%** | -1,2% | -0,5 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 463 | 47,7% | +0,5% | -0,7% | 0,6 |
| 3m | 463 | 46,7% | +0,5% | -1,1% | 0,5 |
| 6m | 463 | 44,5% | +0,3% | -3,7% | 0,3 |

Funil (1.326 sinais): medido 1.164 (87,8%); sem preços no Yahoo (deslistado ou desconhecido) 135 (10,2%); sem preço perto da entrada 27 (2,0%).

Por ano (3m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 216 | +4,7% | +2,8% |
| 2021 | 172 | -7,2% | -4,7% |
| 2022 | 157 | -4,5% | -3,4% |
| 2023 | 199 | +0,5% | -0,3% |
| 2024 | 200 | +0,7% | -1,4% |
| 2025 | 220 | -1,4% | -2,0% |

## `short_crowded` — Short lotado

Regra: FINRA com 7 ou mais dias para zerar, short de 1 mi de ações ou mais, alta de 25% ou mais sobre o relatório anterior e volume médio de 100 mil ou mais; datado na liquidação + 10 dias úteis. Hipótese: fica atrás do índice. Prazo principal: 1 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 710 | 49,6% | 44,9% | -0,1% | **-0,7%** | **-1,3%** | -0,9% | -0,4 |
| treino 2020–2022 | 3m | 710 | 44,8% | 41,4% | +0,7% | **-1,6%** | **-3,7%** | -2,0% | -0,0 |
| treino 2020–2022 | 6m | 710 | 45,6% | 36,5% | +2,1% | **-3,2%** | **-8,4%** | -3,9% | -0,4 |
| teste 2023–2025 | 1m | 916 | 50,0% | 41,4% | +0,4% | **-1,3%** | **-1,7%** | -1,6% | -1,0 |
| teste 2023–2025 | 3m | 916 | 56,3% | 44,5% | +5,5% | **+0,3%** | **-2,7%** | -1,3% | 0,3 |
| teste 2023–2025 | 6m | 916 | 54,5% | 36,6% | +8,7% | **-1,7%** | **-7,7%** | -4,4% | -0,3 |
| tudo 2020–2025 | 1m | 1.626 | 49,8% | 42,9% | +0,2% | **-1,0%** | **-1,5%** | -1,4% | -1,0 |
| tudo 2020–2025 | 3m | 1.626 | 51,3% | 43,2% | +3,4% | **-0,5%** | **-3,2%** | -1,6% | 0,2 |
| tudo 2020–2025 | 6m | 1.626 | 50,6% | 36,5% | +5,8% | **-2,3%** | **-8,0%** | -4,1% | -0,5 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 710 | 49,6% | 46,8% | -0,1% | **-0,5%** | **-0,9%** | -0,9% | -0,2 |
| treino 2020–2022 | 3m | 710 | 44,8% | 43,9% | +0,7% | **-1,4%** | **-3,0%** | -1,9% | -0,1 |
| treino 2020–2022 | 6m | 710 | 45,6% | 41,3% | +2,1% | **-2,3%** | **-5,7%** | -3,1% | -0,7 |
| teste 2023–2025 | 1m | 916 | 50,0% | 45,9% | +0,4% | **-0,6%** | **-0,8%** | -1,0% | -0,6 |
| teste 2023–2025 | 3m | 916 | 56,3% | 47,7% | +5,5% | **+2,1%** | **-0,8%** | +0,4% | 1,4 |
| teste 2023–2025 | 6m | 916 | 54,5% | 43,1% | +8,7% | **+1,4%** | **-5,1%** | -1,4% | 0,6 |
| tudo 2020–2025 | 1m | 1.626 | 49,8% | 46,2% | +0,2% | **-0,6%** | **-0,9%** | -0,9% | -0,6 |
| tudo 2020–2025 | 3m | 1.626 | 51,3% | 46,1% | +3,4% | **+0,6%** | **-1,8%** | -0,6% | 0,8 |
| tudo 2020–2025 | 6m | 1.626 | 50,6% | 42,3% | +5,8% | **-0,2%** | **-5,3%** | -2,1% | 0,0 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 584 | 41,6% | -1,3% | -1,3% | -2,1 |
| 3m | 584 | 43,5% | -1,8% | -2,5% | -1,1 |
| 6m | 584 | 36,3% | -2,9% | -6,6% | -0,6 |

Funil (1.652 sinais): medido 1.626 (98,4%); sem preço perto da entrada 25 (1,5%); sem preços no Yahoo (deslistado ou desconhecido) 1 (0,1%).

Por ano (1m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 182 | +3,6% | +0,4% |
| 2021 | 237 | -4,4% | -2,2% |
| 2022 | 291 | -0,4% | -1,1% |
| 2023 | 326 | -1,7% | -2,4% |
| 2024 | 341 | -3,4% | -2,0% |
| 2025 | 249 | +2,3% | -0,4% |

## `squeeze_setup` — Squeeze em formação

Regra: 7 ou mais dias para zerar, short em queda de 15% ou mais e preço em alta de 20% ou mais nos 10 pregões até a data do sinal. Hipótese: bate o índice. Prazo principal: 1 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 72 | 43,1% | 45,8% | +0,8% | **+1,0%** | **-2,0%** | +0,0% | 0,7 |
| treino 2020–2022 | 3m | 72 | 50,0% | 43,1% | +14,4% | **+10,5%** | **-10,1%** | +5,9% | 0,7 |
| treino 2020–2022 | 6m | 72 | 44,4% | 38,9% | +19,3% | **+10,3%** | **-14,1%** | +7,3% | 0,6 |
| teste 2023–2025 | 1m | 93 | 33,3% | 31,2% | -2,7% | **-4,8%** | **-8,3%** | -5,3% | -2,5 |
| teste 2023–2025 | 3m | 93 | 33,3% | 31,2% | -1,7% | **-7,8%** | **-15,7%** | -9,2% | -0,1 |
| teste 2023–2025 | 6m | 93 | 31,2% | 22,6% | -2,9% | **-13,2%** | **-28,9%** | -13,4% | -0,2 |
| tudo 2020–2025 | 1m | 165 | 37,6% | 37,6% | -1,2% | **-2,3%** | **-6,3%** | -2,9% | -1,2 |
| tudo 2020–2025 | 3m | 165 | 40,6% | 36,4% | +5,3% | **+0,2%** | **-13,3%** | -2,9% | 0,3 |
| tudo 2020–2025 | 6m | 165 | 37,0% | 29,7% | +6,7% | **-2,9%** | **-23,1%** | -4,1% | 0,1 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 72 | 43,1% | 41,7% | +0,8% | **+0,2%** | **-2,6%** | -0,7% | 0,8 |
| treino 2020–2022 | 3m | 72 | 50,0% | 38,9% | +14,4% | **+7,2%** | **-10,2%** | +2,4% | 0,7 |
| treino 2020–2022 | 6m | 72 | 44,4% | 34,7% | +19,3% | **+7,0%** | **-14,4%** | +3,8% | 0,6 |
| teste 2023–2025 | 1m | 93 | 33,3% | 37,6% | -2,7% | **-4,3%** | **-6,7%** | -4,7% | -2,5 |
| teste 2023–2025 | 3m | 93 | 33,3% | 32,3% | -1,7% | **-5,7%** | **-13,4%** | -7,0% | 0,0 |
| teste 2023–2025 | 6m | 93 | 31,2% | 25,8% | -2,9% | **-9,5%** | **-23,4%** | -9,7% | -0,0 |
| tudo 2020–2025 | 1m | 165 | 37,6% | 39,4% | -1,2% | **-2,3%** | **-5,2%** | -2,9% | -1,0 |
| tudo 2020–2025 | 3m | 165 | 40,6% | 35,2% | +5,3% | **-0,1%** | **-13,4%** | -3,1% | 0,4 |
| tudo 2020–2025 | 6m | 165 | 37,0% | 29,7% | +6,7% | **-2,3%** | **-22,1%** | -3,6% | 0,2 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 26 | 34,6% | -3,0% | -8,6% | -0,8 |
| 3m | 26 | 30,8% | -12,4% | -18,7% | -3,1 |
| 6m | 26 | 19,2% | -23,5% | -28,6% | -3,5 |

Funil (166 sinais): medido 165 (99,4%); salto suspeito (grupamento não ajustado) 1 (0,6%).

Por ano (1m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 32 | -1,2% | -3,9% |
| 2021 | 13 | -2,2% | -1,2% |
| 2022 | 27 | +5,1% | -0,3% |
| 2023 | 25 | -9,6% | -9,2% |
| 2024 | 40 | -3,0% | -5,3% |
| 2025 | 28 | -3,1% | -8,9% |

## `ftd_persistent` — Falhas de entrega persistentes

Regra: falhas de 10 mil ações ou mais e de 0,5% ou mais das ações em circulação em 5 ou mais liquidações seguidas num arquivo quinzenal da SEC; datado na publicação do arquivo. Hipótese: fica atrás do índice. Prazo principal: 1 mês(es).

Contra o SPY:

| Período | Prazo | N | Acerto | Bate SPY | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 364 | 38,5% | 34,6% | +1,2% | **+0,1%** | **-6,7%** | -0,8% | -1,6 |
| treino 2020–2022 | 3m | 364 | 34,6% | 29,7% | +1,6% | **-0,5%** | **-16,0%** | -6,5% | -3,1 |
| treino 2020–2022 | 6m | 364 | 25,3% | 20,6% | -17,3% | **-21,0%** | **-36,0%** | -24,1% | -8,3 |
| teste 2023–2025 | 1m | 587 | 27,3% | 25,6% | -11,1% | **-12,8%** | **-16,5%** | -13,6% | -5,3 |
| teste 2023–2025 | 3m | 587 | 24,0% | 19,1% | -10,6% | **-15,5%** | **-35,4%** | -26,2% | -4,4 |
| teste 2023–2025 | 6m | 587 | 22,8% | 18,1% | -18,9% | **-28,8%** | **-54,9%** | -38,8% | -7,8 |
| tudo 2020–2025 | 1m | 951 | 31,5% | 29,0% | -6,4% | **-7,9%** | **-12,4%** | -8,5% | -4,7 |
| tudo 2020–2025 | 3m | 951 | 28,1% | 23,1% | -5,9% | **-9,8%** | **-27,6%** | -19,1% | -5,4 |
| tudo 2020–2025 | 6m | 951 | 23,8% | 19,0% | -18,3% | **-25,8%** | **-46,8%** | -33,0% | -10,9 |

Contra o IWM:

| Período | Prazo | N | Acerto | Bate IWM | Retorno médio | Excesso médio | Excesso mediano | Excesso winsor. | t (safra mensal) |
|---|---|---|---|---|---|---|---|---|---|
| treino 2020–2022 | 1m | 364 | 38,5% | 34,9% | +1,2% | **-0,3%** | **-8,7%** | -1,2% | -1,5 |
| treino 2020–2022 | 3m | 364 | 34,6% | 30,5% | +1,6% | **+0,3%** | **-15,6%** | -5,6% | -2,8 |
| treino 2020–2022 | 6m | 364 | 25,3% | 22,8% | -17,3% | **-16,7%** | **-29,5%** | -19,8% | -7,3 |
| teste 2023–2025 | 1m | 587 | 27,3% | 25,7% | -11,1% | **-12,4%** | **-16,5%** | -13,2% | -5,2 |
| teste 2023–2025 | 3m | 587 | 24,0% | 20,8% | -10,6% | **-14,9%** | **-33,4%** | -25,7% | -4,3 |
| teste 2023–2025 | 6m | 587 | 22,8% | 18,7% | -18,9% | **-27,9%** | **-53,8%** | -37,8% | -7,7 |
| tudo 2020–2025 | 1m | 951 | 31,5% | 29,2% | -6,4% | **-7,8%** | **-12,4%** | -8,5% | -4,7 |
| tudo 2020–2025 | 3m | 951 | 28,1% | 24,5% | -5,9% | **-9,1%** | **-26,0%** | -18,4% | -5,0 |
| tudo 2020–2025 | 6m | 951 | 23,8% | 20,3% | -18,3% | **-23,6%** | **-42,5%** | -30,8% | -10,3 |

Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, contra o SPY:

| Prazo | N | Bate SPY | Excesso médio | Excesso mediano | t (safra mensal) |
|---|---|---|---|---|---|
| 1m | 71 | 47,9% | -1,1% | -2,9% | -0,8 |
| 3m | 71 | 28,2% | -0,6% | -14,3% | -0,6 |
| 6m | 71 | 32,4% | -2,4% | -22,5% | -1,3 |

Funil (984 sinais): medido 951 (96,6%); sem preço perto da entrada 27 (2,7%); salto suspeito (grupamento não ajustado) 5 (0,5%); sem preços no Yahoo (deslistado ou desconhecido) 1 (0,1%).

Por ano (1m contra o SPY):

| Ano | N | Excesso médio | Excesso mediano |
|---|---|---|---|
| 2020 | 70 | +24,6% | +6,3% |
| 2021 | 152 | -1,8% | -8,6% |
| 2022 | 142 | -10,1% | -11,8% |
| 2023 | 99 | -8,8% | -14,3% |
| 2024 | 198 | -11,1% | -15,0% |
| 2025 | 290 | -15,4% | -17,5% |

## Funil dos dados

- **eightk**: queries 1.900, hits 31.009, filings 24.987, buyback 5.459, exit 1.717, item_4.01 8.172, nt 14.963, item_1.03 698
- **form144**: hits 97.157, notices 95.995, amendments 1.162, unparsed 0
- **ftd**: files 144, cusips_mapped 35.800
- **thirteenf**: reports_read 189.791, quarters 25, active_filers_median 4.533, unmapped_top 19
- **short**: settlement_dates 144, squeeze_candidates 3.729

## Limitações

1. **Viés de sobrevivência.** Os preços vêm do Yahoo, que quase não tem tickers deslistados, e os tickers vêm da lista atual da SEC. Falências, atrasos de relatório e empresas em crise são as que mais faltam, então os sinais de *evitar* são medidos nos sobreviventes e provavelmente parecem menos negativos do que foram.
2. **O Form 144 tem 2,7 anos de histórico** (eletrônico só desde 2023-04-13), sem período de treino, e só a regra de contagem é testada; o `form144_large`, por valor, aparece ao vivo mas não foi testado.
3. **Cobertura da busca textual.** As regras de 8-K dependem da busca textual do EDGAR. Um filing que descreve a recompra ou a renúncia com outras palavras escapa, e as buscas por item precisam do título ("Item 1.03") em algum documento do filing.
4. **Defasagem do 13F.** O consenso é datado no prazo de 45 dias e usa só os 13F arquivados até lá; as posições têm até 4,5 meses nessa data. Os CUSIPs viram tickers pelos arquivos de falhas de entrega da SEC, que só listam papéis que já tiveram falhas.
5. **Data do short interest.** O dado da FINRA é datado 10 dias úteis depois da liquidação, por segurança; a publicação real costuma vir 2 a 3 dias antes.
6. **Data das falhas de entrega**: a mais tardia entre o Last-Modified HTTP e uma regra de calendário conservadora; um arquivo republicado depois só atrasa a data.
7. **Prazos sobrepostos e sinais agrupados.** O t por safra mensal corrige parte disso, não tudo. São onze testes principais; espera-se cerca de um falso positivo a 5% por acaso.
8. **Execução idealizada.** De fechamento a fechamento, custo fixo, sem impacto no preço; nenhum sinal aqui exige venda a descoberto.
