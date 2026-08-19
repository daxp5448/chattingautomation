"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useLiveSocket } from "@/lib/useLiveSocket";
import type { ConversationSummary, Message, Restaurant } from "@/lib/types";
import { IconMessageCircle, IconCheckCircle, IconSparkles } from "@/components/icons";

// --- Legacy engine: bot-couldn't-answer handoff (unchanged since Phase 1) ----------

function LegacyLiveChat({ restaurantId, canReply }: { restaurantId: string; canReply: boolean }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await apiFetch<ConversationSummary[]>(`/restaurants/${restaurantId}/conversations`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load conversations");
    }
  }, [restaurantId]);

  const loadMessages = useCallback(
    async (customerId: string) => {
      try {
        setMessages(await apiFetch<Message[]>(`/restaurants/${restaurantId}/conversations/${customerId}/messages`));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load messages");
      }
    },
    [restaurantId]
  );

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (selected) loadMessages(selected);
  }, [selected, loadMessages]);

  useLiveSocket(restaurantId, (event) => {
    if (event.type === "handover") loadConversations();
    if (event.type === "staff_reply" && selected && event.customer_id === selected) loadMessages(selected);
  });

  async function sendReply(e: FormEvent) {
    e.preventDefault();
    if (!selected || !reply.trim()) return;
    setSending(true);
    try {
      await apiFetch(`/restaurants/${restaurantId}/conversations/${selected}/messages`, {
        method: "POST",
        body: JSON.stringify({ body: reply }),
      });
      setReply("");
      await loadMessages(selected);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send reply");
    } finally {
      setSending(false);
    }
  }

  async function resolve() {
    if (!selected) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/conversations/${selected}/resolve`, { method: "POST" });
      setSelected(null);
      setMessages([]);
      await loadConversations();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to resolve conversation");
    }
  }

  return (
    <div className="space-y-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="flex gap-4">
        <div className="w-72 shrink-0 space-y-2">
          {conversations.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => setSelected(c.customer_id)}
              className={`w-full rounded-xl border p-3 text-left text-sm shadow-sm transition ${
                selected === c.customer_id ? "border-primary bg-primary/5" : "border-slate-200 bg-white hover:bg-slate-50"
              }`}
            >
              <p className="flex items-center gap-1.5 font-medium text-slate-800">
                <IconMessageCircle size={13} className="text-slate-400" /> {c.customer_name || c.customer_phone}
              </p>
              <p className="truncate text-xs text-slate-400">{c.last_message_preview}</p>
            </button>
          ))}
          {conversations.length === 0 && (
            <p className="flex flex-col items-center gap-1.5 rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400">
              <IconSparkles size={16} className="text-slate-300" />
              No conversations waiting — nice work!
            </p>
          )}
        </div>

        <div className="flex-1 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          {!selected ? (
            <div className="flex h-64 items-center justify-center text-sm text-slate-400">Select a conversation to see the transcript.</div>
          ) : (
            <div className="flex h-full flex-col">
              <div className="mb-3 flex items-center justify-between border-b border-slate-100 pb-3">
                <p className="text-sm font-semibold text-slate-800">Transcript</p>
                <button onClick={resolve} className="flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                  <IconCheckCircle size={13} /> Resolve (back to bot)
                </button>
              </div>
              <div className="mb-3 max-h-96 space-y-2 overflow-y-auto rounded-lg bg-slate-50 p-3">
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={`max-w-[80%] rounded-lg px-3 py-2 text-sm shadow-sm ${
                      m.direction === "inbound" ? "bg-white text-slate-800" : "ml-auto bg-emerald-100 text-emerald-900"
                    }`}
                  >
                    <p>{m.body}</p>
                    <p className="mt-1 text-[10px] text-slate-400">
                      {m.sent_by} · {new Date(m.created_at).toLocaleTimeString()}
                    </p>
                  </div>
                ))}
                {messages.length === 0 && <p className="text-sm text-slate-400">No messages yet.</p>}
              </div>
              {canReply ? (
                <form onSubmit={sendReply} className="mt-auto flex gap-2">
                  <input
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="Type a reply..."
                    className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <button type="submit" disabled={sending} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-60">
                    Send
                  </button>
                </form>
              ) : (
                <p className="mt-auto rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Human handoff replies aren&apos;t included in this business&apos;s plan -- contact support to
                  upgrade.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Generic engine: HUMAN_HANDOFF step conversations ------------------------------
// Same shape as LegacyLiveChat above, pointed at /generic-conversations instead of
// /conversations, and "Resume automation" instead of "Resolve" (see
// app/api/v1/routers/generic_conversations.py -- clears is_handed_over and resets
// current_step back to the flow's entry step, rather than the legacy engine's simpler
// resolve-and-forget).

function GenericLiveChat({ restaurantId, canReply }: { restaurantId: string; canReply: boolean }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await apiFetch<ConversationSummary[]>(`/restaurants/${restaurantId}/generic-conversations`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load conversations");
    }
  }, [restaurantId]);

  const loadMessages = useCallback(
    async (customerId: string) => {
      try {
        setMessages(await apiFetch<Message[]>(`/restaurants/${restaurantId}/generic-conversations/${customerId}/messages`));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load messages");
      }
    },
    [restaurantId]
  );

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (selected) loadMessages(selected);
  }, [selected, loadMessages]);

  useLiveSocket(restaurantId, (event) => {
    if (event.type === "generic_handover") loadConversations();
    if (event.type === "generic_inbound_while_handed_off" && selected && event.customer_id === selected) loadMessages(selected);
    if (event.type === "generic_staff_reply" && selected && event.customer_id === selected) loadMessages(selected);
  });

  async function sendReply(e: FormEvent) {
    e.preventDefault();
    if (!selected || !reply.trim()) return;
    setSending(true);
    try {
      await apiFetch(`/restaurants/${restaurantId}/generic-conversations/${selected}/messages`, {
        method: "POST",
        body: JSON.stringify({ body: reply }),
      });
      setReply("");
      await loadMessages(selected);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send reply");
    } finally {
      setSending(false);
    }
  }

  async function resume() {
    if (!selected) return;
    try {
      await apiFetch(`/restaurants/${restaurantId}/generic-conversations/${selected}/resume`, { method: "POST" });
      setSelected(null);
      setMessages([]);
      await loadConversations();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to resume automation");
    }
  }

  return (
    <div className="space-y-4">
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="flex gap-4">
        <div className="w-72 shrink-0 space-y-2">
          {conversations.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => setSelected(c.customer_id)}
              className={`w-full rounded-xl border p-3 text-left text-sm shadow-sm transition ${
                selected === c.customer_id ? "border-primary bg-primary/5" : "border-slate-200 bg-white hover:bg-slate-50"
              }`}
            >
              <p className="flex items-center gap-1.5 font-medium text-slate-800">
                <IconMessageCircle size={13} className="text-slate-400" /> {c.customer_name || c.customer_phone}
              </p>
              <p className="truncate text-xs text-slate-400">{c.last_message_preview}</p>
            </button>
          ))}
          {conversations.length === 0 && (
            <p className="flex flex-col items-center gap-1.5 rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400">
              <IconSparkles size={16} className="text-slate-300" />
              No conversations waiting — nice work!
            </p>
          )}
        </div>

        <div className="flex-1 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          {!selected ? (
            <div className="flex h-64 items-center justify-center text-sm text-slate-400">Select a conversation to see the transcript.</div>
          ) : (
            <div className="flex h-full flex-col">
              <div className="mb-3 flex items-center justify-between border-b border-slate-100 pb-3">
                <p className="text-sm font-semibold text-slate-800">Transcript</p>
                <button onClick={resume} className="flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">
                  <IconCheckCircle size={13} /> Resume automation
                </button>
              </div>
              <div className="mb-3 max-h-96 space-y-2 overflow-y-auto rounded-lg bg-slate-50 p-3">
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={`max-w-[80%] rounded-lg px-3 py-2 text-sm shadow-sm ${
                      m.direction === "inbound" ? "bg-white text-slate-800" : "ml-auto bg-emerald-100 text-emerald-900"
                    }`}
                  >
                    <p>{m.body}</p>
                    <p className="mt-1 text-[10px] text-slate-400">
                      {m.sent_by} · {new Date(m.created_at).toLocaleTimeString()}
                    </p>
                  </div>
                ))}
                {messages.length === 0 && <p className="text-sm text-slate-400">No messages yet.</p>}
              </div>
              {canReply ? (
                <form onSubmit={sendReply} className="mt-auto flex gap-2">
                  <input
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="Type a reply..."
                    className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <button type="submit" disabled={sending} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-60">
                    Send
                  </button>
                </form>
              ) : (
                <p className="mt-auto rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Human handoff replies aren&apos;t included in this business&apos;s plan -- contact support to
                  upgrade.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LiveChatForRestaurant({ restaurantId }: { restaurantId: string }) {
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Restaurant>(`/restaurants/${restaurantId}`)
      .then(setRestaurant)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load business"));
  }, [restaurantId]);

  if (error) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!restaurant) return <p className="text-sm text-slate-500">Loading...</p>;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Live Chat</h1>
        <p className="text-sm text-slate-500">
          {restaurant.uses_generic_engine
            ? "Conversations paused for a human -- a flow's Human Handoff step sent them here, waiting on you."
            : "Conversations the bot couldn't answer on its own — rule-based matching found nothing, so it's waiting on you."}
        </p>
      </div>
      {restaurant.uses_generic_engine ? (
        <GenericLiveChat restaurantId={restaurantId} canReply={restaurant.enabled_features === null || restaurant.enabled_features.includes("live_chat_handoff")} />
      ) : (
        <LegacyLiveChat restaurantId={restaurantId} canReply={restaurant.enabled_features === null || restaurant.enabled_features.includes("live_chat_handoff")} />
      )}
    </div>
  );
}

export default function LiveChatPage() {
  return <RequireRestaurant>{(restaurantId) => <LiveChatForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
