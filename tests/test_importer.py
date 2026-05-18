from __future__ import annotations

import io
import zipfile

from wechat_rss_lite.importer import parse_subscription_import


def test_parse_plain_text_with_common_delimiters() -> None:
    entries = parse_subscription_import(text="alpha, beta\n gamma，delta epsilon")

    assert [entry.id for entry in entries] == ["alpha", "beta", "gamma", "delta", "epsilon"]


def test_parse_csv_with_id_and_title_columns() -> None:
    entries = parse_subscription_import(
        text="id,title\nacct-1,Account One\nacct-2,Account Two\n",
        filename="accounts.csv",
    )

    assert [(entry.id, entry.title) for entry in entries] == [
        ("acct-1", "Account One"),
        ("acct-2", "Account Two"),
    ]


def test_parse_xlsx_with_inline_strings() -> None:
    buffer = io.BytesIO()
    sheet = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row><c t="inlineStr"><is><t>id</t></is></c><c t="inlineStr"><is><t>title</t></is></c></row>
        <row><c t="inlineStr"><is><t>acct-1</t></is></c><c t="inlineStr"><is><t>Account One</t></is></c></row>
      </sheetData>
    </worksheet>
    """
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

    entries = parse_subscription_import(filename="accounts.xlsx", content=buffer.getvalue())

    assert [(entry.id, entry.title) for entry in entries] == [("acct-1", "Account One")]
