"""Form 3/4/5 history: the SEC's quarterly "Insider Transactions Data Sets".

Each zip holds TSV tables. We use three: SUBMISSION (one filing per row, with
the filing date), REPORTINGOWNER (who filed and their position) and
NONDERIV_TRANS (the Table I transactions). DuckDB reads the TSVs straight from disk.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from radar.edgar import normalize_cik
from radar.http import SecClient, SecHttpError
from radar.models import Purchase, PurchaseFiling
from radar.roles import classify_title

log = logging.getLogger(__name__)

DATASETS_PAGE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
# The SEC has moved the files before; the page is the source of truth and these are fallbacks.
FALLBACK_URLS = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{name}",
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{name}",
)
TABLES = ("SUBMISSION", "REPORTINGOWNER", "NONDERIV_TRANS")
_LINK = re.compile(r'href="([^"]*?/(\d{4})q([1-4])_form345\.zip)"', re.I)

# Securities that are not the common stock traded under the issuer's ticker.
_NOT_COMMON = re.compile(
    r"preferred|\bpfd\b|warrant|\bnotes?\b|\bbonds?\b|debenture|convertible|\brights?\b|\boptions?\b",
    re.I,
)

Quarter = tuple[int, int]


@dataclass(frozen=True)
class LoadStats:
    quarters: int
    form4_filings: int
    purchase_rows: int
    purchase_filings: int
    excluded_non_common: int
    excluded_bad_dates: int


def quarter_of(day: date) -> Quarter:
    return day.year, (day.month - 1) // 3 + 1


def quarters_between(start: date, end: date) -> list[Quarter]:
    quarters: list[Quarter] = []
    year, quarter = quarter_of(start)
    last = quarter_of(end)
    while (year, quarter) <= last:
        quarters.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return quarters


def parse_dataset_links(html: str) -> dict[Quarter, str]:
    links: dict[Quarter, str] = {}
    for href, year, quarter in _LINK.findall(html):
        url = href if href.startswith("http") else f"https://www.sec.gov{href}"
        links.setdefault((int(year), int(quarter)), url)
    return links


def dataset_links(client: SecClient) -> dict[Quarter, str]:
    """Finds the actual URL of each zip on the SEC page (cached for one day)."""
    try:
        return parse_dataset_links(client.get_text(DATASETS_PAGE, max_age=86_400))
    except SecHttpError as exc:
        log.warning("could not read the datasets page (%s); using default URLs", exc)
        return {}


def ensure_quarter(client: SecClient, quarter: Quarter, links: dict[Quarter, str]) -> Path:
    """Makes sure the quarter's TSVs are extracted in the cache and returns the folder."""
    year, q = quarter
    name = f"{year}q{q}_form345.zip"
    target = client.cache_dir / "insider-datasets" / f"{year}q{q}"
    if all((target / f"{table}.tsv").exists() for table in TABLES):
        return target

    candidates = [links[quarter]] if quarter in links else []
    candidates += [template.format(name=name) for template in FALLBACK_URLS]
    archive: Path | None = None
    last_error: Exception | None = None
    for url in dict.fromkeys(candidates):
        try:
            archive = client.download(url)
            break
        except SecHttpError as exc:
            last_error = exc
    if archive is None:
        raise RuntimeError(f"dataset {name} unavailable from the SEC: {last_error}")

    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        members = {Path(info.filename).name.upper(): info for info in bundle.infolist()}
        for table in TABLES:
            info = members.get(f"{table}.TSV")
            if info is None:
                raise RuntimeError(f"{name} does not contain {table}.tsv")
            # Write under a name we choose, never using paths from inside the zip.
            partial = target / f"{table}.tsv.tmp"
            with bundle.open(info) as source, partial.open("wb") as sink:
                while chunk := source.read(1 << 20):
                    sink.write(chunk)
            partial.replace(target / f"{table}.tsv")
    return target


