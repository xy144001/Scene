#!/usr/bin/env python3
"""Remove disconnected bbox-polluting fragments from a GLB asset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean broad slabs and low-area bbox fragments from a GLB asset.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--significant-area", type=float, default=0.01)
    parser.add_argument("--bbox-padding", type=float, default=0.02)
    parser.add_argument("--broad-area", type=float, default=0.5)
    return parser.parse_args()


def face_components(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    face_count = len(mesh.faces)
    parent = np.arange(face_count, dtype=np.int32)
    rank = np.zeros(face_count, dtype=np.int8)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return int(index)

    def union(a: int, b: int) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a == root_b:
            return
        if rank[root_a] < rank[root_b]:
            root_a, root_b = root_b, root_a
        parent[root_b] = root_a
        if rank[root_a] == rank[root_b]:
            rank[root_a] += 1

    for a, b in mesh.face_adjacency:
        union(int(a), int(b))

    groups: dict[int, list[int]] = {}
    for index in range(face_count):
        groups.setdefault(find(index), []).append(index)
    return [np.asarray(faces, dtype=np.int64) for faces in groups.values()]


def component_stats(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    face_vertices = mesh.vertices[mesh.faces]
    face_areas = mesh.area_faces
    rows: list[dict[str, Any]] = []
    for index, faces in enumerate(face_components(mesh)):
        verts = face_vertices[faces].reshape(-1, 3)
        bounds = np.stack([verts.min(axis=0), verts.max(axis=0)])
        extents = bounds[1] - bounds[0]
        sorted_extents = np.sort(extents)
        broad_sheet = bool(sorted_extents[2] >= 0.62 and sorted_extents[1] >= 0.50 and sorted_extents[0] <= 0.045)
        rows.append(
            {
                "index": index,
                "faces": faces,
                "face_count": int(len(faces)),
                "area": float(face_areas[faces].sum()),
                "bounds": bounds,
                "extents": extents,
                "broad_sheet": broad_sheet,
            }
        )
    return rows


def json_component(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "index": int(row["index"]),
        "face_count": int(row["face_count"]),
        "area": round(float(row["area"]), 8),
        "bounds": np.round(row["bounds"], 6).tolist(),
        "extents": np.round(row["extents"], 6).tolist(),
        "broad_sheet": bool(row["broad_sheet"]),
    }


def clean_mesh(mesh: trimesh.Trimesh, args: argparse.Namespace) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    rows = component_stats(mesh)
    removed_faces: list[np.ndarray] = []
    removed: list[dict[str, Any]] = []

    active_rows = []
    for row in rows:
        if row["broad_sheet"] and float(row["area"]) >= args.broad_area:
            removed_faces.append(row["faces"])
            removed.append(json_component(row, "broad_high_area_slab"))
        else:
            active_rows.append(row)

    significant_bounds = [row["bounds"] for row in active_rows if float(row["area"]) >= args.significant_area]
    if significant_bounds:
        stacked = np.stack(significant_bounds)
        robust_bounds = np.stack([stacked[:, 0, :].min(axis=0), stacked[:, 1, :].max(axis=0)])
    else:
        robust_bounds = np.asarray(mesh.bounds, dtype=float)

    min_allowed = robust_bounds[0] - float(args.bbox_padding)
    max_allowed = robust_bounds[1] + float(args.bbox_padding)
    for row in active_rows:
        if float(row["area"]) >= args.significant_area:
            continue
        bounds = row["bounds"]
        outside = bool(np.any(bounds[0] < min_allowed) or np.any(bounds[1] > max_allowed))
        if outside:
            removed_faces.append(row["faces"])
            removed.append(json_component(row, "low_area_bbox_outlier"))

    if removed_faces:
        mask = np.ones(len(mesh.faces), dtype=bool)
        mask[np.concatenate(removed_faces)] = False
        cleaned = mesh.copy()
        cleaned.update_faces(mask)
        cleaned.remove_unreferenced_vertices()
    else:
        cleaned = mesh.copy()

    raw_bounds = np.asarray(mesh.bounds, dtype=float)
    clean_bounds = np.asarray(cleaned.bounds, dtype=float)
    report = {
        "raw_bounds": np.round(raw_bounds, 6).tolist(),
        "raw_extents": np.round(raw_bounds[1] - raw_bounds[0], 6).tolist(),
        "robust_bounds": np.round(robust_bounds, 6).tolist(),
        "robust_extents": np.round(robust_bounds[1] - robust_bounds[0], 6).tolist(),
        "clean_bounds": np.round(clean_bounds, 6).tolist(),
        "clean_extents": np.round(clean_bounds[1] - clean_bounds[0], 6).tolist(),
        "removed_component_count": len(removed),
        "removed_face_count": int(sum(len(faces) for faces in removed_faces)),
        "removed_components": removed,
    }
    return cleaned, report


def main() -> None:
    args = parse_args()
    loaded = trimesh.load(args.input, force="scene")
    if not isinstance(loaded, trimesh.Scene):
        loaded = trimesh.Scene(loaded)

    output_scene = trimesh.Scene()
    reports = []
    for node in loaded.graph.nodes_geometry:
        node_transform, geom_name = loaded.graph[node]
        geom = loaded.geometry[geom_name].copy()
        geom.apply_transform(node_transform)
        cleaned, report = clean_mesh(geom, args)
        reports.append({"geometry": geom_name, **report})
        output_scene.add_geometry(cleaned, geom_name=geom_name)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_scene.export(args.output)

    full_report = {
        "input": str(args.input),
        "output": str(args.output),
        "significant_area": float(args.significant_area),
        "bbox_padding": float(args.bbox_padding),
        "broad_area": float(args.broad_area),
        "geometries": reports,
    }
    report_path = args.report or args.output.with_suffix(".bbox_cleanup.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")
    print(json.dumps(full_report, indent=2), flush=True)


if __name__ == "__main__":
    main()
