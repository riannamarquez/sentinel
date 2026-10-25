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
import type { Approval, Bypass } from "../api";
import { analyzeChain, attackStory, type AttackChain } from "./attackChain";
import { dollars } from "./format";

const RED = "#dc2626";
const GRAY = "#94a3b8";

// Each account steps right and down from the one before it, so time reads left to right
// while the chain still fits the narrow left column.
const NODE_WIDTH = 150;
const X_STEP = 40;
const Y_STEP = 140;

type HopData = { amount: string; waited: string | null; attack: boolean };
type HopEdge = Edge<HopData, "hop">;

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
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { hop: HopEdgeView };

function buildGraph({ order, owned, labels, hops }: AttackChain) {
  const attackAccounts = new Set(hops.filter((h) => h.attack).flatMap((h) => [h.from, h.to]));

  const nodes: Node[] = order.map((id, i) => {
    const attack = attackAccounts.has(id);
    const outside = !owned.has(id);
    return {
      id,
      position: { x: i * X_STEP, y: i * Y_STEP },
      data: { label: labels.get(id) },
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

  // One arrow per hop, so split transfers to the same account don't draw on top of each other.
  const edges: HopEdge[] = hops.map((h) => ({
    id: h.key,
    source: h.from,
    target: h.to,
    type: "hop",
    markerEnd: { type: MarkerType.ArrowClosed, color: h.attack ? RED : GRAY, width: 18, height: 18 },
    data: {
      amount: dollars(Math.round(h.totalCents / 100) * 100) + (h.txs.length > 1 ? ` in ${h.txs.length} transfers` : ""),
      waited: h.waitedSeconds === null ? null : waitedLabel(h.waitedSeconds),
      attack: h.attack,
    },
  }));

  return { nodes, edges };
}

// The rechallenge is a fresh test attack from the backend, not Red's path, so the result is
// reported under the map rather than drawn onto any hop, and never called "like this one".
function RechallengeBanner({ rechallenge }: { rechallenge: NonNullable<Approval["rechallenge"]> }) {
  const fired = rechallenge.triggered_rule_ids.join(", ");
  return rechallenge.alert ? (
    <div className="border-t-2 border-emerald-300 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-900">
      ✓ The active rules caught a fresh test attack{fired && ` (fired: ${fired})`}
    </div>
  ) : (
    <div className="border-t-2 border-red-300 bg-red-50 px-4 py-3 text-sm font-semibold text-red-900">
      ✗ A fresh test attack still got through
    </div>
  );
}

export default function NetworkMap({ bypass, redRan, rechallenge }: {
  bypass: Bypass | null;
  redRan: boolean;
  rechallenge: Approval["rechallenge"];
}) {
  if (!bypass) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center">
        <p className="font-semibold text-slate-500">Account network map</p>
        <p className="mt-1 text-sm text-slate-400">
          {redRan ? "Red didn't find a way past the rules, so there's no attack path to show." : "The attack path will appear here."}
        </p>
      </div>
    );
  }

  const chain = analyzeChain(bypass);
  const { nodes, edges } = buildGraph(chain);
  const story = attackStory(chain);
  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-3">
        <p className="text-sm font-semibold">How the stolen money moved</p>
        {story && <p className="mt-1.5 text-sm leading-snug text-slate-700">{story.join(" ")}</p>}
        <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 bg-red-600" /> stolen money
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-4 rounded-sm border-2 border-slate-400" /> inside this bank
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-4 rounded-sm border-2 border-dashed border-slate-400" /> outside (another institution)
          </li>
        </ul>
      </div>
      <div className="min-h-0 flex-1">
        {/* Remount per bypass so fitView re-frames the new path. */}
        <ReactFlow key={bypass.bypass_id} nodes={nodes} edges={edges} edgeTypes={edgeTypes}
          fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.3}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
          panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false}
          preventScrolling={false} />
      </div>
      {rechallenge && <RechallengeBanner rechallenge={rechallenge} />}
    </div>
  );
}
