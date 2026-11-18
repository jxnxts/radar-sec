"""Signal rules. Each test describes a situation the rule has to handle."""

from datetime import date, timedelta

import pytest

from radar.config import SignalConfig
from radar.models import Purchase, PurchaseFiling, Reporter, Schedule13D
from radar.roles import classify_title
from radar.signals import (
    ACTIVIST_13D,
    BIG_OFFICER_BUY,
    CLUSTER_BUY,
    detect_activist_13d,
    detect_big_officer_buys,
    detect_cluster_buys,
    explain,
    explanations,
)

CFG = SignalConfig()
D0 = date(2024, 3, 4)  # a Monday


def filing(
    accession: str,
    filed: date,
    owners: tuple[str, ...],
    value: float,
    *,
    issuer: str = "100",
    bought: date | None = None,
    price: float | None = None,
    after: float | None = None,
    ceo: bool = False,
    cfo: bool = False,
    od: bool = True,
    title: str = "",
    shares_after: float | None = None,
) -> PurchaseFiling:
    # Each filing trades at its own price, so the purchases do not look like the same one.
    price = price or 10.0 + (ord(accession[0]) - ord("a"))
    return PurchaseFiling(
        accession=accession,
        issuer_cik=issuer,
        issuer_name=f"Company {issuer}",
        ticker="CMP",
        filing_date=filed,
        owner_ciks=frozenset(owners),
        owner_names=tuple(f"Insider {o}" for o in owners),
        is_ceo=ceo,
        is_cfo=cfo,
        is_officer_or_director=od,
        officer_title=title,
        purchases=(Purchase(bought or filed - timedelta(days=1), value / price, price, after),),
        shares_after=shares_after if shares_after is not None else after,
    )


# ----------------------------------------------------------------------- role


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Chief Executive Officer", (True, False)),
        ("President & CEO", (True, False)),
        ("Co-CEO", (True, False)),
        ("Chief Financial Officer", (False, True)),
        ("Interim CFO", (False, True)),
        ("EVP, Chief Financial and Administrative Officer", (False, True)),
        ("CEO and CFO", (True, True)),
        ("Chief Operating Officer", (False, False)),
        ("SVP, General Counsel", (False, False)),
        ("Former CEO", (False, False)),
        ("", (False, False)),
        (None, (False, False)),
    ],
)
def test_classify_title(title, expected):
    assert classify_title(title) == expected


def test_classify_title_reads_remarks_when_told_to():
    assert classify_title("See Remarks", "Chief Executive Officer and Chairman") == (True, False)
    assert classify_title("See Remarks", "Senior Vice President") == (False, False)
    # Remarks only count when the title points to them.
    assert classify_title("VP Sales", "Reports to the Chief Executive Officer") == (False, False)


# ---------------------------------------------------------------- cluster_buy


def test_cluster_fires_when_second_insider_files():
    filings = [
        filing("a", D0, ("1",), 60_000),
        filing("b", D0 + timedelta(days=3), ("2",), 50_000),
    ]
    (signal,) = detect_cluster_buys(filings, CFG)
    assert signal.type == CLUSTER_BUY
    assert signal.signal_date == D0 + timedelta(days=3)  # filing date that closes the group
    assert signal.trigger_accession == "b"
    assert signal.details["n_insiders"] == 2
    assert signal.details["total_value"] == 110_000
    assert signal.details["accessions"] == ["a", "b"]
    assert signal.details["window_days"] == 14
    assert "2 distinct insiders" in signal.explanation
    assert 50 <= signal.score <= 100


def test_cluster_needs_minimum_total_value():
    filings = [filing("a", D0, ("1",), 40_000), filing("b", D0, ("2",), 50_000)]
    assert detect_cluster_buys(filings, CFG) == []


def test_cluster_needs_distinct_insiders():
    filings = [
        filing("a", D0, ("1",), 80_000),
        filing("b", D0 + timedelta(days=2), ("1",), 80_000),
    ]
    assert detect_cluster_buys(filings, CFG) == []


def test_joint_filing_counts_as_one_insider():
    # Fund, manager and partner in the same Form 4: a single purchase by a single insider.
    filings = [filing("a", D0, ("1", "2", "3"), 500_000)]
    assert detect_cluster_buys(filings, CFG) == []


def test_affiliates_filing_separately_for_the_same_trade_count_once():
    # Real pattern: each person in the group files their own Form 4 for the same trade.
    # The identical final position betrays the repetition: it is the same lot of shares.
    same = {"bought": D0 - timedelta(days=1), "price": 12.0, "after": 500_000}
    filings = [
        filing("a", D0, ("1",), 120_000, **same),
        filing("b", D0, ("2",), 120_000, **same),
        filing("c", D0, ("3",), 120_000, **same),
    ]
    assert detect_cluster_buys(filings, CFG) == []


