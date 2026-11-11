"""Immutable snapshots + fenced atomic head CAS. Works on standalone MongoDB."""
from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


class Conflict(ValueError):
    pass


class FencedOut(Conflict):
    """Ownership changed; leave queued commands for the current writer to recover."""
    pass


class MongoStore:
    def __init__(self, db):
        self.db = db
        self.heads = db.operations_heads
        self.states = db.operations_states
        self.commands = db.operations_commands
        self.jobs = db.operations_adjustments
        self.logs = db.operations_history
        self.previews = db.operations_previews
        self._finalized_state = None
        self._finalized_receipts = set()

    async def setup(self):
        await self.heads.update_one({"_id": "active"}, {"$setOnInsert": {"version": 0, "state_id": None, "owner": "", "epoch": 0, "lease_until": 0, "receipts": []}}, upsert=True)
        await self.states.create_index("expires_at", expireAfterSeconds=0)
        await self.previews.create_index('purge_at', expireAfterSeconds=0)
        await self.commands.create_index([("status", 1), ("created_at", 1)])
        await self.logs.create_index([("run_id", 1), ("at", -1)])

    async def archive(self, state):
        await self.db.operations_runs.update_one({"_id": state["run_id"]}, {"$setOnInsert": {"state": state}}, upsert=True)

    async def put_preview(self, preview):
        doc = copy.deepcopy(preview)
        if doc.get('expires_at'):
            doc['purge_at'] = datetime.fromtimestamp(doc['expires_at'], timezone.utc)
        await self.previews.insert_one(doc)

    async def get_preview(self, key):
        return await self.previews.find_one({'_id': key})

    async def save_chain_draft(self, config):
        await self.db.operations_chain_configs.replace_one({'_id': 'draft'}, {'_id': 'draft', 'config': copy.deepcopy(config)}, upsert=True)

    async def get_chain_draft(self):
        doc = await self.db.operations_chain_configs.find_one({'_id': 'draft'})
        return doc.get('config') if doc else None

    async def claim(self, owner, now):
        current = await self.heads.find_one({"_id": "active"})
        if current["owner"] == owner:
            query = {"_id": "active", "owner": owner, "epoch": current["epoch"]}
            update = {"$set": {"lease_until": now + 15, "heartbeat_at": now}}
        else:
            query = {"_id": "active", "lease_until": {"$lte": now}}
            update = {"$set": {"owner": owner, "lease_until": now + 15, "heartbeat_at": now}, "$inc": {"epoch": 1}}
        return await self.heads.find_one_and_update(query, update, return_document=ReturnDocument.AFTER)

    async def read(self):
        head = await self.heads.find_one({"_id": "active"})
        if not head or not head.get("state_id"):
            return None, head
        doc = await self.states.find_one({"_id": head["state_id"]})
        if not doc:
            raise RuntimeError("已提交状态快照缺失，请恢复备份；不自动重置实例")
        return doc["state"], head

    async def publish(self, state, head, now, *, command_id=None, result=None, logs=None):
        state = copy.deepcopy(state)
        state["version"] = head["version"] + 1
        sid = uuid4().hex
        doc = {"_id": sid, "state": state, "command_id": command_id, "at": now, "transitions": logs or []}
        await self.states.insert_one(doc)
        receipts = head.get("receipts", [])[:]
        if command_id:
            receipts.append({"id": command_id, "result": result or {"run_id": state["run_id"]}})
        changed = await self.heads.find_one_and_update(
            {"_id": "active", "owner": head["owner"], "epoch": head["epoch"], "version": head["version"], "lease_until": {"$gt": now}},
            {"$set": {"state_id": sid, "version": state["version"], "run_id": state["run_id"], "receipts": receipts[-128:]}},
            return_document=ReturnDocument.AFTER)
        if changed is None:
            await self.states.update_one({"_id": sid}, {"$set": {"expires_at": datetime.now(timezone.utc) + timedelta(days=2)}})
            raise FencedOut("执行维护者或状态版本已变化，重新读取后重试")
        # An active snapshot never expires, even after a long service outage.
        await self.states.update_one({"_id": sid}, {"$unset": {"expires_at": ""}})
        if head.get("state_id"):
            await self.states.update_one({"_id": head["state_id"]}, {"$set": {"expires_at": datetime.now(timezone.utc) + timedelta(days=2)}})
        await self.finalize(changed)
        return state, changed

    async def finalize(self, head):
        if head.get("state_id") and head["state_id"] != self._finalized_state:
            doc = await self.states.find_one({"_id": head["state_id"]})
            if doc:
                await self.states.update_one({"_id": doc["_id"]}, {"$unset": {"expires_at": ""}})
                for i, entry in enumerate(doc.get("transitions", [])):
                    await self.logs.update_one({"_id": f"{doc['_id']}:{i}"}, {"$setOnInsert": {**entry, "run_id": doc["state"]["run_id"], "at": entry.get("occurred_at", doc["at"]), "state_version": doc["state"]["version"]}}, upsert=True)
                self._finalized_state = head["state_id"]
        for receipt in head.get("receipts", []):
            if receipt["id"] in self._finalized_receipts:
                continue
            await self.commands.update_one({"_id": receipt["id"], "status": "queued"}, {"$set": {"status": "done", "result": receipt["result"]}})
            self._finalized_receipts.add(receipt["id"])
        self._finalized_receipts.intersection_update(r["id"] for r in head.get("receipts", []))

    async def submit(self, cid, kind, payload, now):
        try:
            await self.commands.insert_one({"_id": cid, "kind": kind, "payload": payload, "created_at": now, "status": "queued"})
        except DuplicateKeyError:
            pass
        doc = await self.commands.find_one({"_id": cid})
        if doc["kind"] != kind or doc["payload"] != payload:
            raise Conflict("相同幂等键不能用于不同请求")
        return doc

    async def queued(self, now=None):
        query = {"status": "queued"}
        if now is not None:
            query["$or"] = [{"payload.scheduled_at": {"$exists": False}}, {"payload.scheduled_at": None}, {"payload.scheduled_at": {"$lte": now}}]
        return await self.commands.find(query).sort("created_at", 1).limit(20).to_list(20)

    async def command(self, cid):
        return await self.commands.find_one({"_id": cid})

    async def fail(self, cid, error, code=422):
        await self.commands.update_one({"_id": cid, "status": "queued"}, {"$set": {"status": "failed", "error": str(error), "code": code}})

    async def put_job(self, job):
        try:
            await self.jobs.insert_one(job)
        except DuplicateKeyError:
            pass
        return await self.jobs.find_one({"_id": job["_id"]})

    async def job(self, jid):
        return await self.jobs.find_one({"_id": jid})

    async def update_job(self, jid, values):
        await self.jobs.update_one({"_id": jid}, {"$set": values})

    async def pending_jobs(self):
        return await self.jobs.find({"status": "queued"}).sort("created_at", 1).limit(2).to_list(2)

    async def recover_jobs(self, owner):
        await self.jobs.update_many({"status": "running", "owner": {"$ne": owner}}, {"$set": {"status": "queued"}})

    async def history(self, run_id, limit=100):
        rows = await self.logs.find({"run_id": run_id}, {"_id": 0}).sort("at", -1).limit(limit).to_list(limit)
        jobs = await self.jobs.find({"run_id": run_id}, {"snapshot": 0}).sort("created_at", -1).limit(20).to_list(20)
        for j in jobs:
            j["id"] = j.pop("_id")
        return {"events": rows, "adjustments": jobs}


