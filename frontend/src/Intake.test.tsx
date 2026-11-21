import { fireEvent, render, screen } from "@testing-library/react";
import { emptyProfile } from "./api";
import { Intake } from "./Intake";
import { mockFetch } from "./testdata";

afterEach(() => vi.unstubAllGlobals());

function setup() {
  const onSubmit = vi.fn();
  const profile = {
    ...emptyProfile(),
    zip: "85004",
    county_ssa: "03060",
    county_name: "Maricopa",
    state: "AZ",
  };
  render(<Intake profile={profile} maxDrugs={30} maxProviders={15} busy={false} onSubmit={onSubmit} />);
  return onSubmit;
}

const rxInput = () => screen.getByLabelText("RxCUI");
const addByRx = () => screen.getByRole("button", { name: "Add by RxCUI" });

describe("intake: add a drug by RxCUI (QA #2)", () => {
  it("works with only an RxCUI (offline path) and labels the drug with it", () => {
    const onSubmit = setup();
    fireEvent.change(rxInput(), { target: { value: "197361" } });
    expect(addByRx()).toBeEnabled();
    fireEvent.click(addByRx());
    expect(screen.getByText("RxCUI 197361")).toBeInTheDocument();
    expect(rxInput()).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    expect(onSubmit.mock.calls[0][0].drugs[0]).toMatchObject({ rxcui: "197361", name: "RxCUI 197361" });
  });

  it("uses the typed drug name as the label when there is one", () => {
    setup();
    fireEvent.change(screen.getByLabelText("Drug name"), { target: { value: "amlodipine 5 mg" } });
    fireEvent.change(rxInput(), { target: { value: "197361" } });
    fireEvent.click(addByRx());
    expect(screen.getByText("amlodipine 5 mg")).toBeInTheDocument();
  });

  it("explains bad input instead of doing nothing", () => {
    setup();
    expect(addByRx()).toBeDisabled();
    fireEvent.change(rxInput(), { target: { value: "metformin" } });
    fireEvent.click(addByRx());
    expect(screen.getByRole("alert")).toHaveTextContent(/RxCUI is a number/);
    fireEvent.change(rxInput(), { target: { value: "12345678901" } });
    fireEvent.click(addByRx());
    expect(screen.getByRole("alert")).toHaveTextContent(/1 to 10 digits/);
    expect(screen.queryByText(/^RxCUI \d/)).toBeNull();
  });

  it("does not add the same RxCUI twice", () => {
    setup();
    for (let i = 0; i < 2; i++) {
      fireEvent.change(rxInput(), { target: { value: "197361" } });
      fireEvent.click(addByRx());
    }
    expect(screen.getAllByText("RxCUI 197361")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent(/already on your list/);
  });
});

// Thomas's ml3090 report 2026-11-19: "The drugs search has no response" for "tamsulosin 0.4 mg capsule".
describe("intake: drug search always answers", () => {
  const drugName = () => screen.getByLabelText("Drug name");
  const status = () => screen.getByRole("status", { name: "Drug search status" });
  const CAPSULE = { rxcui: "863669", name: "tamsulosin hydrochloride 0.4 MG Oral Capsule", tty: "SCD" };

  it("full string: shows the fallback note and the 863669 capsule first", async () => {
    const calls = mockFetch({
      "GET /api/drugs": { candidates: [CAPSULE], matched_as: "tamsulosin", how: "ingredient" },
    });
    setup();
    fireEvent.change(drugName(), { target: { value: "tamsulosin 0.4 mg capsule" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const list = await screen.findByRole("list", { name: "Drug matches" });
    expect(list.querySelector("button")).toHaveTextContent(
      "Add tamsulosin hydrochloride 0.4 MG Oral Capsule",
    );
    expect(status()).toHaveTextContent(/No exact match for “tamsulosin 0.4 mg capsule”.*“tamsulosin”/);
    expect(calls[0].key).toBe("GET /api/drugs");
  });

  it("partial name with Enter searches instead of submitting the form", async () => {
    let url = "";
    mockFetch({
      "GET /api/drugs": (u: string) => {
        url = u;
        return { candidates: [CAPSULE], matched_as: null, how: "exact" };
      },
    });
    const onSubmit = setup();
    fireEvent.change(drugName(), { target: { value: "tamsulosin" } });
    fireEvent.keyDown(drugName(), { key: "Enter" });
    expect(await screen.findByText(/1 match\(es\) for “tamsulosin”/)).toBeInTheDocument();
    expect(url).toContain("q=tamsulosin");
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Add tamsulosin/ }));
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    expect(onSubmit.mock.calls[0][0].drugs[0]).toMatchObject({ rxcui: "863669" });
  });

  it("says so when nothing is found", async () => {
    mockFetch({ "GET /api/drugs": { candidates: [], matched_as: null, how: "none" } });
    setup();
    fireEvent.change(drugName(), { target: { value: "zzqx" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/No drugs found for “zzqx”/)).toBeInTheDocument();
  });

  it("shows the server's error (e.g. no internet to RxNav) with the RxCUI hint", async () => {
    mockFetch({
      "GET /api/drugs": new Response(
        JSON.stringify({ detail: { code: "lookup_failed", message: "Drug search is unavailable." } }),
        { status: 503 },
      ),
    });
    setup();
    fireEvent.change(drugName(), { target: { value: "tamsulosin" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable.*RxCUI instead/);
  });

  it("shows Searching… while the request is in flight", async () => {
    let release: (v: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((r) => (release = r))),
    );
    setup();
    fireEvent.change(drugName(), { target: { value: "tamsulosin" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("button", { name: "Searching…" })).toBeDisabled();
    expect(status()).toHaveTextContent("Searching for “tamsulosin”…");
    release(new Response(JSON.stringify({ candidates: [], how: "none" }), { status: 200 }));
    expect(await screen.findByText(/No drugs found/)).toBeInTheDocument();
  });

  it("asks for 2+ letters instead of ignoring the click", () => {
    setup();
    fireEvent.change(drugName(), { target: { value: "t" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least 2 letters/);
  });
});

describe("intake: Medigap assumption for the standard option (WP11)", () => {
  it("sends the plan and the quote in cents; no quote until one is typed", () => {
    const onSubmit = setup();
    fireEvent.change(screen.getByLabelText("Medigap policy"), { target: { value: "G" } });
    expect(screen.getByText(/premium isn’t included until you enter a quote/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    expect(onSubmit.mock.calls[0][0].medigap).toEqual({ plan: "G", monthly_premium_cents: null });
    fireEvent.change(screen.getByLabelText("Medigap monthly premium quote"), { target: { value: "145.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    expect(onSubmit.mock.calls[1][0].medigap).toEqual({ plan: "G", monthly_premium_cents: 14550 });
    fireEvent.change(screen.getByLabelText("Medigap policy"), { target: { value: "" } });
    expect(screen.queryByLabelText("Medigap monthly premium quote")).not.toBeInTheDocument();
  });
});

describe("intake: dental must-haves (WP12)", () => {
  it("sends dental and the minimum yearly maximum in cents", () => {
    const onSubmit = setup();
    fireEvent.click(screen.getByLabelText(/Only plans that include dental/));
    fireEvent.change(screen.getByLabelText("Minimum dental yearly maximum"), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    expect(onSubmit.mock.calls[0][0].must_haves).toMatchObject({
      dental: true,
      dental_min_max_cents: 100000,
    });
  });
});

describe("intake: doctors from the NPI registry (WP13)", () => {
  it("searches by name + the county's state, adds the pick with its NPI and must-keep", async () => {
    const calls = mockFetch({
      "GET /api/providers": {
        candidates: [
          {
            npi: "1234567893",
            name: "Ana Test",
            specialty: "Internal Medicine",
            city: "PHOENIX",
            state: "AZ",
          },
        ],
        note: "",
      },
    });
    const onSubmit = setup();
    fireEvent.change(screen.getByLabelText("Doctor last name"), { target: { value: "Test" } });
    fireEvent.change(screen.getByLabelText("Doctor first name"), { target: { value: "Ana" } });
    fireEvent.keyDown(screen.getByLabelText("Doctor last name"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: /Add Ana Test, Internal Medicine, PHOENIX/ }));
    expect(onSubmit).not.toHaveBeenCalled(); // Enter searched, it didn't submit the form
    fireEvent.click(screen.getByLabelText("Must keep Ana Test"));
    fireEvent.click(screen.getByLabelText(/Only plans whose directory lists all my must-keep doctors/));
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    const sent = onSubmit.mock.calls[0][0];
    expect(sent.providers).toEqual([
      {
        must_keep: true,
        name: "Ana Test",
        npi: "1234567893",
        specialty: "Internal Medicine",
        city: "PHOENIX",
      },
    ]);
    expect(sent.must_haves.doctors_listed).toBe(true);
    expect(calls[0].key).toBe("GET /api/providers");
  });

  it("offers adding the typed name without checking when nothing is found", async () => {
    mockFetch({ "GET /api/providers": { candidates: [], note: "" } });
    const onSubmit = setup();
    fireEvent.change(screen.getByLabelText("Doctor last name"), { target: { value: "Nobody" } });
    fireEvent.click(screen.getByRole("button", { name: "Find doctor" }));
    expect(await screen.findByText(/No doctor found/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add “Nobody” without checking" }));
    expect(screen.getByText("not checked")).toBeInTheDocument();
    expect(screen.queryByLabelText("Must keep Nobody")).not.toBeInTheDocument(); // no NPI, nothing to check
    fireEvent.click(screen.getByRole("button", { name: "Compare plans" }));
    expect(onSubmit.mock.calls[0][0].providers).toEqual([{ must_keep: false, name: "Nobody" }]);
  });
});
