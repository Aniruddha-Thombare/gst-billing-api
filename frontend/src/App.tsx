import { Route, Routes } from "react-router-dom";
import { ComingSoon } from "@/components/common/ComingSoon";
import { AppShell } from "@/components/layout/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import { RegisterPage } from "@/features/auth/RegisterPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { InvoiceDetailPage } from "@/features/invoices/InvoiceDetailPage";
import { InvoiceNewPage } from "@/features/invoices/InvoiceNewPage";
import { InvoicesPage } from "@/features/invoices/InvoicesPage";
import { ItemsPage } from "@/features/items/ItemsPage";
import { PartiesPage } from "@/features/parties/PartiesPage";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { AgingPage } from "@/features/reports/AgingPage";
import { Gstr1Page } from "@/features/reports/Gstr1Page";
import { Gstr3bPage } from "@/features/reports/Gstr3bPage";
import { SalesSummaryPage } from "@/features/reports/SalesSummaryPage";
import { UsersPage } from "@/features/users/UsersPage";

/** The route table: which URL shows which page. Everything except /login and /register sits inside AppShell, which guards login. */
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<AppShell />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/invoices" element={<InvoicesPage />} />
        <Route path="/invoices/new" element={<InvoiceNewPage />} />
        <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
        <Route path="/notes" element={<InvoicesPage notes />} />
        <Route path="/parties" element={<PartiesPage />} />
        <Route path="/items" element={<ItemsPage />} />
        <Route path="/payments" element={<PaymentsPage />} />
        <Route path="/reports/gstr1" element={<Gstr1Page />} />
        <Route path="/reports/gstr3b" element={<Gstr3bPage />} />
        <Route path="/reports/sales" element={<SalesSummaryPage />} />
        <Route path="/reports/aging" element={<AgingPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="*" element={<ComingSoon title="Not found" note="That page does not exist." />} />
      </Route>
    </Routes>
  );
}
