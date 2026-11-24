# Example frontier staging work order

This example is for one sanctioned dev-env staging session. The coordinator
fills in the bracketed values before dispatch. The original fixture premise is
[The Office of Lost Tuesdays](../../tests/drafting/fixtures/brief.md).

1. **Scope.** Draft three boards for the prepared story `<story-id>` in
   `<production-id>` on staging. Read the supplied brief and pinned set, cast
   and layouts. Write original dialogue, short direction notes and executable
   cues from that brief. Use the [draft schema and apply procedure](agent-drafting.md).
2. **Acceptance evidence.** Return the private draft path and SHA-256, the
   receipt path, the board IDs and each apply result. Leave the boards in
   Studio for creative review.
3. **Dependencies.** The coordinator supplies `STUDIO_MCP_URL`, the mounted key
   file path and its non-secret key ID, the approved frontier session, a private
   job directory and the exact two IDs above. The key grants `read` and
   `draft:write` for `<production-id>` only. Confirm that the story and pins match.
4. **Ownership.** The session owns this draft and its conditional apply through
   MCP. Any key or grant changes, media bytes, generation jobs, Build, approval,
   publication and edits to other productions are outside this assignment.
5. **Budget.** One draft and one apply, maximum 20 minutes, at most two CPU
   threads, zero GPU, zero metered API calls. Declare the model and session ID
   in the draft. Record input/output tokens and USD cost from the session when
   known. Use JSON null for any unknown number.
6. **Handoff.** Report the draft and receipt locators and hash, known usage,
   elapsed time, applied and conflicting board IDs, and anything unconfirmed.
   Keep the key and creative artifacts on the private path.
7. **Stop.** Finish after the receipt or report the exact denial, stale
   revision, ambiguous outcome or cap. Leave conflicts for the coordinator.
   Any further creative pass gets a new draft and the previous receipt.
