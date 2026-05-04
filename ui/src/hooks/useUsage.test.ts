import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useUsage } from "./useUsage";

describe("useUsage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches and exposes data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ x: 1 }),
    }));
    const { result } = renderHook(() => useUsage<{ x: number }>("/api/foo"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ x: 1 });
    expect(result.current.error).toBeNull();
  });

  it("surfaces a non-2xx response as an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    }));
    const { result } = renderHook(() => useUsage("/api/boom"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toContain("500");
    expect(result.current.data).toBeNull();
  });

  it("re-fetches when refreshKey changes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ n: 1 }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ n: 2 }) });
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook(
      ({ key }: { key: number }) => useUsage<{ n: number }>("/api/x", key),
      { initialProps: { key: 0 } },
    );
    await waitFor(() => expect(result.current.data).toEqual({ n: 1 }));
    rerender({ key: 1 });
    await waitFor(() => expect(result.current.data).toEqual({ n: 2 }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
