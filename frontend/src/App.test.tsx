import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "./App";
import { CONFIG, mockFetch, ROWS } from "./testdata";

afterEach(() => vi.unstubAllGlobals());

describe("App shell", () => {
  it("shows the required disclaimer", () => {
    mockFetch({});
    render(<App />);
    const d = screen.getByRole("complementary", { name: "Disclaimer" });
    expect(d).toHaveTextContent("not a licensed insurance agent or broker");
    expect(d).toHaveTextContent("not affiliated with or endorsed by CMS, Medicare or any plan");
    expect(d).toHaveTextContent("It earns no commissions.");
    expect(d).toHaveTextContent("1-800-633-4227");
    expect(d).toHaveTextContent("1-877-839-2675");
  });
});

describe("consent → intake → compare (No-save)", () => {
  it("preselects No-save, names the provider, and keeps nothing in browser storage", async () => {
    const calls = mockFetch({
      "GET /api/config": CONFIG,
      "GET /api/session": { session: null },
      "POST /api/session": { session: { mode: "nosave", expires_at: "x", plan_year: 2027 } },
      "GET /api/location": {
        counties: [{ ssa_code: "03060", fips: "04013", state: "AZ", county: "Maricopa", res_ratio: 1 }],
        note: null,
      },
      "POST /api/compare": {
        canvas: { tab: "table", rows: ROWS, top: ["H0028_028_0"], notes: ["Part B is a placeholder."] },
        top: [],
        checklist: CONFIG.checklist,
        approximation_notes: [],
        data_vintage: "S1",
        recommendation_ids: [],
      },
    });
    render(<App />);
    const nosave = await screen.findByRole("radio", { name: /No-save/ });
    expect(nosave).toBeChecked();
    expect(screen.getByText(/Anthropic Claude \(claude-test\)/)).toBeInTheDocument();
    const start = screen.getByRole("button", { name: "Start" });
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /estimate tool/ }));
    fireEvent.click(start);
    expect(await screen.findByText("No-save", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End session & erase" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("ZIP code"), { target: { value: "85004" } });
    fireEvent.click(screen.getByRole("button", { name: "Find county" }));
    expect(await screen.findByText("County: Maricopa")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Dropped Plan C").closest("tr")).toHaveClass("dropped");
    expect(screen.getByRole("article", { name: /Rank 1: Test Plan A/ })).toBeInTheDocument();

    const post = calls.find((c) => c.key === "POST /api/compare");
    expect((post?.body as { profile: { zip: string } }).profile.zip).toBe("85004");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("NS5: preselects No-save even when the config says Saved is the default", async () => {
    // A forged or misconfigured /api/config must not preselect Saved (DESIGN v0.5 B2.3 G3).
    mockFetch({
      "GET /api/config": { ...CONFIG, default_mode: "saved", modes: ["nosave", "saved"] },
      "GET /api/session": { session: null },
    });
    render(<App />);
    expect(await screen.findByRole("radio", { name: /No-save/ })).toBeChecked();
    const saved = screen.getByRole("radio", { name: /Save for 30 days/ });
    expect(saved).toBeEnabled();
    expect(saved).not.toBeChecked();
  });

  it("NS6: Start without touching the radio creates a No-save session", async () => {
    const calls = mockFetch({
      "GET /api/config": { ...CONFIG, default_mode: "saved" },
      "GET /api/session": { session: null },
      "POST /api/session": { session: { mode: "nosave", expires_at: "x", plan_year: 2027 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /estimate tool/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByText("No-save", { selector: ".badge" })).toBeInTheDocument();
    const post = calls.find((c) => c.key === "POST /api/session");
    expect((post?.body as { mode: string }).mode).toBe("nosave");
  });

  it("offers only No-save when Saved mode is unavailable", async () => {
    mockFetch({ "GET /api/config": { ...CONFIG, modes: ["nosave"] }, "GET /api/session": { session: null } });
    render(<App />);
    expect(await screen.findByRole("radio", { name: /Save for 30 days/ })).toBeDisabled();
  });

  it("tells the user when an old No-save session was renewed", async () => {
    mockFetch({
      "GET /api/config": CONFIG,
      "GET /api/session": {
        session: { mode: "nosave", expires_at: "x", plan_year: 2027 },
        renewed: true,
        profile: null,
        chat: [],
        canvas: {},
      },
    });
    render(<App />);
    expect(await screen.findByText(/earlier No-save session ended/)).toBeInTheDocument();
  });

  it("shows the no-LLM notice and keeps the form when the assistant is off", async () => {
    mockFetch({
      "GET /api/config": { ...CONFIG, llm_enabled: false, llm_provider_label: null },
      "GET /api/session": {
        session: { mode: "saved", expires_at: "x", plan_year: 2027 },
        chat: [],
        canvas: {},
      },
    });
    render(<App />);
    expect(await screen.findByText(/assistant is off right now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare plans" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete my data" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeDisabled());
  });
});
