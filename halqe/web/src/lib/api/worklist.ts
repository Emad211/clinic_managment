/**
 * Worklist domain — mirrors WorklistItemDTO + WorklistResponseDTO +
 * FollowupTaskDTO (mark-done).
 */
import { apiFetch } from "./_core";

export interface WorklistItem {
  id: number;
  patient_uuid: string | null;
  patient_full_name: string | null;
  kind: string | null;       // same value as reason — the "kind" of follow-up
  reason: string | null;
  due_date: string | null;   // ISO date YYYY-MM-DD (can be null)
  status: string;            // 'open' | 'done' | 'dismissed'
  fulfillment: string | null;
  created_at: string;        // ISO datetime
  resolved_at: string | null;
  /**
   * Cumulative closed-invoice revenue for this patient (Toman).
   * Only populated when the authed user is a MANAGER and include_revenue=true
   * was sent. Backend enforces the manager gate — non-managers always get null.
   */
  revenue?: number | null;
}

export interface WorklistResponse {
  items: WorklistItem[];
  total: number;
  limit: number;
  offset: number;
}

export async function apiGetWorklist({
  status,
  limit = 20,
  offset = 0,
  includeRevenue = true,
}: {
  status?: string;
  limit?: number;
  offset?: number;
  /**
   * When true, passes include_revenue=true to the backend.
   * The backend only populates `revenue` for MANAGER users — non-managers
   * receive null regardless. Defaults to true so the UI auto-shows the column
   * for managers without any client-side role check.
   */
  includeRevenue?: boolean;
} = {}): Promise<WorklistResponse> {
  const params = new URLSearchParams();
  if (status !== undefined) params.set("status", status);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (includeRevenue) params.set("include_revenue", "true");
  return apiFetch<WorklistResponse>(`/worklist?${params.toString()}`);
}

// ────────────────────────────────────────────────────────────
// Mark worklist task done  — mirrors FollowupTaskDTO
// ────────────────────────────────────────────────────────────

export interface FollowupTaskDTO {
  id: number;
  patient_link_id: number;
  tenant_id: number;
  reason: string | null;
  detail: string | null;
  due_date: string | null;
  status: string;
  fulfillment: string | null;
  source_rule: string | null;
  source_event: string | null;
  created_at: string;
  resolved_at: string | null;
}

export async function apiMarkDone(taskId: number): Promise<FollowupTaskDTO> {
  return apiFetch<FollowupTaskDTO>(`/worklist/${taskId}/done`, {
    method: "POST",
  });
}