def test_distinct_insiders_buying_identical_lots_still_count_separately():
    # Real pattern (Castellum, Mar 2023): five directors buy the same lot, at the same
    # price, on the same day. Each one ends up with a different position.
    same = {"bought": D0 - timedelta(days=1), "price": 12.0}
    filings = [
        filing("a", D0, ("1",), 60_000, after=54_116, **same),
        filing("b", D0, ("2",), 60_000, after=12_500, **same),
        filing("c", D0, ("3",), 60_000, after=30_567, **same),
    ]
    (signal,) = detect_cluster_buys(filings, CFG)
    assert signal.details["n_insiders"] == 3
    assert signal.details["total_value"] == 180_000


def test_owner_shared_between_filings_links_them():
    filings = [
        filing("a", D0, ("1", "9"), 80_000),
        filing("b", D0 + timedelta(days=1), ("2", "9"), 70_000),
    ]
    assert detect_cluster_buys(filings, CFG) == []


def test_cluster_ignores_purchases_older_than_the_window():
    filings = [
        filing("a", D0, ("1",), 80_000),
        filing("b", D0 + timedelta(days=20), ("2",), 80_000),
    ]
    assert detect_cluster_buys(filings, CFG) == []


def test_late_filing_of_an_old_purchase_does_not_count():
    # Filed inside the window, but the purchase itself was months earlier.
    filings = [
        filing("a", D0, ("1",), 80_000, bought=D0 - timedelta(days=90)),
        filing("b", D0 + timedelta(days=1), ("2",), 80_000),
    ]
    assert detect_cluster_buys(filings, CFG) == []


def test_no_lookahead_signal_never_uses_filings_from_the_future():
    # The second insider's purchase happened on day 1 but was only filed on day 10.
    # The signal can only exist on day 10, never earlier.
    early, late = D0, D0 + timedelta(days=10)
    filings = [
        filing("a", early, ("1",), 80_000),
        filing("b", late, ("2",), 80_000, bought=early - timedelta(days=1)),
    ]
    (signal,) = detect_cluster_buys(filings, CFG)
    assert signal.signal_date == late
    assert signal.trigger_accession == "b"
    assert signal.details["last_buy"] == (D0 - timedelta(days=1)).isoformat()


def test_cluster_cooldown_blocks_repeats_for_the_same_issuer():
    filings = [
        filing("a", D0, ("1",), 80_000),
        filing("b", D0 + timedelta(days=1), ("2",), 80_000),
        filing("c", D0 + timedelta(days=2), ("3",), 80_000),  # third insider, same wave
        filing("d", D0 + timedelta(days=40), ("4",), 80_000),
        filing("e", D0 + timedelta(days=41), ("5",), 80_000),  # new wave, outside the cooldown
    ]
    signals = detect_cluster_buys(filings, CFG)
    assert [s.trigger_accession for s in signals] == ["b", "e"]


def test_cluster_respects_signals_already_recorded():
    filings = [filing("a", D0, ("1",), 80_000), filing("b", D0 + timedelta(days=1), ("2",), 80_000)]
    prior = {"100": [D0 - timedelta(days=5)]}
    assert detect_cluster_buys(filings, CFG, prior_signals=prior) == []


def test_clusters_are_evaluated_per_issuer():
    filings = [
        filing("a", D0, ("1",), 80_000, issuer="100"),
        filing("b", D0, ("2",), 80_000, issuer="200"),
    ]
    assert detect_cluster_buys(filings, CFG) == []


def test_cluster_counts_officers_and_directors_separately_from_big_holders():
    filings = [
        filing("a", D0, ("1",), 80_000, od=True),
        filing("b", D0, ("2",), 80_000, od=False),  # 10% owner
    ]
    (signal,) = detect_cluster_buys(filings, CFG)
    assert signal.details["n_insiders"] == 2
    assert signal.details["n_officer_director"] == 1


def test_cluster_thresholds_are_configurable():
    cfg = SignalConfig(cluster_min_insiders=3, cluster_min_value=10_000)
    two = [filing("a", D0, ("1",), 80_000), filing("b", D0, ("2",), 80_000)]
    assert detect_cluster_buys(two, cfg) == []
    three = [*two, filing("c", D0, ("3",), 5_000)]
    assert len(detect_cluster_buys(three, cfg)) == 1


