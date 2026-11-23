"""Tamper-evident audit chain (K1 `audit_event`, `audit_checkpoint`): synchronous writer, signed checkpoints
with an anchors volume, and the verifier.

Record hash: `hash = sha256(RFC 8785 of the header)`, where the header holds stream, seq, event_key,
occurred_at, actor, kind, subject, `payload_hash = sha256(RFC 8785 of payload)` and `prev_hash` (the same
scheme as WP-08's async writer `sgw.api.audit_log`, which shares the lock and genesis constants).

A checkpoint signs `{v, stream, seq, head_hash, key_id, anchored_at}` with the in-process Ed25519 key. Its
anchor file (written once, outside the database) repeats the signed head and adds the segment of row hashes
since the previous checkpoint under a second signature. The verifier walks the chain from seq 1 and reports
the first bad sequence: a gap, a broken link, a payload or record hash that does not recompute, or a row
whose hash differs from the notarised segment (which pinpoints a rewrite even when every later hash was
recomputed). Rows after the newest checkpoint are only as safe as the chain itself, so checkpoints run
after every high-value event and on a timer.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.api.audit_log import AUDIT_LOCK_KEY, GENESIS_HASH, record_hash
from sgw.approval.signer import Ed25519Signer, Keyring, verify_signature
from sgw.contracts.api_models import AuditEventOut, AuditVerifyResult
from sgw.contracts.approval import canonical_json, sha256_hex
from sgw.contracts.base import utc_iso

log = logging.getLogger("sgw.approval.audit")
ActorType = Literal["user", "system", "agent"]
STREAM = "global"
CHECKPOINT_VERSION = 1
BATCH = 2000
STREAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RETIRED = ".retired"
INSTANCE_FILE = ".instance"
ROW_COLUMNS = (
    "stream, seq, event_key, occurred_at, actor_type, actor_id, kind, subject, payload_hash, payload,"
    " prev_hash, hash"
)


class AuditError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def header_of(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "stream": row["stream"],
        "seq": row["seq"],
        "event_key": row["event_key"],
        "occurred_at": utc_iso(_utc(row["occurred_at"])),
        "actor_type": row["actor_type"],
        "actor_id": row["actor_id"],
        "kind": row["kind"],
        "subject": row["subject"],
        "payload_hash": row["payload_hash"],
        "prev_hash": row["prev_hash"],
    }


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    hash: str
    event_key: str


def append(
    conn: psycopg.Connection[Any],
    *,
    kind: str,
    actor_type: ActorType,
    actor_id: str,
    subject: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    stream: str = STREAM,
    event_key: str | None = None,
) -> AuditRecord:
    """Append one record in the caller's transaction; the advisory lock keeps `seq` gapless and linear."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
    last = conn.execute(
        "SELECT seq, hash FROM audit_event WHERE stream = %s ORDER BY seq DESC LIMIT 1", (stream,)
    ).fetchone()
    seq, prev_hash = (int(last[0]) + 1, str(last[1])) if last else (1, GENESIS_HASH)
    key = event_key or f"{kind}:{uuid.uuid4()}"
    row = {
        "stream": stream,
        "seq": seq,
        "event_key": key,
        "occurred_at": occurred_at,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "kind": kind,
        "subject": subject,
        "payload_hash": sha256_hex(canonical_json(payload)),
        "prev_hash": prev_hash,
    }
    digest = record_hash(header_of(row))
    conn.execute(
        f"INSERT INTO audit_event ({ROW_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",  # noqa: S608
        (
            stream,
            seq,
            key,
            occurred_at,
            actor_type,
            actor_id,
            kind,
            subject,
            row["payload_hash"],
            Jsonb(payload),
            prev_hash,
            digest,
        ),
    )
    return AuditRecord(seq=seq, hash=digest, event_key=key)


