import { fmtDate, STATUS_LABEL, type Ncr } from "../../lib/api";
import { Badge, Card, LevelBadge, statusTone } from "../ui";

export function NcrHeader({ ncr }: { ncr: Ncr }) {
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono">{ncr.code}</span>
          <Badge tone={statusTone(ncr.status)}>{STATUS_LABEL[ncr.status] ?? ncr.status}</Badge>
        </span>
      }
      actions={<LevelBadge level={ncr.detected_level} />}
    >
      <p className="text-sm leading-relaxed">{ncr.description}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-5">
        <Meta k="Planta · línea" v={`${ncr.plant_id} · ${ncr.line_id}`} />
        <Meta k="Turno" v={`T${ncr.shift}`} />
        <Meta k="Parte" v={ncr.part_number ?? "—"} />
        <Meta k="Cliente" v={ncr.customer_id ?? "—"} />
        <Meta k="Alta" v={fmtDate(ncr.created_at)} />
      </dl>
      {!!ncr.classification_reasons?.length && (
        <p className="mt-3 text-xs text-muted">
          Por qué es {ncr.detected_level}: {ncr.classification_reasons.join("; ")}
          {ncr.contains_pii ? " · contiene datos personales (se seudonimizan antes de ir al modelo)" : ""}
        </p>
      )}
    </Card>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-muted">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}
