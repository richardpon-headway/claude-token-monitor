import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QuotaBar } from "./QuotaBar";

const FLOOR = 233_333;

describe("QuotaBar", () => {
  it("renders the percentage rounded to a whole number", () => {
    render(<QuotaBar todayOutput={Math.round(FLOOR * 0.5)} />);
    expect(screen.getByText(/\(50%\)/)).toBeInTheDocument();
  });

  it("uses emerald color under 80%", () => {
    const { container } = render(<QuotaBar todayOutput={100_000} />); // ~43%
    expect(container.querySelector(".bg-emerald-500")).toBeTruthy();
    expect(container.querySelector(".bg-amber-400")).toBeFalsy();
    expect(container.querySelector(".bg-red-500")).toBeFalsy();
  });

  it("uses amber color between 80% and 100%", () => {
    const { container } = render(<QuotaBar todayOutput={Math.round(FLOOR * 0.9)} />);
    expect(container.querySelector(".bg-amber-400")).toBeTruthy();
    expect(container.querySelector(".bg-emerald-500")).toBeFalsy();
  });

  it("uses red color and shows over-100 indicator above floor", () => {
    const { container } = render(<QuotaBar todayOutput={Math.round(FLOOR * 1.5)} />);
    expect(container.querySelector(".bg-red-500")).toBeTruthy();
    // overflow strip uses red-500/40
    expect(container.querySelector(".bg-red-500\\/40")).toBeTruthy();
  });

  it("clamps the bar at 100% width even when over quota", () => {
    const { container } = render(<QuotaBar todayOutput={FLOOR * 5} />);
    const bar = container.querySelector(".bg-red-500") as HTMLElement;
    expect(bar.style.width).toBe("100%");
  });
});
