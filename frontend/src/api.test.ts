import { parseSse } from "./api";

describe("SSE parser", () => {
  it("splits complete events and keeps the tail", () => {
    const { events, rest } = parseSse(
      'event: meta\ndata: {"a":1}\n\nevent: delta\ndata: {"text":"hi"}\n\nevent: do',
    );
    expect(events).toEqual([
      { event: "meta", data: '{"a":1}' },
      { event: "delta", data: '{"text":"hi"}' },
    ]);
    expect(rest).toBe("event: do");
  });
});
