"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { ImageManager, ownerQueryString } from "@/components/ImageManager";
import type { ImageRecord } from "@/lib/types";
import { IconX } from "@/components/icons";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type Connection,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { ApiEndpoint, FlowStep, FlowStepType } from "@/lib/types";

// Shared visual editor for a generic-engine FlowDefinition's step graph -- reused at
// /niches (Super Admin, editing NicheTemplate.default_flow_steps/default_ui_layout) and
// /flow-builder (Owner/Manager, editing a business's own FlowDefinition.steps/ui_layout
// via PUT /restaurants/{id}/flow/steps). Server-side shape validation
// (app/services/flow_shape_validation.py::validate_flow_graph) is the real source of
// truth -- this editor keeps the common path easy to build correctly, but a save can
// still be rejected (e.g. a dangling reference left after deleting a node); that error
// is surfaced verbatim from the API, not silently swallowed.

const STEP_TYPES: FlowStepType[] = [
  "message",
  "menu_select",
  "quantity_input",
  "free_text_input",
  "confirm_action",
  "condition",
  "delay",
  "api_call",
  "human_handoff",
  "ai_response",
  "send_whatsapp_flow",
];

const TYPE_COLORS: Record<FlowStepType, string> = {
  message: "border-slate-300 bg-slate-50",
  menu_select: "border-blue-300 bg-blue-50",
  quantity_input: "border-indigo-300 bg-indigo-50",
  free_text_input: "border-violet-300 bg-violet-50",
  confirm_action: "border-emerald-300 bg-emerald-50",
  condition: "border-amber-300 bg-amber-50",
  delay: "border-cyan-300 bg-cyan-50",
  api_call: "border-rose-300 bg-rose-50",
  human_handoff: "border-orange-300 bg-orange-50",
  ai_response: "border-fuchsia-300 bg-fuchsia-50",
  send_whatsapp_flow: "border-teal-300 bg-teal-50",
};

const HAS_NO_NEXT: FlowStepType[] = ["human_handoff", "condition"];
const MAX_DELAY_SECONDS = 5.0; // mirrors backend MAX_DELAY_SECONDS_PER_STEP (flow_shape_validation.py)
const CONDITION_OPERATORS = ["equals", "not_equals", "greater_than", "less_than", "contains"] as const;

function defaultStepFor(stepId: string, type: FlowStepType): FlowStep {
  switch (type) {
    case "message":
      return { step_id: stepId, type, prompt: "New message", next: null, back_target: null };
    case "menu_select":
      return {
        step_id: stepId, type, prompt: "Choose an option", buttons_from: "static",
        static_options: [], routes: {}, next: null, back_target: null,
      };
    case "quantity_input":
      return { step_id: stepId, type, prompt: "Enter quantity", next: null, back_target: null };
    case "free_text_input":
      return { step_id: stepId, type, prompt: "Type your answer", capture_key: "note", next: null, back_target: null };
    case "confirm_action":
      return { step_id: stepId, type, prompt: "Confirm?", next: null, back_target: null };
    case "condition":
      return { step_id: stepId, type, condition: { context_key: "", operator: "equals", value: "" }, then_step: null, else_step: null };
    case "delay":
      return { step_id: stepId, type, delay_seconds: 1, next: null };
    case "api_call":
      return { step_id: stepId, type, endpoint_id: null, capture_key: "", next: null };
    case "human_handoff":
      return { step_id: stepId, type, message: "Connecting you with our team now" };
    case "ai_response":
      return { step_id: stepId, type, next: null };
    case "send_whatsapp_flow":
      // Opt-in per restaurant (whatsapp_flow_order_id) -- see generic_flow_engine.py's
      // _render_step. fallback_next is where customers land if the business hasn't
      // enabled native ordering; defaults to `next` if left unset.
      return { step_id: stepId, type, prompt: "Ready to order?", cta: "Order Now", next: null, fallback_next: null, back_target: null };
  }
}

