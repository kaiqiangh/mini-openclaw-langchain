import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { Input, Select, TabButton, TabsList } from "@/components/ui/primitives";

function TabsHarness() {
  const [value, setValue] = useState("one");

  return (
    <>
      <TabsList
        ariaLabel="Harness tabs"
        value={value}
        onChange={setValue}
        className="grid-cols-3"
      >
        <TabButton id="tab-one" controls="panel-one" value="one">
          One
        </TabButton>
        <TabButton id="tab-two" controls="panel-two" value="two">
          Two
        </TabButton>
        <TabButton id="tab-three" controls="panel-three" value="three">
          Three
        </TabButton>
      </TabsList>
      <div id="panel-one" role="tabpanel" aria-labelledby="tab-one" hidden={value !== "one"} />
      <div id="panel-two" role="tabpanel" aria-labelledby="tab-two" hidden={value !== "two"} />
      <div id="panel-three" role="tabpanel" aria-labelledby="tab-three" hidden={value !== "three"} />
    </>
  );
}

describe("ui primitives", () => {
  it("supports controlled tabs semantics and keyboard navigation", () => {
    render(<TabsHarness />);

    const tablist = screen.getByRole("tablist", { name: "Harness tabs" });
    const tabOne = screen.getByRole("tab", { name: "One" });
    const tabTwo = screen.getByRole("tab", { name: "Two" });

    expect(tablist).toBeInTheDocument();
    expect(tabOne).toHaveAttribute("aria-selected", "true");
    expect(tabTwo).toHaveAttribute("aria-selected", "false");

    tabOne.focus();
    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    expect(tabTwo).toHaveAttribute("aria-selected", "true");
    expect(tabTwo).toHaveFocus();
  });

  it("binds described-by and invalid state for form fields", () => {
    render(
      <>
        <span id="input-hint">hint</span>
        <span id="input-error">error</span>
        <Input invalid hintId="input-hint" errorId="input-error" />
        <span id="select-hint">hint</span>
        <Select hintId="select-hint" />
      </>,
    );

    const input = screen.getByRole("textbox");
    const select = screen.getByRole("combobox");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "input-hint input-error");
    expect(select).toHaveAttribute("aria-describedby", "select-hint");
    expect(select).not.toHaveAttribute("aria-invalid");
  });
});
