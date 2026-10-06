import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import AdminLogin from "./pages/AdminLogin.jsx";
import AdminDashboard from "./pages/AdminDashboard.jsx";
import { ADMIN_BASE } from "./adminBase.js";

// Отдельная точка входа админки (см. a.html и adminBase.js) — не входит в
// бандл страниц игроков.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path={ADMIN_BASE} element={<AdminLogin />} />
        <Route path={`${ADMIN_BASE}/dashboard`} element={<AdminDashboard />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