# ------------------------------------------------------------ big_officer_buy


def test_ceo_buying_above_threshold_fires():
    (signal,) = detect_big_officer_buys(
        [filing("a", D0, ("1",), 300_000, ceo=True, title="Chief Executive Officer")], CFG
    )
    assert signal.type == BIG_OFFICER_BUY
    assert signal.signal_date == D0
    assert signal.details["role"] == "CEO"
    assert signal.details["total_value"] == 300_000
    assert "CEO" in signal.explanation


def test_cfo_counts_and_ceo_scores_higher():
    (ceo,) = detect_big_officer_buys([filing("a", D0, ("1",), 300_000, ceo=True)], CFG)
    (cfo,) = detect_big_officer_buys([filing("b", D0, ("2",), 300_000, cfo=True)], CFG)
    assert cfo.details["role"] == "CFO"
    assert ceo.score > cfo.score


def test_officer_buy_below_threshold_or_other_roles_do_not_fire():
    assert detect_big_officer_buys([filing("a", D0, ("1",), 249_999, ceo=True)], CFG) == []
    assert detect_big_officer_buys([filing("b", D0, ("1",), 5_000_000)], CFG) == []  # director


def test_officer_buy_score_grows_with_size_and_stake_increase():
    small = detect_big_officer_buys([filing("a", D0, ("1",), 250_000, ceo=True)], CFG)[0]
    large = detect_big_officer_buys([filing("b", D0, ("1",), 2_500_000, ceo=True)], CFG)[0]
    doubled = detect_big_officer_buys(
        [filing("c", D0, ("1",), 250_000, ceo=True, price=10.0, shares_after=50_000)], CFG
    )[0]
    assert large.score > small.score
    assert doubled.score > small.score  # 25K shares bought on top of 25K: position doubled
    assert doubled.details["stake_increase"] == 1.0


def test_officer_buy_cooldown():
    filings = [
        filing("a", D0, ("1",), 300_000, ceo=True),
        filing("b", D0 + timedelta(days=1), ("1",), 300_000, ceo=True),
        filing("c", D0 + timedelta(days=45), ("1",), 300_000, ceo=True),
    ]
    assert [s.trigger_accession for s in detect_big_officer_buys(filings, CFG)] == ["a", "c"]


# --------------------------------------------------------------- activist_13d


def schedule(form: str = "SCHEDULE 13D", percent: float | None = 9.9, purpose: str = ""):
    return Schedule13D(
        form=form,
        issuer_name="Target Inc.",
        issuer_cik="555",
        reporters=(Reporter("Activist Fund LP", "777", 1_000_000, percent),),
        source_format="xml",
        purpose=purpose,
    )


def activist(doc, cfg=CFG):
    return detect_activist_13d(doc, accession="acc-1", filing_date=D0, cfg=cfg, ticker="TGT")


def test_new_13d_above_five_percent_fires():
    signal = activist(schedule())
    assert signal.type == ACTIVIST_13D
    assert signal.signal_date == D0
    assert signal.ticker == "TGT"
    assert signal.details["percent"] == 9.9
    assert "Activist Fund LP" in signal.explanation and "9.90%" in signal.explanation


@pytest.mark.parametrize("form", ["SCHEDULE 13D/A", "SC 13D/A"])
def test_13d_amendments_never_fire(form):
    assert activist(schedule(form=form, percent=20.0)) is None


def test_13d_below_threshold_or_without_percent_does_not_fire():
    assert activist(schedule(percent=4.99)) is None
    assert activist(schedule(percent=None)) is None
    assert activist(schedule(percent=5.0)) is not None


def test_legacy_form_name_is_also_an_original_13d():
    assert activist(schedule(form="SC 13D")) is not None


def test_13d_score_grows_with_stake_and_activist_language():
    base = activist(schedule(percent=5.0))
    bigger = activist(schedule(percent=15.0))
    vocal = activist(schedule(percent=5.0, purpose="We intend to nominate directors to the Board."))
    assert bigger.score > base.score
    assert vocal.score > base.score
    assert vocal.details["activist_tone"] is True


# ---------------------------------------------------------------- explanation


