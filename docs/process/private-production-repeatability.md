# Private production repeatability

**Proven.** A second four-board production used the installed package workflow.
The producer verified the stock inputs, synthesized voices, ran the leased Wan
service phase and assembled the picture offline on the render worker. The
create-only archive held a master and a phone proxy. An independent reader
matched both files by byte count and SHA-256 and decoded all 301 frames at
24 fps in each. Both files passed the sound and frame checks. The full-film
transcript passed with one documented hesitation tolerance. The affected take
matched exactly in isolation. See the authenticated
[archive verification and run measurements](https://work.haynesnetwork.com/work_packages/991/activity#comment-10695).

From worker dispatch to independent archive readback, the second production
took 35m 45s (session creation at 21:51:33 to readback at 22:27:18 UTC) and the
[first production](https://work.haynesnetwork.com/work_packages/990/activity#comment-10682)
took 49m 07s (worker start at 21:00:58 to readback at 21:50:05 UTC). The second
cut was shorter. Its worker kickoff to readback took 32m 37s, and its first
versioned brief to readback took 30m 42s. The first production's brief start
time was unrecorded.
Four serial Wan submissions, including one lettering quality retry, took
13.214 engine minutes and 97 seconds at the cooldown gates. The replacement
passed the original lettering floor at the length that had worked in the first
production. The full picture assembly took 89 seconds. Final encode and
verification took 10 seconds.

One offline attempt stopped because a transferred cache file retained an extra
hard link. The producer preserved the source and destination bytes and verified
them again as separate files. Use independent copies with the original file
modes when transferring a store, as its publish checks require.

The owner received an owner-only link to the verified phone proxy on the
private phone thread. Human handset playback, listening and creative review
are pending.
See the authenticated [delivery receipt](https://work.haynesnetwork.com/work_packages/991/activity#comment-10697),
[offline workflow](manual-short-poc.md#package-builds-on-the-cpu-worker) and
[build phases](../reference/studio-build.md#phases).
