#!/usr/bin/env python3
"""Official OAI transport and a minimal-field parser for Physics Pulse Lite.

Python 3.11+; standard library only. This is a metadata collector, not a PDF scraper.
Initial harvest: physics set, modification date >= the beginning of the retained
window. This is NOT a submission-date query. Count only the raw v1 timestamp.
Incremental harvests: all sets, to also learn about moves out of physics.

A failed/incomplete harvest never publishes a new dashboard snapshot.
Network integration must be verified in the deployment environment.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import gzip
import io
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
OAI_URL = "https://oaipmh.arxiv.org/oai"
OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"
MAX_RESPONSE = 128 * 1024 * 1024
LOG = logging.getLogger("arxiv-pulse")


class HarvestError(RuntimeError):
    pass


class OAIError(HarvestError):
    def __init__(self, code: str, message: str):
        super().__init__(f"OAI {code}: {message}")
        self.code = code


def utc_datetime(value: str) -> datetime:
    """Accept RFC 2822 raw version dates and ISO 8601, always return UTC."""
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = parsedate_to_datetime(text)
    if dt.tzinfo is None:
        raise ValueError(f"Date has no explicit timezone: {text!r}")
    return dt.astimezone(UTC)


def stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def monday(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC)
    return (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def child_text(parent: ET.Element, name: str, default: str = "") -> str:
    for node in parent:
        if local_name(node) == name:
            return "".join(node.itertext()).strip()
    return default


def canonical_category(value: str) -> str:
    # math.MP is an alias for the mathematical-physics archive.
    return "math-ph" if value == "math.MP" else value


def clean_id(value: str) -> str:
    value = value.removeprefix("oai:arXiv.org:").removeprefix("arXiv:")
    value = re.sub(r"v\d+$", "", value.strip())
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})", value):
        raise HarvestError(f"Unexpected arXiv identifier: {value!r}")
    return value


def parse_oai(xml: bytes, title_minimum: datetime | None = None, *,
              author_minimum: datetime | None = None) -> dict[str, Any]:
    """Extract core fields; optionally keep authors from already-received records.

    Abstracts are always discarded. author_minimum enables title/author retention
    for in-window records during an ordinary sync, without additional requests.

    arXiv does not support a field projection for ListRecords. Irrelevant XML
    elements are cleared as they are parsed; raw responses are never cached.
    Passing no title_minimum means no titles, not unlimited title history.
    """
    if len(xml) > MAX_RESPONSE or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise HarvestError("Unsafe or oversized XML response.")
    records=[]; token=None; response_date=None; error=None; listing=False; first=True
    discard={"abstract","comments","journal-ref","doi","license","report-no","msc-class","acm-class"}
    if author_minimum is None:discard.add("authors")
    try:
        for event, el in ET.iterparse(io.BytesIO(xml), events=("start","end")):
            name=local_name(el)
            if first:
                if name!="OAI-PMH":raise HarvestError("The endpoint did not return OAI-PMH.")
                first=False
            if event=="start":
                if el.tag==OAI_NS+"ListRecords":listing=True
                continue
            if name in discard:
                el.clear()
                continue
            if el.tag==OAI_NS+"responseDate":response_date=el.text
            elif el.tag==OAI_NS+"error":error=(el.get("code","unknown"),el.text or "")
            elif el.tag==OAI_NS+"resumptionToken":token=(el.text or "").strip() or None
            elif el.tag==OAI_NS+"record":
                header=el.find(OAI_NS+"header")
                if header is None:raise HarvestError("Missing record header.")
                identifier=clean_id(header.findtext(OAI_NS+"identifier", ""))
                if header.get("status")=="deleted":
                    records.append({"id":identifier,"deleted":True});el.clear();continue
                metadata=el.find(OAI_NS+"metadata")
                raw=next((v for v in metadata if local_name(v)=="arXivRaw"),None) if metadata is not None else None
                if raw is None:raise HarvestError(f"{identifier}: missing arXivRaw metadata.")
                if clean_id(child_text(raw,"id",identifier))!=identifier:raise HarvestError("Identifier mismatch.")
                version=next((v for v in raw if local_name(v)=="version" and v.get("version") in ("1","v1")),None)
                if version is None:raise HarvestError(f"{identifier}: no v1 timestamp.")
                pub=utc_datetime(child_text(version,"date"))
                categories=child_text(raw,"categories").split()
                if not categories:raise HarvestError(f"{identifier}: missing primary category.")
                rec={"id":identifier,"created":int(pub.timestamp()),"category":canonical_category(categories[0])}
                if title_minimum is not None and (pub>=title_minimum or (author_minimum is not None and pub>=author_minimum)):
                    title=" ".join(child_text(raw,"title").split())
                    if not title:raise HarvestError(f"{identifier}: missing recent title.")
                    rec["title"]=title
                if author_minimum is not None and pub>=author_minimum:
                    rec["authors"]=" ".join(child_text(raw,"authors").split()) or None
                records.append(rec);el.clear()
    except ET.ParseError as exc:
        raise HarvestError("Invalid OAI XML.") from exc
    if not response_date:raise HarvestError("Missing responseDate.")
    utc_datetime(response_date)
    if error:
        if error[0]=="noRecordsMatch":return {"records":[],"token":None,"responseDate":response_date}
        raise OAIError(*error)
    if not listing:raise HarvestError("Missing ListRecords.")
    return {"records":records,"token":token,"responseDate":response_date}


class SerialHTTP:
    """One connection at a time and >=3.1 seconds between arXiv requests."""

    def __init__(self, user_agent: str, minimum_interval: float = 3.1):
        self.user_agent = user_agent
        self.minimum_interval = max(3.1, minimum_interval)
        self.last_request = 0.0

    def request(
        self, url: str, data: bytes | None = None,
        headers: dict[str, str] | None = None, attempts: int = 6
    ) -> bytes:
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip", **(headers or {})}
        for attempt in range(attempts):
            wait = self.minimum_interval - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    body = response.read(MAX_RESPONSE + 1)
                    if len(body) > MAX_RESPONSE:
                        raise HarvestError("Response exceeds the size limit.")
                    if response.headers.get("Content-Encoding", "").lower()=="gzip":
                        try:
                            with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz:
                                body=gz.read(MAX_RESPONSE+1)
                        except (OSError,EOFError) as exc:
                            raise HarvestError("Invalid gzip response.") from exc
                        if len(body)>MAX_RESPONSE:raise HarvestError("Decompressed response exceeds limit.")
                    return body
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                    raise HarvestError(f"HTTP {exc.code} from {url.split('?')[0]}") from exc
                raw_wait = exc.headers.get("Retry-After", "")
                try:
                    delay = float(raw_wait)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(raw_wait) - datetime.now(UTC)).total_seconds()
                    except (TypeError, ValueError):
                        delay = 5 * (2 ** attempt)
                # Never reduce a server-provided Retry-After.
                delay = max(self.minimum_interval, delay)
                if delay > 1800:
                    raise HarvestError("Server requested a long pause; try again later.") from exc
                LOG.warning("HTTP %s; pausing %.1f seconds.", exc.code, delay)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == attempts - 1:
                    raise HarvestError(f"Network failure: {exc}") from exc
                time.sleep(5 * (2 ** attempt))
        raise HarvestError("Request retries exhausted.")