def test_explanations_are_rendered_from_details_in_both_languages():
    filings = [
        filing("a", D0, ("1",), 60_000, title="Chief Financial Officer", cfo=True),
        filing("b", D0 + timedelta(days=3), ("2",), 50_000),
    ]
    (signal,) = detect_cluster_buys(filings, CFG)
    assert explain(signal, "en") == signal.explanation
    assert explain(signal, "en") == (
        "2 distinct insiders bought $110K of Company 100 (CMP) stock on the open market "
        "(code P) between Mar 3, 2024 and Mar 6, 2024, within a 14-day window. "
        "Insider 1 (Chief Financial Officer): $60K; Insider 2 (Director/Officer): $50K."
    )
    assert explain(signal, "pt-BR") == (
        "2 insiders distintos compraram US$ 110 mil em ações de Company 100 (CMP) a mercado "
        "(código P) entre 03/03/2024 e 06/03/2024, dentro de uma janela de 14 dias. "
        "Insider 1 (Chief Financial Officer): US$ 60 mil; Insider 2 (diretor/executivo): "
        "US$ 50 mil."
    )
    assert explanations(signal) == {"en": explain(signal, "en"), "pt-BR": explain(signal, "pt-BR")}


def test_cluster_explanation_falls_back_to_the_default_window():
    filings = [filing("a", D0, ("1",), 60_000), filing("b", D0, ("2",), 50_000)]
    (signal,) = detect_cluster_buys(filings, SignalConfig(cluster_window_days=10))
    assert "10-day window" in signal.explanation
    del signal.details["window_days"]  # stored before the window was recorded
    assert "14-day window" in explain(signal, "en")


def test_officer_and_activist_explanations_in_portuguese():
    (officer,) = detect_big_officer_buys(
        [
            filing(
                "a",
                D0,
                ("1",),
                300_000,
                ceo=True,
                title="Chief Executive Officer",
                price=10.0,
                shares_after=60_000,
            )
        ],
        CFG,
    )
    assert explain(officer, "en") == (
        "Insider 1 (CEO, Chief Executive Officer) bought $300K of Company 100 (CMP) stock on "
        "the open market (code P): 30,000 shares at an average of $10.00, on Mar 3, 2024. "
        "Their stake grew 100.0%."
    )
    assert explain(officer, "pt-BR") == (
        "Insider 1 (CEO, Chief Executive Officer) comprou US$ 300 mil em ações de Company 100 "
        "(CMP) a mercado (código P): 30.000 ações a US$ 10,00 em média, em 03/03/2024. "
        "A posição dele(a) cresceu 100,0%."
    )
    doc = Schedule13D(
        form="SCHEDULE 13D",
        issuer_name="Target Inc.",
        issuer_cik="555",
        reporters=(Reporter("", "", 1_000, 7.5), Reporter("Partner LP", "", 1_000, 7.5)),
        source_format="legacy",
    )
    signal = activist(doc)
    assert signal.details["filer"] == "Unidentified filer"
    assert explain(signal, "en") == (
        "Unidentified filer filed a new 13D reporting 7.50% of Target Inc. (1,000 shares). "
        "Joint filers: Partner LP. Data extracted from an old-format (text) 13D: check the "
        "filing."
    )
    assert explain(signal, "pt-BR").startswith(
        "Declarante não identificado arquivou um 13D novo declarando 7,50% de Target Inc. "
        "(1.000 ações). Arquivam em conjunto: Partner LP."
    )


# ----------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    ("value", "en", "pt"),
    [
        (994.95, "$994.95", "US$ 994,95"),
        (91_577.22, "$92K", "US$ 92 mil"),
        (300_000_000, "$300M", "US$ 300 mi"),
        (3_550_000, "$3.55M", "US$ 3,55 mi"),
        (1_390_000_000, "$1.39B", "US$ 1,39 bi"),
        (None, "n/a", "n/d"),
    ],
)
def test_money_is_formatted_per_locale(value, en, pt):
    from radar import fmt

    assert fmt.usd(value) == en
    assert fmt.usd(value, "pt-BR") == pt


def test_numbers_percentages_and_dates_per_locale():
    from radar import fmt

    assert fmt.pct(-0.0312, signed=True) == "-3.1%" and fmt.pct(0.5) == "50.0%"
    assert fmt.pct(-0.0312, signed=True, lang="pt-BR") == "-3,1%"
    assert fmt.pct_points(9.9) == "9.90%" and fmt.pct_points(9.9, lang="pt-BR") == "9,90%"
    assert fmt.number(1234567) == "1,234,567"
    assert fmt.number(1234567, lang="pt-BR") == "1.234.567"
    assert fmt.price(11.44) == "$11.44" and fmt.price(11.44, "pt-BR") == "US$ 11,44"
    assert fmt.day(date(2026, 11, 18)) == "Nov 18, 2026"
    assert fmt.day(date(2026, 11, 18), "pt-BR") == "18/11/2026"
    assert fmt.usd(-5_000) == "-$5K"
