import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QuotaBar } from "./QuotaBar";

const FLOOR = 233_333;

describe("QuotaBar", () => {
  it("renders the percentage rounded to a whole number", () => {
    render(<QuotaBar todayOutput={Math.round(FLOOR * 0.5)} />);
    expect(screen.getByText(/\(50%\)/)).toBeInTheDocument();
  });

  it("always uses a single emerald color regardless of percentage", () => {
    for (const pct of [0.43, 0.9, 1.5, 5.0]) {
      const { container, unmount } = render(
        <QuotaBar todayOutput={Math.round(FLOOR * pct)} />,
      );
      expect(container.querySelector(".bg-emerald-500")).toBeTruthy();
      expect(container.querySelector(".bg-amber-400")).toBeFalsy();
      expect(container.querySelector(".bg-red-500")).toBeFalsy();
      expect(container.querySelector(".text-emerald-400")).toBeTruthy();
      unmount();
    }
  });

  it("auto-scales past 100%: bar width = pct / scaleMax", () => {
    // 105% -> scaleMax=200 -> bar at 52.5%
    const { container } = render(<QuotaBar todayOutput={Math.round(FLOOR * 1.05)} />);
    const bar = container.querySelector(".bg-emerald-500") as HTMLElement;
    expect(parseFloat(bar.style.width)).toBeCloseTo(52.5, 0);
  });

  it("draws a tick mark at 100% when over quota", () => {
    // 150% -> scaleMax=200 -> 1 tick at left=50%
    const { container } = render(<QuotaBar todayOutput={Math.round(FLOOR * 1.5)} />);
    const ticks = container.querySelectorAll("[aria-hidden]");
    expect(ticks.length).toBe(1);
    expect((ticks[0] as HTMLElement).style.left).toBe("50%");
  });

  it("draws multiple tick marks for high multiples", () => {
    // 244% -> scaleMax=300 -> ticks at 100/300=33.33% and 200/300=66.67%
    const { container } = render(<QuotaBar todayOutput={Math.round(FLOOR * 2.44)} />);
    const ticks = container.querySelectorAll("[aria-hidden]");
    expect(ticks.length).toBe(2);
  });

  it("draws no internal ticks under 100%", () => {
    const { container } = render(<QuotaBar todayOutput={FLOOR / 2} />);
    expect(container.querySelectorAll("[aria-hidden]").length).toBe(0);
  });
});
