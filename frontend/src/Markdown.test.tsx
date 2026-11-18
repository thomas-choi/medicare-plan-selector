import { render } from "@testing-library/react";
import { allowedLink, Markdown } from "./Markdown";

describe("safe markdown", () => {
  it("never renders raw HTML", () => {
    const { container } = render(
      <Markdown text={'<img src=x onerror="alert(1)"> <script>alert(1)</script> **bold**'} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });

  it("links only to the allowlist", () => {
    const { container } = render(
      <Markdown
        text={
          "See [Plan Finder](https://www.medicare.gov/plan-compare/) or [evil](https://evil.example/x) or [js](javascript:alert(1))"
        }
      />,
    );
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://www.medicare.gov/plan-compare/"]);
    expect(container.textContent).toContain("evil");
  });

  it("allowlist helper", () => {
    expect(allowedLink("https://www.shiphelp.org/x")).toBe(true);
    expect(allowedLink("https://cms.gov")).toBe(true);
    expect(allowedLink("http://medicare.gov")).toBe(false);
    expect(allowedLink("https://medicare.gov.evil.com")).toBe(false);
  });

  it("renders lists", () => {
    const { container } = render(<Markdown text={"Top plans:\n- one\n- two"} />);
    expect(container.querySelectorAll("li")).toHaveLength(2);
  });
});
