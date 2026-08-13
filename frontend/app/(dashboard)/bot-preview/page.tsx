"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import type { FlowDefinitionFull, FlowStep, HomeButton, MessageEntry, Restaurant } from "@/lib/types";

const INSERTABLE_VARIABLES = [
  "business_name", "customer_name", "date", "time", "order_id", "booking_id",
  "quantity", "address", "service_name", "product_name", "total",
];

const STEP_TYPE_LABELS: Record<string, string> = {
  message: "Info message",
  menu_select: "Menu / buttons",
  quantity_input: "Quantity prompt",
  free_text_input: "Ask a question",
  confirm_action: "Confirmation step",
  human_handoff: "Talk to a Human",
  send_whatsapp_flow: "WhatsApp Flow",
};

// Raw Graph API payload shapes (see backend/app/services/whatsapp_client.py::OutboundMessage)
// -- rendered directly, so "what the preview shows" can never drift from what a real
// customer's WhatsApp actually receives.
interface PreviewMessage {
  type: string;
  text?: { body: string };
  image?: { link: string; caption?: string };
  document?: { link: string; filename: string; caption?: string };
  location?: { latitude: number; longitude: number; name?: string; address?: string };
  interactive?: {
    type: string;
    body?: { text: string };
    action?: {
      buttons?: { reply: { id: string; title: string } }[];
      button?: string;
      sections?: { title: string; rows: { id: string; title: string; description?: string }[] }[];
      parameters?: { flow_cta?: string };
    };
  };
}

interface Turn {
  from: "customer" | "bot";
  messages?: PreviewMessage[];
  text?: string;
}