def _read(table: str, folders: list[Path]) -> str:
    files = ", ".join(f"'{folder / (table + '.tsv')}'" for folder in folders)
    return (
        f"read_csv([{files}], delim='\\t', header=true, all_varchar=true, quote='', "
        "escape='', strict_mode=false, null_padding=true, union_by_name=true)"
    )


def load_purchase_filings(
    folders: list[Path], *, first_day: date, last_day: date
) -> tuple[list[PurchaseFiling], LoadStats]:
    """Reads the P purchases from original Form 4s filed between `first_day` and `last_day`.

    Amendments (4/A) are left out: they repeat transactions already reported and
    would make the same purchase count twice.
    """
    con = duckdb.connect()
    for table in TABLES:
        con.execute(f"CREATE VIEW {table.lower()} AS SELECT * FROM {_read(table, folders)}")

    con.execute(
        """
        CREATE TABLE filings AS
        SELECT ACCESSION_NUMBER AS accession,
               CAST(try_strptime(FILING_DATE, '%d-%b-%Y') AS DATE) AS filing_date,
               ISSUERCIK AS issuer_cik,
               coalesce(ISSUERNAME, '') AS issuer_name,
               coalesce(ISSUERTRADINGSYMBOL, '') AS symbol,
               coalesce(REMARKS, '') AS remarks
        FROM submission
        WHERE DOCUMENT_TYPE = '4'
        QUALIFY row_number() OVER (PARTITION BY ACCESSION_NUMBER ORDER BY FILING_DATE) = 1
        """
    )
    con.execute(
        """
        CREATE TABLE purchases AS
        SELECT f.accession,
               CAST(try_strptime(n.TRANS_DATE, '%d-%b-%Y') AS DATE) AS trans_date,
               try_cast(n.TRANS_SHARES AS DOUBLE) AS shares,
               try_cast(n.TRANS_PRICEPERSHARE AS DOUBLE) AS price,
               try_cast(n.SHRS_OWND_FOLWNG_TRANS AS DOUBLE) AS shares_after,
               coalesce(n.SECURITY_TITLE, '') AS security_title
        FROM nonderiv_trans n
        JOIN filings f ON f.accession = n.ACCESSION_NUMBER
        WHERE n.TRANS_CODE = 'P'
          AND coalesce(n.TRANS_ACQUIRED_DISP_CD, 'A') <> 'D'
          AND f.filing_date BETWEEN ? AND ?
        """,
        [first_day, last_day],
    )
    form4_filings = con.execute(
        "SELECT count(*) FROM filings WHERE filing_date BETWEEN ? AND ?", [first_day, last_day]
    ).fetchone()[0]

    tx = con.execute(
        """
        SELECT p.*, f.filing_date, f.issuer_cik, f.issuer_name, f.symbol, f.remarks
        FROM purchases p JOIN filings f USING (accession)
        WHERE p.shares > 0 AND p.price > 0
        ORDER BY f.filing_date, p.accession, p.trans_date
        """
    ).df()
    owners = con.execute(
        """
        SELECT o.ACCESSION_NUMBER AS accession, o.RPTOWNERCIK AS owner_cik,
               coalesce(o.RPTOWNERNAME, '') AS owner_name,
               coalesce(o.RPTOWNER_RELATIONSHIP, '') AS relationship,
               coalesce(o.RPTOWNER_TITLE, '') AS title
        FROM reportingowner o
        WHERE o.ACCESSION_NUMBER IN (SELECT DISTINCT accession FROM purchases)
        """
    ).df()
    con.close()

    purchase_rows = len(tx)
    non_common = tx["security_title"].str.contains(_NOT_COMMON, na=False)
    excluded_non_common = int(non_common.sum())
    tx = tx[~non_common]
    # A purchase dated after its own filing, or with no date, is a filing error.
    bad_dates = tx["trans_date"].isna() | (tx["trans_date"] > tx["filing_date"])
    excluded_bad_dates = int(bad_dates.sum())
    tx = tx[~bad_dates]

    owners_by_filing = {acc: group for acc, group in owners.groupby("accession", sort=False)}
    filings: list[PurchaseFiling] = []
    for accession, group in tx.groupby("accession", sort=False):
        first = group.iloc[0]
        owner_rows = owners_by_filing.get(accession)
        is_ceo = is_cfo = is_od = False
        title = ""
        ciks: set[str] = set()
        names: list[str] = []
        if owner_rows is not None:
            for row in owner_rows.itertuples(index=False):
                ciks.add(normalize_cik(row.owner_cik))
                names.append(row.owner_name)
                relationship = row.relationship.lower()
                is_od |= "director" in relationship or "officer" in relationship
                if "officer" in relationship:
                    ceo, cfo = classify_title(row.title, first.remarks)
                    is_ceo |= ceo
                    is_cfo |= cfo
                    title = title or row.title
        after = group["shares_after"].dropna()
        filings.append(
            PurchaseFiling(
                accession=accession,
                issuer_cik=normalize_cik(first.issuer_cik),
                issuer_name=first.issuer_name,
                ticker=first.symbol,
                filing_date=_as_date(first.filing_date),
                owner_ciks=frozenset(ciks) or frozenset({f"filing:{accession}"}),
                owner_names=tuple(names),
                is_ceo=is_ceo,
                is_cfo=is_cfo,
                is_officer_or_director=is_od,
                officer_title=title,
                purchases=tuple(
                    Purchase(
                        _as_date(r.trans_date),
                        float(r.shares),
                        float(r.price),
                        None if pd.isna(r.shares_after) else float(r.shares_after),
                    )
                    for r in group.itertuples(index=False)
                ),
                shares_after=float(after.max()) if len(after) else None,
            )
        )

    stats = LoadStats(
        quarters=len(folders),
        form4_filings=int(form4_filings),
        purchase_rows=purchase_rows,
        purchase_filings=len(filings),
        excluded_non_common=excluded_non_common,
        excluded_bad_dates=excluded_bad_dates,
    )
    return filings, stats


