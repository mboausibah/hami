"""Clusters = connected components of reviewer-approved links (a rejected link splits a cluster)."""
from __future__ import annotations

import sqlite3
from collections import defaultdict


def _components(edges: list[tuple[int, int]]) -> dict[int, list[int]]:
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    comps: dict[int, list[int]] = defaultdict(list)
    for x in list(parent):
        comps[find(x)].append(x)
    return {min(v): sorted(v) for v in comps.values()}


def clusters_for_all(conn: sqlite3.Connection) -> dict[int, list[int]]:
    """{cluster_id (smallest scan id): [scan ids]} over approved links. Scans of the same host as a
    cluster member join the cluster too (a case is a site)."""
    links = conn.execute("SELECT scan_a, scan_b FROM links WHERE review_status='approved'").fetchall()
    edges = [(r["scan_a"], r["scan_b"]) for r in links]
    if not edges:
        return {}
    members = {s for e in edges for s in e}
    marks = ",".join("?" * len(members))
    hosts = conn.execute(f"SELECT scan_id, host FROM scans WHERE scan_id IN ({marks})", tuple(members)).fetchall()
    host_set = {r["host"] for r in hosts}
    hmarks = ",".join("?" * len(host_set))
    same_host = conn.execute(f"SELECT scan_id, host FROM scans WHERE host IN ({hmarks})", tuple(host_set)).fetchall()
    first_by_host: dict[str, int] = {}
    for r in hosts:
        first_by_host.setdefault(r["host"], r["scan_id"])
    for r in same_host:
        anchor = first_by_host[r["host"]]
        if r["scan_id"] != anchor:
            edges.append((anchor, r["scan_id"]))
    return _components(edges)


def cluster_of(conn: sqlite3.Connection, scan_id: int) -> tuple[int | None, list[int]]:
    for cid, scans in clusters_for_all(conn).items():
        if scan_id in scans or cid == scan_id:
            return cid, scans
    return None, []
