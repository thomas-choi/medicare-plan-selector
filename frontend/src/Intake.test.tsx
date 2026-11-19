import { fireEvent, render, screen } from "@testing-library/react";
import { emptyProfile } from "./api";
import { Intake } from "./Intake";

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
