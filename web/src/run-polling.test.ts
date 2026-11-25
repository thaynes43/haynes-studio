import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { pollInterval, pollRuns } from "./run-polling";

class Visibility extends EventTarget {
  visibilityState: DocumentVisibilityState = "visible";

  change(state: DocumentVisibilityState) {
    this.visibilityState = state;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

describe("run polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads immediately, polls active runs and stops once terminal", async () => {
    const read = vi.fn<() => Promise<boolean>>().mockResolvedValueOnce(true).mockResolvedValue(false);
    const onData = vi.fn((active: boolean) => active);
    const poll = pollRuns(new Visibility(), { read, onData, onError: () => true });

    await vi.advanceTimersByTimeAsync(pollInterval - 1);
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(onData.mock.calls).toEqual([[true], [false]]);
    await vi.advanceTimersByTimeAsync(pollInterval * 5);
    expect(read).toHaveBeenCalledTimes(2);

    poll.refresh();
    expect(read).toHaveBeenCalledTimes(3);
    poll.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("aborts a hidden tab and ignores its late read after visibility resumes", async () => {
    const visibility = new Visibility();
    visibility.change("hidden");
    let finish!: (data: string) => void;
    const read = vi.fn<(signal: AbortSignal) => Promise<string>>()
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue("new");
    const onData = vi.fn(() => true);
    const poll = pollRuns(visibility, { read, onData, onError: () => true });

    expect(read).not.toHaveBeenCalled();
    visibility.change("visible");
    const [signal] = read.mock.calls[0];
    visibility.change("hidden");
    expect(signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(pollInterval * 3);
    expect(read).toHaveBeenCalledTimes(1);

    visibility.change("visible");
    finish("old");
    await vi.advanceTimersByTimeAsync(0);
    expect(read).toHaveBeenCalledTimes(2);
    expect(onData.mock.calls).toEqual([["new"]]);
    poll.stop();
    await vi.advanceTimersByTimeAsync(pollInterval * 2);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("backs off from read errors, resets on success and stops on a refusal", async () => {
    const visibility = new Visibility();
    const loss = new Error("connection lost");
    const refusal = new Error("forbidden");
    const read = vi.fn<() => Promise<boolean>>()
      .mockRejectedValueOnce(loss).mockRejectedValueOnce(loss)
      .mockResolvedValueOnce(true).mockRejectedValueOnce(loss).mockRejectedValue(refusal);
    const onError = vi.fn((error) => error === loss);
    const poll = pollRuns(visibility, { read, onData: (active) => active, onError });

    await vi.advanceTimersByTimeAsync(2 * pollInterval - 1);
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4 * pollInterval - 1);
    expect(read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1 + pollInterval);
    expect(read).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(2 * pollInterval);
    expect(read).toHaveBeenCalledTimes(5);
    expect(onError.mock.calls).toEqual([[loss], [loss], [loss], [refusal]]);
    visibility.change("hidden");
    visibility.change("visible");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(read).toHaveBeenCalledTimes(5);
    poll.stop();
  });
});
