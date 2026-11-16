import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, csv, formatDetail, request, setApiKey } from "./api.js";

const store = {};
beforeEach(() => {
  for (const k of Object.keys(store)) delete store[k];
  globalThis.sessionStorage = {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => (store[k] = String(v)),
    removeItem: (k) => delete store[k],
  };
});

const fakeFetch = (status, json) => vi.fn(async () => ({ ok: status < 400, status, json: async () => json }));

describe("formatDetail", () => {
  it("handles strings, validation arrays and injection errors", () => {
    expect(formatDetail("nope")).toBe("nope");
    expect(formatDetail([{ loc: ["body", "title"], msg: "too short" }])).toBe("title: too short");
    expect(
      formatDetail({ code: "prompt_injection_detected", message: "rejected", fields: { content: ["role_hijack"] } }),
    ).toBe("rejected (content: role_hijack)");
    expect(formatDetail(null, 500)).toBe("Request failed (500)");
  });
});

describe("request", () => {
  it("sends the API key header and JSON body", async () => {
    setApiKey("ank_test");
    const f = fakeFetch(200, { ok: true });
    await request("/posts", { method: "POST", body: { a: 1 }, fetchImpl: f });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/v1/posts");
    expect(init.headers["X-API-Key"]).toBe("ank_test");
    expect(init.body).toBe('{"a":1}');
  });

  it("omits the key when auth=false", async () => {
    setApiKey("ank_test");
    const f = fakeFetch(201, {});
    await request("/agents", { method: "POST", body: {}, auth: false, fetchImpl: f });
    expect(f.mock.calls[0][1].headers["X-API-Key"]).toBeUndefined();
  });

  it("throws ApiError with status and message", async () => {
    await expect(request("/x", { fetchImpl: fakeFetch(401, { detail: "missing or invalid API key" }) })).rejects.toMatchObject({
      status: 401,
      message: "missing or invalid API key",
    });
  });

  it("reports an unreachable backend", async () => {
    const f = vi.fn(async () => { throw new TypeError("fetch failed"); });
    await expect(request("/x", { fetchImpl: f })).rejects.toBeInstanceOf(ApiError);
  });
});

describe("helpers", () => {
  it("csv trims and drops empties", () => expect(csv(" a, b ,,c ")).toEqual(["a", "b", "c"]));
  it("listPosts drops empty filters from the query string", async () => {
    const f = fakeFetch(200, []);
    globalThis.fetch = f;
    await api.listPosts({ tag: "", mine: false, industry: "Retail", limit: 10 });
    expect(f.mock.calls[0][0]).toBe("/api/v1/posts?industry=Retail&limit=10");
  });
});
