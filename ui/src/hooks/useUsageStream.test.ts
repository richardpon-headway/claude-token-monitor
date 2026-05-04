import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useUsageStream } from "./useUsageStream";

class MockEventSource {
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  close = vi.fn();
  constructor(url: string) {
    this.url = url;
    MockEventSource.last = this;
  }
  static last: MockEventSource | null = null;
}

describe("useUsageStream", () => {
  beforeEach(() => {
    MockEventSource.last = null;
    vi.stubGlobal("EventSource", MockEventSource);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("subscribes to /api/stream", () => {
    renderHook(() => useUsageStream());
    expect(MockEventSource.last?.url).toBe("/api/stream");
  });

  it("flips to live=true on open and bumps refreshKey on message", () => {
    const { result } = renderHook(() => useUsageStream());
    expect(result.current.live).toBe(false);

    act(() => MockEventSource.last!.onopen?.(new Event("open")));
    expect(result.current.live).toBe(true);

    const before = result.current.refreshKey;
    act(() =>
      MockEventSource.last!.onmessage?.(new MessageEvent("message", { data: "{}" })),
    );
    expect(result.current.refreshKey).toBe(before + 1);
  });

  it("falls back to 10s polling: refreshKey ticks even without SSE messages", () => {
    const { result } = renderHook(() => useUsageStream());
    const before = result.current.refreshKey;
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(result.current.refreshKey).toBe(before + 1);
  });

  it("flips live=false on error", () => {
    const { result } = renderHook(() => useUsageStream());
    act(() => MockEventSource.last!.onopen?.(new Event("open")));
    expect(result.current.live).toBe(true);
    act(() => MockEventSource.last!.onerror?.(new Event("error")));
    expect(result.current.live).toBe(false);
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useUsageStream());
    const es = MockEventSource.last!;
    unmount();
    expect(es.close).toHaveBeenCalled();
  });
});
