import { fireEvent, render, screen } from "@testing-library/react";
import { FeedbackDialog, ModeContext, TEAM_NOTICE } from "./Feedback";
import { mockFetch } from "./testdata";

afterEach(() => vi.unstubAllGlobals());

describe("feedback", () => {
  it("No-save: the team form shows the storage notice and sends to_team", async () => {
    const calls = mockFetch({ "POST /api/feedback": { stored: "message", linked: false } });
    render(
      <ModeContext.Provider value="nosave">
        <FeedbackDialog onClose={() => {}} lastToolCalls={[]} />
      </ModeContext.Provider>,
    );
    expect(screen.getByRole("dialog", { name: "Send a message to the team" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(TEAM_NOTICE);
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "The chart is great" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/Your message was sent/)).toBeInTheDocument();
    expect(calls[0].body).toMatchObject({ kind: "general", to_team: true, include_details: false });
  });

  it("Saved: offers the include-details opt-in instead", () => {
    mockFetch({});
    render(
      <ModeContext.Provider value="saved">
        <FeedbackDialog onClose={() => {}} lastToolCalls={[]} />
      </ModeContext.Provider>,
    );
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByRole("checkbox", { name: /Include my details/ })).not.toBeChecked();
  });
});
