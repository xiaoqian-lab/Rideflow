import type { Plan } from "../types";

export default function PlanJson({ plan }: { plan: Plan | null }) {
  return (
    <div className="state">
      <div className="label">Plan JSON</div>
      {plan ? (
        <details>
          <summary>展开完整 Plan JSON</summary>
          <pre>{JSON.stringify(plan, null, 2)}</pre>
        </details>
      ) : (
        <pre>尚未产生计划。先在上方完成一次「意图 → 澄清 → 计划」。</pre>
      )}
    </div>
  );
}
