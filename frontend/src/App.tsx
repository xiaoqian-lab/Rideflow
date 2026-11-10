import { useCallback, useEffect, useRef, useState } from "react";
import Composer from "./components/Composer";
import MapView from "./components/MapView";
import MessageList from "./components/MessageList";
import PlanJson from "./components/PlanJson";
import StageCards from "./components/StageCards";
import { fetchHealth, streamChat } from "./api";
import type { ChatMessage, Plan, SerializedMessage } from "./types";

type Health = "checking" | "ok" | "error";

let nextId = 0;

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: nextId++,
      role: "bot",
      text: "想去哪骑？给我起点、终点、天数和大致偏好。也可以点「示例」一键填入。",
    },
  ]);
  const [progress, setProgress] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [health, setHealth] = useState<Health>("checking");

  const historyRef = useRef<SerializedMessage[]>([]);
  const loadingRef = useRef(false);

  useEffect(() => {
    fetchHealth()
      .then((res) => setHealth(res.status === "ok" ? "ok" : "error"))
      .catch(() => setHealth("error"));
  }, []);

  const appendBot = useCallback((text: string) => {
    if (!text.trim()) return;
    setMessages((prev) => [...prev, { id: nextId++, role: "bot", text }]);
  }, []);

  const handleSend = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      setProgress("正在连接…");
      setMessages((prev) => [
        ...prev,
        { id: nextId++, role: "user", text: message },
      ]);
      try {
        const result = await streamChat(
          { message, history: historyRef.current, stream: true },
          (p) => setProgress(p),
        );
        historyRef.current = result.messages;
        setProgress(null);
        if (result.plan) setPlan(result.plan);
        appendBot(result.reply);
        const question = result.question?.trim();
        if (question && question !== result.reply.trim()) {
          appendBot(question);
        }
      } catch (err) {
        setProgress(null);
        appendBot(`出错了：${err instanceof Error ? err.message : String(err)}`);
      } finally {
        loadingRef.current = false;
        setLoading(false);
      }
    },
    [appendBot],
  );

  const healthLabel =
    health === "ok"
      ? "后端已连接"
      : health === "error"
        ? "后端未连接"
        : "检查后端…";

  return (
    <>
      <header>
        <h1>Rideflow · 骑行规划</h1>
        <span className={`badge ${health}`}>{healthLabel}</span>
      </header>
      <div className="layout">
        <div className="left">
          <MessageList messages={messages} progress={progress} />
          {plan && <StageCards plan={plan} />}
          <Composer loading={loading} onSend={handleSend} />
        </div>
        <div className="right">
          <MapView plan={plan} />
          <PlanJson plan={plan} />
        </div>
      </div>
    </>
  );
}
