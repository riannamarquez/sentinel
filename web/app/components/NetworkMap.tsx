"use client";

import {
  BaseEdge,
  EdgeLabelRenderer,
  getStraightPath,
  MarkerType,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Bypass } from "../api";
import { dollars } from "./format";

const RED = "#dc2626";
const GRAY = "#94a3b8";

// Each account steps right and down from the one before it, so time reads left to right
// while the chain still fits the narrow left column.
const NODE_WIDTH = 150;
const X_STEP = 40;
const Y_STEP = 140;

type HopData = { amount: string; waited: string | null; attack: boolean; blockedBy: string | null };
type HopEdge = Edge<HopData, "hop">;

function accountLabel(id: string) {
  if (id === "SRC") return "Source account";
  const mule = id.match(/^M(\d+)$/);
  if (mule) return `Mule ${mule[1]}`;
  if (id.startsWith("EXT-")) {
    const name = id.slice(4).replace(/[-_]/g, " ");
    return `${name.charAt(0).toUpperCase()}${name.slice(1)} (outside)`;
  }
  return id;
}

function waitedLabel(seconds: number) {
  const hours = seconds / 3600;
  return hours < 1 ? `waited ${Math.round(seconds / 60)} min` : `waited ${hours.toFixed(1)} h`;
}

function HopEdgeView({ id, sourceX, sourceY, targetX, targetY, data, markerEnd }: EdgeProps<HopEdge>) {
  const [path, labelX, labelY] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  const color = data?.attack ? RED : GRAY;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ stroke: color, strokeWidth: 3 }} />
      {data && (
        <EdgeLabelRenderer>
          <div className="nodrag nopan absolute rounded-md border bg-white px-2 py-0.5 text-center leading-tight shadow-sm"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, borderColor: color }}>
            <div className="text-[15px] font-bold" style={{ color }}>{data.amount}</div>
            {data.waited && <div className="text-xs text-slate-600">{data.waited}</div>}
            {data.blockedBy && (
              <div className="mt-1 rounded bg-emerald-600 px-2 py-0.5 text-xs font-bold text-white">
                ✓ Blocked by {data.blockedBy}
              </div>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { hop: HopEdgeView };

function buildGraph(bypass: Bypass, blockedBy: string | null) {
  const txs = [...bypass.scenario.transactions].sort((a, b) => a.timestamp - b.timestamp);
  const attackAccounts = new Set(
    txs.filter((t) => t.ground_truth_label === "malicious").flatMap((t) => [t.from_id, t.to_id]),
  );

  // Accounts in order of first appearance, which is time order.
  const order: string[] = [];
  for (const t of txs) for (const id of [t.from_id, t.to_id]) if (!order.includes(id)) order.push(id);

  const nodes: Node[] = order.map((id, i) => {
    const attack = attackAccounts.has(id);
    const outside = id.startsWith("EXT-");
    return {
      id,
      position: { x: i * X_STEP, y: i * Y_STEP },
      data: { label: accountLabel(id) },
      draggable: false,
      selectable: false,
      style: {
        width: NODE_WIDTH,
        fontSize: 15,
        fontWeight: 700,
        color: attack ? "#7f1d1d" : "#334155",
        background: outside ? "#f8fafc" : attack ? "#fef2f2" : "#ffffff",
        border: `2px ${outside ? "dashed" : "solid"} ${attack ? RED : GRAY}`,
        borderRadius: 10,
      },
    };
  });

  // "Waited" is the time since the money last arrived in the sending account.
  const edges: HopEdge[] = txs.map((t, i) => {
    const inflow = txs.slice(0, i).findLast((p) => p.to_id === t.from_id);
    const attack = t.ground_truth_label === "malicious";
    return {
      id: t.transaction_id,
      source: t.from_id,
      target: t.to_id,
      type: "hop",
      markerEnd: { type: MarkerType.ArrowClosed, color: attack ? RED : GRAY, width: 18, height: 18 },
      data: {
        amount: dollars(Math.round(t.amount_cents / 100) * 100),
        waited: inflow ? waitedLabel(t.timestamp - inflow.timestamp) : null,
        attack,
        blockedBy: i === txs.length - 1 ? blockedBy : null,
      },
    };
  });

  return { nodes, edges };
}

export default function NetworkMap({ bypass, blockedBy }: { bypass: Bypass | null; blockedBy: string | null }) {
  if (!bypass) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center">
        <p className="font-semibold text-slate-500">Account network map</p>
        <p className="mt-1 text-sm text-slate-400">The attack path will appear here.</p>
      </div>
    );
  }

  const { nodes, edges } = buildGraph(bypass, blockedBy);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3 text-sm">
        <span className="font-semibold">Red&apos;s attack path</span>
        <span className="flex items-center gap-1 text-xs text-slate-500">
          <span className="inline-block h-0.5 w-4 bg-red-600" /> stolen money
        </span>
      </div>
      <div className="min-h-0 flex-1">
        {/* Remount per bypass so fitView re-frames the new path. */}
        <ReactFlow key={bypass.bypass_id} nodes={nodes} edges={edges} edgeTypes={edgeTypes}
          fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.3}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
          panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false}
          preventScrolling={false} />
      </div>
    </div>
  );
}