class MemoryStore:
    """Same persistence contract for deterministic tests; never production fallback."""
    def __init__(self):
        self.state = None
        self.head = {"version": 0, "owner": "", "epoch": 0, "lease_until": 0, "receipts": []}
        self.commands, self.jobs, self.logs = {}, {}, []
        self.archives = {}
        self.previews = {}
        self.chain_draft = None

    async def setup(self):
        pass

    async def archive(self, state):
        self.archives[state['run_id']] = copy.deepcopy(state)

    async def put_preview(self, preview):
        self.previews[preview['_id']] = copy.deepcopy(preview)

    async def get_preview(self, key):
        return copy.deepcopy(self.previews.get(key))

    async def save_chain_draft(self, config):
        self.chain_draft = copy.deepcopy(config)

    async def get_chain_draft(self):
        return copy.deepcopy(self.chain_draft)

    async def claim(self, owner, now):
        if self.head["owner"] not in {"", owner} and self.head["lease_until"] > now:
            return None
        if self.head["owner"] != owner:
            self.head["epoch"] += 1
        self.head.update(owner=owner, lease_until=now + 15, heartbeat_at=now)
        return copy.deepcopy(self.head)

    async def read(self):
        return copy.deepcopy(self.state), copy.deepcopy(self.head)

    async def publish(self, state, head, now, *, command_id=None, result=None, logs=None):
        if any(head[k] != self.head[k] for k in ["version", "owner", "epoch"]) or self.head["lease_until"] <= now:
            raise FencedOut("维护者/版本失效")
        self.state = copy.deepcopy(state)
        self.head["version"] += 1
        self.state["version"] = self.head["version"]
        self.head["run_id"] = state["run_id"]
        if command_id:
            self.head["receipts"].append({"id": command_id, "result": result or {"run_id": state["run_id"]}})
        self.logs += [{**e, "run_id": state["run_id"], "at": e.get("occurred_at", now)} for e in (logs or [])]
        await self.finalize(self.head)
        return await self.read()

    async def finalize(self, head):
        for r in head.get("receipts", []):
            if r["id"] in self.commands:
                self.commands[r["id"]].update(status="done", result=r["result"])

    async def submit(self, cid, kind, payload, now):
        if cid in self.commands and (self.commands[cid]["kind"] != kind or self.commands[cid]["payload"] != payload):
            raise Conflict("幂等键复用")
        return copy.deepcopy(self.commands.setdefault(cid, {"_id": cid, "kind": kind, "payload": copy.deepcopy(payload), "created_at": now, "status": "queued"}))

    async def queued(self, now=None):
        return copy.deepcopy([v for v in self.commands.values() if v["status"] == "queued" and (now is None or not v["payload"].get("scheduled_at") or v["payload"]["scheduled_at"] <= now)][:20])

    async def command(self, cid):
        return copy.deepcopy(self.commands.get(cid))

    async def fail(self, cid, error, code=422):
        self.commands[cid].update(status="failed", error=str(error), code=code)

    async def put_job(self, job):
        return copy.deepcopy(self.jobs.setdefault(job["_id"], copy.deepcopy(job)))

    async def job(self, jid):
        return copy.deepcopy(self.jobs.get(jid))

    async def update_job(self, jid, values):
        self.jobs[jid].update(copy.deepcopy(values))

    async def pending_jobs(self):
        return copy.deepcopy([v for v in self.jobs.values() if v["status"] == "queued"][:2])

    async def recover_jobs(self, owner):
        for j in self.jobs.values():
            if j["status"] == "running" and j.get("owner") != owner:
                j["status"] = "queued"

    async def history(self, run_id, limit=100):
        return {"events": sorted([copy.deepcopy(e) for e in self.logs if e["run_id"] == run_id], key=lambda e: e["at"], reverse=True)[:limit],
                "adjustments": [{**copy.deepcopy(j), "id": j["_id"]} for j in self.jobs.values() if j["run_id"] == run_id]}
