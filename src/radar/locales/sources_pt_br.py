"""Brazilian Portuguese messages of the extra signal sources."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    "source.insiders": "Insiders",
    "source.form144": "Form 144",
    "source.thirteenf": "13F",
    "source.eightk": "8-K",
    "source.short": "Short",
    "signal.form144_cluster": "Grupo de Form 144",
    "signal.form144_large": "Venda planejada grande (144)",
    "signal.fund_consensus_13f": "Consenso de fundos (13F)",
    "signal.notable_fund_new_13f": "Fundo notável, posição nova",
    "signal.buyback_8k": "Recompra autorizada (8-K)",
    "signal.ceo_cfo_exit_8k": "Saída de CEO/CFO (8-K)",
    "signal.bankruptcy_8k": "Falência (8-K)",
    "signal.auditor_change_8k": "Troca de auditor (8-K)",
    "signal.late_filing_nt": "Relatório atrasado (NT)",
    "signal.short_crowded": "Short lotado",
    "signal.squeeze_setup": "Squeeze em formação",
    "signal.ftd_persistent": "Falhas de entrega persistentes",
    "explain.form144_cluster": (
        "{n} insiders arquivaram Form 144 (aviso de venda planejada) de {company} em "
        "{window} dias{total}. Vendedores: {who}."
    ),
    "explain.form144_cluster.total": ", cerca de {value} no total",
    "explain.form144_large": (
        "{seller} ({role}) planeja vender {value}{pct} de {company} (Form 144). "
        "Só contexto: esta regra não foi testada no backtest."
    ),
    "explain.form144_large.pct": " ({pct} das ações em circulação)",
    "explain.fund_consensus_13f": (
        "{delta} fundos ativos passaram a ter {company} ({before} → {now} de {total}) nos 13F "
        "do trimestre encerrado em {period}: {rank}º maior ganho de alcance do trimestre."
    ),
    "explain.notable_fund_new_13f": (
        "{manager} abriu posição nova em {company}, {weight} do seu 13F do trimestre "
        "encerrado em {period}."
    ),
    "explain.buyback_8k": "{company} anunciou uma nova autorização de recompra de ações (8-K).",
    "explain.ceo_cfo_exit_8k": "{company}: o {who} está saindo (8-K, item 5.02).",
    "explain.bankruptcy_8k": (
        "{company} informou falência ou recuperação judicial (8-K, item 1.03)."
    ),
    "explain.auditor_change_8k": "{company} trocou de auditor (8-K, item 4.01).",
    "explain.late_filing_nt": "{company} avisou a SEC que o {report} vai atrasar ({form}).",
    "explain.late_filing_nt.annual": "relatório anual (10-K)",
    "explain.late_filing_nt.quarterly": "relatório trimestral (10-Q)",
    "explain.short_crowded": (
        "As posições vendidas em {ticker} subiram {change}, para {shares} ações "
        "({dtc} dias para zerar), na liquidação de {settled}."
    ),
    "explain.squeeze_setup": (
        "Os vendidos em {ticker} estão recomprando ({change}, {dtc} dias para zerar) enquanto "
        "o preço subiu {move} em 10 pregões."
    ),
    "explain.ftd_persistent": (
        "{ticker} teve falhas de entrega acima de 0,5% das ações em {days} liquidações "
        "seguidas (pico de {peak} ações, {fraction} das ações em circulação)."
    ),
    "explain.untested": " Não testado no backtest.",
    "event.form144": "{seller} ({role}) planeja vender {value}",
    "event.8k": "8-K · {items}",
    "event.8k.none": "8-K · sem itens informados",
    "event.nt_filing": "{form}: {report} atrasado",
    "event.nt_filing.annual": "relatório anual",
    "event.nt_filing.quarterly": "relatório trimestral",
    "event.13f_filing": ("{manager} arquivou o 13F de {period}: {positions} posições, {new} novas"),
    "event.13f_consensus": "Consenso 13F de {period}: {filers} fundos ativos",
    "event.short_interest_release": (
        "Posições vendidas FINRA em {settled}: {symbols} papéis, {flagged} sinalizados"
    ),
    "event.ftd_release": "Falhas de entrega SEC {file}: {rows} linhas, {flagged} sinalizadas",
    "event.role.affiliate": "afiliado",
    "item.1.01": "Acordo relevante",
    "item.1.02": "Acordo encerrado",
    "item.1.03": "Falência",
    "item.1.05": "Incidente cibernético",
    "item.2.01": "Aquisição/venda concluída",
    "item.2.02": "Resultado divulgado",
    "item.2.03": "Nova dívida",
    "item.2.04": "Vencimento antecipado de dívida",
    "item.2.05": "Custos de saída",
    "item.2.06": "Baixa contábil",
    "item.3.01": "Aviso de deslistagem",
    "item.3.02": "Emissão sem registro",
    "item.3.03": "Direitos dos acionistas",
    "item.4.01": "Troca de auditor",
    "item.4.02": "Balanços não confiáveis",
    "item.5.01": "Mudança de controle",
    "item.5.02": "Troca de executivo/conselheiro",
    "item.5.03": "Estatuto/ano fiscal",
    "item.5.07": "Votação de acionistas",
    "item.7.01": "Divulgação Reg FD",
    "item.8.01": "Outros eventos",
    "item.9.01": "Anexos",
    "sources.rule.form144_cluster": (
        "pelo menos 3 vendedores distintos arquivam Form 144 original do mesmo emissor em "
        "10 dias corridos; dispara na data do terceiro; cooldown de 30 dias"
    ),
    "sources.rule.form144_large": (
        "um Form 144 de US$ 10 mi ou mais, ou de 1% ou mais das ações em circulação (não testado)"
    ),
    "sources.rule.fund_consensus_13f": (
        "as 30 ações com maior ganho de alcance entre os gestores ativos do 13F (20 a 500 "
        "posições, arquivado até o prazo de 45 dias e também no trimestre anterior), universo "
        "com 20 ou mais detentores; datado no prazo"
    ),
    "sources.rule.notable_fund_new_13f": (
        "um gestor da lista fixa abre posição ausente do 13F anterior, valendo 1% ou mais do "
        "13F; datado no arquivamento"
    ),
    "sources.rule.buyback_8k": (
        "o texto do 8-K traz uma das frases fixas de nova autorização de recompra; cooldown de "
        "90 dias"
    ),
    "sources.rule.ceo_cfo_exit_8k": (
        "8-K com item 5.02 cujo texto diz que o CEO ou o CFO renunciou, deixou o cargo ou foi "
        "desligado"
    ),
    "sources.rule.bankruptcy_8k": "8-K com item 1.03 (falência ou recuperação judicial)",
    "sources.rule.auditor_change_8k": "8-K com item 4.01 (troca do auditor independente)",
    "sources.rule.late_filing_nt": "NT 10-K ou NT 10-Q original",
    "sources.rule.short_crowded": (
        "FINRA com 7 ou mais dias para zerar, short de 1 mi de ações ou mais, alta de 25% ou "
        "mais sobre o relatório anterior e volume médio de 100 mil ou mais; datado na "
        "liquidação + 10 dias úteis"
    ),
    "sources.rule.squeeze_setup": (
        "7 ou mais dias para zerar, short em queda de 15% ou mais e preço em alta de 20% ou "
        "mais nos 10 pregões até a data do sinal"
    ),
    "sources.rule.ftd_persistent": (
        "falhas de 10 mil ações ou mais e de 0,5% ou mais das ações em circulação em 5 ou mais "
        "liquidações seguidas num arquivo quinzenal da SEC; datado na publicação do arquivo"
    ),
    "sources.status.ok": "medido",
    "sources.status.no_ticker": "sem ticker",
    "sources.status.no_prices": "sem preços no Yahoo (deslistado ou desconhecido)",
    "sources.status.no_entry_price": "sem preço perto da entrada",
    "sources.status.price_mismatch": "preço incompatível",
    "sources.status.suspect_jump": "salto suspeito (grupamento não ajustado)",
    "sources.report.title": "Novos sinais de mercado: backtest de {start} a {end}",
    "sources.report.generated": (
        "Gerado em {when}. Regras, períodos e critérios de veredito foram fixados antes em "
        "[`research/new-signals-plan.md`](../research/new-signals-plan.md). Preços: Yahoo "
        "Finance (ajustados), com o mesmo cache e o mesmo motor de entrada e saída do backtest "
        "de insiders. Nenhuma IA é usada."
    ),
    "sources.report.no_data": "_Sem dados._",
    "sources.report.h.verdict": "Veredito",
    "sources.report.verdict_intro": (
        "Prazo principal, excesso de retorno sobre o SPY, **período de teste 2023–2025** "
        "(Form 144: de 2023-05 a 2025-12, o único histórico eletrônico). Custos: 0,2% ida e "
        "volta; 1,0% quando o preço de entrada é menor que US$ 5."
    ),
    "sources.report.long": "compra",
    "sources.report.avoid": "evitar",
    "sources.report.months": "{n}m",
    "sources.report.verdict.use": "usar",
    "sources.report.verdict.maybe": "talvez",
    "sources.report.verdict.discard": "descartar",
    "sources.report.verdict.avoid": "evitar",
    "sources.report.verdict.maybe_avoid": "talvez (evitar)",
    "sources.report.verdict.insufficient": "dados insuficientes",
    "sources.report.reason.insufficient": (
        "{n} sinais medidos em {months} meses (exige {min_n} ou mais em {min_months} ou mais)"
    ),
    "sources.report.reason.use": "média e mediana do teste > 0, t = {t}, o treino concorda",
    "sources.report.reason.maybe_t": "média e mediana do teste > 0, mas t = {t}",
    "sources.report.reason.maybe_train": (
        "média e mediana do teste > 0 (t = {t}), mas o treino discorda"
    ),
    "sources.report.reason.discard_long": "o excesso do teste não é positivo na média e na mediana",
    "sources.report.reason.avoid": "média e mediana do teste < 0, t = {t}, o treino concorda",
    "sources.report.reason.maybe_avoid_t": "média e mediana do teste < 0, mas t = {t}",
    "sources.report.reason.maybe_avoid_train": (
        "média e mediana do teste < 0 (t = {t}), mas o treino discorda"
    ),
    "sources.report.reason.discard_avoid": (
        "o excesso do teste não é negativo na média e na mediana"
    ),
    "sources.report.reason.untested": "só contexto",
    "sources.report.col.signal": "Sinal",
    "sources.report.col.hypothesis": "Hipótese",
    "sources.report.col.primary": "Prazo",
    "sources.report.col.n_test": "N (teste)",
    "sources.report.col.exc_mean": "Excesso médio",
    "sources.report.col.exc_median": "Excesso mediano",
    "sources.report.col.beats_spy": "Bate SPY",
    "sources.report.col.t": "t (safra mensal)",
    "sources.report.col.train_mean": "Média treino",
    "sources.report.col.iwm_mean": "Média vs IWM",
    "sources.report.col.iwm_median": "Mediana vs IWM",
    "sources.report.col.verdict": "Veredito",
    "sources.report.col.period": "Período",
    "sources.report.col.horizon": "Prazo",
    "sources.report.col.n": "N",
    "sources.report.col.hit": "Acerto",
    "sources.report.col.beats": "Bate {name}",
    "sources.report.col.net_mean": "Retorno médio",
    "sources.report.col.exc_winsor": "Excesso winsor.",
    "sources.report.col.year": "Ano",
    "sources.report.col.measured": "Medidos",
    "sources.report.col.sub_penny": "Entrada < US$ 0,01",
    "sources.report.col.under_dollar": "Entrada < US$ 1",
    "sources.report.period.train": "treino 2020–2022",
    "sources.report.period.test": "teste 2023–2025",
    "sources.report.period.all": "tudo 2020–2025",
    "sources.report.period.f144_first": "2023-05 → 2024-06",
    "sources.report.period.f144_second": "2024-07 → 2025-12",
    "sources.report.period.f144_all": "tudo (2023-05 → 2025-12)",
    "sources.report.rule_line": (
        "Regra: {rule}. Hipótese: {hypothesis}. Prazo principal: {months} mês(es)."
    ),
    "sources.report.hyp_long": "bate o índice",
    "sources.report.hyp_avoid": "fica atrás do índice",
    "sources.report.against": "Contra o {name}:",
    "sources.report.liquid_line": (
        "Recorte líquido (preço ≥ US$ 5, valor de mercado ≥ US$ 300 mi), período de teste, "
        "contra o SPY:"
    ),
    "sources.report.funnel_line": "Funil ({n} sinais): {parts}.",
    "sources.report.by_year": "Por ano ({months}m contra o SPY):",
    "sources.report.h.quality": "Qualidade dos dados: cotações abaixo de um centavo",
    "sources.report.quality_text": (
        "Quem atrasa relatório, troca de auditor ou pede falência é quase sempre empresa de "
        "balcão. As séries do Yahoo delas trazem cotações de US$ 0,0001–0,001 que saltam para "
        "centavos ou dólares (um único negócio ou um grupamento não ajustado), o que vira "
        "retornos de milhares por cento. O filtro de salto do backtest de insiders ignora de "
        "propósito bases abaixo de US$ 0,01, então elas passam. Nestes sinais a **média não "
        "tem sentido**: leia a mediana, a média winsorizada e o recorte líquido."
    ),
    "sources.report.how_to_read": (
        "Como ler: *excesso* = retorno líquido menos o SPY nas mesmas datas. *Bate SPY* = "
        "fração dos sinais com excesso positivo. *t (safra mensal)* = estatística t da média "
        "do excesso por safra mensal (um ponto por mês, para sinais agrupados não inflarem o "
        "número). *evitar* = papéis de que convém ficar longe (um filtro, não uma recomendação "
        "de venda a descoberto)."
    ),
    "sources.report.survivorship": (
        "Viés de sobrevivência: o Yahoo quase não guarda histórico de empresas deslistadas. "
        "Sinais em empresas que depois faliram ou foram compradas ficam em geral sem medição, "
        "e isso pesa mais nos sinais de *evitar* (falências acima de tudo). Veja o funil de "
        "cada sinal."
    ),
    "sources.report.h.liquid": "Visão secundária: recorte líquido",
    "sources.report.liquid_intro": (
        "O plano fixou um recorte líquido (preço de entrada ≥ US$ 5 e valor de mercado ≥ "
        "US$ 300 mi) como visão reportada, não como base do veredito. A mesma regra de "
        "veredito aplicada a ele, para referência:"
    ),
    "sources.report.h.funnel": "Funil dos dados",
    "sources.report.h.limitations": "Limitações",
    "sources.report.limitation.1": (
        "**Viés de sobrevivência.** Os preços vêm do Yahoo, que quase não tem tickers "
        "deslistados, e os tickers vêm da lista atual da SEC. Falências, atrasos de relatório e "
        "empresas em crise são as que mais faltam, então os sinais de *evitar* são medidos nos "
        "sobreviventes e provavelmente parecem menos negativos do que foram."
    ),
    "sources.report.limitation.2": (
        "**O Form 144 tem 2,7 anos de histórico** (eletrônico só desde 2023-04-13), sem "
        "período de treino, e só a regra de contagem é testada; o `form144_large`, por valor, "
        "aparece ao vivo mas não foi testado."
    ),
    "sources.report.limitation.3": (
        "**Cobertura da busca textual.** As regras de 8-K dependem da busca textual do EDGAR. "
        "Um filing que descreve a recompra ou a renúncia com outras palavras escapa, e as "
        'buscas por item precisam do título ("Item 1.03") em algum documento do filing.'
    ),
    "sources.report.limitation.4": (
        "**Defasagem do 13F.** O consenso é datado no prazo de 45 dias e usa só os 13F "
        "arquivados até lá; as posições têm até 4,5 meses nessa data. Os CUSIPs viram tickers "
        "pelos arquivos de falhas de entrega da SEC, que só listam papéis que já tiveram falhas."
    ),
    "sources.report.limitation.5": (
        "**Data do short interest.** O dado da FINRA é datado 10 dias úteis depois da "
        "liquidação, por segurança; a publicação real costuma vir 2 a 3 dias antes."
    ),
    "sources.report.limitation.6": (
        "**Data das falhas de entrega**: a mais tardia entre o Last-Modified HTTP e uma regra "
        "de calendário conservadora; um arquivo republicado depois só atrasa a data."
    ),
    "sources.report.limitation.7": (
        "**Prazos sobrepostos e sinais agrupados.** O t por safra mensal corrige parte disso, "
        "não tudo. São onze testes principais; espera-se cerca de um falso positivo a 5% por "
        "acaso."
    ),
    "sources.report.limitation.8": (
        "**Execução idealizada.** De fechamento a fechamento, custo fixo, sem impacto no preço; "
        "nenhum sinal aqui exige venda a descoberto."
    ),
    "sources.cli.step.eightk": "8-K e NT: busca textual do EDGAR, mês a mês",
    "sources.cli.step.form144": "Form 144: busca textual do EDGAR, dia a dia (desde 2023-04-13)",
    "sources.cli.step.ftd": (
        "Falhas de entrega: arquivos quinzenais da SEC (e o mapa CUSIP → ticker)"
    ),
    "sources.cli.step.thirteenf": "13F: conjuntos de dados da SEC, um zip por vez",
    "sources.cli.step.short": "Short interest: datas de liquidação da FINRA",
    "sources.cli.step.prices": "Preços de {n} tickers (Yahoo, com cache)",
    "sources.cli.prices_done": (
        "    {cached} do cache, {downloaded} baixados, {no_data} sem dados, {failed} com falha"
    ),
    "cli.cycle.source_events": "{n} eventos das fontes extras",
    "cli.news.polled": (
        "{items} notícias novas de {feeds} feed(s), {matched} associadas a um ticker."
    ),
    "cli.news.note": "Feeds: {note}",
    "cli.news.no_registry": (
        "Não foi possível carregar a lista de tickers da SEC: as notícias foram guardadas sem "
        "associação."
    ),
    "cli.forward.empty": "Nada registrado ainda em {path}. Rode `radar watch` ou `radar serve`.",
    "cli.forward.title": "Registro do teste prospectivo: {path}",
    "cli.forward.day": "Dia (UTC)",
    "cli.forward.total": "Total",
    "cli.forward.records": "{n} registros em {days} dia(s)",
}
