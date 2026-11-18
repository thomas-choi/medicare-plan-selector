import { render, screen } from "@testing-library/react";
import { Admin } from "./Admin";
import { mockFetch } from "./testdata";

afterEach(() => vi.unstubAllGlobals());

describe("admin page", () => {
  it("lists redacted feedback and the summary", async () => {
    mockFetch({
      "GET /api/admin/feedback": {
        items: [
          {
            id: 7,
            created_at: "2026-11-17",
            kind: "general",
            mode: "nosave",
            linked: false,
            rating: null,
            thumbs: null,
            chosen_plan_key: null,
            text_redacted: "my [drug] is pricey",
            prompt_version: "v1",
            model_id: "fake",
            triage_status: "new",
          },
        ],
      },
      "GET /api/admin/summary": { thumbs: { up: 3, down: 1, up_rate: 0.75 }, outcomes: {}, llm_usage: [] },
    });
    render(<Admin />);
    expect(await screen.findByText("my [drug] is pricey")).toBeInTheDocument();
    expect(screen.getByText(/75% helpful/)).toBeInTheDocument();
    expect(screen.getByText(/\(unlinked\)/)).toBeInTheDocument();
  });

  it("explains when the gate is missing", async () => {
    mockFetch({});
    render(<Admin />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/admin gate/);
  });
});
