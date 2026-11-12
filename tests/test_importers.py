from datetime import date
from pathlib import Path

from app.importers import csv_banks
from app.importers.base import dedup_keys

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


def read(name):
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_sparkasse_parses_german_numbers_and_dates():
    txs = csv_banks.SparkasseCSV().parse(read("sparkasse_sample.csv"))
    assert len(txs) == 10
    assert txs[0].booked_on == date(2026, 9, 26)
    assert txs[0].amount == 3450.00
    assert txs[1].amount == -1150.00


def test_ing_skips_metadata_block():
    txs = csv_banks.IngCSV().parse(read("ing_sample.csv"))
    assert [t.amount for t in txs] == [-300.00, -300.00, 212.40]
    assert txs[0].counterparty == "Sparplan Depot"


def test_bos_combines_debit_and_credit():
    txs = csv_banks.BankOfScotlandCSV().parse(read("bos_sample.csv"))
    assert [t.amount for t in txs] == [-95.00, 12.45, -41.87]


def test_detection():
    assert csv_banks.detect(read("sparkasse_sample.csv")).bank == "sparkasse"
    assert csv_banks.detect(read("ing_sample.csv")).bank == "ing"
    assert csv_banks.detect(read("bos_sample.csv")).bank == "bos"
    assert csv_banks.detect("a,b,c\n1,2,3") is None


def test_identical_rows_in_one_file_get_distinct_keys():
    txs = csv_banks.SparkasseCSV().parse(read("sparkasse_sample.csv"))
    keys = dedup_keys(1, txs)
    assert len(set(keys)) == len(keys)  # the two identical 102,30 shops stay separate
    assert keys == dedup_keys(1, txs)   # and keys are stable across runs


def test_sparkasse_reads_counterparty_iban():
    txs = csv_banks.SparkasseCSV().parse(read("sparkasse_sample.csv"))
    assert txs[0].counterparty_iban == "DE11111111111111111111"     # salary row
    assert txs[3].counterparty_iban == ""                           # card payment: Kontonummer empty


def test_sparkasse_old_style_account_number_is_not_an_iban():
    text = read("sparkasse_sample.csv").replace('"DE11111111111111111111"', '"1234567"', 1)
    assert csv_banks.SparkasseCSV().parse(text)[0].counterparty_iban == ""
