import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("AICodeArena could not find the #root element");
}

createRoot(rootElement).render(<App />);