def list_events(
    conn: psycopg.Connection[Any],
    *,
    from_seq: int = 1,
    limit: int = 500,
    stream: str = STREAM,
    subject: str | None = None,
) -> list[AuditEventOut]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT stream, seq, occurred_at, actor_type, actor_id, kind, subject, payload_hash, prev_hash,"
            " hash, payload->>'decision' AS decision, payload->>'reason' AS reason FROM audit_event"
            " WHERE stream = %s AND seq >= %s AND (%s::text IS NULL OR subject = %s)"
            " ORDER BY seq LIMIT %s",
            (stream, from_seq, subject, subject, limit),
        ).fetchall()
    return [AuditEventOut.model_validate(r) for r in rows]


# ---- checkpoints and anchors ---------------------------------------------------------------------------


def checkpoint_message(*, stream: str, seq: int, head_hash: str, key_id: str, anchored_at: datetime) -> bytes:
    return canonical_json(
        {
            "v": CHECKPOINT_VERSION,
            "stream": stream,
            "seq": seq,
            "head_hash": head_hash,
            "key_id": key_id,
            "anchored_at": utc_iso(_utc(anchored_at)),
        }
    )


def segment_message(*, stream: str, from_seq: int, to_seq: int, hashes: list[str], key_id: str) -> bytes:
    return canonical_json(
        {
            "v": CHECKPOINT_VERSION,
            "kind": "segment",
            "stream": stream,
            "from_seq": from_seq,
            "to_seq": to_seq,
            "hashes": hashes,
            "key_id": key_id,
        }
    )


