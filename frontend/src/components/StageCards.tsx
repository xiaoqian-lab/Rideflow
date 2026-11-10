import type { Plan, Stage } from "../types";
import { pointLabel } from "../geometry";

const COLORS = ["#4fd1c5", "#f6ad55", "#7f9cf5"];

export default function StageCards({ plan }: { plan: Plan }) {
  return (
    <div className="stages">
      <div className="label">逐日 stage</div>
      {plan.stages.map((stage, i) => (
        <StageCard
          key={stage.day}
          stage={stage}
          color={COLORS[i % COLORS.length]}
        />
      ))}
    </div>
  );
}

function StageCard({ stage, color }: { stage: Stage; color: string }) {
  const surface = stage.route?.surface_breakdown ?? {};
  const paved =
    typeof surface.paved === "number" ? Math.round(surface.paved * 100) : null;

  return (
    <div className="stage">
      <h4>
        <span className="dot" style={{ background: color }} />
        Day {stage.day} · {pointLabel(stage.start)} → {pointLabel(stage.end)}
      </h4>
      <span className="kv">
        {stage.route.distance_km.toFixed(1)} km · 爬升{" "}
        {Math.round(stage.route.climb_m)}m · 下降{" "}
        {Math.round(stage.route.descent_m)}m
        {paved !== null ? ` · 铺装 ${paved}%` : ""}
      </span>
      {stage.notes && <div className="note">{stage.notes}</div>}
    </div>
  );
}
