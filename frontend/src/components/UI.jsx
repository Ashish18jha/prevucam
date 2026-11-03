import Icon from "./Icons";
import { typeLabel, typeTone } from "../utils/format";

export function Panel({ title, actions, children, pad = true, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <div className="panel-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {pad ? <div className="panel-body">{children}</div> : children}
    </section>
  );
}

export function Stat({ label, value, hint, accent = "var(--cyan)" }) {
  return (
    <div className="panel stat" style={{ "--accent": accent }}>
      <div className="label">{label}</div>
      <div className="value">{value ?? "—"}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function Badge({ tone = "slate", dot, pulse, children }) {
  return (
    <span className={`badge ${tone}`}>
      {dot && <span className={`dot ${pulse ? "pulse" : ""}`} />}
      {children}
    </span>
  );
}

export const TypeBadge = ({ type }) => <Badge tone={typeTone(type)}>{typeLabel(type)}</Badge>;

export function StatusBadge({ status }) {
  const tone = { completed: "green", recording: "red", processing: "amber", failed: "red", sent: "green",
    partial: "amber", skipped: "slate", pending: "slate" }[status] || "slate";
  return <Badge tone={tone} dot pulse={status === "recording"}>{status}</Badge>;
}

export function Switch({ checked, onChange, label, disabled }) {
  return (
    <label className="switch" style={disabled ? { opacity: 0.5 } : null}>
      <input type="checkbox" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      {label && <span>{label}</span>}
    </label>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Empty({ title, children }) {
  return <div className="empty"><strong>{title}</strong>{children}</div>;
}

export const ErrorBox = ({ error }) => (error ? <div className="error-box">{error.message || String(error)}</div> : null);

export function Btn({ icon, children, busy, className = "", ...rest }) {
  return (
    <button className={`btn ${className}`} disabled={busy || rest.disabled} {...rest}>
      {icon && <Icon name={icon} />}
      {busy ? "Working…" : children}
    </button>
  );
}

export function PageHead({ title, subtitle, children }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}
