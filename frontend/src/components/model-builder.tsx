"use client";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Brain, CheckCircle2, Info, Loader2, Play, Trash2, TriangleAlert, Trophy } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, fmtNum, humanize, timeAgo } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input, Label, Select } from "./ui/input";
import { ErrorNote, Skeleton, Tabs } from "./ui/misc";
import { ChartRenderer } from "./charts/chart-renderer";
import { DataGrid } from "./data-grid";
import { motion } from "./motion";

const tip = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };
const METRIC_LABEL: Record<string, string> = { roc_auc: "ROC AUC", pr_auc: "PR AUC", balanced_accuracy: "Balanced accuracy", accuracy: "Accuracy", precision: "Precision",
  recall: "Recall", f1: "F1", r2: "R²", rmse: "RMSE", mae: "MAE", baseline_rmse: "Baseline RMSE", majority_baseline_accuracy: "Majority-class accuracy", positive_rate: "Positive rate" };

function Setup({ dataset, onStarted }: { dataset: any; onStarted: (m: any) => void }) {
  const cols: any[] = dataset.profile.columns;
  const cands: any[] = dataset.profile.candidate_targets || [];
  const outcome = /churn|target|label|outcome|default|convert|fraud|survived|purchased|left|^y$/i;
  const suggested = (cands.find((c) => outcome.test(c.column)) || cands.find((c) => cols.find((x) => x.name === c.column)?.semantic_type === "boolean") || cands[0])?.column;
  const [target, setTarget] = useState<string>(suggested || cols[cols.length - 1].name);
  const [off, setOff] = useState<Set<string>>(new Set());
  const [split, setSplit] = useState("random");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const hasDate = (dataset.profile.datetime_columns || []).length > 0;
  const leaks = new Set((dataset.profile.leakage_hints || []).filter((h: any) => h.target === target).map((h: any) => h.feature));
  const ids = new Set(dataset.profile.identifier_columns || []);
  const features = cols.filter((c) => c.name !== target);

  async function start() {
    setBusy(true); setErr(null);
    try {
      const m = await api(`/datasets/${dataset.id}/automl`, { method: "POST", json: { target, split, features: features.map((c) => c.name).filter((n) => !off.has(n)) } });
      onStarted(m);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader><div><CardTitle>Train a prediction model</CardTitle>
        <CardDescription>Several models are compared by 5-fold cross-validation on training data, against a naive baseline. Only the winner is scored once on held-out data.</CardDescription></div></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label>What to predict</Label>
            <Select value={target} onChange={(e) => { setTarget(e.target.value); setOff(new Set()); }} className="mt-1">
              {cols.map((c) => <option key={c.name} value={c.name}>{c.name} ({humanize(c.semantic_type)})</option>)}</Select></div>
          <div><Label>How to test it</Label>
            <Select value={split} onChange={(e) => setSplit(e.target.value)} className="mt-1">
              <option value="random">Random 25% held out</option>
              <option value="time" disabled={!hasDate}>Latest 25% by date (forecast-style){hasDate ? "" : ": needs a date column"}</option></Select></div>
        </div>
        <div>
          <Label>Features ({features.length - off.size} used)</Label>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {features.map((c) => {
              const flag = leaks.has(c.name) ? "possible leakage" : ids.has(c.name) ? "identifier" : c.semantic_type === "datetime" ? "date" : null;
              const on = !off.has(c.name) && !flag;
              return (
                <button key={c.name} disabled={!!flag} title={flag ? `Excluded automatically: ${flag}` : on ? "Click to exclude" : "Click to include"}
                  onClick={() => { const n = new Set(off); n.has(c.name) ? n.delete(c.name) : n.add(c.name); setOff(n); }}
                  className={cn("rounded-full border px-2.5 py-1 text-[12px] transition", on ? "border-accent bg-accent-soft text-accent-text" : "border-border text-fg-3", flag && "cursor-not-allowed line-through opacity-60")}>
                  {c.name}{flag && <span className="ml-1 no-underline">({flag})</span>}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-[11.5px] text-fg-3">Identifiers, dates and columns that predict the target almost perfectly on their own are excluded automatically and listed in the results.</p>
        </div>
        {err && <ErrorNote message={err} />}
        <Button onClick={start} disabled={busy}><Play /> Train and compare models</Button>
      </CardContent>
    </Card>
  );
}

function Waterfall({ e }: { e: any }) {
  const rows = e.contributions.slice(0, 10).map((c: any) => ({ name: `${c.feature} = ${typeof c.value === "number" ? fmtNum(c.value) : c.value ?? "missing"}`, v: c.contribution }));
  return (
    <div style={{ height: rows.length * 28 + 40 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
          <XAxis type="number" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => fmtNum(v)} />
          <YAxis type="category" dataKey="name" width={210} fontSize={11} tickLine={false} axisLine={false} interval={0} />
          <Tooltip contentStyle={tip} formatter={(v: any) => [fmtNum(v), "Contribution"]} cursor={{ fill: "var(--surface-2)" }} />
          <ReferenceLine x={0} stroke="var(--border-strong, var(--border))" />
          <Bar dataKey="v" radius={3} maxBarSize={16}>{rows.map((r: any, i: number) => <Cell key={i} fill={r.v >= 0 ? "var(--chart-1)" : "var(--chart-4)"} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Predictor({ model }: { model: any }) {
  const schema: any[] = model.result.input_schema;
  const [vals, setVals] = useState<Record<string, any>>(() => Object.fromEntries(schema.map((f) => [f.name, f.kind === "numeric" ? f.median : f.mode])));
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try { setOut((await api(`/models/${model.id}/predict`, { method: "POST", json: { rows: [vals] } })).predictions[0]); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader><div><CardTitle>Try a prediction</CardTitle><CardDescription>Start from typical values (medians and most common categories), change any input, and see what drives the result.</CardDescription></div></CardHeader>
      <CardContent className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            {schema.map((f) => (
              <label key={f.name} className="text-[12px] text-fg-3">{f.name}
                {f.kind === "numeric"
                  ? <Input type="number" className="mt-1" value={vals[f.name] ?? ""} step="any" onChange={(e) => setVals({ ...vals, [f.name]: e.target.value === "" ? null : +e.target.value })} />
                  : <Select className="mt-1" value={vals[f.name] ?? ""} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })}>{f.options.map((o: string) => <option key={o}>{o}</option>)}</Select>}
                {f.kind === "numeric" && <span className="text-[10.5px]">training range {fmtNum(f.min)} to {fmtNum(f.max)}</span>}
              </label>
            ))}
          </div>
          <Button onClick={go} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Brain />} Predict</Button>
          {err && <ErrorNote message={err} />}
        </div>
        <div>
          {out ? <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
            <div className="text-[12px] text-fg-3">Prediction</div>
            <div className="text-[22px] font-semibold text-fg">{typeof out.prediction === "number" ? fmtNum(out.prediction) : out.prediction}
              {out.probability != null && <span className="ml-2 text-[14px] font-normal text-fg-2">probability {(out.probability * 100).toFixed(1)}%</span>}</div>
            <p className="text-[12px] text-fg-3">Starting from the average model output of {fmtNum(out.explanation.base_value)} ({out.explanation.scale}), each bar shows how much this input moved the result. Bars add up to {fmtNum(out.explanation.output)}.</p>
            <Waterfall e={out.explanation} />
            {schema.some((f) => f.kind === "numeric" && vals[f.name] != null && (vals[f.name] < f.min || vals[f.name] > f.max)) &&
              <p className="flex gap-1.5 text-[12px] text-warning"><TriangleAlert className="size-3.5" /> Some inputs are outside the training range, so this prediction is an extrapolation.</p>}
          </motion.div> : <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border p-8 text-center text-[13px] text-fg-3">Run a prediction to see its explanation.</div>}
        </div>
      </CardContent>
    </Card>
  );
}

function Scenario({ model }: { model: any }) {
  const schema: any[] = model.result.input_schema;
  const cats = schema.filter((f) => f.kind === "category");
  const blank = () => ({ feature: schema[0].name, op: schema[0].kind === "numeric" ? "percent" : "set", value: schema[0].kind === "numeric" ? 10 : schema[0].options[0] });
  const [changes, setChanges] = useState<any[]>([blank()]);
  const [filter, setFilter] = useState<{ column: string; value: string } | null>(null);
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const upd = (i: number, patch: any) => setChanges(changes.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  async function go() {
    setBusy(true); setErr(null);
    try {
      setOut(await api(`/models/${model.id}/scenario`, { method: "POST", json: { changes, filters: filter ? [{ column: filter.column, op: "==", value: filter.value }] : null } }));
    } catch (e: any) { setErr(e.message); setOut(null); } finally { setBusy(false); }
  }
  const OPS = [["percent", "change by %"], ["add", "add"], ["multiply", "multiply by"], ["set", "set to"]];
  return (
    <Card>
      <CardHeader><div><CardTitle>What-if scenario</CardTitle><CardDescription>Change inputs for every row (or a segment) and see how the model's average prediction moves, with a 95% bootstrap interval.</CardDescription></div></CardHeader>
      <CardContent className="space-y-3">
        {changes.map((c, i) => {
          const f = schema.find((x) => x.name === c.feature);
          return (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_150px_1fr_auto]">
              <Select aria-label="Feature" value={c.feature} onChange={(e) => { const nf = schema.find((x) => x.name === e.target.value); upd(i, { feature: nf.name, op: nf.kind === "numeric" ? "percent" : "set", value: nf.kind === "numeric" ? 10 : nf.options[0] }); }}>
                {schema.map((x) => <option key={x.name}>{x.name}</option>)}</Select>
              <Select aria-label="Change" value={c.op} onChange={(e) => upd(i, { op: e.target.value })} disabled={f?.kind !== "numeric"}>
                {(f?.kind === "numeric" ? OPS : [["set", "set to"]]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
              {f?.kind === "numeric" ? <Input aria-label="Value" type="number" step="any" value={c.value} onChange={(e) => upd(i, { value: e.target.value === "" ? "" : +e.target.value })} />
                : <Select aria-label="Value" value={c.value} onChange={(e) => upd(i, { value: e.target.value })}>{f?.options.map((o: string) => <option key={o}>{o}</option>)}</Select>}
              <Button variant="ghost" size="icon" aria-label="Remove change" disabled={changes.length === 1} onClick={() => setChanges(changes.filter((_, j) => j !== i))}><Trash2 /></Button>
            </div>
          );
        })}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => setChanges([...changes, blank()])} disabled={changes.length >= 5}>Add change</Button>
          {cats.length > 0 && (filter ? (
            <span className="flex items-center gap-1.5 text-[12.5px] text-fg-2">Only rows where
              <Select className="h-8 w-36" value={filter.column} onChange={(e) => setFilter({ column: e.target.value, value: cats.find((x) => x.name === e.target.value).options[0] })}>{cats.map((x) => <option key={x.name}>{x.name}</option>)}</Select> =
              <Select className="h-8 w-36" value={filter.value} onChange={(e) => setFilter({ ...filter, value: e.target.value })}>{cats.find((x) => x.name === filter.column)?.options.map((o: string) => <option key={o}>{o}</option>)}</Select>
              <button className="text-accent-text hover:underline" onClick={() => setFilter(null)}>all rows</button></span>
          ) : <button className="text-[12.5px] text-accent-text hover:underline" onClick={() => setFilter({ column: cats[0].name, value: cats[0].options[0] })}>Limit to a segment</button>)}
          <Button size="sm" className="ml-auto" onClick={go} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Play />} Run scenario</Button>
        </div>
        {err && <ErrorNote message={err} />}
        {out && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-3 rounded-lg border border-border p-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div><div className="text-[11.5px] text-fg-3">Average before</div><div className="num text-[18px] font-semibold">{fmtNum(out.before_mean)}</div></div>
              <div><div className="text-[11.5px] text-fg-3">Average after</div><div className="num text-[18px] font-semibold">{fmtNum(out.after_mean)}</div></div>
              <div><div className="text-[11.5px] text-fg-3">Difference</div><div className={cn("num text-[18px] font-semibold", out.difference > 0 ? "text-success" : out.difference < 0 ? "text-danger" : "")}>{out.difference > 0 ? "+" : ""}{fmtNum(out.difference)}</div></div>
              <div><div className="text-[11.5px] text-fg-3">95% interval</div><div className="num text-[15px] font-medium">{fmtNum(out.ci95[0])} to {fmtNum(out.ci95[1])}</div></div>
            </div>
            <p className="text-[12.5px] text-fg-2">Measured in {out.unit}, over {out.rows.toLocaleString()} rows. The prediction rose for {(out.share_increased * 100).toFixed(0)}% of rows and fell for {(out.share_decreased * 100).toFixed(0)}%.
              {out.total_before != null && ` Total predicted: ${fmtNum(out.total_before)} → ${fmtNum(out.total_after)}.`}</p>
            <ChartRenderer spec={{ id: "scn", kind: "bar", title: "Distribution of predictions before and after", data: out.histogram, x: "bin", series: [{ key: "before", label: "Before" }, { key: "after", label: "After" }] }} height={220} />
            {out.warnings.map((w: string) => <p key={w} className="flex gap-1.5 text-[12.5px] text-warning"><TriangleAlert className="mt-0.5 size-3.5 shrink-0" />{w}</p>)}
            <p className="flex gap-1.5 text-[12px] text-fg-3"><Info className="mt-0.5 size-3.5 shrink-0" />{out.caveat}</p>
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}

function Results({ model }: { model: any }) {
  const r = model.result;
  const [view, setView] = useState<"importance" | "shap" | "pdp">("shap");
  const pdpCols = Object.keys(r.partial_dependence || {}).filter((k) => r.partial_dependence[k].length);
  const [pdp, setPdp] = useState(pdpCols[0]);
  const primary = r.primary_metric;
  const cls = r.task === "classification";
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader><div>
          <CardTitle className="flex items-center gap-2"><Trophy className="size-4 text-accent-text" /> {humanize(r.best_model)} predicts {r.target}{r.binary ? ` = ${r.positive_class}` : ""}</CardTitle>
          <CardDescription>{humanize(r.task)} · {r.n_train.toLocaleString()} training rows, {r.n_test.toLocaleString()} test rows · {r.split_description} · {r.seconds}s</CardDescription></div></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Object.entries(r.test_metrics).map(([k, v]: any) => (
              <div key={k} className={cn("rounded-xl border p-3", k === primary ? "border-accent bg-accent-soft/40" : "border-border")}>
                <div className="text-[11.5px] text-fg-3">{METRIC_LABEL[k] || humanize(k)}</div>
                <div className="num text-[19px] font-semibold text-fg">{["rmse", "mae", "baseline_rmse"].includes(k) ? fmtNum(v) : (v as number).toFixed(3)}</div>
              </div>
            ))}
          </div>
          <p className="text-[12px] text-fg-3">All figures above are from the held-out test set, which was used once, after the model was chosen.</p>
          {(r.warnings.length > 0 || r.notes.length > 0 || r.excluded.length > 0) && (
            <ul className="space-y-1 text-[12.5px]">
              {r.warnings.map((w: string) => <li key={w} className="flex gap-2 text-fg-2"><TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />{w}</li>)}
              {r.notes.map((w: string) => <li key={w} className="flex gap-2 text-fg-2"><Info className="mt-0.5 size-3.5 shrink-0 text-fg-3" />{w}</li>)}
              {r.excluded.map((e: any) => <li key={e.feature} className="flex gap-2 text-fg-2"><Info className="mt-0.5 size-3.5 shrink-0 text-fg-3" /><span><b className="font-medium">{e.feature}</b> excluded. {e.reason}</span></li>)}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><div><CardTitle>Model comparison</CardTitle><CardDescription>Mean and spread over 5 cross-validation folds of the training data. The baseline shows what “no skill” scores.</CardDescription></div></CardHeader>
        <CardContent><DataGrid dense columns={["model", ...Object.keys(r.leaderboard[0]).filter((k) => k.startsWith("cv_") && !k.endsWith("_sd") && !k.startsWith("cv_train")), "fit_seconds", "description"]}
          rows={r.leaderboard.map((b: any) => ({ ...b, model: b.model === r.best_model ? `${humanize(b.model)} (chosen)` : humanize(b.model),
            ...Object.fromEntries(Object.keys(b).filter((k) => k.startsWith("cv_") && !k.endsWith("_sd") && !k.startsWith("cv_train")).map((k) => [k, b[k] == null ? "" : `${b[k].toFixed(3)} ± ${(b[k + "_sd"] ?? 0).toFixed(3)}`])) }))} /></CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        {cls && r.charts.confusion && <Card><CardHeader><div><CardTitle>Confusion matrix</CardTitle><CardDescription>Held-out test rows: actual (rows) vs predicted (columns).</CardDescription></div></CardHeader>
          <CardContent className="overflow-x-auto"><table className="text-[12.5px]"><thead><tr><th />{r.charts.confusion.labels.map((l: string) => <th key={l} className="px-3 pb-1 text-left font-medium text-fg-3">predicted {l}</th>)}</tr></thead>
            <tbody>{r.charts.confusion.matrix.map((row: number[], i: number) => <tr key={i}><th className="pr-3 text-right font-medium text-fg-3">actual {r.charts.confusion.labels[i]}</th>
              {row.map((v, j) => <td key={j} className={cn("num px-3 py-2", i === j ? "bg-accent-soft text-accent-text font-semibold" : "text-fg")}>{v.toLocaleString()}</td>)}</tr>)}</tbody></table></CardContent></Card>}
        {r.charts.roc && <Card><CardContent className="pt-5"><ChartRenderer spec={{ id: "roc", kind: "line", title: `ROC curve (AUC ${r.test_metrics.roc_auc.toFixed(3)})`, data: r.charts.roc, x: "fpr", series: [{ key: "tpr", label: "True positive rate" }], x_label: "False positive rate", diagonal: true }} height={240} /></CardContent></Card>}
        {r.charts.calibration?.length > 1 && <Card><CardContent className="pt-5"><ChartRenderer spec={{ id: "cal", kind: "line", title: "Calibration: observed rate vs predicted probability", data: r.charts.calibration, x: "predicted", series: [{ key: "observed", label: "Observed rate" }], diagonal: true }} height={240} /></CardContent></Card>}
        {r.charts.pred_vs_actual && <Card><CardContent className="pt-5"><ChartRenderer spec={{ id: "pva", kind: "scatter", title: "Predicted vs actual (test sample)", data: r.charts.pred_vs_actual.map((p: any) => ({ x: p.actual, y: p.predicted })), x: "x", series: [{ key: "y" }], x_label: "Actual", y_label: "Predicted", diagonal: true }} height={260} /></CardContent></Card>}
        {r.charts.residuals && <Card><CardContent className="pt-5"><ChartRenderer spec={{ id: "res", kind: "scatter", title: "Residuals (actual − predicted) vs predicted", data: r.charts.residuals.map((p: any) => ({ x: p.predicted, y: p.residual })), x: "x", series: [{ key: "y" }], x_label: "Predicted", y_label: "Residual" }} height={260} /></CardContent></Card>}
      </div>

      <Card>
        <CardHeader><div><CardTitle>What the model relies on</CardTitle><CardDescription>{view === "shap" ? r.shap_note : view === "importance" ? "Drop in test score when a feature is shuffled (5 repeats). Near zero means the model barely uses it." : "Average prediction as one feature changes and the others keep their observed values."}</CardDescription></div></CardHeader>
        <CardContent className="space-y-3">
          <Tabs value={view} onChange={setView} items={[{ value: "shap" as const, label: "Shapley values" }, { value: "importance" as const, label: "Permutation importance" }, ...(pdpCols.length ? [{ value: "pdp" as const, label: "Partial dependence" }] : [])]} />
          {view === "shap" && <ChartRenderer spec={{ id: "shap", kind: "bar", title: "Mean |Shapley value| per feature", data: r.shap_global.slice(0, 15), x: "feature", series: [{ key: "mean_abs_shap", label: "Mean |contribution|" }], layout: "horizontal" }} height={Math.max(200, Math.min(15, r.shap_global.length) * 28 + 40)} />}
          {view === "importance" && <ChartRenderer spec={{ id: "pi", kind: "bar", title: "Permutation importance on the test set", data: r.importance.slice(0, 15), x: "feature", series: [{ key: "importance", label: "Score drop" }], layout: "horizontal", error: ["std", "std"] }} height={Math.max(200, Math.min(15, r.importance.length) * 28 + 40)} />}
          {view === "pdp" && pdp && <>
            <Select className="w-56" value={pdp} onChange={(e) => setPdp(e.target.value)} aria-label="Feature">{pdpCols.map((c) => <option key={c}>{c}</option>)}</Select>
            <ChartRenderer spec={{ id: "pdp", kind: "line", title: `Average prediction as ${pdp} changes`, data: r.partial_dependence[pdp], x: "value", series: [{ key: "prediction", label: cls ? "Predicted probability" : "Prediction" }] }} height={240} />
          </>}
          <p className="text-[11.5px] text-fg-3">These show how the model uses its inputs. They are associations learned from this data, not proof that changing a feature would change the outcome.</p>
        </CardContent>
      </Card>
      <Predictor model={model} />
      <Scenario model={model} />
    </div>
  );
}

export function ModelBuilder({ dataset }: { dataset: any }) {
  const list = useApi<any[]>(`/datasets/${dataset.id}/models`);
  const [sel, setSel] = useState<string | null>(null);
  const current = sel || list.data?.[0]?.id || null;
  const model = useApi<any>(current ? `/models/${current}` : null, { poll: (m) => ["queued", "running"].includes(m.status), interval: 1500 });
  const [setup, setSetup] = useState(false);
  useEffect(() => { if (model.data && !["queued", "running"].includes(model.data.status)) list.reload(); }, [model.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const showSetup = setup || (list.data && list.data.length === 0);
  const m = model.data;
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_260px]">
      <div className="space-y-5">
        {list.loading && <Skeleton className="h-60" />}
        {showSetup && <Setup dataset={dataset} onStarted={(nm) => { setSetup(false); setSel(nm.id); list.reload(); }} />}
        {!showSetup && m && (m.status === "queued" || m.status === "running") && (
          <Card className="flex items-center gap-3 p-6"><Loader2 className="size-5 animate-spin text-accent-text" />
            <div><div className="text-[14px] font-medium text-fg">Training models to predict {m.target}</div><div className="text-[12.5px] text-fg-3">{m.progress || "Queued"}</div></div></Card>)}
        {!showSetup && m?.status === "failed" && <ErrorNote message={m.error || "Training failed."} />}
        {!showSetup && m?.status === "succeeded" && <Results key={m.id} model={m} />}
      </div>
      <Card className="h-fit">
        <CardHeader><div><CardTitle>Models</CardTitle><CardDescription>Trained on this dataset.</CardDescription></div></CardHeader>
        <CardContent className="space-y-1">
          <Button size="sm" variant="secondary" className="mb-2 w-full" onClick={() => setSetup(true)}><Play /> New model</Button>
          {list.data?.map((x) => (
            <div key={x.id} className={cn("group flex items-start gap-1 rounded-lg px-2 py-1.5 hover:bg-surface-2", x.id === current && !showSetup && "bg-surface-2")}>
              <button className="min-w-0 flex-1 text-left" onClick={() => { setSel(x.id); setSetup(false); }}>
                <div className="flex items-center gap-1.5 truncate text-[12.5px] text-fg">{x.status === "succeeded" ? <CheckCircle2 className="size-3.5 text-success" /> : x.status === "failed" ? <TriangleAlert className="size-3.5 text-warning" /> : <Loader2 className="size-3.5 animate-spin" />}{x.target}</div>
                <div className="truncate text-[11px] text-fg-3">{timeAgo(x.created_at)}{x.summary ? ` · ${humanize(x.summary.best_model)} ${METRIC_LABEL[x.summary.primary_metric]} ${x.summary.score?.toFixed(3)}` : ""}</div>
              </button>
              <button aria-label="Delete model" className="p-1 text-fg-3 opacity-60 hover:text-danger group-hover:opacity-100" onClick={async () => { await api(`/models/${x.id}`, { method: "DELETE" }); if (x.id === current) setSel(null); list.reload(); }}><Trash2 className="size-3.5" /></button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
