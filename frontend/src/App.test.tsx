import { render, screen } from "@testing-library/react";
import { App } from "./App";

describe("App shell", () => {
  it("shows the required disclaimer", () => {
    render(<App />);
    const d = screen.getByRole("complementary", { name: "Disclaimer" });
    expect(d).toHaveTextContent("not a licensed insurance agent or broker");
    expect(d).toHaveTextContent("not affiliated with or endorsed by CMS, Medicare or any plan");
    expect(d).toHaveTextContent("It earns no commissions.");
    expect(d).toHaveTextContent("1-800-633-4227");
    expect(d).toHaveTextContent("1-877-839-2675");
  });
});
