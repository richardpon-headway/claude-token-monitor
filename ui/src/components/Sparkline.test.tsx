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

  it("scales bar heights to the max value within the viewBox coordinate system", () => {
    const { container } = render(<Sparkline data={[10, 0, 20]} />);
    const rects = container.querySelectorAll("rect");
    const heights = Array.from(rects).map((r) =>
      Number(r.getAttribute("height")),
    );
    // viewBox height is 100; max value (20) hits 100; half (10) hits ~50; 0 stays 0.
    expect(heights[2]).toBeCloseTo(100);
    expect(heights[0]).toBeCloseTo(50);
    expect(heights[1]).toBe(0);
  });

  it("forwards className to the SVG so callers can position it", () => {
    const { container } = render(
      <Sparkline data={[1, 2]} className="absolute inset-0" />,
    );
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("class")).toContain("absolute");
  });

  it("cumulative mode renders an area path instead of rects", () => {
    const { container } = render(
      <Sparkline data={[10, 10, 10]} mode="cumulative" />,
    );
    expect(container.querySelectorAll("rect").length).toBe(0);
    expect(container.querySelectorAll("path").length).toBe(2); // area + line
  });

  it("draws quota reference lines at integer multiples within the y-range", () => {
    // max value 250, quota 100 -> lines at 100 and 200 (within [0, 250])
    const { container } = render(<Sparkline data={[250]} quota={100} />);
    expect(container.querySelectorAll("line").length).toBe(2);
  });

  it("caps quota lines at 8 to avoid stripe clutter", () => {
    // max value 1000, quota 1 -> would naively draw 1000 lines
    const { container } = render(<Sparkline data={[1000]} quota={1} />);
    expect(container.querySelectorAll("line").length).toBe(8);
  });
});