def _as_date(value: object) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def warmup_start(start: date, days: int) -> date:
    """First day of data needed for the window of the earliest possible signal."""
    return start - timedelta(days=days)


# ------------------------------------------------------------------- tickers

_EXCHANGES = re.compile(
    r"\b(NYSE\s*AMERICAN|NYSE\s*ARCA|NYSE\s*MKT|NYSE|NASDAQ\s*(GS|GM|CM)?|NASD|AMEX|"
    r"OTC\s*MARKETS|OTC\s*PINK|OTCQB|OTCQX|OTCBB|OTC|TSXV|TSX|CBOE|BATS)\b"
)
_INVALID = frozenset({"", "NONE", "NA", "NULL", "NIL", "TBD", "PRIVATE", "NOTAPPLICABLE"})
_TICKER = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")


def normalize_symbol(raw: str | None) -> str:
    """Cleans up the ticker typed on the Form 4 ("NYSE: KRC", "(SIRI)", "HEI, HEI.A", "N/A").

    Returns the ticker in Yahoo's format (share class separated by a hyphen), or ""
    if there is no recognizable ticker.
    """
    text = (raw or "").upper().strip()
    if text.replace("/", "").replace(".", "").replace(" ", "") in _INVALID:
        return ""
    text = _EXCHANGES.sub(" ", text)
    text = re.sub(r"[\"'()\[\]{}]", " ", text)
    tokens = [t.strip(".-") for t in re.split(r"[\s,;:/&|]+|\bAND\b", text) if t.strip(".-")]
    if len(tokens) > 1 and all(len(t) == 1 and t.isalpha() for t in tokens):
        tokens = ["".join(tokens)]  # "N O G" → "NOG"
    for token in tokens:
        if token not in _INVALID and _TICKER.match(token):
            return token.replace(".", "-")
    return ""
