import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders one rect per data point", () => {
    const { container } = render(<Sparkline data={[1, 2, 3, 4, 5]} />);
    expect(container.querySelectorAll("rect").length).toBe(5);
  });

  it("emphasizes the last bar with a brighter fill", () => {
    const { container } = render(<Sparkline data={[1, 2, 3]} />);
    const rects = container.querySelectorAll("rect");
    const fills = Array.from(rects).map((r) => r.getAttribute("fill"));
    // First two share the muted fill; last is the bright one.
    expect(fills[0]).toBe(fills[1]);
    expect(fills[2]).not.toBe(fills[1]);
  });

  it("renders nothing for empty data", () => {
    const { container } = render(<Sparkline data={[]} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("scales bars to the max value (no zero-height bar for non-zero data)", () => {
    const { container } = render(<Sparkline data={[10, 0, 20]} height={20} />);
    const rects = container.querySelectorAll("rect");
    const heights = Array.from(rects).map((r) =>
      Number(r.getAttribute("height")),
    );
    // Bar at index 0 is 10/20 of full height; index 2 hits full; index 1 is 0.
    expect(heights[2]).toBeCloseTo(20);
    expect(heights[1]).toBe(0);
    expect(heights[0]).toBeGreaterThan(0);
  });
});
