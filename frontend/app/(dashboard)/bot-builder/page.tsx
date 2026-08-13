"use client";

import { useEffect, useState, type FormEvent } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { RequireRestaurant } from "@/components/RequireRestaurant";
import { useCurrentRestaurant } from "@/lib/restaurant";
import type { BotMessage, FaqEntry } from "@/lib/types";

// Mirrors app/services/flow_engine.py::DEFAULT_MESSAGES -- shown as a starting point so
// an admin can see (and tweak) exactly what the bot already says, instead of staring at
// a blank box for anything they haven't customized yet.
const DEFAULT_MESSAGE_TEXT: Record<string, string> = {
  welcome: "👋 Welcome to {{restaurant_name}}! How can we help you today?",
  ask_quantity: "How many of *{{product_name}}* would you like? Reply with a number.",
  ask_coupon: "Have a coupon code? Enter it, reply REDEEM <points> to use loyalty points, or reply SKIP.",
  ask_address: "Great! Please share your delivery address.",
  order_confirmed:
    "✅ Order {{order_number}} confirmed!\nTotal: {{currency}} {{total}}\nEstimated delivery: {{delivery_time}}\nThank you for ordering from {{restaurant_name}}!",
  order_cancelled: "Your order has been cancelled. Send *hi* anytime to start a new order.",
  restaurant_closed: "We're currently closed. Please check back during our opening hours.",
  contact_us: "You can reach {{restaurant_name}} at {{support_number}}.",
  handover: "Connecting you with our team -- someone will reply here shortly.",
  today_special_empty: "No specials are marked right now -- check back soon!",
};

const MESSAGE_GROUPS: {
  title: string;
  icon: string;
  items: { key: string; label: string; hint?: string }[];
}[] = [
  {
    title: "Greeting",
    icon: "👋",
    items: [{ key: "welcome", label: "First reply when a customer says \"hi\"", hint: "{{restaurant_name}}" }],
  },
  {
    title: "While ordering",
    icon: "🛒",
    items: [
      { key: "ask_quantity", label: "After picking an item, asking how many", hint: "{{product_name}}" },
      { key: "ask_coupon", label: "At checkout, asking for a coupon code" },
      { key: "ask_address", label: "Asking where to deliver" },
      {
        key: "order_confirmed",
        label: "Sent right after an order is placed",
        hint: "{{order_number}} {{total}} {{delivery_time}} {{restaurant_name}}",
      },
      { key: "order_cancelled", label: "Sent if the customer cancels at checkout" },
    ],
  },
  {
    title: "Special situations",
    icon: "⚠️",
    items: [
      { key: "restaurant_closed", label: "Sent if no branch is currently open" },
      { key: "today_special_empty", label: "Sent when \"Today's Special\" has nothing marked yet" },
      { key: "contact_us", label: "Sent for \"Contact Us\" (only if the branch has no phone set)", hint: "{{restaurant_name}} {{support_number}}" },
      { key: "handover", label: "Sent when the chat is handed over to a staff member" },
    ],
  },
];

