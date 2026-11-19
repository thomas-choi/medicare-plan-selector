import { render } from "@testing-library/react";
import indexHtml from "../index.html?raw";
import { App } from "./App";
import { mockFetch } from "./testdata";

afterEach(() => vi.unstubAllGlobals());

// QA #4 saw "🐴 Medicare Plan Selector" in the browser tab. The page never sets an emoji: these tests pin the
// title to plain text (the prefix most likely came from the QA browser automation marking its tab).
describe("document title", () => {
  it("index.html has a plain-text title", () => {
    const m = indexHtml.match(/<title>([^<]*)<\/title>/);
    expect(m?.[1]).toBe("Medicare Plan Selector");
    expect(/^[\x20-\x7e]*$/.test(m?.[1] ?? "")).toBe(true);
  });

  it("the app does not change the title", () => {
    mockFetch({});
    document.title = "Medicare Plan Selector";
    render(<App />);
    expect(document.title).toBe("Medicare Plan Selector");
  });
});
