import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { limparSessao } from "../api/cliente";
import { restaurarApi } from "./apiFalsa";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  restaurarApi();
  limparSessao();
});
