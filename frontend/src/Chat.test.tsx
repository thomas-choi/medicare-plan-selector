import { render, screen } from "@testing-library/react";
import { Chat, EMPTY_REPLY } from "./Chat";

const noop = () => {};

describe("chat", () => {
  it("shows a notice instead of an endless pending '…' for a finished empty reply (QA #7)", () => {
    render(
      <Chat
        history={[
          { role: "user", content: "Explain H0028_028_0" },
          { role: "assistant", content: "", citations: [{ source: "CMS PBP", vintage: "2027" }] },
        ]}
        enabled
        maxChars={2000}
        onCanvas={noop}
        onProfile={noop}
        onLimit={noop}
      />,
    );
    expect(screen.getByText(EMPTY_REPLY)).toBeInTheDocument();
    expect(screen.queryByText("…")).not.toBeInTheDocument();
  });
});
