import { createRoot } from "react-dom/client";
import App from "./App";
import "maplibre-gl/dist/maplibre-gl.css";
import "./index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing #root element");
}
createRoot(root).render(<App />);
