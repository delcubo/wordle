import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import MyTournaments from "./pages/MyTournaments.jsx";
import PlayerGame from "./pages/PlayerGame.jsx";
import AdminLogin from "./pages/AdminLogin.jsx";
import AdminDashboard from "./pages/AdminDashboard.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/play/:token" element={<MyTournaments />} />
        <Route path="/play/:token/:tournamentId" element={<PlayerGame />} />
        <Route path="/alvipa" element={<AdminLogin />} />
        <Route path="/admin" element={<AdminDashboard />} />
        <Route path="/" element={null} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
