"""Local single-user evidence workflow. Only reviewed built-in recipes execute."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class StateError(ValueError):
    pass


class IntegrityError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def approval_digest(spec):
    return digest(canonical({"payload": spec["payload"], "dataset_snapshot": spec.get("dataset_snapshot"),
                             "evidence": spec.get("evidence", []), **({"mandate": spec["mandate"]} if "mandate" in spec else {})}))


class Pod:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        (self.root / "packages").mkdir(exist_ok=True)
        self.db = self.root / "pod.sqlite"
        with self._connection() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS objects (kind TEXT,id TEXT PRIMARY KEY,body TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY,spec TEXT,run TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY,at TEXT,kind TEXT,id TEXT,action TEXT)")

    def _connection(self):
        return sqlite3.connect(self.db, timeout=10)

    def _save(self, kind, body, *, connection=None):
        def write(c):
            c.execute("INSERT OR REPLACE INTO objects VALUES (?,?,?)", (kind, body["id"], canonical(body).decode()))
            c.execute("INSERT INTO events(at,kind,id,action) VALUES(?,?,?,?)", (now(), kind, body["id"], body.get("status", "saved")))
        if connection is None:
            with self._connection() as c:
                write(c)
        else:
            write(connection)
        return body

    def _new(self, kind, **body):
        return self._save(kind, {"id": uuid.uuid4().hex, "created_at": now(), **body})

    def get(self, kind, object_id):
        with self._connection() as c:
            row = c.execute("SELECT body FROM objects WHERE kind=? AND id=?", (kind, object_id)).fetchone()
        if row is None:
            raise KeyError(object_id)
        return json.loads(row[0])

    def list(self, kind, *, limit=200, offset=0):
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("invalid pagination")
        with self._connection() as c:
            rows = c.execute("SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC LIMIT ? OFFSET ?", (kind, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _all(self, kind):
        with self._connection() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC", (kind,))]

    def queued_runs(self):
        return [r for r in reversed(self._all("run")) if r["status"] == "queued"]

    def get_request(self, key):
        with self._connection() as c:
            row = c.execute("SELECT spec,run FROM requests WHERE key=?", (key,)).fetchone()
        return {"spec": row[0], "run": row[1]} if row else None

    def create_opportunity(self, title, research_type, problem=""):
        if research_type not in {"investment_research", "capability_evaluation"}:
            raise ValueError("unknown research type")
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError("title must contain 1..300 characters")
        return self._new("opportunity", title=title, research_type=research_type, problem=problem, status="discovered")

    def set_mandate(self, opportunity_id, mandate):
        required = {"objective", "baseline", "acceptance", "stop_condition", "receiver"}
        if not isinstance(mandate, dict) or set(mandate) != required or any(
                not isinstance(v, str) or not v.strip() or len(v) > 3000 for v in mandate.values()):
            raise ValueError("mandate requires objective, baseline, acceptance, stop_condition, receiver")
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM objects WHERE kind='opportunity' AND id=?", (opportunity_id,)).fetchone()
            if not row:
                raise KeyError(opportunity_id)
            op = json.loads(row[0])
            op.update(mandate=mandate, status="planned")
            return self._save("opportunity", op, connection=c)

    def receive_package(self, package_id, receiver, decision, reason):
        if decision not in {"accepted", "rejected", "followup"}:
            raise ValueError("invalid delivery decision")
        if any(not isinstance(v, str) or not v.strip() or len(v)>3000 for v in (receiver, reason)):
            raise ValueError("receiver and reason required")
        package = self.get("package", package_id)
        if not self.verify_package(package["path"])["valid"]:
            raise IntegrityError("delivery package verification failed")
        run = self.get("run", package["run_id"])
        spec = self.get("spec", run["spec_id"])
        feedback = self._new("delivery", package_id=package_id, receiver=receiver,
                             decision=decision, reason=reason, identity="local assertion; not external authentication")
        op = self.get("opportunity", spec["opportunity_id"])
        op.update(status={"accepted":"received", "rejected":"rejected", "followup":"followup"}[decision])
        self._save("opportunity", op)
        return feedback

    def add_artifact(self, source, title, content, metadata=None):
        if not isinstance(content, bytes) or len(content) > 25_000_000:
            raise ValueError("artifact must be bytes, maximum25MB")
        sha = digest(content)
        path = self.root / "blobs" / sha
        if path.exists() and digest(path.read_bytes()) != sha:
            raise IntegrityError("existing blob changed")
        if not path.exists():
            path.write_bytes(content)
        with self._connection() as c:
            rows = c.execute("SELECT body FROM objects WHERE kind='artifact'").fetchall()
        for (row,) in rows:
            value = json.loads(row)
            if value["sha256"] == sha and value["source"] == source:
                return value
        return self._new("artifact", source=source, title=title, sha256=sha, path=str(path), metadata=metadata or {})

    def read_artifact(self, artifact_id):
        artifact = self.get("artifact", artifact_id)
        path = self.root / "blobs" / artifact["sha256"]
        data = path.read_bytes()
        if digest(data) != artifact["sha256"]:
            raise IntegrityError("artifact checksum mismatch")
        return data

    def link_artifact(self, opportunity_id, artifact_id):
        artifact = self.get("artifact", artifact_id)
        self.read_artifact(artifact_id)
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM objects WHERE kind='opportunity' AND id=?", (opportunity_id,)).fetchone()
            if not row:
                raise KeyError(opportunity_id)
            opportunity = json.loads(row[0])
            links = opportunity.setdefault("artifacts", [])
            if artifact_id not in links:
                links.append(artifact_id)
            self._save("opportunity", opportunity, connection=c)
        return {"opportunity_id": opportunity_id, "artifact_id": artifact_id, "sha256": artifact["sha256"]}

    def create_spec(self, opportunity_id, payload):
        opportunity = self.get("opportunity", opportunity_id)
        if payload.get("recipe") not in {"demo", "paper", "quant"}:
            raise ValueError("unknown trusted recipe")
        unknown = set(payload) - {"recipe", "seed", "dataset", "steps", "paths", "target", "features", "min_train", "ridge"}
        if unknown:
            raise ValueError(f"unknown spec fields: {sorted(unknown)}")
        for key, upper in (("steps", 2000), ("paths", 100000)):
            if key in payload and (type(payload[key]) is not int or not 2 <= payload[key] <= upper):
                raise ValueError(f"invalid {key} budget")
        if "seed" in payload and (type(payload["seed"]) is not int or not 0 <= payload["seed"] < 2**32):
            raise ValueError("invalid seed")
        if payload["recipe"] == "quant":
            from .quant import validate_payload
            validate_payload(payload)
        elif set(payload) & {"target", "features", "min_train", "ridge"}:
            raise ValueError("quant fields require quant recipe")
        evidence = []
        for artifact_id in opportunity.get("artifacts", []):
            artifact = self.get("artifact", artifact_id)
            self.read_artifact(artifact_id)
            evidence.append({k: artifact[k] for k in ("id", "source", "title", "sha256", "metadata")})
        return self._new("spec", opportunity_id=opportunity_id, payload=payload, evidence=evidence,
                         sha256=digest(canonical(payload)), status="planned", mandate=opportunity.get("mandate", {}))

    def approve(self, spec_id):
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM objects WHERE kind='spec' AND id=?", (spec_id,)).fetchone()
            if not row:
                raise KeyError(spec_id)
            spec = json.loads(row[0])
            if spec["status"] != "planned":
                raise StateError("spec must be planned before approval")
            dataset = spec["payload"].get("dataset")
            if dataset:
                path = Path(dataset).resolve()
                if not path.is_file():
                    raise ValueError("dataset manifest not found")
                if spec["payload"]["recipe"] == "quant":
                    from .quant import snapshot_dataset
                    spec["dataset_snapshot"] = snapshot_dataset(path)
                else:
                    spec["dataset_snapshot"] = digest(path.read_bytes())
            for evidence in spec.get("evidence", []):
                if digest(self.read_artifact(evidence["id"])) != evidence["sha256"]:
                    raise IntegrityError("source changed before approval")
            spec["approval_sha256"] = approval_digest(spec)
            spec.update(status="approved", approved_at=now())
            return self._save("spec", spec, connection=c)

    def submit(self, spec_id, *, idempotency_key=None):
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM objects WHERE kind='spec' AND id=?", (spec_id,)).fetchone()
            if not row:
                raise KeyError(spec_id)
            spec = json.loads(row[0])
            if spec["status"] != "approved":
                raise StateError("spec must be approved")
            if digest(canonical(spec["payload"])) != spec["sha256"]:
                raise IntegrityError("approved spec changed")
            if idempotency_key:
                previous = c.execute("SELECT spec,run FROM requests WHERE key=?", (idempotency_key,)).fetchone()
                if previous:
                    if previous[0] != spec_id:
                        raise StateError("idempotency conflict")
                    return json.loads(c.execute("SELECT body FROM objects WHERE id=?", (previous[1],)).fetchone()[0])
            run = {"id": uuid.uuid4().hex, "created_at": now(), "spec_id": spec_id, "spec_sha256": spec["sha256"], "status": "queued", "research_status": "not_evaluated"}
            self._save("run", run, connection=c)
            if idempotency_key:
                c.execute("INSERT INTO requests VALUES(?,?,?)", (idempotency_key, spec_id, run["id"]))
            return run

    def execute(self, run_id):
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM objects WHERE kind='run' AND id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            run = json.loads(row[0])
            if run["status"] != "queued":
                return run
            run.update(status="running", started_at=now())
            self._save("run", run, connection=c)
        spec = self.get("spec", run["spec_id"])
        try:
            if digest(canonical(spec["payload"])) != run["spec_sha256"]:
                raise IntegrityError("spec checksum mismatch")
            if spec["payload"].get("dataset"):
                path = Path(spec["payload"]["dataset"]).resolve()
                if spec["payload"]["recipe"] == "quant":
                    from .quant import snapshot_dataset
                    if snapshot_dataset(path) != spec.get("dataset_snapshot"):
                        raise IntegrityError("approved quant dataset changed")
                elif not path.is_file() or digest(path.read_bytes()) != spec.get("dataset_snapshot"):
                    raise IntegrityError("approved dataset manifest changed")
            if spec.get("approval_sha256") != approval_digest(spec):
                raise IntegrityError("approval checksum mismatch")
            for evidence in spec.get("evidence", []):
                if digest(self.read_artifact(evidence["id"])) != evidence["sha256"]:
                    raise IntegrityError("approved source changed")
            from .cases import execute_recipe
            if spec["payload"]["recipe"] == "quant":
                from .quant import execute_quant
                result = execute_quant(spec["payload"])
            else:
                result = execute_recipe(spec["payload"])
            run.update(result=result, evidence_level=result["evidence_level"], research_status=result["research_status"], status=result.get("execution_status", "succeeded"))
        except Exception as exc:
            # Built-in recipes never include credentials in their exception messages.
            run.update(status="failed", error_type=type(exc).__name__, error=str(exc), research_status="not_evaluated")
        run["finished_at"] = now()
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            current = json.loads(c.execute("SELECT body FROM objects WHERE kind='run' AND id=?", (run_id,)).fetchone()[0])
            if current["status"] == "cancelled":
                return current
            return self._save("run", run, connection=c)

    def run_spec(self, spec_id, *, idempotency_key=None):
        run = self.submit(spec_id, idempotency_key=idempotency_key)
        return self.execute(run["id"])

    def cancel(self, run_id):
        with self._connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT body FROM objects WHERE kind='run' AND id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            run = json.loads(row[0])
            if run["status"] not in {"queued", "running"}:
                raise StateError("only queued/running jobs can cancel")
            run.update(status="cancelled", finished_at=now(), cancellation="result publication blocked; trusted inline calculation may finish")
            return self._save("run", run, connection=c)

    def recover(self):
        # Explicit maintenance operation; caller must stop workers before using it.
        recovered = []
        for run in self._all("run"):
            if run["status"] == "running":
                run.update(status="interrupted", finished_at=now(), research_status="not_evaluated")
                self._save("run", run)
                recovered.append(run["id"])
        return recovered

    def review(self, run_id, reviewer, decision):
        run = self.get("run", run_id)
        if run["status"] not in {"succeeded", "blocked"}:
            raise StateError("only completed/blocked results can be reviewed")
        if decision not in {"engineering_verified", "needs_data", "rejected", "scientifically_reviewed"}:
            raise ValueError("invalid review decision")
        if decision == "scientifically_reviewed" and run["research_status"] == "not_evaluated":
            raise StateError("no scientific result to review")
        if not reviewer or len(reviewer) > 200:
            raise ValueError("reviewer required")
        return self._new("review", run_id=run_id, reviewer=reviewer, decision=decision, identity="local assertion; not external authentication")

    def export_package(self, run_id):
        run = self.get("run", run_id)
        reviews = [r for r in self._all("review") if r["run_id"] == run_id]
        if not reviews or reviews[0]["decision"] == "rejected":
            raise StateError("accepted review required")
        spec = self.get("spec", run["spec_id"])
        opportunity = self.get("opportunity", spec["opportunity_id"])
        attachments = {}
        for evidence in spec.get("evidence", []):
            content = self.read_artifact(evidence["id"])
            if digest(content) != evidence["sha256"]:
                raise IntegrityError("source changed before export")
            attachments["evidence-" + evidence["sha256"] + ".bin"] = content
        if spec["payload"]["recipe"] == "quant":
            from .quant import snapshot_dataset
            dataset = Path(spec["payload"]["dataset"]).resolve()
            if snapshot_dataset(dataset) != spec.get("dataset_snapshot"):
                raise IntegrityError("quant dataset changed before export")
            metadata = json.loads(dataset.read_text(encoding="utf-8-sig"))
            attachments["dataset.csv"] = (dataset.parent / metadata["csv"]).read_bytes()
            attachments["dataset-manifest-original.json"] = dataset.read_bytes()
            attachments["dataset-manifest.json"] = canonical({**metadata, "csv":"dataset.csv"})
        package_id = uuid.uuid4().hex
        path = self.root / "packages" / package_id
        path.mkdir()
        values = {"run.json": run, "spec.json": spec, "opportunity.json": opportunity, "reviews.json": reviews}
        for name, value in values.items():
            (path / name).write_bytes(canonical(value))
        for name, content in attachments.items():
            (path / name).write_bytes(content)
        manifest = {"schema_version": 1, "id": package_id, "created_at": now(), "evidence_level": run.get("evidence_level", "none"), "scientific_replication_certified": False, "files": {name: digest((path / name).read_bytes()) for name in [*values, *attachments]}}
        (path / "manifest.json").write_bytes(canonical(manifest))
        return self._new("package", path=str(path), run_id=run_id, manifest=manifest)

    @staticmethod
    def verify_package(path):
        root = Path(path).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        errors = []
        for name, expected in manifest["files"].items():
            target = (root / name).resolve()
            if not target.is_relative_to(root) or target == root:
                raise IntegrityError("package path escapes root")
            if not target.is_file() or digest(target.read_bytes()) != expected:
                errors.append(name)
        required = {"run.json", "spec.json", "opportunity.json", "reviews.json"}
        if not required.issubset(manifest["files"]):
            errors.append("required files absent")
        if not errors:
            try:
                run, spec, opportunity, reviews = [json.loads((root / name).read_text(encoding="utf-8")) for name in ("run.json", "spec.json", "opportunity.json", "reviews.json")]
                valid = (
                    manifest.get("schema_version") == 1
                    and run["status"] in {"succeeded", "blocked"}
                    and run["spec_id"] == spec["id"]
                    and spec["opportunity_id"] == opportunity["id"]
                    and spec["status"] == "approved"
                    and digest(canonical(spec["payload"])) == spec["sha256"] == run["spec_sha256"]
                    and spec["approval_sha256"] == approval_digest(spec)
                    and isinstance(reviews, list) and bool(reviews)
                    and all(r["run_id"] == run["id"] for r in reviews)
                    and reviews[0]["decision"] != "rejected"
                )
                if not valid:
                    errors.append("package record relationships invalid")
            except (KeyError, TypeError, ValueError):
                errors.append("package record schema invalid")
        return {"valid": not errors, "errors": errors, "scientific_replication_certified": False}
