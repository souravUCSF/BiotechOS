"use client";

import { useEffect, useRef, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  tppBuilderGreeting,
  tppBuilderChat,
  tppBuilderFinalize,
  type ChatMessage,
} from "@/lib/api";

export function TppBuilderDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (version: number) => void;
}) {
  const { programId } = useProgram();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    tppBuilderGreeting().then((g) =>
      setMessages([{ role: "assistant", content: g }]),
    );
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  async function send() {
    if (!input.trim()) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: input.trim() }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const r = await tppBuilderChat(next, programId, apiKey);
      setMessages([...next, { role: "assistant", content: r.reply }]);
    } finally {
      setBusy(false);
    }
  }

  async function finalize() {
    setFinalizing(true);
    try {
      const r = await tppBuilderFinalize(messages, programId, apiKey);
      onCreated(r.version);
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="flex h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-neutral-700 bg-neutral-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-neutral-800 p-4">
          <div>
            <h2 className="text-lg font-semibold">Build a new TPP with Opus</h2>
            <p className="text-xs text-neutral-500">
              A guided conversation to design an effective TPP for this program.
            </p>
          </div>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-300">✕</button>
        </div>

        <div className="border-b border-neutral-800 p-3">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Anthropic API key (optional — enables live Opus reasoning)"
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm"
          />
        </div>

        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : ""}>
              <div
                className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                  m.role === "user"
                    ? "bg-emerald-700 text-white"
                    : "bg-neutral-900 text-neutral-200"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {busy && <div className="text-xs text-neutral-500">TPP Builder is thinking…</div>}
        </div>

        <div className="border-t border-neutral-800 p-3">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !busy && send()}
              placeholder="Reply to the TPP Builder…"
              className="flex-1 rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
            />
            <button
              onClick={send}
              disabled={busy || !input.trim()}
              className="rounded bg-neutral-700 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              Send
            </button>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-neutral-600">
              When you&apos;ve converged, finalize into a new TPP version.
            </span>
            <button
              onClick={finalize}
              disabled={finalizing || messages.length < 2}
              className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {finalizing ? "Creating…" : "Create this TPP"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
