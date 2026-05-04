import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { GroupByToggle } from "./GroupByToggle";

describe("GroupByToggle", () => {
  it("marks the current value as selected", () => {
    render(<GroupByToggle value="session" onChange={() => {}} />);
    expect(screen.getByRole("tab", { name: "Session" })).toHaveAttribute(
      "aria-selected", "true",
    );
    expect(screen.getByRole("tab", { name: "Topic" })).toHaveAttribute(
      "aria-selected", "false",
    );
  });

  it("invokes onChange with the clicked value", () => {
    const onChange = vi.fn();
    render(<GroupByToggle value="topic" onChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: "Project" }));
    expect(onChange).toHaveBeenCalledWith("project");
  });
});