function BotBubble({ message, onOption }: { message: PreviewMessage; onOption: (id: string, title: string) => void }) {
  const base = "max-w-[85%] rounded-2xl rounded-tl-none bg-white px-3 py-2 text-[13px] leading-snug text-slate-800 shadow-sm";

  if (message.type === "text") return <div className={base}>{message.text?.body}</div>;
  if (message.type === "image") {
    return (
      <div className={`${base} max-w-[85%] space-y-2 p-2`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={message.image?.link} alt="" className="max-h-52 w-full rounded-lg object-cover" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
        {message.image?.caption && <p className="whitespace-pre-wrap px-1 pb-1">{message.image.caption}</p>}
      </div>
    );
  }
  if (message.type === "document") {
    return <div className={base}>📄 {message.document?.filename}{message.document?.caption && <p className="mt-1 text-xs text-slate-500">{message.document.caption}</p>}</div>;
  }
  if (message.type === "location") {
    return <div className={base}>📍 {message.location?.name || "Location"}<p className="text-xs text-slate-500">{message.location?.address}</p></div>;
  }
  if (message.type === "interactive") {
    const interactive = message.interactive!;
    if (interactive.type === "button") {
      return (
        <div className="space-y-1.5">
          <div className={base}>{interactive.body?.text}</div>
          <div className="flex flex-col gap-1.5">
            {interactive.action?.buttons?.map((b) => (
              <button key={b.reply.id} onClick={() => onOption(b.reply.id, b.reply.title)}
                className="max-w-[85%] rounded-full border border-emerald-300 bg-white px-3 py-1.5 text-left text-xs font-medium text-emerald-700 shadow-sm hover:bg-emerald-50">
                {b.reply.title}
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (interactive.type === "list") {
      const rows = interactive.action?.sections?.[0]?.rows ?? [];
      return (
        <div className="space-y-1.5">
          <div className={base}>{interactive.body?.text}</div>
          <div className="max-w-[85%] divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white shadow-sm">
            {rows.map((r) => (
              <button key={r.id} onClick={() => onOption(r.id, r.title)} className="block w-full px-3 py-2 text-left text-xs hover:bg-emerald-50">
                <span className="font-medium text-slate-800">{r.title}</span>
                {r.description && <span className="block text-[11px] text-slate-500">{r.description}</span>}
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (interactive.type === "location_request_message") {
      return <div className={base}>📍 {interactive.body?.text} <span className="text-xs text-slate-400">(native location share)</span></div>;
    }
    if (interactive.type === "flow") {
      return <div className={base}>{interactive.body?.text} <span className="mt-1 block text-xs text-emerald-700">[Opens WhatsApp Flow: {interactive.action?.parameters?.flow_cta}]</span></div>;
    }
  }
  return <div className={base}>[Unsupported preview message type: {message.type}]</div>;
}

function WhatsAppPhone({
  businessName, turns, loading, sessionStarted, input, setInput, onSend, onOption, onStart,
}: {
  businessName: string; turns: Turn[]; loading: boolean; sessionStarted: boolean;
  input: string; setInput: (v: string) => void; onSend: () => void; onOption: (id: string, title: string) => void; onStart: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [turns]);

  return (
    <div className="sticky top-6 mx-auto w-full max-w-sm overflow-hidden rounded-[2rem] border-8 border-slate-900 bg-slate-900 shadow-xl">
      <div className="overflow-hidden rounded-[1.4rem] bg-[#e5ddd5]">
        <div className="flex items-center gap-2 bg-emerald-700 px-3 py-2.5 text-white">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500 text-xs font-bold">
            {businessName.slice(0, 1).toUpperCase() || "?"}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium leading-tight">{businessName || "Business"}</p>
            <p className="text-[11px] text-emerald-100">{loading ? "typing…" : "online"}</p>
          </div>
        </div>
        <div ref={scrollRef} className="flex h-[460px] flex-col gap-2 overflow-y-auto px-3 py-3">
          {turns.length === 0 && (
            <p className="m-auto max-w-[80%] text-center text-xs text-slate-500">
              Tap &quot;Start Preview&quot;, or select a step on the left and tap &quot;Preview This Step&quot;.
            </p>
          )}
          {turns.map((turn, i) =>
            turn.from === "customer" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-tr-none bg-[#dcf8c6] px-3 py-2 text-[13px] text-slate-800 shadow-sm">{turn.text}</div>
              </div>
            ) : (
              <div key={i} className="flex flex-col gap-2">
                {turn.messages?.map((m, j) => <BotBubble key={j} message={m} onOption={onOption} />)}
              </div>
            )
          )}
          {loading && <div className="text-xs text-slate-400">Bot is typing…</div>}
        </div>
        <div className="flex gap-2 border-t border-slate-300 bg-white p-2">
          {!sessionStarted ? (
            <button onClick={onStart} disabled={loading} className="w-full rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
              ▶ Start Preview
            </button>
          ) : (
            <>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onSend()}
                placeholder="Type a message..."
                disabled={loading}
                className="flex-1 rounded-full border border-slate-300 px-3 py-1.5 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:bg-slate-50"
              />
              <button onClick={onSend} disabled={loading || !input.trim()} className="rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40">
                Send
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StepEditor({
  restaurantId, entry, flow, onSaved,
}: {
  restaurantId: string; entry: MessageEntry; flow: FlowDefinitionFull; onSaved: () => void;
}) {
  const [draftText, setDraftText] = useState(entry.text);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [buttons, setButtons] = useState<HomeButton[] | null>(null);
  const [buttonsLoading, setButtonsLoading] = useState(false);

  const step = flow.steps.find((s) => s.step_id === entry.step_id) as FlowStep | undefined;
  const buttonsAreStatic = step?.buttons_from === "static";
  const dynamicSource = typeof step?.buttons_from === "string" && step.buttons_from !== "static" ? step.buttons_from : null;
  const isEntryStep = flow.entry_step_id === entry.step_id;

  useEffect(() => {
    setDraftText(entry.text);
    setSaved(false);
    setError(null);
  }, [entry]);

  useEffect(() => {
    if (!buttonsAreStatic) {
      setButtons(null);
      return;
    }
    setButtonsLoading(true);
    apiFetch<{ buttons: HomeButton[] }>(`/restaurants/${restaurantId}/flow/steps/${encodeURIComponent(entry.step_id)}/buttons`)
      .then((r) => setButtons(r.buttons))
      .catch(() => setButtons([]))
      .finally(() => setButtonsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.step_id, buttonsAreStatic]);

  const isDirty = draftText !== entry.text;

  async function saveText() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/flow/messages/${encodeURIComponent(entry.step_id)}`, {
        method: "PATCH",
        body: JSON.stringify({ text: draftText }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function restoreDefault() {
    setSaving(true);
    setError(null);
    try {
      const restored = await apiFetch<MessageEntry>(`/restaurants/${restaurantId}/flow/messages/${encodeURIComponent(entry.step_id)}/restore-default`, { method: "POST" });
      setDraftText(restored.text);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to restore default");
    } finally {
      setSaving(false);
    }
  }

  async function saveButtons(next: HomeButton[]) {
    setButtons(next);
    try {
      const result = await apiFetch<{ buttons: HomeButton[] }>(`/restaurants/${restaurantId}/flow/steps/${encodeURIComponent(entry.step_id)}/buttons`, {
        method: "PATCH",
        body: JSON.stringify({ buttons: next.map((b) => ({ id: b.id, title: b.title, icon: b.icon, visible: b.visible, destination_step_id: b.destination_step_id })) }),
      });
      setButtons(result.buttons);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save buttons");
    }
  }

  const allStepIds = flow.steps.map((s) => s.step_id);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-slate-400">{entry.message_key}</p>
          <p className="text-xs text-slate-500">{STEP_TYPE_LABELS[entry.step_type] ?? entry.step_type}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${entry.is_customized ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
          {entry.is_customized === null ? "Niche default" : entry.is_customized ? "Customized" : "Using default"}
        </span>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}

      {/* --- Message text --- */}
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Message</h3>
        <textarea
          rows={4}
          value={draftText}
          onChange={(e) => setDraftText(e.target.value)}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-slate-400">+ Insert:</span>
          {INSERTABLE_VARIABLES.map((v) => (
            <button key={v} onClick={() => setDraftText((t) => `${t}{{${v}}}`)} className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-100">
              {`{{${v}}}`}
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span>{draftText.length} characters</span>
          {isDirty && <span className="font-medium text-amber-600">● Unsaved changes</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={saveText} disabled={saving || !isDirty} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40">
            {saving ? "Saving..." : "Save"}
          </button>
          {isDirty && (
            <button onClick={() => setDraftText(entry.text)} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
              Discard Changes
            </button>
          )}
          {entry.is_customized && (
            <button onClick={restoreDefault} disabled={saving} className="rounded-md border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-40">
              Restore Default
            </button>
          )}
          {saved && <span className="text-xs font-medium text-emerald-600">Saved ✓</span>}
        </div>
      </section>

      {/* --- Media (only meaningful on the entry/welcome step; other steps' images come
           from the catalog item/category they display, edited via Catalog/Media Library) --- */}
      {isEntryStep && <WelcomeMediaEditor restaurantId={restaurantId} />}
      {!isEntryStep && (dynamicSource === "categories" || dynamicSource === "items") && (
        <section className="space-y-1 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Media</h3>
          <p>
            This step&apos;s images come from your {dynamicSource === "categories" ? "category" : "product"} photos — edit them in{" "}
            <a href="/menu" className="font-medium text-primary hover:underline">Catalog</a> or the{" "}
            <a href="/media-library" className="font-medium text-primary hover:underline">Media Library</a>.
          </p>
        </section>
      )}

      {/* --- Buttons --- */}
      {buttonsAreStatic && (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Buttons</h3>
          {buttonsLoading && <p className="text-xs text-slate-400">Loading...</p>}
          <div className="space-y-2">
            {(buttons ?? []).map((b, i) => (
              <div key={b.id} className="rounded-lg border border-slate-200 bg-white p-2.5">
                <div className="flex items-center gap-2">
                  <input
                    value={b.title}
                    onChange={(e) => {
                      const next = [...(buttons ?? [])];
                      next[i] = { ...b, title: e.target.value };
                      setButtons(next);
                    }}
                    onBlur={() => saveButtons(buttons ?? [])}
                    className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs"
                  />
                  <label className="flex items-center gap-1 text-[11px] text-slate-500">
                    <input type="checkbox" checked={b.visible} onChange={(e) => { const next = [...(buttons ?? [])]; next[i] = { ...b, visible: e.target.checked }; saveButtons(next); }} />
                    Visible
                  </label>
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                  <span>→</span>
                  <select
                    value={b.destination_step_id}
                    onChange={(e) => { const next = [...(buttons ?? [])]; next[i] = { ...b, destination_step_id: e.target.value }; saveButtons(next); }}
                    className="rounded-md border border-slate-300 px-1.5 py-1 text-[11px]"
                  >
                    {allStepIds.map((id) => <option key={id} value={id}>{id}</option>)}
                  </select>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
      {dynamicSource && dynamicSource !== "categories" && dynamicSource !== "items" && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          This step&apos;s options are generated from your {dynamicSource} — nothing to edit here directly.
        </p>
      )}
    </div>
  );
}

function WelcomeMediaEditor({ restaurantId }: { restaurantId: string }) {
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`).then((r) => { setRestaurant(r); setUrl(r.cover_image_url ?? ""); });
  }, [restaurantId]);

  async function save() {
    setSaving(true);
    try {
      await apiFetch(`/restaurants/${restaurantId}`, { method: "PATCH", body: JSON.stringify({ cover_image_url: url || null }) });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Media (Business Cover Image)</h3>
      <p className="text-[11px] text-slate-400">
        The Welcome message and any step with no catalog image of its own falls back to this business-wide cover photo.
      </p>
      {restaurant?.cover_image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={restaurant.cover_image_url} alt="" className="h-28 w-full rounded-lg border border-slate-200 object-cover" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
      )}
      <div className="flex gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs" />
        <button onClick={save} disabled={saving} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
      {saved && <span className="text-xs font-medium text-emerald-600">Saved ✓</span>}
    </section>
  );
}

function BotPreviewForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [flow, setFlow] = useState<FlowDefinitionFull | null>(null);
  const [messages, setMessages] = useState<MessageEntry[]>([]);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  async function loadAll() {
    try {
      const [r, f, m] = await Promise.all([
        apiFetch<Restaurant>(`/restaurants/${restaurantId}`),
        apiFetch<FlowDefinitionFull>(`/restaurants/${restaurantId}/flow`),
        apiFetch<MessageEntry[]>(`/restaurants/${restaurantId}/flow/messages`),
      ]);
      setRestaurant(r);
      setFlow(f);
      setMessages(m);
      setSelectedStepId((prev) => prev ?? f.entry_step_id);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "This business has no flow configured yet.");
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  async function refreshMessages() {
    try {
      const m = await apiFetch<MessageEntry[]>(`/restaurants/${restaurantId}/flow/messages`);
      setMessages(m);
      const f = await apiFetch<FlowDefinitionFull>(`/restaurants/${restaurantId}/flow`);
      setFlow(f);
    } catch {
      // best-effort refresh
    }
  }

  async function sendTurn(body: { kind: string; text?: string; reply_id?: string }, customerLabel: string) {
    setPreviewLoading(true);
    setPreviewError(null);
    setTurns((t) => [...t, { from: "customer", text: customerLabel }]);
    try {
      const result = await apiFetch<{ session_id: string; messages: PreviewMessage[] }>(`/restaurants/${restaurantId}/flow/preview`, {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, ...body }),
      });
      setSessionId(result.session_id);
      setTurns((t) => [...t, { from: "bot", messages: result.messages }]);
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function previewThisStep(stepId: string) {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const result = await apiFetch<{ session_id: string; messages: PreviewMessage[] }>(`/restaurants/${restaurantId}/flow/preview/jump`, {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, step_id: stepId }),
      });
      setSessionId(result.session_id);
      setTurns([{ from: "bot", messages: result.messages }]);
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleStart() {
    setTurns([]);
    setSessionId(null);
    sendTurn({ kind: "text", text: "hi" }, "hi");
  }

  async function handleRestart() {
    setPreviewLoading(true);
    try {
      if (sessionId) await apiFetch(`/restaurants/${restaurantId}/flow/preview/reset?session_id=${encodeURIComponent(sessionId)}`, { method: "POST" });
    } catch {
      // best-effort
    }
    setSessionId(null);
    setTurns([]);
    setPreviewLoading(false);
    sendTurn({ kind: "text", text: "hi" }, "hi");
  }

  function handleOption(id: string, title: string) {
    if (previewLoading) return;
    sendTurn({ kind: "button_reply", reply_id: id }, title);
  }

  function handleSend() {
    if (!input.trim() || previewLoading) return;
    const text = input.trim();
    setInput("");
    sendTurn({ kind: "text", text }, text);
  }

  const selectedEntry = useMemo(() => messages.find((m) => m.step_id === selectedStepId) ?? null, [messages, selectedStepId]);

  if (loadError) {
    return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{loadError}</p>;
  }
  if (!flow) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-16">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Bot Preview</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            {restaurant?.name} → Customer Journey. Edit on the left, see the exact WhatsApp result on the right — same live
            configuration real customers get.
          </p>
        </div>
        <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">● LIVE</span>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
        🧪 Every save here goes live immediately (no Draft/Publish staging yet) — but the preview itself never creates a
        real customer, order, payment, or notification.
      </div>

      {previewError && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{previewError}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        {/* LEFT: editor */}
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-4 py-2.5">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Customer Journey</h2>
            </div>
            <nav className="max-h-64 overflow-y-auto p-2">
              {messages.map((m) => (
                <div key={m.step_id} className={`flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-sm ${selectedStepId === m.step_id ? "bg-primary/10 font-medium text-primary" : "text-slate-600 hover:bg-slate-50"}`}>
                  <button onClick={() => setSelectedStepId(m.step_id)} className="flex-1 truncate text-left">
                    {m.step_id === flow.entry_step_id ? "● " : ""}{m.step_id}
                  </button>
                  <button onClick={() => previewThisStep(m.step_id)} disabled={previewLoading} className="shrink-0 text-[11px] text-slate-400 hover:text-primary disabled:opacity-40">
                    👁 Preview
                  </button>
                </div>
              ))}
            </nav>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            {selectedEntry ? (
              <StepEditor key={selectedEntry.step_id} restaurantId={restaurantId} entry={selectedEntry} flow={flow} onSaved={refreshMessages} />
            ) : (
              <p className="text-sm text-slate-400">Select a step to edit.</p>
            )}
          </div>

          <div className="flex flex-wrap gap-2 text-xs">
            <a href="/flow-builder" className="rounded-md border border-slate-300 px-3 py-1.5 font-medium text-slate-600 hover:bg-slate-50">🧭 Open Visual Flow</a>
            <a href="/messages" className="rounded-md border border-slate-300 px-3 py-1.5 font-medium text-slate-600 hover:bg-slate-50">📝 Open Messages</a>
          </div>
        </div>

        {/* RIGHT: phone preview */}
        <div>
          <WhatsAppPhone
            businessName={restaurant?.name ?? ""}
            turns={turns}
            loading={previewLoading}
            sessionStarted={sessionId !== null}
            input={input}
            setInput={setInput}
            onSend={handleSend}
            onOption={handleOption}
            onStart={handleStart}
          />
          {sessionId && (
            <div className="mt-3 flex justify-center">
              <button onClick={handleRestart} disabled={previewLoading} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm hover:bg-slate-50 disabled:opacity-50">
                ↻ Restart
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BotPreviewPage() {
  return <RequireRestaurant>{(restaurantId) => <BotPreviewForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
