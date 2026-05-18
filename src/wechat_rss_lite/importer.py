from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class ImportEntry:
    id: str
    title: str


def parse_subscription_import(
    *,
    text: str = "",
    filename: str = "",
    content: bytes | None = None,
) -> list[ImportEntry]:
    suffix = Path(filename).suffix.lower()
    if content and suffix == ".xlsx":
        return _dedupe(_parse_xlsx(content))
    if content:
        text = _decode_text(content)
    if suffix == ".csv":
        return _dedupe(_parse_csv(text))
    return _dedupe(_parse_plain_text(text))


def _parse_plain_text(text: str) -> list[ImportEntry]:
    entries: list[ImportEntry] = []
    for token in re.split(r"[\s,，;；]+", text):
        value = token.strip()
        if value:
            entries.append(ImportEntry(id=value, title=value))
    return entries


def _parse_csv(text: str) -> list[ImportEntry]:
    entries: list[ImportEntry] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        values = [cell.strip() for cell in row if cell.strip()]
        if not values or _looks_like_header(values):
            continue
        if len(values) == 1:
            entries.append(ImportEntry(id=values[0], title=values[0]))
        else:
            entries.append(ImportEntry(id=values[0], title=values[1]))
    return entries


def _parse_xlsx(content: bytes) -> list[ImportEntry]:
    entries: list[ImportEntry] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_name = _first_sheet_name(archive)
        root = ElementTree.fromstring(archive.read(sheet_name))
    for row in root.findall(".//{*}sheetData/{*}row"):
        values = [_cell_text(cell, shared_strings).strip() for cell in row.findall("{*}c")]
        values = [value for value in values if value]
        if not values or _looks_like_header(values):
            continue
        if len(values) == 1:
            entries.append(ImportEntry(id=values[0], title=values[0]))
        else:
            entries.append(ImportEntry(id=values[0], title=values[1]))
    return entries


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings: list[str] = []
    for item in root.findall("{*}si"):
        parts = [node.text or "" for node in item.findall(".//{*}t")]
        strings.append("".join(parts))
    return strings


def _first_sheet_name(archive: zipfile.ZipFile) -> str:
    candidates = sorted(
        name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
    )
    if not candidates:
        raise ValueError("No worksheet found in xlsx file")
    return candidates[0]


def _cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    value_node = cell.find("{*}v")
    inline_node = cell.find("{*}is/{*}t")
    if inline_node is not None:
        return inline_node.text or ""
    if value_node is None or value_node.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        index = int(value_node.text)
        return shared_strings[index] if index < len(shared_strings) else ""
    return value_node.text


def _looks_like_header(values: list[str]) -> bool:
    normalized = {value.strip().lower().replace(" ", "_") for value in values[:2]}
    headers = {"id", "account_id", "fakeid", "title", "name", "公众号", "公众号名称", "订阅_id", "订阅id"}
    return bool(normalized & headers)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    return content.decode("utf-8", errors="ignore")


def _dedupe(entries: list[ImportEntry]) -> list[ImportEntry]:
    seen: set[str] = set()
    result: list[ImportEntry] = []
    for entry in entries:
        if entry.id in seen:
            continue
        seen.add(entry.id)
        result.append(entry)
    return result

