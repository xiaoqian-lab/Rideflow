import { useState } from "react";
import type { FormEvent } from "react";

interface Props {
  loading: boolean;
  onSend: (text: string) => void;
}

export default function Composer({ loading, onSend }: Props) {
  const [value, setValue] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = value.trim();
    if (!text || loading) return;
    onSend(text);
    setValue("");
  };

  return (
    <form className="composer" onSubmit={submit}>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="输入出行意图…"
      />
      <button
        type="button"
        className="example"
        onClick={() => setValue("从美因茨骑到科隆，3 天，每天 70km 左右")}
      >
        示例
      </button>
      <button type="submit" disabled={loading}>
        {loading ? "规划中…" : "发送"}
      </button>
    </form>
  );
}
