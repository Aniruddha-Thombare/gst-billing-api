import {
  BarChart3, Boxes, FileText, FileSpreadsheet, Gauge, Landmark, LayoutDashboard, Receipt, Settings, Users, WalletCards,
  type LucideIcon,
} from "lucide-react";

export interface NavItem { label: string; to?: string; icon: LucideIcon; soon?: string; ownerOnly?: boolean; }
export interface NavSection { title: string; items: NavItem[]; }

/**
 * The sidebar, as data. Items without a `to` are shown greyed out with a reason,
 * so the menu matches the product plan but never links to a screen the backend cannot serve yet.
 */
export const NAV: NavSection[] = [
  { title: "Main", items: [
    { label: "Dashboard", to: "/", icon: LayoutDashboard },
    { label: "Invoices", to: "/invoices", icon: FileText },
    { label: "Clients", to: "/parties", icon: Users },
    { label: "Products / Items", to: "/items", icon: Boxes },
    { label: "Payments", to: "/payments", icon: WalletCards },
    { label: "Credit / Debit Notes", to: "/notes", icon: Receipt },
  ] },
  { title: "Reports", items: [
    { label: "GSTR-1", to: "/reports/gstr1", icon: FileSpreadsheet },
    { label: "GSTR-3B", to: "/reports/gstr3b", icon: Landmark },
    { label: "Sales Summary", to: "/reports/sales", icon: BarChart3 },
    { label: "Receivables Aging", to: "/reports/aging", icon: Gauge },
    { label: "Purchase Register", icon: FileText, soon: "Version 2 (accounts payable)" },
  ] },
  { title: "Settings", items: [
    { label: "Users & Roles", to: "/users", icon: Users, ownerOnly: true },
    { label: "Business Profile", icon: Settings, soon: "Later" },
  ] },
];
