import { api } from "./api";

export const DEMO_QUESTION = "Why did our profit decline last month, and which products should we investigate first?";

export async function startDemo(push: (href: string) => void, which: "retail" | "churn" = "retail", question = DEMO_QUESTION) {
  const ds = await api(`/datasets/demo/${which}`, { method: "POST" });
  const a = await api("/analyses/plan", { method: "POST", json: { dataset_id: ds.id, question } });
  push(`/analyses/${a.id}`);
}
