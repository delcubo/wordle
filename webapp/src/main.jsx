import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";

import MyTournaments from "./pages/MyTournaments.jsx";
import PlayerGame from "./pages/PlayerGame.jsx";
import AdminLogin from "./pages/AdminLogin.jsx";
import AdminDashboard from "./pages/AdminDashboard.jsx";

// Отдельная иконка вкладки для админки — чтобы отличать её от вкладки
// участника среди множества открытых вкладок браузера (см. пункт бэклога).
function FaviconSwitcher() {
  const location = useLocation();
  useEffect(() => {
    const href = location.pathname.startsWith("/alvipa") ? "/favicon-admin.svg" : "/favicon.svg";
    document.querySelector('link[rel="icon"]')?.setAttribute("href", href);
  }, [location.pathname]);
  return null;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <FaviconSwitcher />
      <Routes>
        <Route path="/play/:token" element={<MyTournaments />} />
        <Route path="/play/:token/:tournamentId" element={<PlayerGame />} />
        <Route path="/alvipa" element={<AdminLogin />} />
        <Route path="/alvipa/dashboard" element={<AdminDashboard />} />
        <Route path="/" element={null} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
