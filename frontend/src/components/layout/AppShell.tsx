import { useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

/** The frame around every logged-in page. It also guards the routes: no user, back to /login. */
export function AppShell() {
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  if (!user) return <Navigate to="/login" replace />;
  return (
    <div className="min-h-screen">
      <Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="lg:pl-64">
        <Topbar onMenu={() => setMenuOpen(true)} />
        <main className="mx-auto max-w-[1400px] p-4 sm:p-6"><Outlet /></main>
      </div>
    </div>
  );
}
