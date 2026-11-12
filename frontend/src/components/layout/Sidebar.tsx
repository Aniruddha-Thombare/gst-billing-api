import { FileText, X } from "lucide-react";
import { NavLink } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { cn } from "@/lib/utils";
import { NAV } from "./nav";

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  return (
    <>
      {open ? <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={onClose} aria-hidden /> : null}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-sidebar text-sidebar-foreground transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-5 py-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-sidebar-active text-white"><FileText className="h-5 w-5" /></div>
            <div className="leading-tight"><div className="font-bold text-white">GST BILLING</div><div className="text-[11px] tracking-wide">& REPORTS SYSTEM</div></div>
          </div>
          <button className="lg:hidden" onClick={onClose} aria-label="Close menu"><X className="h-5 w-5" /></button>
        </div>
        <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-6">
          {NAV.map((section) => (
            <div key={section.title}>
              <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider opacity-60">{section.title}</div>
              {section.items.filter((i) => !i.ownerOnly || user?.role === "owner").map((item) =>
                item.to ? (
                  <NavLink
                    key={item.label}
                    to={item.to}
                    end={item.to === "/"}
                    onClick={onClose}
                    className={({ isActive }) => cn(
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-white/10",
                      isActive && "bg-sidebar-active text-white hover:bg-sidebar-active",
                    )}
                  >
                    <item.icon className="h-4 w-4" />{item.label}
                  </NavLink>
                ) : (
                  <div key={item.label} title={item.soon} className="flex cursor-not-allowed items-center gap-3 rounded-md px-3 py-2 text-sm opacity-40">
                    <item.icon className="h-4 w-4" />{item.label}
                  </div>
                ),
              )}
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
