"""Trim orders back to a target count, oldest first, so a full scan stays fast enough.

Checkouts add orders all day. Past ~1.5M on an M10, overlapping COLLSCANs push each
other out of the WiredTiger cache, every scan goes to disk, and the incident turns
from "checkout takes a second" into a queue that never drains.
"""

import os

from pymongo import MongoClient

db = MongoClient(os.environ["MONGODB_URI"])[os.environ.get("MONGODB_DB", "storefront")]
TARGET = int(os.environ.get("SEED_ORDERS", "1300000"))

extra = db.orders.count_documents({}) - TARGET
print(f"orders: {extra + TARGET}, removing {max(extra, 0)}", flush=True)
while extra > 0:
    ids = [d["_id"] for d in db.orders.find({}, {"_id": 1}).sort("created_at", 1).limit(min(10_000, extra))]
    extra -= db.orders.delete_many({"_id": {"$in": ids}}).deleted_count
    print(f"  {extra} to go", flush=True)
print("orders:", db.orders.estimated_document_count())