function stepPreview(step: FlowStep): string {
  if (typeof step.prompt === "string" && step.prompt) return step.prompt;
  if (typeof step.message === "string" && step.message) return step.message;
  if (step.type === "condition") {
    const c = (step.condition as { context_key?: string; operator?: string; value?: unknown }) || {};
    return `${c.context_key || "?"} ${c.operator || "?"} ${JSON.stringify(c.value)}`;
  }
  if (step.type === "delay") return `wait ${step.delay_seconds ?? 0}s`;
  if (step.type === "api_call") return `call: ${step.endpoint_id || "(no endpoint chosen)"}`;
  return "";
}

// --- Custom node -------------------------------------------------------------------

interface StepNodeData {
  step: FlowStep;
  isEntry: boolean;
  [key: string]: unknown;
}

function StepNode({ data, selected }: NodeProps) {
  const { step, isEntry } = data as StepNodeData;
  const color = TYPE_COLORS[step.type] || TYPE_COLORS.message;
  const showNext = !HAS_NO_NEXT.includes(step.type);

  return (
    <div className={`w-56 rounded-xl border-2 px-3 py-2.5 shadow-soft transition-shadow ${color} ${selected ? "shadow-panel ring-2 ring-primary ring-offset-2" : ""}`}>
      <Handle type="target" position={Position.Top} id="in" className="!h-2 !w-2 !bg-slate-400" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs font-semibold text-slate-700">{step.step_id}</span>
        {isEntry && <span className="rounded-full bg-primary px-1.5 py-0.5 text-[9px] font-medium text-white">ENTRY</span>}
      </div>
      <p className="mt-0.5 text-[10px] uppercase tracking-wide text-slate-500">{step.type}</p>
      <p className="mt-1 truncate text-xs text-slate-600">{stepPreview(step)}</p>

      {step.type === "condition" ? (
        <>
          <Handle type="source" position={Position.Right} id="then" style={{ top: "35%" }} className="!h-2 !w-2 !bg-emerald-500" />
          <Handle type="source" position={Position.Right} id="else" style={{ top: "65%" }} className="!h-2 !w-2 !bg-red-500" />
        </>
      ) : (
        showNext && <Handle type="source" position={Position.Bottom} id="out" className="!h-2 !w-2 !bg-slate-500" />
      )}
      <Handle type="source" position={Position.Left} id="back" className="!h-2 !w-2 !bg-slate-300" />
    </div>
  );
}

const NODE_TYPES = { step: StepNode };

// --- Edge derivation -----------------------------------------------------------------
// Edges are always DERIVED from the steps array (never a separate source of truth) --
// this is what keeps the graph and the underlying JSON impossible to desync.

