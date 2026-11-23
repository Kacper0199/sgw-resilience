export interface SseMessage {
  id?: string;
  event: string;
  data: string;
  retry?: number;
}

/** Incremental text/event-stream parser (spec: field lines, blank line dispatches, comments ignored). */
export function createSseParser(onMessage: (message: SseMessage) => void) {
  let buffer = "";
  let current: { id?: string; event?: string; data: string[]; retry?: number } = { data: [] };

  const dispatch = () => {
    if (current.data.length > 0 || current.event) {
      onMessage({
        id: current.id,
        event: current.event ?? "message",
        data: current.data.join("\n"),
        retry: current.retry,
      });
    }
    current = { data: [], id: current.id };
  };

  const line = (raw: string) => {
    if (raw === "") return dispatch();
    if (raw.startsWith(":")) return;
    const idx = raw.indexOf(":");
    const field = idx === -1 ? raw : raw.slice(0, idx);
    const value = idx === -1 ? "" : raw.slice(idx + 1).replace(/^ /, "");
    if (field === "data") current.data.push(value);
    else if (field === "event") current.event = value;
    else if (field === "id") current.id = value;
    else if (field === "retry" && /^\d+$/.test(value)) current.retry = Number(value);
  };

  return {
    push(chunk: string) {
      buffer += chunk;
      const lines = buffer.split(/\r\n|\n|\r/);
      buffer = lines.pop() ?? "";
      for (const l of lines) line(l);
    },
  };
}
