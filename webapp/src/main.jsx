import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import MyTournaments from "./pages/MyTournaments.jsx";
import PlayerGame from "./pages/PlayerGame.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/play/:token" element={<MyTournaments />} />
        <Route path="/play/:token/:tournamentId" element={<PlayerGame />} />
        <Route path="/" element={null} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
