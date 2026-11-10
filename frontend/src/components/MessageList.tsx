import { useEffect, useRef } from "react";
import type { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  progress: string | null;
}

export default function MessageList({ messages, progress }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, progress]);

  return (
    <div className="chat" ref={scrollRef}>
      {messages.map((m) => (
        <div key={m.id} className={`msg ${m.role}`}>
          {m.text}
        </div>
      ))}
      {progress && (
        <div className="msg bot progress">
          {progress}
          <span className="cursor">▍</span>
        </div>
      )}
    </div>
  );
}
