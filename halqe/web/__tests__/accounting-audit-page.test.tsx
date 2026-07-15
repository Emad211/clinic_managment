import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

jest.mock("next/navigation", () => ({
  usePathname: () => "/accounting/audit",
}));

const logout = jest.fn();
jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ ready: true, logout }),
}));

jest.mock("@/components/Nav", () => function MockNav() {
  return <nav aria-label="mock navigation" />;
});

jest.mock("@/lib/api/accounting-audit", () => ({
  apiGetAccountingAuditLogs: jest.fn(),
}));

import { ApiError } from "@/lib/api";
import { apiGetAccountingAuditLogs } from "@/lib/api/accounting-audit";
import AccountingAuditPage from "@/app/accounting/audit/page";

const DATA = {
  date_from: "2099-01-01",
  date_to: "2099-01-02",
  page: 1,
  page_size: 50,
  total: 1,
  total_pages: 1,
  category_summary: [{ action_category: "invoice", count: 1 }],
  filter_options: {
    action_types: ["item_payment_set"],
    action_categories: ["invoice"],
    users: [{ user_id: 1, username: "manager", full_name: "مدیر نمونه" }],
  },
  rows: [
    {
      id: 1,
      created_at: "2099-01-01T09:00:00+03:30",
      user_id: 1,
      username: "manager",
      user_full_name: "مدیر نمونه",
      action_type: "item_payment_set",
      action_category: "invoice",
      description: "تغییر پرداخت آزمایشی",
      target_type: "visit",
      target_id: 10,
      target_name: "ویزیت نمونه",
      invoice_id: 20,
      patient_id: 30,
      patient_name: "بیمار نمونه",
      amount: 125000,
      old_value: "unpaid",
      new_value: "paid",
      ip_address: "127.0.0.1",
      user_agent: "test",
    },
  ],
};

beforeEach(() => {
  jest.clearAllMocks();
  (apiGetAccountingAuditLogs as jest.Mock).mockResolvedValue(DATA);
});

test("renders audit rows and applies text filters", async () => {
  render(<AccountingAuditPage />);
  expect(await screen.findByRole("heading", { name: "بازبینی رویدادهای حسابداری" })).toBeInTheDocument();
  expect(await screen.findByText("تغییر پرداخت آزمایشی")).toBeInTheDocument();
  expect(screen.getByText("مدیر نمونه")).toBeInTheDocument();
  expect(screen.getAllByText("فاکتور").length).toBeGreaterThan(0);

  fireEvent.change(screen.getByLabelText("جست‌وجوی متن"), {
    target: { value: "بیمار نمونه" },
  });
  fireEvent.click(screen.getByRole("button", { name: "اعمال فیلتر" }));
  await waitFor(() => {
    expect(apiGetAccountingAuditLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({ search_text: "بیمار نمونه", page: 1, page_size: 50 }),
    );
  });
});

test("shows manager-only denial without rendering the ledger", async () => {
  (apiGetAccountingAuditLogs as jest.Mock).mockRejectedValue(
    new ApiError(403, "دسترسی محدود", "forbidden"),
  );
  render(<AccountingAuditPage />);
  expect(
    await screen.findByText("بازبینی رویدادها فقط برای مدیر یا ادمین قابل دسترسی است."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "دفتر رویدادها" })).not.toBeInTheDocument();
});