function BotBuilderForRestaurant({ restaurantId }: { restaurantId: string }) {
  const { hasFeature } = useCurrentRestaurant();
  const canManageFaq = hasFeature("faq_autoresponder");
  const [messages, setMessages] = useState<BotMessage[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState<string | null>(null);

  const [faqEntries, setFaqEntries] = useState<FaqEntry[]>([]);
  const [faqKeywords, setFaqKeywords] = useState("");
  const [faqAnswer, setFaqAnswer] = useState("");
  const [creatingFaq, setCreatingFaq] = useState(false);

  async function load() {
    try {
      const [msgs, faqs] = await Promise.all([
        apiFetch<BotMessage[]>(`/restaurants/${restaurantId}/bot/messages`),
        apiFetch<FaqEntry[]>(`/restaurants/${restaurantId}/faq`),
      ]);
      setMessages(msgs);
      setFaqEntries(faqs);
      const byKey = Object.fromEntries(msgs.map((m) => [m.key, m.content]));
      setDrafts(Object.fromEntries(Object.keys(DEFAULT_MESSAGE_TEXT).map((key) => [key, byKey[key] ?? DEFAULT_MESSAGE_TEXT[key]])));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load bot configuration");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  function isCustomized(key: string): boolean {
    return messages.some((m) => m.key === key);
  }

  function isDirty(key: string): boolean {
    const saved = messages.find((m) => m.key === key)?.content ?? DEFAULT_MESSAGE_TEXT[key];
    return (drafts[key] ?? "") !== saved;
  }

  async function saveMessage(key: string) {
    setSaving(key);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/bot/messages`, {
        method: "PUT",
        body: JSON.stringify({ key, content: drafts[key] || "" }),
      });
      await load();
      setJustSaved(key);
      setTimeout(() => setJustSaved(null), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save message");
    } finally {
      setSaving(null);
    }
  }

  async function handleCreateFaq(e: FormEvent) {
    e.preventDefault();
    setCreatingFaq(true);
    setError(null);
    try {
      await apiFetch(`/restaurants/${restaurantId}/faq`, {
        method: "POST",
        body: JSON.stringify({
          trigger_keywords: faqKeywords.split(",").map((k) => k.trim()).filter(Boolean),
          answer: faqAnswer,
          display_order: faqEntries.length,
        }),
      });
      setFaqKeywords("");
      setFaqAnswer("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create FAQ entry");
    } finally {
      setCreatingFaq(false);
    }
  }

  async function deleteFaq(id: string) {
    try {
      await apiFetch(`/restaurants/${restaurantId}/faq/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete FAQ entry");
    }
  }

  return (
    <div className="space-y-8 pb-16">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Bot Builder</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Everything your WhatsApp bot says and does lives here — no code, ever. Each message below shows what the
          bot already sends; edit it to make it yours, or leave it as-is. Looking for the main menu buttons? That
          moved to <a href="/home-builder" className="font-medium text-primary hover:underline">Home Builder</a>.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <section className="space-y-5">
        {MESSAGE_GROUPS.map((group) => (
          <div key={group.title} className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
              <span className="text-lg">{group.icon}</span>
              <h2 className="text-sm font-semibold text-slate-800">{group.title}</h2>
            </div>
            <div className="divide-y divide-slate-100">
              {group.items.map(({ key, label, hint }) => (
                <div key={key} className="p-5">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <label className="text-sm font-medium text-slate-700">{label}</label>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        isCustomized(key) ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"
                      }`}
                    >
                      {isCustomized(key) ? "Customized" : "Using default"}
                    </span>
                  </div>
                  <textarea
                    rows={2}
                    value={drafts[key] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <div className="mt-2 flex items-center gap-3">
                    <button
                      onClick={() => saveMessage(key)}
                      disabled={saving === key || !isDirty(key)}
                      className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                    >
                      {saving === key ? "Saving..." : "Save"}
                    </button>
                    {justSaved === key && <span className="text-xs font-medium text-emerald-600">Saved ✓</span>}
                    {hint && <span className="text-[11px] text-slate-400">Variables: {hint}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">Quick answers (FAQ)</h2>
          <p className="text-xs text-slate-500">
            Rule-based, free -- no AI subscription. When a customer types a free-text question, it&apos;s matched
            against keywords here (and menu item tags) before ever handing the chat to a human.
          </p>
        </div>
        {!canManageFaq && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            The FAQ Auto-Responder isn&apos;t included in this business&apos;s plan -- contact support to upgrade.
            Existing entries below are unaffected.
          </p>
        )}
        {canManageFaq && (
        <form onSubmit={handleCreateFaq} className="flex flex-wrap items-end gap-3 rounded-lg bg-slate-50 p-3">
          <div>
            <label className="block text-xs font-medium text-slate-500">Trigger keywords (comma separated)</label>
            <input
              required
              value={faqKeywords}
              onChange={(e) => setFaqKeywords(e.target.value)}
              placeholder="delivery time, how long"
              className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div className="flex-1">
            <label className="block text-xs font-medium text-slate-500">Answer</label>
            <input required value={faqAnswer} onChange={(e) => setFaqAnswer(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          </div>
          <button type="submit" disabled={creatingFaq} className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
            {creatingFaq ? "Adding..." : "Add FAQ"}
          </button>
        </form>
        )}

        <div className="space-y-2">
          {faqEntries.map((f) => (
            <div key={f.id} className="flex items-center justify-between rounded-lg border border-slate-100 bg-white px-4 py-2">
              <div>
                <p className="text-xs text-slate-400">{f.trigger_keywords.join(", ")}</p>
                <p className="text-sm">{f.answer}</p>
              </div>
              <button onClick={() => deleteFaq(f.id)} className="text-xs font-medium text-red-600 hover:text-red-700">
                Remove
              </button>
            </div>
          ))}
          {faqEntries.length === 0 && <p className="text-sm text-slate-400">No FAQ entries yet.</p>}
        </div>
      </section>
    </div>
  );
}

export default function BotBuilderPage() {
  return <RequireRestaurant>{(restaurantId) => <BotBuilderForRestaurant restaurantId={restaurantId} />}</RequireRestaurant>;
}