class AnchorStore:
    """Write-once JSON files `<root>/<database>/<stream>/<seq:012d>.json` on the anchors volume; the database
    name keeps chains of different databases (main, scratch, tests) apart on one volume."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, namespace: str, stream: str) -> Path:
        for part in (namespace, stream):
            if not STREAM_RE.match(part):
                raise AuditError(f"invalid anchor path part {part!r}")
        return self.root / namespace / stream

    def path(self, namespace: str, stream: str, seq: int) -> Path:
        return self._dir(namespace, stream) / f"{seq:012d}.json"

    def write(self, namespace: str, doc: dict[str, Any]) -> Path:
        """Write once and atomically: a temp file is linked into place, so a crash never leaves a partial
        anchor and an existing anchor is never replaced (FileExistsError)."""
        path = self.path(namespace, str(doc["stream"]), int(doc["seq"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(doc, handle, indent=1, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return path

    def retire(self, namespace: str, at: datetime | None = None) -> Path | None:
        """Move the anchors of a database that was dropped and recreated (a new chain starts at seq 1) to
        `<root>/.retired/<namespace>-<UTC stamp>`; never deletes. Without this the new chain fails verify
        against the old signed heads. None when the database has no anchors."""
        if not STREAM_RE.match(namespace):
            raise AuditError(f"invalid anchor path part {namespace!r}")
        folder = self.root / namespace
        if not folder.is_dir():
            return None
        stamp = _utc(at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.root / RETIRED / f"{namespace}-{stamp}"
        target.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(target)
        return target

    def instance(self, namespace: str) -> str | None:
        """The database instance (`pg_database.oid`) the anchors of `namespace` were written for; None for
        anchors written before instances were recorded."""
        try:
            return (self.root / namespace / INSTANCE_FILE).read_text(encoding="utf-8").strip() or None
        except (FileNotFoundError, NotADirectoryError):
            return None

    def adopt(self, namespace: str, instance: str) -> Path | None:
        """Before writing anchors for a database instance: anchors of an earlier instance under the same name
        (the database was replaced, e.g. a demo moment loaded by an API that cannot retire anchors) are
        retired first. Returns the retired folder, if any."""
        if not STREAM_RE.match(namespace):
            raise AuditError(f"invalid anchor path part {namespace!r}")
        known = self.instance(namespace)
        if known == instance:
            return None
        retired = self.retire(namespace) if known is not None else None
        folder = self.root / namespace
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{INSTANCE_FILE}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(instance + "\n", encoding="utf-8")
        os.replace(tmp, folder / INSTANCE_FILE)
        return retired

    def namespaces(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and STREAM_RE.match(p.name))

    def load(self, namespace: str, stream: str) -> list[dict[str, Any]]:
        folder = self._dir(namespace, stream)
        if not folder.is_dir():
            return []
        docs: list[dict[str, Any]] = []
        for path in sorted(folder.glob("*.json")):
            try:
                docs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                docs.append({"stream": stream, "seq": _seq_from_name(path), "corrupt": True})
        return docs


def _seq_from_name(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError:
        return 0


@dataclass(frozen=True)
class Checkpoint:
    stream: str
    seq: int
    from_seq: int
    head_hash: str
    key_id: str
    signature: str
    anchored_at: datetime
    anchor_path: Path | None


def _anchor_doc(
    conn: psycopg.Connection[Any], signer: Ed25519Signer, stream: str, seq: int
) -> dict[str, Any] | None:
    """The anchor of the committed checkpoint at `seq`, rebuilt from the database (segment = rows since the
    previous checkpoint). None when the checkpoint was signed by another key (cannot co-sign its segment)."""
    row = conn.execute(
        "SELECT head_hash, signature, key_id, anchored_at FROM audit_checkpoint"
        " WHERE stream = %s AND seq = %s",
        (stream, seq),
    ).fetchone()
    if row is None or row[2] != signer.key_id:
        return None
    prev = conn.execute(
        "SELECT max(seq) FROM audit_checkpoint WHERE stream = %s AND seq < %s", (stream, seq)
    ).fetchone()
    from_seq = (int(prev[0]) if prev and prev[0] is not None else 0) + 1
    hashes = [
        str(r[0])
        for r in conn.execute(
            "SELECT hash FROM audit_event WHERE stream = %s AND seq BETWEEN %s AND %s ORDER BY seq",
            (stream, from_seq, seq),
        ).fetchall()
    ]
    return {
        "v": CHECKPOINT_VERSION,
        "stream": stream,
        "seq": seq,
        "head_hash": str(row[0]),
        "key_id": signer.key_id,
        "anchored_at": utc_iso(_utc(row[3])),
        "signature": str(row[1]),
        "segment": {"from_seq": from_seq, "to_seq": seq, "hashes": hashes},
        "segment_signature": signer.sign(
            segment_message(stream=stream, from_seq=from_seq, to_seq=seq, hashes=hashes, key_id=signer.key_id)
        ),
    }


def database_instance(conn: psycopg.Connection[Any]) -> str:
    """The physical database behind the connection: a replaced database (drop and recreate, a demo moment
    copied over it) keeps its name but gets a new oid."""
    row = conn.execute("SELECT oid::text FROM pg_database WHERE datname = current_database()").fetchone()
    return str(row[0]) if row else ""


def _current_anchors(
    conn: psycopg.Connection[Any], anchors: AnchorStore | None, stream: str
) -> list[dict[str, Any]]:
    """The anchors of this database instance. Anchors left by a replaced database under the same name belong
    to another chain: they are not evidence about this one (the writer retires them on its next run)."""
    if anchors is None:
        return []
    namespace = conn.info.dbname
    known = anchors.instance(namespace)
    if known is not None and known != database_instance(conn):
        return []
    return anchors.load(namespace, stream)


def write_missing_anchors(
    conn: psycopg.Connection[Any], signer: Ed25519Signer, anchors: AnchorStore, *, stream: str = STREAM
) -> list[Path]:
    """Anchor every committed checkpoint of this key that has no anchor file yet (a previous write failed).
    Failures are logged and retried by the next run; a missing anchor is never reported as tampering."""
    written: list[Path] = []
    rows = conn.execute(
        "SELECT seq FROM audit_checkpoint WHERE stream = %s AND key_id = %s ORDER BY seq",
        (stream, signer.key_id),
    ).fetchall()
    namespace = conn.info.dbname
    try:
        if anchors.adopt(namespace, database_instance(conn)) is not None:
            log.warning("audit anchors of a replaced %s database retired before anchoring", namespace)
    except OSError:
        log.warning("anchor folder of %s could not be prepared; the next checkpoint run retries", namespace)
        return written
    for (seq,) in rows:
        if anchors.path(namespace, stream, int(seq)).exists():
            continue
        doc = _anchor_doc(conn, signer, stream, int(seq))
        if doc is None:
            continue
        try:
            written.append(anchors.write(namespace, doc))
        except FileExistsError:
            continue
        except OSError:
            log.warning(
                "anchor write for %s seq %s failed; the next checkpoint run retries",
                stream,
                seq,
                exc_info=True,
            )
            break
    return written


def checkpoint(
    conn: psycopg.Connection[Any],
    signer: Ed25519Signer,
    anchors: AnchorStore | None,
    *,
    stream: str = STREAM,
    at: datetime | None = None,
) -> Checkpoint | None:
    """Sign the current head if it moved since the last checkpoint and commit the checkpoint row; only then
    write the anchor file (and any earlier anchor whose write failed). Returns None when nothing is new."""
    anchored_at = _utc(at or datetime.now(UTC))
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
        head = conn.execute(
            "SELECT seq, hash FROM audit_event WHERE stream = %s ORDER BY seq DESC LIMIT 1", (stream,)
        ).fetchone()
        last = conn.execute("SELECT max(seq) FROM audit_checkpoint WHERE stream = %s", (stream,)).fetchone()
        last_seq = int(last[0]) if last and last[0] is not None else 0
        if head is None or last_seq >= int(head[0]):
            created = None
        else:
            seq, head_hash = int(head[0]), str(head[1])
            signature = signer.sign(
                checkpoint_message(
                    stream=stream, seq=seq, head_hash=head_hash, key_id=signer.key_id, anchored_at=anchored_at
                )
            )
            conn.execute(
                "INSERT INTO audit_checkpoint (stream, seq, head_hash, signature, key_id, anchored_at)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (stream, seq, head_hash, signature, signer.key_id, anchored_at),
            )
            created = (seq, last_seq + 1, head_hash, signature)
    written = write_missing_anchors(conn, signer, anchors, stream=stream) if anchors is not None else []
    if created is None:
        return None
    seq, from_seq, head_hash, signature = created
    path = next((p for p in written if p.name == f"{seq:012d}.json"), None)
    return Checkpoint(stream, seq, from_seq, head_hash, signer.key_id, signature, anchored_at, path)


# ---- verifier ------------------------------------------------------------------------------------------


@dataclass
class VerifyReport:
    ok: bool
    checked_to_seq: int
    first_bad_seq: int | None
    signed_head_seq: int | None
    problems: list[str] = field(default_factory=list)

    @property
    def notary(self) -> Literal["signed", "UNSIGNED"]:
        return "signed" if self.signed_head_seq is not None else "UNSIGNED"

    def result(self) -> AuditVerifyResult:
        return AuditVerifyResult(
            ok=self.ok,
            checked_to_seq=self.checked_to_seq,
            first_bad_seq=self.first_bad_seq,
            signed_head_seq=self.signed_head_seq,
            notary=self.notary,
        )


@dataclass(frozen=True)
class _Head:
    seq: int
    head_hash: str
    source: str
    key_id: str


Head = _Head


def _rows(conn: psycopg.Connection[Any], stream: str) -> Iterator[dict[str, Any]]:
    after = 0
    while True:
        with conn.cursor(row_factory=dict_row) as cur:
            batch = cur.execute(
                f"SELECT {ROW_COLUMNS} FROM audit_event WHERE stream = %s AND seq > %s ORDER BY seq LIMIT %s",  # noqa: S608
                (stream, after, BATCH),
            ).fetchall()
        if not batch:
            return
        yield from batch
        after = int(batch[-1]["seq"])


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _signed_by_trusted_key(
    keyring: Keyring, key_id: str, at: datetime | None, message: bytes, sig: str
) -> bool:
    key = keyring.get(key_id)
    if key is None or at is None or not key.valid_at(at):
        return False
    return verify_signature(key.public_key, message, sig)


def _trusted_heads(
    conn: psycopg.Connection[Any],
    stream: str,
    keyring: Keyring,
    anchors: AnchorStore | None,
    problems: list[str],
) -> tuple[dict[int, _Head], dict[int, str]]:
    """Checkpoints whose signatures verify against the keyring, and the notarised row hashes from anchors."""
    heads: dict[int, _Head] = {}
    db_rows = conn.execute(
        "SELECT seq, head_hash, signature, key_id, anchored_at FROM audit_checkpoint WHERE stream = %s"
        " ORDER BY seq",
        (stream,),
    ).fetchall()
    db_seqs = set()
    for seq, head_hash, signature, key_id, anchored_at in db_rows:
        db_seqs.add(int(seq))
        at = _utc(anchored_at)
        message = checkpoint_message(
            stream=stream, seq=int(seq), head_hash=head_hash, key_id=key_id, anchored_at=at
        )
        if _signed_by_trusted_key(keyring, key_id, at, message, signature):
            heads[int(seq)] = _Head(int(seq), str(head_hash), "db", str(key_id))
        else:
            problems.append(f"checkpoint {seq}: signature does not verify against the trusted keyring")
    segments: dict[int, tuple[str, int]] = {}
    for doc in _current_anchors(conn, anchors, stream):
        seq = int(doc.get("seq", 0))
        if doc.get("corrupt"):
            problems.append(f"anchor {seq}: unreadable")
            continue
        anchored = _parse_time(doc.get("anchored_at"))
        key_id = str(doc.get("key_id", ""))
        message = (
            checkpoint_message(
                stream=stream,
                seq=seq,
                head_hash=str(doc.get("head_hash", "")),
                key_id=key_id,
                anchored_at=anchored,
            )
            if anchored is not None
            else b""
        )
        if not _signed_by_trusted_key(keyring, key_id, anchored, message, str(doc.get("signature", ""))):
            problems.append(f"anchor {seq}: signature does not verify against the trusted keyring")
            continue
        known = heads.get(seq)
        if known is not None and known.head_hash != doc["head_hash"]:
            problems.append(f"checkpoint {seq}: database head differs from the anchored head")
        if seq not in db_seqs:
            problems.append(f"checkpoint {seq}: anchored but missing from the database")
        heads.setdefault(seq, _Head(seq, str(doc["head_hash"]), "anchor", key_id))
        segment = doc.get("segment") or {}
        hashes = [str(h) for h in segment.get("hashes", [])]
        from_seq, to_seq = int(segment.get("from_seq", 0)), int(segment.get("to_seq", 0))
        seg_ok = (
            to_seq == seq
            and from_seq >= 1
            and len(hashes) == to_seq - from_seq + 1
            and _signed_by_trusted_key(
                keyring,
                key_id,
                anchored,
                segment_message(
                    stream=stream, from_seq=from_seq, to_seq=to_seq, hashes=hashes, key_id=key_id
                ),
                str(doc.get("segment_signature", "")),
            )
        )
        if not seg_ok:
            problems.append(f"anchor {seq}: segment signature does not verify")
            continue
        for offset, digest in enumerate(hashes):
            segments[from_seq + offset] = (digest, seq)
    return _bound_retired_keys(heads, segments, keyring, problems)


def _bound_retired_keys(
    heads: dict[int, _Head],
    segments: dict[int, tuple[str, int]],
    keyring: Keyring,
    problems: list[str],
) -> tuple[dict[int, _Head], dict[int, str]]:
    """A retired key's own `anchored_at` claim is not trusted (its holder could backdate it). Its checkpoints
    count only below the first checkpoint signed by a later key, whose head commits to everything before."""
    dropped: set[int] = set()
    for head in heads.values():
        key = keyring.get(head.key_id)
        if key is None or key.retired_at is None:
            continue
        born = datetime.fromisoformat(key.created_at)
        later = [
            h.seq
            for h in heads.values()
            if (k := keyring.get(h.key_id)) is not None and datetime.fromisoformat(k.created_at) > born
        ]
        if not later or head.seq >= min(later):
            dropped.add(head.seq)
            problems.append(
                f"checkpoint {head.seq}: retired key {head.key_id} signed after its successor took over"
                if later
                else f"checkpoint {head.seq}: retired key {head.key_id} has no successor checkpoint"
            )
    kept = {s: h for s, h in heads.items() if s not in dropped}
    return kept, {s: d for s, (d, cp) in segments.items() if cp not in dropped}


def _row_problem(row: dict[str, Any], expected: int, prev: str) -> str | None:
    seq = int(row["seq"])
    if seq != expected:
        return f"seq {expected}: missing (next row is {seq})"
    if row["prev_hash"] != prev:
        return f"seq {seq}: prev_hash does not link to seq {seq - 1}"
    try:
        payload_hash = sha256_hex(canonical_json(row["payload"]))
    except ValueError:
        return f"seq {seq}: payload is not canonical JSON"
    if row["payload_hash"] != payload_hash:
        return f"seq {seq}: payload does not match payload_hash"
    if row["hash"] != record_hash(header_of(row)):
        return f"seq {seq}: record hash does not recompute"
    return None


def chain_rows(conn: psycopg.Connection[Any], stream: str = STREAM) -> Iterator[dict[str, Any]]:
    """Every record of a stream in sequence order, in batches (the rows `verify_rows` checks)."""
    return _rows(conn, stream)


def trusted_heads(
    conn: psycopg.Connection[Any],
    keyring: Keyring | None = None,
    anchors: AnchorStore | None = None,
    stream: str = STREAM,
    problems: list[str] | None = None,
) -> tuple[dict[int, Head], dict[int, str]]:
    """Signed checkpoint heads and notarised segment hashes that verify against the keyring and anchors."""
    return _trusted_heads(
        conn, stream, keyring or Keyring(), anchors, problems if problems is not None else []
    )


def verify_rows(
    rows: Iterable[Mapping[str, Any]],
    heads: Mapping[int, Head],
    segments: Mapping[int, str],
    problems: list[str] | None = None,
) -> VerifyReport:
    """The chain checks over given rows: gapless seq, prev-hash links, payload and record hashes, the
    notarised segments, the signed checkpoint heads, and truncation below the highest signed head. `problems`
    carries earlier findings (from `trusted_heads`); the first row problem is put in front."""
    found = list(problems or [])
    expected, prev, first_bad = 1, GENESIS_HASH, None
    for row in rows:
        problem = _row_problem(dict(row), expected, prev)
        seq = int(row["seq"])
        if problem is None and seq in segments and segments[seq] != row["hash"]:
            problem = f"seq {seq}: hash differs from the notarised segment (rewritten)"
        if problem is None and seq in heads and heads[seq].head_hash != row["hash"]:
            problem = f"seq {seq}: hash differs from the signed checkpoint head"
        if problem is not None:
            first_bad = expected
            found.insert(0, problem)
            break
        prev, expected = row["hash"], expected + 1
    last_good = expected - 1
    if first_bad is None and heads and max(heads) > last_good:
        first_bad = last_good + 1
        found.insert(0, f"seq {first_bad}: rows up to signed seq {max(heads)} are missing (truncated)")
    signed = [s for s in heads if s <= last_good]
    return VerifyReport(
        ok=first_bad is None and not found,
        checked_to_seq=last_good,
        first_bad_seq=first_bad,
        signed_head_seq=max(signed) if signed else None,
        problems=found,
    )


def verify(
    conn: psycopg.Connection[Any],
    *,
    keyring: Keyring | None = None,
    anchors: AnchorStore | None = None,
    stream: str = STREAM,
) -> VerifyReport:
    problems: list[str] = []
    heads, segments = _trusted_heads(conn, stream, keyring or Keyring(), anchors, problems)
    return verify_rows(_rows(conn, stream), heads, segments, problems)