function stepsToEdges(steps: FlowStep[]): Edge[] {
  const edges: Edge[] = [];
  const ids = new Set(steps.map((s) => s.step_id));

  for (const step of steps) {
    const next = step.next as string | null | undefined;
    if (next && ids.has(next)) {
      edges.push({
        id: `${step.step_id}-next-${next}`, source: step.step_id, target: next,
        sourceHandle: "out", label: "next", data: { field: "next" },
        markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#64748b" },
      });
    }
    const backTarget = step.back_target as string | null | undefined;
    if (backTarget && ids.has(backTarget)) {
      edges.push({
        id: `${step.step_id}-back-${backTarget}`, source: step.step_id, target: backTarget,
        sourceHandle: "back", label: "back", data: { field: "back_target" },
        style: { stroke: "#cbd5e1", strokeDasharray: "4 3" }, markerEnd: { type: MarkerType.ArrowClosed },
      });
    }
    if (step.type === "condition") {
      const thenStep = step.then_step as string | null | undefined;
      const elseStep = step.else_step as string | null | undefined;
      if (thenStep && ids.has(thenStep)) {
        edges.push({
          id: `${step.step_id}-then-${thenStep}`, source: step.step_id, target: thenStep,
          sourceHandle: "then", label: "true", data: { field: "then_step" },
          style: { stroke: "#10b981" }, markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
      if (elseStep && ids.has(elseStep)) {
        edges.push({
          id: `${step.step_id}-else-${elseStep}`, source: step.step_id, target: elseStep,
          sourceHandle: "else", label: "false", data: { field: "else_step" },
          style: { stroke: "#ef4444" }, markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    const routes = (step.routes as Record<string, string> | undefined) || {};
    for (const [buttonId, target] of Object.entries(routes)) {
      if (!ids.has(target)) continue;
      edges.push({
        id: `${step.step_id}-route-${buttonId}-${target}`, source: step.step_id, target,
        sourceHandle: "out", label: buttonId, data: { field: "route", routeKey: buttonId }, deletable: false,
        style: { stroke: "#93c5fd" }, markerEnd: { type: MarkerType.ArrowClosed },
      });
    }
  }
  return edges;
}

// --- Property panel --------------------------------------------------------------------

// Curated images attached directly to this step (see backend/app/models/image.py's
// flow_definition_id/flow_step_id owner shape and generic_flow_engine.py::_step_gallery)
// -- distinct from an item/category's own images, which a menu_select step only shows
// indirectly via buttons_from. Only rendered when editing a real business's live
// FlowDefinition (restaurantId+flowDefinitionId both set) -- a niche TEMPLATE's
// default_flow_steps has no restaurant/FlowDefinition row to attach an Image against yet.
function StepImagesEditor({ restaurantId, flowDefinitionId, stepId }: { restaurantId: string; flowDefinitionId: string; stepId: string }) {
  const [images, setImages] = useState<ImageRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch<ImageRecord[]>(`/restaurants/${restaurantId}/images?${ownerQueryString({ flowDefinitionId, stepId })}`)
      .then((rows) => { if (!cancelled) setImages(rows); })
      .catch(() => { if (!cancelled) setImages([]); }) // e.g. a brand-new step not saved yet
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [restaurantId, flowDefinitionId, stepId]);

  return (
    <div>
      <label className="block text-xs font-medium text-slate-500">Images shown on this step</label>
      <p className="mb-1 text-[10px] text-slate-400">Save the flow once after adding a new step before attaching images to it.</p>
      {loading ? (
        <p className="text-xs text-slate-400">Loading...</p>
      ) : (
        <ImageManager
          restaurantId={restaurantId}
          imageType="gallery"
          owner={{ flowDefinitionId, stepId }}
          images={images}
          onChange={setImages}
        />
      )}
    </div>
  );
}

function StepPropertyPanel({
  step, allStepIds, apiEndpoints, onChange, onDelete, restaurantId, flowDefinitionId,
}: {
  step: FlowStep;
  allStepIds: string[];
  apiEndpoints: ApiEndpoint[];
  onChange: (next: FlowStep) => void;
  onDelete: () => void;
  restaurantId?: string;
  flowDefinitionId?: string;
}) {
  const otherStepIds = allStepIds.filter((id) => id !== step.step_id);

  function set(patch: Record<string, unknown>) {
    onChange({ ...step, ...patch });
  }

  const NextTargetField = ({ field, label }: { field: string; label: string }) => (
    <div>
      <label className="block text-xs font-medium text-slate-500">{label}</label>
      <select
        value={(step[field] as string) || ""}
        onChange={(e) => set({ [field]: e.target.value || null })}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
      >
        <option value="">(none)</option>
        {otherStepIds.map((id) => (
          <option key={id} value={id}>{id}</option>
        ))}
      </select>
    </div>
  );

  // Fields the structured panel already owns per type -- everything else on the step
  // object round-trips untouched via the Advanced JSON box below, so per-niche fields
  // this editor doesn't have dedicated widgets for (e.g. dynamic buttons_from sourcing)
  // are never silently dropped.
  const OWNED_FIELDS: Record<string, string[]> = {
    message: ["step_id", "type", "prompt", "back_target"],
    menu_select: ["step_id", "type", "prompt", "static_options", "routes", "next", "back_target"],
    quantity_input: ["step_id", "type", "prompt", "next", "back_target"],
    free_text_input: ["step_id", "type", "prompt", "capture_key", "next", "back_target"],
    confirm_action: ["step_id", "type", "prompt", "next", "back_target"],
    condition: ["step_id", "type", "condition", "then_step", "else_step"],
    delay: ["step_id", "type", "delay_seconds", "next"],
    api_call: ["step_id", "type", "endpoint_id", "capture_key", "next"],
    human_handoff: ["step_id", "type", "message"],
    ai_response: ["step_id", "type", "next"],
  };
  const owned = new Set(OWNED_FIELDS[step.type] || ["step_id", "type"]);
  const extra = Object.fromEntries(Object.entries(step).filter(([k]) => !owned.has(k)));
  const [extraJson, setExtraJson] = useState(JSON.stringify(extra, null, 2));
  const [extraError, setExtraError] = useState<string | null>(null);

  function applyExtraJson() {
    try {
      const parsed = JSON.parse(extraJson);
      onChange({ ...Object.fromEntries(Object.entries(step).filter(([k]) => owned.has(k))), ...parsed } as FlowStep);
      setExtraError(null);
    } catch {
      setExtraError("Not valid JSON -- fix the syntax or your edit won't be applied.");
    }
  }

  return (
    <div className="w-80 shrink-0 space-y-3 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <div>
          <p className="font-mono text-sm font-semibold text-slate-800">{step.step_id}</p>
          <p className="text-xs uppercase tracking-wide text-slate-400">{step.type}</p>
        </div>
        <button onClick={onDelete} className="rounded-md px-2 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-50">Delete step</button>
      </div>

      {(step.type === "message" || step.type === "menu_select" || step.type === "quantity_input" || step.type === "free_text_input" || step.type === "confirm_action") && (
        <div>
          <label className="block text-xs font-medium text-slate-500">Prompt</label>
          <textarea rows={3} value={(step.prompt as string) || ""} onChange={(e) => set({ prompt: e.target.value })} className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs" />
        </div>
      )}

      {step.type === "human_handoff" && (
        <div>
          <label className="block text-xs font-medium text-slate-500">Handoff message</label>
          <textarea rows={3} value={(step.message as string) || ""} onChange={(e) => set({ message: e.target.value })} className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs" />
        </div>
      )}

      {restaurantId && flowDefinitionId &&
        (step.type === "message" || step.type === "menu_select" || step.type === "quantity_input" || step.type === "confirm_action") && (
        <StepImagesEditor restaurantId={restaurantId} flowDefinitionId={flowDefinitionId} stepId={step.step_id} />
      )}

      {step.type === "free_text_input" && (
        <div>
          <label className="block text-xs font-medium text-slate-500">Capture key (where the answer lands in context)</label>
          <input value={(step.capture_key as string) || ""} onChange={(e) => set({ capture_key: e.target.value })} className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs" />
        </div>
      )}

      {step.type === "menu_select" && (
        <div>
          <label className="block text-xs font-medium text-slate-500">Buttons</label>
          <div className="mt-1 space-y-2">
            {((step.static_options as { id: string; title: string; icon?: string | null }[]) || []).map((opt, i) => (
              <div key={i} className="flex items-center gap-1 rounded-md border border-slate-100 p-1.5">
                <input
                  value={opt.title}
                  onChange={(e) => {
                    const options = [...((step.static_options as any[]) || [])];
                    options[i] = { ...options[i], title: e.target.value };
                    set({ static_options: options });
                  }}
                  className="w-20 rounded border border-slate-200 px-1 py-0.5 text-xs"
                  placeholder="title"
                />
                <select
                  value={(step.routes as Record<string, string>)?.[opt.id] || ""}
                  onChange={(e) => set({ routes: { ...(step.routes as Record<string, string>), [opt.id]: e.target.value } })}
                  className="flex-1 rounded border border-slate-200 px-1 py-0.5 text-xs"
                >
                  <option value="">destination...</option>
                  {otherStepIds.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
                <button
                  onClick={() => {
                    const options = ((step.static_options as any[]) || []).filter((_, idx) => idx !== i);
                    const routes = { ...(step.routes as Record<string, string>) };
                    delete routes[opt.id];
                    set({ static_options: options, routes });
                  }}
                  className="text-red-500"
                ><IconX size={11} strokeWidth={2} /></button>
              </div>
            ))}
            <button
              onClick={() => {
                const suffix = Math.random().toString(36).slice(2, 7);
                const options = [...((step.static_options as any[]) || []), { id: `${step.step_id}:${suffix}`, title: "New button", icon: null }];
                set({ static_options: options });
              }}
              className="rounded-md border border-slate-300 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
            >+ Add button</button>
          </div>
          <p className="mt-1 text-[10px] text-slate-400">Drag from the node's bottom handle to set a fallback `next` (used if no button route matches).</p>
        </div>
      )}

      {step.type === "condition" && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs font-medium text-slate-500">Context key</label>
            <input
              value={((step.condition as any)?.context_key) || ""}
              onChange={(e) => set({ condition: { ...(step.condition as object), context_key: e.target.value } })}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Operator</label>
            <select
              value={((step.condition as any)?.operator) || "equals"}
              onChange={(e) => set({ condition: { ...(step.condition as object), operator: e.target.value } })}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs"
            >
              {CONDITION_OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Value</label>
            <input
              value={String(((step.condition as any)?.value) ?? "")}
              onChange={(e) => set({ condition: { ...(step.condition as object), value: e.target.value } })}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs"
            />
          </div>
          <p className="text-[10px] text-slate-400">Connect the node's green (true) and red (false) handles to set then_step / else_step.</p>
        </div>
      )}

      {step.type === "delay" && (
        <div>
          <label className="block text-xs font-medium text-slate-500">Delay seconds (max {MAX_DELAY_SECONDS})</label>
          <input
            type="number" min={0} max={MAX_DELAY_SECONDS} step="0.5"
            value={(step.delay_seconds as number) ?? 0}
            onChange={(e) => set({ delay_seconds: Number(e.target.value) })}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs"
          />
        </div>
      )}

      {step.type === "api_call" && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs font-medium text-slate-500">Endpoint</label>
            <select
              value={(step.endpoint_id as string) || ""}
              onChange={(e) => set({ endpoint_id: e.target.value || null })}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs"
            >
              <option value="">choose an endpoint...</option>
              {apiEndpoints.map((ep) => <option key={ep.id} value={ep.id}>{ep.name}</option>)}
            </select>
            {apiEndpoints.length === 0 && (
              <p className="mt-1 text-[10px] text-amber-600">No API endpoints configured yet -- a Super Admin adds these first.</p>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">Capture key (where the response lands in context)</label>
            <input value={(step.capture_key as string) || ""} onChange={(e) => set({ capture_key: e.target.value })} className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs" />
          </div>
        </div>
      )}

      {step.type === "ai_response" && (
        <p className="text-xs text-slate-500">Placeholder step -- sends a &quot;not configured yet&quot; message until the AI Knowledge Base feature ships. Connect its bottom handle to what should happen next.</p>
      )}

      {(step.type === "condition" ? (
        <div className="grid grid-cols-2 gap-2">
          <NextTargetField field="then_step" label="Then (true)" />
          <NextTargetField field="else_step" label="Else (false)" />
        </div>
      ) : !HAS_NO_NEXT.includes(step.type) ? (
        <NextTargetField field="next" label="Next" />
      ) : null)}

      {step.type !== "condition" && step.type !== "human_handoff" && step.type !== "delay" && step.type !== "api_call" && step.type !== "ai_response" && (
        <NextTargetField field="back_target" label="Back button target" />
      )}

      <details className="rounded-md border border-slate-100 bg-slate-50 p-2">
        <summary className="cursor-pointer text-[11px] font-medium text-slate-600">Advanced fields (raw JSON)</summary>
        {extraError && <p className="mt-1 text-[10px] text-red-600">{extraError}</p>}
        <textarea
          rows={5}
          value={extraJson}
          onChange={(e) => setExtraJson(e.target.value)}
          onBlur={applyExtraJson}
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-[10px]"
        />
      </details>
    </div>
  );
}

// --- Main editor ------------------------------------------------------------------

export interface FlowGraphEditorProps {
  steps: FlowStep[];
  entryStepId: string;
  uiLayout: Record<string, { x: number; y: number }>;
  apiEndpoints: ApiEndpoint[];
  saving: boolean;
  error: string | null;
  onSave: (steps: FlowStep[], entryStepId: string, uiLayout: Record<string, { x: number; y: number }>) => void;
  // Set only when editing a real business's live FlowDefinition (Flow Builder) -- left
  // undefined when editing a NicheTemplate's default_flow_steps (Niches page), which has
  // no restaurant/FlowDefinition row yet to attach a step image against. See
  // StepImagesEditor above for what this gates.
  restaurantId?: string;
  flowDefinitionId?: string;
}

function autoPosition(index: number): { x: number; y: number } {
  const col = index % 4;
  const row = Math.floor(index / 4);
  return { x: 60 + col * 280, y: 60 + row * 160 };
}

function FlowGraphEditorInner({ steps, entryStepId, uiLayout, apiEndpoints, saving, error, onSave, restaurantId, flowDefinitionId }: FlowGraphEditorProps) {
  const [localSteps, setLocalSteps] = useState<FlowStep[]>(steps);
  const [localEntryStepId, setLocalEntryStepId] = useState(entryStepId);
  const [localLayout, setLocalLayout] = useState(uiLayout);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newStepId, setNewStepId] = useState("");
  const [newStepType, setNewStepType] = useState<FlowStepType>("message");
  const [formError, setFormError] = useState<string | null>(null);

  const nodes: Node[] = useMemo(
    () =>
      localSteps.map((step, i) => ({
        id: step.step_id,
        type: "step",
        position: localLayout[step.step_id] || autoPosition(i),
        data: { step, isEntry: step.step_id === localEntryStepId },
        selected: step.step_id === selectedId,
      })),
    [localSteps, localLayout, localEntryStepId, selectedId]
  );

  const edges = useMemo(() => stepsToEdges(localSteps), [localSteps]);

  const updateStep = useCallback((stepId: string, next: FlowStep) => {
    setLocalSteps((prev) => prev.map((s) => (s.step_id === stepId ? next : s)));
  }, []);

  const onNodesChange = useCallback((changes: any[]) => {
    for (const change of changes) {
      if (change.type === "position" && change.position) {
        setLocalLayout((prev) => ({ ...prev, [change.id]: change.position }));
      }
      if (change.type === "select" && change.selected) {
        setSelectedId(change.id);
      }
    }
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    const { source, target, sourceHandle } = connection;
    if (!source || !target) return;
    setLocalSteps((prev) =>
      prev.map((s) => {
        if (s.step_id !== source) return s;
        if (sourceHandle === "then") return { ...s, then_step: target };
        if (sourceHandle === "else") return { ...s, else_step: target };
        if (sourceHandle === "back") return { ...s, back_target: target };
        return { ...s, next: target };
      })
    );
  }, []);

  const onEdgesDelete = useCallback((deleted: Edge[]) => {
    setLocalSteps((prev) =>
      prev.map((s) => {
        const gone = deleted.find((e) => e.source === s.step_id);
        if (!gone) return s;
        const field = (gone.data as { field?: string } | undefined)?.field;
        if (field === "next") return { ...s, next: null };
        if (field === "back_target") return { ...s, back_target: null };
        if (field === "then_step") return { ...s, then_step: null };
        if (field === "else_step") return { ...s, else_step: null };
        return s;
      })
    );
  }, []);

  function addStep() {
    const id = newStepId.trim();
    if (!id) {
      setFormError("Step ID is required.");
      return;
    }
    if (!/^[a-zA-Z0-9_]+$/.test(id)) {
      setFormError("Step ID can only contain letters, numbers, and underscores.");
      return;
    }
    if (localSteps.some((s) => s.step_id === id)) {
      setFormError(`A step called '${id}' already exists.`);
      return;
    }
    setFormError(null);
    setLocalSteps((prev) => [...prev, defaultStepFor(id, newStepType)]);
    setLocalLayout((prev) => ({ ...prev, [id]: autoPosition(localSteps.length) }));
    setNewStepId("");
    setSelectedId(id);
  }

  function deleteStep(id: string) {
    if (id === localEntryStepId) {
      setFormError("Can't delete the entry step -- pick a different entry step first.");
      return;
    }
    setLocalSteps((prev) => prev.filter((s) => s.step_id !== id));
    setLocalLayout((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    if (selectedId === id) setSelectedId(null);
  }

  const selectedStep = localSteps.find((s) => s.step_id === selectedId) || null;
  const menuSelectStepIds = localSteps.filter((s) => s.type === "menu_select").map((s) => s.step_id);

  return (
    <div className="space-y-3">
      {error && <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>}
      {formError && <p className="rounded-lg border border-red-100 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{formError}</p>}

      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-slate-200 bg-white p-3.5 shadow-card">
        <div>
          <label className="block text-xs font-medium text-slate-500">Entry step</label>
          <select
            value={localEntryStepId}
            onChange={(e) => setLocalEntryStepId(e.target.value)}
            className="rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {menuSelectStepIds.length === 0 && <option value={localEntryStepId}>{localEntryStepId}</option>}
            {menuSelectStepIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
          <p className="mt-0.5 text-[10px] text-slate-400">Must be a menu_select step (carries the buttons).</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">New step ID</label>
          <input value={newStepId} onChange={(e) => setNewStepId(e.target.value)} placeholder="e.g. ask_size" className="w-40 rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-500">Type</label>
          <select value={newStepType} onChange={(e) => setNewStepType(e.target.value as FlowStepType)} className="rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
            {STEP_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <button onClick={addStep} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-soft transition-colors hover:border-primary/30 hover:text-primary-dark">+ Add step</button>
        <div className="ml-auto">
          <button
            onClick={() => onSave(localSteps, localEntryStepId, localLayout)}
            disabled={saving}
            className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-white shadow-soft transition-colors hover:bg-primary-dark disabled:opacity-60"
          >
            {saving ? "Saving..." : "Save flow"}
          </button>
        </div>
      </div>

      <div className="flex gap-3">
        <div className="h-[600px] flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/60 shadow-card">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onConnect={onConnect}
            onEdgesDelete={onEdgesDelete}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
        {selectedStep && (
          <StepPropertyPanel
            step={selectedStep}
            allStepIds={localSteps.map((s) => s.step_id)}
            apiEndpoints={apiEndpoints}
            onChange={(next) => updateStep(selectedStep.step_id, next)}
            onDelete={() => deleteStep(selectedStep.step_id)}
            restaurantId={restaurantId}
            flowDefinitionId={flowDefinitionId}
          />
        )}
      </div>
    </div>
  );
}

export function FlowGraphEditor(props: FlowGraphEditorProps) {
  return (
    <ReactFlowProvider>
      <FlowGraphEditorInner {...props} />
    </ReactFlowProvider>
  );
}
